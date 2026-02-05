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

from tqdm import tqdm

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

    # Define pipeline steps
    steps = [
        "Downloading video",
        "Downloading background music",
        "Extracting audio",
        "Transcribing with Groq",
        "Selecting best clips",
    ]

    # Create main progress bar
    pbar = tqdm(total=len(steps), desc="Pipeline", unit="step", ncols=80, bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} {desc}")

    # Step 1: Download video
    pbar.set_description("Downloading video")
    video_path = download_video(video_url)
    pbar.update(1)
    tqdm.write(f"  -> Downloaded: {video_path.name}")

    # Step 2: Download background music
    pbar.set_description("Downloading music")
    music_path = None
    try:
        music_path = download_random_music()
        tqdm.write(f"  -> Music: {music_path.name}")
    except Exception as e:
        tqdm.write(f"  -> Music download failed (will continue without): {e}")
    pbar.update(1)

    # Step 3: Extract audio for transcription
    pbar.set_description("Extracting audio")
    audio_path = extract_audio(video_path)
    pbar.update(1)
    tqdm.write(f"  -> Audio: {audio_path.name}")

    # Step 4: Transcribe with Groq
    pbar.set_description("Transcribing")
    transcript = transcribe_audio(audio_path)
    pbar.update(1)
    tqdm.write(f"  -> Transcript length: {len(transcript)} chars")

    # Save transcript for reference
    transcript_path = DOWNLOADS_DIR / f"{video_path.stem}_transcript.txt"
    transcript_path.write_text(transcript, encoding="utf-8")

    # Step 5: Select best clips
    pbar.set_description("Selecting clips")
    clips = select_best_clips(transcript, video_title, video_path=video_path)
    pbar.update(1)
    pbar.close()

    tqdm.write(f"  -> Found {len(clips)} clips")
    for c in clips:
        tqdm.write(f"     Clip {c['clip_number']}: {c['start_time']} -> {c['end_time']} | {c['title']}")

    # Process each clip with its own progress bar
    final_outputs = []
    clips_metadata = []

    for clip_data in tqdm(clips, desc="Processing clips", unit="clip", ncols=80):
        clip_num = clip_data["clip_number"]
        start = timestamp_to_seconds(clip_data["start_time"])
        end = timestamp_to_seconds(clip_data["end_time"])

        # Sub-progress for clip processing (4 steps per clip)
        clip_steps = ["Cutting", "Voiceover script", "Voiceover audio", "Mixing", "Metadata"]
        clip_pbar = tqdm(total=len(clip_steps), desc=f"Clip {clip_num}", unit="step", ncols=80, leave=False)

        # Cut clip from video
        clip_pbar.set_description(f"Clip {clip_num}: Cutting")
        clip_path = cut_clip(video_path, start, end, clip_num)
        clip_pbar.update(1)

        # Get transcript segment for this clip
        clip_transcript = clip_data.get("hook", "") + " " + clip_data.get("reason", "")

        # Generate voiceover script
        clip_pbar.set_description(f"Clip {clip_num}: Script")
        vo_script = generate_voiceover_script(clip_transcript, clip_data["title"], video_title)
        clip_pbar.update(1)

        # Save script for reference
        script_path = CLIPS_DIR / f"script_{clip_num}.txt"
        script_path.write_text(vo_script, encoding="utf-8")

        # Generate voiceover audio
        clip_pbar.set_description(f"Clip {clip_num}: TTS")
        vo_audio_path = CLIPS_DIR / f"voiceover_{clip_num}.mp3"
        generate_voiceover_audio(vo_script, vo_audio_path)
        clip_pbar.update(1)

        # Mix voiceover + background music with clip
        clip_pbar.set_description(f"Clip {clip_num}: Mixing")
        final_path = mix_voiceover(clip_path, vo_audio_path, music_path, clip_num)
        final_outputs.append(final_path)
        clip_pbar.update(1)

        # Generate YouTube metadata
        clip_pbar.set_description(f"Clip {clip_num}: Metadata")
        try:
            yt_meta = generate_youtube_metadata(
                clip_data.get("title", f"Clip {clip_num}"),
                clip_data.get("hook", ""),
                video_title,
            )
        except Exception as e:
            tqdm.write(f"  -> Metadata generation failed, using defaults: {e}")
            yt_meta = {
                "title": clip_data.get("title", f"Clip {clip_num}"),
                "description": f"#shorts #roblox #gaming",
                "tags": ["roblox", "gaming", "shorts", "clips"],
            }
        clip_pbar.update(1)
        clip_pbar.close()

        clips_metadata.append({
            "clip_number": clip_num,
            "title": yt_meta.get("title", clip_data.get("title", f"Clip {clip_num}")),
            "description": yt_meta.get("description", ""),
            "tags": yt_meta.get("tags", []),
            "hook": clip_data.get("hook", ""),
        })
        tqdm.write(f"  -> Clip {clip_num} done: {final_path.name}")

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
