import json
import time
import os
import random
from pathlib import Path
from groq import Groq
import google.generativeai as genai
from config import GROQ_API_KEY, GROQ_MODEL, WHISPER_MODEL, NUM_CLIPS, CLIP_MIN_SECONDS, CLIP_MAX_SECONDS, GEMINI_API_KEY, GEMINI_MODEL

# ── Groq Client ─────────────────────────────────────────────
groq_client = None
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)
else:
    print("[WARNING] GROQ_API_KEY not set — Groq features will fail.")

# ── Gemini Client ───────────────────────────────────────────
gemini_configured = False
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_configured = True
else:
    print("[WARNING] GEMINI_API_KEY not set — Gemini features will fail.")


def _get_provider() -> str:
    """Randomly select between 'groq' and 'gemini' (50/50) if both are available."""
    if groq_client and gemini_configured:
        return random.choice(["groq", "gemini"])
    elif groq_client:
        return "groq"
    elif gemini_configured:
        return "gemini"
    else:
        return "none"


def transcribe_audio(audio_path: Path) -> str:
    """Use Groq's Whisper-large-v3 to get a timestamped transcript."""
    if not groq_client:
        raise RuntimeError("GROQ_API_KEY required for transcription (Whisper).")

    print(f"[AI-Groq] Transcribing audio with Whisper: {audio_path.name}")
    
    with open(audio_path, "rb") as file:
        transcription = groq_client.audio.transcriptions.create(
            file=(audio_path.name, file),
            model=WHISPER_MODEL,
            response_format="verbose_json",
        )
    
    # Format transcript with timestamps
    formatted_transcript = ""
    for segment in transcription.segments:
        start = segment['start']
        end = segment['end']
        text = segment['text']
        start_str = f"{int(start // 60):02d}:{int(start % 60):02d}"
        end_str = f"{int(end // 60):02d}:{int(end % 60):02d}"
        formatted_transcript += f"[{start_str} - {end_str}] {text}\n"
    
    return formatted_transcript


def select_best_clips(transcript: str, video_title: str, video_path: Path = None) -> list[dict]:
    """Pick the most engaging clips using either Groq (Llama 3) or Gemini (Flash)."""
    provider = _get_provider()
    print(f"[AI-{provider.title()}] Analyzing transcript for best clips...")

    # Truncate transcript to ~8K tokens (~20K chars) to stay under Groq's 12K TPM limit
    # Gemini Flash has a huge context window, but we keep it consistent for now.
    MAX_TRANSCRIPT_CHARS = 20000
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        print(f"[AI] Transcript too long ({len(transcript)} chars), truncating to {MAX_TRANSCRIPT_CHARS} chars")
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n... [TRANSCRIPT TRUNCATED]"

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
    
    response_text = ""
    try:
        if provider == "gemini":
            model = genai.GenerativeModel(GEMINI_MODEL)
            # Gemini typically wraps JSON in markdown blocks, we ask it not to, but handle it anyway
            result = model.generate_content(
                f"You are a viral video editor. Return only JSON.\n\n{prompt}",
                generation_config={"response_mime_type": "application/json"}
            )
            response_text = result.text
        else:
            # Groq
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": "You are a viral video editor. Return only JSON."}, 
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            response_text = response.choices[0].message.content

        # Clean potential markdown code blocks if the provider/model ignores instructions
        response_text = response_text.replace("```json", "").replace("```", "").strip()
        data = json.loads(response_text)
    
    except Exception as e:
        print(f"[AI-{provider.title()}] Error parsing JSON or API call: {e}")
        data = []
    
    # Extract list from various possible JSON structures
    clips_list = []
    if isinstance(data, list):
        clips_list = data
    elif isinstance(data, dict):
        if "clips" in data:
            clips_list = data["clips"]
        elif "segments" in data:
            clips_list = data["segments"]
        elif all(k.isdigit() or k.startswith("clip") for k in data.keys()):
            clips_list = list(data.values())
        else:
            # If it's a single clip object
            if "start_time" in data and "end_time" in data:
                clips_list = [data]
            else:
                clips_list = []

    # Final Fallback: If AI fails to find clips, pick a segment from the middle
    if not clips_list:
        print(f"[AI] [WARN] AI returned no valid clips, using robust fallback.")
        clips_list = [{
            "clip_number": 1,
            "start_time": "00:15",
            "end_time": "01:05",
            "title": video_title[:50],
            "reason": "AI fallback selection",
            "hook": "You need to see this!"
        }]
            
    return clips_list[:NUM_CLIPS]


def generate_voiceover_script(clip_transcript: str, clip_title: str, video_title: str) -> str:
    """Generate a commentary voiceover script using Llama 3 or Gemini."""
    provider = _get_provider()
    print(f"[AI-{provider.title()}] Generating voiceover script for: {clip_title}")

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
- Do NOT narrate or summarize what's happening
- DO add your own analysis, facts, or perspective
- Keep it concise — this plays OVER the original audio
- Sound natural, like a real commentator

Return ONLY the voiceover script text."""

    try:
        if provider == "gemini":
            model = genai.GenerativeModel(GEMINI_MODEL)
            result = model.generate_content(prompt)
            return result.text.strip()
        else:
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.9,
            )
            return response.choices[0].message.content.strip()
            
    except Exception as e:
        print(f"[AI-{provider.title()}] Voiceover generation failed: {e}")
        return "Check this out! What do you think about this moment? Let me know in the comments below!"


def generate_youtube_metadata(clip_title: str, clip_hook: str, video_title: str) -> dict:
    """Generate SEO-optimized YouTube title, description, and tags using Llama 3 or Gemini."""
    provider = _get_provider()
    print(f"[AI-{provider.title()}] Generating YouTube metadata for: {clip_title}")

    prompt = f"""You are a YouTube SEO expert specializing in Roblox gaming shorts.

ORIGINAL VIDEO: "{video_title}"
CLIP TITLE: "{clip_title}"
CLIP HOOK: "{clip_hook}"

Generate YouTube metadata for this short clip. Return ONLY valid JSON:
{{
  "title": "A catchy, clickbait-style YouTube title under 70 characters.",
  "description": "A YouTube description (3-5 lines) with hashtags.",
  "tags": ["tag1", "tag2", "tag3"]
}}"""

    response_text = ""
    try:
        if provider == "gemini":
            model = genai.GenerativeModel(GEMINI_MODEL)
            result = model.generate_content(
                f"You are a YouTube SEO expert. Return only JSON.\n\n{prompt}",
                generation_config={"response_mime_type": "application/json"}
            )
            response_text = result.text
        else:
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": "You are a YouTube SEO expert. Return only JSON."}, 
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
                response_format={"type": "json_object"}
            )
            response_text = response.choices[0].message.content
        
        # Cleanup
        response_text = response_text.replace("```json", "").replace("```", "").strip()
        return json.loads(response_text)

    except Exception as e:
        print(f"[AI-{provider.title()}] Metadata generation failed: {e}")
        return {
            "title": clip_title[:70],
            "description": f"#shorts #roblox #gaming\n\nOriginal video: {video_title}",
            "tags": ["roblox", "gaming", "shorts", "clips"]
        }


def timestamp_to_seconds(ts: str) -> float:
    """Convert MM:SS or HH:MM:SS to seconds."""
    parts = ts.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0.0
