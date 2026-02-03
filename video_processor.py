import subprocess
from pathlib import Path
from config import (
    CLIPS_DIR,
    OUTPUT_DIR,
    VIDEO_CODEC,
    VIDEO_CRF,
    VIDEO_PRESET,
    AUDIO_BITRATE,
    ORIGINAL_AUDIO_VOLUME,
    MUSIC_VOLUME,
)


def cut_clip(video_path: Path, start_seconds: float, end_seconds: float, clip_index: int) -> Path:
    """Extract a clip from the video using ffmpeg."""
    output_path = CLIPS_DIR / f"clip_{clip_index}.mp4"
    duration = end_seconds - start_seconds

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_seconds),
        "-i", str(video_path),
        "-t", str(duration),
        "-c:v", VIDEO_CODEC,
        "-crf", VIDEO_CRF,
        "-preset", VIDEO_PRESET,
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        str(output_path),
    ]

    print(f"[FFMPEG] Cutting clip {clip_index}: {start_seconds}s → {end_seconds}s")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed: {result.stderr[-500:]}")

    return output_path


def mix_voiceover(clip_path: Path, voiceover_path: Path, music_path: Path | None, clip_index: int) -> Path:
    """Mix original clip audio (lowered) + voiceover + background music."""
    output_path = OUTPUT_DIR / f"final_clip_{clip_index}.mp4"

    # Get duration of the clip to calculate fade out
    try:
        probe_cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(clip_path)
        ]
        duration_str = subprocess.check_output(probe_cmd, text=True).strip()
        duration = float(duration_str)
    except Exception:
        duration = 60.0  # Fallback if probe fails

    if music_path and music_path.exists():
        # Calculate fade out: start 5s before end
        fade_start = max(0, duration - 5)
        
        # 3-layer mix: original (low) + voiceover + background music (subtle)
        filter_complex = (
            f"[0:a]volume={ORIGINAL_AUDIO_VOLUME}[orig];"
            f"[1:a]adelay=2000|2000,volume=1.8[voice];"
            f"[2:a]volume={MUSIC_VOLUME},afade=t=out:st={fade_start}:d=5[music];"
            f"[orig][voice][music]amix=inputs=3:duration=first:dropout_transition=2[aout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-i", str(voiceover_path),
            "-i", str(music_path),
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", VIDEO_CODEC,
            "-crf", VIDEO_CRF,
            "-preset", VIDEO_PRESET,
            "-c:a", "aac",
            "-b:a", AUDIO_BITRATE,
            "-shortest",
            str(output_path),
        ]
    else:
        # 2-layer fallback: original (low) + voiceover only
        filter_complex = (
            f"[0:a]volume={ORIGINAL_AUDIO_VOLUME}[orig];"
            f"[1:a]adelay=2000|2000,volume=1.8[voice];"
            f"[orig][voice]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-i", str(voiceover_path),
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", VIDEO_CODEC,
            "-crf", VIDEO_CRF,
            "-preset", VIDEO_PRESET,
            "-c:a", "aac",
            "-b:a", AUDIO_BITRATE,
            "-shortest",
            str(output_path),
        ]

    print(f"[FFMPEG] Mixing voiceover + music for clip {clip_index} (Duration: {duration:.1f}s)")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg mix failed: {result.stderr[-500:]}")

    return output_path


def add_subtitles(video_path: Path, subtitle_text: str, clip_index: int) -> Path:
    """Burn subtitles onto the video (optional enhancement)."""
    # Write subtitle to temp SRT file
    srt_path = CLIPS_DIR / f"sub_{clip_index}.srt"
    srt_content = f"1\n00:00:02,000 --> 00:01:30,000\n{subtitle_text}\n"
    srt_path.write_text(srt_content, encoding="utf-8")

    output_path = OUTPUT_DIR / f"final_sub_clip_{clip_index}.mp4"

    # Use ffmpeg subtitles filter — escape path for Windows
    srt_escaped = str(srt_path).replace("\\", "/").replace(":", "\\:")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"subtitles='{srt_escaped}':force_style='FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Bold=1'",
        "-c:v", VIDEO_CODEC,
        "-crf", VIDEO_CRF,
        "-preset", VIDEO_PRESET,
        "-c:a", "copy",
        str(output_path),
    ]

    print(f"[FFMPEG] Adding subtitles to clip {clip_index}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[WARN] Subtitle burn failed (non-critical): {result.stderr[-200:]}")
        return video_path  # Return without subtitles if it fails

    return output_path


def cleanup_temp_files():
    """Remove intermediate files from clips directory."""
    for f in CLIPS_DIR.glob("*"):
        try:
            f.unlink()
        except Exception:
            pass
