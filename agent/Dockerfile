FROM python:3.12-slim

# espeak-ng: Kokoro phonemization. curl: fetch model assets at build.
RUN apt-get update && apt-get install -y --no-install-recommends \
        espeak-ng curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the Kokoro model + voices into the image (no runtime download).
RUN mkdir -p models && \
    curl -sSL -o models/kokoro-v1.0.onnx \
        https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx && \
    curl -sSL -o models/voices-v1.0.bin \
        https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

COPY . .

# Pre-download Silero VAD + LiveKit turn-detector weights into the image.
RUN python agent.py download-files

ENV KOKORO_MODEL_PATH=/app/models/kokoro-v1.0.onnx \
    KOKORO_VOICES_PATH=/app/models/voices-v1.0.bin \
    PORT=8080

# `start` = production worker mode (connects out to LiveKit Cloud).
CMD ["python", "agent.py", "start"]
