# Graph Report - C:\Users\vicky\Desktop\samsung-lap-19-4\samsung-lap-19-4\video-gen\video-gen\manim-agent-network  (2026-04-30)

## Corpus Check
- 46 files · ~0 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 436 nodes · 808 edges · 17 communities detected
- Extraction: 67% EXTRACTED · 33% INFERRED · 0% AMBIGUOUS · INFERRED: 269 edges (avg confidence: 0.59)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 29|Community 29]]

## God Nodes (most connected - your core abstractions)
1. `SceneTimingRecord` - 41 edges
2. `AssemblyError` - 33 edges
3. `CompositionValidator` - 27 edges
4. `ScenePlan` - 27 edges
5. `ImageFetcherRequest` - 16 edges
6. `ValidatorRequest` - 12 edges
7. `set_log_context()` - 11 edges
8. `compose_html()` - 10 edges
9. `assemble()` - 10 edges
10. `JobDatabase` - 10 edges

## Surprising Connections (you probably didn't know these)
- `Validates HyperFrames HTML composition.` --uses--> `AssemblyError`  [INFERRED]
  services\compositor\app\html_validator.py → services\compositor\app\duration_prober.py
- `Parse HTML composition and verify all requirements.      Validates:     1. HTML` --uses--> `AssemblyError`  [INFERRED]
  services\compositor\app\html_validator.py → services\compositor\app\duration_prober.py
- `Generate TTS using OpenAI. Returns True if successful.` --uses--> `VoiceoverRequest`  [INFERRED]
  services\voiceover\app\main.py → shared\schemas\requests.py
- `Generate TTS using OpenAI. Returns True if successful.` --uses--> `VoiceoverResponse`  [INFERRED]
  services\voiceover\app\main.py → shared\schemas\responses.py
- `Fallback to espeak (last resort).` --uses--> `VoiceoverRequest`  [INFERRED]
  services\voiceover\app\main.py → shared\schemas\requests.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.08
Nodes (47): AssemblyError, compute_scene_timings(), probe_duration(), Duration probing and scene timing computation for the compositor service.  Thi, Custom exception for assembly-related errors., Run ffprobe and return duration in seconds (3 decimal places).          Args:, Probe all files and compute start_time_seconds by accumulation.          For H, HTML validation for HyperFrames composition documents. (+39 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (41): check_env_key(), EnvGuardResult, HealthCheckResult, is_valid_job_status(), parse_generate_response(), parse_health_response(), parse_semver(), Pure Python helper module for property-based tests of the project-init feature. (+33 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (36): CompositionValidator, Validates HyperFrames HTML composition., Parse HTML composition and verify all requirements.      Validates:     1. HTML, validate_composition(), truncate_lower_third(), HTMLParser, _build_html(), Property-based tests for the manim-hyperframes-compositor feature.  Tests vali (+28 more)

### Community 3 - "Community 3"
Cohesion: 0.09
Nodes (34): assemble(), assemble_video(), _build_hf_prompt(), _build_manim_prompt(), classify_scene(), _extract_html(), generate_code(), _generate_hyperframes() (+26 more)

### Community 4 - "Community 4"
Cohesion: 0.16
Nodes (35): LangGraphState, generate_script(), BaseModel, GenerationRequest, JobState, ScenePlan, ScriptResponse, Validate a single scene. Returns (scene_id, render_path, error_log). (+27 more)

### Community 5 - "Community 5"
Cohesion: 0.1
Nodes (27): _clean_keywords(), extract_keywords(), _fallback_tokenize(), _parse_keywords_json(), Keyword extractor module for the image-fetcher service.  Extracts 1-5 keywords, Parse the LLM response content as a JSON array of keywords.          Handles c, Normalize and filter keywords for better search quality., Fallback tokenizer that filters narration_text into 1-5 useful keywords. (+19 more)

### Community 6 - "Community 6"
Cohesion: 0.13
Nodes (23): check_latex_error(), manim_scene_strategy(), Property-based tests for LaTeX package availability in Manim rendering.  Task, Generate Manim scene code with Tex/MathTex objects., Render Manim code inside the validator Docker container.          Args:, Render Manim code via the validator service API.          Args:         code:, Check if the output contains LaTeX package errors.          Returns:, Specific test for standalone.cls package availability.          This test spec (+15 more)

### Community 7 - "Community 7"
Cohesion: 0.13
Nodes (11): detect_content_type(), health(), Validate HyperFrames HTML content., Detect content type based on file content.          Args:         code_path:, Validate Manim Python code., Validate HyperFrames HTML structure.          Checks for valid HTML with at le, validate_code(), validate_hyperframes() (+3 more)

### Community 8 - "Community 8"
Cohesion: 0.18
Nodes (17): assembler_node(), code_generator_node(), _generate_one_scene(), _generate_voiceover(), image_fetcher_node(), _post(), script_writer_node(), _validate_one_scene() (+9 more)

### Community 9 - "Community 9"
Cohesion: 0.1
Nodes (5): Scene, Scene1, Scene2, Scene3, Scene4

### Community 10 - "Community 10"
Cohesion: 0.14
Nodes (13): _acquire_rate_slot_sync(), get_llm_client(), _get_semaphore(), _NimChat, NimClient, _NimCompletions, Shared NVIDIA NIM chat client with async-safe rate limiting.  Rate limit: config, Sync entry point — used by services that call from sync context. (+5 more)

### Community 11 - "Community 11"
Cohesion: 0.16
Nodes (9): _get_connection(), JobDatabase, Persistent job storage using SQLite. Provides durability across orchestrator re, List jobs with optional status filter., Delete jobs older than specified days., Get webhook URL for a job., Thread-safe SQLite database for job persistence., Initialize database schema. (+1 more)

### Community 12 - "Community 12"
Cohesion: 0.2
Nodes (16): generate_espeak_fallback(), generate_kokoro_tts(), generate_voiceover(), _get_kokoro(), _provider_output_path(), Split text into sentence-boundary chunks under max_chars., Emergency espeak-ng fallback. Uses espeak-ng (Debian package name)., _split_text() (+8 more)

### Community 13 - "Community 13"
Cohesion: 0.19
Nodes (16): filter_by_relevance(), _image_embedding(), _image_session(), _models_available(), _preprocess_image(), SigLIP ONNX relevance scorer for image-text similarity.  Uses the ONNX-exporte, Return a relevance score in [0, 1] between the image and query_text.      Uses, Score all images against query_text, keep those above threshold,     return top (+8 more)

### Community 14 - "Community 14"
Cohesion: 0.18
Nodes (1): Smoke tests: hit /health on every service via TestClient (no Docker needed).

### Community 15 - "Community 15"
Cohesion: 0.67
Nodes (3): BaseSettings, Settings, Settings

### Community 29 - "Community 29"
Cohesion: 1.0
Nodes (1): Get thread-local database connection.

## Knowledge Gaps
- **72 isolated node(s):** `Keyword extractor module for the image-fetcher service.  Extracts 1-5 keywords`, `Extract 1-5 keywords from narration_text and visual_description using an LLM.`, `Parse the LLM response content as a JSON array of keywords.          Handles c`, `Normalize and filter keywords for better search quality.`, `Fallback tokenizer that filters narration_text into 1-5 useful keywords.` (+67 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 14`** (11 nodes): `code_generator_client()`, `compositor_client()`, `orchestrator_client()`, `test_health_checks.py`, `Smoke tests: hit /health on every service via TestClient (no Docker needed).`, `script_writer_client()`, `test_compositor_health()`, `test_validator_health()`, `test_voiceover_health()`, `validator_client()`, `voiceover_client()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 29`** (1 nodes): `Get thread-local database connection.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `set_log_context()` connect `Community 3` to `Community 12`, `Community 4`, `Community 5`, `Community 7`?**
  _High betweenness centrality (0.095) - this node is a cross-community bridge._
- **Why does `assemble()` connect `Community 3` to `Community 0`, `Community 2`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Why does `fetch_images_for_scene()` connect `Community 5` to `Community 3`?**
  _High betweenness centrality (0.077) - this node is a cross-community bridge._
- **Are the 39 inferred relationships involving `SceneTimingRecord` (e.g. with `AssemblyError` and `compute_scene_timings()`) actually correct?**
  _`SceneTimingRecord` has 39 INFERRED edges - model-reasoned connections that need verification._
- **Are the 29 inferred relationships involving `AssemblyError` (e.g. with `SceneTimingRecord` and `CompositionValidator`) actually correct?**
  _`AssemblyError` has 29 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `CompositionValidator` (e.g. with `AssemblyError` and `Property-based tests for the manim-hyperframes-compositor feature.  Tests vali`) actually correct?**
  _`CompositionValidator` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `ScenePlan` (e.g. with `Generate code for a single scene. Returns (scene_id, code_path, error).` and `Validate a single scene. Returns (scene_id, render_path, error_log).`) actually correct?**
  _`ScenePlan` has 25 INFERRED edges - model-reasoned connections that need verification._