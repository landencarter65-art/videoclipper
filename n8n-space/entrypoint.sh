#!/bin/sh
# Import workflow on startup
echo "Importing workflow from /home/node/workflow.json..."
n8n import:workflow --input=/home/node/workflow.json

# Start n8n
exec n8n start