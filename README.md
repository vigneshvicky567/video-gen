# Manim Video Generator (Multi-Agent System)

This project supersedes the `manim-video-generator` codebase by introducing a production-grade multi-agent system implemented using FastAPI, LangGraph, and Google Generative AI (Gemini).

It orchestrates multiple microservices to automatically generate Manim Community animations with voiceover narration.

## Architecture

1.  **Orchestrator Service:** Entry point. Accepts user prompt, manages LangGraph state, and coordinates tasks.
2.  **Script Writer Service:** Uses Gemini to draft narration and scene plans.
3.  **Manim Generator Service:** Uses Gemini to write valid Manim CE Python code.
4.  **Validator Service:** Runs `manim render` via subprocess to test the code. Implements a self-healing retry loop.
5.  **Voiceover Service:** Generates audio narration using `google-generativeai` (Gemini TTS) or `pyttsx3`.
6.  **Assembler Service:** Merges video and audio using `ffmpeg`.
7.  **Quality Review Service:** Verifies final output with `ffprobe`.

## Quickstart

```bash
docker-compose up --build
```
