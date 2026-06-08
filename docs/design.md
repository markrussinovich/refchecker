# RefChecker — Export Theme Design Spec

This document **governs the visual design of every exported report** produced by
`backend/export.py` (HTML, PDF, Markdown, Word/DOCX). The goal is that a report a
researcher shares is recognisably the *same product* as the RefChecker app, not a
generic template. When you change a colour, a heading style, or a status glyph in
`export.py`, change it here first — this file is the source of truth.

> **Real-data only.** The theme styles whatever the verification produced. It
> never adds illustrative numbers, sample references, or placeholder verdicts. A
> section with no data is omitted, not filled.

---

## 1. Design read

RefChecker is a **calm, Mac-native research tool** — the visual language is the
ChatGPT-desktop / macOS lineage the app already uses (`web-ui/src/index.css`):
quiet neutral surfaces, a single confident teal-green accent, hairline borders,
soft card shadows, and a system font stack. It is the opposite of a marketing
page: no gradients, no hero imagery, no decorative colour. Colour is **functional
only** — it encodes verification status (the traffic-light language) and the one
brand accent. A report should feel like a trustworthy lab instrument's printout.

Explicitly **rejected** (anti-slop guardrails):

- No purple/indigo gradient headers or "AI-app" violet washes.
- No Inter / Geneva web-default font — the app is Mac-native, so are the exports.
- No invented accent. The accent is `#10a37f`, not a stock `#6366f1` or `#22c55e`.
- No emoji confetti or decorative icons; the only glyphs are the status legend.

---

## 2. Colour tokens

These are the **app's real tokens** lifted verbatim from `web-ui/src/index.css`.
Light is the default (and the print/PDF target); dark mirrors the app shell and
engages via `prefers-color-scheme` in the HTML export. PDF and DOCX always render
on white paper, so they use the **light** column only.

### Brand & surface

| Token            | Light (default) | Dark (app shell) | Role                              |
| ---------------- | --------------- | ---------------- | --------------------------------- |
| `accent`         | `#10a37f`       | `#10a37f`        | Brand teal-green; verified/success |
| `accent-soft`    | `rgba(16,163,127,.12)` | `rgba(16,163,127,.18)` | accent tint fills          |
| `bg`             | `#f7f7f8`       | `#212121`        | page background                   |
| `card`           | `#ffffff`       | `#2f2f2f`        | card / surface                    |
| `border`         | `#e5e5e5`       | `#444444`        | hairline dividers & card edges    |
| `track`          | `#ececf1`       | `#424242`        | progress-bar / donut track        |
| `fg`             | `#0d0d0d`       | `#ececec`        | primary text                      |
| `fg-2`           | `#676767`       | `#b4b4b4`        | secondary text / section labels   |
| `muted`          | `#8e8ea0`       | `#8b8b96`        | metadata, captions                |
| `link`           | `#2563eb`       | `#60a5fa`        | source links                      |

### Status (the traffic-light language)

The same status colours the in-app `ReferenceCard` uses. **Hallucination is the
app's real orange `#dc6b1d`, not a stock purple** — exports must match the app.

| Status        | Light     | Dark      | Glyph | Label (text formats)  |
| ------------- | --------- | --------- | ----- | --------------------- |
| verified      | `#10a37f` | `#10a37f` | 🟢    | Verified              |
| warning       | `#f59e0b` | `#fbbf24` | 🟡    | Warning               |
| error         | `#ef4146` | `#f87171` | 🔴    | Error                 |
| hallucinated  | `#dc6b1d` | `#fb923c` | 🟠    | Likely hallucinated   |
| unverified    | `#8e8ea0` | `#8b8b96` | ⚪    | Unverified            |

Tinted status backgrounds (for callouts) follow the app's `*-bg` tokens:
`error-bg #fef2f2`, `warning-bg #fffbeb`, `success-bg #ecfdf5`, `halluc-bg #fff7ed`
(dark: `#3b1818 / #3b2f05 / #052e22 / #431c07`).

Severity → band colour (verdict bar, AI band): `high → error`, `medium → warning`,
`low → accent`. AI distribution segments: `AI → error`, `Mixed → warning`,
`Human → accent`.

> In `export.py` these live in `_STATUS_COLOR`, `_BAND_COLOR`, `_SEG`,
> `_STATUS_EMOJI`, `_STATUS_LABEL`, and the `:root` / dark block of `_html_doc`.

---

## 3. Type scale

System font stack, exactly the app's `--font-sans`:

```
-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, Helvetica, Arial, sans-serif
```

Numerals use `font-variant-numeric: tabular-nums` so stat counts and scores align.

| Element            | Size / weight                              | Notes                                   |
| ------------------ | ------------------------------------------ | --------------------------------------- |
| Body               | 15px / 1.6                                 | comfortable reading measure (≤860px)    |
| `h1` (report title)| 23px, weight 650, `-0.015em`               | one per report                          |
| `h2` (section)     | 13px, **uppercase**, `0.05em`, `fg-2`      | quiet section label, app card-header voice |
| `h3`               | 14px, weight 600                           | sub-headings (e.g. Flagged passages)    |
| Stat number        | 25px, weight 700, `-0.02em`                | tinted by status                        |
| Caption / meta     | 12–12.5px, `muted`                         | author · year · venue                   |

DOCX half-point sizes mirror this (`w:sz` = pt × 2): title 36, section 28, body
22, meta 18, footer 16. PDF (PyMuPDF Story) uses pt: h1 16pt, h2 12pt, body 9–10pt.

---

## 4. Components

- **Wordmark header.** Top of every report: an inline accent check-mark glyph +
  `Ref` (in `fg`) + `Checker` (in `accent`), with the timestamp right-aligned in
  `muted`, under a hairline `border` rule. No raster logo. In PDF/DOCX the
  wordmark is a text rule (accent underline / accent text) since those engines
  have no inline SVG support.
- **Verdict bar.** A `card` with a 3px **left** border in the severity colour and
  a matching status dot. Left border only — the other three sides stay hairline
  `border`, so it reads as a quiet callout, not a coloured box.
- **Health pill.** Rounded `999px` pill; score chip filled with the health colour
  (white text), grade word beside it. Same formula as the in-app `HealthBadge`.
- **Stat cards.** Equal-width flex cards, soft shadow, big tabular number tinted
  by its status, small `muted` label.
- **Card.** `radius-lg` (14px), 1px `border`, `shadow`, generous padding. Houses
  AI detection, references, batch overview.
- **Reference row.** Status **chip** (filled, white text, capitalised) + title
  (+ `✓ cited` accent badge when inline-cited) + `muted` meta + source link.
  Issues nest below as coloured lines: `⛔` error, `⚠` warning, `· … (minor)`,
  `✎ Suggested:` correction in an `accent` / `success-bg` callout.
- **AI detection.** Donut (segments = `_SEG`, track = `track`, centre label =
  `fg`), band line in band colour, distribution pills, per-page bars on `track`,
  flagged-passage list on `error-bg` with a left `error` rule. The advisory
  **disclaimer** is mandatory on every AI render path and every format.
- **Shadows / radii.** `--shadow-card` from the app; radii `6 / 10 / 14px` and a
  `999px` pill. Borders are always 1px hairlines.

---

## 5. Light / dark

- **HTML** ships both: light `:root`, dark via `@media (prefers-color-scheme: dark)`.
  The report follows the reader's OS, matching whichever theme the app runs in.
- **PDF & DOCX** are print artefacts → **light only** (paper is white). The PDF
  `@media print` block and the PyMuPDF palette force the legible light tokens.

---

## 6. Print / PDF rules

- Force the light theme; drop all shadows; links render in `fg` (ink), not blue.
- `break-inside: avoid` on cards, reference rows, and flagged-passage items so a
  single reference never splits across a page break.
- A4 page, ~40pt margins (handled by the PyMuPDF `Story` placement box).
- Section headings carry a hairline accent/`border` underline to echo the app's
  card headers within the engine's limited CSS.
- Batch PDFs: wordmark + overview table on page 1; each paper starts on a fresh
  page (`page-break-before`) **without** repeating the wordmark.

---

## 7. Format-specific structure (within each format's limits)

| Format   | Structure                                                                                  |
| -------- | ------------------------------------------------------------------------------------------ |
| HTML     | Full theme: wordmark, verdict, health pill, stat cards, AI donut/bars, chipped reference list. Light+dark, print CSS. |
| PDF      | Same information, simplified for PyMuPDF (tables not flex/grid, no SVG donut). Light palette, accent wordmark rule, underlined sections. |
| Markdown | Brand line, verdict, health, a metric **table**, an AI block, an **Issues** list with `🔴/🟡` + `⛔/⚠/✎`, and an all-references list led by a **status-emoji legend**. LLM-ingestible. |
| DOCX     | Minimal OOXML: accent brand line, status-tinted headings & stats, status emoji + label per reference, a legend row, the mandatory AI disclaimer. |

Every format shares the same `_model()` data and the same status legend, so a
report reads identically whichever way it is opened.

---

## 8. Reproducibility checklist

When restyling exports, keep these in lockstep so the report never drifts from
the app:

1. Status/brand hexes match `web-ui/src/index.css` (§2) for both light and dark.
2. Status glyphs/labels are identical across Markdown, DOCX, and the HTML chips.
3. The accent is `#10a37f` everywhere; hallucination is `#dc6b1d` (orange).
4. Font stack is the app's `--font-sans`; no web-default substitution.
5. PDF/DOCX use the light column only; HTML ships both with `prefers-color-scheme`.
6. The AI advisory disclaimer appears on every AI render path in every format.
7. No fabricated data — empty sections are omitted, not filled.
