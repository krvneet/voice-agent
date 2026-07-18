FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Pre-download Silero VAD weights into the image (STT/LLM/TTS + turn detection
# all run via LiveKit Inference, so no local model files are needed for them).
RUN python agent.py download-files

ENV PORT=8080

# `start` = production worker mode (connects out to LiveKit Cloud).
CMD ["python", "agent.py", "start"]
