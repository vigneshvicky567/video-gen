# Implementation Plan: project-init

## Overview

Implement the complete developer bootstrapping experience for the Manim Agent Network project. This covers creating the `.env.template`, the `scripts/check-prereqs.sh` prerequisite checker, the `scripts/validate.sh` health and smoke-test runner, extending the `Makefile` with guarded targets, fixing the `docker-compose.yml` named-volume conflict, and writing Python/Hypothesis property-based tests for all six correctness properties defined in the design.

## Tasks

- [x] 1. Create `.env.template`
  - Create `video-gen/manim-agent-network/.env.template` with all required keys, placeholder values, and inline comments exactly as specified in the design
  - Keys required: `OPENAI_API_KEY`, `LANGSMITH_API_KEY`, `SCRIPT_WRITER_MODEL`, `CODE_GENERATOR_MODEL`, `VOICEOVER_MODEL`, `VOICEOVER_PROVIDER`, `COQUI_MODEL`, `COQUI_REFERENCE_VOICE`
  - Default values: `SCRIPT_WRITER_MODEL=gpt-4o`, `CODE_GENERATOR_MODEL=gpt-4o`, `VOICEOVER_MODEL=tts-1-hd`, `VOICEOVER_PROVIDER=openai`, `COQUI_MODEL=xtts_v2`, `COQUI_REFERENCE_VOICE=` (empty)
  - Placeholder values: `OPENAI_API_KEY=your-openai-api-key-here`, `LANGSMITH_API_KEY=your-langsmith-api-key-here`
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

  - [ ]* 1.1 Write property test for `.env.template` key presence and defaults (Property 3)
    - **Property 3: Env template contains all required keys with correct defaults**
    - Parse `.env.template` and assert every required key is present with its specified default value
    - Run as a parameterized test over the list of `(key, expected_default)` pairs
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9**

- [x] 2. Implement Python helper module for property-based tests
  - Create `video-gen/manim-agent-network/tests/__init__.py` (empty)
  - Create `video-gen/manim-agent-network/tests/init_helpers.py` with pure Python implementations of the logic under test:
    - `parse_semver(version_string: str) -> tuple[int, int, int]` — extract `(major, minor, patch)` from raw version strings produced by `docker --version`, `docker compose version`, and `git --version`, tolerating pre-release suffixes and missing patch components
    - `version_gte(a: tuple[int, int], b: tuple[int, int]) -> bool` — compare `(major, minor)` tuples
    - `check_env_key(env_content: str, key: str, placeholder: str) -> EnvGuardResult` — parse env file content and return an `EnvGuardResult` dataclass
    - `parse_health_response(http_status: int, body: str, service_name: str, port: int) -> HealthCheckResult` — return a `HealthCheckResult` dataclass
    - `parse_generate_response(post_status: int, post_body: str) -> SmokeTestResult` — parse POST `/generate` response
    - `is_valid_job_status(status: str) -> bool` — check membership in `{"starting", "pending", "running", "completed", "failed"}`
    - `validate_smoke_test(post_status: int, post_body: str, get_status_value: str) -> SmokeTestResult` — full smoke test predicate
  - Define `EnvGuardResult`, `HealthCheckResult`, and `SmokeTestResult` as dataclasses in this module
  - _Requirements: 1.1, 1.2, 1.3, 3.10, 7.1–7.7, 8.2, 8.4, 8.5_

- [x] 3. Write property-based tests (Hypothesis)
  - Create `video-gen/manim-agent-network/tests/test_project_init_properties.py`
  - Import helpers from `tests/init_helpers.py`
  - Use `hypothesis` with `@given` and `@settings(max_examples=100)` for all property tests

  - [ ]* 3.1 Write property test for version comparison correctness (Property 1)
    - **Property 1: Version comparison correctness**
    - Generate random `(major_a, minor_a, major_b, minor_b)` with `st.integers(min_value=0, max_value=99)`
    - Assert `version_gte((major_a, minor_a), (major_b, minor_b)) == ((major_a, minor_a) >= (major_b, minor_b))`
    - Also generate realistic version strings with pre-release suffixes; assert `parse_semver` extracts correct numeric components
    - **Validates: Requirements 1.1, 1.2, 1.3**

  - [ ]* 3.2 Write property test for prerequisite check result correctness (Property 2)
    - **Property 2: Prerequisite check result correctness and output completeness**
    - Generate random `{tool: (is_present: bool, version: (int, int))}` dicts for Docker Engine, Docker Compose, and Git
    - Assert exactly three `VersionCheckResult` records are produced
    - Assert each `passed` field equals `is_present AND version >= minimum`
    - Assert every failing result's output string contains the tool name, required version, and install URL
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7**

  - [ ]* 3.3 Write property test for env guard rejecting invalid key states (Property 4)
    - **Property 4: Env guard rejects all invalid OPENAI_API_KEY states**
    - Generate inputs from: empty string, `"your-openai-api-key-here"`, whitespace-only strings, absent key
    - Assert `EnvGuardResult.passed == False` for all such inputs
    - Assert output contains `"OPENAI_API_KEY"` for all failing cases
    - **Validates: Requirements 3.10**

  - [ ]* 3.4 Write property test for health check result faithfulness (Property 5)
    - **Property 5: Health check result faithfully reflects HTTP response**
    - Generate random `(http_status: int, body: str)` pairs with `st.integers(100, 599)` and `st.text()`
    - Assert `HealthCheckResult.passed == (http_status == 200 and body == '{"status": "ok"}')`
    - Assert every failing result's output contains service name, port, status code, and body
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7**

  - [ ]* 3.5 Write property test for smoke test response validation (Property 6)
    - **Property 6: Smoke test response validation**
    - Generate random POST response bodies (valid UUID job_id, invalid strings, missing field) and random GET status values (valid set members and arbitrary strings)
    - Assert `SmokeTestResult.passed` matches the full predicate: `post_status == 200 AND job_id is UUID AND job_status in valid_set`
    - Assert non-200 POST responses produce output containing the status code and body
    - **Validates: Requirements 8.2, 8.4, 8.5**

- [x] 4. Checkpoint — Ensure all property tests pass
  - Run `pytest video-gen/manim-agent-network/tests/test_project_init_properties.py -v` and confirm all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Create `scripts/check-prereqs.sh`
  - Create `video-gen/manim-agent-network/scripts/check-prereqs.sh` as an executable Bash script
  - Implement `check_tool` function: run version command, handle command-not-found, parse semver with `grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?'`, compare `(major, minor)` against minimum, print pass/fail with install URL
  - Minimum versions: Docker Engine ≥ 20.10, Docker Compose ≥ 2.0, Git ≥ 2.0
  - Run all three checks independently so all failures are reported in one pass
  - Exit code `0` when all pass, `1` when any fail
  - Mark the file executable (`chmod +x`)
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

- [-] 6. Create `scripts/validate.sh`
  - Create `video-gen/manim-agent-network/scripts/validate.sh` as an executable Bash script
  - Implement `health_check(name, port)`: `curl -s -o /tmp/body -w "%{http_code}"` to capture status and body separately; assert status 200 and body `{"status":"ok"}`; print service name, port, status, body on failure
  - Loop over all six services (ports 8000–8005) and collect failures
  - Implement `smoke_test()`: POST to `http://localhost:8000/generate` with the Pythagorean Theorem topic; parse `job_id` with `jq -r .job_id`; validate UUID format with regex; sleep 2; GET `/job/{job_id}`; validate `status` is in the valid set
  - Accept `--health-only` and `--smoke` as the first argument; default to `--health-only`
  - Exit code `0` when all checks pass, `1` on any failure
  - Mark the file executable (`chmod +x`)
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ] 7. Fix `docker-compose.yml` named-volume conflict
  - Remove the top-level `volumes:` block (`volumes:\n  workspace:`) from `video-gen/manim-agent-network/docker-compose.yml`
  - The bind-mount `./workspace:/workspace` in each service definition is sufficient and must not be shadowed by a named volume
  - _Requirements: 5.2, 6.1, 6.2, 6.3_

- [ ] 8. Extend `Makefile` with guarded and new targets
  - Replace the existing `Makefile` at `video-gen/manim-agent-network/Makefile` with the extended version
  - Add `guard_env` as a private target (or inline shell function) that:
    - Checks `.env` exists; if not, prints `ERROR: .env file not found. Copy .env.template to .env and fill in OPENAI_API_KEY.` and exits 1
    - Reads `OPENAI_API_KEY` from `.env`; if empty or equal to `your-openai-api-key-here`, prints `ERROR: OPENAI_API_KEY is not set. Edit .env and provide a valid key.` and exits 1
  - Update `build` target: run guard, then `docker-compose build`
  - Update `run` target: run guard, then `mkdir -p workspace/temp workspace/outputs`, then check ports 8000–8005 with `lsof -i :{port}` (or `ss -ltn` on Linux), then `docker-compose up -d`
  - Add `check` target: `bash scripts/check-prereqs.sh`
  - Add `validate` target: `bash scripts/validate.sh --health-only`
  - Add `smoke` target: `bash scripts/validate.sh --smoke`
  - Keep existing `logs` and `down` targets unchanged
  - Update `.PHONY` to include `check`, `validate`, `smoke`
  - _Requirements: 1.1–1.7, 3.10, 4.1–4.5, 5.1, 5.4–5.7, 6.1–6.3, 9.1–9.3_

- [ ] 9. Final checkpoint — Verify all artifacts are consistent
  - Confirm `.env.template` keys match the `environment:` blocks in `docker-compose.yml`
  - Confirm `scripts/check-prereqs.sh` and `scripts/validate.sh` are executable
  - Confirm `Makefile` `.PHONY` list is complete
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Property tests (tasks 3.1–3.5) target pure Python helper functions in `tests/init_helpers.py` that mirror the Bash logic; this avoids shelling out in tests while still validating the core algorithms
- The `docker-compose.yml` named-volume fix (task 7) is a prerequisite for `make run` to correctly bind-mount `./workspace` into containers
- The Makefile guard (task 8) must distinguish three failure modes: file missing, key absent, key is placeholder — each with a distinct error message
- `hypothesis` must be listed in `requirements.txt` (or a `requirements-dev.txt`) before running the property tests
