FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    nodejs \
    npm \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
WORKDIR /app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create data directories with correct permissions
RUN mkdir -p downloads clips output music && \
    chown -R user:user /app

COPY --chown=user . .
RUN chmod +x start.sh

USER user

EXPOSE 7860

CMD ["./start.sh"]
