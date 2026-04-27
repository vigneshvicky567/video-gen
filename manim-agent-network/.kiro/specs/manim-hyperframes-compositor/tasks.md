# Implementation Plan: manim-hyperframes-compositor

## Overview

Replace the ffmpeg-based assembler with a two-service HyperFrames pipeline. Tasks are ordered by the graphify knowledge-graph principle: touch god nodes (shared schemas + state) first, then dependent services, then graph wiring, then Docker/infra, then property tests.

## Tasks

- [x] 1. Extend shared schemas and state (god nodes: ScenePlan, ScriptResponse, JobState, LangGraphState)
  - [x] 1.1 Add `SceneTimingRecord` to `shared/schemas/common.py`
    - Define Pydantic model with fields: `scene_id: int`, `render_path: str`, `audio_path: str`, `actual_video_duration_seconds: float`, `actual_audio_duration_seconds: float`, `start_time_seconds: float`
    - _Requirements: 7.4, 7.5_

  - [x] 1.2 Extend `AssemblerRequest` and add `ImageFetcherRequest` in `shared/schemas/requests.py`
    - Add `scene_plans: List[ScenePlan]` and `image_paths: Dict[int, List[str]]` (both required) to `AssemblerRequest`
    - Add new `ImageFetcherRequest(BaseModel)` with `job_id: str` and `scenes: List[ScenePlan]`
    - _Requirements: 7.1, 5.6_

  - [x] 1.3 Add `ImageFetcherResponse` to `shared/schemas/responses.py`
    - Define `ImageFetcherResponse(BaseModel)` with `image_paths: Dict[int, List[str]]`
    - _Requirements: 2.6_

  - [x] 1.4 Extend `LangGraphState` in `shared/models/agent_state.py`
    - Add `image_paths: Dict[int, List[str]]` field
    - _Requirements: 3.1, 7.2_

  - [x] 1.5 Add new config keys to `shared/config.py`
    - Add `PEXELS_API_KEY: str`, `IMAGE_FETCHER_URL: str` (default `"http://image-fetcher:8006"`), `COMPOSITOR_LLM_MODEL: str` (default `"gpt-4o"`)
    - _Requirements: 6.4, 6.6_

  - [x] 1.6 Add new env vars to `.env.template`
    - Add `PEXELS_API_KEY=`, `COMPOSITOR_LLM_MODEL=gpt-4o` with comments
    - _Requirements: 6.4, 6.6_

- [x] 2. Implement image-fetcher service (Community 2: new *Request models)
  - [x] 2.1 Create `services/image-fetcher/app/__init__.py`
    - Empty init file to make the directory a Python package
    - _Requirements: 2.1_

  - [x] 2.2 Implement `services/image-fetcher/app/keyword_extractor.py`
    - Single `openai.chat.completions.create` call per scene; system prompt instructs model to return JSON array of 1–5 keywords from `narration_text` + `visual_description`
    - On JSON parse failure, fall back to first 3 whitespace-split tokens of `narration_text`
    - _Requirements: 2.1_

  - [x] 2.3 Implement `services/image-fetcher/app/pexels_client.py`
    - `GET https://api.pexels.com/v1/search?query=...&per_page=3&orientation=landscape` with `Authorization: {PEXELS_API_KEY}` header
    - Return up to 3 `src.large` URLs; return empty list immediately if `PEXELS_API_KEY` is absent or empty
    - On HTTP 4xx/5xx log warning and return empty list
    - _Requirements: 2.2, 6.6, 6.7_

  - [x] 2.4 Implement `services/image-fetcher/app/wikimedia_client.py`
    - `GET https://en.wikipedia.org/w/api.php?action=query&generator=search&gsrsearch={keyword}&prop=pageimages&piprop=original&format=json`
    - Iterate keywords until at least one image URL found, up to 3 total; return empty list on HTTP error
    - _Requirements: 2.3_

  - [x] 2.5 Implement `services/image-fetcher/app/main.py`
    - FastAPI app with `POST /fetch` accepting `ImageFetcherRequest`, returning `ImageFetcherResponse`
    - For each scene: extract keywords → Pexels → Wikimedia fallback if empty → download each candidate URL, stream bytes, check magic bytes (JPEG: `FF D8 FF`, PNG: `89 50 4E 47`), write valid images to `{WORKSPACE_DIR}/temp/{job_id}/images/scene_{scene_id}/img_{n}.jpg`
    - Record empty list for scene if both sources return nothing; never raise on missing images
    - Include `/health` endpoint
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

- [x] 3. Checkpoint — image-fetcher service complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement compositor service — duration prober (Community 3: response models + SceneTimingRecord)
  - [x] 4.1 Create `services/compositor/app/__init__.py`
    - Empty init file
    - _Requirements: 1.1_

  - [x] 4.2 Implement `services/compositor/app/duration_prober.py`
    - `probe_duration(file_path: str) -> float`: run `ffprobe -v quiet -print_format json -show_streams {file_path}`, parse JSON, return `round(float(streams[0]["duration"]), 3)`; raise `AssemblyError` on non-zero exit or missing stream data
    - `compute_scene_timings(render_paths, audio_paths) -> List[SceneTimingRecord]`: iterate `sorted(render_paths.keys())`, probe both files, accumulate `max(video_dur, audio_dur)` into `start_time_seconds`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 5. Implement compositor service — LLM composer and HTML validator (Community 4: graph nodes)
  - [x] 5.1 Implement `services/compositor/app/html_validator.py`
    - `CompositionValidator(HTMLParser)`: collect `src` attributes from `<video>`, `<audio>`, `<img>` tags; count each tag type
    - `validate_composition(html_path: str) -> None`: read file, feed to parser (propagate `HTMLParseError`), check all `src` paths exist on disk, raise `AssemblyError` listing missing paths
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 5.2 Implement `services/compositor/app/llm_composer.py`
    - Build prompt with script title, per-scene timing records, image paths, canvas spec (1920×1080, `#0f0f0f`), and HyperFrames layout instructions (title card, video panel left 1280×720, image right 600×400, lower-third truncated to 120 chars, audio track)
    - Call `openai.chat.completions.create(model=settings.COMPOSITOR_LLM_MODEL)`, extract HTML block (look for `<!DOCTYPE html>` or `<html`), retry up to 2 additional times if no valid HTML found, then raise `AssemblyError`
    - Write result to `{WORKSPACE_DIR}/temp/{job_id}/composition.html`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [x] 5.3 Implement `services/compositor/app/main.py`
    - FastAPI app with `POST /assemble` accepting extended `AssemblerRequest`, returning `AssemblerResponse`
    - Pipeline: `compute_scene_timings` → `llm_composer.generate` → `validate_composition` → `subprocess` call to `npx hyperframes render --input {html_path} --output {output_path} --width 1920 --height 1080`
    - Verify output file exists and size > 0; raise `AssemblyError` otherwise
    - Write final MP4 to `{WORKSPACE_DIR}/outputs/{job_id}_final.mp4`
    - Catch `AssemblyError` in FastAPI exception handler, return HTTP 500 with detail
    - Include `/health` endpoint
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.4, 6.5_

- [x] 6. Checkpoint — compositor service complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Wire new nodes into LangGraph graph.py (Community 4: assembler_node, _post, graph edges)
  - [x] 7.1 Add `image_fetcher_node` to `services/orchestrator/app/core/graph.py`
    - Import `ImageFetcherRequest` and `settings.IMAGE_FETCHER_URL`
    - Implement `async def image_fetcher_node(state: LangGraphState)`: build request from `state["job_id"]` and `state["script"]["scenes"]`, POST to `{IMAGE_FETCHER_URL}/fetch`, merge `image_paths` into state with `int(k)` key coercion, set `status="image_fetching"`; on exception set `overall_error` and `status="failed"`
    - _Requirements: 3.2, 3.3, 3.4, 3.5_

  - [x] 7.2 Update `assembler_node` in `graph.py`
    - Extend the request dict with `scene_plans: state["script"]["scenes"]` and `image_paths: state.get("image_paths", {})`
    - _Requirements: 7.3_

  - [x] 7.3 Rewire graph edges in `graph.py`
    - Replace `workflow.add_edge("voiceover_node", "assembler_node")` with `workflow.add_edge("voiceover_node", "image_fetcher_node")`
    - Add `workflow.add_conditional_edges("image_fetcher_node", lambda s: "failed" if s.get("overall_error") else "assembler_node")`
    - Register `image_fetcher_node` with `workflow.add_node`
    - _Requirements: 3.2, 3.5_

- [x] 8. Add Docker infrastructure for new services
  - [x] 8.1 Create `infrastructure/docker/Dockerfile.image-fetcher`
    - `FROM base-manim-agent`, copy shared + service app, install Python deps, expose port 8006
    - _Requirements: 6.2_

  - [x] 8.2 Create `infrastructure/docker/Dockerfile.compositor`
    - Multi-stage: `FROM node:18-slim AS node_stage` to install `hyperframes` at pinned version; `FROM base-manim-agent`, copy Node/npx from node stage, install `ffprobe`/`ffmpeg`, copy shared + service app, expose port 8005
    - _Requirements: 6.2, 6.3_

  - [x] 8.3 Update `docker-compose.yml`
    - Add `image-fetcher` service on port 8006 with `PEXELS_API_KEY`, `OPENAI_API_KEY` env vars and workspace volume
    - Rename/replace `assembler` service with `compositor` on port 8005 with `OPENAI_API_KEY`, `COMPOSITOR_LLM_MODEL` env vars
    - Add `IMAGE_FETCHER_URL=http://image-fetcher:8006` and `COMPOSITOR_LLM_MODEL` to orchestrator environment
    - Add `image-fetcher` to orchestrator `depends_on`
    - _Requirements: 6.1, 6.2, 6.4, 6.5, 6.6_

- [x] 9. Checkpoint — infrastructure wired
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Implement property-based tests in `tests/test_compositor_properties.py`
  - [x] 10.1 Write property test for SceneTimingRecord start-time accumulation (Properties 1 + 2)
    - Use `@given(st.lists(st.tuples(st.floats(min_value=0.1, max_value=60.0, allow_nan=False), st.floats(min_value=0.1, max_value=60.0, allow_nan=False)), min_size=1, max_size=20))` with `@settings(max_examples=200)`
    - Mock `probe_duration` to return the tuple values; call `compute_scene_timings`; assert `records[N].start_time_seconds == sum(max(v,a) for v,a in pairs[:N])` for all N; assert all `start_time_seconds >= 0.0`
    - **Property 1: SceneTimingRecord start-time accumulation**
    - **Property 2: start_time_seconds is always non-negative**
    - **Validates: Requirements 1.4, 1.6, 7.5**

  - [x] 10.2 Write property test for HTML round-trip structural equivalence (Property 3)
    - Use `@given(st.integers(0,5), st.integers(0,5), st.integers(0,5))` with `@settings(max_examples=100)`
    - Build synthetic HTML with N video, audio, img elements; parse with `CompositionValidator`; serialize; parse again; assert counts match
    - **Property 3: HTML round-trip structural equivalence**
    - **Validates: Requirements 8.5**

  - [x] 10.3 Write property test for magic byte validation (Property 4)
    - Use `@given(st.binary(min_size=0, max_size=64))` with `@settings(max_examples=200)`
    - Extract the magic-byte check logic from `main.py` into a testable `is_valid_image(data: bytes) -> bool` helper; assert it returns `True` iff bytes start with `FF D8 FF` or `89 50 4E 47`
    - **Property 4: Magic byte validation accepts only JPEG and PNG**
    - **Validates: Requirements 2.7**

  - [x] 10.4 Write property test for image fetcher scene coverage (Property 5)
    - Use `@given(st.lists(st.builds(ScenePlan, scene_id=st.integers(1,100), narration_text=st.text(min_size=1), visual_description=st.text(min_size=1), estimated_duration_seconds=st.integers(1,30)), min_size=1, max_size=10, unique_by=lambda s: s.scene_id))` with `@settings(max_examples=100)`
    - Mock Pexels and Wikimedia clients to return empty lists; call the image-fetcher fetch logic directly; assert every `scene_id` in input appears as a key in the returned `image_paths`
    - **Property 5: Image fetcher response covers all requested scenes**
    - **Validates: Requirements 2.5, 2.6**

  - [x] 10.5 Write property test for Pexels Authorization header (Property 6)
    - Use `@given(st.text(min_size=1, max_size=64, alphabet=st.characters(whitelist_categories=("L","N"))))` with `@settings(max_examples=100)`
    - Patch `httpx.AsyncClient` to capture request headers; instantiate `PexelsClient` with the generated key; call search; assert `Authorization` header equals the key
    - **Property 6: Pexels Authorization header carries the configured API key**
    - **Validates: Requirements 6.6**

  - [x] 10.6 Write property test for lower-third truncation (Property 7)
    - Use `@given(st.text(min_size=0, max_size=500))` with `@settings(max_examples=100)`
    - Extract the truncation expression `narration_text[:120]` into a testable `truncate_lower_third(text: str) -> str` helper; assert `len(result) <= 120` and `result == text` when `len(text) <= 120`
    - **Property 7: Lower-third narration text is truncated to 120 characters**
    - **Validates: Requirements 4.6**

- [x] 11. Final checkpoint — all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Task ordering follows graphify god-node principle: shared schemas (task 1) → services (tasks 2, 4–5) → graph wiring (tasks 7) → Docker/infra (task 8) → tests (task 10)
- `image-fetcher` runs on port 8006; `compositor` replaces `assembler` on port 8005 — orchestrator URL config unchanged
- Property tests in task 10 validate universal correctness properties defined in the design document
- The `is_valid_image` and `truncate_lower_third` helpers should be extracted as standalone functions to make them directly testable by the property tests
