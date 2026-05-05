# TODO

## ✅ All Done

- [x] Manim render quality: `-ql` (480p15 portrait) → `-qm` (720p30 landscape)
- [x] HyperFrames composition: deterministic Python generation (no LLM)
- [x] HyperFrames root attributes: `data-composition-id`, `data-duration`, `data-width`, `data-height`
- [x] HyperFrames timeline: `window.__timelines["main"] = tl` (object syntax)
- [x] HyperFrames media: unique `id` on every `<video>` and `<audio>` element
- [x] Removed OpenAI SDK dependency entirely
- [x] LLM client replaced with direct NVIDIA NIM httpx client
- [x] Removed Dia2 and PyTorch/CUDA from voiceover service and docker-compose
- [x] Kokoro ONNX set as primary TTS (CPU, offline, preinstalled in image)
- [x] Kokoro voice set to `af_bella` (warmer tone, better for educational content)
- [x] Kokoro speed set to `0.9` (easier to follow for math/technical content)
- [x] Long-text chunking in Kokoro TTS (splits at sentence boundaries, 400 char limit)
- [x] All containers rebuilt with fresh images
- [x] All containers restarted (no stale code running)
- [x] Stale workspace/temp artifacts cleaned (19 old 480p15 job folders deleted)
- [x] CHANGES_SUMMARY.md deleted (was outdated working doc)
- [x] Health-check tests added (`tests/test_health_checks.py`)
- [x] Tests updated to reflect Kokoro-only provider
- [x] README updated to remove Dia2/OpenAI references

---

## 🔍 Next time you generate a video, verify:

```bash
# Voiceover logs should show Kokoro, not espeak
docker compose logs voiceover --follow

# Final video should be full duration
ffprobe workspace/outputs/<job_id>_final.mp4 2>&1 | grep Duration

# Manim renders should be 720p30, not 480p15
ls workspace/temp/<job_id>/render_scene_*/videos/*/*/
```
