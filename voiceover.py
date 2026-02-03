import asyncio
import edge_tts
from pathlib import Path
from config import TTS_VOICE


async def _generate_tts(text: str, output_path: Path):
    """Generate speech audio from text using edge-tts."""
    communicate = edge_tts.Communicate(
        text,
        voice=TTS_VOICE,
        rate="-5%",      # Slightly slower for clarity
        volume="+10%",   # Boost volume
        pitch="+0Hz",
    )
    await communicate.save(str(output_path))


def generate_voiceover_audio(text: str, output_path: Path) -> Path:
    """Convert text to speech and save as MP3. Returns the output path."""
    print(f"[TTS] Generating voiceover audio: {output_path.name}")
    asyncio.run(_generate_tts(text, output_path))
    return output_path
