# AI Coding Agent Instructions

## Project Overview

**manim-agent-network** is a multi-agent microservice architecture for generating mathematical videos using Manim CE + AI (OpenAI/Gemini).

```
Topic → Script Writer → Code Generator → Validator → Voiceover → Assembler → Video
```

## Architecture

- **6 microservices** on ports 8000-8005
- **LangGraph** orchestration in `services/orchestrator/app/core/graph.py`
- **Shared state** via `LangGraphState` TypedDict in `shared/models/agent_state.py`
- **Config** centralized in `shared/config.py`

## Key Files

| File | Purpose |
|------|---------|
| `services/orchestrator/app/core/graph.py` | LangGraph workflow definition |
| `shared/models/agent_state.py` | State schema (job_id, script, code_paths, etc.) |
| `shared/config.py` | Settings (API keys, models, timeouts) |
| `docker-compose.yml` | Service orchestration |
| `Makefile` | Build/run shortcuts |

## Important Patterns

### Adding a New Service
1. Create `services/<name>/app/main.py` with FastAPI
2. Add Dockerfile in `infrastructure/docker/`
3. Register in `docker-compose.yml` (port, env vars)
4. Add node to LangGraph in `graph.py`

### LangGraph Node Pattern
```python
async def my_node(state: LangGraphState):
    # Call service via HTTP
    result = await _post(f"{settings.SERVICE_URL}/endpoint", {...})
    # Return state updates
    return {"key": "value", "status": "step_name"}
```

### API Key Configuration
- **OpenAI**: Set `OPENAI_API_KEY` in `.env`, models: `gpt-4o`, `tts-1-hd`
- **Gemini**: Set `GEMINI_API_KEY` (commented out by default)
- **LangSmith**: Set `LANGSMITH_API_KEY` for tracing

## Commands

```bash
make build    # Build Docker images (uses uv)
make run      # Start all services
make logs     # View logs
curl -X POST http://localhost:8000/generate -d '{"topic": "..."}'
```

## Current Tech Stack

- **LLM**: OpenAI `gpt-4o` (configurable in `.env`)
- **TTS**: OpenAI `tts-1-hd` (or `tts-1`)
- **Video**: Manim CE
- **Orchestration**: LangGraph
- **Package Manager**: uv (in Docker)
