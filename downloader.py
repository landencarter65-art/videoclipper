import json
import random
import subprocess
import feedparser
from pathlib import Path
from config import CHANNEL_IDS, DOWNLOADS_DIR, DB_PATH, MUSIC_DIR, MUSIC_PLAYLIST_URL, BASE_DIR


def load_processed():
    if DB_PATH.exists():
        return json.loads(DB_PATH.read_text())
    return []


def save_processed(video_ids):
    DB_PATH.write_text(json.dumps(video_ids))


def get_latest_video_from_channel(channel_id: str) -> dict | None:
    """Fetch the most recent video from a YouTube channel.
    Tries yt-dlp first (more reliable from cloud), falls back to RSS."""

    # Check for cookies file to avoid rate limits
    cookies_path = BASE_DIR / "cookies.txt"
    cookies_args = ["--cookies", str(cookies_path)] if cookies_path.exists() else []

    # Method 1: yt-dlp (works better from cloud IPs)
    try:
        channel_url = f"https://www.youtube.com/channel/{channel_id}/videos"
        cmd = [
            "yt-dlp",
            *cookies_args,
            "--flat-playlist",
            "--playlist-items", "1",
            "--print", "%(id)s",
            "--print", "%(title)s",
            "--print", "%(url)s",
            "--no-warnings",
            "--extractor-args", "youtube:player_client=web",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            channel_url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 3:
                video_id = lines[0].strip()
                title = lines[1].strip()
                url = lines[2].strip()
                if not url.startswith("http"):
                    url = f"https://www.youtube.com/watch?v={video_id}"
                print(f"  [yt-dlp] Found: {title} ({video_id})")
                return {
                    "video_id": video_id,
                    "title": title,
                    "url": url,
                    "published": "",
                }
    except Exception as e:
        print(f"  [yt-dlp] Failed for {channel_id}: {e}")

    # Method 2: RSS fallback
    try:
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        feed = feedparser.parse(feed_url)
        if feed.entries:
            entry = feed.entries[0]
            print(f"  [RSS] Found: {entry['title']} ({entry['yt_videoid']})")
            return {
                "video_id": entry["yt_videoid"],
                "title": entry["title"],
                "url": entry["link"],
                "published": entry.get("published", ""),
            }
        else:
            print(f"  [RSS] No entries for channel {channel_id}")
    except Exception as e:
        print(f"  [RSS] Failed for {channel_id}: {e}")

    print(f"  [WARN] Could not fetch any video for channel {channel_id}")
    return None


def check_new_videos() -> list[dict]:
    """Check all monitored channels for new (unprocessed) videos."""
    print(f"[CHECK] Checking {len(CHANNEL_IDS)} channels...")
    processed = load_processed()
    print(f"[CHECK] Already processed: {len(processed)} videos")
    new_videos = []

    for channel_id in CHANNEL_IDS:
        print(f"[CHECK] Checking channel: {channel_id}")
        video = get_latest_video_from_channel(channel_id)
        if video:
            if video["video_id"] not in processed:
                print(f"  → NEW: {video['title']}")
                new_videos.append(video)
            else:
                print(f"  → Already processed: {video['title']}")
        else:
            print(f"  → No video found")

    print(f"[CHECK] Found {len(new_videos)} new videos")
    return new_videos


def mark_processed(video_id: str):
    processed = load_processed()
    processed.append(video_id)
    save_processed(processed[-500:])


def download_video(video_url: str) -> Path:
    """Download video using yt-dlp at best quality. Returns path to downloaded file."""
    # Clean old downloads first
    for f in DOWNLOADS_DIR.glob("*.mp4"):
        try:
            f.unlink()
        except Exception:
            pass

    output_template = str(DOWNLOADS_DIR / "%(id)s.%(ext)s")
    
    cookies_path = BASE_DIR / "cookies.txt"
    cookies_args = ["--cookies", str(cookies_path)] if cookies_path.exists() else []

    cmd = [
        "yt-dlp",
        *cookies_args,
        "--format", "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "--merge-output-format", "mp4",
        "--output", output_template,
        "--no-playlist",
        video_url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr}")

    for f in DOWNLOADS_DIR.glob("*.mp4"):
        return f

    raise FileNotFoundError("Downloaded video not found")


def download_random_music() -> Path:
    """Download a random track from the background music playlist."""
    print("[MUSIC] Fetching playlist info...")

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--print", "url",
        MUSIC_PLAYLIST_URL,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp playlist fetch failed: {result.stderr}")

    urls = [u.strip() for u in result.stdout.strip().split("\n") if u.strip()]
    if not urls:
        raise RuntimeError("No tracks found in music playlist")

    track_url = random.choice(urls)
    print(f"[MUSIC] Downloading random track from playlist ({len(urls)} tracks available)")

    output_template = str(MUSIC_DIR / "bg_music.%(ext)s")

    for f in MUSIC_DIR.glob("*"):
        try:
            f.unlink()
        except Exception:
            pass

    cmd = [
        "yt-dlp",
        "--format", "bestaudio",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--output", output_template,
        "--no-playlist",
        track_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp music download failed: {result.stderr}")

    for f in MUSIC_DIR.glob("*.mp3"):
        print(f"[MUSIC] Downloaded: {f.name}")
        return f

    raise FileNotFoundError("Downloaded music file not found")


def extract_audio(video_path: Path) -> Path:
    """Extract audio from video for transcription."""
    audio_path = video_path.with_suffix(".wav")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(audio_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return audio_path
