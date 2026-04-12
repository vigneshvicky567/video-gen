FROM python:3.10-slim-bullseye

# System dependencies for Manim, FFmpeg, and pyttsx3
RUN apt-get update && apt-get install -y \
    build-essential \
    libcairo2-dev \
    libpango1.0-dev \
    libgif-dev \
    texlive-latex-base \
    texlive-fonts-recommended \
    texlive-latex-recommended \
    texlive-latex-extra \
    cm-super \
    ffmpeg \
    espeak \
    alsa-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure the workspace directory is created and accessible
RUN mkdir -p /workspace && chmod -R 777 /workspace

ENV PYTHONPATH=/app
