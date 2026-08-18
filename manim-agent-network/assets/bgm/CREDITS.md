# BGM library — audition & license

8 instrumental royalty-free tracks by **Kevin MacLeod** (incompetech.com).
Licensed **Creative Commons Attribution 4.0 (CC-BY 4.0)**.

| File | Length | Feel |
|---|---|---|
| Carefree.mp3 | 3:25 | Light, plucky acoustic — upbeat explainer |
| Inspired.mp3 | 4:46 | Warm piano — calm, hopeful |
| Dreamer.mp3 | 3:24 | Gentle piano — soft, reflective |
| Healing.mp3 | 2:10 | Ambient pad — very calm |
| Crinoline Dreams.mp3 | 4:06 | Mellow electronic — neutral bed |
| Thinking Music.mp3 | 3:16 | Light pizzicato — curious/neutral |
| Local Forecast - Elevator.mp3 | 0:55 | Easy lounge — short loop |
| Wholesome.mp3 | 6:04 | Calm acoustic — long, unobtrusive |

## To use one as the film's bed
Set in `.env` (in-container path), then rebuild the compositor:
```
BG_MUSIC_PATH=/assets/bgm/Inspired.mp3
```

## Attribution (REQUIRED by CC-BY when you publish)
Put this in the video description / credits:
> Music: Kevin MacLeod (incompetech.com) — Licensed under Creative Commons: By Attribution 4.0
> https://creativecommons.org/licenses/by/4.0/

No attribution? Use the synthesized `../music.mp3` (license-free, made in-house) instead.
