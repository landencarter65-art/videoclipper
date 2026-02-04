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
from pathlib import Path

from config import DOWNLOADS_DIR, CLIPS_DIR, OUTPUT_DIR
from downloader import check_new_videos, download_video, extract_audio, mark_processed, download_random_music
from gemini_ai import transcribe_audio, select_best_clips, generate_voiceover_script, generate_youtube_metadata, timestamp_to_seconds
from voiceover import generate_voiceover_audio
from video_processor import cut_clip, mix_voiceover, cleanup_temp_files


def process_video(video_url: str, video_title: str = "Unknown"):
    """Run the full pipeline on a single video."""
    print(f"\n{'='*60}")
    print(f"Processing: {video_title}")
    print(f"URL: {video_url}")
    print(f"{'='*60}\n")

    # Step 1: Download video + background music
    print("[1/7] Downloading video...")
    video_path = download_video(video_url)
    print(f"  → Downloaded: {video_path.name}")

    print("\n[2/7] Downloading background music from playlist...")
    music_path = None
    try:
        music_path = download_random_music()
        print(f"  → Music: {music_path.name}")
    except Exception as e:
        print(f"  → Music download failed (will continue without): {e}")

    # Step 2: Extract audio for transcription
    print("\n[3/7] Extracting audio...")
    audio_path = extract_audio(video_path)
    print(f"  → Audio: {audio_path.name}")

    # Step 4: Transcribe with Gemini
    print("\n[4/7] Transcribing with Gemini (AI)...")
    transcript = transcribe_audio(audio_path)
    print(f"  → Transcript length: {len(transcript)} chars")

    # Save transcript for reference
    transcript_path = DOWNLOADS_DIR / f"{video_path.stem}_transcript.txt"
    transcript_path.write_text(transcript, encoding="utf-8")

    # Step 5: Select best clips
    print("\n[5/7] Selecting best clips (Heuristic)...")
    # Pass video_path so heuristic mode can calculate duration
    clips = select_best_clips(transcript, video_title, video_path=video_path)
    print(f"  → Found {len(clips)} clips")
    for c in clips:
        print(f"     Clip {c['clip_number']}: {c['start_time']} → {c['end_time']} | {c['title']}")

    # Step 6 & 7: For each clip, generate voiceover and mix
    final_outputs = []
    clips_metadata = []
    for clip_data in clips:
        clip_num = clip_data["clip_number"]
        start = timestamp_to_seconds(clip_data["start_time"])
        end = timestamp_to_seconds(clip_data["end_time"])

        # Cut clip from video
        print(f"\n[6/7] Processing clip {clip_num}...")
        clip_path = cut_clip(video_path, start, end, clip_num)

        # Get transcript segment for this clip (approximate from the full transcript)
        clip_transcript = clip_data.get("hook", "") + " " + clip_data.get("reason", "")

        # Generate voiceover script
        vo_script = generate_voiceover_script(clip_transcript, clip_data["title"], video_title)
        print(f"  → Voiceover script: {vo_script[:80]}...")

        # Save script for reference
        script_path = CLIPS_DIR / f"script_{clip_num}.txt"
        script_path.write_text(vo_script, encoding="utf-8")

        # Generate voiceover audio
        vo_audio_path = CLIPS_DIR / f"voiceover_{clip_num}.mp3"
        generate_voiceover_audio(vo_script, vo_audio_path)

        # Mix voiceover + background music with clip
        print(f"\n[7/8] Mixing final clip {clip_num}...")
        final_path = mix_voiceover(clip_path, vo_audio_path, music_path, clip_num)
        final_outputs.append(final_path)

        # Generate YouTube metadata (title, description, tags)
        print(f"\n[8/8] Generating YouTube metadata for clip {clip_num}...")
        try:
            yt_meta = generate_youtube_metadata(
                clip_data.get("title", f"Clip {clip_num}"),
                clip_data.get("hook", ""),
                video_title,
            )
        except Exception as e:
            print(f"  → Metadata generation failed, using defaults: {e}")
            yt_meta = {
                "title": clip_data.get("title", f"Clip {clip_num}"),
                "description": f"#shorts #roblox #gaming",
                "tags": ["roblox", "gaming", "shorts", "clips"],
            }
        print(f"  → YT Title: {yt_meta.get('title', '')[:60]}")

        clips_metadata.append({
            "clip_number": clip_num,
            "title": yt_meta.get("title", clip_data.get("title", f"Clip {clip_num}")),
            "description": yt_meta.get("description", ""),
            "tags": yt_meta.get("tags", []),
            "hook": clip_data.get("hook", ""),
        })
        print(f"  → Output: {final_path.name}")

    # Cleanup temp files
    cleanup_temp_files()

    # Clean up downloaded video and audio
    try:
        video_path.unlink()
        audio_path.unlink()
    except Exception:
        pass

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
