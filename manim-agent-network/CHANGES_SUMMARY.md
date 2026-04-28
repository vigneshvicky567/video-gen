# Complete Changes Summary

## Overview
This document summarizes all changes made to fix video generation issues including portrait orientation, incomplete duration, and voiceover failures.

---

## 🎯 Problems Fixed

### 1. **Portrait Orientation Issue** (480×270 instead of 1920×1080)
- **Root Cause**: Validator used `-ql` (low quality) flag producing 480p15 portrait renders
- **Fix**: Changed to `-qm` (medium quality) for 720p30 landscape output

### 2. **Incomplete Video Duration** (16.7s instead of 53s)
- **Root Cause**: Missing HyperFrames metadata attributes (data-composition-id, data-duration, data-width, data-height)
- **Fix**: Deterministic HTML generation with all required HyperFrames attributes

### 3. **Voiceover Failures** (Silent fallback to espeak)
- **Root Cause**: Broken Dia2 installation, missing CUDA, no OpenAI key
- **Fix**: Proper Dia2 installation, Kokoro ONNX fallback, removed OpenAI dependency

---

## 📦 Changed Files (21 total)

### Configuration Files

#### `.env`
- **Removed**: `OPENAI_API_KEY`, `OPENAI_TIMEOUT_SECONDS`, `VOICEOVER_MODEL`
- **Added**: 
  - `NVIDIA_API_KEY` for all LLM calls
  - `VOICEOVER_PROVIDER=dia2`
  - `VOICEOVER_FALLBACK_PROVIDER=kokoro`
  - `ALLOW_ESPEAK_FALLBACK=false`
  - Dia2 configuration: `DIA2_MODEL`, `DIA2_DEVICE`, `DIA2_DTYPE`, `DIA2_CFG_SCALE`, `DIA2_TEMPERATURE`
  - Kokoro configuration: `KOKORO_MODEL_PATH`, `KOKORO_VOICES_PATH`, `KOKORO_VOICE`, `KOKORO_SPEED`, `KOKORO_LANG`

#### `.env.template`
- Same changes as `.env` with placeholder values
- Added comprehensive comments explaining each provider

#### `README.md`
- Updated architecture diagram to show NVIDIA NIM and local TTS
- Removed all OpenAI references
- Added voiceover provider documentation (Dia2 + Kokoro)
- Updated environment variables table
- Added troubleshooting section for TTS issues

#### `docker-compose.yml`
- Updated voiceover service environment variables
- Removed OpenAI-related env vars from all services
- Added NVIDIA NIM configuration across services

#### `requirements.txt`
- **Removed**: `openai>=...` package
- **Added**: 
  - `httpx` for NVIDIA NIM HTTP client
  - `kokoro-onnx` for offline TTS fallback
  - `soundfile` for audio file handling
  - `onnxruntime` for Kokoro model inference

---

### Infrastructure Changes

#### `infrastructure/docker/Dockerfile.voiceover`
- Install Dia2 from official `nari-labs/dia2` GitHub source (not broken PyPI package)
- Preinstall Kokoro ONNX model assets for offline operation
- Add Docker build sanity check: `from dia2 import Dia2, GenerationConfig, SamplingConfig`
- Install `ffmpeg` for audio validation
- Download Kokoro models during build to `/models/kokoro/`

---

### Service Changes

#### `services/voiceover/app/main.py` (Complete Rewrite)
**New Features**:
- **Provider cascade**: Dia2 → Kokoro → espeak (if enabled)
- **CUDA detection**: Auto-skip Dia2 if CUDA unavailable when `DIA2_DEVICE=cuda`
- **Audio validation**: ffprobe check for every generated file
- **Provider metadata**: Returns `provider_used`, `fallback_used`, `warning` in response
- **Fail loudly**: Job fails if all acceptable providers fail (no silent espeak fallback)

**Key Functions**:
- `generate_dia2_tts()`: Dia2 generation with proper import and config
- `generate_kokoro_tts()`: Kokoro ONNX fallback
- `generate_espeak_fallback()`: Emergency fallback (disabled by default)
- `_validate_audio()`: ffprobe validation for existence, size, and audio stream
- `_cuda_available()`: Runtime CUDA detection

#### `services/validator/app/main.py`
**Key Changes**:
- Changed Manim quality flag: `-ql` → `-qm` (480p15 portrait → 720p30 landscape)
- Added content type detection: `detect_content_type()` distinguishes Manim vs HyperFrames
- Added HyperFrames validation: `validate_hyperframes()` checks for:
  - `data-composition-id` on root
  - `data-width` and `data-height` on root
  - `data-start` and `data-duration` on clips
  - Object timeline registration: `window.__timelines['id'] = tl`
  - Rejects array syntax: `window.__timelines.push(tl)`
- Fail fast if new renders still produce 480p15 output
- Improved error logging with full code dump on failure

#### `services/compositor/app/main.py`
**Key Changes**:
- Simplified assembly flow: compute timings → generate HTML → validate → render
- Removed LLM-based composition generation
- Added deterministic HTML generation via `compose_html()`
- Strengthened HTML validation before HyperFrames render
- Better error handling with full traceback logging

#### `services/compositor/app/llm_composer.py` (Major Refactor)
**Before**: LLM-generated HTML with unpredictable structure
**After**: Deterministic Python template generation

**New `compose_html()` Function**:
- Generates stable HyperFrames HTML from `SceneTimingRecord` list
- **Root div attributes**:
  ```html
  <div id="composition"
       data-composition-id="main"
       data-start="0"
       data-duration="53.8"
       data-width="1920"
       data-height="1080">
  ```
- **Video elements** (Manim scenes):
  ```html
  <video class="clip scene-visual"
         id="video-scene-2"
         data-start="5"
         data-duration="11"
         data-track-index="9"
         src="render_scene_2/videos/scene_2/720p30/Scene2.mp4"
         style="position:absolute;left:320px;top:180px;width:1280px;height:720px;"
         muted playsinline>
  ```
- **Audio elements**:
  ```html
  <audio class="clip"
         id="audio-scene-2"
         data-start="5"
         data-duration="5.563"
         data-track-index="12"
         src="scene_2_audio.wav">
  ```
- **Timeline registration**:
  ```javascript
  window.__timelines = window.__timelines || {};
  window.__timelines["main"] = tl;
  ```

**Key Improvements**:
- All media elements have unique IDs
- Correct timing attributes (data-start, data-duration)
- Non-overlapping track indexes
- Landscape video positioning (centered 1280×720 in 1920×1080 canvas)
- Lower-third narration overlays with proper styling

#### `services/compositor/app/html_validator.py`
**New Validations**:
- Root must have `data-composition-id`
- Root must have `data-width` and `data-height`
- Root must have `data-duration`
- All media elements must have `id` attributes
- Timeline must use object syntax: `window.__timelines['id']`
- Reject array syntax: `window.__timelines.push()`
- Validate local file paths exist

---

### Shared Code Changes

#### `shared/config.py`
**Removed**:
- `OPENAI_API_KEY`
- `OPENAI_TIMEOUT_SECONDS`
- `VOICEOVER_MODEL` (was `tts-1-hd`)

**Added**:
- `NVIDIA_API_KEY`: NVIDIA NIM API key
- `NVIDIA_BASE_URL`: `https://integrate.api.nvidia.com/v1`
- `NVIDIA_TIMEOUT_SECONDS`: 120
- `VOICEOVER_PROVIDER`: Primary TTS provider (dia2 | kokoro)
- `VOICEOVER_FALLBACK_PROVIDER`: Fallback TTS provider
- `ALLOW_ESPEAK_FALLBACK`: Emergency fallback toggle
- Dia2 settings: `DIA2_MODEL`, `DIA2_DEVICE`, `DIA2_DTYPE`, `DIA2_CFG_SCALE`, `DIA2_TEMPERATURE`
- Kokoro settings: `KOKORO_MODEL_PATH`, `KOKORO_VOICES_PATH`, `KOKORO_VOICE`, `KOKORO_SPEED`, `KOKORO_LANG`

#### `shared/llm_client.py` (Complete Rewrite)
**Before**: Used OpenAI Python SDK
**After**: Custom NVIDIA NIM HTTP client

**New Implementation**:
```python
class NimClient:
    """Small compatibility wrapper for existing chat completion call sites."""
    def __init__(self):
        self.chat = _NimChat()

class _NimChat:
    def __init__(self):
        self.completions = _NimCompletions()

class _NimCompletions:
    def create(self, **kwargs):
        # Direct httpx POST to NVIDIA NIM endpoint
        # Returns SimpleNamespace with same structure as OpenAI response
```

**Benefits**:
- No OpenAI SDK dependency
- Direct HTTP control
- Same API surface for existing callers
- Works with NVIDIA's OpenAI-compatible endpoint

#### `shared/schemas/responses.py`
**Updated `VoiceoverResponse`**:
```python
class VoiceoverResponse(BaseModel):
    scene_id: int
    audio_path: str
    provider_used: Optional[str] = None      # NEW: actual provider used
    fallback_used: bool = False              # NEW: whether fallback was used
    warning: Optional[str] = None            # NEW: optional warning message
```

---

### Other Service Updates

#### `services/code-generator/app/main.py`
- Updated to use new `get_llm_client()` from `shared.llm_client`
- Removed OpenAI SDK imports

#### `services/image-fetcher/app/keyword_extractor.py`
- Updated to use new `get_llm_client()` from `shared.llm_client`
- Removed OpenAI SDK imports

#### `services/orchestrator/app/core/graph.py`
- Updated to use new `get_llm_client()` from `shared.llm_client`
- Logs actual voiceover provider used
- Removed OpenAI SDK imports

---

### Test Updates

#### `tests/test_voiceover.py`
- Updated to test new provider cascade logic
- Tests Dia2 → Kokoro → espeak fallback flow
- Tests CUDA availability detection
- Tests audio validation
- Tests provider metadata in response

#### `tests/test_html_validator.py`
- Added tests for new HyperFrames validations
- Tests root composition ID requirement
- Tests root dimensions requirement
- Tests timeline registration format
- Tests media ID requirements

#### `tests/test_llm_composer.py`
- Updated to test deterministic HTML generation
- Tests root attributes presence
- Tests media element structure
- Tests timeline registration format

#### `tests/test_project_init_properties.py`
- Updated to reflect new configuration structure
- Removed OpenAI-related property tests
- Added NVIDIA NIM property tests

---

## 🔄 Migration Path

### For Existing Deployments

1. **Update environment variables**:
   ```bash
   # Remove
   unset OPENAI_API_KEY
   unset VOICEOVER_MODEL
   
   # Add
   export NVIDIA_API_KEY="your-nvidia-api-key"
   export VOICEOVER_PROVIDER="dia2"
   export VOICEOVER_FALLBACK_PROVIDER="kokoro"
   ```

2. **Rebuild all services**:
   ```bash
   docker compose build
   ```

3. **Recreate containers** (important for validator -qm flag):
   ```bash
   docker compose down
   docker compose up -d
   ```

4. **Verify new renders**:
   - Check validator logs show `manim render -qm`
   - Confirm new Manim outputs are in `720p30/` folders
   - Verify voiceover logs show Dia2 or Kokoro (not espeak)

---

## 🎬 Expected Behavior After Fixes

### Video Quality
- ✅ **Landscape orientation**: 1280×720 (not 480×270 portrait)
- ✅ **Proper aspect ratio**: 16:9 widescreen
- ✅ **Better quality**: 720p30 instead of 480p15
- ✅ **Centered in composition**: Videos positioned at left:320px to center in 1920×1080 canvas

### Video Duration
- ✅ **Full duration**: 53+ seconds (all scenes)
- ✅ **All scenes included**: Title card + all scenes with audio
- ✅ **Proper timing**: Sequential scenes with correct start times
- ✅ **No premature stopping**: HyperFrames renders complete timeline

### Voiceover Quality
- ✅ **High-quality TTS**: Dia2 (GPU) or Kokoro (CPU) instead of espeak
- ✅ **Proper fallback**: Automatic cascade when primary fails
- ✅ **Provider transparency**: Logs show which provider was actually used
- ✅ **Fail loudly**: Job fails if acceptable providers unavailable (no silent espeak)

### HyperFrames Compliance
- ✅ **No lint warnings**: All required attributes present
- ✅ **Correct dimensions**: 1920×1080 landscape detected
- ✅ **Proper timeline**: GSAP timeline registered correctly
- ✅ **Media discovery**: All video/audio elements have IDs

---

## 🧪 Testing Checklist

- [ ] Generate new video with fixed services
- [ ] Check video files are in `720p30/` folders (not `480p15/`)
- [ ] Verify composition HTML has all required attributes
- [ ] Check HyperFrames logs for no lint warnings
- [ ] Measure final video duration (should be 53+ seconds)
- [ ] Visual inspection shows landscape orientation
- [ ] Voiceover logs show Dia2 or Kokoro (not espeak)
- [ ] Audio quality is acceptable (not robotic espeak)

---

## 📚 Technical Details

### Manim Quality Flags
- `-ql`: Low quality, 480p15, **portrait** (480×270) ❌
- `-qm`: Medium quality, 720p30, **landscape** (1280×720) ✅
- `-qh`: High quality, 1080p60, landscape (1920×1080)

### HyperFrames Required Attributes
```html
<!-- Root composition -->
<div data-composition-id="main"
     data-start="0"
     data-duration="53.8"
     data-width="1920"
     data-height="1080">
  
  <!-- Media clips -->
  <video id="video-scene-2"
         data-start="5"
         data-duration="11"
         data-track-index="9"
         src="...">
  
  <audio id="audio-scene-2"
         data-start="5"
         data-duration="5.563"
         data-track-index="12"
         src="...">
</div>

<!-- Timeline registration -->
<script>
  window.__timelines = window.__timelines || {};
  window.__timelines["main"] = tl;  // Object syntax, not array push
</script>
```

### Voiceover Provider Cascade
1. **Dia2** (primary, GPU-accelerated)
   - Requires CUDA when `DIA2_DEVICE=cuda`
   - Auto-skips if CUDA unavailable
   - High-quality dialogue TTS

2. **Kokoro ONNX** (fallback, CPU-capable)
   - Preinstalled in Docker image
   - Works offline
   - Lightweight, good quality

3. **espeak** (emergency only)
   - Disabled by default (`ALLOW_ESPEAK_FALLBACK=false`)
   - Robotic voice
   - Only for smoke tests

---

## 🔗 Related Documentation

- [HyperFrames Documentation](https://github.com/hyperframes/hyperframes)
- [Dia2 GitHub](https://github.com/nari-labs/dia2)
- [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx)
- [Manim Community Edition](https://docs.manim.community/)
- [NVIDIA NIM](https://build.nvidia.com/)

---

## 🙏 Credits

Changes implemented by AI agent to fix:
1. Portrait orientation issue (480×270 → 720p30 landscape)
2. Incomplete video duration (16.7s → full 53s)
3. Voiceover failures (espeak → Dia2/Kokoro)
4. OpenAI dependency removal (→ NVIDIA NIM)
5. Deterministic HyperFrames composition generation
