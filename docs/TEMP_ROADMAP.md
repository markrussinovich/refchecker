# RefChecker — Temporary Delivery Roadmap

> Working tracker for the outstanding multi-batch feature request. Step-by-step,
> DoD + TDD per item, built with workflow/subagent loops (fullstack dev →
> watchdog → reviewer → safety). **Hard constraint: zero placeholder / fake /
> demo / generated / test data in any shipped surface, including AI detection.**
> Status legend: ✅ done · 🟡 in progress · ⬜ queued · 🔵 design-only (external
> dependency, cannot ship real data this cycle).

_Last updated: build cycle after v0.8.2._

---

## A. Shipped (v0.7.96 → v0.8.2, verified, published as latest)

| # | Item | Status |
|---|------|--------|
| 27 | Author hover card redesign (avatar, metric chips, recent work, profile links) | ✅ |
| 35 | Per-page AI sentence plots (GPTZero-style 3-dot confidence + per-page top AI/Human) | ✅ |
| 36 | Native-PDF highlighting of AI-flagged paragraphs (PyMuPDF locate → overlay + downloadable annotated PDF) | ✅ |
| — | Export HTML 500 fix (read `check["results"]`, tolerate JSON-string ai_detection) | ✅ (live in v0.8.1) |
| — | Author-match tolerance (Levenshtein surname + 1-omission subset) | ✅ |
| — | Token/cost tracking correctness (per-flow, lifetime-reset bug fixed) | ✅ |
| — | Safety audit: 4 strict reviewers, zero placeholder/fake-data findings | ✅ |
| — | AI-detection panel + top sentences collapsible | ✅ |
| — | CLI ASCII banner modernization + environment/help sections | ✅ |

---

## B. This cycle — concrete, fully buildable now (real data only)

### B1. Export & Report overhaul  ✅  **(done — pending review-loop sign-off)**
- **What**: `/export/{id}/html` 500 → support **PDF · HTML · MD · DOCX**; include/exclude **checkboxes** per section; report **with / without corrections**; GPTZero-style, LLM-ingestible layout; **downweight minor year-mismatch warnings** (Semantic Scholar noise), elevate errors/hallucinations; single **and** batch report (one-page overall + each paper separately).
- **DoD**: every format downloads without 500 on a real check; MD is plain + machine-parseable; PDF renders via bundled PyMuPDF (no new heavy dep); DOCX is a valid OOXML zip (stdlib only); corrections toggle changes output; year-only warnings sink below errors; batch report aggregates real per-paper rows.
- **TDD**: `tests/` unit asserting each serializer returns non-empty for a real check fixture, section toggles add/remove sections, corrections toggle changes content, minor-year warnings reclassified to "minor".
- **Files**: `backend/export.py`, `backend/main.py` (route), `web-ui/.../ShareModal.jsx`.

### B2. Clickable inline-citation contexts → native-doc jump + highlight  ✅  (#37)
- Citation numbers in the context tab become links → open the native PDF view and highlight that citation's paragraph (reuse `/api/preview/{id}/locate`, `span_type:'citation'`); AI color-coding + hover data when detection on. **Builds directly on shipped #36.**

### B3. Find-shows-match-location  ✅
- Native overlay find now locates the query on the page (PyMuPDF) and highlights the rects (yellow) + jumps to the page — not just an estimated page.
- _original:_
- Search currently jumps to a page; surface the matched text location (DocumentViewer already does in-text; extend to the PDF page overlay via `locate`).

### B4. Share overhaul  🟡 (mostly done)
- ✅ export checkboxes (section include/exclude) · ✅ with/without corrections · ✅ HTML/PDF/MD/DOCX · ✅ Share button moved to rightmost of outline (right of thumbnail) · ✅ batch share (overview + each paper).
- ⬜ remaining: html-to-video option w/ preview; Quick-link anonymous-host sidecar (desktop hosting limit — gist publish is the real working path).
- _original note:_
- Share on **batches** + other import methods; **Share button to the right of the article thumbnail**; **html-to-video** export option shown with preview in the share page; **Quick-link** anonymous-host sidecar (zero-config links, no domain/token) alongside the existing GitHub publish.

### B5. Seen-References radial / chord graph view  ✅
- 3D / **Radial** toggle in `GraphLibraryView`; pure-SVG chord layout (nodes on a circle grouped by status, Bézier chords through centre, hover spotlights chords), same data, no new dep.
- _original:_
- Add a radial/chord layout alternative to the existing 3D force graph (`GraphLibraryView.jsx`), real library edges only.

### B6. anime.js micro-interactions  ✅
- `animejs@3.2.2`; HealthBadge score count-up on change (e.g. after "apply all fixes"), `prefers-reduced-motion` respected.
- _original:_
- Add `animejs` for tasteful, reduced-motion-respecting transitions (result reveal, chips, graph) — app or README, only where it improves clarity.

### B7. Better CLI view  ⬜
- Further polish banner/help (already modernized); align with theme; richer `--help`.

### B8. Retraction & citation-lineage tracking  ✅  (enterprise Med/M — **real data**)
- `backend/retraction.py` (OpenAlex `is_retracted`, injectable fetch, 4 tests) + `GET /api/check/{id}/retractions` + on-demand `RetractionCheck` UI banner. No DOI → "no_doi", not indexed → "unknown", never a fabricated retraction.
- _original:_
- Flag cited papers later retracted using **real** signals (Crossref `update-to`/relation, OpenAlex `is_retracted`). No fabricated retractions.

### B9. Citation-health score + shareable badge  ✅  (enterprise Med/S — **real data**)
- Same formula as the in-app HealthBadge (no divergence). In all 4 export formats + `GET /api/check/{id}/health` (JSON) + `GET /api/check/{id}/badge.svg` (embeddable SVG). **Bonus:** orphan/uncited-reference detector (honest guard: only fires when inline extraction ran).
- _original:_
- Score computed deterministically from a check's actual verified/warning/error/hallucinated counts; SVG badge endpoint.

### B10. No-placeholder-data safety loop  🟡 (continuous)
- Workflow: safety + fullstack + strict-reviewer subagents audit every new surface; loop until clean.

---

## C. Enterprise list (new batch) — design + tractable slices

| Pri/Size | Item | Plan |
|----------|------|------|
| High / M | **Reference suggestions / "did you miss these?"** gap-finder | 🔵→⬜ Real: use existing source APIs (Semantic Scholar/OpenAlex related-works) on the paper's own references to surface plausibly-missing citations. Tractable as a real feature. |
| High / M | **Interactive onboarding + field-specific guides** (medical→PMID, ML→arXiv) | ✅ `FieldGuide.jsx` — dismissible, real per-discipline guidance (ML/CS, Medicine, Physics, Social science), mounted on the input screen. |
| Med / M | Retraction & citation-lineage tracking | ⬜ B8 above. |
| Med / S | Citation-health score + badge | ⬜ B9 above. |
| High / M | **Journal/conference pre-submission gate** (branded report, badge) | 🔵 Design: branded variant of B1 report + a credibility badge (B9). Editor dashboard is multi-tenant server work — design only. |
| High / L | **Zotero & Mendeley live sync** | 🔵 Design only: requires Zotero Web API key / Mendeley OAuth. No real sync without user credentials → would be fake data. Ship a documented connector design + a manual Zotero `.bib`/collection import path (real, no creds) as the first slice. |
| High / L | **Overleaf & Google Docs integration** | 🔵 Design only: Overleaf has no public write API; Google Docs needs OAuth. First real slice = `.tex`/`.bib` round-trip already supported; editor plugin is design-only. |
| High / L | **Team mode (real-time collaborative)** | 🔵 Design only: needs a multi-user backend/auth/websync. Single-user desktop app cannot deliver real collab data this cycle. Design doc + per-fix attribution schema. |

> Honesty note: items marked 🔵 are **not** shipped as fake/demo integrations.
> Faking a Zotero sync or a team feed would violate the no-placeholder-data
> constraint. They get a real design + the largest credential-free slice that
> can carry real data, and are flagged clearly in-product as "design preview"
> only if surfaced at all.

---

## C2. Validated ideas from the persona discovery workflow (#31, real-data)
Cheap high-value wins surfaced + cross-validated by researcher/head-of-product/fullstack agents:
- **Orphan / uncited-reference detector** (S/high) — bibliography entry with no `citation_contexts` and not inline-cited → flag. Uses data we already have.
- **Apply-all-corrections export to BibTeX / RIS / LaTeX** (S/high) — builds on `corrected_reference`.
- **Per-reference health badges** (retraction / OA / predatory-venue) (S/high) — pairs with #39/#40.
- **Venue-legitimacy signal** via DOAJ (real API).
- **Manuscript re-check diff** (what changed since last version) (S/med).
- **Claim-support verification** (does the cited paper back the sentence?) (L/high — bigger, LLM-assisted).
- Confirms existing roadmap items #39 retraction, #40 health score, #41 gap-finder, and #37 jump-to-context (already shipped).

## D. Execution order (this + next cycles)
1. **B1 Export/Report** (active — fixes a live user-facing error). 
2. B2 citation links → B3 find-location (share the `locate` plumbing).
3. B4 share overhaul.
4. B9 citation-health + B8 retraction (real-data enterprise wins).
5. B5 radial graph, B6 anime.js, B7 CLI polish.
6. C gap-finder + onboarding (real slices); 🔵 designs documented.
7. B10 safety loop runs after every batch; release cut only when asked.
