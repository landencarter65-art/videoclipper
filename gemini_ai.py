import json
import time
from pathlib import Path
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GEMINI_MODEL, NUM_CLIPS, CLIP_MIN_SECONDS, CLIP_MAX_SECONDS

client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    print("[WARNING] GEMINI_API_KEY not set — AI features will fail until configured.")


def transcribe_audio(audio_path: Path) -> str:
    """Upload audio to Gemini and get a timestamped transcript."""
    print(f"[AI] Uploading audio for transcription: {audio_path.name}")
    audio_file = client.files.upload(file=str(audio_path))

    # Wait for file to be processed
    while audio_file.state.name == "PROCESSING":
        time.sleep(5)
        audio_file = client.files.get(name=audio_file.name)

    if audio_file.state.name == "FAILED":
        raise RuntimeError("Gemini file upload failed")

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            audio_file,
            """Transcribe this audio with precise timestamps.
Format each segment as:
[MM:SS - MM:SS] Text spoken in this segment

Be very precise with timestamps. Include every spoken word.
Group text into natural segments of 5-15 seconds each.""",
        ],
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=8192,
        ),
    )

    # Clean up uploaded file
    try:
        client.files.delete(name=audio_file.name)
    except Exception:
        pass

    return response.text


def select_best_clips(transcript: str, video_title: str) -> list[dict]:
    """Use Gemini to pick the most engaging clips from the transcript."""
    print("[AI] Analyzing transcript for best clips...")

    prompt = f"""You are a viral video editor. Analyze this transcript from the video titled "{video_title}".

TRANSCRIPT:
{transcript}

Find the {NUM_CLIPS} most engaging, viral-worthy segments. Each clip must be {CLIP_MIN_SECONDS}-{CLIP_MAX_SECONDS} seconds long.

Look for moments that are:
- Emotionally intense or surprising
- Contains a complete thought or story beat
- Would hook a viewer scrolling on social media
- Has a strong opening line

Return ONLY valid JSON (no markdown, no code blocks), an array of objects:
[
  {{
    "clip_number": 1,
    "start_time": "MM:SS",
    "end_time": "MM:SS",
    "title": "Short catchy title for this clip",
    "reason": "Why this segment is engaging",
    "hook": "The opening line that grabs attention"
  }}
]"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=2048,
        ),
    )

    text = response.text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    clips = json.loads(text)
    return clips


def generate_voiceover_script(clip_transcript: str, clip_title: str, video_title: str) -> str:
    """Generate a commentary voiceover script that adds value and transforms the content."""
    print(f"[AI] Generating voiceover script for: {clip_title}")

    prompt = f"""You are a professional video commentator creating transformative content.

ORIGINAL VIDEO: "{video_title}"
CLIP: "{clip_title}"
CLIP TRANSCRIPT:
{clip_transcript}

Write a SHORT voiceover commentary script (4-6 sentences) that:
1. Opens with a hook that adds YOUR perspective (don't repeat what's said in the clip)
2. Adds analysis, context, or insight that the original doesn't provide
3. Shares an opinion or reaction that makes this YOUR content
4. Ends with a thought-provoking statement or call to engagement

RULES:
- Do NOT narrate or summarize what's happening — the viewer can see/hear that
- DO add your own analysis, facts, or perspective
- Keep it concise — this plays OVER the original audio
- Sound natural, like a real commentator, not robotic
- Use conversational tone

Return ONLY the voiceover script text, nothing else."""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.9,
            max_output_tokens=1024,
        ),
    )

    return response.text.strip()


def generate_youtube_metadata(clip_title: str, clip_hook: str, video_title: str) -> dict:
    """Generate SEO-optimized YouTube title, description, and tags for a clip."""
    print(f"[AI] Generating YouTube metadata for: {clip_title}")

    prompt = f"""You are a YouTube SEO expert specializing in Roblox gaming shorts.

ORIGINAL VIDEO: "{video_title}"
CLIP TITLE: "{clip_title}"
CLIP HOOK: "{clip_hook}"

Generate YouTube metadata for this short clip. Return ONLY valid JSON (no markdown, no code blocks):
{{
  "title": "A catchy, clickbait-style YouTube title under 70 characters. Use caps for emphasis. Include relevant keywords like Roblox.",
  "description": "A YouTube description (3-5 lines) with:\n- Line 1: Hook sentence\n- Line 2: What happens in the clip\n- Line 3: Call to action (like, subscribe, comment)\n- Line 4-5: Hashtags (at least 8, mix of broad and niche Roblox tags)",
  "tags": ["tag1", "tag2", "tag3", "up to 15 relevant tags for YouTube search SEO, mix of broad gaming tags and specific Roblox tags"]
}}"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.8,
            max_output_tokens=1024,
        ),
    )

    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    return json.loads(text)


def timestamp_to_seconds(ts: str) -> float:
    """Convert MM:SS or HH:MM:SS to seconds."""
    parts = ts.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0.0
