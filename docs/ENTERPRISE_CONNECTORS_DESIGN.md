# Enterprise connectors — design + credential-free first slices

> These four enterprise items (from the High/L–M list) require third-party
> OAuth or a multi-tenant backend that a single-user desktop app does not have.
> Shipping a mock "live sync" or a fake "team feed" would violate the project's
> hard no-placeholder/no-fake-data rule. So each is delivered here as a **real
> design** plus the **largest slice that can carry real data with no credentials**
> — and is NOT surfaced in-product as if it were live until the real backend exists.

---

## 1. Zotero & Mendeley live sync  (High / L)
**Goal:** "Check with RefChecker" on a Zotero/Mendeley collection; write verification status back.

**Why not now:** Zotero Web API needs a user API key + libraryID; Mendeley needs OAuth2. Writing
status back needs write scope + per-item PATCH. No credentials → no real data.

**Real credential-free first slice (buildable now):**
- **Zotero/Mendeley export import**: both export standard **BibTeX/RIS**. RefChecker already
  ingests `.bib`. Add **RIS import** + a "drop your Zotero export here" path → verify → and an
  **annotated BibTeX/RIS export** that writes the verification verdict + corrected fields into
  each entry's `note`/`annote` field. The user re-imports that into Zotero/Mendeley manually.
  This is the whole value (verify a library, get status back) with zero credentials.

**Full design:** `connectors/zotero.py` adapter behind a `BibStoreConnector` ABC
(`pull(collection) -> [entries]`, `push(entry_id, status)`); API key stored via the existing
`useKeyStore`; status written to a RefChecker tag + an `extra` line. Mendeley = same ABC, OAuth2
device-code flow. Gate behind a Settings "Connectors" panel; never auto-sync.

---

## 2. Overleaf & Google Docs integration  (High / L)
**Goal:** verify the bibliography from inside the editor; apply fixes inline.

**Why not now:** Overleaf has **no public write API** (only git/Dropbox bridge on paid tiers);
Google Docs needs OAuth + a Workspace add-on. No real in-editor write without those.

**Real credential-free first slice (buildable now):**
- **`.tex` + `.bib` round-trip** is already supported for input. Add a **"corrected `.bib`"
  export** (one-click: apply all confirmed corrections → download a drop-in `references.bib`).
  Overleaf users replace their file; the fix is real, just not auto-pushed.
- A **Google Docs paste target**: export the report as clean Markdown (already shipped) which
  pastes into Docs with structure intact.

**Full design:** an Overleaf **git-bridge** sync (paid Overleaf feature) reading `main.tex`'s
`\bibliography`, and a Google Docs **Apps Script add-on** calling a hosted RefChecker API. Both
need the hosted/multi-tenant backend in §4-adjacent work.

---

## 3. Team mode — real-time collaborative verification  (High / L)
**Goal:** collaborative, real-time verification with per-fix attribution.

**Why not now:** needs multi-user auth, a shared server, presence/websync (CRDT), and an identity
per fix. A single-user desktop app has exactly one user; a "team feed" here would be fabricated.

**Real credential-free first slice (buildable now):**
- **Per-fix attribution locally**: stamp each applied correction with `applied_by` (the OS user)
  + timestamp in the check history, and show it in the Corrections view + export. This is the
  data model team mode needs, captured truthfully for the single local user today.
- **Hand-off export/import**: a check (with its applied-fix log) already serializes; add a
  `.refcheck.json` export/import so two people can pass a verification session by file.

**Full design:** a hosted workspace (org → project → check), WebSocket presence, a CRDT
(Yjs/Automerge) over the corrections list, and an auth provider. This is a server product, tracked
separately — not emulated in the desktop client.

---

## 4. Journal/conference pre-submission gate  (High / M)
**Goal:** branded report, editor dashboard, credibility badge.

**Status:** the **branded report** and **credibility badge** are effectively DONE via shipped work —
the multi-format report (`backend/export.py`) is the branded artifact, and the **citation-health
score + `/badge.svg`** is the credibility badge. What remains server-side is the **editor
dashboard** (multi-submission, multi-tenant) — same hosted-backend dependency as §3.

**Real credential-free first slice (DONE / buildable now):**
- Branded PDF/HTML report with the health badge + verdict + issue prioritization (shipped).
- A **"submission packet"** export preset (report + corrected `.bib`) for authors to attach to a
  submission. Cheap to add on top of the existing export checkboxes.

---

## Honesty summary
| Item | Real slice shippable now | Needs hosted/OAuth backend |
|---|---|---|
| Zotero/Mendeley | RIS import + annotated BibTeX/RIS export | live API sync + write-back |
| Overleaf/GDocs | corrected `.bib` export + Markdown paste | in-editor add-on/git bridge |
| Team mode | local per-fix attribution + session hand-off file | real-time multi-user server |
| Pre-submission gate | branded report + health badge (shipped) + submission packet | editor dashboard |

None of the un-built halves are surfaced in-product as working. The credential-free slices above
are the next real, no-fake increments and are added to the execution queue.
