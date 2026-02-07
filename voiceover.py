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
        rate="-5%",      # Slightly slower for clarity
        volume="+10%",   # Boost volume
        pitch="+0Hz",
    )

    word_timings = []

    # Stream audio and collect word boundaries
    with open(output_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] in ["WordBoundary", "word_boundary"]:
                # Extract timing - offset and duration are in 100-nanosecond units
                # Some versions of edge-tts use different casing
                start_ms = chunk.get("offset", 0) // 10000  # Convert to milliseconds
                duration_ms = chunk.get("duration", 0) // 10000
                end_ms = start_ms + duration_ms

                word_timings.append({
                    "word": chunk.get("text", ""),
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                })

    return word_timings


def generate_voiceover_audio(text: str, output_path: Path) -> Tuple[Path, List[dict]]:
    """
    Convert text to speech and save as MP3.

    Returns:
        Tuple of (output_path, word_timings)
        word_timings: [{"word": str, "start_ms": int, "end_ms": int}, ...]
    """
    print(f"[TTS] Generating voiceover audio: {output_path.name}")
    try:
        # If already inside an event loop (e.g. FastAPI/uvicorn), use nest_asyncio or thread
        loop = asyncio.get_running_loop()
        # Running inside an existing loop — run TTS in a separate thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            word_timings = pool.submit(
                asyncio.run, _generate_tts_with_timing(text, output_path)
            ).result()
    except RuntimeError:
        # No running loop — safe to use asyncio.run()
        word_timings = asyncio.run(_generate_tts_with_timing(text, output_path))
    print(f"[TTS] Extracted {len(word_timings)} word timings")
    return output_path, word_timings
