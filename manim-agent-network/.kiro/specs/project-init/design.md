# Design Document: project-init

## Overview

The `project-init` feature defines the complete bootstrapping experience for a new developer joining the **Manim Agent Network** project. It covers every step from a fresh `git clone` to a fully operational, smoke-tested system: prerequisite verification, `.env` configuration, Docker image builds, service startup, workspace directory initialization, health validation, and an end-to-end smoke test.

The design is implemented as a collection of shell-level artifacts — a `Makefile` with extended targets, a `scripts/check-prereqs.sh` prerequisite checker, a `scripts/validate.sh` health + smoke-test runner, and a `.env.template` file — layered on top of the existing `docker-compose.yml`. No new runtime services are introduced; all new code is developer tooling.

**Key design decisions:**

- **Makefile as the single entry point.** Developers already know `make build` / `make run`. New targets (`make check`, `make validate`, `make smoke`) extend that vocabulary without introducing a new CLI tool.
- **Bash scripts for portability.** The prerequisite checker and validator are plain Bash so they run on macOS, Linux, and WSL2 without additional runtimes.
- **`curl` + `jq` for HTTP assertions.** Both are universally available in Docker-based environments and CI runners; no Python test framework is needed for the validation layer.
- **Guard clause in Makefile for `OPENAI_API_KEY`.** A `make build` / `make run` guard reads the `.env` file and aborts early with a clear message if the key is missing or still set to the placeholder, preventing a confusing runtime failure deep inside a container.

---

## Architecture

```
Developer Terminal
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Makefile  (entry point for all developer commands)              │
│                                                                  │
│  make check    ──▶  scripts/check-prereqs.sh                     │
│  make build    ──▶  [guard: OPENAI_API_KEY]                      │
│                     docker-compose build                         │
│  make run      ──▶  [guard: OPENAI_API_KEY]                      │
│                     mkdir -p workspace/temp workspace/outputs    │
│                     docker-compose up -d                         │
│  make validate ──▶  scripts/validate.sh  (health checks)        │
│  make smoke    ──▶  scripts/validate.sh  (health + smoke test)  │
│  make logs     ──▶  docker-compose logs -f                       │
│  make down     ──▶  docker-compose down                          │
└──────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Docker Compose  (service orchestration)                         │
│                                                                  │
│  base-manim-agent  (build-time only)                             │
│  orchestrator  :8000  ──depends_on──▶  script-writer             │
│                                        code-generator            │
│                                        validator                 │
│                                        voiceover                 │
│                                        assembler                 │
│  script-writer :8001                                             │
│  code-generator:8002                                             │
│  validator     :8003                                             │
│  voiceover     :8004                                             │
│  assembler     :8005                                             │
│                                                                  │
│  Shared volume: ./workspace  ──▶  /workspace (all containers)   │
└──────────────────────────────────────────────────────────────────┘
```

### Data / Control Flow During Init

```
make check
  └─▶ check-prereqs.sh
        ├─ docker --version  ──▶ parse semver ──▶ pass/fail
        ├─ docker compose version ──▶ parse semver ──▶ pass/fail
        └─ git --version ──▶ parse semver ──▶ pass/fail

make build
  └─▶ guard_env (reads .env, checks OPENAI_API_KEY)
  └─▶ docker-compose build
        ├─ Dockerfile.base  (built first, tagged base-manim-agent)
        └─ Dockerfile.{orchestrator,script-writer,...}  (FROM base-manim-agent)

make run
  └─▶ guard_env
  └─▶ mkdir -p workspace/temp workspace/outputs
  └─▶ docker-compose up -d

make validate
  └─▶ validate.sh --health-only
        └─▶ for port in 8000..8005: GET /health ──▶ assert {"status":"ok"}

make smoke
  └─▶ validate.sh --smoke
        ├─▶ health checks (all 6 services)
        └─▶ POST /generate ──▶ assert job_id UUID
            └─▶ GET /job/{job_id} ──▶ assert status in valid set
```

---

## Components and Interfaces

### 1. `scripts/check-prereqs.sh`

**Purpose:** Verify Docker Engine ≥ 20.10, Docker Compose ≥ 2.0, and Git ≥ 2.0 are installed.

**Interface (pseudocode):**

```
function check_tool(name, min_major, min_minor, version_cmd, install_url):
    run version_cmd → raw_version_string
    if command not found:
        print_error(name, min_major.min_minor, install_url)
        return FAIL
    parse semver from raw_version_string → (major, minor, patch)
    if (major, minor) < (min_major, min_minor):
        print_error(name, detected_version, min_major.min_minor, install_url)
        return FAIL
    print_ok(name, detected_version)
    return PASS

main():
    results = []
    results += check_tool("Docker Engine", 20, 10,
                          "docker --version",
                          "https://docs.docker.com/engine/install/")
    results += check_tool("Docker Compose", 2, 0,
                          "docker compose version",
                          "https://docs.docker.com/compose/install/")
    results += check_tool("Git", 2, 0,
                          "git --version",
                          "https://git-scm.com/downloads")
    if any(results == FAIL):
        exit(1)
    print("✓ All prerequisites satisfied.")
    exit(0)
```

**Exit codes:** `0` = all pass, `1` = one or more failures.

---

### 2. `Makefile` — extended targets

New targets added to the existing `Makefile`:

| Target | Description |
|--------|-------------|
| `check` | Run `scripts/check-prereqs.sh` |
| `build` | Guard `OPENAI_API_KEY`, then `docker-compose build` |
| `run` | Guard `OPENAI_API_KEY`, create workspace dirs, then `docker-compose up -d` |
| `validate` | Run `scripts/validate.sh --health-only` |
| `smoke` | Run `scripts/validate.sh --smoke` |
| `logs` | `docker-compose logs -f` (existing, unchanged) |
| `down` | `docker-compose down` (existing, unchanged) |

**Guard clause pseudocode (embedded in Makefile `build` and `run` targets):**

```
function guard_env():
    if .env does not exist:
        print "ERROR: .env file not found. Copy .env.template to .env and fill in OPENAI_API_KEY."
        exit(1)
    read OPENAI_API_KEY from .env
    if OPENAI_API_KEY is empty OR OPENAI_API_KEY == "your-openai-api-key-here":
        print "ERROR: OPENAI_API_KEY is not set. Edit .env and provide a valid key."
        exit(1)
```

---

### 3. `scripts/validate.sh`

**Purpose:** HTTP-level health checks and smoke test against running containers.

**Interface (pseudocode):**

```
SERVICES = [
    ("orchestrator",   8000),
    ("script-writer",  8001),
    ("code-generator", 8002),
    ("validator",      8003),
    ("voiceover",      8004),
    ("assembler",      8005),
]

function health_check(name, port):
    response = curl GET http://localhost:{port}/health
    if http_status != 200 OR body != '{"status":"ok"}':
        print_fail(name, port, http_status, body)
        return FAIL
    print_ok(name, port)
    return PASS

function smoke_test():
    response = curl POST http://localhost:8000/generate
               body: {"topic": "The Pythagorean Theorem visually explained"}
               header: Content-Type: application/json
    if http_status != 200:
        print "SMOKE FAIL: POST /generate returned {http_status}: {body}"
        return FAIL
    job_id = parse response.job_id
    if job_id is empty or not UUID format:
        print "SMOKE FAIL: job_id missing or invalid in response"
        return FAIL
    print "✓ Job submitted: {job_id}"

    sleep 2  # allow orchestrator to register the job

    response = curl GET http://localhost:8000/job/{job_id}
    status = parse response.status
    VALID_STATUSES = {"starting", "pending", "running", "completed", "failed"}
    if status not in VALID_STATUSES:
        print "SMOKE FAIL: unexpected status '{status}'"
        return FAIL
    print "✓ Job status: {status}"
    return PASS

main(mode):
    failures = 0
    for (name, port) in SERVICES:
        failures += health_check(name, port)
    if mode == "--smoke":
        failures += smoke_test()
    if failures > 0:
        exit(1)
    print "✓ All checks passed. System is ready."
    exit(0)
```

**Dependencies:** `curl`, `jq` (both available in standard Linux/macOS environments and CI runners).

---

### 4. `.env.template`

A committed template file that developers copy to `.env` before first use.

```
# ─── Required ────────────────────────────────────────────────────────────────
# Your OpenAI API key. Obtain from https://platform.openai.com/api-keys
OPENAI_API_KEY=your-openai-api-key-here

# ─── Model Configuration ─────────────────────────────────────────────────────
SCRIPT_WRITER_MODEL=gpt-4o
CODE_GENERATOR_MODEL=gpt-4o
VOICEOVER_MODEL=tts-1-hd

# ─── Voiceover Provider ───────────────────────────────────────────────────────
# Accepted values: openai | coqui
VOICEOVER_PROVIDER=openai

# ─── Coqui TTS (only used when VOICEOVER_PROVIDER=coqui) ─────────────────────
COQUI_MODEL=xtts_v2
# Path to a .wav reference voice file for voice cloning (leave empty for default voice)
COQUI_REFERENCE_VOICE=

# ─── LangSmith Tracing (optional) ────────────────────────────────────────────
# Obtain from https://langsmith.com
# Leave as placeholder or empty to disable tracing (no error will be raised)
LANGSMITH_API_KEY=your-langsmith-api-key-here
```

---

### 5. `docker-compose.yml` — workspace volume fix

The existing `docker-compose.yml` declares a named volume `workspace:` at the bottom, which conflicts with the bind-mount `./workspace:/workspace` used by each service. The named volume declaration must be removed so that the bind-mount correctly maps the host directory `./workspace` into containers. The `make run` target creates `workspace/temp` and `workspace/outputs` on the host before `docker-compose up -d`.

---

## Data Models

### VersionCheckResult

```
VersionCheckResult:
    tool_name:        string          # e.g. "Docker Engine"
    required_version: string          # e.g. "20.10"
    detected_version: string | null   # null if tool not found
    passed:           boolean
    install_url:      string          # URL to official install guide
```

### HealthCheckResult

```
HealthCheckResult:
    service_name: string   # e.g. "orchestrator"
    port:         integer  # e.g. 8000
    http_status:  integer  # actual HTTP status code
    body:         string   # raw response body
    passed:       boolean
```

### SmokeTestResult

```
SmokeTestResult:
    job_id:         string | null   # UUID returned by /generate
    post_status:    integer         # HTTP status of POST /generate
    post_body:      string          # raw response body
    job_status:     string | null   # value of .status from GET /job/{id}
    passed:         boolean
    failure_reason: string | null   # human-readable failure description
```

### EnvGuardResult

```
EnvGuardResult:
    env_file_exists:    boolean
    key_present:        boolean   # OPENAI_API_KEY key exists in file
    key_is_placeholder: boolean   # value equals "your-openai-api-key-here"
    key_is_empty:       boolean
    passed:             boolean   # true only when file exists AND key is non-empty AND not placeholder
```

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Version comparison correctness

*For any* two semantic version strings A and B, the version comparison function SHALL return `A >= B` if and only if A's (major, minor) tuple is lexicographically greater than or equal to B's (major, minor) tuple. This must hold for all valid version string formats produced by `docker --version`, `docker compose version`, and `git --version`, including strings with pre-release suffixes and missing patch components.

**Validates: Requirements 1.1, 1.2, 1.3**

---

### Property 2: Prerequisite check result correctness and output completeness

*For any* combination of tool availability states (present/absent) and detected version values, the prerequisite checker SHALL produce exactly one `VersionCheckResult` per tool, each result's `passed` field SHALL be `true` if and only if the tool is present AND its detected version satisfies the minimum version constraint, and for every result where `passed` is `false` the output string SHALL contain the tool name, the required minimum version, and the official install URL.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7**

---

### Property 3: Env template contains all required keys with correct defaults

*For any* parse of the `.env.template` file, every required environment variable key (`OPENAI_API_KEY`, `LANGSMITH_API_KEY`, `SCRIPT_WRITER_MODEL`, `CODE_GENERATOR_MODEL`, `VOICEOVER_MODEL`, `VOICEOVER_PROVIDER`, `COQUI_MODEL`, `COQUI_REFERENCE_VOICE`) SHALL be present, and each key with a specified default value SHALL have exactly that default value in the template.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9**

---

### Property 4: Env guard rejects all invalid OPENAI_API_KEY states

*For any* `.env` file content where `OPENAI_API_KEY` is absent, empty, composed only of whitespace, or equal to the placeholder string `"your-openai-api-key-here"`, the `EnvGuardResult.passed` field SHALL be `false` and the output SHALL contain the string `"OPENAI_API_KEY"`.

**Validates: Requirements 3.10**

---

### Property 5: Health check result faithfully reflects HTTP response

*For any* `(http_status, body)` pair returned by a service's `/health` endpoint, the `HealthCheckResult.passed` field SHALL be `true` if and only if `http_status == 200` AND `body == '{"status": "ok"}'`. For every result where `passed` is `false`, the output string SHALL contain the service name, port number, actual HTTP status code, and actual response body.

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7**

---

### Property 6: Smoke test response validation

*For any* POST response to `/generate`, the `SmokeTestResult.passed` field SHALL be `true` if and only if the HTTP status is `200`, the `job_id` field is present and conforms to UUID format, and a subsequent GET to `/job/{job_id}` returns a `status` field whose value is one of `{"starting", "pending", "running", "completed", "failed"}`. For any non-200 POST response, the output SHALL contain the HTTP status code and response body.

**Validates: Requirements 8.2, 8.4, 8.5**

---

## Error Handling

### Prerequisite Check Failures

- Each tool check is independent; all three checks always run so the developer sees all missing tools in one pass.
- Error messages include: tool name, required version, detected version (or "not found"), and the official install URL.
- The script exits with code `1` if any check fails, making it CI-friendly.

### `.env` Guard Failures

- The guard runs before any Docker command so the developer gets a clear message before a potentially long build.
- The guard distinguishes three cases: file missing, key absent, key is placeholder/empty — each with a distinct message.

### Docker Build Failures

- `docker-compose build` streams output to the terminal; Docker's own error output (failing layer, Dockerfile line) is visible directly.
- The Makefile does not suppress Docker output, so the developer sees the full build log.
- On failure, `docker-compose build` exits non-zero, which propagates through `make` and halts the process.

### Port Conflict Detection

- Before `docker-compose up -d`, the `make run` target checks whether ports 8000–8005 are in use using `lsof -i :{port}` (macOS/Linux) or `netstat -ano` (Windows/WSL2).
- If a conflict is found, the target prints the conflicting port and the PID/process name, then exits before starting any containers.

### Health Check Failures

- `validate.sh` checks all six services and collects all failures before exiting, so the developer sees every unhealthy service in one run.
- Output includes: service name, port, actual HTTP status, actual response body.
- Exit code `1` on any failure.

### Smoke Test Failures

- If POST `/generate` returns non-200, the script prints the status and body and marks the test failed.
- If `job_id` is missing or malformed, the script reports the raw response body.
- If the job status is not in the valid set, the script reports the unexpected value.

### Coqui TTS Not Installed

- If `VOICEOVER_PROVIDER=coqui` and the `TTS` package is absent, the Voiceover service logs: `"ERROR: Coqui TTS is not installed. Rebuild the Docker image with Coqui support enabled (uncomment the TTS line in requirements.txt)."` and returns HTTP 500 for voiceover requests.

### LangSmith Key Missing

- If `LANGSMITH_API_KEY` is absent or empty, the Orchestrator starts normally without tracing. No error or warning is raised that would block startup (existing behavior, confirmed in `main.py`).

---

## Testing Strategy

### Unit Tests

Unit tests cover the pure logic components of the init tooling:

1. **Version parser** (`parse_semver`): test that version strings like `"Docker version 24.0.5"`, `"git version 2.39.2"`, `"Docker Compose version v2.20.0"` are correctly parsed into `(major, minor, patch)` tuples. Include edge cases: pre-release suffixes, missing patch component.

2. **Version comparator** (`version_gte`): test all boundary conditions — equal versions, one above, one below, major version dominates minor.

3. **Env guard logic** (`check_env_key`): test with file missing, key absent, key empty, key = placeholder, key = valid value.

4. **Health check response parser** (`parse_health_response`): test with `{"status":"ok"}` (pass), `{"status":"error"}` (fail), non-JSON body (fail), empty body (fail).

5. **Smoke test response parser** (`parse_generate_response`): test with valid UUID job_id, missing job_id field, non-UUID string, empty string.

6. **Job status validator** (`is_valid_job_status`): test each of the five valid statuses and several invalid strings.

### Property-Based Tests

Property tests use **Hypothesis** (Python). Since the tooling scripts are Bash, the property tests target equivalent Python helper functions that implement the same pure logic (version parsing, env guard, health check assertion, smoke test assertion). Each test runs a minimum of **100 iterations**.

Test tagging format:

```python
# Feature: project-init, Property N: <property_text>
```

**Property 1 — Version comparison correctness:**
Generate random `(major_a, minor_a, major_b, minor_b)` tuples using `st.integers(min_value=0, max_value=99)`. Assert `version_gte(a, b) == ((major_a, minor_a) >= (major_b, minor_b))`. Also generate realistic version strings with pre-release suffixes and assert the parser extracts the correct numeric components.

**Property 2 — Prerequisite check result correctness and output completeness:**
Generate random `{tool: (is_present: bool, version: (int, int))}` dicts for the three tools. Assert the checker produces exactly three `VersionCheckResult` records, each `passed` field matches `is_present AND version >= minimum`, and for every failing result the output string contains the tool name, required version, and install URL.

**Property 3 — Env template contains all required keys with correct defaults:**
This is a deterministic check (the template file is fixed), so it runs as a single parameterized test over the list of `(key, expected_default)` pairs. Assert each pair is present in the parsed template.

**Property 4 — Env guard rejects all invalid OPENAI_API_KEY states:**
Generate random strings from: empty string, `"your-openai-api-key-here"`, strings of only whitespace characters, and absent key. Assert `EnvGuardResult.passed == False` and output contains `"OPENAI_API_KEY"` for all such inputs.

**Property 5 — Health check result faithfully reflects HTTP response:**
Generate random `(http_status: int, body: str)` pairs using `st.integers(100, 599)` and `st.text()`. Assert `HealthCheckResult.passed == (http_status == 200 and body == '{"status": "ok"}')`. For failing results, assert output contains service name, port, status code, and body.

**Property 6 — Smoke test response validation:**
Generate random POST response bodies (valid UUID job_id, invalid strings, missing field) and random GET response status values (valid set members, arbitrary strings). Assert `SmokeTestResult.passed` matches the full predicate: `post_status == 200 AND job_id is UUID AND job_status in valid_set`. For non-200 POST responses, assert output contains the status code and body.

### Integration Tests

Integration tests run against the live Docker environment (CI pipeline, post-`make run`):

1. **Full health check pass:** Run `scripts/validate.sh --health-only` after `make run`; assert exit code 0.
2. **Smoke test pass:** Run `scripts/validate.sh --smoke`; assert exit code 0 and that the returned `job_id` is a valid UUID.
3. **Port conflict detection:** Start a dummy process on port 8000, run `make run`, assert the Makefile exits non-zero with a message containing "8000".
4. **Env guard blocks build:** Set `OPENAI_API_KEY=your-openai-api-key-here` in `.env`, run `make build`, assert exit code 1 and error message contains "OPENAI_API_KEY".
5. **Workspace dirs created:** Delete `workspace/temp` and `workspace/outputs`, run `make run`, assert both directories exist after the command completes.
