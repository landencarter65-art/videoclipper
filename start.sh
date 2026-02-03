#!/bin/sh

# Decode YouTube cookies from environment variable if set
if [ -n "$YOUTUBE_COOKIES_BASE64" ]; then
    echo "Decoding YouTube cookies from environment..."
    echo "$YOUTUBE_COOKIES_BASE64" | base64 -d > /app/cookies.txt
    echo "Cookies file created ($(wc -c < /app/cookies.txt) bytes)."
else
    echo "WARNING: YOUTUBE_COOKIES_BASE64 not set - YouTube may block downloads!"
fi

echo "Starting YouTube Auto Clipper API..."
exec uvicorn api:app --host 0.0.0.0 --port 7860
