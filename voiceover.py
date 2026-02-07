import asyncio
import edge_tts
from pathlib import Path
from typing import List, Tuple
from config import TTS_VOICE


async def _generate_tts_with_timing(text: str, output_path: Path) -> List[dict]:
    """
    Generate TTS audio and extract word-level timestamps.

    Returns:
        List of dicts: [{"word": str, "start_ms": int, "end_ms": int}, ...]
    """
    communicate = edge_tts.Communicate(
        text,
        voice=TTS_VOICE,
        rate="-5%",
        volume="+10%",
        pitch="+0Hz",
    )

    word_timings = []

    with open(output_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] in ["WordBoundary", "word_boundary"]:
                start_ms = chunk.get("offset", 0) // 10000
                duration_ms = chunk.get("duration", 0) // 10000
                end_ms = start_ms + duration_ms

                word_timings.append({
                    "word": chunk.get("text", ""),
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                })

    return word_timings


def _estimate_word_timings(text: str) -> List[dict]:
    """Fallback: estimate word timings at ~200ms per word starting at 0ms."""
    words = text.split()
    timings = []
    current_ms = 0
    for word in words:
        duration = max(150, len(word) * 60)  # longer words get more time
        timings.append({
            "word": word,
            "start_ms": current_ms,
            "end_ms": current_ms + duration,
        })
        current_ms += duration + 50  # 50ms gap between words
    return timings


def generate_voiceover_audio(text: str, output_path: Path) -> Tuple[Path, List[dict]]:
    """
    Convert text to speech and save as MP3.

    Returns:
        Tuple of (output_path, word_timings)
        word_timings: [{"word": str, "start_ms": int, "end_ms": int}, ...]
    """
    print(f"[TTS] Generating voiceover audio: {output_path.name}")

    word_timings = []
    try:
        # Try running in a new event loop (works when not inside an existing loop)
        word_timings = asyncio.run(_generate_tts_with_timing(text, output_path))
    except RuntimeError as e:
        # Already inside an event loop (e.g. FastAPI) — run in a thread
        print(f"[TTS] Event loop conflict ({e}), using thread fallback")
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, _generate_tts_with_timing(text, output_path))
            word_timings = future.result(timeout=120)
    except Exception as e:
        print(f"[TTS] TTS generation failed: {e}")

    # Check if audio file was actually created
    if not output_path.exists() or output_path.stat().st_size < 1000:
        print(f"[TTS] WARNING: Audio file is missing or too small ({output_path})")

    # If no word timings extracted, estimate from text
    if not word_timings:
        print(f"[TTS] No word boundaries from TTS, estimating timings from text")
        word_timings = _estimate_word_timings(text)

    print(f"[TTS] Extracted {len(word_timings)} word timings")
    return output_path, word_timings
