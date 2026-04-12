# Reference Architecture: `rohitg00/manim-video-generator`

This document outlines the baseline approach used in the `rohitg00/manim-video-generator` repository, which this multi-agent microservice architecture supersedes.

## Original Approach
The original repository works as a direct pipeline script. It accepts a topic, queries an LLM to generate Manim CE Python code, and attempts to run it locally to produce a video.

### Core Workflow
1. **Prompting**: Takes a user topic (e.g., "The Pythagorean Theorem").
2. **LLM Code Generation**: Sends the prompt to an LLM (originally OpenAI/Anthropic/Gemini) to generate raw Python code utilizing the `manim` library. The prompt likely includes basic instructions on creating a `Scene`.
3. **Execution**: The script saves the generated code to a `.py` file and calls the `manim` CLI tool via `subprocess.run(["manim", "render", ...])`.
4. **Error Handling (Basic)**: If the render fails, it captures the error log and feeds it back to the LLM to rewrite the code.
5. **Output**: Produces a final `.mp4` file.

## Limitations of the Original Concept
- **Monolithic**: The entire process is a single sequential script, lacking scalability or separation of concerns.
- **Single Agent**: Relies on one generic LLM call to handle both the mathematical logic/storyboard and the complex Manim syntax.
- **No Voiceover / Audio Sync**: It primarily generates visual-only scenes without synchronized narration.
- **Fragile State**: State (retries, code output, logs) is managed in memory during a single script execution. If it fails, all progress is lost.

## How the New Architecture Supersedes It
Our new architecture transitions from a single script to a **Production-Grade Multi-Agent Network**:
- **Microservices**: Separation of concerns (Orchestrator, Script Writer, Manim Coder, Validator, Voiceover, Assembler). Each service can scale independently.
- **LangGraph Orchestration**: Robust state management (`TypedDict`) and directed acyclic graph (DAG) routing via LangGraph, enabling complex loops (like validation) and parallel execution.
- **Advanced Gemini Audio**: Utilizes Gemini 2.5 Flash TTS (and Piper fallback) for high-quality, expressive voiceovers synchronized with the visuals.
- **Shared Volume**: Persistent, robust file handling across services via a shared Docker volume (`/workspace`), completely removing large data payloads from HTTP requests.
- **Specialized Prompting**: The "Script Writer" focuses solely on the pedagogical structure and narration, passing a "Scene Plan" to the "Manim Coder", which focuses exclusively on Manim CE API syntax.
