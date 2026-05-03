# Agent Instructions for RefChecker

This file provides guidance for AI coding agents working in this repository.

## Core Project Requirement: Path Parity

RefChecker exposes three primary execution paths for checking references:

1. **Bulk path** — batch processing (e.g. `openreview.sh` / scripted multi-paper runs).
2. **CLI path** — single-paper command-line invocation (e.g. `run_refchecker.py`).
3. **WebUI path** — interactive checks via the FastAPI backend + React frontend (`run_webui.py`, `backend/`, `web-ui/`).

These three paths **must remain identical wherever possible**. Concretely:

- All three paths must call into the **same core checking logic** (the shared `refchecker` core in [src/refchecker](src/refchecker)). Do not duplicate or fork verification, parsing, LLM-prompting, or scoring logic into a path-specific implementation.
- Configuration, defaults, thresholds, prompts, model selection, retry/error-handling behavior, and reference-extraction pipelines must be sourced from shared modules — not redefined per path.
- Any new feature, bug fix, or behavior change made to one path must be applied to (or made available to) the other two paths in the same change, unless there is a documented, path-specific reason it cannot apply (e.g. a UI-only affordance).
- Path-specific code should be limited to **I/O, presentation, and orchestration** (argument parsing, HTTP/WebSocket transport, progress reporting, file vs. upload handling, rendering). It must not contain checking logic.

## Result Parity

Running the same paper with the same configuration through bulk, CLI, and WebUI **must produce matching results**, with the only permitted differences being:

- **LLM non-determinism** (sampling variance from the underlying model). Where determinism is configurable (e.g. temperature 0, fixed seed), results should match exactly.
- **Presentation/format differences** (JSON vs. rendered HTML vs. terminal output) — the underlying data must be the same.

The following must match across paths (modulo LLM non-determinism):

- Set of extracted references.
- Per-reference verification verdicts (verified / unverified / errors / warnings / hallucination, etc.).
- Aggregate counts (total references processed, error counts, warning counts, unverified counts, hallucination counts).
- Error/warning categorization and messages.

If you observe a discrepancy across paths that is **not** explainable by LLM non-determinism, treat it as a bug and fix the divergence at the shared layer.

## Reference Status Icon Precedence

When rendering a per-reference status icon (WebUI, CLI summaries, bulk reports), the icon is selected by the following precedence — the first matching rule wins:

1. **Hallucination** — if the reference is flagged as hallucinated, show the hallucination icon.
2. **Error** — otherwise, if the reference has any error, show the error icon.
3. **Warning** — otherwise, if the reference has any warning, show the warning icon.
4. **Verified / Unverified** — otherwise, show the verified or unverified icon based on the reference's verification status.

This precedence is implemented in the shared status helper (see [web-ui/src/utils/referenceStatus.js](web-ui/src/utils/referenceStatus.js), `getEffectiveReferenceStatus`) and must be mirrored by any other path that renders per-reference status.

## Guidance for Changes

When modifying this repo:

- Prefer changes in the shared core ([src/refchecker](src/refchecker)) over changes in path-specific wrappers ([backend/refchecker_wrapper.py](backend/refchecker_wrapper.py), [run_refchecker.py](run_refchecker.py), bulk scripts in [_workspace](_workspace)).
- When touching one path, audit the other two for the same code/behavior and update them together.
- When adding a new option or flag, expose it consistently in CLI args, the WebUI form/API, and the bulk runner.
- Add or update tests under [tests/](tests/) that exercise the change through more than one path when feasible.
