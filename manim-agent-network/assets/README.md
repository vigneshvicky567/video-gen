# Final-cut assets

Drop branded media here; the compositor mounts this folder read-only at `/assets`
and stitches them around every generated film at assemble time.

| File | Env var | What it does |
|---|---|---|
| `intro.mp4` | `INTRO_VIDEO_PATH=/assets/intro.mp4` | Prepended before the film |
| `outro.mp4` | `OUTRO_VIDEO_PATH=/assets/outro.mp4` | Appended after the film |
| `music.mp3` | `BG_MUSIC_PATH=/assets/music.mp3` | Low-volume bed under the narration |

Recommended: 1920×1080 H.264 + AAC, 2–6 s for intro/outro; instrumental,
royalty-free music. All optional — an unset/empty path is simply skipped.

Tune the bed with `BG_MUSIC_VOLUME` (default `0.12`) and
`BG_MUSIC_FADEOUT_SECONDS` (default `2.0`) in `.env`.
