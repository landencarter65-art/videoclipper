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
    """Extract a clip and crop to 9:16 vertical."""
    output_path = CLIPS_DIR / f"clip_{clip_index}.mp4"
    duration = end_seconds - start_seconds

    # Crop center to 9:16 aspect ratio, then scale to output resolution
    vf = (
        f"crop=ih*9/16:ih,"
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_seconds),
        "-i", str(video_path),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", VIDEO_CODEC,
        "-c:a", "aac",
        "-preset", VIDEO_PRESET,
        "-crf", VIDEO_CRF,
        str(output_path),
    ]

    print(f"[FFMPEG] Cutting 9:16 clip {clip_index}: {start_seconds}s -> {end_seconds}s ({duration:.1f}s)")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed: {result.stderr[-500:]}")

    return output_path


def mix_audio(clip_path: Path, music_path: Path | None, clip_index: int) -> Path:
    """Mix original clip audio + background music (no voiceover)."""
    if not music_path or not music_path.exists():
        return clip_path  # No music to mix, return clip as-is

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

    fade_start = max(0, duration - 5)

    filter_complex = (
        f"[0:a]volume={ORIGINAL_AUDIO_VOLUME}[orig];"
        f"[1:a]volume={MUSIC_VOLUME},afade=t=out:st={fade_start}:d=5[music];"
        f"[orig][music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_path),
        "-i", str(music_path),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        str(output_path),
    ]

    print(f"[FFMPEG] Mixing audio + music for clip {clip_index} (Duration: {duration:.1f}s)")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg mix failed: {result.stderr[-500:]}")

    return output_path


def create_word_srt(word_timings: List[dict], output_path: Path,
                    delay_ms: int = 0) -> Path:
    """Create word-by-word SRT subtitles from speech transcription.

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

        start_ms = timing["start_ms"] + delay_ms
        end_ms = timing["end_ms"] + delay_ms

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
    """Burn subtitles onto video using force_style."""
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
    # Strategy 1: Word-by-word SRT with force_style
    if word_timings and len(word_timings) > 0:
        try:
            print(f"[FFMPEG] Burning word-by-word subtitles for clip {clip_index}")
            srt_path = CLIPS_DIR / f"sub_{clip_index}.srt"
            create_word_srt(word_timings, srt_path, delay_ms=0)
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
