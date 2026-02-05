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
)


def cut_clip(video_path: Path, start_seconds: float, end_seconds: float, clip_index: int) -> Path:
    """Extract a clip from the video using ffmpeg and convert to 9:16 vertical."""
    output_path = CLIPS_DIR / f"clip_{clip_index}.mp4"
    duration = end_seconds - start_seconds

    # 9:16 Crop + cinematic effects chain:
    # 1. Crop to 9:16 aspect ratio
    # 2. Scale to 108% (778x1382) for slow zoom headroom
    # 3. Animated crop back to 720x1280 with:
    #    - Ken Burns slow zoom (drift toward center via pow curve)
    #    - Speed ramp illusion (pow(t/dur, 0.7) = fast start, slow end)
    #    - Shake/pulse at voiceover start (~2s mark, sin/cos oscillation)
    # 4. Color grading (contrast + saturation + brightness boost)
    # 5. Vignette (dark edges, draws focus to center)
    # 6. Fade in/out transitions
    fade_out = max(0, duration - 0.5)

    vf = (
        "crop=ih*9/16:ih,"
        "scale=778:1382,"
        f"crop=720:1280"
        f":'29*pow(t/{duration},0.7)+between(t,1.8,2.5)*3*sin(25*t)'"
        f":'51*pow(t/{duration},0.7)+between(t,1.8,2.5)*3*cos(20*t)',"
        "eq=contrast=1.1:saturation=1.3:brightness=0.02,"
        "vignette=PI/5,"
        f"fade=in:st=0:d=0.5,fade=out:st={fade_out}:d=0.5"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_seconds),
        "-i", str(video_path),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", VIDEO_CODEC,
        "-crf", VIDEO_CRF,
        "-preset", VIDEO_PRESET,
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        str(output_path),
    ]

    print(f"[FFMPEG] Cutting 9:16 clip {clip_index}: {start_seconds}s → {end_seconds}s")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed: {result.stderr[-500:]}")

    return output_path


def mix_voiceover(clip_path: Path, voiceover_path: Path, music_path: Path | None, clip_index: int) -> Path:
    """Mix original clip audio (lowered) + voiceover + background music."""
    output_path = CLIPS_DIR / f"mixed_{clip_index}.mp4"

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
            "-c:v", "copy",
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
            "-c:v", "copy",
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


def ms_to_ass_time(ms: int) -> str:
    """Convert milliseconds to ASS timestamp format (H:MM:SS.cs)."""
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    centiseconds = (ms % 1000) // 10
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def generate_ass_subtitles(word_timings: List[dict], output_path: Path,
                           voiceover_delay_ms: int = 2000) -> Path:
    """
    Generate TikTok-style ASS subtitles - ONE word at a time with clean box.

    Args:
        word_timings: List of {"word": str, "start_ms": int, "end_ms": int}
        output_path: Path to save the .ass file
        voiceover_delay_ms: Delay before voiceover starts (default 2000ms)

    Returns:
        Path to the generated .ass file
    """
    # ASS Header - Clean TikTok/CapCut style
    # BorderStyle=4 = opaque box background
    # BackColour=&HBB000000 = semi-transparent black box
    # Alignment=2 = bottom center (like TikTok)
    # Large bold font, white text
    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Impact,72,&H00FFFFFF,&H000000FF,&H00000000,&HBB000000,1,0,0,0,100,100,0,0,4,0,0,2,20,20,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogues = []

    # Show ONE word at a time for clean TikTok style
    for timing in word_timings:
        word = timing["word"].strip().upper()
        if not word:
            continue

        # Add voiceover delay to timestamps
        start_ms = timing["start_ms"] + voiceover_delay_ms
        end_ms = timing["end_ms"] + voiceover_delay_ms

        # Ensure minimum display time (at least 150ms per word)
        if end_ms - start_ms < 150:
            end_ms = start_ms + 150

        start_time = ms_to_ass_time(start_ms)
        end_time = ms_to_ass_time(end_ms)

        dialogue = f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{word}"
        dialogues.append(dialogue)

    # Write ASS file
    ass_content = ass_header + "\n".join(dialogues)
    output_path.write_text(ass_content, encoding="utf-8")

    print(f"[SUBTITLES] Generated ASS with {len(dialogues)} words")
    return output_path


def add_subtitles(video_path: Path, subtitle_text: str, clip_index: int,
                  word_timings: List[dict] = None) -> Path:
    """
    Burn subtitles onto the video.

    Args:
        video_path: Input video file
        subtitle_text: Full subtitle text (fallback if no timings)
        clip_index: Clip number for naming
        word_timings: Optional word timings for animated TikTok-style subtitles
    """
    output_path = OUTPUT_DIR / f"final_clip_{clip_index}.mp4"

    # Strategy 1: Animated ASS subtitles (if word timings available)
    if word_timings and len(word_timings) > 0:
        try:
            print(f"[FFMPEG] Burning TikTok-style subtitles for clip {clip_index}")
            ass_path = CLIPS_DIR / f"sub_{clip_index}.ass"
            generate_ass_subtitles(word_timings, ass_path, voiceover_delay_ms=2000)

            # Escape path for FFmpeg filter (Windows compatibility)
            ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")

            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-vf", f"ass='{ass_escaped}'",
                "-c:v", VIDEO_CODEC,
                "-crf", VIDEO_CRF,
                "-preset", VIDEO_PRESET,
                "-c:a", "copy",
                str(output_path),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return output_path
            else:
                print(f"[WARN] ASS subtitle burn failed, trying SRT fallback: {result.stderr[-200:]}")
        except Exception as e:
            print(f"[WARN] ASS generation failed: {e}, trying SRT fallback")

    # Strategy 2: Simple SRT fallback (existing method)
    try:
        print(f"[FFMPEG] Burning simple subtitles for clip {clip_index}")
        clean_text = subtitle_text.replace("\n", " ").replace("\"", "'").strip().upper()

        srt_path = CLIPS_DIR / f"sub_{clip_index}.srt"
        srt_content = f"1\n00:00:02,000 --> 00:01:30,000\n{clean_text}\n"
        srt_path.write_text(srt_content, encoding="utf-8")

        srt_escaped = str(srt_path).replace("\\", "/").replace(":", "\\:")
        # Clean TikTok style - white text, black box background, bottom center
        style = "Fontname=Impact,FontSize=72,PrimaryColour=&H00FFFFFF,BackColour=&HBB000000,Bold=1,Alignment=2,MarginV=120,BorderStyle=4"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"subtitles='{srt_escaped}':force_style='{style}'",
            "-c:v", VIDEO_CODEC,
            "-crf", VIDEO_CRF,
            "-preset", VIDEO_PRESET,
            "-c:a", "copy",
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return output_path
        else:
            print(f"[WARN] SRT subtitle burn failed: {result.stderr[-200:]}")
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
