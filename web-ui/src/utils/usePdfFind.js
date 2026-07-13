import { useCallback, useMemo, useRef, useState } from 'react'

/**
 * R42 — Native-PDF find/search controller (custom, text-layer based).
 *
 * pdf.js exposes no ready-to-use find UI here; we render each page as a canvas
 * with absolutely-positioned highlight boxes (NativePdfViewer), and we already
 * extract, per page, the concatenated text plus each text item's char-span and
 * device-space bbox. This controller reuses that exact geometry to implement a
 * Cmd/Ctrl+F find: normalize → match (case-insensitive, whitespace-tolerant) →
 * map each match's char range onto the covering item boxes → ordered match list
 * with per-match rects → current-index tracking + next/prev (wrap-around).
 *
 * It is intentionally a PURE function over the page geometry so the
 * match/navigation logic is unit-testable without pdf.js or the DOM.
 *
 * Page shape expected (mirrors NativePdfViewer's per-page record):
 *   { pageNumber, pageText, items: [{ start, end, x, y, w, h }] }
 * where `start`/`end` are char offsets into `pageText` and x/y/w/h are the
 * item's rect in the SAME device space the highlight overlays use (i.e. already
 * multiplied by the current paint SCALE).
 *
 * The find color is deliberately yellow (current = accent/blue) so it never
 * collides with the R14 status/citation highlight hues (green/red/amber/violet/
 * orange/slate). Those literals live in the viewer; this file is geometry only.
 */

// Collapse runs of whitespace to a single space; PDF text extraction is noisy.
const collapseWs = (s) => String(s || '').replace(/\s+/g, ' ')

/**
 * Minimum query length before we search. One- or two-character queries match
 * almost everything and produce a useless, jumpy result set; mirror the
 * extracted-text viewer's `>= 2` gate.
 */
export const MIN_FIND_LEN = 2

/**
 * Find every (non-overlapping) case-insensitive occurrence of `query` in
 * `text`, returning [start, end] char ranges. Whitespace-tolerant: a run of
 * whitespace in `text` matches a single space in the (collapsed) query, so a
 * query that spans a soft line break in the PDF still matches.
 *
 * @param {string} text
 * @param {string} query
 * @returns {Array<[number, number]>}
 */
export function findRangesInText(text, query) {
  const q = collapseWs(query).trim()
  if (q.length < MIN_FIND_LEN || !text) return []
  // Build a whitespace-tolerant, case-insensitive regex from the literal query:
  // escape regex metachars, then let each space match one-or-more whitespace.
  const escaped = q
    .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    .replace(/ /g, '\\s+')
  let re
  try {
    re = new RegExp(escaped, 'gi')
  } catch {
    return []
  }
  const out = []
  let m
  let guard = 0
  while ((m = re.exec(text)) !== null) {
    const start = m.index
    const end = start + m[0].length
    if (end > start) out.push([start, end])
    // Never get stuck on a zero-width match; always advance past this one.
    re.lastIndex = Math.max(end, start + 1)
    if (++guard > 100000) break // pathological-input safety valve
  }
  return out
}

/**
 * Map a [start,end] char range to the union of the item rects it overlaps.
 * Returns one rect per covered item (kept separate so a match that wraps lines
 * draws a box per line rather than one giant bounding box).
 *
 * @param {Array<{start:number,end:number,x:number,y:number,w:number,h:number}>} items
 * @param {[number, number]} range
 * @returns {Array<{x:number,y:number,w:number,h:number}>}
 */
export function rangeToRects(items, [qs, qe]) {
  const rects = []
  for (const it of items) {
    if (it.end > qs && it.start < qe && it.w > 0) {
      rects.push({ x: it.x, y: it.y, w: it.w, h: it.h })
    }
  }
  return rects
}

/**
 * Compute the full, ordered find-match list across all pages for a query.
 *
 * Matches are ordered by page then by char offset, so next/prev walks the
 * document top-to-bottom. Each match carries its page number, char range, and
 * the rects to draw. Matches that resolve to zero rects (text item had no
 * geometry) are dropped so navigation never lands on an invisible match.
 *
 * @param {Array<{pageNumber:number, pageText:string, items:Array}>} pages
 * @param {string} query
 * @returns {Array<{pageNumber:number, range:[number,number], rects:Array, matchIndex:number}>}
 */
export function computeFindMatches(pages, query) {
  const q = collapseWs(query).trim()
  if (q.length < MIN_FIND_LEN || !Array.isArray(pages) || !pages.length) return []
  const matches = []
  for (const p of pages) {
    const ranges = findRangesInText(p.pageText || '', q)
    for (const range of ranges) {
      const rects = rangeToRects(p.items || [], range)
      if (!rects.length) continue
      matches.push({ pageNumber: p.pageNumber, range, rects })
    }
  }
  // Stable order: page ascending, then char offset ascending.
  matches.sort((a, b) => (a.pageNumber - b.pageNumber) || (a.range[0] - b.range[0]))
  return matches.map((m, i) => ({ ...m, matchIndex: i }))
}

/**
 * Clamp a desired index into the match list with wrap-around. Returns 0 when
 * the list is empty so callers can read a stable current index.
 */
export function wrapIndex(index, count) {
  if (!count) return 0
  return ((index % count) + count) % count
}

/**
 * React hook wrapping the find controller: owns the query + current-match index,
 * recomputes the match list (memoized) whenever the query or page geometry
 * changes, and exposes next/prev (wrap-around) + clear. Pure logic — the viewer
 * decides how to render the rects + which match is "current".
 *
 * @param {Array} pages  per-page geometry (see computeFindMatches).
 * @returns {{
 *   query: string,
 *   setQuery: (q: string) => void,
 *   matches: Array,
 *   matchCount: number,
 *   current: number,            // 0-based index of the active match (0 when none)
 *   currentMatch: object|null,  // the active match record, or null
 *   next: () => void,
 *   prev: () => void,
 *   clear: () => void,
 *   isMatchCurrent: (m: object) => boolean,
 * }}
 */
export function usePdfFind(pages) {
  const [query, setQueryRaw] = useState('')
  const [current, setCurrent] = useState(0)
  // Remember the last query the index was reset for, so typing resets the
  // active match to the first hit (don't keep a stale index from a prior query).
  const lastQueryRef = useRef('')

  const matches = useMemo(() => computeFindMatches(pages, query), [pages, query])
  const matchCount = matches.length

  const setQuery = useCallback((q) => {
    setQueryRaw(q)
    if (q !== lastQueryRef.current) {
      lastQueryRef.current = q
      setCurrent(0)
    }
  }, [])

  const next = useCallback(() => {
    setCurrent((c) => wrapIndex(c + 1, matchCount))
  }, [matchCount])

  const prev = useCallback(() => {
    setCurrent((c) => wrapIndex(c - 1, matchCount))
  }, [matchCount])

  const clear = useCallback(() => {
    setQueryRaw('')
    lastQueryRef.current = ''
    setCurrent(0)
  }, [])

  // Keep `current` valid if the match list shrinks (e.g. geometry re-rendered).
  const safeCurrent = matchCount ? wrapIndex(current, matchCount) : 0
  const currentMatch = matchCount ? matches[safeCurrent] : null

  const isMatchCurrent = useCallback(
    (m) => !!currentMatch && m === currentMatch,
    [currentMatch],
  )

  return {
    query,
    setQuery,
    matches,
    matchCount,
    current: safeCurrent,
    currentMatch,
    next,
    prev,
    clear,
    isMatchCurrent,
  }
}

export default usePdfFind
