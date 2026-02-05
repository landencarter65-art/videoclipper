"""
Auto Clipping Pipeline
======================
Detects new YouTube uploads → Downloads → Transcribes → Picks best clips →
Generates voiceover commentary → Mixes audio → Outputs final clips.

Usage:
    python main.py                  # Process new videos from monitored channels
    python main.py --url URL        # Process a specific YouTube video URL
"""

import argparse
import sys
import gc
from pathlib import Path

from tqdm import tqdm

from config import DOWNLOADS_DIR, CLIPS_DIR, OUTPUT_DIR, NUM_CLIPS
from downloader import check_new_videos, download_video, extract_audio, mark_processed, download_random_music
from gemini_ai import transcribe_audio, select_best_clips, generate_voiceover_script, generate_youtube_metadata, timestamp_to_seconds
from voiceover import generate_voiceover_audio
from video_processor import cut_clip, mix_voiceover, cleanup_temp_files


def process_video(video_url: str, video_title: str = "Unknown", progress_callback=None):
    """Run the full pipeline on a single video.

    Args:
        video_url: YouTube video URL
        video_title: Title of the video
        progress_callback: Optional function(percent, step_name) to report progress
    """
    def update_progress(percent: int, step: str):
        """Update progress via callback and console."""
        print(f"[{percent}%] {step}")
        if progress_callback:
            progress_callback(percent, step)

    print(f"\n{'='*60}")
    print(f"Processing: {video_title}")
    print(f"URL: {video_url}")
    print(f"{'='*60}\n")

    # Pipeline has 5 initial steps + 5 steps per clip (assuming NUM_CLIPS clips)
    # Total steps: 5 + (NUM_CLIPS * 5) = 5 + 15 = 20 steps for 3 clips
    total_steps = 5 + (NUM_CLIPS * 5)
    current_step = 0

    def step_progress(step_name: str):
        nonlocal current_step
        current_step += 1
        percent = int((current_step / total_steps) * 100)
        update_progress(percent, step_name)

    # Step 1: Download video
    update_progress(0, "Downloading video...")
    video_path = download_video(video_url)
    step_progress(f"Downloaded: {video_path.name}")

    # Step 2: Download background music
    music_path = None
    try:
        music_path = download_random_music()
        step_progress(f"Music: {music_path.name}")
    except Exception as e:
        step_progress(f"Music skipped: {e}")

    # Step 3: Extract audio for transcription
    audio_path = extract_audio(video_path)
    step_progress(f"Audio extracted: {audio_path.name}")

    # Step 4: Transcribe with Groq
    try:
        transcript = transcribe_audio(audio_path)
        step_progress(f"Transcribed: {len(transcript)} chars")
    finally:
        gc.collect()

    # Save transcript for reference
    transcript_path = DOWNLOADS_DIR / f"{video_path.stem}_transcript.txt"
    transcript_path.write_text(transcript, encoding="utf-8")

    # Step 5: Select best clips
    clips = select_best_clips(transcript, video_title, video_path=video_path)
    step_progress(f"Found {len(clips)} clips")

    for c in clips:
        print(f"   Clip {c['clip_number']}: {c['start_time']} -> {c['end_time']} | {c['title']}")

    # Process each clip
    final_outputs = []
    clips_metadata = []

    for clip_data in clips:
        clip_num = clip_data["clip_number"]
        start = timestamp_to_seconds(clip_data["start_time"])
        end = timestamp_to_seconds(clip_data["end_time"])

        # Cut clip from video
        clip_path = cut_clip(video_path, start, end, clip_num)
        step_progress(f"Clip {clip_num}: Cut video")

        # Get transcript segment for this clip
        clip_transcript = clip_data.get("hook", "") + " " + clip_data.get("reason", "")

        # Generate voiceover script
        vo_script = generate_voiceover_script(clip_transcript, clip_data["title"], video_title)
        step_progress(f"Clip {clip_num}: Generated script")

        # Save script for reference
        script_path = CLIPS_DIR / f"script_{clip_num}.txt"
        script_path.write_text(vo_script, encoding="utf-8")

        # Generate voiceover audio
        vo_audio_path = CLIPS_DIR / f"voiceover_{clip_num}.mp3"
        generate_voiceover_audio(vo_script, vo_audio_path)
        step_progress(f"Clip {clip_num}: Generated voiceover")

        # Mix voiceover + background music with clip
        final_path = mix_voiceover(clip_path, vo_audio_path, music_path, clip_num)
        final_outputs.append(final_path)
        step_progress(f"Clip {clip_num}: Mixed audio")
        
        gc.collect()

        # Generate YouTube metadata
        try:
            yt_meta = generate_youtube_metadata(
                clip_data.get("title", f"Clip {clip_num}"),
                clip_data.get("hook", ""),
                video_title,
            )
        except Exception as e:
            print(f"  -> Metadata generation failed, using defaults: {e}")
            yt_meta = {
                "title": clip_data.get("title", f"Clip {clip_num}"),
                "description": f"#shorts #roblox #gaming",
                "tags": ["roblox", "gaming", "shorts", "clips"],
            }
        step_progress(f"Clip {clip_num}: Generated metadata")

        clips_metadata.append({
            "clip_number": clip_num,
            "title": yt_meta.get("title", clip_data.get("title", f"Clip {clip_num}")),
            "description": yt_meta.get("description", ""),
            "tags": yt_meta.get("tags", []),
            "hook": clip_data.get("hook", ""),
        })
        print(f"  -> Clip {clip_num} done: {final_path.name}")

    # Cleanup temp files
    cleanup_temp_files()

    # Clean up downloaded video and audio
    try:
        if video_path.exists(): video_path.unlink()
        if audio_path.exists(): audio_path.unlink()
    except Exception:
        pass
    
    gc.collect()

    print(f"\n{'='*60}")
    print(f"DONE! {len(final_outputs)} clips ready in: {OUTPUT_DIR}")
    for f in final_outputs:
        print(f"  → {f.name}")
    print(f"{'='*60}\n")

    return {"files": final_outputs, "clips_metadata": clips_metadata}


def run_pipeline():
    """Check for new videos and process them."""
    print("[Pipeline] Checking for new uploads...")
    new_videos = check_new_videos()

    if not new_videos:
        print("[Pipeline] No new videos found.")
        return

    for video in new_videos:
        try:
            process_video(video["url"], video["title"])
            mark_processed(video["video_id"])
        except Exception as e:
            print(f"[ERROR] Failed to process {video['title']}: {e}")
            continue


def main():
    parser = argparse.ArgumentParser(description="Auto Clipping Pipeline")
    parser.add_argument("--url", type=str, help="Process a specific YouTube video URL")
    parser.add_argument("--title", type=str, default="Video", help="Video title (used with --url)")
    args = parser.parse_args()

    if args.url:
        process_video(args.url, args.title)
    else:
        run_pipeline()


if __name__ == "__main__":
    main()
