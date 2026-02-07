import subprocess
from pathlib import Path
from typing import List
from config import (
    CLIPS_DIR,
    OUTPUT_DIR,
    VIDEO_CODEC,
    VIDEO_CRF,
    VIDEO_PRESET,
    AUDIO_BITRATE,
    ORIGINAL_AUDIO_VOLUME,
    MUSIC_VOLUME,
    OUTPUT_WIDTH,
    OUTPUT_HEIGHT,
    SUBTITLE_STYLE,
)


def cut_clip(video_path: Path, start_seconds: float, end_seconds: float, clip_index: int) -> Path:
    """Extract a clip from the video using ffmpeg (simple cut, no effects)."""
    output_path = CLIPS_DIR / f"clip_{clip_index}.mp4"
    duration = end_seconds - start_seconds

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_seconds),
        "-i", str(video_path),
        "-t", str(duration),
        "-c:v", VIDEO_CODEC,
        "-c:a", "aac",
        "-preset", VIDEO_PRESET,
        "-crf", VIDEO_CRF,
        str(output_path),
    ]

    print(f"[FFMPEG] Cutting clip {clip_index}: {start_seconds}s -> {end_seconds}s ({duration:.1f}s)")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed: {result.stderr[-500:]}")

    return output_path


def create_rainbow_background(duration: float, clip_index: int) -> Path:
    """Create animated blurred rainbow gradient background (matching notebook)."""
    output_path = CLIPS_DIR / f"rainbow_bg_{clip_index}.mp4"

    filter_cmd = (
        f"color=s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:c=red:d={duration},"
        f"hue=H=t*60:s=2,"
        f"boxblur=luma_radius=100:luma_power=3,"
        f"eq=brightness=0.05:saturation=1.2"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", filter_cmd,
        "-t", str(duration),
        "-c:v", VIDEO_CODEC,
        "-preset", VIDEO_PRESET,
        "-crf", VIDEO_CRF,
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]

    print(f"[FFMPEG] Creating rainbow background for clip {clip_index} ({duration:.1f}s)")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg rainbow bg failed: {result.stderr[-500:]}")

    return output_path


def combine_with_rainbow(clip_path: Path, rainbow_bg_path: Path, clip_index: int) -> Path:
    """Overlay video on rainbow background (centered, maintaining aspect ratio)."""
    output_path = CLIPS_DIR / f"combined_{clip_index}.mp4"

    filter_complex = (
        f"[1:v]scale=-1:{OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease[scaled];"
        f"[0:v][scaled]overlay=(W-w)/2:(H-h)/2:shortest=1[outv]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(rainbow_bg_path),
        "-i", str(clip_path),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "1:a?",
        "-c:v", VIDEO_CODEC,
        "-c:a", "aac",
        "-preset", VIDEO_PRESET,
        "-crf", VIDEO_CRF,
        "-shortest",
        str(output_path),
    ]

    print(f"[FFMPEG] Combining clip {clip_index} with rainbow background")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg combine failed: {result.stderr[-500:]}")

    return output_path


def mix_voiceover(clip_path: Path, voiceover_path: Path, music_path: Path | None, clip_index: int) -> Path:
    """Mix original clip audio (lowered) + voiceover + background music."""
    output_path = CLIPS_DIR / f"mixed_{clip_index}.mp4"

    try:
        probe_cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(clip_path)
        ]
        duration_str = subprocess.check_output(probe_cmd, text=True).strip()
        duration = float(duration_str)
    except Exception:
        duration = 60.0

    if music_path and music_path.exists():
        fade_start = max(0, duration - 5)

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
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", AUDIO_BITRATE,
            str(output_path),
        ]
    else:
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
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", AUDIO_BITRATE,
            str(output_path),
        ]

    print(f"[FFMPEG] Mixing voiceover + music for clip {clip_index} (Duration: {duration:.1f}s)")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg mix failed: {result.stderr[-500:]}")

    return output_path


def create_word_srt(word_timings: List[dict], output_path: Path,
                    voiceover_delay_ms: int = 2000) -> Path:
    """Create word-by-word SRT subtitles (matching notebook approach).

    Each word gets its own subtitle entry, displayed one at a time in uppercase.
    """
    def ms_to_srt_time(ms: int) -> str:
        hours = ms // 3600000
        ms %= 3600000
        minutes = ms // 60000
        ms %= 60000
        seconds = ms // 1000
        millis = ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    srt_lines = []
    index = 1

    for timing in word_timings:
        word = timing["word"].strip().upper()
        if not word:
            continue

        start_ms = timing["start_ms"] + voiceover_delay_ms
        end_ms = timing["end_ms"] + voiceover_delay_ms

        if end_ms - start_ms < 150:
            end_ms = start_ms + 150

        start_t = ms_to_srt_time(start_ms)
        end_t = ms_to_srt_time(end_ms)

        srt_lines.append(f"{index}\n{start_t} --> {end_t}\n{word}\n")
        index += 1

    srt_content = "\n".join(srt_lines)
    output_path.write_text(srt_content, encoding="utf-8")

    print(f"[SUBTITLES] Generated SRT with {index - 1} words")
    return output_path


def burn_subtitles(input_video: Path, srt_path: Path, clip_index: int,
                   style: dict = None) -> Path:
    """Burn subtitles onto video using force_style (matching notebook approach)."""
    output_path = OUTPUT_DIR / f"final_clip_{clip_index}.mp4"
    if style is None:
        style = SUBTITLE_STYLE

    force_style = (
        f"FontName={style['font']},"
        f"FontSize={style['font_size']},"
        f"PrimaryColour={style['primary_color']},"
        f"OutlineColour={style['outline_color']},"
        f"BackColour={style['back_color']},"
        f"BorderStyle=1,"
        f"Outline={style['outline']},"
        f"Shadow={style['shadow']},"
        f"Bold={style['bold']},"
        f"Alignment={style['alignment']},"
        f"MarginV={style['margin_v']}"
    )

    srt_escaped = str(srt_path).replace("\\", "/").replace(":", r"\:")
    subtitle_filter = f"subtitles='{srt_escaped}':force_style='{force_style}'"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-vf", subtitle_filter,
        "-c:v", VIDEO_CODEC,
        "-c:a", "copy",
        "-preset", VIDEO_PRESET,
        "-crf", VIDEO_CRF,
        str(output_path),
    ]

    print(f"[FFMPEG] Burning subtitles for clip {clip_index}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg subtitle burn failed: {result.stderr[-500:]}")

    return output_path


def add_subtitles(video_path: Path, subtitle_text: str, clip_index: int,
                  word_timings: List[dict] = None) -> Path:
    """Burn subtitles onto the video.

    Strategy 1: Word-by-word SRT with force_style (if word timings available)
    Strategy 2: Chunked SRT fallback (if no timings)
    Strategy 3: Return video without subtitles (failsafe)
    """
    output_path = OUTPUT_DIR / f"final_clip_{clip_index}.mp4"

    # Strategy 1: Word-by-word SRT with force_style
    if word_timings and len(word_timings) > 0:
        try:
            print(f"[FFMPEG] Burning word-by-word subtitles for clip {clip_index}")
            srt_path = CLIPS_DIR / f"sub_{clip_index}.srt"
            create_word_srt(word_timings, srt_path, voiceover_delay_ms=2000)
            return burn_subtitles(video_path, srt_path, clip_index)
        except Exception as e:
            print(f"[WARN] Word-by-word subtitle burn failed: {e}, trying fallback")

    # Strategy 2: Chunked SRT fallback
    try:
        print(f"[FFMPEG] Burning chunked subtitles for clip {clip_index}")
        clean_text = subtitle_text.replace("\n", " ").replace("\"", "'").strip().upper()

        srt_path = CLIPS_DIR / f"sub_{clip_index}.srt"
        words = clean_text.split()
        chunks = [" ".join(words[i:i+5]) for i in range(0, len(words), 5)]
        srt_lines = []
        for i, chunk in enumerate(chunks):
            start_s = i * 4
            end_s = (i + 1) * 4
            h_s, m_s, s_s = start_s // 3600, (start_s % 3600) // 60, start_s % 60
            h_e, m_e, s_e = end_s // 3600, (end_s % 3600) // 60, end_s % 60
            start_t = f"{h_s:02d}:{m_s:02d}:{s_s:02d},000"
            end_t = f"{h_e:02d}:{m_e:02d}:{s_e:02d},000"
            srt_lines.append(f"{i+1}\n{start_t} --> {end_t}\n{chunk}\n")

        srt_content = "\n".join(srt_lines)
        srt_path.write_text(srt_content, encoding="utf-8")

        return burn_subtitles(video_path, srt_path, clip_index)
    except Exception as e:
        print(f"[WARN] SRT fallback failed: {e}")

    # Strategy 3: Return video without subtitles
    print("[WARN] All subtitle methods failed, returning video without subtitles")
    return video_path


def cleanup_temp_files():
    """Remove intermediate files from clips directory."""
    for f in CLIPS_DIR.glob("*"):
        try:
            f.unlink()
        except Exception:
            pass
