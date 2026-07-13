# RefChecker — Feature Guide & Access-Method Matrix

RefChecker ships in **four access methods** that share **one** verification engine
(`backend.refchecker_wrapper.ProgressRefChecker`):

- **Web UI** — the React SPA served by the FastAPI backend (`refchecker-webui`).
- **Desktop (Tauri)** — the same SPA + backend bundled as a native macOS / Windows /
  Linux app (the backend runs as a PyInstaller sidecar).
- **CLI** — `academic-refchecker` (the standalone batch/report CLI) and
  `refchecker-webui check` (the single-paper, web-parity checker).
- **API** — the FastAPI HTTP endpoints the Web UI itself calls.

This guide is the canonical, code-verified description of every capability and
where it is available. The CLI column lists the **exact flag**, matching
`refchecker-webui check --help` (run it for the authoritative list). Interactive
UI surfaces (in-app viewers, graphs, share video, author/journal hovers) are
**web/desktop-only** and are documented as such — the CLI never claims them.

> **Honesty first.** RefChecker does **not fabricate**. Every author, paper, DOI,
> and count shown comes from a real resolved source; a check **abstains** (no badge)
> rather than emit a wrong verdict. AI-generated-text detection is **opt-in and
> advisory only** — never proof of misconduct. All surfaces run **single-user/local
> by default**; accounts, Teams, and presence light up only when you explicitly
> enable multi-user mode (see [MULTIUSER.md](MULTIUSER.md)).

---

## Feature matrix

Legend: ✅ available · — not applicable to that surface · 🌐 needs a hosted/multi-user server.

| Capability | Web | Desktop | CLI | API | Notes |
|---|:---:|:---:|:---:|:---:|---|
| Reference verification (S2 / OpenAlex / CrossRef / DBLP / ACL) | ✅ | ✅ | ✅ | ✅ | Core engine; identical results across surfaces |
| LLM extraction (Anthropic / OpenAI / Google / Azure / vLLM) | ✅ | ✅ | ✅ `--llm-provider` | ✅ | `--no-llm` for regex/structural only |
| Hallucination detection (deep web search) | ✅ | ✅ | ✅ `--check-hallucinations` | ✅ | Needs a web-search-capable provider |
| Inline-citation numbering / ordering check | ✅ | ✅ | ✅ `--check-citation-order` | ✅ | Scheme-aware; **abstains** when unclear |
| Retraction screening (OpenAlex) | ✅ | ✅ | ✅ `--check-retractions` | ✅ | Flags only refs OpenAlex reports retracted |
| Gap-finder / co-citation suggestions | ✅ | ✅ | ✅ `--suggest-missing` | ✅ | OpenAlex-resolved real works only |
| Cross-source enrichment (counts / abstract / claim-TL;DR / funding / author metrics incl. ORCID · h-index) | ✅ | ✅ | ✅ on by default (`--no-enrich`) | ✅ | Mirrors the web/API default |
| Add-to-reference-list (dedup + renumbered list + tracked PDF diff) | ✅ | ✅ | — | — | Interactive editing surface |
| Similar papers + "Cites & Refs" + common-works view | ✅ | ✅ | — | — | Interactive UI surface |
| Seen-library graphs (radial + Obsidian-style 3D) | ✅ | ✅ | — | — | Interactive UI surface |
| Native PDF viewers (find · in-PDF citation links · color coding · pinch-zoom) | ✅ | ✅ | — | — | Interactive UI surface |
| AI-generated-text detection (opt-in, advisory) | ✅ | ✅ | ✅ `--ai-detection {local,api}` + `--ai-detection-consent` | ✅ | Consent required; never proof of misconduct |
| Multi-detector compare (RAID-informed roster, checkbox export) | ✅ | ✅ | ✅ `--detectors key1,key2` · `--list-detectors` | ✅ | Per-detector scores shown honestly; no synthetic ensemble; uninstalled ⇒ abstains |
| Per-reference chat (full-text grounded, TL;DR fallback) + Summarize | ✅ | ✅ | — | — | Separate model selection per feature |
| Share / export (HTML · Markdown · PDF · DOCX · RIS · video) | ✅ | ✅ | — (CLI uses report files) | — | Interactive share surface; CLI emits report files |
| Live token / $ telemetry per LLM flow | ✅ | ✅ | — | ✅ (per-request usage) | UI meter is web/desktop; usage returned by API |
| Structured machine-readable output | ✅ | ✅ | ✅ `--json` | ✅ (JSON) | CLI: progress→stderr, JSON→stdout |
| Bulk / batch checking | ✅ | ✅ | ✅ (`academic-refchecker --paper-list` / `--openreview`) | ✅ | See the README Bulk Checking section |
| Local databases (offline / faster verification) | ✅ | ✅ | ✅ `--database-dir` / `--s2-db` / … | ✅ | Same resolver across surfaces |
| Accounts · Teams · realtime shared-batch presence | 🌐 | 🌐 | — | 🌐 | Opt-in multi-user; see [MULTIUSER.md](MULTIUSER.md) |
| Support menu (email + open a GitHub issue) | ✅ | ✅ | — | — | In-app header menu |

---

## Per-feature guides

### Reference verification

The shared engine resolves every reference against **Semantic Scholar, OpenAlex,
CrossRef, DBLP, and ACL Anthology**, compares titles / authors / years / venues /
DOIs / arXiv IDs / URLs, and tolerates formatting variation. When verification is
inconclusive it abstains (`unverified`) rather than guess.

```bash
# Web-parity single-paper check (reuses ProgressRefChecker)
refchecker-webui check --paper 2406.01234
refchecker-webui check --paper ./paper.pdf --json

# Standalone batch/report CLI
academic-refchecker --paper 1706.03762
academic-refchecker --paper ./paper.pdf --llm-provider anthropic
```

### Hallucination detection

A deterministic pre-filter selects suspicious references, the configured
hallucination LLM runs a mandatory deep web search, and RefChecker re-verifies
against any LLM-found metadata before deciding error vs. likely fabrication.
Providers: **OpenAI, Anthropic, Google, Azure**.

```bash
refchecker-webui check --paper 2406.01234 --check-hallucinations \
    --llm-provider anthropic --llm-model claude-3-5-sonnet-latest

# Separate hallucination provider/model
refchecker-webui check --paper ./paper.pdf --check-hallucinations \
    --hallucination-provider anthropic --hallucination-model claude-3-5-sonnet-latest
```

### Inline-citation numbering / ordering check

Audits the body's inline-citation scheme (numeric vs. author-year) for gaps,
out-of-order, duplicates, undefined, and uncited references. It is scheme-aware
and **abstains** when the scheme is ambiguous.

```bash
refchecker-webui check --paper ./paper.pdf --check-citation-order --json
# JSON key: citation_order { scheme, abstained, badge, issues[] }
```

### Retraction screening

Flags cited references that **OpenAlex** reports as retracted — real signal only,
no heuristics.

```bash
refchecker-webui check --paper ./refs.bib --check-retractions
# JSON key: retractions { checked, with_doi, retracted, source, results[] }
```

### Gap-finder / co-citation suggestions

Suggests frequently co-cited works that are **missing** from the bibliography,
resolved against real OpenAlex works (never fabricated).

```bash
refchecker-webui check --paper ./refs.bib --suggest-missing
# JSON key: suggestions { checked, analyzed, source, suggestions[], note }
```

### Cross-source enrichment & author metrics

Backfills per-reference counts, abstract, claim/TL;DR, open-access full-text,
preprint, funding, and **author metrics (citation counts, h-index, ORCID)** by
cross-filling from all sources. **On by default**, mirroring the web/API.

```bash
refchecker-webui check --paper 2406.01234            # enrichment ON
refchecker-webui check --paper 2406.01234 --no-enrich  # opt out
```

In the Web UI / Desktop, author and journal **hover cards** add affiliation,
paper/citation counts, h-index, ORCID, homepage, recent papers, and journal
author-guideline links (these hover surfaces are web/desktop-only).

### Add-to-reference-list (dedup · renumber · tracked PDF diff)

In the References / Corrections tabs you can **add** a suggested or similar work
to the bibliography. RefChecker **de-duplicates** against existing entries,
produces a **renumbered reference list**, and shows a **before→after renumber
diff** (e.g. `[5] → [6]`) over the document so you can see exactly what shifts.
This is an interactive editing surface — web/desktop only.

### Similar papers, "Cites & Refs" & common-works view

Three clearly-scoped discovery modes over **real OpenAlex** data:

- **References** — papers whose bibliographies overlap this paper's references.
- **Citations** — papers co-cited with this one.
- **Both** — combined.

Each candidate is rescored by per-candidate reference-overlap and can be expanded
to reveal **which shared works** drive the match (the common-works detail). Similar
candidates from Semantic Scholar / OpenAlex / web-search / your LLM are deduped
with source badges and **re-verified** before display. Web/desktop only.

### Seen-library graphs (radial + 3D)

Every verified reference is persisted to a global identity cache (DOI / arXiv /
normalized-title key). The library renders as a **radial graph** (clickable DOIs,
full article info on hover) and an **Obsidian-style 3D force-directed graph**
(node size = times seen, edges = shared authors / venue). Web/desktop only.

### Native PDF viewers (find · in-PDF links · color coding · pinch-zoom)

The in-app viewer renders the **real PDF** (pdf.js) with **status color-coded**
highlights, **click-to-jump** in-PDF citation links (reference ↔ document), an
in-document **find** bar (⌘F / Ctrl+F with match navigation), and **trackpad
pinch-zoom** (defaults to fit-width). Non-PDF sources (pasted text, `.tex`,
`.bib`, `.txt`) are converted to a self-contained PDF so they render the same
way, with a graceful text fallback. Web/desktop only.

### AI-generated-text detection (opt-in, advisory)

Optionally analyzes the article **body text** for AI-generated likelihood,
returning a low/medium/high band plus advisory flagged passages. **Opt-in and
advisory only** — it abstains on short or highly technical text, and is never a
basis for an accusation.

Engines: a **local calibrated model** (`desklib/ai-text-detector`, DeBERTa-v3,
MIT — runs offline after a one-time runtime + model download), an **LLM judge**
(reuses your configured provider; hard-capped at "medium"), or an **external API**
(Pangram / GPTZero — key + explicit consent, your text is sent to a third party).

```bash
# Local heuristic backend (still requires explicit consent)
refchecker-webui check --paper ./paper.pdf \
    --ai-detection local --ai-detection-consent

# External API backend
refchecker-webui check --paper ./paper.pdf --ai-detection api \
    --ai-detection-consent --ai-detection-service pangram \
    --ai-detection-key $PANGRAM_KEY
# JSON key: ai_detection { band, score, backend, ... }
```

`--ai-detection` **requires** `--ai-detection-consent`; without it the CLI exits
with an error. The CLI never runs detection unless you opt in.

#### Multi-detector compare (RAID-leaderboard-informed roster)

You can install **one or more** open-source detectors and run them
**side-by-side** — each detector's verdict is shown on its own. There is **no
synthetic "ensemble truth"**: disagreement between detectors is signal, not noise
to hide. Detectors are **installed on demand** (never bundled), and an
**uninstalled detector abstains — it never reports a number**. Heavy Tier-2
metric/zero-shot detectors are listed for honesty but are **opt-in and not
runnable in this build** (real size / RAM warnings shown).

| Key | Model | Arch | Tier | Size | License | Note |
|---|---|---|:---:|---|---|---|
| `desklib` *(default)* | `desklib/ai-text-detector-v1.01` | DeBERTa-v3-large | 1 | ~870 MB | MIT | RAID leaderboard leader among open models |
| `superannotate` | `SuperAnnotate/ai-detector` | RoBERTa-Large | 1 | ~1.4 GB | research/eval | #1 open-source on RAID (late 2024) |
| `e5-small-lora` | `MayZhou/e5-small-lora-ai-generated-detector` | e5-small + LoRA | 1 | ~130 MB | MIT | tiny/fast/CPU-friendly (~89% acc) |
| `mage` | `yaful/MAGE` | Longformer | 1 | ~570 MB | Apache-2.0 | "Detection in the wild" (ACL 2024) |
| `binoculars` | paired causal LMs | metric zero-shot | 2 (heavy) | ~14 GB | see models | best at low FPR; **opt-in, not runnable here** |
| `fast-detectgpt` | GPT-Neo-2.7B scorer | metric zero-shot | 2 (heavy) | ~11 GB | see models | 340× faster DetectGPT; **opt-in, not runnable here** |
| `radar` | `TrustSafeAI/RADAR-Vicuna-7B` | adversarial classifier | 2 (heavy) | ~13 GB | see card | robust to paraphrase; **opt-in, not runnable here** |

Roster informed by the [RAID benchmark (ACL 2024)](https://github.com/liamdugan/raid)
([leaderboard](https://raid-bench.xyz/), [paper](https://arxiv.org/abs/2405.07940)).
In the Web UI / Desktop you install/remove each detector from **Settings → AI
Detection** (real size + license shown), run any subset, see per-detector scores
and per-sentence agreement, and **checkbox-export** only the detectors you select.

```bash
# List the roster (installed vs. available, sizes/tiers/licenses) — no paper needed
refchecker-webui check --list-detectors
refchecker-webui check --list-detectors --json   # machine-readable

# Run a subset side-by-side (only INSTALLED detectors run; the rest abstain)
refchecker-webui check --paper ./paper.pdf \
    --ai-detection local --ai-detection-consent \
    --detectors desklib,e5-small-lora
# Naming an unknown or not-installed detector exits with a clear
# "installed vs. available" error — never a fabricated number.
```

### Per-reference chat (full-text grounded) & Summarize

The Article Assistant offers **Chat-with-PDF** and **Summarize**, grounded in the
article's full text where available, with an honest **TL;DR/abstract fallback**
when full text is missing and an honest abstain when no text exists at all.
**Chat and Summarize can use separate model selections** (configure each in
Settings); an empty-state prompts you to configure a model if none is set. A
per-reference "Chat about this reference" button grounds the conversation on that
single reference. Web/desktop only.

### Share & export

One click produces a **self-contained HTML report** (references + verdicts +
AI-detection visuals inline), with options to **publish a link** (GitHub Gist),
export **Markdown / PDF / DOCX**, export an animated **video** walkthrough (WebM),
and export **RIS** (with the verifier's *corrected* metadata) for Zotero /
EndNote / Mendeley / Rayyan / Papers / RefWorks. The interactive share surface is
web/desktop only; from the CLI use `academic-refchecker --report-file` /
`--report-format {json,jsonl,csv,text}` for machine-readable reports.

### Live token / $ telemetry

A per-check token + estimated-USD meter tracks every LLM flow (extraction,
hallucination, chat/summarize, AI-detection LLM-judge), with per-provider and
per-kind breakdowns and a cascade-savings hint; it persists across restarts. The
meter UI is web/desktop; the API returns per-request usage so callers can meter
themselves.

### Structured output (`--json`)

`refchecker-webui check --json` prints **one** JSON document to **stdout** while
all progress goes to **stderr** (so stdout stays machine-readable). The document
always carries `paper_title`, `paper_source`, `source_type`, `extraction_method`,
`summary`, and `references`, plus — only when the corresponding flag is set —
`citation_order`, `retractions`, `suggestions`, and `ai_detection`.

### Accounts · Teams · presence

Opt-in multi-user mode adds OAuth sign-in (Google / GitHub / Microsoft),
team-scoped shared checks, collaboration on the same batch, and realtime
shared-batch **presence**. Single-user/local is the default. Full setup —
including the in-app **enable-accounts-&-Teams form with hot-reload** — is in
[MULTIUSER.md](MULTIUSER.md).

---

## See also

- [README — feature matrix & CLI](../README.md#feature-matrix-web--desktop--cli--api)
- [Multi-user & Teams setup](MULTIUSER.md)
- [Web UI guide](web-ui.md)
- [Testing guide](testing.md)
