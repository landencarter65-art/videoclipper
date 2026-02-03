#!/bin/sh
echo "Starting YouTube Auto Clipper API..."
exec uvicorn api:app --host 0.0.0.0 --port 7860
