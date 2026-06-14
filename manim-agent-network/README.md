# Manim Agent Network 🚀

<p align="center">
  <img src="https://img.shields.io/badge/Architecture-Multi--Agent%20Microservices-blue?style=for-the-badge" alt="Architecture">
  <img src="https://img.shields.io/badge/Orchestration-LangGraph-green?style=for-the-badge" alt="Orchestration">
  <img src="https://img.shields.io/badge/Video-Manim%20CE-purple?style=for-the-badge" alt="Video">
  <img src="https://img.shields.io/badge/AI-NVIDIA%20NIM-orange?style=for-the-badge" alt="AI">
</p>

A **production-grade, multi-agent microservice architecture** for generating mathematical and technical videos using **Manim Community Edition (CE)** and NVIDIA NIM.

---

## 🎯 Overview

Manim Agent Network transforms a simple topic into a fully narrated, animated video through an intelligent multi-agent pipeline:

```
Topic → Script Writer → Code Generator → Validator → Voiceover → Compositor → Final Video
```

### Key Features

- **🤖 Multi-Agent Orchestration** — 6 independent microservices powered by LangGraph
- **🎬 Manim CE Integration** — Generate stunning mathematical animations
- **🔊 Local Voiceover** — Kokoro ONNX (CPU, offline) with automatic retry
- **♻️ Self-Healing** — Automatic retry with error feedback for failed renders
- **🐳 Docker-Ready** — Full containerization with docker-compose

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ORCHESTRATOR (LangGraph)                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │   Script    │───▶│    Code     │───▶│  Validator  │───▶│  Voiceover  │  │
│  │   Writer    │    │  Generator  │    │             │    │             │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│        │                  │                  │                  │          │
│        ▼                  ▼                  ▼                  ▼          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │ NVIDIA NIM  │    │ NVIDIA NIM  │    │  manim      │    │  Kokoro     │  │
│  │   (Script)  │    │   (Code)    │    │  render     │    │   ONNX TTS  │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│                                                                     │        │
│                                                                     ▼        │
│                                                              ┌─────────────┐ │
│                                                              │ Compositor  │ │
│                                                              │  (ffmpeg)   │ │
│                                                              └─────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Services

| Service | Port | Responsibility |
|---------|------|----------------|
| **Orchestrator** | 8000 | LangGraph state machine, job management |
| **Script Writer** | 8001 | Generate narrative & scene plans with NVIDIA NIM |
| **Code Generator** | 8002 | Generate Manim CE Python/HyperFrames code with NVIDIA NIM |
| **Validator** | 8003 | Execute `manim render`, capture errors |
| **Voiceover** | 8004 | Generate local narration audio (Kokoro ONNX) |
| **Compositor** | 8005 | Compose HyperFrames HTML timeline, render & assemble final .mp4 |

---

## 🚀 Quickstart

### Prerequisites

- Docker & Docker Compose
- NVIDIA NIM API key

### 1. Clone & Configure

```bash
git clone https://github.com/vigneshvicky567/video-gen.git
cd video-gen/manim-agent-network

# Edit .env with your API key
nano .env
```

```env
NVIDIA_API_KEY=your_actual_nvidia_api_key_here
```

### 2. Build & Run

```bash
make build    # Build Docker images
make run      # Start all services
```

### 3. Generate a Video

```bash
# Trigger generation
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"topic": "The Pythagorean Theorem visually explained"}'

# Response: {"job_id": "abc-123", "message": "Generation started."}

# Check status
curl http://localhost:8000/job/abc-123

# Monitor logs
make logs
```

### 4. Output

Once status is `completed`, find your video at:
```
workspace/outputs/<job_id>_final.mp4
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NVIDIA_API_KEY` | - | **Required** - Your NVIDIA NIM API key |
| `SCRIPT_WRITER_MODEL` | `moonshotai/kimi-k2-instruct` | Model for script generation |
| `CODE_GENERATOR_MODEL` | `moonshotai/kimi-k2-instruct` | Model for code generation |
| `VOICEOVER_PROVIDER` | `kokoro` | TTS provider (Kokoro ONNX) |
| `VOICEOVER_MAX_RETRIES` | `3` | Kokoro retry attempts on failure |
| `KOKORO_VOICE` | `af_sarah` | Kokoro narrator voice |

### Voiceover Providers

#### Kokoro ONNX (Primary, CPU-capable, offline)
Preinstalled in the Docker image, no GPU needed:

```env
VOICEOVER_PROVIDER=kokoro
KOKORO_VOICE=af_sarah
```

On failure, Kokoro is retried up to `VOICEOVER_MAX_RETRIES` times (default 3,
`VOICEOVER_RETRY_BACKOFF_SECONDS` seconds apart). There is no fallback engine.

---

## 📁 Project Structure

```
manim-agent-network/
├── docker-compose.yml          # Multi-container orchestration
├── Makefile                    # Build/run shortcuts
├── requirements.txt            # Python dependencies
├── .env                        # Environment configuration
│
├── infrastructure/docker/      # Dockerfiles for each service
│   ├── Dockerfile.base         # Base image with dependencies
│   ├── Dockerfile.orchestrator
│   ├── Dockerfile.script-writer
│   ├── Dockerfile.code-generator
│   ├── Dockerfile.validator
│   ├── Dockerfile.voiceover
│   └── Dockerfile.compositor
│
├── services/                   # Microservice implementations
│   ├── orchestrator/
│   │   └── app/core/graph.py   # LangGraph workflow definition
│   ├── script-writer/          # NVIDIA NIM-powered script generation
│   ├── code-generator          # Manim CE code generation
│   ├── validator/              # Render validation & error capture
│   ├── voiceover/              # Local TTS (Kokoro ONNX)
│   └── compositor/             # HyperFrames HTML composition & render
│
├── shared/                     # Common code across services
│   ├── config.py               # Settings management
│   ├── models/agent_state.py   # LangGraph TypedDict state
│   └── schemas/                # Pydantic request/response models
│
└── workspace/                  # Shared volume for file passing
    ├── temp/                   # Intermediate files (py, mp4, wav)
    └── outputs/                # Final rendered videos
```

---

## 🔧 Development

### Running Tests

```bash
# Test a specific service
docker-compose exec script-writer python -m pytest

# Or run locally
pip install -r requirements.txt
python -m pytest services/script-writer/
```

### Adding a New Service

1. Create `services/<service-name>/app/main.py`
2. Add Dockerfile in `infrastructure/docker/`
3. Register in `docker-compose.yml`
4. Add node to LangGraph in `services/orchestrator/app/core/graph.py`

---

## 🐛 Troubleshooting

### Manim Render Fails

The validator captures stderr and feeds it back to the code generator for retry (up to 3 attempts). Check logs:

```bash
make logs | grep -i error
```

### TTS Issues

- **Kokoro**: Rebuild the voiceover image if `/models/kokoro` assets are missing:
  ```bash
  docker compose build voiceover
  docker compose up -d voiceover
  ```

### Out of Memory

Reduce render quality in validator:
```python
# In services/validator/app/main.py
cmd = ["manim", "render", "-qm", ...]  # -qm = 720p30 landscape
```

---

## 📜 License

MIT License - See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- [Manim Community Edition](https://manim.community/) - Beautiful math animations
- [LangGraph](https://langchain-ai.github.io/langgraph/) - Agent orchestration
- [NVIDIA NIM](https://build.nvidia.com/) - LLM inference for the agents
- [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx) - Lightweight offline TTS
