"""
FastAPI server for the YouTube Auto Clipper pipeline.
n8n calls these endpoints to orchestrate the workflow.
"""

import os
import threading
import traceback
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import OUTPUT_DIR, API_SECRET, CHANNEL_IDS, DB_PATH
from downloader import check_new_videos, mark_processed, get_latest_video_from_channel, load_processed
from main import process_video

app = FastAPI(title="YouTube Auto Clipper API")

# ── Auth ────────────────────────────────────────────────────
async def verify_auth(authorization: str = Header(None)):
    if API_SECRET:
        if not authorization or authorization != f"Bearer {API_SECRET}":
            raise HTTPException(401, "Unauthorized")


# ── Job tracking (async pattern for long processing) ────────
jobs: dict[str, dict] = {}


class ProcessRequest(BaseModel):
    url: str
    title: str = "Video"


def _run_job(job_id: str, url: str, title: str):
    """Background worker that runs the pipeline and updates job status."""

    def progress_callback(percent: int, step: str):
        """Update job progress."""
        jobs[job_id]["progress"] = percent
        jobs[job_id]["current_step"] = step

    try:
        result = process_video(url, title, progress_callback=progress_callback)
        clips = []
        for i, file_path in enumerate(result["files"]):
            meta = result["clips_metadata"][i] if i < len(result["clips_metadata"]) else {}
            clips.append({
                "filename": file_path.name,
                "download_url": f"/download/{file_path.name}",
                "title": meta.get("title", f"Clip {i+1}"),
                "description": meta.get("description", ""),
                "tags": meta.get("tags", []),
                "hook": meta.get("hook", ""),
            })
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["current_step"] = "Done!"
        jobs[job_id]["clips"] = clips
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        print(f"[JOB {job_id}] FAILED: {e}")
        traceback.print_exc()


# ── Endpoints ───────────────────────────────────────────────

from fastapi.responses import FileResponse, HTMLResponse

# ... (rest of imports)

@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html>
        <head>
            <title>YouTube Auto Clipper API</title>
            <style>
                body { font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; line-height: 1.6; }
                h1 { color: #2d3748; }
                code { background: #f7fafc; padding: 2px 5px; border-radius: 3px; font-family: monospace; }
                pre { background: #f7fafc; padding: 15px; border-radius: 5px; overflow-x: auto; }
            </style>
        </head>
        <body>
            <h1>🎥 YouTube Auto Clipper API</h1>
            <p>This API automates the creation of YouTube Shorts/TikToks from long-form videos using Gemini AI.</p>
            
            <h2>How to use:</h2>
            <ol>
                <li><strong>Configure Secrets:</strong> Set <code>GEMINI_API_KEY</code>, <code>CHANNEL_IDS</code>, and optionally <code>API_SECRET</code> in your Space settings.</li>
                <li><strong>Trigger a Job:</strong> Send a POST request to <code>/process-video</code> with the video URL.</li>
                <li><strong>Poll Status:</strong> Check <code>/job/{job_id}</code> until completed.</li>
                <li><strong>Download:</strong> Use the returned download URLs.</li>
            </ol>
            
            <h3>Endpoints:</h3>
            <ul>
                <li><code>GET /debug</code> - Check configuration and health</li>
                <li><code>GET /check-channels</code> - List new videos from monitored channels</li>
                <li><code>POST /process-video</code> - Start processing (JSON body: <code>{"url": "..."}</code>)</li>
            </ul>
        </body>
    </html>
    """


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/debug")
async def debug():
    """Debug endpoint — shows config, channels, processed videos, and tests one RSS feed."""
    processed = load_processed()

    # Test first channel with error capture
    test_result = None
    test_error = None
    if CHANNEL_IDS:
        try:
            test_result = get_latest_video_from_channel(CHANNEL_IDS[0])
        except Exception as e:
            test_error = str(e)

    # Also try a raw yt-dlp test to see the actual error
    ytdlp_test = None
    if CHANNEL_IDS:
        try:
            import subprocess
            cmd = [
                "yt-dlp",
                "--flat-playlist",
                "--playlist-items", "1",
                "--print", "%(id)s|||%(title)s",
                "--extractor-args", "youtube:player_client=web",
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                f"https://www.youtube.com/channel/{CHANNEL_IDS[0]}/videos",
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            ytdlp_test = {
                "returncode": r.returncode,
                "stdout": r.stdout[:500],
                "stderr": r.stderr[:500],
            }
        except Exception as e:
            ytdlp_test = {"error": str(e)}

    return {
        "channels_configured": len(CHANNEL_IDS),
        "channel_ids": CHANNEL_IDS,
        "processed_count": len(processed),
        "processed_ids": processed[-10:],
        "db_path": str(DB_PATH),
        "db_exists": DB_PATH.exists(),
        "test_first_channel": test_result,
        "test_error": test_error,
        "ytdlp_raw_test": ytdlp_test,
    }


@app.get("/check-channels", dependencies=[Depends(verify_auth)])
async def check_channels():
    """Return list of new (unprocessed) videos from monitored channels."""
    new_videos = check_new_videos()
    return {"videos": new_videos}


@app.post("/process-video", dependencies=[Depends(verify_auth)])
async def start_processing(req: ProcessRequest):
    """Start processing a video. Returns a job_id to poll for completion."""
    # Validate URL is not empty
    if not req.url or not req.url.strip():
        raise HTTPException(400, "URL is required and cannot be empty")

    if not req.url.startswith("http"):
        raise HTTPException(400, f"Invalid URL format: {req.url}")

    # Check if another job is already running
    running = [j for j in jobs.values() if j["status"] == "processing"]
    if running:
        raise HTTPException(409, "Another job is already running. Wait for it to finish.")

    job_id = str(uuid.uuid4())[:8]
    
    # Simple cleanup of old jobs to prevent memory growth
    if len(jobs) > 20:
        oldest_job = next(iter(jobs))
        del jobs[oldest_job]

    jobs[job_id] = {
        "status": "processing",
        "progress": 0,
        "current_step": "Starting...",
        "clips": [],
        "error": None
    }

    thread = threading.Thread(target=_run_job, args=(job_id, req.url.strip(), req.title.strip()), daemon=True)
    thread.start()

    return {"job_id": job_id, "status": "processing", "progress": 0}


@app.get("/job/{job_id}", dependencies=[Depends(verify_auth)])
async def get_job(job_id: str):
    """Poll job status. Returns clips when completed."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return jobs[job_id]


@app.post("/mark-processed", dependencies=[Depends(verify_auth)])
async def mark_video_processed(video_id: str):
    """Mark a video as processed so it won't be picked up again."""
    mark_processed(video_id)
    return {"status": "ok"}


@app.get("/download/{filename}", dependencies=[Depends(verify_auth)])
async def download_file(filename: str):
    """Download a generated clip file."""
    # Prevent path traversal
    safe_name = Path(filename).name
    path = OUTPUT_DIR / safe_name
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(str(path), media_type="video/mp4", filename=safe_name)


@app.post("/cleanup", dependencies=[Depends(verify_auth)])
async def cleanup():
    """Delete all output files to free disk space."""
    count = 0
    for f in OUTPUT_DIR.glob("*.mp4"):
        try:
            f.unlink()
            count += 1
        except Exception:
            pass
    jobs.clear()
    return {"status": "cleaned", "files_deleted": count}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
