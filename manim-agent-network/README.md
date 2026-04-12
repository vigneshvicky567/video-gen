# Manim Agent Network 🚀

<p align="center">
  <img src="https://img.shields.io/badge/Architecture-Multi--Agent%20Microservices-blue?style=for-the-badge" alt="Architecture">
  <img src="https://img.shields.io/badge/Orchestration-LangGraph-green?style=for-the-badge" alt="Orchestration">
  <img src="https://img.shields.io/badge/Video-Manim%20CE-purple?style=for-the-badge" alt="Video">
  <img src="https://img.shields.io/badge/AI-Gemini-orange?style=for-the-badge" alt="AI">
</p>

A **production-grade, multi-agent microservice architecture** for generating mathematical and technical videos using **Manim Community Edition (CE)** and **Google Gemini**.

---

## 🎯 Overview

Manim Agent Network transforms a simple topic into a fully narrated, animated video through an intelligent multi-agent pipeline:

```
Topic → Script Writer → Code Generator → Validator → Voiceover → Assembler → Final Video
```

### Key Features

- **🤖 Multi-Agent Orchestration** — 6 independent microservices powered by LangGraph
- **🎬 Manim CE Integration** — Generate stunning mathematical animations
- **🔊 Multiple TTS Options** — Gemini 3.1 Pro, Flash, or local Coqui TTS with voice cloning
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
│  │   Gemini    │    │   Gemini    │    │  manim      │    │   Gemini    │  │
│  │   (Script)  │    │   (Code)    │    │  render     │    │   TTS /     │  │
│  │             │    │             │    │             │    │   Coqui     │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│                                                                     │        │
│                                                                     ▼        │
│                                                              ┌─────────────┐ │
│                                                              │  Assembler  │ │
│                                                              │  (ffmpeg)   │ │
│                                                              └─────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Services

| Service | Port | Responsibility |
|---------|------|----------------|
| **Orchestrator** | 8000 | LangGraph state machine, job management |
| **Script Writer** | 8001 | Generate narrative & scene plans (Gemini) |
| **Code Generator** | 8002 | Generate Manim CE Python code (Gemini) |
| **Validator** | 8003 | Execute `manim render`, capture errors |
| **Voiceover** | 8004 | Generate narration audio (Gemini/Coqui) |
| **Assembler** | 8005 | Merge video + audio into final .mp4 |

---

## 🚀 Quickstart

### Prerequisites

- Docker & Docker Compose
- Google Gemini API Key

### 1. Clone & Configure

```bash
git clone https://github.com/vigneshvicky567/video-gen.git
cd video-gen/manim-agent-network

# Edit .env with your API key
nano .env
```

```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
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
| `GEMINI_API_KEY` | - | **Required** - Your Gemini API key |
| `SCRIPT_WRITER_MODEL` | `gemini-2.5-flash` | Model for script generation |
| `CODE_GENERATOR_MODEL` | `gemini-2.5-flash` | Model for code generation |
| `VOICEOVER_MODEL` | `gemini-2.5-flash-tts` | TTS model for voiceover |
| `VOICEOVER_PROVIDER` | `gemini` | `gemini` or `coqui` |
| `COQUI_MODEL` | `xtts_v2` | Coqui TTS model name |
| `COQUI_REFERENCE_VOICE` | - | Path to reference voice file for cloning |

### Voiceover Providers

#### Gemini TTS (Default)
Uses Google's Gemini for high-quality TTS. Set models:
- `gemini-2.5-flash-tts` (fast, cost-effective)
- `gemini-3.1-pro` (highest quality)

#### Coqui TTS (Local)
Run TTS locally with voice cloning support:

```env
VOICEOVER_PROVIDER=coqui
COQUI_MODEL=xtts_v2
COQUI_REFERENCE_VOICE=/workspace/voice_samples/my_voice.wav
```

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
│   └── Dockerfile.assembler
│
├── services/                   # Microservice implementations
│   ├── orchestrator/
│   │   └── app/core/graph.py   # LangGraph workflow definition
│   ├── script-writer/          # Gemini-powered script generation
│   ├── code-generator          # Manim CE code generation
│   ├── validator/              # Render validation & error capture
│   ├── voiceover/              # TTS (Gemini/Coqui)
│   └── assembler/              # FFmpeg video assembly
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

- **Gemini**: Ensure API key has TTS quota
- **Coqui**: Ensure model is installed (`pip install TTS`)

### Out of Memory

Reduce render quality in validator:
```python
# In services/validator/app/main.py
cmd = ["manim", "render", "-ql", ...]  # -ql = low quality
```

---

## 📜 License

MIT License - See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- [Manim Community Edition](https://manim.community/) - Beautiful math animations
- [LangGraph](https://langchain-ai.github.io/langgraph/) - Agent orchestration
- [Google Gemini](https://gemini.google.com/) - AI powering the agents
- [Coqui TTS](https://github.com/coqui-ai/TTS) - Open-source TTS with voice cloning
