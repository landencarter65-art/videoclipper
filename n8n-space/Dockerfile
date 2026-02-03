FROM docker.n8n.io/n8nio/n8n:latest

USER root

# n8n stores data here
RUN mkdir -p /home/node/.n8n && chown -R node:node /home/node

# Copy workflow to auto-import on startup
COPY workflow.json /home/node/workflow.json
COPY entrypoint.sh /home/node/entrypoint.sh
RUN chmod +x /home/node/entrypoint.sh

USER node

# n8n config
ENV N8N_PORT=7860 \
    N8N_PROTOCOL=https \
    GENERIC_TIMEZONE=Africa/Casablanca \
    N8N_DEFAULT_BINARY_DATA_MODE=filesystem \
    N8N_USER_FOLDER=/home/node/.n8n \
    N8N_RUNNERS_ENABLED=false \
    N8N_BLOCK_ENV_ACCESS_IN_NODE=false

# HF Spaces requirement
EXPOSE 7860

ENTRYPOINT ["/home/node/entrypoint.sh"]
