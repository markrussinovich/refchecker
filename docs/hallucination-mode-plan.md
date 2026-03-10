# Hallucination Mode Plan

## Goal

Build a high-confidence bulk triage mode that scans many papers and reports only references that are likely hallucinated or seriously wrong.

This mode is intended to help reviewers and maintainers find the worst reference problems quickly. It is not meant to prove that every flagged citation is hallucinated.

## Success Criteria

- Accept bulk paper input from the CLI.
- Reuse the existing reference verification pipeline.
- Score or classify suspicious references using strict heuristics.
- Output paper-level summaries plus machine-readable reports.
- Keep false positives low by excluding routine citation noise.

## Scope

### In scope

- `--mode hallucination` CLI flow.
- Bulk input support such as `--paper-list`.
- Structured report output such as JSON and CSV.
- High-confidence suspicion scoring based on existing error objects.
- Paper-level rollups that highlight only flagged papers.

### Out of scope for the first milestone

- Claiming that all flagged citations are definitely hallucinations.
- Full OpenReview venue crawling from the CLI.
- Replacing the existing verifier or extraction pipeline.
- UI work beyond any later report compatibility needs.

## Implementation Phases

### Phase 1: CLI foundation

Status: complete

- [x] Add `--mode hallucination`.
- [x] Add `--paper-list` for bulk CLI input.
- [x] Add report arguments for machine-readable exports.
- [x] Preserve current single-paper behavior.
- [x] Add paper-level triage console summaries for bulk runs.

Target files:

- `src/refchecker/core/refchecker.py`
- `README.md`

### Phase 2: Suspicion policy

Status: in progress

- [x] Add a dedicated scoring module that converts existing verifier results into suspicion levels.
- [x] Start with conservative rules:
  - unverified with rich metadata
  - DOI mismatch
  - arXiv/OpenReview identifier mismatch
  - multiple major mismatches together
- [x] Exclude weak signals such as year-only drift.
- [~] Tune thresholds against real-world false positives.

Target files:

- `src/refchecker/core/hallucination_policy.py`
- `src/refchecker/core/refchecker.py`
- `tests/unit/`

### Phase 3: Report generation

Status: in progress

- [x] Add JSON output for flagged references.
- [x] Add paper-level rollups.
- [x] Add optional CSV export for spreadsheet triage.
- [x] Support `--only-flagged` to suppress verbose clean-paper output.

Target files:

- `src/refchecker/core/refchecker.py`
- `tests/unit/`

### Phase 4: Scale and data sources

Status: not started

- Add across-paper batching improvements.
- Reuse caches more aggressively across a bulk run.
- Consider OpenReview conference ingestion once list-based input is stable.

Target files:

- `src/refchecker/core/refchecker.py`
- `src/refchecker/checkers/openreview_checker.py`
- `src/refchecker/checkers/enhanced_hybrid_checker.py`

## Proposed CLI Shape

```bash
academic-refchecker \
  --mode hallucination \
  --paper-list iclr_papers.txt \
  --report-format json \
  --report-file hallucination_report.json \
  --only-flagged
```

## Reporting Model

Each flagged record should include:

- source paper metadata
- cited reference text and parsed fields
- verifier output
- suspicion level
- normalized reason codes
- corrected target metadata when available

## Current Progress Notes

- Branch created: `hallucination`
- Initial task focus: bulk CLI input and report scaffolding
- Implemented: `--mode`, `--paper-list`, `--report-file`, `--report-format`, `--only-flagged`
- Implemented: initial `hallucination_policy.py` scoring module
- Implemented: initial JSON and JSONL structured report output
- Implemented: focused unit tests for policy and paper-list loading
- Implemented: OpenReview URL source metadata enrichment for bulk PDF inputs
- Implemented: paper-level rollups in structured JSON reports
- Implemented: CSV export for spreadsheet-style triage
- Implemented: package-qualified config imports to remove unresolved-import diagnostics
- Implemented: `pybtex` migration to replace deprecated `bibtexparser`
- Validated: Sonnet-backed 3-paper OpenReview sample with cleaner flagged-paper grouping
- Validated: focused regression suite after `bibtexparser` uninstall (`47 passed`)
- Implemented: bulk hallucination console triage summary for multi-paper CLI runs
- Validated: bulk CLI smoke run with triage summary output
- Implemented: downgraded operational `unverified` and API-failure cases so rate limits/network issues do not become hallucination candidates
- Next code slice: keep tuning thresholds against larger real-world samples and broaden docs
