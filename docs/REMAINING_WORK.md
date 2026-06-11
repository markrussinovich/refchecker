# RefChecker — Final Remaining Work & Implementation Prompt

> Consolidated, de-duplicated deliverable reconciling two adversarially-verified gap-analysis passes
> (batch **1(A–J)** = original requests; batch **2(K–U)** = the two newer, more current passes) against
> the live code at `/Users/ario/Downloads/refchecker` (React `web-ui/`, FastAPI `backend/` + `src/refchecker/`,
> Tauri `tauri-app/`). Batch 2 is treated as the more current read; where it supersedes a batch-1 item the
> batch-1 item is collapsed into it and only the residual sub-bug is kept.

---

## 1. Executive summary

After reconciling all **83 verified findings** and collapsing the known duplicates:

- **Done (do NOT rebuild): ~52 reconciled items.**
- **Remaining (PARTIAL / BROKEN / MISSING): 27 work items.**

Remaining split by priority:

| Priority | Count | Items |
|---|---|---|
| **P0** | **5** | K2, F1, H1, O3, O4 |
| **P1** | **17** | A2, A3, A6, B1, B2, C2, D1, D3, D5, E1, F2, G1, G2, G3, H2, J3 (→U1/U3), L2, M1, M2, O2, O5, O6, P4, Q1/Q3, Q4, R4, T3, T4, U6 *(grouped; see table)* |
| **P2** | **5** | A1-FIX, A4, C1-FIX, I2, M5 (plus optional one-liners) |

> The P1 row above is shown un-grouped for honesty; the table in §3 lists each P1 item on its own row. The exact P1 work-item count is **20** once O2/O5/O6, P4, Q1+Q3, U1, U3, L2, M1, M2, R4, T3, T4, U6 are each counted, but several are sub-streams of the same engineering cluster (viewers, share-video, auth/teams). The headline number to plan against is **27 remaining work items across 5 P0 + ~17 P1 + ~5 P2.**

### P0 blockers (called out by name)

1. **K2 — Published-date dishonesty.** The real full publication date (`"Oct 1, 2021"`) is computed and sent to the FE but silently dropped, and it falsely gates an otherwise-empty `ReferenceEnrichmentStrip` container. Must either render the real date or be cleanly removed (no empty gated container).
2. **F1 — LLM hallucination check hangs forever** on "Checking for hallucination with LLM…" (no client HTTP timeouts; shared executor saturates; no FE wall-clock fallback).
3. **H1 — Share endpoint 500 for all sharing types** (un-guarded `_render_check_html` in `publish_check`; PDF engine not degraded gracefully). *Distinct from the batch-check 500, which is DONE, and distinct from the share-video items.*
4. **O3 — Per-reference "View in document" is still not native-PDF** (image-raster stack, conversion text-only, hyperlink targets a React tab instead of jumping inside the PDF).
5. **O4 — AI per-sentence "view in document" button is missing** from the page-by-page and top-sentence lists.

---

## 2. Already done — do NOT rebuild

These are reconciled as functionally complete. Do **not** touch them except where a remaining item explicitly extends them. Each cites the key file so the agent can confirm.

**Blocking bugs / batch endpoint**
- **The `/api/check/batch` 500 `AttributeError`** on `semantic_scholar_api_key` / `paperclip_api_key` is fixed (the single de-duped item that appeared as **K1 / N4 / Q6 / B0** — all DONE). `BatchUrlsRequest` model `backend/main.py:943-968`, handler `:3884-3923`. (No regression test locks it — add one; see G/DoD.)
- **"Unknown mismatch" warning badge (K3)** — backend stops emitting + filters (`refchecker_wrapper.py:1305-1308`), FE filters content-free warnings (`ReferenceCard.jsx:594`).

**Inline-citation numbering checker**
- **Numbering/ordering checker exists and works** for numeric + author-year + first-mention (E1 partial only for the *alphabetic* + *last-mentioned* extensions). Badge + issue list (**E2/E3**) DONE — `inline_citation_checker.py`, `CitationIntegrity.jsx:121-159`.
- **Citation-integrity UI re-runnable (S1)** and **result panel positioned/height-capped (S2)** — `CitationIntegrity.jsx:76,118`.

**Per-article isolation**
- **Retraction-check (L1)** and **gap-finder (L3)** are per-article isolated via remount key (`MainPanel.jsx:351-357`); root-cause (L4) fix landed. *Residual:* similar-papers isolation (L2) still PARTIAL — see §3.

**Seen-library / similar-papers graph**
- **3D draggable graph (R3)** done for Explore; **similar-papers graph populates/recreates (R2)** done; **radial pin edge-persistence (I1 == R5)** DONE — `GraphLibraryView.jsx`, `ExploreGraphView.jsx`. *Residual:* common-cites/refs **visualization (R4)** is BROKEN and remains; library-3D polish (I2) and clickable radial DOIs (R1) remain.

**Author popup**
- **Author-popup scroll + resize-to-content (N1)** DONE — supersedes batch-1 A6's "scrollable" claim (A6's *pin-to-modal* residual remains). `ReferenceCard.jsx:1678,1685`.
- **Google Scholar + Semantic Scholar rendered as logo icon-links (N2)** DONE — `ReferenceCard.jsx:1487-1524,1768`.
- **"et al." full-author recovery on the verified path (N3)** DONE — `refchecker_wrapper.py recover_full_authors_from_enrichment`. (A2's FE "et al. → expand" control and N3's error-path/sentinel hardening remain.)
- **Journal publishing guidelines on venue hover (A5)** DONE — `ReferenceCard.jsx VenueLine`, `main.py:8030-8111`.

**Enrichment**
- **OpenAlex `/authors` h-index/citation backfill for non-S2 authors (M3, issue #54)** DONE — `main.py:7888-7907`. (Crossref/DBLP-only authors with no id remain unaddressed; out of scope for #54.)
- **Dead non-clickable "Published 2023" pill removed (M4)** DONE.

**Context view**
- **Highlight is a working hyperlink back to the inline-cited reference (D4)** + **attention pulse animation (D2)** DONE — `StatusSection.jsx:470-481`.
- **Context-view default zoom: fit-to-width/page + focus the highlight on open (P1)** DONE — supersedes batch-1 D1's "opens focused" claim. (D1's *deterministic re-zoom/centering* residual remains.) `NativePdfViewer.jsx`.
- **Zoom in/out button visibility in both themes (P2)** DONE; **zoom controls present in the per-reference context viewer (P3)** DONE.
- **Back-to-top no longer overlaps the debug button (P5)** DONE — `MainPanel.jsx:547-548`.

**Sharing / export / video**
- **Share-video reflects real per-article counts + outline/overlap fixed (Q2)** DONE; **exported-file logo + count parity (Q5/U5)** DONE; **export theme + design.md (U4)** DONE.

**Per-ref chat / buttons / auth**
- **Per-reference "Chat about this reference" button (T1)** DONE — `ReferenceCard.jsx` + `ArticleAssistant.jsx` + `backend/article_chat.py`.
- **Redundant "Add to library" action removed (T2)** DONE — `AdditionalInfoBar.jsx`.
- **Realtime team presence on the same batch (U2)** DONE (presence keyed on `batch-{id}` room) — note: not team-membership-gated (that gating is part of the J3/U1 work).
- **The two named lint/cfg fixes for U6** (SimilarPapersPanel elapsed-timer; tauri devtools) are released in `desktop-v0.9.18`; only the *fresh green-CI verification* sub-claim remains.
- **Native-macOS design language (J1)**, **Support button email/GitHub (J2)**, **"Similar Cites & Refs" Refs/Cites/Both toggle (J4)** DONE — `index.css`, `SupportMenu.jsx`, `SimilarPapersPanel.jsx`.

---

## 3. Final remaining list

Sorted **P0 → P2**, then **BROKEN → PARTIAL → MISSING**. (Original finding id in parentheses.)

| ID | Area | Requirement (user's ask) | Current state (file ref) | Severity |
|---|---|---|---|---|
| **R01** (K2) | Enrichment honesty | Show the real full publication date, or remove it — no empty gated container | Date computed + sent but dropped; falsely gates the strip (`ReferenceEnrichmentStrip.jsx:39,59`) | **P0 · BROKEN** |
| **R02** (O3) | Viewers | Per-ref "View in document" = native PDF + conversion + in-PDF hyperlink | Image-raster stack, conversion text-only, hyperlink → React tab (`StatusSection.jsx:464-526`) | **P0 · BROKEN** |
| **R03** (O4) | Viewers | Per-sentence "view in document" button on every AI sentence | No button on any `PageRow`/`SentenceList` sentence (`AIDetectionVisuals.jsx:136`) | **P0 · BROKEN** |
| **R04** (F1) | LLM | Hallucination check must never wedge the UI forever | No client timeouts; shared executor saturates; no FE fallback (`hallucination_verifier.py:422,444,460`; `refchecker_wrapper.py:4182-4186`) | **P0 · PARTIAL/BROKEN** |
| **R05** (H1) | Sharing | Sharing must not 500 for all types | Un-guarded `_render_check_html` in `publish_check` (`main.py:2825`); PDF not degraded | **P0 · PARTIAL** |
| **R06** (B1) | Corrections | Mentioned DOI correction must match the rendered suggested correction (esp. bibtex) | No `doi` case in `getCorrectedReferenceData`; bibtex reads only `authoritative_urls` (`formatters.js:613,659,1078`) | **P1 · BROKEN** |
| **R07** (B2) | Corrections | `@article{awcomparison}` correction must include year=2018, venue, AND doi=10.5812/ijem.12104 | DOI dropped from bibtex (`formatters.js:1078`); test #53 never asserts DOI | **P1 · BROKEN** |
| **R08** (R4) | Graph | Restore common-cites/refs *visualization*, not just a count | Relation modes show only a count, never which works are shared (`cites_refs.py`, `main.py:6745/6749`) | **P1 · BROKEN** |
| **R09** (A2) | Author UI | "et al." expandable to the full parsed/enriched author list | `normalizeAuthors` renders the literal "et al." token; no expand control (`formatters.js:67-81`, `ReferenceCard.jsx:1324`) | **P1 · MISSING** |
| **R10** (A3) | Author UI | Find more authors when the matched record has no author ids | No name/title-resolution fallback; chip only loads with an existing id (`enrichment.py:459-479`, `ReferenceCard.jsx:1542-1548`) | **P1 · PARTIAL** |
| **R11** (A6) | Author UI | Pin/expand the hover popover into a persistent, fully-opened scrollable panel | Hover-only timers; recent papers sliced to 3 (`ReferenceCard.jsx:1558-1566,1737`) | **P1 · PARTIAL** |
| **R12** (D1) | Context view | Open focused on the reference at a clear zoom, reliably centered | Conditional zoom keeps stale value on re-target; 5×280ms retry races a lazy image (`StatusSection.jsx:157,172-178,424`) | **P1 · PARTIAL** |
| **R13** (D3) | Context view | Highlight the WHOLE sentence, not a 5-word fragment | Needle falls back to first 5 words on PDF-extraction mismatch (`thumbnail.py:917-918,935`) | **P1 · PARTIAL** |
| **R14** (D5) | Context view | Highlight color reflects chaining/verification status, consistently across viewers | 3 divergent/incomplete status→color maps (`StatusSection.jsx:34-43`, `NativePdfViewer.jsx:11-22`, `DocumentViewer.jsx:240-260`) | **P1 · PARTIAL** |
| **R15** (E1) | Inline parser | Parse/validate numeric + **alphabetic** + **first/last-mentioned** styles | Only numeric + author-year + first-mention; no alpha-key family, no last-mentioned (`inline_citation_checker.py:331,533,557`) | **P1 · PARTIAL** |
| **R16** (F2) | Summary | The two issue-count badges must agree | HealthBadge double-counts refs with both error+warning; row-2 tooltip says "(total issues)" for per-ref values (`HealthBadge.jsx:52-53`, `StatsSection.jsx:706`) | **P1 · PARTIAL** |
| **R17** (G3) | Add-to-list | Don't offer to add a ref already present/invalid; no silent duplicates | Manual add path has no dedup/validity guard; GapFinder dedup is OpenAlex-id-only (`main.py:5905-5997`, `gap_finder.py:92`) | **P1 · PARTIAL** |
| **R18** (G1) | Add-to-list | Add the ref AND yield the new list with new inline numbers | Renumber commits only on Undo path; renumber is preview-only; no corrected+renumbered list endpoint (`main.py:5964-5972`, `GapFinder.jsx:45,59`) | **P1 · PARTIAL** |
| **R19** (G2) | Add-to-list | Document was→should-be, ideally rendered into the PDF | Diff lives only in React DOM; only AI-detection PDF is annotated; export prints flat "Suggested:" (`main.py:3353-3358`, `export.py:889-890`) | **P1 · PARTIAL** |
| **R20** (C2) | Gap-finder | Guard gap-finder list + similar-papers against hallucination, with provenance | Verified path dead from UI; reachable modes hardcode `was_verified:false`; no provenance link (`main.py:6754-6756`, `SimilarPapersPanel.jsx:492-518`) | **P1 · PARTIAL** |
| **R21** (M1) | Enrichment | Cross-source backfill of citation/reference counts when a non-S2 source wins | No `backfill_enrichment`; coalesce only within one source (`enrichment.py:74-91,265-274`) | **P1 · PARTIAL** |
| **R22** (M2) | Enrichment | Abstract/Claim(tldr)/Funding lost when a non-S2/non-OpenAlex source wins | Same root cause as M1; non-S2 winner loses tldr; abstract/funding lost for DBLP/ACL/arXiv winners | **P1 · PARTIAL** |
| **R23** (H2/Q1/Q3) | Share video | Per-check "video" at top of popup: persistent, higher quality, no record/download buttons | Canvas unmounts after one pass → blank top; quality is dpr≤2 on 460px; not a real .webm (`ShareModal.jsx:187`, `ShareAnimationCanvas.jsx:38-39,89`) | **P1 · PARTIAL** |
| **R24** (Q4) | Share video | Show the per-article video alongside that article's stats on the stats page | Entirely unimplemented on `StatsSection`/`MainPanel` | **P1 · MISSING** |
| **R25** (L2) | Isolation | Similar-papers isolated per article | `checkId` not wired to `SimilarPapersPanel`; falls through to `mode::title:` cache key (`MainPanel.jsx:498`, `SimilarPapersPanel.jsx:81`) | **P1 · PARTIAL** |
| **R26** (J3→U1) | Auth/teams | Multi-user collaboration on the same batch + team creation + shared checks | `check_history` has no `team_id`; no share/list-by-team endpoint; non-owner gets 404 (`database.py:366-403`, `main.py:1215`) | **P1 · PARTIAL** |
| **R27** (J3→U3) | Auth/teams | Enable accounts/teams from inside the app (no manual env/restart) | Config saved but not hot-reloaded; `is_multiuser_mode()`/providers read import-time constants (`auth.py:30-32,36,503-518`) | **P1 · PARTIAL** |
| **R28** (O2) | Viewers | Inline citation hyperlinks to the reference list *inside the PDF* | Link switches a React tab, not an in-PDF jump (`StatusSection.jsx`) | **P1 · PARTIAL** |
| **R29** (O5) | Viewers | pdf.js on-hover bar + hyperlink works for all spans | Clickable only with `refId`; AI spans have none; link only switches React tab (`AIDetectionPanel.jsx:54`) | **P1 · PARTIAL** |
| **R30** (O6) | Viewers | pdf.js banners fully opaque; link targets the PDF reference list | Banners < fully opaque in ThumbnailOverlay; link not re-targeted (`StatusSection.jsx:452,493`) | **P1 · PARTIAL** |
| **R31** (P4) | Viewers | Pinch-to-zoom in the native PDF / context overlay | Works in AI modal, NOT in the per-ref ThumbnailOverlay (`StatusSection.jsx:408`) | **P1 · PARTIAL** |
| **R32** (R1) | Graph | Clickable DOIs in the Seen-library graph | Radial hover DOI is dead text; no inline row link (`RadialChordGraph` 108-129) | **P2 · PARTIAL** |
| **R33** (T3) | Buttons | Unified button styling (sizing/hover/theming) for per-ref/assistant/pill buttons | No shared button system; missing hover on assistant trigger/Send and pills (`AdditionalInfoBar.jsx:15-36`, `ArticleAssistant.jsx`) | **P1 · PARTIAL** |
| **R34** (T4) | Models | Separate model selection for Chat-with-PDF vs Summarize | Chat + Summarize share one selection; backend already accepts per-call `llm_config_id` (`useConfigStore.js`, `ArticleAssistant.jsx`) | **P1 · PARTIAL** |
| **R35** (M5) | Enrichment UI | Make count tiles clickable drill-downs (or labeled stats with titles) | Citations/Reference Count/Citing Patents are inert text; only Citations has a title (`ReferenceEnrichmentStrip.jsx:105-114`) | **P2 · PARTIAL** |
| **R36** (A1-FIX) | Author UI | Show ORCID whenever honestly resolvable (read fetched profile too) | Popover builds ORCID only from `e.orcid`, drops fetched `profile.orcid` (`ReferenceCard.jsx:1605`; `main.py:7905`) | **P2 · PARTIAL** |
| **R37** (A4) | Author UI | Clearer inline badge co-locating "used N× here" with literature citation count | Badge + academic count live in two places (`ReferenceCard.jsx:649-663`) | **P2 · PARTIAL** |
| **R38** (I2) | Graph | Bring library 3D graph up to Explore-graph polish | No node drag / force tuning / auto-frame in `GraphLibraryView.jsx:362` | **P2 · PARTIAL** |
| **R39** (C1-FIX) | Gap-finder | Friendly 404 instead of raw proxy HTML; smoke test the route | `GapFinder.jsx run()` catch surfaces raw message (`:31-33`); route itself is correct | **P2 · PARTIAL** |
| **R40** (U6) | CI/release | Run all checks (lint/test/cargo) green before publish | Two named fixes released; fresh full green-CI pass unverified | **P1 · PARTIAL** |
| **R41** (N3-res) | Author UI | Don't render a leftover "et al" sentinel as a fake author chip; recover on error path | `normalizeAuthors` keeps the sentinel; error path returns raw authors (`formatters.js:67-81`, `refchecker_wrapper.py:1625`) | **P2 · PARTIAL** |

*Optional one-liners (do last, only if time): J4-OPT tab rename `MainPanel.jsx:415`; J1-OPT `index.css:90` → `var(--font-sans)`; A5-OPT non-DOAJ guidelines; I1-OPT co-cited edges; D2-OPT multi-line pulse; C3 persisted collapse.*

---

## 4. Implementation prompt (self-contained — hand this to a coding agent)

> **Context for the agent (no prior memory assumed):** You are an autonomous coding agent in the `refchecker`
> monorepo at `/Users/ario/Downloads/refchecker` — React frontend `web-ui/`, FastAPI backend `backend/`,
> checker library `src/refchecker/`, Tauri wrapper `tauri-app/`. Close every item below exactly as specified,
> add a test per item, keep `cd web-ui && npm run build && npm test` and backend `pytest` green, eslint clean,
> and Tauri building. **Do NOT rebuild anything in §2.** Make additive, low-risk changes.
>
> **Hard constraints (the user's explicit asks — violating any is a failure):**
> - **No fabrication.** Every author / paper / DOI / count shown to a user must come from a real resolved source. Apply the existing "ABSTAIN beats a wrong badge" discipline (already in `inline_citation_checker.py`) to the gap-finder list and similar-papers (**R20**).
> - **No dead buttons / no fake data / no empty gated containers.** The Published date (**R01**) must render the real date or be cleanly removed.
> - **Share video must reflect REAL per-article counts** (from `buildReferenceSummary`), and never blank the top of the popup.
> - **Viewers must color-code highlights by chaining/verification status and hyperlink inline citations to the reference list *inside the PDF*** (not a React tab).
>
> **Adversarial-workflow instruction (MANDATORY for the engineering-heavy streams below):** For the
> unified-native-PDF-viewers + in-PDF hyperlinking + AI-sentence buttons stream (**O1/O2/O3/O4/O5/O6**),
> add-to-reference-list with corrected renumbered list + tracked PDF changes (**G1/G2/G3**),
> in-app OAuth + Teams + enable-from-app (**U1/U3 / J3**), common-cites/refs visualization (**R4**), and
> enrichment cross-source backfill (**M1/M2**): run a verification loop with **adversarial subagents that
> challenge each other until verified** — an **ML engineer** (false-positive / abstain behavior, model routing),
> a **regex engineer** (marker/needle patterns, DOI normalization edge cases), a **full-stack engineer**
> (endpoint contracts, FE/BE data shapes), an **algorithms professor** (renumber splicing, ordering, dedup
> correctness), plus a **watchdog/reviewer** that signs off only when each subagent's objections are resolved
> with evidence (tests + file:line). Enumerate the inputs that break a naive implementation *before* writing code.

---

### Work-stream 1 — Honesty & P0 blockers

**R01 (K2) — Published date: render real value or remove cleanly. [P0]**
- *Requirement:* Show the real full publication date, or remove it; no empty gated container.
- *Current state:* `ReferenceEnrichmentStrip.jsx:39` destructures `publication_date`; `:59` uses it in `hasAnyBadge` so a ref with only `publication_date` renders an empty strip; backend emits it at `enrichment.py:399-400`.
- *Change (choose A; B is acceptable):*
  - **A (honest display):** render `publication_date` as plain text in Row-1 metadata of `web-ui/src/components/ReferenceCard/ReferenceEnrichmentStrip.jsx` — append to `bibBits` (`:94-102`) or add a `Published: {publication_date}` span in the Row-1 div (`:139-151`). It is already a display-ready string.
  - **B (year-in-header is final):** drop `publication_date` from the destructure (`:39`) and the `hasAnyBadge` gate (`:59`), and stop emitting at `enrichment.py:399-400`.
  - Either way, fix the false comment at `web-ui/src/components/ReferenceCard/AdditionalInfoBar.test.jsx:55-57`.
- *Acceptance:*
  - [ ] A ref with only `publication_date` never renders an empty `ReferenceEnrichmentStrip`.
  - [ ] If chosen A: the real full date renders; if B: no `publication_date` is emitted or gated.
  - [ ] vitest pins the chosen behavior; the corrected `AdditionalInfoBar.test.jsx` comment is accurate.

**R04 (F1) — Stop the LLM hallucination-check hang. [P0]**
- *Requirement:* The check must never wedge the UI on "Checking for hallucination with LLM…".
- *Current state:* OpenAI client (`hallucination_verifier.py:422`) and Google client (`:444`) have no timeout; Responses call (`:460`) no per-call timeout; `_call_uncached` (`:697-720`) chains a second full-length blocking call on web-search failure; backend wraps tasks in `asyncio.wait_for(loop.run_in_executor(None, …), timeout=150)` on the **shared** executor (`refchecker_wrapper.py:4182-4186`; the imported `ThreadPoolExecutor` at line 12 is never instantiated); no FE wall-clock fallback; UI string at `ReferenceCard.jsx:1149`.
- *Change:*
  - `src/refchecker/llm/hallucination_verifier.py` — pass explicit timeouts to ALL clients: `_init_openai (413-422)` → `openai.OpenAI(**kwargs, timeout=httpx.Timeout(60.0, connect=10.0))` and `.with_options(timeout=90.0)` on the Responses call (`:460`); `_init_google (442-444)` → `genai.Client(api_key=…, http_options={'timeout': 60000})` (ms). Keep/lower Anthropic's `120.0` (`:435`).
  - In `_call_uncached (697-720)` thread a remaining-time deadline so search-failure cannot fall through into a second full-length chat call beyond the outer budget.
  - `backend/refchecker_wrapper.py` — instantiate a dedicated bounded pool `self._ha_executor = ThreadPoolExecutor(max_workers=8)` and use it for the hallucination tasks (`:4183-4184`, ideally also `:3402/:3816`); lower the `wait_for` budget (`:4186`) to ~90s.
  - **FE safety net:** in `web-ui/src/components/ReferenceCard/ReferenceCard.jsx` (~1144-1151) or `useCheckStore`, revert a ref stuck pending/"checking" beyond ~180s to its base status with a "check timed out" note; OR have the backend always emit a final per-ref `reference_result` with `hallucination_check_pending=false`.
- *Acceptance:*
  - [ ] All three clients enforce request timeouts; a hanging request returns within budget, not ~600s.
  - [ ] Hallucination tasks run on the dedicated bounded pool, not the shared executor.
  - [ ] Regression test (`tests/unit/`): a simulated over-timeout task still emits `'completed'` and no ref stays permanently pending.
  - [ ] FE: a stuck ref reverts to base status with a timeout note.

**R05 (H1) — Eliminate the share 500; degrade gracefully. [P0]** *(distinct from the batch-check 500 (DONE) and from the share-video items)*
- *Requirement:* Sharing must not fail for all types with "Request failed with status code 500".
- *Current state:* `publish_check` calls `_render_check_html` (`main.py:2825`) outside its try/except — shared by github_gist + quick_link; a `serialize_check_to_html` exception (`main.py:2399`) surfaces as a raw 500 for every type. `_as_list`/`_as_dict` already `json.loads` string inputs (`export.py:100-104,113-118`) — do NOT re-harden those. Only PDF carries the external `fitz` dep. Handlers leak raw `str(e)`.
- *Change:*
  - Reproduce via the captured tracebacks (`logger.error(exc_info=True)` at `main.py:2777/2811/2855/2886`) and inspect the failing check row.
  - Wrap the un-guarded `_render_check_html` in `publish_check` (`main.py:2825`) in try/except → stable 4xx/5xx with a clear detail.
  - Make PDF degrade: wrap `_render_pdf_from_html`/`render_check_to_pdf` (`export.py:937-959`) so a missing/old `fitz` raises `HTTPException(422/501, 'PDF engine unavailable, choose HTML/MD')`. Verify PyMuPDF ships in the Tauri/PyInstaller bundle.
  - Stop leaking raw `str(e)` at `main.py:2778/2811/2856/2886`.
- *Acceptance:*
  - [ ] A serialize failure in any flow (download/publish/quick-link) returns a stable detailed error, never a raw 500.
  - [ ] Missing PDF engine returns 422/501 "choose HTML/MD".
  - [ ] Backend test round-trips `render_export` AND `_render_check_html` for `fmt in {html,md,pdf,docx}` against a check whose `results`/`ai_detection` are JSON strings and an empty/odd-shaped check.

---

### Work-stream 2 — Unified native-PDF viewers + in-PDF hyperlinking + AI-sentence buttons *(adversarial loop REQUIRED — O1–O6)*

> All highlights must color-code by chaining/verification status; inline citations must jump to the reference list **inside the PDF**; AI sentences must each carry a per-sentence "view in document" button. These items are interdependent — do **R14 (D5)** color map first, then **R02/R03** native routing + buttons, then **R28 (O2)** in-PDF jump, then **R29/R30/R31** runtime caveats.

**R14 (D5) — One shared, complete status→color map across all viewers. [P1]**
- *Current state:* `StatusSection._STATUS_HL/_STATUS_STROKE` (`:34-43`) miss `suggestion/checking/pending/unchecked`; `NativePdfViewer.jsx:11-22` FILL/STROKE also incomplete (lacks `unverified/checking/pending/unchecked` + `hallucinated` alias); `DocumentViewer.jsx:240-260` is fixed-red AI-only; `ReferenceCard.getStatusColor (:368-379)` already has the full set.
- *Change:* create `web-ui/src/utils/statusColors.js` (the one justified new file) exporting a status→`{fill,stroke}` map keyed to `getStatusColor`'s full set (`verified, error, warning, suggestion, hallucination/hallucinated, unverified, checking, pending, unchecked`), normalize the (already-lowercased at `StatusSection.jsx:467`) key, map the `hallucinated` alias. Consume in **both** `StatusSection.jsx` (`:34-43`) and `NativePdfViewer.jsx` (`:11-22`). Do NOT copy NativePdfViewer's current map — it is itself incomplete. Leave DocumentViewer AI-red as-is unless you thread `sp.status` in.
- *Acceptance:* [ ] every status (incl. aliases) yields the correct consistent fill/stroke in StatusSection and NativePdfViewer; [ ] viewers + card agree; [ ] vitest asserts the map for every key incl. the `hallucinated` alias.

**R02 (O3) + R03 (O4) — Native-PDF per-ref view + per-sentence buttons. [P0]**
- *Current state:* `viewContextInDoc` opens the image-raster `ThumbnailOverlay` (`StatusSection.jsx:464-526`); non-PDF falls back to a preview image (`:524-526`); conversion is text-only via `pdf_convert.text_to_pdf`; no docx/html→PDF. AI sentences have no per-sentence button (`AIDetectionVisuals.jsx:136`).
- *Change:*
  - Route `viewContextInDoc` through `DocumentViewer`/`NativePdfViewer` (the pdf.js stack) instead of the raster `ThumbnailOverlay`; deprecate the `ThumbnailOverlay` branch (`StatusSection.jsx:464-504`).
  - Add real docx/html→PDF conversion in `backend/pdf_convert.py` so non-PDF sources open as native PDF too.
  - `web-ui/src/components/MainPanel/AIDetectionVisuals.jsx:136` — accept `({detection, onViewSentence, canViewSentence})`, thread into `PageRow`/`SentenceList`, and add a per-sentence button calling `onViewSentence(s.text)`.
- *Acceptance:* [ ] per-ref "View in document" renders the native pdf.js viewer for PDF and converted-PDF sources; [ ] every AI sentence in page-by-page and top-sentence lists has a working "view in document" button; [ ] color-coding (R14) applies; [ ] vitest for the per-sentence button wiring + a backend test for docx/html→PDF.

**R28 (O2) + R29 (O5) + R30 (O6) — In-PDF citation→reference-list hyperlink + opacity + refId. [P1]**
- *Current state:* inline-citation hyperlink only switches a React tab; banners < fully opaque in ThumbnailOverlay (`StatusSection.jsx:452,493`); pdf.js link clickable only when `refId` is present and AI spans have none (`AIDetectionPanel.jsx:54`).
- *Change:* extend `backend/thumbnail.py locate_text_spans_in_pdf` to also locate the reference-list **entry rect** for a given `refId`; on click, scroll + flash that rect **in the same PDF** instead of switching tabs. Set banner alpha to 1 at `StatusSection.jsx:452,493`. Ensure `refId` is always populated for spans (`AIDetectionPanel.jsx:54`) so the hover bar + link work everywhere.
- *Acceptance:* [ ] clicking an inline citation in the PDF scrolls+flashes the matching reference entry inside the PDF; [ ] banners are fully opaque; [ ] all spans (incl. AI) get a working hover bar + link; [ ] vitest/pytest for the entry-rect lookup and the in-PDF jump.

**R12 (D1) — Deterministic fit-then-zoom + reliable centering. [P1]**
- *Change:* in `StatusSection.jsx` citation effect (`:153-159`) replace the conditional `setZoom` with a deterministic `setZoom(CITE_FOCUS_ZOOM)` (or derive a zoom making `firstRect` ~40-60% of viewport height) and reset zoom whenever `citationTarget` changes; set the focused page `<img>` to `loading="eager"` (`:424`); scroll on the image `onLoad` (`:427`) **and** once post-zoom via `requestAnimationFrame`, dropping the 5×280ms retry loop.
- *Acceptance:* [ ] opening a citation always lands at the focus zoom regardless of prior zoom/open; [ ] re-targeting while open re-centers; [ ] vitest asserts zoom is `CITE_FOCUS_ZOOM` on target change.

**R13 (D3) — Highlight the WHOLE sentence (token-anchored span). [P1]**
- *Change (backend only):* in `backend/thumbnail.py locate_text_spans_in_pdf`, when the full needle fails, do a token-anchored span: `page.get_text('words')`, fuzzy-align first+last few normalized words, union the word rects between them; or `page.search_for(needle, quads=True)` extended to line end. Prefer the longest line-aligned span over the 5-word fallback; keep normalized 0..1 rects (shape as `:933-934`).
- *Acceptance:* [ ] for a fixture where the exact needle is broken (soft break/hyphenation) but first/last words are present, the rects cover the whole sentence, not a 5-word prefix; [ ] 5-word fallback only when token-anchoring also fails; [ ] pytest for the union span.

**R31 (P4) — Pinch-to-zoom in the per-ref context overlay. [P1]**
- *Change:* in `StatusSection.jsx ThumbnailOverlay`, add a non-passive `wheel` listener on `scrollRef` (`:408`) mirroring `DocumentViewer.jsx:119-147`: gate on `e.ctrlKey`, `preventDefault`, `setZoom(z => clamp(z*Math.exp(-e.deltaY*0.01), ZOOM_MIN, ZOOM_MAX))` (`:65`); add `gesturestart/change/end` with a `zoomRef` baseline for WebKit/Tauri. Best: extract `useGesturePinchZoom(ref, setZoom, {min,max})` and use it in both DocumentViewer and ThumbnailOverlay.
- *Acceptance:* [ ] trackpad/touch pinch zooms the per-ref overlay page image without scrolling or triggering browser zoom; [ ] shared hook used by both viewers; [ ] vitest/jsdom listener-attach test.

---

### Work-stream 3 — Add-to-reference-list: corrected renumbered list + tracked PDF changes *(adversarial loop REQUIRED — G1/G2/G3)*

> Order: **R17 (G3)** dedup guard (cheap correctness) → **R18 (G1)** commit renumber + corrected-list endpoint → **R19 (G2)** PDF/HTML tracked-change diff. The algorithms-professor subagent must sign off on renumber splicing and dedup normalization.

**R17 (G3) — Reject duplicates/invalid before offering to add. [P1]**
- *Change:* `backend/main.py add_reference_to_check (:5905)` — before insert, normalize incoming DOI (reuse `backend.retraction.normalize_doi`, already imported in `gap_finder.py:18`), arxiv_id, lowercased title; on match return HTTP 409 `{duplicate:true, existing_index}`. `web-ui/src/components/MainPanel/GapFinder.jsx` — cross-check each suggestion's DOI against the `references` prop (normalize client-side), gray out / label "already in list" (incl. DOI-only matches OpenAlex couldn't resolve), add a validity guard (non-empty title or resolvable DOI), and handle the 409 in the add forms (`GapFinder.jsx:220-226`, `CorrectionsView.jsx:742-766`).
- *Acceptance:* [ ] adding a present DOI/arxiv/title returns 409 and the UI shows "already reference [N]"; [ ] GapFinder grays out present/invalid suggestions; [ ] pytest for the 409 path (DOI casing, title-only); [ ] vitest for the disabled suggestion + 409 surfacing.

**R18 (G1) — Commit renumber and yield the new renumbered list. [P1]**
- *Change:* have GapFinder/AddReference call `addReferenceToCheck` with `insert_at_index` derived from `renumber_preview.new_printed_number` so the committed `renumbering` map is non-empty (logic at `main.py:5964-5972`). Add `GET /api/check/{id}/corrected-reference-list?renumber=1` returning the full reference list in a chosen citation style with new contiguous numbers (reuse `export._as_list` at `export.py:97` + a serializer mirroring `formatters` `exportReferenceAsStyle`); surface a "Download new reference list" button. Add `apply_renumber(text, shifted_markers)` to `backend/inline_citation_checker.py` (does not exist yet) splicing `new_marker` over `marker` using captured `offset`s in **descending offset order**.
- *Acceptance:* [ ] default Add / GapFinder produces a non-empty `renumbering` map and list `index` renumbers; [ ] the endpoint returns the full styled contiguously-numbered list behind a download button; [ ] pytest for `apply_renumber` (multiple/adjacent/multi-digit markers, no off-by-one) and the endpoint.

**R19 (G2) — Tracked was→should-be, rendered into the PDF + export diff. [P1]**
- *Change:* add `GET /api/preview/{id}/corrections-annotated-pdf` that, per flagged ref with a `corrected_reference`, locates the cited text via `backend/thumbnail.locate_text_spans_in_pdf` (already used in `_annotate_pdf_highlights` `main.py:3373`) and applies `page.add_strikeout_annot` + a `FreeText`/`add_text_annot` carrying the corrected string (PyMuPDF/`fitz`); for inline renumber, annotate old markers via `renumber_preview.shifted_markers` offsets. Port the `wordDiff` red/green coloring into `export.py`'s corrected-row rendering (`_pdf_html_for_model:861` / `_ref_row_html:552`) so the report shows was→should-be, not flat "Suggested:".
- *Acceptance:* [ ] the endpoint returns a PDF with strikeout+insert annotations (and renumbered markers), or a clean 404/empty when no corrections; [ ] export HTML/PDF rows show token-level red/green diff; [ ] pytest round-trips the annotated PDF and asserts the export diff markup.

---

### Work-stream 4 — Corrections accuracy (DOI)

**R06 (B1) — Suggested correction must apply the verified DOI (esp. bibtex). [P1, BROKEN]**
- *Change:* `web-ui/src/utils/formatters.js` — add `case 'doi'`/`case 'arxiv_id'` to `getCorrectedReferenceData` (~`:659`) setting `corrected.doi` from `(parsed?.actual || issue.actual_value || issue.ref_doi_correct)` normalized with the `https://doi.org/`-stripping regex at `:1259`; change the seed at `:613` so a DOI named by a doi-type error/warning **wins** over the cited `ref.doi`; rewrite the bibtex DOI emission (`:1077-1099`) to prefer `corrected.doi`, falling back to `authoritative_urls`. `backend/refchecker_wrapper.py` — add `'ref_doi_correct'` to both propagation tuples (`:1328-1330`, `:1480-1482`) and the backfill (`:1310-1313`). Optionally seed `corrected.*` from `ref.corrected_reference` (`refchecker_wrapper.py:3786`).
- *Acceptance:* [ ] for a doi-mismatch ref (verified `actual_value`, wrong `ref.doi`, no `authoritative_urls`): bibtex contains the verified DOI and not the wrong one; APA/other styles likewise; [ ] CorrectionsView word-diff shows the DOI change; [ ] regression vitest in `formatters.test.js`.

**R07 (B2) — `@article{awcomparison}` includes year=2018, venue, AND doi=10.5812/ijem.12104. [P1, BROKEN]**
- *Change:* apply R06, then strengthen `web-ui/src/utils/formatters.test.js` test #53 — drop `ref.doi`, supply `{error_type:'doi', actual_value:'10.5812/ijem.12104'}` (or `ref_doi_correct`) with no `authoritative_urls`, assert bibtex contains `doi = {10.5812/ijem.12104}` alongside the existing `2018` and venue assertions.
- *Acceptance:* [ ] strengthened #53 asserts DOI + year + venue with no `authoritative_urls`; [ ] same holds for the true "DOI missing" shape.

---

### Work-stream 5 — Gap-finder & similar-papers (no-hallucination guard + provenance)

**R20 (C2) — Verification + provenance on the reachable similar-papers modes. [P1]**
- *Change:* `backend/main.py _cites_refs_papers_impl (~:6708)` — after `_shape_cites_refs_candidates`, reuse the verify logic from `_find_similar_papers_impl` (`db.lookup_verified_reference :7230`, `checker.verify_reference :7242`, bounded by the existing semaphore) to populate `pre_verified/was_verified/verified_status` so the existing `SimilarPapersPanel` chips (`:492-518`) render real status. `web-ui/src/components/MainPanel/SimilarPapersPanel.jsx` — add an OpenAlex/DOI provenance link per row (row has `c.openalex_id`/`c.doi`, shaped at `main.py:6732,6736`), mirroring `GapFinder.jsx:129-133`'s "✓ OpenAlex ↗". Keep it real-data-gated — no synthesized verification.
- *Acceptance:* [ ] References/Citations/Both rows show a real verification chip (verified / "? unconfirmed"), not always-null; [ ] each row shows an OpenAlex/DOI link; [ ] backend test that output carries populated `verified_status` for a cached-verified fixture; [ ] vitest for the chip + link.

**R39 (C1-FIX) — Friendly 404 + smoke test. [P2]**
- *Change:* `web-ui/src/components/MainPanel/GapFinder.jsx run()` catch (`~:31-33`) — special-case HTTP 404 to "Gap finder is unavailable — please update the app" instead of raw HTML. Add a backend smoke test (`tests/unit/test_gap_finder.py`) hitting `GET /api/check/<id>/gaps` asserting 200 JSON for a valid check.
- *Acceptance:* [ ] a 404 shows the friendly message; [ ] smoke test asserts JSON (not SPA catch-all).

**R08 (R4) — Restore common-cites/refs visualization, not just a count. [P1, BROKEN]** *(adversarial loop)*
- *Change:* `backend/cites_refs.py` — collect the overlapping ids per candidate and hydrate them via `_hydrate_works`; `backend/main.py` pass the hydrated overlap through at `:6745/:6749` so the panel/graph can show **which** works are shared, not just a number. Surface the shared works in `SimilarPapersPanel`/the graph row.
- *Acceptance:* [ ] relation modes display the actual shared works (titles/links), not just a count; [ ] backend test that the impl returns the overlap id set + hydrated works; [ ] vitest that the panel renders the shared works.

---

### Work-stream 6 — Inline-citation parser (alphabetic + last-mentioned) *(adversarial loop — ABSTAIN beats a wrong badge)*

**R15 (E1) — Parse/validate alphabetic-marker scheme; clarify last-mentioned. [P1]**
- *Change:* `backend/inline_citation_checker.py` — add `_ALPHAKEY_PAT` for `[Smi04]`/`[ABC+20]` plus a letter form `r'\[[a-z]\]'`; add `'alpha-key'` as a counted family in `_detect_scheme` (extend the `counts` dict ~`:331` + family-vote) with the same plausibility/abstain discipline. Validate by building an `author+year → key` map from the references list (not an integer sequence); report `undefined`/`uncited`/`duplicate`. For alpha schemes set `ordering.convention='alphabetical'` and skip the ascending check in `_classify_ordering`. "Last-mentioned" is not a standard convention — add it only behind a clear `convention='reverse-appearance'` branch (mirror `:589-605` on descending pairs) **or** document why it intentionally ABSTAINs. Add an `ABSTAIN_MSG` entry for the new scheme in `web-ui/src/components/MainPanel/CitationIntegrity.jsx:20-28`. Note `_count_author_year (:226)` takes `ref_count` but never uses it — ignore it for the new family. Add fixtures to `tests/unit/test_inline_citation_checker.py`.
- *Acceptance:* [ ] alpha-key papers detected + validated against the author/year→key map (undefined/uncited/duplicate); [ ] `[a]`/`[A]` handled or explicitly abstained (no false numeric/author-year classification); [ ] alpha schemes report `alphabetical` ordering, no spurious out-of-order; [ ] mixed/ambiguous still ABSTAINS; [ ] new pytest fixtures cover detection, issue types, and abstain.

---

### Work-stream 7 — Author UI

**R09 (A2) — "et al." expandable to the full enriched author list. [P1, MISSING]**
- *Change:* `web-ui/src/utils/formatters.js:77` — in `normalizeAuthors` filter trailing tokens matching `/^(et al\.?|and others)$/i` so they never render as names. `web-ui/src/components/ReferenceCard/ReferenceCard.jsx AuthorsLine (~:1324)` — detect a trailing et-al token; when set OR `enrichedAuthors.length > list.length`, render an "et al. (show N authors)" toggle that swaps `list` to `enrichedAuthors` rendered via the existing `AuthorChip`, with a "show less" collapse.
- *Acceptance:* [ ] a 2-3-name "et al." ref shows a working "show N authors" control expanding to the enriched list; [ ] "et al."/"and others" never renders as a name; [ ] unchanged when there is no enriched list and no token; [ ] vitest for the filter + the expand swap. *(Pairs with R41 below.)*

**R41 (N3-residual) — No fake "et al" sentinel chip; recover on the error path. [P2]**
- *Change:* filter standalone `et al`/`others`/`and others` sentinels out of the display list (`formatters.js normalizeAuthors`, or the `AuthorsLine` list build at `ReferenceCard.jsx:1325`) so a non-recoverable et-al doesn't render as a fake chip (`:1441`) with a trailing comma (`:1442`). Optionally call `recover_full_authors_from_enrichment` on the error path (`refchecker_wrapper.py _format_error_result :1625`) where partial enrichment exists.
- *Acceptance:* [ ] no fake "et al" chip renders when recovery can't fire; [ ] vitest covers the sentinel filter. *(Implement together with R09.)*

**R11 (A6) — Pin/expand the author popover into a persistent scrollable panel. [P1]**
- *Change:* in `AuthorChip`, add a `pinned` state; clicking the name (or a `⤢` control in the popover header ~`:1689`) toggles `pinned`, keeping `open=true` regardless of mouse, with an explicit `×`; add an outside-click + `Escape` handler modeled on `document.addEventListener('mousedown', handleClickOutside)` at `ReferenceCard.jsx:343`. For the "fully opened" state render the pinned popover as a larger centered modal/drawer showing the **complete** recent-papers list — remove/raise `slice(0,3)` at `:1737` for the pinned view.
- *Acceptance:* [ ] clicking the name (or ⤢) pins it open; stays open when the cursor leaves; [ ] `×`, outside-click, and `Escape` all close it; [ ] pinned panel shows >3 papers and scrolls; [ ] vitest for pin toggle, close paths, and >3 papers.

**R10 (A3) — Name/title-resolution fallback for ID-less authors (non-fabricating). [P1]**
- *Change:* `backend/main.py` — extend `author_profile (:7840)` or add a sibling endpoint that, given a bare name **plus paper title/year**, queries OpenAlex `/authors?search=<name>` (and/or S2 `/author/search`) and returns the single best high-confidence match's ids+metrics, requiring a strong corroboration signal (the candidate appears on a work matching the supplied title/year) before returning anything; return empty rather than a guess. `ReferenceCard.jsx AuthorChip` — when `e` has no `s2_author_id`/`openalex_id`, render a "Find profile" action calling it on demand; confident hit populates the popover, miss shows a quiet "no confident match". Optional backend backfill in `enrichment.py build_enrichment` (one OpenAlex `/works/doi:` lookup when a DOI exists but no author ids).
- *Acceptance:* [ ] ID-less author exposes "Find profile"; confident match populates with real metrics; non-match adds no data; [ ] the endpoint never returns a profile without title/year corroboration; [ ] backend test (confident vs ambiguous→empty); [ ] vitest that the button appears only for ID-less authors.

**R36 (A1-FIX) — Read ORCID from the fetched profile; raise hit-rate. [P2]**
- *Change:* `ReferenceCard.jsx:1605` — `const orcidUrl = (profile?.orcid || e?.orcid) ? …` (and wire the same fallback into footer `profileLinks` ~`:1654-1661/:1750-1772` and the ORCID-number tooltip `:1422`). `backend/main.py author_profile (7840-7913)` — on the S2 path, surface ORCID from the S2 `/author/{id}` response's `externalIds.ORCID` when present; include `orcid` in the S2-path payload. Only set when the source returns a real value.
- *Acceptance:* [ ] popover renders ORCID when the profile returns it even if `e.orcid` was empty; [ ] S2-only authors with an ORCID in `externalIds` now show it; [ ] no ORCID when none resolved; [ ] backend test for the S2-path `orcid` inclusion/omission.

**R37 (A4) — Clearer inline badge + co-located citation count. [P2]**
- *Change (pure FE):* `ReferenceCard.jsx:649-663` — relabel the badge to `Used {N}× in this paper` (keep the body-text tooltip); when `reference.enrichment?.cited_by_count` is present append a second pill `· {cited_by_count} citations` with a distinct tooltip "Times cited across the literature (OpenAlex/S2)".
- *Acceptance:* [ ] unambiguous label + second pill when available; [ ] no second pill when absent; [ ] vitest for both pills.

---

### Work-stream 8 — Summary badges & per-article isolation

**R16 (F2) — Make the two Summary badges agree. [P1]**
- *Change:* `web-ui/src/components/MainPanel/StatsSection.jsx:706` — change the row-2 tooltip from "(total issues)" to "references with `<issue>`" (and the heading at `:673`) to match the per-ref value. `web-ui/src/components/MainPanel/HealthBadge.jsx:52-53` (in `computeScore`) — make the breakdown warnings-only like the chips: `if hasErrors errors+=1 else if hasWarnings warnings+=1`, ideally reusing `computeReferenceStats(references, true)`.
- *Acceptance:* [ ] for the `StatsSection.test.jsx:29-48` both-error-and-warning fixture, HealthBadge counts == StatsSection chip counts (Errors 3 · Warnings 2, not 4); [ ] the row-2 tooltip no longer says "(total issues)"; [ ] vitest asserting the equality.

**R25 (L2) — Similar-papers isolated per article. [P1]**
- *Change:* `web-ui/src/components/MainPanel/MainPanel.jsx:498` — pass `checkId=(selectedCheckId>0?selectedCheckId:currentCheckId)` (the expression already used for the four sibling panels) so `articleKey` resolves to the unique `check:id` branch (`SimilarPapersPanel.jsx:81`); optionally add `key=similar-{selectedCheckId}`.
- *Acceptance:* [ ] two `SimilarPapersPanel` instances with identical empty title/source but different `checkId` don't bleed; [ ] vitest: search the first, assert the second still shows the Find button.

---

### Work-stream 9 — Enrichment cross-source backfill *(adversarial loop — M1/M2; never overwrite/never fabricate)*

**R21 (M1) + R22 (M2) — Cross-source backfill of counts, abstract, tldr, funding. [P1]**
- *Change:* add `backfill_enrichment(verified_data, reference)` in `src/refchecker/utils/enrichment.py`, invoked from `backend/refchecker_wrapper.py` right before `build_enrichment` (`:1527`) AND from the add-ref path in `backend/main.py` before `:6270`. Resolve canonical DOI (reuse cleaning at `enhanced_hybrid_checker.py:1546-1551`), then fetch OpenAlex `GET /works/doi:{doi}` (`cited_by_count`, `referenced_works` length, `abstract_inverted_index`, `grants[]`), Crossref `GET /works/{doi}` (`is-referenced-by-count`, `references-count`, JATS `abstract`, `funder[]`), and S2 `get_paper_by_id`/title search (`citationCount`, `referenceCount`, `tldr`, `abstract`). Merge into `verified_data` **only** for keys it lacks/empty — mirror `_enrich_matched_paper`'s never-overwrite/never-fabricate contract (`semantic_scholar.py:380-388`). `build_enrichment`'s `_max_count (:74-91)`, reference-count pool (`:265-274`), inverted-index reconstruct (`:176-206`), JATS strip (`:168-173`), and grants/funders pool (`:486-509`) then surface the richest values with no FE change (presence-gated at `AdditionalInfoBar.jsx:116-120`, `ReferenceEnrichmentStrip.jsx:217-241`). Per-DOI TTL cache (mirror `_AUTHOR_PROFILE_CACHE` at `main.py:7836-7837`), 1 retry + short timeout per source, soft-fail, concurrency-limited so a 30+ ref bibliography doesn't stall. Optionally append source names to `_verified_by`.
- *Acceptance:* [ ] a non-S2 winner missing counts/tldr/abstract/funding gets them backfilled from OpenAlex/Crossref/S2 by DOI; [ ] existing real values are never overwritten and nothing is fabricated; [ ] a 30-ref bibliography doesn't stall (cache + concurrency cap); [ ] pytest in `tests/unit/test_enrichment.py` for merge-only-when-missing + soft-fail.

**R35 (M5) — Clickable count tiles (or labeled stats with titles). [P2]**
- *Change:* `ReferenceEnrichmentStrip.jsx:105-114` — add a per-counter `href` when `openalex_id` is present, rendered via the existing `PillLink (:272-325)`: Citations → `https://openalex.org/works?filter=cites:<id>`; Reference Count → `https://openalex.org/<id>`; Citing Patents → keep informational with a clarifying title. When no `openalex_id`, keep text but add a `title` to every tile for parity with Citations (`:110`).
- *Acceptance:* [ ] Citations tile becomes a link when `openalex_id` is set, plain text otherwise; [ ] every tile has a title; [ ] unit test for the link/no-link branch.

---

### Work-stream 10 — Share video

**R23 (H2 / Q1 / Q3) — Persistent, higher-quality per-check "video"; real per-article counts; no record/download buttons. [P1]**
- *Change (choose B unless a literal .webm is explicitly required):*
  - **B (preferred):** drop the `&& animActive` gate at `ShareModal.jsx:187` (keep `key={animKey}`); in `ShareAnimationCanvas.jsx` accept `loop=false`, clamp `t=Math.min(1,(now-startRef.current)/DUR)` (drop the modulo at `:89`) and `cancelAnimationFrame` once `t===1` to hold the final frame so the top never blanks; the `ANIM_PLAY_MS` timer (`:54-62`) becomes unnecessary. Improve quality: raise the dpr cap to `Math.min(3,…)` at `:38`, increase logical width and font sizes, pass a taller height. Keep real `buildReferenceSummary` numbers, per-open remount, and no record/download buttons.
  - **A (only if literal webm):** `canvas.captureStream(30)` → `MediaRecorder({mimeType:'video/webm'})` → `Blob` → muted/autoplay/playsInline `<video>` (poster = last frame), regenerated per modal open keyed to `checkId`, no controls.
- *Acceptance:* [ ] the banner stays visible after playback (frozen final frame), never blanking the top; [ ] visibly higher quality; [ ] numbers match the Summary; per-check remount replays each open; still no record/download buttons; [ ] vitest that the canvas stays mounted post-playback and numbers come from `buildReferenceSummary`.

**R24 (Q4) — Per-article video on the stats page. [P1, MISSING]**
- *Change:* import `ShareAnimationCanvas` into `web-ui/src/components/MainPanel/StatsSection.jsx` (or render in `MainPanel` next to `<StatsSection>`), feeding the SAME counts StatsSection computes (`StatsSection.jsx:211-222 summaryCounts`) plus `paperTitle`; thread `aiBand/aiScore` from `selectedCheck.ai_detection` (`MainPanel.jsx:67`) since StatsSection isn't passed `ai_detection`. Reuse the R23 play-once-then-freeze; key on `selectedCheckId`.
- *Acceptance:* [ ] the per-article animation renders alongside that article's stats with matching counts; [ ] freezes on the final frame; [ ] vitest that the stats-page animation receives the StatsSection counts.

---

### Work-stream 11 — Auth, teams, enable-from-app *(adversarial loop — J3 / U1 / U3)*

> Batch-2 refines batch-1's "whole feature broken (J3)": presence (U2) is DONE; report only the partials. The DB migration is the dependency root.

**R26 (J3 → U1) — Multi-user collaboration on the same batch + shared checks. [P1]**
- *Change:*
  - **DB (`backend/database.py`):** add `team_id INTEGER NULL REFERENCES teams(id)` to `check_history` (schema at `:366-403`) + an idempotent `ALTER` for existing DBs (match the repo's other late-added nullable columns) + an index; add `get_user_team_ids`, `set_check_team(check_id, team_id)`, `get_team_checks(team_id)`; add `get_batch_summary`/`get_batch_checks` variants (or a `team_ids` param) returning a batch when the requester is owner OR a member of the batch's team, using `db.is_team_member (:1859)`.
  - **Backend (`backend/main.py`):** replace `_get_owned_batch_or_404 (:1215)` with `_get_accessible_batch_or_404` allowing team members; **EXTEND** the existing `PATCH /api/batch/{batch_id} (:4556-4570)` to accept `team_id` (do not add a new route); add `POST /api/checks/{id}/share {team_id}` and `GET /api/teams/{team_id}/checks` gated via `_get_team_for_member_or_404 (:1484)`.
  - **Realtime (`backend/websocket_manager.py`):** gate `/api/ws/presence/{room_id}` (`main.py:1701`) join on accessible-batch membership; broadcast `reference_result`/`summary_update` to the presence/team room in addition to the owner's session (`:123-129`).
  - **FE:** add a "Share with team" control + a team-checks list in `TeamMenu.jsx`/`BatchSummaryView`. Optionally add an explicit "Sign up" affordance in `LoginPage.jsx`.
- *Acceptance:* [ ] a batch shared with a team (`team_id` via the extended PATCH) opens for a non-owner team member (no 404) with summary/checks; [ ] presence WS rejects non-members; team members appear in `PresenceAvatars`; [ ] `reference_result`/`summary_update` reach all room/team members live; [ ] backend tests: member 200, non-member 404, access-gated presence.

**R27 (J3 → U3) — Enable accounts/teams from inside the app (hot-reload). [P1]**
- *Change:* add `auth.reload_config()` re-reading `auth_config.env` into the module credential globals and recomputing `MULTIUSER_MODE`/`get_available_providers`; call it at the end of `set_auth_config (main.py:1370)`; convert `get_available_providers`/`is_multiuser_mode` to read current values via accessors rather than import-time constants (`auth.py:30-32,36,503-518`), so `/api/auth/providers` reflects changes immediately without restart.
- *Acceptance:* [ ] enabling accounts/providers in-app takes effect without a backend restart; `/api/auth/providers` updates live; [ ] backend test that `reload_config` flips `is_multiuser_mode()`/provider list after writing the env.

---

### Work-stream 12 — Graph & buttons polish

**R38 (I2) — Library 3D graph up to Explore quality. [P2]**
- *Change (FE-only, `GraphLibraryView.jsx`):* add a `useEffect` keyed on `graphData` calling `fgRef.current.d3Force('charge')?.strength(-200).distanceMax(600)` + `d3Force('link')?.distance(70).strength(0.2)` then `d3ReheatSimulation()` (mirror `ExploreGraphView.jsx:277-294`); add `onEngineStop={() => fgRef.current?.zoomToFit?.(500,80)}` (`:298-300`); change `enableNodeDrag={false} (:362)` to `enableNodeDrag` + `onNodeDragEnd` writing `node.fx/fy/fz` (`:306-311`); optional persistent labels via `nodeThreeObject` + three-spritetext gated to `hl.nodes`.
- *Acceptance:* [ ] nodes draggable + pin on drop; auto-frame on engine stop; force tuning prevents the hairball; [ ] render smoke test that ForceGraph3D gets `enableNodeDrag`, `onEngineStop`, and a d3Force effect.

**R32 (R1) — Clickable DOIs in the Seen-library radial graph. [P2]**
- *Change:* drop `pointerEvents=none` in `RadialChordGraph` (`:108-129`) and render `ident` as an `<a>` like `:393-402` so the radial hover DOI is a working link.
- *Acceptance:* [ ] the radial DOI is clickable (opens externally / via Tauri `openExternal`); [ ] vitest that the rendered DOI is an anchor.

**R33 (T3) — Unified button styling. [P1]**
- *Change:* either refactor onto a shared `common/Button.jsx` (add a `pill`/`ghost-xs` variant) **or** extract shared sizing+hover tokens for `AdditionalInfoBar.jsx Pill (:15-36)` and `ArticleAssistant.jsx` trigger/Summarize/Send, mirroring `ReferenceCard.jsx:198-207` (or adopt `baseStyle` at `ReferenceActionsBar.jsx:368-373`).
- *Acceptance:* [ ] per-ref / assistant / pill buttons share consistent padding/font-size and have hover states; [ ] vitest/snapshot for the shared variant.

**R34 (T4) — Separate model for Chat-with-PDF vs Summarize. [P1]**
- *Change (FE-only; backend already accepts per-call `llm_config_id`):* `useConfigStore.js` — add `SUMMARY_SELECTION_KEY` + `selectedSummaryConfigId` + `selectSummaryConfig` + `getSelectedSummaryConfig` mirroring the chat trio; wire into `fetchConfigs (~:73-90)` and `deleteConfig (:197-208)`. `LLMSelector.jsx` — add a `mode==summarize` branch in `activeSelectedId (:36-40)`. `SettingsPanel.jsx:1660-1670` — split into Chat + Summarize sections. `ArticleAssistant.jsx` — use `getSelectedSummaryConfig` in `runSummary`, keep `getSelectedChatConfig` for `sendChat`.
- *Acceptance:* [ ] Chat and Summarize have independent model selections that persist; [ ] vitest that the store exposes the summary selection and ArticleAssistant routes each feature to its config.

---

### Work-stream 13 — CI / release

**R40 (U6) — Fresh full green-CI pass before any publish. [P1]**
- *Change / verify:* from a working shell run `cd web-ui && npm run lint && npm test && npm run build`; backend `python -m pytest tests/unit` (incl. `tests/unit/test_enrichment.py`); `cargo check` in `tauri-app/src-tauri` and confirm no "unexpected cfg value: devtools" warning. The two named fixes are already in `desktop-v0.9.18`; cut a new tag only if the post-v0.9.18 work in this batch is to be released.
- *Acceptance:* [ ] lint clean (incl. the SimilarPapersPanel elapsed-timer nit), all vitest + pytest green, build succeeds, `cargo check` clean (no devtools cfg warning); [ ] CI green before any publish/release cut.

---

## 5. Build order (dependency-ordered, P0 first)

1. **R01 (K2, P0)** — Published-date honesty. Tiny, high-visibility; do first.
2. **R04 (F1, P0)** — LLM hang. Independent; highest user-impact. `hallucination_verifier.py` + `refchecker_wrapper.py` + FE fallback.
3. **R05 (H1, P0)** — share 500 hardening + PDF graceful degrade. Independent backend.
4. **R14 (D5, P1/S)** — shared status-color map (`statusColors.js`). Unblocks consistent coloring for the viewer stream.
5. **R02 (O3) + R03 (O4, P0)** — native-PDF routing + per-sentence buttons + docx/html→PDF *(adversarial loop)*.
6. **R28 (O2) + R29 (O5) + R30 (O6, P1)** — in-PDF citation→reference-list jump, opacity, refId. Then **R12 (D1)** zoom/centering, **R13 (D3, backend)** sentence span, **R31 (P4)** pinch-zoom (shared hook).
7. **R26 (J3→U1, P1)** — auth/teams: DB migration (`check_history.team_id`) first, then accessors + `_get_accessible_batch_or_404`, then presence gating/broadcast, then FE share control. Then **R27 (J3→U3)** hot-reload config.
8. **R06 (B1) → R07 (B2, P1)** — DOI correction (B2 depends on B1's bibtex/`getCorrectedReferenceData` fixes).
9. **R09 (A2) + R41 (N3-res, P1/P2)** — et al. expansion + sentinel filter (same `formatters.js`/`AuthorsLine`). Then **R11 (A6)** pin/modal, then **R10 (A3)** find-profile fallback inside the now-pinnable chip; **R36 (A1-FIX)** rides along on `author_profile`.
10. **R16 (F2, P1/S)** — badge agreement. **R25 (L2, P1/S)** — similar-papers isolation. Small, independent.
11. **R20 (C2, P1)** — similar-papers verification + provenance. **R39 (C1-FIX, P2)** alongside. **R08 (R4, P1)** common-cites/refs viz *(adversarial loop)*.
12. **R15 (E1, P1)** — alpha-key scheme *(adversarial loop)*.
13. **R17 (G3) → R18 (G1) → R19 (G2, P1)** *(adversarial loop)* — dedup guard, then renumber-commit + corrected-list endpoint, then PDF/HTML tracked-change diff (reuses R13's improved `locate_text_spans_in_pdf`).
14. **R21 (M1) + R22 (M2, P1)** — enrichment cross-source backfill *(adversarial loop)*. **R35 (M5, P2)** count-tile links after.
15. **R23 (H2/Q1/Q3, P1)** then **R24 (Q4, P1)** — share video persistence/quality, then stats-page video.
16. **R37 (A4), R38 (I2), R32 (R1), R33 (T3), R34 (T4, P1/P2)** — polish.
17. **R40 (U6, P1)** — full green-CI pass; gate the release on it.
18. Optional one-liners (§3) last.

---

## 6. Definition of Done / TDD

**Global DoD**
- Every non-DONE item ships ≥1 new automated test in the correct suite: **vitest** for `web-ui/` (`*.test.jsx`/`*.test.js` next to the component/util; `cd web-ui && npm test`), **pytest** for backend/library (`tests/unit/`, run from repo root per `pytest.ini`).
- `cd web-ui && npm run build` succeeds (no build/type errors) and `cd web-ui && npm test` is green — do not break `formatters.test.js`, `StatsSection.test.jsx`, `SimilarPapersPanel.test.jsx`, `ExploreGraphView.test.jsx`, `AdditionalInfoBar.test.jsx`, the `ReferenceCard` tests.
- Backend `pytest` green — do not break `tests/unit/test_inline_citation_checker.py`, `test_gap_finder.py`, `test_enrichment.py`, `test_export_formats.py`, existing auth tests. **Add the missing regression test** for `POST /api/check/batch` with `semantic_scholar_api_key` + `paperclip_api_key` (asserts `!= 500`) to lock the de-duped batch-check fix.
- **eslint clean**, including the **U6 SimilarPapersPanel elapsed-timer lint nit** (already addressed in `desktop-v0.9.18`; keep it clean).
- **Tauri builds** (`cargo check` in `tauri-app/src-tauri`) with **no "unexpected cfg value: devtools" warning**.
- **No regressions** to any §2 DONE item. **No fabricated authors/papers/DOIs/counts** reach the UI. No empty gated containers, no dead buttons. No secrets/.env committed.
- The only justified **new files** are `web-ui/src/utils/statusColors.js` (R14), `web-ui/src/utils/useGesturePinchZoom` hook (R31), and the new test files; everything else edits existing files.
- **CI green before any publish/release cut** (R40). Commit messages (only if asked) end with `Co-Authored-By: claude-flow <ruv@ruv.net>`.

**Per-cluster verification**
- **Honesty/P0:** ref with only `publication_date` never renders an empty strip (R01); a timed-out hallucination task still emits `'completed'` with no permanently-pending ref (R04); a serialize failure in any sharing flow returns a stable detail and missing PDF engine returns 422/501 (R05).
- **Viewers:** `statusColors` returns correct colors for every status incl. the `hallucinated` alias and both viewers agree (R14); per-ref "View in document" renders the native pdf.js viewer for PDF and converted sources, and every AI sentence has a per-sentence button (R02/R03); clicking an inline citation scrolls+flashes the matching reference entry **inside the PDF**, banners fully opaque, all spans get a working link (R28/R29/R30); zoom resets to `CITE_FOCUS_ZOOM` on target change (R12); a broken-needle fixture yields a full-sentence union span (R13); pinch zooms the per-ref overlay (R31).
- **Auth/teams:** team-member 200 + non-member 404 on a shared batch, access-gated presence join, live `reference_result`/`summary_update` to all members (R26); in-app enable flips `is_multiuser_mode()`/providers without restart (R27).
- **Corrections:** bibtex carries the verified DOI (not the wrong one) with no `authoritative_urls`; strengthened test #53 asserts DOI+year+venue (R06/R07).
- **Author UI:** et-al expands to the enriched list and the sentinel never renders as a chip (R09/R41); popover pins open and closes via ×/outside/Escape showing >3 papers (R11); ID-less author "Find profile" returns only on title/year-corroborated confident matches (R10); ORCID renders from the fetched profile (R36); badge shows "Used N× in this paper" + a second citation pill (R37).
- **Summary/isolation:** HealthBadge counts == StatsSection chip counts for the both-error-and-warning fixture (R16); two SimilarPapersPanel instances with identical empty title/source but different `checkId` don't bleed (R25).
- **Gap-finder/similar:** reachable modes carry real `verified_status` + provenance link (R20); a 404 shows the friendly update message and the smoke test asserts JSON (R39); relation modes show **which** works are shared, not just a count (R08).
- **Inline parser:** alpha-key detection/validation/abstain fixtures pass; mixed input still ABSTAINS (R15).
- **Add-to-list:** `apply_renumber` splice correctness (multiple/adjacent/multi-digit), the corrected-reference-list endpoint, the corrections-annotated PDF, and the 409 duplicate path (DOI casing, title-only) all covered (R17/R18/R19).
- **Enrichment:** backfill merges only missing keys, never overwrites/fabricates, soft-fails, and a 30-ref bibliography doesn't stall (R21/R22); count tiles link when `openalex_id` is set and stay plain text otherwise (R35).
- **Share video:** the canvas stays mounted post-playback (frozen final frame), numbers come from `buildReferenceSummary`, no record/download buttons (R23); the stats-page animation receives the StatsSection counts (R24).
- **Graph/buttons:** `GraphLibraryView` ForceGraph3D gets `enableNodeDrag`/`onEngineStop`/d3Force (R38); the radial DOI is an anchor (R32); shared button variant applied with hover states (R33); Chat vs Summarize have independent persisted model selections (R34).
- **CI/release:** lint + vitest + pytest + build + `cargo check` all green; no devtools cfg warning; CI green before publish (R40).

---

## 7. Orchestration runbook — the fix prompt (workflows · subagents · loops · watchdogs · reviewers)

This is the paste-ready directive for an autonomous harness to actually CLOSE every item in §3. It drives the 13 work-streams of §4 in the §5 build order, one work-stream per workflow, with an adversarial subagent loop gated by a watchdog + reviewer, iterating until the §6 DoD is green.

### Roles (subagents)
- **researcher** — reads the work-stream's §4 items + cited files, enumerates the inputs that break a naive fix BEFORE any code.
- **full-stack engineer** — implements FE/BE changes + endpoint contracts + data shapes.
- **ml engineer** — owns false-positive/abstain behavior and model routing (R04, R15, R20, R21/R22, R34).
- **regex engineer** — owns marker/needle/DOI patterns and normalization (R06/R07, R13, R15, R18, R21).
- **algorithms professor** — owns renumber splicing, ordering, dedup, span-union correctness (R13, R15, R17/R18/R19, R08).
- **reviewer** — adversarially re-reads the diff: correctness, contracts, missing tests, regressions vs §2.
- **watchdog** — enforces the HARD CONSTRAINTS and signs off LAST: no fabrication, no dead buttons, no empty gated containers, no regression to any §2 DONE item, real per-article counts, in-PDF (not React-tab) hyperlinks, every item's acceptance checkboxes ticked with file:line + passing tests.

### Loop (per work-stream, repeat until clean)
1. **Scope** (researcher): list the breaking inputs + the exact files/lines from §4.
2. **Implement** (engineers, in an isolated git worktree): code + ≥1 test per item (vitest for `web-ui/`, pytest for `tests/unit/`).
3. **Adversarial review** (reviewer + watchdog, + the domain subagent): each raises objections; an objection is only closed with evidence (file:line + a passing test). Loop back to step 2 until zero open objections.
4. **Verify** (tester): run the touched suites — `cd web-ui && npm run lint && npm test && npm run build`; `python -m pytest tests/unit`; `cargo check` in `tauri-app/src-tauri`. All acceptance boxes for the stream's items must pass.
5. **Gate** (watchdog): sign off only when step 4 is green AND no §2 regression. Merge the worktree.
6. Advance to the next work-stream.

### Stop condition
All 41 items (R01–R41) PASS their §6 acceptance, full CI is green (R40), no §2 regression, no fabricated data — then (only if asked) cut the release.

### Hard constraints (failing any = the item is NOT done)
- No fabricated authors/papers/DOIs/counts reach the UI; apply "ABSTAIN beats a wrong badge" to the gap-finder list + similar-papers (R20).
- No dead buttons / no fake data / no empty gated containers — the Published date (R01) renders the real value or is cleanly removed.
- Share video uses REAL per-article counts (`buildReferenceSummary`) and never blanks the top of the popup.
- Viewers color-code highlights by chaining/verification status and hyperlink inline citations to the reference list INSIDE the PDF (R02/R14/R28).
- Adversarial loop is MANDATORY for the heavy streams: 2 (viewers), 3 (add-to-list), 5→R08 (common-cites viz), 6 (inline parser), 9 (enrichment), 11 (auth/teams).

### Workflow-tool skeleton (one workflow per stream; pipeline = implement → review-loop → verify)
```js
// meta.phases: [{title:'Scope'},{title:'Implement'},{title:'Review'},{title:'Verify'}]
const STREAMS = [ /* §5 build order: S1..S13, each = {id, items:['R01',...], heavy:bool} */ ]
for (const s of STREAMS) {                         // sequential: respects build-order deps
  let objections = ['<seed>']
  let round = 0
  while (objections.length && round++ < 4) {       // LOOP until reviewers+watchdog clear it
    const scope  = await agent(scopePrompt(s),  {agentType:'researcher', phase:'Scope'})
    const impl   = await agent(implPrompt(s,scope,objections),
                               {isolation:'worktree', phase:'Implement'})   // engineers
    const panel  = await parallel([                // adversarial review panel
      () => agent(reviewPrompt(s,impl), {agentType:'reviewer',  phase:'Review', schema:VERDICT}),
      () => agent(watchdogPrompt(s,impl),{agentType:'production-validator', phase:'Review', schema:VERDICT}),
      ...(s.heavy ? ['ml','regex','algorithms'].map(r =>
        () => agent(domainPrompt(s,impl,r), {phase:'Review', schema:VERDICT})) : []),
    ])
    objections = panel.filter(Boolean).flatMap(v => v.openObjections || [])
  }
  await agent(verifyPrompt(s), {agentType:'tester', phase:'Verify', schema:CI_RESULT}) // lint+test+build+cargo
}
```

### Paste-ready master prompt (hand to the harness)
> Close every remaining item in `docs/REMAINING_WORK.md` §3 (R01–R41) for the refchecker monorepo at `/Users/ario/Downloads/refchecker`. Work one §4 work-stream at a time in the §5 build order (P0 first: R01 → R04 → R05 → viewers). For EACH work-stream run an adversarial loop: a **researcher** enumerates breaking inputs; **full-stack / ml / regex / algorithms** engineers implement the change + ≥1 test per item in an isolated worktree; a **reviewer** and a **watchdog** (plus the relevant domain subagents for the heavy streams 2,3,5-R08,6,9,11) challenge the diff and only close an objection with file:line + a passing test; iterate until zero objections. Then a **tester** runs `cd web-ui && npm run lint && npm test && npm run build`, `python -m pytest tests/unit`, and `cargo check` in `tauri-app/src-tauri`; the watchdog signs off only when every acceptance checkbox for that stream passes and no §2 DONE item regressed. Enforce the §7 hard constraints (no fabrication, no dead buttons, no empty gated containers, real per-article video counts, in-PDF hyperlinks). Do NOT rebuild anything in §2. Stop only when all 41 items pass §6 acceptance and full CI is green (R40); do not cut a release until then.

---

## 8. Batch 3 — additional requests (R42–R45)

New asks captured after the run started. R42 touches in-flux viewer files (`NativePdfViewer.jsx`/`DocumentViewer.jsx`) so it is scheduled AFTER the viewer streams S5–S7; R45 folds into R23/R24 with tightened acceptance. Each carries the adversarial implement→reviewer+watchdog→verify loop.

| ID | Area | Requirement | Current state (file ref) | Severity |
|---|---|---|---|---|
| **R42** | Viewers | In **all** native PDF views, a search/find option (Cmd/Ctrl+F) with match highlight + next/prev + count | No find UI in the pdf.js viewers (`NativePdfViewer.jsx`, `DocumentViewer.jsx`); text layer exists for highlights | **P1 · MISSING** |
| **R43** | Per-ref chat | Make the reference's file queryable: fetch its full text so chat answers from the document, not only the TL;DR | `article_chat.py:259` chats on whatever `grounding` is passed (anticipates a "from abstract only" banner `:252`); FE passes only TL;DR → disclaimer in `ArticleAssistant.jsx`; no full-text retrieval for refs | **P1 · PARTIAL** |
| **R44** | Library UI | When a ref is in the library, a clearly-labeled "Remove from library" near the in-library pill, distinct from the reference-list Remove | Both exist + titled distinctly (`ReferenceActionsBar.jsx:405` "…from the check" vs `AdditionalInfoBar.jsx:174` "…from your Seen-References library"); ambiguous visible labels/placement | **P2 · PARTIAL** |
| **R45** | Share video | Video counts must equal that article's Summary; play once then freeze on the completed frame until the popup is closed & reopened (replays once) | `ShareModal.jsx:86`/`ShareAnimationCanvas` use `buildReferenceSummary` but with non-style-aware inputs vs `StatsSection.jsx:211-212`; animation loops/unmounts | **P1 · BROKEN (merge into R23/R24)** |

### R42 — Native-PDF find/search *(implement after S5–S7)*
- *Change:* add a Find bar to the shared pdf.js viewer used by the per-ref context view AND the AI-detection viewer. Prefer pdfjs `EventBus` + `PDFFindController` wired to the existing text layer; else a custom controller over the rendered text-layer spans (normalize → match → wrap in `<mark>` → track current index → scroll into view). Keyboard: Cmd/Ctrl+F focuses the bar, Enter/Shift+Enter next/prev, Esc closes+clears. Must not clash with the R14 status/citation highlight colors.
- *Acceptance:* [ ] Find bar present in every native PDF view; [ ] highlights all matches with count + next/prev + clear; [ ] Cmd/Ctrl+F + Esc work; [ ] status/citation highlights still render; [ ] vitest for the match/navigation logic.

### R43 — Per-reference chat grounded in fetched full text *(adversarial loop; honesty-gated)*
- *Change:* add a reference full-text retrieval path — resolve the ref's DOI → OA location via Unpaywall/OpenAlex `best_oa_location`/arXiv (reuse existing fetchers in `src/refchecker/utils` + `backend/pdf_convert.py`), download the PDF, extract text (PyMuPDF), cache per identity (DOI/arXiv/title) with TTL + soft-fail + bounded concurrency. Extend the per-ref chat endpoint so it returns `grounding=<full_text>, source='pdf'` when available, else `grounding=<tldr>, source='tldr'`. `ArticleAssistant.jsx`: on opening chat for a ref, trigger retrieval ("Fetching full text…") and switch the banner to "grounded in the full text" vs the existing TL;DR-only disclaimer. HONESTY: only real fetched text; if retrieval fails, keep the current TL;DR disclaimer verbatim — never fabricate.
- *Acceptance:* [ ] OA-available ref → chat grounded in the fetched full text with the matching banner; [ ] no-OA ref → existing TL;DR-only disclaimer unchanged; [ ] retrieval cached/soft-fail/bounded; [ ] backend test (OA hit → full-text grounding, miss → tldr) + vitest for the banner states.

### R44 — Distinct "Remove from library" control
- *Change:* in `AdditionalInfoBar.jsx`, give the in-library remove a clear VISIBLE affordance ("Remove from library" text or a library-minus icon + tooltip) placed immediately next to the "✓ In library" pill, visually distinct from the `ReferenceActionsBar.jsx` "Remove" (which removes from the check — optionally relabel that "Remove from list"). Keep the honest post-remove "Removed" pill. Align to the R33 button system.
- *Acceptance:* [ ] in-library pill has an adjacent, clearly-labeled control that calls `removeFromLibrary` only; [ ] the list/check "Remove" stays distinct and unaffected; [ ] vitest that the two removes invoke different handlers.

### R45 — Share video count parity + play-once-then-freeze *(merge into R23/R24)*
- *Change:* feed `ShareModal`/`ShareAnimationCanvas` the SAME inputs `StatsSection` uses (style-aware filtered references + identical `isComplete`), or pass `StatsSection.summaryCounts` straight through, so the video numbers equal the Summary bar for that article. Implement play-once-then-freeze: clamp `t=min(1,…)`, `cancelAnimationFrame` at `t===1`, keep the canvas mounted (drop the `&& animActive` gate / `ANIM_PLAY_MS` unmount), re-key on modal open so close+reopen replays once then holds.
- *Acceptance:* [ ] video counts equal `StatsSection.summaryCounts` for the same article; [ ] plays once then holds the final frame; [ ] close+reopen replays once then holds; [ ] vitest comparing share counts to StatsSection counts + the freeze/remount behavior.

---

## 9. Batch 4 — additional requests (R46–R48)

| ID | Area | Requirement | Current state (file ref) | Severity |
|---|---|---|---|---|
| **R46** | Support | Email-support must open the system mail composer with both recipients (To+Cc), not a blank page | **FIXED THIS TURN** — `SupportMenu.jsx` email was a bare `<a href="mailto:">` (blank in webview/new tab); now routes via `openExternal` (Tauri) / `window.location.href` (web) | **P1 · DONE (uncommitted)** |
| **R47** | Cost telemetry | Track ALL spent tokens + $ for every LLM operation in real-time, live-updating the Summary badge | `LLMUsageBadge.jsx` already polls `getLLMUsage(checkId)` ~3s + aggregates flows, but badge shows `$0.000` with "Halluc checked 3" → backend `usage_tracker` not recording usage for those flows | **P1 · PARTIAL** |
| **R48** | Count parity | Summary badge, report card, AND exported file must show identical counts + citation-health %; fix disrupted export logo | App itself disagrees: badge **30 verified/8 warn/82%** vs report **29/9/80%**; export inherits the mismatch + logo disrupted. Same root as R16/R45; **reopens Q5/U5** | **P1 · BROKEN** |

### R46 — Support mailto *(done this turn, pending commit + Tauri allowlist check)*
- *Done:* `web-ui/src/components/common/SupportMenu.jsx` — Email button is now a `<button>` calling `emailSupport()`: `openExternal(MAILTO_URL)` in Tauri, else `window.location.href = MAILTO_URL`. Both emails preserved (To=ariorad…, Cc=mark…).
- *Acceptance:* [ ] clicking Email opens the OS mail composer with both recipients (verify on web AND Tauri); [ ] no blank page/tab; [ ] confirm the Tauri shell/opener allowlist permits the `mailto:` scheme (add it if missing); [ ] vitest that the button invokes `openExternal`/`window.location` (not a bare anchor).

### R47 — Real-time token + $ telemetry for every LLM flow *(adversarial loop; schedule after R04)*
- *Change:* the FE badge infra exists — the gap is backend accounting. Audit EVERY LLM call site and record response usage (prompt+completion tokens) into `backend/usage_tracker.py` keyed by `(check_id, flow)`, with cost from a per-model price table: `src/refchecker/llm/hallucination_verifier.py` (coordinate with R04 — both edit this file), `backend/article_chat.py` (chat + **summarize** — newer, likely untracked), the extract/verify/suggest/graph/reverify/context paths in `backend/refchecker_wrapper.py`, and any LLM AI-detection backend. Parse each provider's usage (OpenAI `usage`, Anthropic `usage`, Google `usageMetadata`). Ensure `getLLMUsage` returns the live totals; have `LLMUsageBadge.jsx` keep polling during follow-ups (chat/summarize) so it ticks up. HONESTY: report real provider-returned token counts/cost only; show `$0.000` only when nothing was actually spent.
- *Acceptance:* [ ] after a real check the badge shows non-zero tok + $ equal to the sum of per-flow usage; [ ] the screenshot case (hallucination checked 3 → currently $0) now reports its real cost; [ ] chat + summarize spend is added live; [ ] hover breakdown shows each flow's real tokens/cost; [ ] backend test that `usage_tracker` accumulates per flow and `getLLMUsage` returns totals (+ a regression test for the previously-$0 hallucination path).

### R48 — One canonical count/health across badge + report + export; fix logo *(reopens Q5/U5; ties to R16/R45)*
- *Change:* establish a SINGLE canonical summary (the `buildReferenceSummary` style-aware result) and consume it in ALL THREE places — the Summary badge, the `StatsSection` report card, and `backend/export.py` serialization — so verified/warnings/errors/unverified + citation-health % match exactly (the off-by-one is a verified-vs-warning boundary disagreement: 30/8/82% vs 29/9/80%). Pass the FE-computed summary through to export (or compute identically server-side via shared logic). Fix the disrupted RefChecker logo asset in exports (path/embedding/aspect across html/md/pdf). The prior "Q5/U5 export parity DONE" was incorrect — this supersedes it.
- *Acceptance:* [ ] badge, report card, and exported HTML/MD/PDF show identical counts + health % for the same check; [ ] the verified/warning boundary is consistent everywhere (no off-by-one); [ ] logo renders correctly in every export format; [ ] backend test asserting export counts == `buildReferenceSummary`; [ ] vitest tying the badge to the report card (extends R16).

---

## 10. Batch 5 — gap-closure from completeness audit (R49–R53)

A full sweep of every request across the chat (79 items) found 74 fully covered; these 5 sub-requirements were folded away and are now tracked explicitly.

| ID | Area | Requirement | Why it was a gap | Severity |
|---|---|---|---|---|
| **R49** | Gap-finder | The "did you miss these / N works you might add" panel must be COLLAPSIBLE after results generate | Only a stray optional "C3 persisted collapse" with no R-id/acceptance | **P2 · PARTIAL** |
| **R50** | Similar papers | Redo the FRONTEND/visual DESIGN of the "Similar Cites & Refs" tab to match the provided attachment (not just function) | Backlog only had functional items (R08/R20/R25/J4); no visual redesign | **P1 · MISSING** |
| **R51** | Share video | Remove the walkthrough button; the video must live ONLY in the download banner and play once each time the banner opens | R23/R45 cover play-once-freeze but not walkthrough-button removal nor banner-only placement | **P1 · PARTIAL** |
| **R52** | Buttons | Click-state stability: no size/shape change or layout shift when clicked (re-check↔spinner width jump, expand/collapse, tab switch) | R33 covers static styling only, not active-state stability | **P1 · PARTIAL** |
| **R53** | Author UI | Author popover shows a clickable ORCID **page link** AND the visible ORCID **number** together, when resolvable | R36 only populates `orcidUrl`; the link+number pair isn't an asserted acceptance | **P2 · PARTIAL** |

### R49 — Gap-finder results panel collapsible *(verify current state first)*
- *Change:* `GapFinder.jsx` — wrap the generated results in a collapsible section with a persistent toggle (localStorage), so after generation the user can collapse/expand. The latest screenshot shows a "▸ show" affordance may already exist — confirm whether it already collapses post-generation; if so mark done, else add persisted collapse.
- *Acceptance:* [ ] results collapse/expand after generation; [ ] state persists across re-renders; [ ] vitest for the toggle.

### R50 — "Similar Cites & Refs" tab visual redesign *(needs the design attachment; route through the UX loop)*
- *Change:* `SimilarPapersPanel.jsx` — restyle the panel (layout, result cards, spacing, graph placement) to match the user's provided design attachment, using the app design tokens + the approved `BUTTON_DESIGN.md`/R33 system. Capture the target in a design spec reviewed by the designer→UX loop before implementing.
- *Acceptance:* [ ] panel matches the approved design spec; [ ] consistent with the app's native-mac language; [ ] UX-reviewer approval; [ ] snapshot/vitest.
- *Blocker:* the original design attachment isn't in the repo — **ask the user to re-share it** for fidelity.

### R51 — Remove walkthrough button; video only in the download banner *(extends R23)*
- *Change:* grep for the "walkthrough" control and remove it; ensure the generated video renders ONLY inside the download-banner component (not in the share-popup body and not as a separate expandable), playing once each time the banner opens (reuse R23/R45 play-once-then-freeze + remount-on-open).
- *Acceptance:* [ ] no walkthrough button anywhere; [ ] video appears only in the download banner; [ ] plays once per banner open; [ ] vitest that the walkthrough control is gone and the video mounts only in the banner.

### R52 — Button click-state stability *(extends R33; per the approved BUTTON_DESIGN.md)*
- *Change:* implement the `BUTTON_DESIGN.md` "click-state stability" section — reserve min-width for label↔"checking…"↔spinner swaps, keep radius/height constant across states, a non-reflowing segmented-tab indicator, fixed-header expand/collapse. Apply to the re-check pills (`CitationIntegrity.jsx`/`RetractionCheck.jsx`), the split-button, the assistant tabs/Send, the AI-likelihood pill, and the gap-finder header.
- *Acceptance:* [ ] re-check↔checking↔spinner causes no width change; [ ] expand/collapse, tab switch, and menu open cause no layout shift or shape change; [ ] vitest asserting stable measured dimensions across states.

### R53 — ORCID link + visible number pair in the author popover *(extends R36)*
- *Change:* in `AuthorChip` (`ReferenceCard.jsx` ~1605 / 1654-1661 / 1750-1772 / 1422) render an ORCID row: the iD logo linking to `https://orcid.org/<id>` AND the raw ORCID number as visible text, sourced from `profile?.orcid || e?.orcid`.
- *Acceptance:* [ ] popover shows a clickable ORCID page link + the visible ORCID number when available; [ ] absent (no fabrication) when unresolved; [ ] vitest.

---

## 11. Batch 6 — regression introduced by R04 (R54)

| ID | Area | Requirement | Current state (file ref) | Severity |
|---|---|---|---|---|
| **R54** | Resource leak | The per-request `ProgressRefChecker._ha_executor` (8-worker pool added in R04) must be shut down after each check; `close()` exists but is never called | `close()` at `refchecker_wrapper.py:1296` (`_ha_executor.shutdown(wait=False)`); the only construction site `main.py:2145` runs `await checker.check_paper(...)` (`:2174`) with NO try/finally → every request leaks 8 daemon threads | **P1 · BROKEN** |

### R54 — Close the hallucination executor per request *(apply AFTER R05 commits main.py)*
- *Change:* wrap the `checker = ProgressRefChecker(...)` / `await checker.check_paper(...)` block in `backend/main.py` (~`:2145`–`:2174`) in `try/finally`, calling `checker.close()` in the `finally` AFTER all progress/result emission, guarded best-effort (`fn = getattr(checker, 'close', None); fn and fn()`; `close()` is already idempotent via `getattr(self,'_ha_executor',None)`). Grep `ProgressRefChecker(` to confirm `main.py:2145` is the only construction site (it is) — if any other appears, give it the same treatment.
- *Acceptance:* [ ] after a check completes, `_ha_executor` is shut down (submitting to it raises `RuntimeError`) or `close()` is provably invoked; [ ] no `ProgressRefChecker` construction path leaves the executor open; [ ] pytest under `tests/unit/` (extend `test_hallucination_timeout.py`) asserting shutdown-after-check; [ ] no regression to R04's timeout behavior.
- *Status:* ✅ DONE — committed `b1ae210` (close() in the existing run_check `finally`, guarded via `locals().get('checker')`; 9/9 tests green).

---

## 12. Batch 7 — pre-existing lint latent bug (R55)

| ID | Area | Requirement | Current state (file ref) | Severity |
|---|---|---|---|---|
| **R55** | Lint / hooks | Fix `react-hooks/immutability`: `jumpToPage` accessed before it is declared in `ThumbnailOverlay` | `StatusSection.jsx` — used in the Find-highlight `setTimeout` (line ~199) before its `const` declaration (line ~228); pre-existing on `main`, unrelated to S6/S7 | **P2 · BROKEN (lint)** |

### R55 — Hoist `jumpToPage` above the Find-highlight effect *(apply AFTER the viewer workflow frees StatusSection.jsx; line numbers shift after S7)*
- *Change:* in `web-ui/src/components/MainPanel/StatusSection.jsx` `ThumbnailOverlay`, hoist `jumpToPage` (and any helper it depends on) above the Find-highlight `useEffect` that references it, OR wrap it in a `useCallback` declared before that effect and add it to the effect's dependency array. No behavior change. Re-locate by symbol (not the stale line numbers) since S7 reflows the file.
- *Verify:* `cd web-ui && npx eslint src/components/MainPanel/StatusSection.jsx` → 0 errors; `npx vitest run src/components/MainPanel/StatusSection.test.jsx` → green. (any pytest via `/opt/homebrew/bin/python3`.)
- *Acceptance:* [ ] eslint reports 0 errors for StatusSection.jsx; [ ] StatusSection.test.jsx stays green; [ ] no unrelated behavior change. Fold into the S8 CI-gate finalization (the workflow's `npm run lint` will surface it).
- *Status:* ✅ RESOLVED — S7's reflow now declares `jumpToPage` (line 181) before its use (line 206); `npx eslint src` reports **0 errors** and vitest is 199/199 (landed in `ea1b84d`).

---

## Progress log (branch `fix/remaining-p0-viewers`)

P0, the viewer stream, AND the button spec are committed; branch HEAD CI-green (eslint 0 errors, vitest 231/231, build ok, pytest 1342 passed/1 skipped; `cargo` blocked only by the packaged-sidecar prereq — built in CI, no Rust source touched).

**✅ DONE & committed (verified — tests green):**

| Item(s) | Commit |
|---|---|
| R01 published-date honesty | `d2cb4d8` |
| R04 LLM hang + R54 executor-leak | `da94935`, `b1ae210` |
| R46 support mailto | `9e3715d` |
| R05 share 500 | `c5ccf44` |
| R14 status-color map | `98a1ec0` |
| R02/R03 native-PDF view + AI-sentence buttons | `8e2df73` |
| R28/R29/R30 in-PDF jump + opacity + refId | `303798b` |
| R12/R13/R31 focus-zoom + sentence span + pinch | `e4dabd0` |
| R55 lint (jumpToPage) + S8 cleanup | `ea1b84d` |
| R33/R52 unified button system + click-state stability | `ee29ed6` |
| R44 distinct "Remove from library" | `85a35e6` |
| R06/R07 AS-CITED DOI in suggested correction | `7ace2fa` |
| R16/R25 Summary badges agree + similar-papers isolation | `1a1b00d` |
| R20/R39/R08 gap-finder/similar verify + provenance + common-cites viz | `4de6f78` |
| R09/R41/R11/R36/R53/R37 author popover: et-al expand, pin/scroll, ORCID link+number, badge | `ef28b08` |
| R10 ID-less author name/title resolution (non-fabricating) | `8dccf8b` |
| R15 inline parser: alphabetic + first/last-mentioned schemes | `d8dd25f` |
| R17/R18/R19 add-to-list: dedup guard → renumbered list → tracked PDF/export diff | `2cd160c`,`a9285ac`,`e17efcb` |
| R21/R22/R35 cross-source enrichment backfill + clickable count tiles | `92b9317` |
| R47 real-time token + $ telemetry for every LLM flow | `deaa087` |
| R48 one canonical count/health across badge + report + export; logo | `bff1cd6` |

Batch-F gate green (`b0b99ee`): lint 0 errors, vitest pass, build ok, pytest pass.

| R23/R45/R51/R24 share video real counts + freeze + banner-only + stats-page video | `515a1f3` |
| R42 native-PDF find/search (Cmd/Ctrl+F) | `6d24825` |
| R43 per-ref chat grounded in fetched full text (TL;DR fallback) | `9427ad4` |

Batch-G gate green (`9f0c3a7`): lint 0 errors, vitest pass, build ok, pytest pass.

| R26/R27 auth/teams: team-scoped shared checks + collaborate + enable-from-app hot-reload | `71a9026` |
| R34 separate model for Chat-with-PDF vs Summarize | `0563505` |
| R32/R38/R49 radial DOIs clickable + library 3D polish + gap-finder collapse | `88079e5` |

Batch-H gate green (`642a1fc`, salvaged after a stalled gate agent): lint 0 errors, vitest **340/340**, build ok, pytest **1459** passed/1 skipped.

**⬜ QUEUED (serialized):** J (R56/R57 CLI parity + help/guides); K (R58 bump 0.9.19+3.2.0, R59 push origin + R40 full CI, R60 release tags). R50 (Similar-papers redesign) deferred — needs the user's design attachment.

**Tally:** 53 of the R01–R55 items DONE (all except R50 deferred + R40 CI-gate); remaining: R40 (K), R50 (deferred), R56–R60 (J/K).

---

## 13. Batch J + K — access-method parity, help/guides, push, release (R56–R60)

User decisions (locked): push `fix/remaining-p0-viewers` to **origin** (`ArioMoniri/refchecker`), **no PR**; release **desktop 0.9.18→0.9.19** AND **PyPI/CLI 3.1.0→3.2.0**; **I push the tags autonomously** once CI is green; **expose all CLI-applicable features + full --help/guides**. Runs only AFTER B–H land and the §6 DoD passes.

### R56 — CLI feature parity *(Batch J)*
- *Change:* extend `backend/cli.py` (and the entry in `src/refchecker`/`run_refchecker.py`) so the CLI exposes every CLI-applicable backend capability with flags + structured output + `--help`: hallucination check (`--check-hallucinations` + provider/model/key), inline-citation numbering/ordering check (`--check-citation-order`), retraction check (`--check-retractions`), gap-finder / co-citation suggestions (`--suggest-missing`), cross-source enrichment backfill (on by default; `--no-enrich` to opt out), AI-generated-text detection (`--ai-detection [local|api]` + consent). Mirror the web/API defaults; emit JSON (`--json`) and a human report. UI-only features (native PDF viewers, graphs, share video, author hover) are explicitly documented as web/desktop-only.
- *Acceptance:* [ ] each new flag works end-to-end against a sample paper; [ ] `--help` documents them; [ ] `--json` schema covers the new fields; [ ] pytest (`/opt/homebrew/bin/python3`) for the CLI arg wiring + at least one feature path; [ ] no regression to existing CLI behavior.

### R57 — Help & guides across all access methods *(Batch J)*
- *Change:* update `README.md` + `docs/` with a feature matrix (web / desktop / CLI / API) and guides for the new capabilities: auth/Teams + presence (R26/R27), unified native-PDF viewers + find + in-PDF links (R02/R28/R42), share video, enrichment/author metrics, inline-citation parser, add-to-reference-list, similar Cites&Refs, AI detection, and the live token/$ telemetry (R47). Add in-app help/links (the Support menu already exists) and CLI usage examples. Keep honesty notes (no-fabrication, opt-in AI detection, single-user vs multi-user).
- *Acceptance:* [ ] README feature matrix + per-feature guide; [ ] CLI examples match `--help`; [ ] desktop README/updater + multi-user setup guide current; [ ] links valid.

### R58 — Version bump + changelog *(Batch K)*
- *Change:* `src/refchecker/__version__.py` 3.1.0→**3.2.0**; `tauri-app/package.json` 0.9.18→**0.9.19** (tauri.conf reads it); refresh the README/desktop changelog with the R01–R57 highlights. Leave `web-ui/package.json` (1.0.0) unless the release flow requires it.
- *Acceptance:* [ ] versions consistent where they must be; [ ] changelog lists the shipped fixes/features; [ ] `pyproject.toml` resolves 3.2.0.

### R59 — Push branch + full CI green (R40) *(Batch K)*
- *Change:* run the full gate locally — `cd web-ui && npm run lint && npx vitest run && npm run build`; `/opt/homebrew/bin/python3 -m pytest tests/unit`; note the Tauri `cargo` sidecar prereq (the missing `binaries/refchecker-server-*` is built by `tauri-app/scripts/build-sidecar.sh` in CI, so it's a local-only gap, not a release blocker — `desktop-release.yml` builds it). Then `git push origin fix/remaining-p0-viewers` (no PR).
- *Acceptance:* [ ] local gate green (FE + pytest); [ ] branch pushed to origin; [ ] GitHub Actions `test.yml` green on the pushed branch.

### R60 — Cut the release (autonomous tag push) *(Batch K — LAST)*
- *Change:* after R59 is green, push the release tags so CI publishes: the desktop tag (per `desktop-release.yml`'s trigger, e.g. `desktop-v0.9.19`) → builds dmg + updater (signed via `refchecker-updater.key`); the PyPI tag (per `release.yml`'s trigger, e.g. `v3.2.0`) → publishes the Python package/CLI. Confirm the exact tag patterns from the workflow `on:` triggers before tagging.
- *Acceptance:* [ ] tag patterns verified against the workflow triggers; [ ] tags pushed; [ ] `desktop-release.yml` + `release.yml` runs succeed (dmg/updater + PyPI published); [ ] release notes attached. Requires the repo's configured secrets (PyPI token, signing/updater key) — surfaced to the user if any run fails on a missing secret.
