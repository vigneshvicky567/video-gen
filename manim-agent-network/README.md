# Manim Agent Network

A production-grade, multi-agent microservice architecture for generating mathematical and technical videos using Manim Community Edition (CE) and Google Gemini.

## Architecture
The system consists of 6 independent FastAPI microservices orchestrated by LangGraph:
1. **Orchestrator**: Manages state transitions and asynchronous HTTP routing.
2. **Script Writer**: Uses Gemini to generate narrative and scene plans.
3. **Code Generator**: Generates Manim CE Python code based on scene instructions (with context-aware retry capabilities).
4. **Validator**: Executes `manim render` locally, capturing stdout/stderr to feed back to the LLM if it fails.
5. **Voiceover**: Uses Gemini TTS (or local `espeak` fallback) to generate narration audio.
6. **Assembler**: Uses `ffmpeg` to merge video clips and audio tracks into a final `.mp4`.

## Setup & Run

### Prerequisites
- Docker and Docker Compose
- A Google Gemini API Key

### Quickstart

1. Configure Environment variables:
   Ensure your `.env` file contains your Gemini API key:
   ```bash
   GEMINI_API_KEY=your_actual_key_here
   ```

2. Build the Multi-Container application:
   ```bash
   make build
   ```

3. Run the application:
   ```bash
   make run
   ```

4. Trigger a Generation Job:
   ```bash
   curl -X POST http://localhost:8000/generate \
        -H "Content-Type: application/json" \
        -d '{"topic": "The Pythagorean Theorem visually explained"}'
   ```
   This will return a `job_id`.

5. Check Job Status:
   ```bash
   curl http://localhost:8000/job/<job_id>
   ```

6. Final Output:
   Once the job status is `completed`, your final `.mp4` video will be available in the shared `workspace/outputs/` directory.

### Monitoring Logs
To monitor the agent transitions and subprocess executions, run:
```bash
make logs
```

## Directory Structure
- `shared/`: Common Pydantic schemas, config, and LangGraph typed dict states.
- `services/`: Individual FastAPI apps for each domain.
- `workspace/`: Shared Docker volume used for passing `.py`, `.mp4`, and `.wav` files between services.
