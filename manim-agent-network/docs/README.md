# docs/

## Active

- **[SECURITY_AUDIT_SPEC.md](SECURITY_AUDIT_SPEC.md)** — the one open workstream.
  16 security findings from the 2026-07-05 audit. Status: SEC-2 (admin-auth
  bypass) **fixed**; SEC-1 (real sandbox for LLM-generated code) and the
  supporting items (env scrub, path jail, SSRF guards) **open** — do before any
  public exposure.

## Archive

[`archive/`](archive/) holds completed work — read for history, not for tasks:

| Doc | What it was |
|---|---|
| `SYSTEM_AUDIT_REMEDIATION_SPEC.md` | Raw 334-finding audit (2026-07-05) — source of both derived specs |
| `PIPELINE_AUDIT_SPEC.md` | Pipeline fragility + content-quality synthesis of that audit |
| `AUDIT_VERIFICATION_AND_FIX_PLAN.md` | Per-finding verification verdicts + the fix plan — **implemented 2026-07-05** |
| `PIPELINE_FIX_REPORT_2026-06-10.md`, `VIDEO_QA_REPORT_f24799da.md` | Earlier debugging write-ups |
| `FINAL_STATUS.md` | Pre-audit system status snapshot (stale) |
| `admin-langsmith-plan.md`, `admin-redesign-spec.md` | Admin console plans (executed/superseded) |
| `nexu-html-video-comparison.md`, `open-design-hyperframes-analysis.md` | Competitive research (conclusions absorbed into the pipeline) |
| `plans/`, `superpowers/` | Executed implementation plans and design specs |

`screenshots/` — image assets for the archived write-ups.
