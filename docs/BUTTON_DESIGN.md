# Button & Action-Area Redesign Spec (v2)

Reference-/article-level action area — refchecker web-ui (dark theme, green accent, native-macOS feel).

> **What changed v1 → v2.** This revision resolves ten reviewer objections that made v1
> under-specified or self-contradictory. The headline fixes: (1) **one radius — `8px` — for
> every status pill** including `AdditionalInfoBar` (§1.0, §4.7); (2) **status fills are named
> translucent tokens**, not the opaque `*-bg` browns/reds (§1.1, §1.2); (3) every hover/active
> state has an **exact value**, no `+4%` hand-waving (§1.3); (4) the **invisible longest-label
> sizer is mandatory** and all `ch` counts are gone — they were smaller than the real labels
> (§3.1); (5) the **"identical at rest" criterion is reconciled with the split-button caret**
> (§3.2, §5); (6) a **per-file interface contract + post-merge checklist** for the two
> concurrently-edited files (§4.5, §4.6, §5); (7) the **segmented-control bold-sizer is
> mandated**, not one-of-three (§3.4b); (8) `box-sizing:border-box` on the input (§3.4d);
> (9) **exact icon px** everywhere (§1.4); (10) a **focus-ring overflow/clip note** for the
> split button and scrolling panels (§1.2, §3.2).

## 0. Scope & problem statement

This spec covers every control in the article-level action area that sits between
the Stats/health row and the References/Corrections tabs in
`web-ui/src/components/MainPanel/MainPanel.jsx` (the `flex flex-wrap items-start gap-2`
row at `MainPanel.jsx:339`, plus the full-width `AIDetectionPanel` at `MainPanel.jsx:372`):

1. **Retraction status pill** — `RetractionCheck.jsx` (`↻ No retractions — re-check` + caption bubble).
2. **Gap-finder collapsible header** — `GapFinder.jsx` (`N works your references cite that you might add ▸ show`).
3. **Citation-numbering split-button** — `CitationIntegrity.jsx` (`↻ Numbering consistent — re-check` + attached caret).
4. **Article assistant** — `ArticleAssistant.jsx` (trigger → `Summarize | Chat` segmented panel + `×` + input + `Send`).
5. **AI-likelihood expandable row** — `AIDetectionPanel.jsx` (chevron + colored pill + score + meta + `View in document` / `Show N flagged passages`).

### The three reported defects, restated as requirements

- **R1 — Visual consistency.** The three re-check/header pills, the assistant trigger, and the AI pill currently use different heights, paddings, radii, fonts, and borders. They must share one token system so they read as one family.
- **R2 — Click-state stability.** Today a click mutates geometry: `RetractionCheck` and `CitationIntegrity` swap the label for `Checking…` (width jump); the segmented tabs/menus/expanders change the header; the AI row grows. No control may change its **width, height, border-radius, or border** as a result of being clicked. Only inner content (icon→spinner, body region) may change.
- **R3 — Grouping & rhythm.** The blocks must align on a shared baseline, share a vertical rhythm, and have a defined max-width and caption placement.

> **Concurrency note.** Two of the files in this spec — `StatusSection.jsx` and `AIDetectionPanel.jsx` — are being edited by another workflow **in parallel**. Treat their changes as authoritative and apply this spec's changes to them **last**, rebasing onto whatever those edits produce. The four flex-row panels (`RetractionCheck`, `GapFinder`, `CitationIntegrity`, `ArticleAssistant`) and the shared `Button.jsx`/`index.css` work are safe to do first. **The minimal rebase contract these two files must satisfy after the merge is specified in §4.5 / §4.6 and verified by the §5 post-merge checklist** — a structural rebase that drops the family treatment must FAIL that checklist.

---

## 1. Shared Button / Pill token system

These tokens are the contract every control in this spec consumes. They are designed
to drop on top of the existing CSS variables in
`web-ui/src/index.css` (`:root` lines 4–46, `.dark` lines 48–77) and the radii already
defined there (`--radius-sm: 6px`, `--radius-md: 10px`, `--radius-lg: 14px`,
`--radius-pill: 9999px` at `index.css:36–39`).

### 1.0 THE ONE RADIUS DECISION (resolves objection 1)

> **Every status pill, action pill, split-button, icon-button, segmented control, and the
> dense AI/inline pills use `border-radius: 8px` (`--control-radius`). Full-round `9999px`
> is reserved ONLY for true status *dots* (the 8×8 colored circle inside a pill), never for
> the pill outline.**

This is the single decision that makes the controls read as one family. It is **binding**, not
"an option." Concretely, the following currently-divergent radii are all unified to `8px`:

| Element | file:line | today | v2 |
|---|---|---|---|
| RetractionCheck pill | `RetractionCheck.jsx:55` (`rounded-md`) | 6px | **8px** (`--control-radius`) |
| CitationIntegrity main/caret | `CitationIntegrity.jsx:82,99` | 6px | **8px** |
| GapFinder trigger | `GapFinder.jsx:100` (`rounded-md`) | 6px | **8px** |
| ArticleAssistant trigger / Send / input | `ArticleAssistant.jsx:255,358,363` (`rounded-md`) | 6px | **8px** |
| AIDetectionPanel likelihood pill | `AIDetectionPanel.jsx:168` (`rounded`) | 4px | **8px** |
| ArticleAssistant `SourceBadge` | `ArticleAssistant.jsx:91` (`rounded-full`) | 9999px | **8px** |
| AIDetectionPanel `SourceBadge`-style span | `AIDetectionPanel.jsx:168` | 4px | **8px** |
| **AdditionalInfoBar `Pill`** | `AdditionalInfoBar.jsx:18` (`borderRadius:9999`) | **9999px** | **8px** |
| CitationIntegrity inner detail badge | `CitationIntegrity.jsx:121` (`rounded-full`) | 9999px | **8px** |

The previous v1 wording that left `AdditionalInfoBar` "at 9999px as an option" and let the AI
dense pill be `8px` while inline status pills stayed `rounded-full` is **withdrawn**. There is no
per-component choice: status pills are `8px` rectangles with soft corners (the native-mac look),
full stop. `AdditionalInfoBar` is **in scope for this decision** (it is the most-seen pill in the
app); only its larger structural migration to `<Button>` remains a follow-up (§4.7).

### 1.1 New control tokens (add to both `:root` and `.dark` in `index.css`)

Geometry tokens are theme-agnostic and live in `:root` once. **The status-fill and status-hover
tokens are theme-dependent and are declared in BOTH `:root` and `.dark`** because the existing
`*-bg` tokens are opaque, themed, and the *wrong* tint (see objection 2): in `.dark`,
`--color-warning-bg` is `#3b2f05` (a brown), `--color-error-bg` is `#3b1818`, `--color-success-bg`
is `#052e22` — none of these match the `rgba(...,0.12–0.14)` translucent tints the live pills use
(`RetractionCheck.jsx:42–43`, `CitationIntegrity.jsx:61–62`). Routing the pills through `*-bg`
would visibly change their look. So we **name the existing translucent tints as new tokens** and
keep using them; we do **not** swap to `*-bg`.

```css
/* === Action-control geometry (theme-agnostic) — add to :root only === */
--control-h:            28px;   /* the ONE canonical control height */
--control-h-sm:         22px;   /* dense inline pills (AI-likelihood, AdditionalInfoBar) */
--control-pad-x:        12px;   /* horizontal padding for default controls */
--control-pad-x-sm:     9px;    /* horizontal padding for dense pills */
--control-gap:          6px;    /* icon↔label gap inside a control */
--control-icon:         14px;   /* the ONE icon-glyph size for every control (objection 9) */
--control-icon-slot:    16px;   /* fixed square that holds icon/refresh/spinner — never reflows */
--control-radius:       8px;    /* THE radius for every pill/button/segment (objection 1) */
--control-caret-w:      28px;   /* split-button caret segment width (square) */
--control-font:         12px;   /* 0.75rem — matches existing text-xs usage */
--control-font-weight:  500;    /* matches existing font-medium */
--control-font-weight-active: 600; /* segmented-control active tab weight */
--control-border:       1px solid var(--color-border);
--control-focus-ring:   0 0 0 2px var(--color-bg-secondary), 0 0 0 4px var(--color-accent);
--control-row-gap:      8px;    /* vertical rhythm BETWEEN action blocks */
--control-caption-gap:  4px;    /* gap between a pill and its caption bubble */
--control-transition:   background 120ms ease, color 120ms ease, border-color 120ms ease;

/* === Status pill fills + hovers (objections 2 & 3) — add to :root === */
/* These ARE the live translucent tints (RetractionCheck:42-43, CitationIntegrity:61-62),
   now named. They do NOT route through the opaque *-bg tokens. Light theme: */
--status-success-fill:        rgba(16, 185, 129, 0.12);
--status-success-fill-hover:  rgba(16, 185, 129, 0.20);  /* +0.08 alpha, deterministic */
--status-warning-fill:        rgba(245, 158, 11, 0.14);
--status-warning-fill-hover:  rgba(245, 158, 11, 0.22);  /* +0.08 alpha */
--status-error-fill:          rgba(239, 68, 68, 0.12);
--status-error-fill-hover:    rgba(239, 68, 68, 0.20);   /* +0.08 alpha */
--outline-fill:               var(--color-bg-secondary); /* resting action pill */
--outline-fill-hover:         var(--color-bg-tertiary);  /* deterministic, themed */
```

```css
/* === Status pill fills + hovers — add to .dark === */
/* Slightly higher base alpha in dark so the tint reads on the dark surface,
   matching the perceived weight of the light-theme tints. Same +0.08 hover delta. */
.dark {
  --status-success-fill:        rgba(16, 185, 129, 0.18);
  --status-success-fill-hover:  rgba(16, 185, 129, 0.26);
  --status-warning-fill:        rgba(251, 191, 36, 0.18);
  --status-warning-fill-hover:  rgba(251, 191, 36, 0.26);
  --status-error-fill:          rgba(248, 113, 113, 0.18);
  --status-error-fill-hover:    rgba(248, 113, 113, 0.26);
  /* --outline-fill / --outline-fill-hover already resolve via the themed
     --color-bg-secondary / --color-bg-tertiary, so no dark override needed. */
}
```

> Rationale for `28px`: the current controls are `py-1.5 + text-xs` (~26px) and
> `px-2 py-1` (~24px); `28px` is a single clean line-height that all of them can hit
> without feeling chunky, and `28 = --control-caret-w` so the split-button caret is a
> perfect square. The dense `22px` (`--control-h-sm`) is for inline pills that live in
> text runs (AI likelihood band, `AdditionalInfoBar`).

> **No NEW hardcoded hex is introduced.** The status-fill `rgba(...)` values are the
> *existing* tints already in the source (`RetractionCheck.jsx:42–43`,
> `CitationIntegrity.jsx:61–62`, `AIDetectionPanel` `BAND_STYLES`), now centralized as
> named tokens instead of repeated inline. The v1 claim "no new color values" was
> imprecise — the precise statement is: **borders/text reuse `--color-*`; fills reuse the
> existing translucent tints, now named; nothing routes through the opaque `*-bg` tokens.**

### 1.2 The single source of truth: extend `common/Button.jsx`

`web-ui/src/components/common/Button.jsx` already centralizes variants
(`primary`/`secondary`/`danger`/`ghost`, lines 15–40) and sizes (`sm`/`md`/`lg`, lines 42–46),
and already renders an inline spinner when `loading` (lines 73–93). It is currently
**unused by the five panels in this spec** — they all hand-roll `<button>`s. The redesign
makes `Button.jsx` the source of truth and adds the variants the panels need.

**Add these variants** to the `variants` map (`Button.jsx:15`). Every fill/hover is an exact
token — no `+4%` (objection 3):

| variant | fill | text | border | hoverBg | use |
|---|---|---|---|---|---|
| `primary` *(exists)* | `--color-accent` | `#fff` | none | `--color-accent-hover` | filled CTA (`Send`, `Confirm add`, `View in document`) |
| `secondary` *(exists)* | `--color-bg-tertiary` | `--color-text-primary` | none | `--color-border` | low-emphasis |
| `ghost` *(exists)* | transparent | `--color-text-secondary` | none | `--color-bg-tertiary` | icon-only / `×` |
| **`outline`** *(new)* | `var(--outline-fill)` | `--color-text-primary` | `--control-border` | `var(--outline-fill-hover)` | **default action pill** (resting re-check, gap header, assistant trigger) |
| **`status-success`** *(new)* | `var(--status-success-fill)` | `--color-success` | `1px solid var(--color-success)` | `var(--status-success-fill-hover)` | re-check "clean" result |
| **`status-warning`** *(new)* | `var(--status-warning-fill)` | `--color-warning` | `1px solid var(--color-warning)` | `var(--status-warning-fill-hover)` | numbering issues found |
| **`status-error`** *(new)* | `var(--status-error-fill)` | `--color-error` | `1px solid var(--color-error)` | `var(--status-error-fill-hover)` | retractions found |

Each variant object gains a `hoverBg` (already the pattern at `Button.jsx:20,26,32,38`); the
`onMouseEnter`/`Leave` handlers (`Button.jsx:61–70`) already swap `backgroundColor` to/from
`hoverBg`, so the new variants need no new handler logic — only the new `hoverBg` token values
above. **Border-color does not change on hover** (only the fill does), so the geometry is fixed.

**Add a `pill` size** (`Button.jsx:42`) that consumes the new tokens instead of Tailwind
padding classes, so height is fixed regardless of content:

```js
// sizes: keep sm/md/lg; the new fixed-height pill size class is empty —
// padding+height come from inline style below, not from Tailwind classes:
pill: '',
```

and in the rendered `<button>` style (`Button.jsx:53`) merge, when `size === 'pill'`:

```js
height: 'var(--control-h)',
minHeight: 'var(--control-h)',
padding: '0 var(--control-pad-x)',
borderRadius: 'var(--control-radius)',
fontSize: 'var(--control-font)',
fontWeight: 'var(--control-font-weight)',
lineHeight: 1,
boxSizing: 'border-box',   // REQUIRED — the input in §3.4(d) gets the same (objection 8)
gap: 'var(--control-gap)',
transition: 'var(--control-transition)',
```

**Replace the focus ring.** The current `focus:ring-2 focus:ring-offset-2` (Tailwind, in
`baseStyles` at `Button.jsx:13`) does not theme correctly on dark surfaces and grows the box via
`ring-offset`. Use `:focus-visible` only (not `:focus`, so mouse clicks never paint a ring) with
the new token. **Add `className="rc-control"` to the base button** so the CSS rule below applies:

```css
/* index.css — add once */
.rc-control { outline: none; }
.rc-control:focus-visible { box-shadow: var(--control-focus-ring); }
```

> **Focus-ring overflow / clipping note (objection 10).** `--control-focus-ring` is a
> double `box-shadow`, which can be **clipped** by (a) the split-button group when each
> segment has `overflow` or sits inside a rounded clip, and (b) the scrolling result panels
> (`CitationIntegrity.jsx:118` `maxHeight:360; overflowY:auto`; the retraction/gap lists).
> Mitigations — **all required where applicable**:
> 1. The split-button group wrapper (§3.2) and any focus-ring-bearing control inside a
>    scroll container set `overflow: visible` on themselves (they don't need to clip their
>    own content; only the *scroll* container clips, and the ring must escape it). Add a
>    helper: `.rc-control { overflow: visible; }`.
> 2. The double-box-shadow ring is drawn **outside** the box (no `inset`), so as long as the
>    immediate ancestor up to the scroll container does not `overflow:hidden`, the ring shows.
>    The scroll container itself (`overflowY:auto`) will clip a ring on a control flush to its
>    edge — so inside scroll panels, give the focusable rows `scroll-margin`/inner padding
>    (the result panels already have `p-3`, which keeps controls off the clip edge).
> 3. On the **split-button**, render the focus ring on the **focused segment** using the
>    outer-corner radius that matches that segment (main vs. caret), so the ring follows the
>    rounded outer corners and the straight inner divider edge — do NOT draw one ring around
>    the whole group on focus (that would imply both segments are focused). Each segment is its
>    own `.rc-control`; its `box-shadow` ring respects its own `border-radius`
>    (`8px 0 0 8px` / `0 8px 8px 0`), which is the desired shape.
> 4. If any container genuinely must clip (none in this spec do), fall back to
>    `outline: 2px solid var(--color-accent); outline-offset: 1px; border-radius` instead of
>    `box-shadow` for that control — `outline` is not clipped by ancestor overflow.

### 1.3 Exact per-variant state table

All values are the same for every control; only the variant color set changes. **No state
changes width, height, border-radius, or border** (objection: deterministic, R2).

| State | Geometry | Visual change (exact) | Forbidden |
|---|---|---|---|
| **rest** | h `28px`, pad-x `12px`, radius `8px`, border `1px` | variant fill/text/border per §1.2 | — |
| **hover** | unchanged | `backgroundColor` → variant `hoverBg` (an exact token: `--*-fill-hover` / `--outline-fill-hover` / `--color-accent-hover`); `transition: var(--control-transition)`. **Border-color and text color stay put.** | any size/radius/border change |
| **active (`:active`)** | unchanged | bg = `hoverBg`; optional `transform: translateY(0.5px)` (no layout cost) | width/height change |
| **focus-visible** | unchanged | `box-shadow: var(--control-focus-ring)` (drawn outside the box, no offset that grows it; see §1.2 overflow note) | layout-affecting outline / ring-offset |
| **disabled** | unchanged | `opacity: 0.6`, `cursor: default`; **keep the same fill/border** (do NOT swap to grey) | swapping the whole color → reads as a different/smaller chip |
| **loading** | unchanged | only the **`--control-icon-slot` (16×16) box** swaps to a spinner; the label slot keeps its reserved width (§3.1) | label text swap that changes the button width |

> The `disabled` rule **overrides** the current `Button.jsx:54–55` behavior, which swaps the
> fill to `--color-bg-tertiary` and the text to `--color-text-muted`. Change those two lines
> so disabled keeps `style.backgroundColor` / `style.color` and only applies `opacity:0.6`.
> (Swapping the fill makes a disabled pill read as a different, smaller chip — the exact
> regression R2 forbids.)

### 1.4 Icon-button + split-button primitives (new shared components)

Add two tiny shared components next to `Button.jsx`. **All glyphs are exactly `14px`
(`--control-icon`) — no ranges (objection 9).**

- **`web-ui/src/components/common/IconButton.jsx`** — square `var(--control-h) × var(--control-h)`
  (28×28) by default, or `var(--control-h-sm)` square (22×22) when `size="sm"`;
  `border-radius: var(--control-radius)` (8px); `ghost` fill; centers a **`14px`** SVG
  (`--control-icon`). Used for the split-button caret, the assistant `×`, the gap-finder header
  chevron, and the AI collapse chevron. Fixed square = never reflows. Carries
  `className="rc-control"` for the focus ring. Accepts `rotated` (boolean) → applies
  `transform: rotate(180deg); transition: transform 150ms ease` to its SVG for chevron toggles.

- **`web-ui/src/components/common/SplitButton.jsx`** — wraps a main `Button` + an `IconButton`
  caret in a single `inline-flex items-stretch` group (see §3.2 for the exact anatomy).
  Centralizes the shared-height + outer-corner-only radius + single 1px divider + relative
  menu wrapper so `CitationIntegrity` (and any future split control) stops hand-rolling it.
  Props: `main` (a `<Button>` element), `caretOpen`, `onCaretToggle`, `caretDisabled`,
  `menu` (the dropdown content, rendered into the absolutely-positioned anchor), `menuOpen`.

> **Glyph-size table (binding, objection 9).** Every control glyph renders at one size:
>
> | glyph | size | where |
> |---|---|---|
> | action icons (cross-circle, list, search, chat-bubble, refresh) | **14px** | inside `--control-icon-slot` 16×16 box, centered |
> | split-button caret chevron | **14px** | `IconButton` (28×28) |
> | gap-finder header chevron | **14px** | `IconButton` (28×28) |
> | AI collapse chevron | **14px** | `IconButton` `size="sm"` (22×22) — was `width="14"` already at `AIDetectionPanel.jsx:162`; keep 14, just standardize the wrapper |
> | assistant `×` | **14px** | `IconButton` (28×28) |
> | status dot (the colored circle) | 8px circle | inside the pill, `border-radius:9999px` (the ONE allowed round) |
>
> Replace the current `width="13" height="13"` action glyphs (`RetractionCheck.jsx:59,61`,
> `CitationIntegrity.jsx:88,90,105`, `GapFinder.jsx:103`, `ArticleAssistant.jsx:260`) with `14`.

---

## 2. Layout, sizing, positioning, grouping (R3)

### 2.1 The action row

`MainPanel.jsx:339` currently wraps the four panels in `flex flex-wrap items-start gap-2`.
Change to a column-of-rows model so every block aligns to the left edge and shares one rhythm:

- Outer container: `display: flex; flex-direction: column; gap: var(--control-row-gap)` (8px),
  `max-width: 760px` (matches the readable column the cards use; pin so pills don't stretch edge-to-edge).
- `items-start` → each block is full-width of that column but its **interactive control is intrinsic width, left-aligned**.
- Drop the per-panel `mb-3` (`RetractionCheck.jsx:53`, `GapFinder.jsx:97`, `CitationIntegrity.jsx:74`,
  `ArticleAssistant.jsx:252`) — vertical spacing is owned by the container `gap`, not by each child, so
  removing/adding a block never leaves a double/zero margin.
- `CitationIntegrity` currently forces `flexBasis:100%` (`CitationIntegrity.jsx:74`) to break to its own
  line inside the old flex-wrap; with the column model this hack is removed.

### 2.2 Alignment within a block

Every block is `display: flex; flex-direction: column; gap: var(--control-caption-gap)` (4px):

```
[ pill / split-button / header ]      ← row 1: the control, intrinsic width, height 28px
[ caption bubble OR result panel ]    ← row 2: full column width, only when present
```

The **caption bubble** (e.g. RetractionCheck's "No retractions found in OpenAlex for the 34
references…") sits directly under its pill at `4px`, left edge aligned to the pill, `text-xs`,
`color: var(--color-text-muted)`, no border, no background (it's a caption, not a card). The
larger **result panels** (gap list, numbering detail, retraction list) stay full column width
with the existing `rounded-lg p-3` card treatment.

### 2.3 The AI-likelihood block

`AIDetectionPanel` is a full-width bordered card (`AIDetectionPanel.jsx:148`) and stays so — it is
**not** an inline pill. Its header row, however, must align its pill/score/meta to the same baseline
and the right-hand `View in document` / `Show N flagged passages` buttons must use the shared `pill`
size so they match the rest of the family.

---

## 3. Per-control anatomy + click-state stability (R2)

### 3.1 Re-check status pills — `RetractionCheck.jsx`, and the main segment of `CitationIntegrity.jsx`

**Anatomy** (`Button` variant `outline` at rest → `status-*` after a result):

```
┌──────────────────────────────────────────────┐  h = 28px, radius 8px
│ [icon-slot 16×16] [label: longest-label sizer]│  pad-x 12, gap 6
└──────────────────────────────────────────────┘
```

- **Icon slot** — a fixed `16×16` box (`--control-icon-slot`). At rest it holds the `14px`
  action glyph (`RetractionCheck.jsx:61` crossed-circle / `CitationIntegrity.jsx:90` list).
  After a result it holds the `14px` refresh glyph (`…:59` / `…:88`). While loading it holds
  **only** the spinner from `Button.jsx:73–92` (rescaled to `14px`). Because the box is fixed,
  the icon↔refresh↔spinner swap never moves the label.

- **Label slot — the key fix, and the only sanctioned technique (objection 4).** `ch` is the
  width of the `0` glyph, **not** of proportional text, and the real labels are far longer than
  v1's `16ch`/`18ch`:
  - retraction longest: `No retractions — re-check` (25 chars), `Checking retractions…` (21),
    `N retracted — re-check` (≈22).
  - numbering longest: `N numbering issues — re-check` (≈29 chars), `Numbering consistent — re-check` (31),
    `Numbering n/a — re-check` (24), `Checking numbering…` (19).

  So `ch` counts are **removed entirely**. **MANDATORY technique — invisible longest-label
  sizer with the live label overlaid:**

  ```jsx
  // LABELS = every string this control can show, longest decides the width.
  <span style={{ position: 'relative', display: 'inline-grid' }}>
    {/* sizer: every candidate stacked in the SAME grid cell; the widest one
        sets the box width; all are visually hidden but occupy space */}
    {LABELS.map((t) => (
      <span key={t} aria-hidden
        style={{ gridArea: '1 / 1', visibility: 'hidden', whiteSpace: 'nowrap' }}>
        {t}
      </span>
    ))}
    {/* live label overlaid in the same cell */}
    <span style={{ gridArea: '1 / 1', whiteSpace: 'nowrap', textAlign: 'left' }}>
      {btnLabel}
    </span>
  </span>
  ```

  `inline-grid` with every candidate in cell `1/1` makes the box exactly as wide as the longest
  real string in that control's own font — never narrower, never resized between
  rest↔checking↔result. This is **required**, not an alternative. (`RetractionCheck` LABELS =
  the four strings at `RetractionCheck.jsx:44–50`; `CitationIntegrity` LABELS = the five strings
  at `CitationIntegrity.jsx:63–71`.)

  > Optional refinement — `web-ui/src/components/common/useReservedWidth.js`: a hook that renders
  > the candidates once off-screen, measures the max `getBoundingClientRect().width`, and returns
  > a `minWidth` in px. Equivalent result; use it if you prefer a measured number to the
  > sizer-grid. **Either the sizer-grid or this hook is required** — hand-counted `ch` is not.

- **Color reports status, geometry never changes.** Keep the existing logic that turns the pill green
  (clean), amber (numbering issues), or red (retractions) — but route it through the `status-*`
  variants so border/fill come from tokens. Height, radius, padding stay identical across
  rest/clean/issue/error/loading.

**Click behavior:**
- click → `state.loading = true` → icon slot shows spinner, label shows `Checking…`, **same box size** (sizer holds the width).
- result → icon = refresh, label = result string, variant = `status-success|warning|error`. No reflow.
- disabled-while-loading uses `opacity:0.6` only (§1.3), not a fill swap.

This replaces `RetractionCheck.jsx:54–64` and the main `<button>` of `CitationIntegrity.jsx:76–93`.

### 3.2 The split-button — `CitationIntegrity.jsx` (main + caret)

Use the new `SplitButton`. Exact anatomy:

```
┌──────────────────────────────┬───────┐   group: inline-flex items-stretch, h=28
│ [icon] Numbering consistent  │  ▾    │   divider = 1px var(--color-border) between
│        — re-check            │       │   main: radius 8 0 0 8; caret: radius 0 8 8 0
└──────────────────────────────┴───────┘   caret = IconButton, width 28 (--control-caret-w)
```

Rules (fixing `CitationIntegrity.jsx:75–111`):
- **Shared height.** Both segments are `var(--control-h)`; `align-items: stretch` guarantees equal height.
- **Outer-corner-only radius.** Main: `border-radius: var(--control-radius) 0 0 var(--control-radius)`
  (`8px 0 0 8px`). Caret: `0 var(--control-radius) var(--control-radius) 0` (`0 8px 8px 0`).
- **Single divider, no double border.** The main segment drops its right border
  (`borderRight: 'none'`); the caret keeps its left border so exactly one 1px line shows.
- **Both segments share the status variant** so the split reads as one chip (current code spreads
  `btnStyle` into both — keep that, now via the variant).

- **RESOLVING THE "IDENTICAL AT REST" vs. ALWAYS-RESERVED-CARET CONFLICT (objection 5).** v1 said
  two contradictory things: R1 wants the citation control "visually identical at rest" to the other
  pills, but §3.2 also wanted a permanent visible caret segment, which would make it visibly
  different (a 28px attached segment + divider the others lack). **Resolution — option A (chosen):
  no caret, no divider, no attached segment until the first check completes.** Before `checked`,
  `CitationIntegrity` renders **exactly a plain `outline` pill identical to the others** — the
  `SplitButton` is rendered in "single" mode (no caret element, no divider). The corner-pop that v1
  was trying to prevent is instead prevented by **keeping the main segment's radius constant**:
  - Pre-check: the main segment has full radius `8px` on **all four corners** (it's a lone pill).
  - Post-check: the caret appears AND the main segment's right corners flatten to
    `8px 0 0 8px` in the **same** render. Because the caret's left edge now butts against the main
    segment's (now-square) right edge, the *visual outer silhouette is unchanged width-wise on the
    left* and only grows on the right by the caret's 28px — which is the legitimate appearance of a
    new control, not a "pop." To make even that growth non-jarring, the caret **fades+slides in**
    (`opacity 0→1`, `translateX(-4px)→0`, 120ms) and the main segment's right-corner radius
    transitions `8px → 0` over the same 120ms.

  > The §5 acceptance item is reworded accordingly: at rest (pre-check) the citation main pill IS
  > visually identical to the other three; the caret is a **post-result** addition, explicitly
  > exempt from the "identical at rest" criterion because at rest it does not exist. This removes
  > the contradiction.

- **Menu alignment.** The caret menu anchors to the caret's bottom-right inside the group's
  `position:relative` wrapper: `position:absolute; top: calc(100% + 4px); right: 0; min-width: 200px;
  z-index: 20`. Opening it does not shift the button. The wrapper has `overflow: visible` so the
  menu and the focus ring (§1.2) are not clipped.

### 3.3 Gap-finder collapsible header — `GapFinder.jsx`

Two states share **one** geometry:

- **Pre-run trigger** (`GapFinder.jsx:99–105`): `Button` `size="pill"` `variant="outline"`,
  `14px` search icon in the fixed icon slot, label `Did you miss these?` / `Analyzing co-citations…`
  (use the §3.1 sizer-grid label slot so the analyzing swap doesn't jump).
- **Result header** (`GapFinder.jsx:110–115`): the full-width clickable header inside the result card.
  Today it's a bare `<button class="w-full flex justify-between">` with a text affordance that
  changes between `▸ show` / `▾ hide` (`:114`). Fixes:
  - The header is a **fixed-height (`28px`) row**; only the chevron rotates, the label text
    `N works your references cite that you might add` is **constant**.
  - **Delete the `▸ show`/`▾ hide` text span** (`:114`) and replace with a right-pinned rotating
    chevron `IconButton` (`rotated={!collapsed}`, `14px` glyph). No text reflow.
  - The expanding list animates with a stable header: wrap the body (`GapFinder.jsx:117–241`) in a
    container that animates `grid-template-rows: 0fr → 1fr` (with `overflow:hidden` on the
    *animated wrapper*, which has no focusable controls flush to its edge) so the header stays put
    while the list reveals.

### 3.4 Summarize | Chat assistant — `ArticleAssistant.jsx`

Four sub-parts:

**(a) Trigger** (`:254–262`) — `Button` `size="pill"` `variant="outline"`, `14px` chat-bubble icon,
label `Chat & Summarize` / `Chat about this reference`. Matches the other resting pills exactly.

**(b) Segmented control `[ Summarize | Chat ]`** (`:266–276`) — replace the `border-b-2` underline
with a **fixed macOS-native segmented control** whose active state is a moving *background fill*, not
a border (a border adds box height and reflows). Anti-reflow technique is **MANDATED, single
option (objection 7):**

  - Container: `display:inline-flex; height:28px; padding:2px; gap:2px;
    border-radius:var(--control-radius); background: var(--color-bg-tertiary); box-sizing:border-box`.
  - Each tab: equal width via fixed `min-width:84px` (or `flex:1` in a fixed-width track),
    `border-radius:6px` (inner radius = outer 8 − 2px padding), transparent at rest, `role="tab"`.
  - **Active indicator** is a filled segment: the active tab gets
    `background: var(--color-bg-primary); color: var(--color-accent);
    font-weight: var(--control-font-weight-active)` (600); inactive tabs are weight 500.
  - **REQUIRED bold-width reservation (the one mandated technique):** render a **hidden bold sizer**
    behind each tab label so the box reserves the 600-weight width whether or not the tab is active.
    Concretely, each tab is:

    ```jsx
    <button role="tab" aria-selected={active} className="rc-control" style={{ position:'relative' }}>
      {/* hidden bold sizer: always 600, reserves the active width */}
      <span aria-hidden style={{ fontWeight: 600, visibility: 'hidden', display:'block', height: 0, overflow:'hidden' }}>
        {label}
      </span>
      {/* visible label at the current weight, absolutely overlaid */}
      <span style={{ fontWeight: active ? 600 : 500, position:'absolute', inset:0, display:'flex',
                     alignItems:'center', justifyContent:'center' }}>
        {label}
      </span>
    </button>
    ```

    The `::after`-sizer / `font-variation-settings` / "same tracking" alternatives are
    **withdrawn** — only the hidden-bold-sizer (above) is permitted, because it is the only one
    that actually reserves the 600-weight width regardless of font. This guarantees
    `Summarize ↔ Chat` never reflows.

**(c) Close `×`** (`:278–280`) — `IconButton` `variant="ghost"`, `28×28`, `14px` glyph, pinned
right via `ml-auto`. Fixed square; clicking only toggles `open`, never resizes neighbors.

**(d) Input + Send** (`:352–367`) — the row is `display:flex; gap:8px; align-items:center`:
  - **Input** (`:353–361`): `flex:1; height:28px; padding:0 10px; border-radius:var(--control-radius);
    border: var(--control-border); background: var(--color-bg-primary);
    **box-sizing: border-box**`. The `box-sizing:border-box` is **REQUIRED (objection 8)**: without
    it, default `content-box` makes the rendered input `30px` (28 + 2×1px border) — 2px taller than
    the 28px Send button on the row whose entire goal is alignment. With `border-box` the input is
    exactly 28px, matching Send. (The `pill` button already sets `box-sizing:border-box` in §1.2;
    this clause makes the input match — both must declare it.)
  - **Send** (`:362–365`): `Button` `size="pill"` `variant="primary"` (filled accent). The fix: it
    gets the **same 28px height as the input** (via `size="pill"`) and a **fixed `minWidth:'64px'`**
    so its disabled↔enabled opacity change and any future `Sending…` label don't resize it. While
    sending, show the spinner in its `14px` icon slot, keep the `Send` label width reserved by the
    §3.1 sizer if a `Sending…` label is added.

**Panel open/close stability:** the trigger→panel transition replaces an inline pill with a full-width
card. To avoid a jarring jump, the card animates in (`opacity 0→1`, `translateY(-2px)→0`, 120ms) and the
**block's left edge and top position are unchanged** because both the trigger and the card start at the
same column origin (§2.2).

### 3.5 AI-likelihood expandable row — `AIDetectionPanel.jsx`

Header anatomy (`AIDetectionPanel.jsx:152–216`), all on a fixed baseline:

```
[chevron 22×22] [● AI-likelihood: Medium]  score 45   AI text check · local · local:desklib/…   ┊  [View in document] [Show N flagged passages]
  IconButton sm    dense status pill (22px)   meta            muted meta                                primary pill        outline pill
```

- **Chevron** (`:154–166`) — already a rotating toggle (`:162–164`). Standardize to
  `IconButton` `size="sm"` (22×22, `--control-h-sm`), `14px` glyph, `rotated={!collapsed}`. Rotation
  only — no reflow. (This toggle controls whether the **whole card body** is shown; the card's outer
  border/width are fixed, only the body region reveals.)
- **Likelihood pill** (`:167–174`) — a **dense status pill**: `height: var(--control-h-sm)` (22px),
  `padding: 0 var(--control-pad-x-sm)` (9px), `border-radius: var(--control-radius)` (**8px — same
  family, objection 1**, replacing the current `rounded` ≈4px), colored by band via the existing
  `BAND_STYLES` (`AIDetectionPanel.jsx:83–89`). **Reconcile `BAND_STYLES` with the new tokens:** the
  band fills currently use the opaque `*-bg` tokens (`var(--color-error-bg)` etc.), which is the
  *brown/red-block* look objection 2 warns about. Point `BAND_STYLES[*].bg` at the new translucent
  status-fill tokens so the AI pill matches the re-check pills exactly:
  - `high.bg → var(--status-error-fill)`, `medium.bg → var(--status-warning-fill)`,
    `low.bg → var(--status-success-fill)`; abstain bands keep `var(--color-bg-tertiary)`.
  - `fg`/`dot` stay as-is (`--color-error/warning/success`).
  It carries the 8px status dot + label. It is `cursor:pointer` and toggles collapse too — keep that,
  but it must **not** change size when the band changes (high/medium/low/inconclusive all share
  geometry; only color differs — the §3.1 sizer is not needed here because all band labels are
  pre-known and the pill has no loading state, but the pill's `min-width` should equal the widest
  band label so a band change never resizes it).
- **`score 45`** (`:175–180`) and **meta** (`:181–185`) — plain `text-xs` muted spans, no chips, fixed in place.
- **Right cluster** (`:187–215`): `View in document` (`:190–203`) → `Button` `size="pill"`
  `variant="primary"`; `Show/Hide N flagged passages` (`:204–213`) → `Button` `size="pill"`
  `variant="outline"`. The label `Show N…`↔`Hide` changes width today (`:212`) — wrap it in the
  §3.1 sizer-grid with both candidate strings (`Hide` and `Show N flagged passages`) so toggling
  doesn't jump. Drop the inline `focus:ring-2 focus:outline-none` Tailwind on these (`:193,:209`) in
  favor of `Button`'s `.rc-control` ring.
- **Expand stability:** clicking `Show` reveals `#ai-detection-spans` (`:249`) **below** the header
  inside the same card; the header row's height/position are unchanged. The card grows downward only
  (acceptable — it's a container card, not an inline pill). The **requirement is that no control's own
  box changes shape**, which this satisfies.

---

## 4. Per-file implementation notes

> Order of work: do (4.0)→(4.4) first; do (4.5) and (4.6) **last** because `AIDetectionPanel.jsx` and
> `StatusSection.jsx` are being edited concurrently by another workflow — rebase onto their result
> using the interface contracts in those sections.

### 4.0 Shared (do first)

- **`web-ui/src/index.css`** — add the §1.1 geometry tokens to `:root` (after line 46); add the
  §1.1 `--status-*-fill` / `--outline-fill` tokens to **both** `:root` and `.dark`; add
  `.rc-control { outline:none; overflow:visible; }` + `.rc-control:focus-visible { box-shadow:var(--control-focus-ring); }`;
  add the segmented-control track + dense-pill helper classes. Extend the existing
  `prefers-reduced-motion` guard (`index.css:272`) to also disable the new chevron-rotate,
  segment-fade, caret slide-in, and grid-row expand transitions.
- **`web-ui/src/components/common/Button.jsx`** — add variants `outline`, `status-success`,
  `status-warning`, `status-error` (map at line 15, each with a `hoverBg` token); add `size:'pill'`
  (line 42) consuming `--control-*` with `box-sizing:border-box`; **change the disabled branch
  (lines 54–55)** to keep the variant fill/text and only dim via `opacity:0.6` (§1.3); swap the
  Tailwind focus ring in `baseStyles` (line 13) for `className="rc-control"` + `:focus-visible`;
  generalize the spinner (lines 73–92) so the fixed `16×16` icon slot shows the spinner when
  `loading`, else an `icon` prop (rescale the SVG to `14px`).
- **New** `web-ui/src/components/common/IconButton.jsx` and
  **new** `web-ui/src/components/common/SplitButton.jsx` (§1.4).
- **New** `web-ui/src/components/common/useReservedWidth.js` (optional but recommended; §3.1) —
  OR use the inline sizer-grid. One of the two is required; `ch` counts are not allowed.

### 4.1 `RetractionCheck.jsx`

- Replace the hand-rolled `<button>` (lines 54–64) with
  `<Button size="pill" variant={...} icon={...} loading={state.loading}>` where `variant` =
  `outline` (rest) / `status-success` (clean) / `status-error` (retracted), derived from the
  existing `btnStyle` branch (lines 39–43). Delete the inline `btnStyle` object (the variants own it now).
- Wrap `btnLabel` (lines 44–50) in the §3.1 **sizer-grid** with all four candidate strings, so
  `Check for retractions`→`Checking retractions…`→`No retractions — re-check`→`N retracted — re-check`
  never resizes. (Remove any `ch` value — there is none in v2.)
- Bump the two action SVGs (`:59,:61`) to `14px`.
- Remove `mb-3` from the wrapper (line 53); the wrapper becomes the §2.2 two-row block
  (`flex-col gap-[var(--control-caption-gap)]`).
- Caption bubble (lines 85–91) moves into row 2 of that block; keep its text, drop the `mt-2`
  (the 4px column gap owns it). Keep the `rounded-lg` card only for the **retracted** list
  (lines 66–84); the clean-state line (85–91) becomes a plain caption (no border/bg) per §2.2.

### 4.2 `GapFinder.jsx`

- Pre-run trigger (lines 99–105) → `<Button size="pill" variant="outline" icon={searchSvg} loading={state.loading}>`
  with the §3.1 sizer-grid for `Did you miss these?`↔`Analyzing co-citations…`. Bump the search SVG (`:103`) to `14px`.
- Result header (lines 110–115): make it a fixed-`28px` row; **delete the `▸ show`/`▾ hide` text span**
  (line 114) and replace with a right-pinned rotating chevron `IconButton` (`rotated={!collapsed}`).
  Keep the constant title text (line 113).
- Wrap the expanding body (lines 116–241, the `{!collapsed && (<>…</>)}`) in a `grid-template-rows:0fr→1fr`
  animation container so the header never moves.
- Inner action buttons stay but adopt the family: `+ Add to references` / `Adding…` (lines 146–150)
  keep their underlined-link styling (they're inline-in-text affordances, intentionally **not** pills —
  call this out so a reviewer doesn't "fix" them); `Confirm add` (lines 221–224) →
  `Button size="pill" variant="primary"`; `Cancel` (line 225) stays a ghost text link.
- The inner `▾`/`▸` renumber toggle (line 187) is an in-text disclosure, not a control pill — leave it.
- Remove `mb-3` (line 97).

### 4.3 `CitationIntegrity.jsx`

- Replace the `inline-flex items-stretch` group (lines 75–111) with `<SplitButton>`: main =
  `Button size="pill" variant={status} icon={...} loading={state.loading}` + §3.1 sizer-grid (all
  five labels from `:63–71`); caret = `IconButton` rotating chevron (`rotated={open}`).
- **Fix the first-result corner per §3.2 option A:** pre-check render **single mode** (no caret/divider,
  full `8px` radius — identical to the other pills); post-check the caret fades/slides in and the main
  segment's right corners transition `8px → 0`. Remove the current
  `borderRadius: checked ? '6px 0 0 6px' : '6px'` and `borderRight: checked ? 'none' : undefined`
  conditionals (lines 82–83) — `SplitButton` owns this.
- Bump the action SVGs (`:88,:90`) and the caret chevron (`:105`) to `14px`.
- Anchor the caret menu per §3.2 (relative group wrapper with `overflow:visible` +
  absolutely-positioned menu).
- Remove the `flexBasis:100%`/`width:100%` hack (line 74) — the §2.1 column makes it unnecessary; the
  detail panel (lines 117–162) keeps full-width via the block, not the flex hack. Inside that panel,
  change the inner badge at `:121` from `rounded-full` to `rounded-[8px]` (the one-radius rule, §1.0).
- The detail panel has `overflowY:auto` (`:118`); per §1.2 keep its `p-3` so focusable controls inside
  don't sit flush to the clip edge, and rely on the controls' own `overflow:visible` ring.
- Remove `mb-3` (line 74).

### 4.4 `ArticleAssistant.jsx`

- Trigger (lines 254–262) → `Button size="pill" variant="outline" icon={chatSvg}`. Bump the SVG (`:260`) to `14px`.
- `SourceBadge` (lines 90–96): change `rounded-full` → `rounded-[8px]` and align to the dense pill
  geometry (`--control-h-sm`, `--control-pad-x-sm`) — §1.0.
- Segmented tabs (lines 266–276) → the §3.4(b) macOS segmented control (filled active segment on a
  `bg-tertiary` track) with the **mandated hidden-bold sizer**, replacing the `border-b-2` underline.
  Preserve `role="tab"`/`aria-selected`.
- `×` (lines 278–280) → `IconButton variant="ghost"` 28×28, `14px` glyph.
- Inner `Summarize this article`/`Summarize this reference` button (lines 288–292) →
  `Button size="pill" variant="outline"` with §3.1 sizer-grid for the `Summarizing…` swap.
- Input + Send row (lines 352–367): set input `height:28px; box-sizing:border-box; padding:0 10px;
  border-radius:8px` (`:358`); **`box-sizing:border-box` is required (objection 8)**. Send →
  `Button size="pill" variant="primary"` with `minWidth:'64px'` and spinner-in-icon-slot while
  sending (`:362–365`).
- Remove `mb-3` (line 252).

### 4.5 `AIDetectionPanel.jsx` — **apply LAST (concurrent edit)**

**Required end-state interface contract (objection 6) — these must be TRUE after the merge,
regardless of how the concurrent workflow restructured the header:**

| element (current line) | MUST end up as |
|---|---|
| collapse chevron (`:154–166`) | `<IconButton size="sm" variant="ghost" rotated={!collapsed}>` (14px glyph) |
| likelihood band pill (`:167–174`) | dense status pill: `height:var(--control-h-sm)`, `padding:0 var(--control-pad-x-sm)`, `border-radius:var(--control-radius)` (8px), fill from `BAND_STYLES[band].bg` **repointed to `--status-*-fill`** |
| `score N` (`:175–180`) | plain `text-xs` muted span (unchanged) |
| `View in document` (`:190–203`) | `<Button size="pill" variant="primary">` (drop inline `focus:ring-2`) |
| `Show/Hide N flagged passages` (`:204–213`) | `<Button size="pill" variant="outline">` wrapped in the §3.1 sizer-grid for `Hide`↔`Show N flagged passages` |
| inner per-span score chip (`:271–278`) | `border-radius:8px` (§1.0) |
| card outer (`:148–150`) | **unchanged** — keep border/width/body-reveal |

- `BAND_STYLES` (`:83–89`): repoint `high/medium/low` `.bg` to `--status-error-fill /
  --status-warning-fill / --status-success-fill`; leave `fg`/`dot` and the abstain bands as-is.
- **Rebase:** if the concurrent workflow has already restructured this header, port the contract
  above onto whatever markup it produced rather than reverting it. The §5 post-merge checklist item
  for this file verifies the contract held.

### 4.6 `StatusSection.jsx` — **apply LAST (concurrent edit)**

This file (~1644 lines) primarily renders the thumbnail/preview overlay + status. **Required
end-state interface contract (objection 6):**

| element (current line) | MUST end up as |
|---|---|
| Cancel-check button (`:1551–1577`) | `<Button size="pill" variant="outline">` (the in-progress cancel control) |
| overlay close (`:307`), page-prev (`:325`), page-next (`:337`), find (`:384`) | `<IconButton>` (token radius `8px` + `.rc-control` focus ring), kept as overlay chrome on the dark scrim — they are NOT part of the article action family, so they may keep a circular *appearance* via an explicit `border-radius:9999px` override ONLY if they are true round icon chips; otherwise `8px` |

- Scope your change to **token adoption + the Cancel→`Button` swap**; do **not** restructure the
  overlay layout. Coordinate so the other workflow's structural edits win.
- **Rebase:** because this file is being edited concurrently, layer only the contract above onto the
  post-merge markup. The §5 checklist item verifies the Cancel control and the overlay icon buttons
  ended up using the shared primitives.

### 4.7 `AdditionalInfoBar.jsx` & `CorrectionsView.jsx`

- **`AdditionalInfoBar.jsx` `Pill` (lines 15–36) — NOW IN SCOPE for the radius decision (objection 1).**
  Change `borderRadius: 9999` (line 18) → `borderRadius: 'var(--control-radius)'` (8px) and align to
  the dense-pill geometry: `padding: 2px 9px` → keep (`9px` = `--control-pad-x-sm`), keep
  `fontSize: 11`, `fontWeight: 600`. This is **required** for the family to read as one — it is the
  most-frequently-seen pill in the app. (The fuller migration of `Pill` to wrap `<Button>`/`IconButton`
  remains a follow-up; the radius + geometry alignment is binding now.)
- `CorrectionsView.jsx` has ~15 hand-rolled `px-2/3 py-0.5/1 rounded` buttons (toolbar lines 551–697,
  per-row lines 881–951). These are a separate (tab-body) surface; migrating them to `Button` is a good
  follow-up but **not part of this spec's acceptance**.

---

## 5. Acceptance checklist (for a UI/UX reviewer)

**Consistency (R1)**
- [ ] The retraction pill, the gap-finder pre-run trigger, the citation-numbering main pill (**at rest, pre-check**), and the assistant trigger are **visually identical**: same 28px height, 12px pad-x, **8px radius**, 1px `--color-border`, `text-xs`/`500`, `--outline-fill` fill, 14px glyph.
- [ ] **ONE radius (`8px`) everywhere:** all status/action pills, the split-button, icon-buttons, the segmented control, the AI dense pill, `AdditionalInfoBar`'s `Pill` (`:18`), the assistant `SourceBadge` (`:91`), and the CitationIntegrity inner badge (`:121`) are `8px` rectangles. The ONLY `9999px` round in the family is the 8×8 status *dot* inside a pill.
- [ ] All four blocks left-align to the same vertical edge and are separated by a consistent 8px gap; the column is capped (~760px) so pills don't stretch full-width.
- [ ] The split-button's two segments share one height and show exactly **one** 1px divider; only the outer corners are rounded. **(Caret is a post-result addition, explicitly exempt from "identical at rest" — see next item.)**
- [ ] **Pre-check, the citation control has no caret/divider** (it's a lone pill identical to the others); the caret appears only after a check and fades/slides in without popping the main segment's left edge.
- [ ] Status fills come from `--status-*-fill` (the live translucent tints), **not** the opaque `--color-*-bg` tokens; in dark mode the pills are translucent green/amber/red tints, never the `#3b2f05` brown / `#3b1818` block. The AI band pill matches.
- [ ] Status colors change **only fill/text/border**, never geometry.
- [ ] Hover changes only the background (to an exact `*-fill-hover` token, +0.08 alpha / `--color-accent-hover` / `--outline-fill-hover`); border-color and text stay put; no size/radius change.
- [ ] Every control glyph is exactly **14px**; the status dot is 8px. No 13px/variable glyphs remain.
- [ ] Focus-visible rings are visible on keyboard focus, themed for dark mode, **and not clipped** on the split-button segments or inside the scrolling result panels (`overflow:visible` on controls; ring follows each segment's own outer-corner radius); absent on plain mouse click.

**Click-state stability (R2)**
- [ ] Clicking `Check for retractions` / re-check: the button's **width, height, radius, and border do not change**; only the icon→spinner and the label-inside-its-sizer-grid change. The sizer-grid holds the width of the **longest real label** (`No retractions — re-check`, 25 chars), so no `ch`-undersizing jump occurs.
- [ ] Clicking `Numbering consistent — re-check`: same — no width jump (sizer-grid sized to the 31-char `Numbering consistent — re-check`); the caret segment does not shift; the main segment's **left** corner does not move when the caret first appears.
- [ ] Opening the split-button caret menu does not move the button; the menu is anchored bottom-right, `overflow:visible`, and overlays.
- [ ] Toggling the gap-finder header (`show`/`hide`) and the AI-likelihood chevron rotates the chevron only; the header label text and header height are unchanged; the body reveals via `grid-rows` without shifting the header.
- [ ] Switching `Summarize`↔`Chat` does not reflow the segmented control: the active indicator is a background fill (not an added border), and the **hidden bold sizer** reserves the 600-weight width so the weight change cannot shift either tab.
- [ ] The assistant `Send` keeps a fixed width across disabled/enabled/sending (`minWidth:64px`); the input and Send share the same **28px** height (input has `box-sizing:border-box`, so it is 28px, not 30px).
- [ ] Toggling `Show N flagged passages`↔`Hide` does not change that button's width (sizer-grid holds both candidates).
- [ ] Disabled controls dim via `opacity:0.6` only — they keep their variant fill/border and do not visibly shrink or change color family (Button's disabled branch no longer swaps to grey).

**Grouping & rhythm (R3)**
- [ ] Each caption bubble sits directly beneath its own pill at 4px, left-aligned, as muted caption text (no border/background); only true result lists keep the card treatment.
- [ ] Removing/adding a block (e.g. when a check has no DOIs and `RetractionCheck`/`GapFinder` don't render) leaves no double or collapsed gap (rhythm owned by container `gap`, not child margins).
- [ ] The AI-likelihood card aligns its header pill/score/meta on one baseline and its right-hand actions use the shared `pill` size.

**Regression / accessibility**
- [ ] Light and dark themes both render correctly: borders/text from `--color-*`; fills from `--status-*-fill` (declared in both `:root` and `.dark`); no new hardcoded hex beyond the named translucent tints that already existed in source.
- [ ] `prefers-reduced-motion` disables the chevron-rotate, segment-fade, caret slide-in, and grid-row expand transitions (the `index.css:272` guard was extended).
- [ ] All controls remain keyboard-operable, with `aria-expanded` preserved on the chevrons/menus and `aria-selected`/`role="tab"` intact on the segmented tabs.

**Post-merge contract (concurrent files — objection 6)**
- [ ] `AIDetectionPanel.jsx` after rebase satisfies the §4.5 contract table: chevron = `IconButton size="sm"`; band pill = dense 8px status pill with `--status-*-fill`; `View in document` = `Button size=pill variant=primary`; `Show/Hide` = `Button size=pill variant=outline` + sizer-grid. If any reverted to an ad-hoc `<button>`/`<span>`, this item FAILS.
- [ ] `StatusSection.jsx` after rebase satisfies the §4.6 contract: the in-progress Cancel control is `Button size=pill variant=outline`; the overlay close/nav/find controls use `IconButton` with the `8px` token radius + `.rc-control` ring (or an explicit round override only for true circular chips).
- [ ] No console errors from the concurrent merge; the other workflow's structural changes are preserved and only the contract token treatment was layered on.
