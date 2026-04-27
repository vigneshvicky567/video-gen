# Requirements Document

## Introduction

This feature covers the end-to-end process a new developer follows to bootstrap the **Manim Agent Network** project from a fresh clone to a fully operational state. The project is a multi-agent microservice system that uses LangGraph, FastAPI, Docker, and OpenAI to generate animated math/technical videos. The initialization process includes verifying system prerequisites, configuring environment variables, building Docker images, starting all six microservices, and validating that the pipeline is healthy and ready to accept video generation requests.

---

## Glossary

- **Developer**: A human operator setting up the project for the first time on a local or CI machine.
- **Setup_Tool**: The collection of shell commands, Makefile targets, and scripts used to initialize the project (e.g., `make build`, `make run`).
- **Env_File**: The `.env` file at the project root (`video-gen/manim-agent-network/.env`) that holds all runtime secrets and configuration values.
- **Orchestrator**: The FastAPI service running on port 8000 that manages the LangGraph state machine and exposes `/generate`, `/job/{job_id}`, and `/health` endpoints.
- **Agent_Service**: Any one of the six Docker-containerized microservices: Orchestrator (8000), Script-Writer (8001), Code-Generator (8002), Validator (8003), Voiceover (8004), Assembler (8005).
- **Base_Image**: The Docker image built from `infrastructure/docker/Dockerfile.base` that all Agent_Services depend on.
- **Workspace_Volume**: The shared Docker volume mounted at `/workspace` inside containers and at `./workspace` on the host, used for passing intermediate and final files between Agent_Services.
- **Health_Endpoint**: The `GET /health` HTTP endpoint exposed by each Agent_Service that returns `{"status": "ok"}` when the service is ready.
- **Validation_Script**: A developer-executable script or sequence of commands that confirms all Agent_Services are healthy and the pipeline can accept a request.
- **OPENAI_API_KEY**: The required OpenAI API key used by Orchestrator, Script-Writer, Code-Generator, and Voiceover services.
- **LANGSMITH_API_KEY**: The optional LangSmith tracing API key used by Orchestrator, Script-Writer, Code-Generator, and Voiceover services.

---

## Requirements

### Requirement 1: System Prerequisites Verification

**User Story:** As a Developer, I want to verify that all required system tools are installed before attempting setup, so that I receive clear guidance when my environment is missing a dependency.

#### Acceptance Criteria

1. THE Setup_Tool SHALL verify that Docker Engine version 20.10 or later is installed and accessible on the host system.
2. THE Setup_Tool SHALL verify that Docker Compose version 2.0 or later is installed and accessible on the host system.
3. THE Setup_Tool SHALL verify that Git version 2.0 or later is installed and accessible on the host system.
4. IF Docker Engine is not found or is below the minimum version, THEN THE Setup_Tool SHALL display a human-readable error message specifying the missing tool, the required minimum version, and a URL to the official installation guide.
5. IF Docker Compose is not found or is below the minimum version, THEN THE Setup_Tool SHALL display a human-readable error message specifying the missing tool, the required minimum version, and a URL to the official installation guide.
6. IF Git is not found or is below the minimum version, THEN THE Setup_Tool SHALL display a human-readable error message specifying the missing tool, the required minimum version, and a URL to the official installation guide.
7. WHEN all prerequisite checks pass, THE Setup_Tool SHALL display a confirmation message listing each verified tool and its detected version.

---

### Requirement 2: Repository Acquisition

**User Story:** As a Developer, I want clear instructions for cloning the repository and navigating to the correct working directory, so that I start setup from the right location.

#### Acceptance Criteria

1. THE Setup_Tool SHALL document the exact `git clone` command required to obtain the repository, including the full repository URL.
2. THE Setup_Tool SHALL document the exact directory path (`video-gen/manim-agent-network`) the Developer must navigate to before running any subsequent setup commands.
3. WHEN the Developer is already inside the `video-gen/manim-agent-network` directory, THE Setup_Tool SHALL accept all subsequent commands without requiring path qualification.

---

### Requirement 3: Environment Configuration

**User Story:** As a Developer, I want a guided process for creating and populating the `.env` file, so that all required secrets and configuration values are set before services start.

#### Acceptance Criteria

1. THE Setup_Tool SHALL provide a template `.env` file at the project root containing all supported environment variable keys with placeholder values and inline comments describing each variable's purpose.
2. THE Env_File SHALL contain the `OPENAI_API_KEY` variable as a required field with a placeholder value of `your-openai-api-key-here`.
3. THE Env_File SHALL contain the `LANGSMITH_API_KEY` variable as an optional field with a placeholder value of `your-langsmith-api-key-here` and a comment indicating it is optional.
4. THE Env_File SHALL contain the `SCRIPT_WRITER_MODEL` variable with a default value of `gpt-4o`.
5. THE Env_File SHALL contain the `CODE_GENERATOR_MODEL` variable with a default value of `gpt-4o`.
6. THE Env_File SHALL contain the `VOICEOVER_MODEL` variable with a default value of `tts-1-hd`.
7. THE Env_File SHALL contain the `VOICEOVER_PROVIDER` variable with a default value of `openai` and a comment listing the accepted values `openai` and `coqui`.
8. THE Env_File SHALL contain the `COQUI_MODEL` variable with a default value of `xtts_v2` and a comment indicating it is only used when `VOICEOVER_PROVIDER=coqui`.
9. THE Env_File SHALL contain the `COQUI_REFERENCE_VOICE` variable with an empty default value and a comment indicating it is only used when `VOICEOVER_PROVIDER=coqui`.
10. IF the Developer attempts to run `make build` or `make run` and the `OPENAI_API_KEY` value in the Env_File is the placeholder string `your-openai-api-key-here` or is empty, THEN THE Setup_Tool SHALL display an error message instructing the Developer to set a valid `OPENAI_API_KEY` before proceeding.

---

### Requirement 4: Docker Image Build

**User Story:** As a Developer, I want a single command to build all Docker images in the correct dependency order, so that I do not have to manage build sequencing manually.

#### Acceptance Criteria

1. WHEN the Developer executes `make build` from the `video-gen/manim-agent-network` directory, THE Setup_Tool SHALL build the Base_Image first before building any Agent_Service image.
2. WHEN the Base_Image build completes successfully, THE Setup_Tool SHALL build all six Agent_Service images: orchestrator, script-writer, code-generator, validator, voiceover, and assembler.
3. THE Setup_Tool SHALL build all Agent_Service images using the Dockerfiles located in `infrastructure/docker/`.
4. IF any Docker image build fails, THEN THE Setup_Tool SHALL halt the build process and display the Docker build error output including the failing layer and the Dockerfile line that caused the failure.
5. WHEN all images are built successfully, THE Setup_Tool SHALL display a summary listing each image name and its build status.
6. THE Base_Image SHALL install all system-level dependencies required by Manim CE, including `ffmpeg`, `libcairo2-dev`, `libpango1.0-dev`, `espeak`, and `build-essential`.
7. THE Base_Image SHALL install all Python dependencies listed in `requirements.txt` using `uv pip install`.

---

### Requirement 5: Service Startup

**User Story:** As a Developer, I want a single command to start all microservices in detached mode, so that the system is running in the background and I can continue using my terminal.

#### Acceptance Criteria

1. WHEN the Developer executes `make run` from the `video-gen/manim-agent-network` directory, THE Setup_Tool SHALL start all six Agent_Services as Docker containers in detached mode.
2. THE Setup_Tool SHALL mount the `./workspace` directory as a shared volume accessible at `/workspace` inside every Agent_Service container.
3. THE Setup_Tool SHALL inject all environment variables defined in the Env_File into the containers that require them, as specified in `docker-compose.yml`.
4. THE Setup_Tool SHALL start the Orchestrator container only after all five downstream Agent_Services (script-writer, code-generator, validator, voiceover, assembler) have started.
5. WHEN all containers are started, THE Setup_Tool SHALL display the names and mapped host ports of all running containers.
6. THE Setup_Tool SHALL expose the Orchestrator on host port 8000, Script-Writer on 8001, Code-Generator on 8002, Validator on 8003, Voiceover on 8004, and Assembler on 8005.
7. IF a required host port (8000–8005) is already in use, THEN THE Setup_Tool SHALL display an error message identifying the conflicting port and the process occupying it.

---

### Requirement 6: Workspace Directory Initialization

**User Story:** As a Developer, I want the workspace directories to be created automatically, so that Agent_Services can write intermediate and final files without encountering missing-directory errors.

#### Acceptance Criteria

1. THE Setup_Tool SHALL ensure the `workspace/temp/` directory exists on the host before any Agent_Service container starts.
2. THE Setup_Tool SHALL ensure the `workspace/outputs/` directory exists on the host before any Agent_Service container starts.
3. IF the `workspace/temp/` or `workspace/outputs/` directories do not exist, THEN THE Setup_Tool SHALL create them automatically without requiring Developer intervention.

---

### Requirement 7: Service Health Validation

**User Story:** As a Developer, I want to verify that all services are healthy after startup, so that I know the system is ready to accept video generation requests before I submit a job.

#### Acceptance Criteria

1. THE Validation_Script SHALL send an HTTP GET request to `http://localhost:8000/health` and verify the response body is `{"status": "ok"}` with HTTP status code 200.
2. THE Validation_Script SHALL send an HTTP GET request to `http://localhost:8001/health` and verify the response body is `{"status": "ok"}` with HTTP status code 200.
3. THE Validation_Script SHALL send an HTTP GET request to `http://localhost:8002/health` and verify the response body is `{"status": "ok"}` with HTTP status code 200.
4. THE Validation_Script SHALL send an HTTP GET request to `http://localhost:8003/health` and verify the response body is `{"status": "ok"}` with HTTP status code 200.
5. THE Validation_Script SHALL send an HTTP GET request to `http://localhost:8004/health` and verify the response body is `{"status": "ok"}` with HTTP status code 200.
6. THE Validation_Script SHALL send an HTTP GET request to `http://localhost:8005/health` and verify the response body is `{"status": "ok"}` with HTTP status code 200.
7. IF any Agent_Service health check returns a non-200 HTTP status code or a response body other than `{"status": "ok"}`, THEN THE Validation_Script SHALL display the service name, port, actual HTTP status code, and actual response body.
8. WHEN all six health checks pass, THE Validation_Script SHALL display a confirmation message stating that all services are healthy and the system is ready.

---

### Requirement 8: End-to-End Smoke Test

**User Story:** As a Developer, I want to submit a minimal video generation request and confirm the pipeline accepts it, so that I know the full agent network is wired up correctly before doing real work.

#### Acceptance Criteria

1. THE Validation_Script SHALL send an HTTP POST request to `http://localhost:8000/generate` with the JSON body `{"topic": "The Pythagorean Theorem visually explained"}` and the header `Content-Type: application/json`.
2. WHEN the POST request is accepted, THE Orchestrator SHALL return an HTTP 200 response containing a `job_id` field with a non-empty UUID string and a `message` field.
3. THE Validation_Script SHALL send an HTTP GET request to `http://localhost:8000/job/{job_id}` using the `job_id` returned in Acceptance Criterion 2.
4. WHEN the GET request is made within 5 seconds of job submission, THE Orchestrator SHALL return a response with a `status` field containing one of the values: `starting`, `pending`, `running`, `completed`, or `failed`.
5. IF the POST request to `/generate` returns a non-200 HTTP status code, THEN THE Validation_Script SHALL display the HTTP status code and response body and indicate that the smoke test failed.

---

### Requirement 9: Log Access

**User Story:** As a Developer, I want a simple command to stream logs from all running services, so that I can monitor pipeline execution and diagnose errors.

#### Acceptance Criteria

1. WHEN the Developer executes `make logs` from the `video-gen/manim-agent-network` directory, THE Setup_Tool SHALL stream the combined stdout and stderr output of all running Agent_Service containers to the Developer's terminal.
2. THE Setup_Tool SHALL prefix each log line with the name of the Agent_Service container that produced it.
3. WHEN the Developer executes `make down` from the `video-gen/manim-agent-network` directory, THE Setup_Tool SHALL stop and remove all Agent_Service containers.

---

### Requirement 10: Optional Coqui TTS Setup

**User Story:** As a Developer, I want clear instructions for enabling local Coqui TTS with voice cloning, so that I can use the voiceover service without relying on the OpenAI TTS API.

#### Acceptance Criteria

1. WHERE `VOICEOVER_PROVIDER` is set to `coqui` in the Env_File, THE Setup_Tool SHALL document the additional installation steps required to enable Coqui TTS, including installing the `TTS` package from the Coqui GitHub repository.
2. WHERE `VOICEOVER_PROVIDER` is set to `coqui` and `COQUI_REFERENCE_VOICE` is set to a non-empty file path, THE Voiceover Agent_Service SHALL use the specified audio file as the reference voice for voice cloning.
3. WHERE `VOICEOVER_PROVIDER` is set to `coqui` and `COQUI_REFERENCE_VOICE` is empty, THE Voiceover Agent_Service SHALL use the default Coqui TTS voice without voice cloning.
4. IF `VOICEOVER_PROVIDER` is set to `coqui` and the `TTS` package is not installed in the container, THEN THE Voiceover Agent_Service SHALL log an error message stating that Coqui TTS is not installed and instruct the Developer to rebuild the Docker image with Coqui support enabled.

---

### Requirement 11: Optional LangSmith Tracing Setup

**User Story:** As a Developer, I want clear instructions for enabling LangSmith tracing, so that I can observe and debug LangGraph pipeline executions in the LangSmith dashboard.

#### Acceptance Criteria

1. WHERE `LANGSMITH_API_KEY` is set to a non-empty, non-placeholder value in the Env_File, THE Orchestrator SHALL initialize a LangSmith client and log the message `LangSmith tracing enabled` at INFO level during startup.
2. WHERE `LANGSMITH_API_KEY` is not set or is empty in the Env_File, THE Orchestrator SHALL start without LangSmith tracing and SHALL NOT raise an error or warning that blocks service startup.
3. THE Setup_Tool SHALL document the URL `https://langsmith.com` as the location where Developers can obtain a `LANGSMITH_API_KEY`.
