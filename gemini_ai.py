import json
import subprocess
import re
from pathlib import Path
# Note: we are not using the google.genai client for the heuristic version
from config import NUM_CLIPS, CLIP_MIN_SECONDS, CLIP_MAX_SECONDS

def call_with_retry(func, *args, **kwargs):
    """(Deprecated) Retries the API call - no-op for heuristic mode."""
    return func(*args, **kwargs)

def get_video_duration(video_path: Path) -> float:
    """Get the duration of a video file in seconds using ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        print(f"[ERROR] Could not get video duration: {e}")
        return 600.0 # Default fallback duration

def transcribe_audio(audio_path: Path) -> str:
    """
    (Heuristic Mode) Skips AI transcription.
    Returns a dummy transcript since we aren't using AI.
    """
    print(f"[Heuristic] Skipping AI transcription for {audio_path.name}")
    return "HEURISTIC_MODE_SKIPPED_TRANSCRIPTION"

def select_best_clips(transcript: str, video_title: str, video_path: Path = None) -> list[dict]:
    """
    (Heuristic Mode) Selects clips based on equidistant intervals.
    Requires video_path to be passed (we modified main.py to pass it).
    """
    print("[Heuristic] Selecting clips based on video duration...")
    
    duration = 0.0
    if video_path and video_path.exists():
        duration = get_video_duration(video_path)
    else:
        # Fallback if video_path isn't passed (though main.py should pass it)
        print("[WARN] Video path missing for duration check, using defaults.")
        duration = 600.0

    clips = []
    # Avoid the first 10% and last 10% of the video
    start_buffer = duration * 0.1
    end_buffer = duration * 0.9
    available_duration = end_buffer - start_buffer
    
    if available_duration < CLIP_MAX_SECONDS:
         # Video too short, just take one from the middle
         step = 0
         points = [duration / 2]
    else:
        # Divide the available space into N segments
        step = available_duration / (NUM_CLIPS + 1)
        points = [start_buffer + step * (i + 1) for i in range(NUM_CLIPS)]

    for i, point in enumerate(points):
        # Ensure clip doesn't exceed video length
        start_sec = point
        end_sec = min(start_sec + CLIP_MAX_SECONDS, duration - 5)
        
        # Format as MM:SS
        start_str = f"{int(start_sec // 60):02d}:{int(start_sec % 60):02d}"
        end_str = f"{int(end_sec // 60):02d}:{int(end_sec % 60):02d}"
        
        clips.append({
            "clip_number": i + 1,
            "start_time": start_str,
            "end_time": end_str,
            "title": f"Part {i+1} - {video_title}",
            "reason": "Heuristic selection",
            "hook": f"Watch part {i+1} of {video_title}"
        })

    return clips

def generate_voiceover_script(clip_transcript: str, clip_title: str, video_title: str) -> str:
    """
    (Heuristic Mode) Returns a generic voiceover script.
    """
    print(f"[Heuristic] Generating generic voiceover for: {clip_title}")
    
    templates = [
        f"You won't believe what happens in this part of {video_title}. Watch till the end!",
        f"Check out this crazy moment from {video_title}. Subscribe for more daily clips!",
        f"This is one of the best moments from {video_title}. What do you think? Let us know in the comments."
    ]
    
    # Pick one based on clip title hash (so it's deterministic for the same clip)
    index = hash(clip_title) % len(templates)
    return templates[index]

def generate_youtube_metadata(clip_title: str, clip_hook: str, video_title: str) -> dict:
    """
    (Heuristic Mode) Returns generic metadata.
    """
    print(f"[Heuristic] Generating generic metadata for: {clip_title}")
    
    return {
        "title": f"CRAZY MOMENT in {video_title} #shorts",
        "description": f"Best moments from {video_title}!

Subscribe for more daily Roblox clips.

#roblox #gaming #shorts #viral",
        "tags": ["roblox", "gaming", "shorts", "clips", "viral", "funny moments"]
    }

def timestamp_to_seconds(ts: str) -> float:
    """Convert MM:SS or HH:MM:SS to seconds."""
    parts = ts.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0.0