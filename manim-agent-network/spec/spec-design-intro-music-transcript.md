---
title: Intro Video, Background Music Bed, and Live Transcript
version: 1.0
date_created: 2026-06-21
owner: Manim Agent Network
tags: [design, compositor, frontend, audio, video]
---

# Introduction

Three production-polish features for the Manim Agent Network video pipeline:

- **A. Prebuilt intro** — a user-supplied branded MP4 is concatenated before every generated film.
- **B. Background music bed** — a user-supplied music track is mixed under the narration at low volume for the whole film.
- **C. Live transcript** — a clickable, auto-highlighting transcript on the studio watch ("the cut") page that seeks the video.

A and B are server-side, done in the **compositor** service at assemble time (ffmpeg). C is **frontend-only** (vanilla JS studio), using data already returned by `GET /job/{id}`.

## 1. Purpose & Scope

Raise perceived production quality (branding + audio) and watch-page utility (transcript) without changing the generation pipeline (script → voiceover → images → code → render). Scope is limited to: the compositor's final assemble step, one optional orchestrator passthrough field, the studio `frontend/`, docker-compose asset mounts, and `.env` config. Out of scope: per-scene music, ducking/sidechain (constant low volume only in v1), word-level transcript timing (sentence/scene-level only in v1), outro.

Intended audience: the engineer implementing these features. The user supplies the intro `.mp4` and music audio file as assets; the pipeline consumes them.

## 2. Definitions

- **Compositor**: service at `services/compositor/`, reachable as `ASSEMBLER_URL` (`http://compositor:8005`). Builds the HyperFrames master timeline, renders it (chunked for long films), and concatenates chunks into the final MP4. Entry: `services/compositor/app/main.py`.
- **Film / generated film**: the rendered explainer MP4 produced today (`final_output_path`), 1920×1080.
- **Intro**: a short fixed branded clip prepended to the film.
- **Music bed**: a looping low-volume background music track under the entire mixed audio.
- **The cut**: studio view (`cutShell()` in `frontend/js/studio.js`) showing the finished film player + filmstrip.
- **Cue / segment**: per-sentence `{text,start,duration}` timing produced by voiceover, stored in job state `audio_segments[scene_id]`.
- **Slot duration**: a scene's on-timeline length = `max(video_duration, audio_duration)`; scene start = sum of prior slot durations.

## 3. Requirements, Constraints & Guidelines

### Feature A — Intro video
- **INT-001**: When an intro asset exists, the compositor MUST concatenate it BEFORE the generated film, producing a single MP4 at `final_output_path`.
- **INT-002**: Intro presence is controlled by `INTRO_VIDEO_PATH` (env). If unset or the file is missing, the pipeline MUST proceed with the film only (no error).
- **INT-003**: The concatenation MUST normalize the intro to the film's resolution (1920×1080), frame rate, pixel format, and audio sample rate/codec so playback has no glitches. Use the ffmpeg `concat` filter (re-encode) rather than the stream-copy concat demuxer, because the intro is produced externally and will not match codec params.
- **INT-004**: If the intro has no audio track, a silent track of the intro's duration MUST be synthesized so the concat audio stream is continuous.
- **CON-001**: The intro MUST NOT be re-rendered per job. Normalize/probe it at most once per job (or cache a normalized copy keyed by source mtime).
- **GUD-001**: Recommended intro asset: 1920×1080, H.264 + AAC, 2–6 seconds, ≤20 MB.

### Feature B — Background music
- **MUS-001**: When a music asset exists, the compositor MUST mix it under the film's full audio at low volume across the entire duration.
- **MUS-002**: Music presence is controlled by `BG_MUSIC_PATH` (env). If unset or missing, proceed with narration-only audio (no error).
- **MUS-003**: Music volume MUST be configurable via `BG_MUSIC_VOLUME` (linear gain, default `0.12` ≈ −18 dB). Narration stays at unity gain.
- **MUS-004**: If music is shorter than the film it MUST loop; if longer it MUST be trimmed to film length. A fade-out over the final `BG_MUSIC_FADEOUT_SECONDS` (default `2.0`) MUST be applied.
- **MUS-005**: The music mix applies to the FILM audio. Ordering relative to Feature A: music is mixed into the film FIRST, then the intro (which has its own audio) is concatenated. The intro is NOT music-bedded.
- **GUD-002**: v1 uses CONSTANT low volume, NOT sidechain ducking. Ducking is a future enhancement (see §7).
- **GUD-003**: Recommended music asset: MP3 or M4A, instrumental, royalty-free/licensed, any length.

### Feature C — Live transcript
- **TRN-001**: On "the cut" view, render a transcript panel listing the narration, one entry per scene (v1) using `script.scenes[].title` + `narration_text`.
- **TRN-002**: Clicking a transcript entry MUST seek the film player (`#screen video`) to that scene's start time and play.
- **TRN-003**: As the film plays, the transcript entry for the current playhead MUST be highlighted (auto-scroll into view), updated on the video `timeupdate` event.
- **TRN-004**: Scene start time MUST be computed as the cumulative sum of prior scenes' slot durations (`max(estimated/actual video, audio)`), matching how the compositor lays out the timeline. Reuse the existing filmstrip cumulative-start logic in `studio.js`.
- **TRN-005 (timing offset)**: If Feature A is active, EVERY transcript timestamp MUST be offset by the intro duration, because the intro shifts all scene start times in the final MP4. The intro duration MUST be exposed to the frontend (job state field `intro_duration_seconds`, default `0`).
- **CON-002**: Feature C is frontend-only and MUST NOT require new backend endpoints; it consumes `GET /job/{id}` (already returns `script`, `audio_segments`, and—after this spec—`intro_duration_seconds`).
- **GUD-004 (optional refinement)**: If `audio_segments[scene_id]` is present, sub-list each sentence with its own seek time (`scene_start + segment.start + intro_offset`) for finer navigation. Degrade to scene-level when absent.

### Cross-cutting
- **CON-003**: All three features are additive and independently toggleable. With all assets absent and Feature C aside, output is byte-for-byte today's behavior.
- **SEC-001**: Asset paths come from env/mounted read-only volumes, never from user request bodies (no path injection into ffmpeg).
- **CON-004**: ffmpeg invocations MUST pass the same wall-clock-scaled timeout treatment already used by the assembler; the extra concat/mix pass is short but MUST be inside the assemble timeout budget.

## 4. Interfaces & Data Contracts

### Configuration (`.env` + docker-compose `compositor` env)
| Var | Default | Meaning |
|---|---|---|
| `INTRO_VIDEO_PATH` | `` (unset) | Absolute path (in-container) to intro MP4, e.g. `/assets/intro.mp4`. Empty = no intro. |
| `BG_MUSIC_PATH` | `` (unset) | In-container path to music file, e.g. `/assets/music.mp3`. Empty = no music. |
| `BG_MUSIC_VOLUME` | `0.12` | Linear gain for the music bed (narration = 1.0). |
| `BG_MUSIC_FADEOUT_SECONDS` | `2.0` | Music fade-out length at film end. |

### Asset mount (docker-compose.yml, `compositor` service)
```yaml
    volumes:
      - ./workspace:/workspace
      - ./assets:/assets:ro          # NEW — user drops intro.mp4 / music.mp3 here
```

### Job state addition (orchestrator)
| Field | Type | Source | Consumer |
|---|---|---|---|
| `intro_duration_seconds` | float | compositor returns it from `/assemble`; orchestrator stores in state | frontend transcript offset (TRN-005) |

`GET /job/{id}` already returns `script`, `audio_segments`, `final_output_path`. Add `intro_duration_seconds` (default `0.0` when no intro).

### Compositor `/assemble` response (additive)
```json
{ "final_output_path": "/workspace/.../final.mp4", "intro_duration_seconds": 4.0 }
```

## 5. Acceptance Criteria

- **AC-001 (intro present)**: Given `INTRO_VIDEO_PATH` points to a valid MP4, When a job assembles, Then `final_output_path` plays the intro first then the film, with continuous audio and no resolution/fps glitch at the seam.
- **AC-002 (intro absent)**: Given `INTRO_VIDEO_PATH` unset, When a job assembles, Then output equals current behavior and no ffmpeg intro step runs.
- **AC-003 (intro no-audio)**: Given an intro MP4 with no audio stream, When concatenated, Then the final audio track is continuous (silent during intro) and A/V stays in sync afterward.
- **AC-004 (music present)**: Given `BG_MUSIC_PATH` set and `BG_MUSIC_VOLUME=0.12`, When a job assembles, Then narration is clearly audible over a quiet music bed for the full film, with a fade-out at the end.
- **AC-005 (music loop/trim)**: Given music shorter/longer than the film, Then it loops/trims to exactly the film length.
- **AC-006 (music absent)**: Given `BG_MUSIC_PATH` unset, Then audio equals current narration-only behavior.
- **AC-007 (transcript seek)**: Given the cut view, When a transcript entry is clicked, Then the player seeks to that scene's start (including intro offset) and plays.
- **AC-008 (transcript highlight)**: Given the film is playing, When the playhead enters a scene's window, Then that transcript entry is highlighted and scrolled into view.
- **AC-009 (transcript offset)**: Given an intro of N seconds, Then transcript seek times equal `scene_cumulative_start + N` and land on the correct spoken content.
- **AC-010 (independence)**: Given all assets absent, Then the only change vs today is the transcript panel rendering on the cut view.

## 6. Test Automation Strategy

- **Test Levels**: Unit (ffmpeg arg builders, cumulative-start math); Integration (compositor assemble with/without assets); Manual (visual/audio review of one rendered film + transcript click).
- **Frameworks**: `pytest` for Python (compositor helpers); a small `assert`-based DOM check or manual reload for the JS transcript (no framework — matches repo norms).
- **Test Data**: a 3s 1920×1080 test intro, a 10s test music clip, a ≥2-scene job. Tiny fixtures committed under `services/compositor/tests/fixtures/`.
- **Key unit tests**:
  - `build_intro_concat_cmd()` emits the concat-filter graph for a 2-input case; and returns `None` when path missing.
  - `build_music_mix_cmd()` emits `aloop`+`volume`+`afade` and trims to film duration; returns `None` when path missing.
  - intro-duration probe via `ffprobe` parses to float; missing file → `0.0`.
  - transcript cumulative-start matches the filmstrip seek logic for a 3-scene fixture.
- **Coverage**: the two ffmpeg arg-builders and the duration/offset math (the only non-trivial logic) must each have one passing assert-test. No coverage target beyond "the branch that breaks has a test."

## 7. Rationale & Context

- **Why compositor, ffmpeg**: the assemble step already runs ffmpeg concat for chunks and probes durations (`services/compositor/app/main.py`, `duration_prober.py`). Intro-concat and music-mix are the same class of operation in the same place — no new infra.
- **Why concat *filter* not demuxer for intro (INT-003)**: the stream-copy concat demuxer requires identical codec/timebase across inputs. The intro is authored externally and will not match; re-encoding via the concat filter (with `scale`,`fps`,`format`,`aresample`) is robust. The film is re-muxed once more — acceptable cost for reliability.
- **Why music mixed before intro (MUS-005)**: the intro is branding with its own sound; bedding music under it is unwanted. Mixing music into the film audio first, then concatenating the intro, keeps the intro pristine.
- **Why constant volume not ducking (GUD-002)**: ducking (`sidechaincompress`) needs tuning to avoid pumping; constant low volume is predictable and ships now. Ducking can replace the `volume` filter later behind the same env.
- **Why transcript is frontend-only (CON-002)**: `GET /job/{id}` already carries `script` + `audio_segments`; the cut view already seeks `#screen video` by cumulative start (filmstrip click). Transcript is the same data + a `timeupdate` highlight.
- **Why the intro offset (TRN-005)**: prepending the intro shifts the film later in the final MP4; without the offset, every transcript seek lands `intro_duration` too early.

## 8. Dependencies & External Integrations

### Infrastructure Dependencies
- **INF-001**: `ffmpeg` + `ffprobe` in the compositor image — already present (used for chunk concat and duration probing).
- **INF-002**: Read-only `./assets` volume mounted into the compositor container.

### Data Dependencies
- **DAT-001**: Intro MP4 — user-supplied, 1920×1080 H.264/AAC recommended, dropped at `./assets/intro.mp4`.
- **DAT-002**: Music file — user-supplied MP3/M4A, dropped at `./assets/music.mp3`.

### Technology Platform Dependencies
- **PLT-001**: Existing FastAPI compositor (Python) and vanilla-JS studio served statically from `frontend/` (no build step; cache-bust via `?v=reelNN` in `studio.html`).

## 9. Examples & Edge Cases

Intro + film concat (re-encode, normalize, synth-silence if intro has no audio):
```bash
ffmpeg -y -i intro.mp4 -i film.mp4 -filter_complex "\
 [0:v]scale=1920:1080,setsar=1,fps=30,format=yuv420p[v0];\
 [1:v]scale=1920:1080,setsar=1,fps=30,format=yuv420p[v1];\
 [0:a]aresample=48000,aformat=channel_layouts=stereo[a0];\
 [1:a]aresample=48000,aformat=channel_layouts=stereo[a1];\
 [v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" \
 -map "[v]" -map "[a]" -c:v libx264 -c:a aac -movflags +faststart out.mp4
# If intro has no audio: replace [0:a]... with anullsrc=r=48000:cl=stereo trimmed to intro duration.
```

Music bed mix (loop, low volume, fade-out; `D` = film duration from ffprobe):
```bash
ffmpeg -y -i film.mp4 -stream_loop -1 -i music.mp3 -filter_complex "\
 [1:a]volume=0.12,afade=t=out:st=$(D-2):d=2[bg];\
 [0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[a]" \
 -map 0:v -map "[a]" -c:v copy -c:a aac -shortest film_music.mp4
```

Edge cases:
- Intro path set but file deleted → log warning, skip intro, `intro_duration_seconds=0`.
- Music longer than film → `duration=first` + `-shortest` trims.
- Film has no audio (all voiceover failed) → music still mixes over silence; intro concat still valid.
- Transcript: a scene with empty `narration_text` → still listed by `title`, seek by scene start.

## 10. Validation Criteria

- All Acceptance Criteria AC-001..AC-010 pass.
- With all three asset/env values empty, a rendered job is identical to pre-change output (except the cut view shows the transcript panel).
- One end-to-end render with a real intro + music produced and reviewed: seam clean, narration audible over music, transcript clicks land on the right spoken words (offset correct).

## 11. Related Specifications / Further Reading

- `services/compositor/app/main.py` — assemble + chunk concat + ffmpeg invocation site.
- `services/compositor/app/duration_prober.py` — existing ffprobe duration logic to reuse for film/intro duration.
- `services/compositor/app/llm_composer.py` — `compose_html` (scene slotting / `pal_bg` backdrop) for how scene start/slot durations are derived.
- `frontend/js/studio.js` — `cutShell()` (the cut view) and the filmstrip cumulative-start seek logic to reuse for the transcript.
- `services/orchestrator/app/core/graph.py` — `assembler_node` (passes `intro_duration_seconds` through to job state).
