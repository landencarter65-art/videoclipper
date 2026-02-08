"""
Auto Clipping Pipeline
======================
Detects new YouTube uploads → Downloads → Transcribes → Picks best clips →
Mixes audio with background music → Burns speech subtitles → Outputs final clips.

Usage:
    python main.py                  # Process new videos from monitored channels
    python main.py --url URL        # Process a specific YouTube video URL
"""

import argparse
import gc
import shutil
from pathlib import Path

from config import DOWNLOADS_DIR, CLIPS_DIR, OUTPUT_DIR, NUM_CLIPS
from downloader import check_new_videos, download_video, extract_audio, mark_processed, download_random_music
from gemini_ai import transcribe_audio, select_best_clips, generate_youtube_metadata, timestamp_to_seconds
from video_processor import cut_clip, mix_audio, add_subtitles, cleanup_temp_files


def extract_clip_words(all_word_timings: list[dict], start_sec: float, end_sec: float) -> list[dict]:
    """Extract word timings that fall within a clip's time range.

    Adjusts timestamps to be relative to the clip start (so they start at 0).
    Returns timings in the format expected by create_word_srt: start_ms/end_ms.
    """
    clip_words = []
    for w in all_word_timings:
        w_start = w["start"]
        w_end = w["end"]
        if w_start >= start_sec and w_end <= end_sec + 0.5:
            clip_words.append({
                "word": w["word"],
                "start_ms": int((w_start - start_sec) * 1000),
                "end_ms": int((w_end - start_sec) * 1000),
            })
    return clip_words


def process_video(video_url: str, video_title: str = "Unknown", progress_callback=None):
    """Run the full pipeline on a single video."""
    def update_progress(percent: int, step: str):
        print(f"[{percent}%] {step}")
        if progress_callback:
            progress_callback(percent, step)

    print(f"\n{'='*60}")
    print(f"Processing: {video_title}")
    print(f"URL: {video_url}")
    print(f"{'='*60}\n")

    # 5 initial steps + 3 per clip (cut, mix, subtitles+metadata)
    total_steps = 5 + (NUM_CLIPS * 3)
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

    # Step 4: Transcribe with Groq (get text + word-level timestamps)
    try:
        transcript, word_timings = transcribe_audio(audio_path)
        step_progress(f"Transcribed: {len(transcript)} chars, {len(word_timings)} words")
    finally:
        gc.collect()

    # Save transcript for reference
    transcript_path = DOWNLOADS_DIR / f"{video_path.stem}_transcript.txt"
    transcript_path.write_text(transcript, encoding="utf-8")

    # Step 5: Select best clips (AI-powered smart clipping)
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

        # Cut clip from video (9:16 crop)
        clip_path = cut_clip(video_path, start, end, clip_num)
        step_progress(f"Clip {clip_num}: Cut video ({end - start:.1f}s)")

        # Mix original audio + background music
        mixed_path = mix_audio(clip_path, music_path, clip_num)

        # Extract word timings from Whisper that fall in this clip's range
        clip_word_timings = extract_clip_words(word_timings, start, end)
        print(f"  -> Found {len(clip_word_timings)} words in clip range")

        # Get the raw transcript text for this clip (fallback for subtitles)
        clip_text_parts = [w["word"] for w in clip_word_timings]
        clip_text = " ".join(clip_text_parts) if clip_text_parts else clip_data.get("hook", "")

        # Burn subtitles
        try:
            final_path = add_subtitles(mixed_path, clip_text, clip_num, clip_word_timings)
            if final_path.parent != OUTPUT_DIR:
                dest = OUTPUT_DIR / f"clip_{clip_num}.mp4"
                shutil.copy(final_path, dest)
                final_path = dest
        except Exception as e:
            print(f"  -> Subtitle burn failed: {e}")
            final_path = OUTPUT_DIR / f"clip_{clip_num}.mp4"
            shutil.copy(mixed_path, final_path)

        final_outputs.append(final_path)
        step_progress(f"Clip {clip_num}: Subtitles burned")

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

    try:
        if video_path.exists(): video_path.unlink()
        if audio_path.exists(): audio_path.unlink()
    except Exception:
        pass

    gc.collect()

    print(f"\n{'='*60}")
    print(f"DONE! {len(final_outputs)} clips ready in: {OUTPUT_DIR}")
    for f in final_outputs:
        print(f"  -> {f.name}")
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
