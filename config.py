import os
from pathlib import Path

# ── Gemini API ──────────────────────────────────────────────
# Stored as HF Space secret "GEMINI_API_KEY" — never hardcode
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── Groq API ────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
WHISPER_MODEL = "whisper-large-v3"

# Use the strongest free model
GEMINI_MODEL = "gemini-2.0-flash"

# ── YouTube Channels to Monitor ─────────────────────────────
# Stored as HF Space secret "CHANNEL_IDS" (comma-separated)
# Example: "UCxxxxxx,UCyyyyyy,UCzzzzzz"
_raw_channels = os.getenv("CHANNEL_IDS", "")
CHANNEL_IDS = [c.strip() for c in _raw_channels.split(",") if c.strip()]

# ── API Auth ────────────────────────────────────────────────
# Shared secret between n8n and this API — set as HF Space secret
API_SECRET = os.getenv("API_SECRET", "")

# ── Clip Settings ───────────────────────────────────────────
NUM_CLIPS = 1
CLIP_MIN_SECONDS = 30
CLIP_MAX_SECONDS = 60    # Max 60 seconds per clip

# ── Background Music ───────────────────────────────────────
# NCS / copyright-free playlist — a random track is picked each run
MUSIC_PLAYLIST_URL = "https://www.youtube.com/watch?v=zeKCzmAKKP4&list=PLGBKsNyGY-afmc5ff3n1HOYGTmZO1xJGw"
MUSIC_VOLUME = "0.10"    # Background music at 10% (subtle, behind voiceover)

# ── Voice Settings (edge-tts) ──────────────────────────────
TTS_VOICE = "en-US-GuyNeural"

# ── FFmpeg Quality ──────────────────────────────────────────
# HF free tier has 2 vCPU — use "medium" preset to avoid timeout
VIDEO_CODEC = "libx264"
VIDEO_CRF = "23"
VIDEO_PRESET = "faster"
AUDIO_BITRATE = "192k"
ORIGINAL_AUDIO_VOLUME = "0.15"

# ── Output Resolution (9:16 vertical) ─────────────────────
OUTPUT_WIDTH = 720
OUTPUT_HEIGHT = 1280

# ── Subtitle Style Presets ─────────────────────────────────
SUBTITLE_STYLES = {
    "classic": {
        "font": "Montserrat-Bold",
        "font_size": 12,
        "primary_color": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "outline": 1,
        "shadow": 1,
        "bold": 1,
        "alignment": 2,
        "margin_v": 100,
    },
    "neon": {
        "font": "Impact",
        "font_size": 22,
        "primary_color": "&H00FFFF00",
        "outline_color": "&H00FF00FF",
        "back_color": "&H00000000",
        "outline": 5,
        "shadow": 3,
        "bold": 1,
        "alignment": 2,
        "margin_v": 100,
    },
    "yellow": {
        "font": "Montserrat-Bold",
        "font_size": 22,
        "primary_color": "&H0000FFFF",
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "outline": 5,
        "shadow": 3,
        "bold": 1,
        "alignment": 2,
        "margin_v": 100,
    },
    "fire": {
        "font": "Impact",
        "font_size": 22,
        "primary_color": "&H000080FF",
        "outline_color": "&H00000080",
        "back_color": "&H00000000",
        "outline": 4,
        "shadow": 2,
        "bold": 1,
        "alignment": 2,
        "margin_v": 110,
    },
    "mrbeast": {
        "font": "Impact",
        "font_size": 22,
        "primary_color": "&H0000FF00",
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "outline": 6,
        "shadow": 4,
        "bold": 1,
        "alignment": 2,
        "margin_v": 80,
    },
    "minimal": {
        "font": "Helvetica-Bold",
        "font_size": 22,
        "primary_color": "&H00FFFFFF",
        "outline_color": "&H80000000",
        "back_color": "&H00000000",
        "outline": 2,
        "shadow": 0,
        "bold": 1,
        "alignment": 2,
        "margin_v": 150,
    },
    "boxed": {
        "font": "Roboto-Bold",
        "font_size": 22,
        "primary_color": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "back_color": "&HCC000000",
        "outline": 0,
        "shadow": 0,
        "bold": 1,
        "alignment": 2,
        "margin_v": 130,
    },
    "aesthetic": {
        "font": "Georgia-Bold",
        "font_size": 22,
        "primary_color": "&H00CBC0FF",
        "outline_color": "&H00800080",
        "back_color": "&H00000000",
        "outline": 3,
        "shadow": 2,
        "bold": 1,
        "alignment": 2,
        "margin_v": 140,
    },
}

SELECTED_STYLE = "boxed"
SUBTITLE_STYLE = SUBTITLE_STYLES[SELECTED_STYLE]

# ── Paths ───────────────────────────────────────────────────
# HF Spaces writable dir is /tmp or the app directory
BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
CLIPS_DIR = BASE_DIR / "clips"
OUTPUT_DIR = BASE_DIR / "output"
DB_PATH = BASE_DIR / "processed_videos.json"

MUSIC_DIR = BASE_DIR / "music"
MUSIC_LIBRARY_DIR = BASE_DIR / "music_library"

for d in [DOWNLOADS_DIR, CLIPS_DIR, OUTPUT_DIR, MUSIC_DIR]:
    d.mkdir(exist_ok=True)
