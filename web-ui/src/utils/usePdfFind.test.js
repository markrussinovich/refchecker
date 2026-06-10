import { describe, expect, it } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import {
  findRangesInText,
  rangeToRects,
  computeFindMatches,
  wrapIndex,
  usePdfFind,
  MIN_FIND_LEN,
} from './usePdfFind'

// A tiny fixture of two "pages" mirroring NativePdfViewer's per-page record:
// pageText is the concatenated text-layer string; items carry char-spans + a
// rect. The rects here are arbitrary but distinguishable per item so we can
// assert which items a match resolved to.
function item(start, end, x, y, w = 10, h = 4) {
  return { start, end, x, y, w, h }
}

// "the cat sat" / "the cat ran" — "cat" appears on both pages, "the" twice/page.
const PAGES = [
  {
    pageNumber: 1,
    pageText: 'the cat sat',
    items: [item(0, 3, 0, 0), item(3, 8, 10, 0), item(8, 11, 30, 0)], // "the","_cat_","sat"
  },
  {
    pageNumber: 2,
    pageText: 'the cat ran',
    items: [item(0, 3, 0, 50), item(3, 8, 10, 50), item(8, 11, 30, 50)],
  },
]

describe('findRangesInText (R42 match logic)', () => {
  it('finds every non-overlapping occurrence, case-insensitively', () => {
    // "ab" appears 3 times; the gaps ("X") between are not matched.
    expect(findRangesInText('abXabXab', 'ab')).toEqual([[0, 2], [3, 5], [6, 8]])
  })

  it('ignores queries shorter than MIN_FIND_LEN', () => {
    expect(MIN_FIND_LEN).toBe(2)
    expect(findRangesInText('the cat', 'a')).toEqual([])
    expect(findRangesInText('the cat', '')).toEqual([])
  })

  it('matches case-insensitively and returns char ranges', () => {
    expect(findRangesInText('The CAT cat', 'cat')).toEqual([[4, 7], [8, 11]])
  })

  it('does not produce overlapping matches', () => {
    // "aaaa" with query "aa" → [0,2],[2,4], NOT [0,2],[1,3],[2,4].
    expect(findRangesInText('aaaa', 'aa')).toEqual([[0, 2], [2, 4]])
  })

  it('is whitespace-tolerant: a query space matches a PDF soft break', () => {
    // PDF extraction yields a newline/double space between the two words.
    expect(findRangesInText('foo\nbar baz', 'bar baz')).toEqual([[4, 11]])
    expect(findRangesInText('alpha   beta', 'alpha beta')).toEqual([[0, 12]])
  })

  it('escapes regex metacharacters in the query (no crash, literal match)', () => {
    expect(findRangesInText('cost is $5.00 today', '$5.00')).toEqual([[8, 13]])
    expect(findRangesInText('a (b) c', '(b)')).toEqual([[2, 5]])
  })
})

describe('rangeToRects', () => {
  it('returns one rect per overlapped item with width', () => {
    const items = [item(0, 3, 0, 0), item(3, 8, 10, 0), item(8, 11, 30, 0)]
    // range [4,7] (inside "cat") overlaps only the middle item.
    expect(rangeToRects(items, [4, 7])).toEqual([{ x: 10, y: 0, w: 10, h: 4 }])
  })

  it('spans multiple items when the match crosses item boundaries', () => {
    const items = [item(0, 3, 0, 0), item(3, 8, 10, 0), item(8, 11, 30, 0)]
    // range [0,11] covers all three items → three rects (per-line/per-item).
    expect(rangeToRects(items, [0, 11])).toHaveLength(3)
  })

  it('drops zero-width items so navigation never lands on an invisible rect', () => {
    const items = [item(0, 5, 0, 0, 0)] // w === 0
    expect(rangeToRects(items, [0, 5])).toEqual([])
  })
})

describe('computeFindMatches (R42 cross-page ordering)', () => {
  it('returns an empty list for a short/blank query', () => {
    expect(computeFindMatches(PAGES, 'a')).toEqual([])
    expect(computeFindMatches(PAGES, '')).toEqual([])
    expect(computeFindMatches([], 'cat')).toEqual([])
  })

  it('orders matches by page then char offset and assigns global indices', () => {
    const matches = computeFindMatches(PAGES, 'the')
    // "the" appears once per page → 2 matches, page 1 before page 2.
    expect(matches.map((m) => m.pageNumber)).toEqual([1, 2])
    expect(matches.map((m) => m.matchIndex)).toEqual([0, 1])
    expect(matches[0].range).toEqual([0, 3])
  })

  it('resolves each match to its drawing rects', () => {
    const matches = computeFindMatches(PAGES, 'cat')
    expect(matches).toHaveLength(2)
    // "cat" sits inside the middle item on each page.
    expect(matches[0].rects).toEqual([{ x: 10, y: 0, w: 10, h: 4 }])
    expect(matches[1].rects).toEqual([{ x: 10, y: 50, w: 10, h: 4 }])
  })

  it('drops matches whose text items had no geometry', () => {
    const pages = [{ pageNumber: 1, pageText: 'cat', items: [item(0, 3, 0, 0, 0)] }]
    expect(computeFindMatches(pages, 'cat')).toEqual([])
  })
})

describe('wrapIndex', () => {
  it('wraps around in both directions', () => {
    expect(wrapIndex(0, 3)).toBe(0)
    expect(wrapIndex(3, 3)).toBe(0)
    expect(wrapIndex(-1, 3)).toBe(2)
    expect(wrapIndex(4, 3)).toBe(1)
  })
  it('is safe on an empty list', () => {
    expect(wrapIndex(0, 0)).toBe(0)
    expect(wrapIndex(5, 0)).toBe(0)
  })
})

describe('usePdfFind hook (navigation)', () => {
  it('starts empty with no query', () => {
    const { result } = renderHook(() => usePdfFind(PAGES))
    expect(result.current.matchCount).toBe(0)
    expect(result.current.current).toBe(0)
    expect(result.current.currentMatch).toBeNull()
  })

  it('computes matches when a query is set and resets the index to the first hit', () => {
    const { result } = renderHook(() => usePdfFind(PAGES))
    act(() => result.current.setQuery('the'))
    expect(result.current.matchCount).toBe(2)
    expect(result.current.current).toBe(0)
    expect(result.current.currentMatch.pageNumber).toBe(1)
  })

  it('next/prev navigate with wrap-around', () => {
    const { result } = renderHook(() => usePdfFind(PAGES))
    act(() => result.current.setQuery('cat')) // 2 matches
    expect(result.current.current).toBe(0)
    act(() => result.current.next())
    expect(result.current.current).toBe(1)
    act(() => result.current.next()) // wraps back to 0
    expect(result.current.current).toBe(0)
    act(() => result.current.prev()) // wraps to last
    expect(result.current.current).toBe(1)
  })

  it('isMatchCurrent flags exactly the active match', () => {
    const { result } = renderHook(() => usePdfFind(PAGES))
    act(() => result.current.setQuery('cat'))
    const [first, second] = result.current.matches
    expect(result.current.isMatchCurrent(first)).toBe(true)
    expect(result.current.isMatchCurrent(second)).toBe(false)
    act(() => result.current.next())
    expect(result.current.isMatchCurrent(second)).toBe(true)
  })

  it('clear() wipes the query and resets the index', () => {
    const { result } = renderHook(() => usePdfFind(PAGES))
    act(() => result.current.setQuery('the'))
    act(() => result.current.next())
    act(() => result.current.clear())
    expect(result.current.query).toBe('')
    expect(result.current.matchCount).toBe(0)
    expect(result.current.current).toBe(0)
  })

  it('changing the query resets the active index back to the first match', () => {
    const { result } = renderHook(() => usePdfFind(PAGES))
    act(() => result.current.setQuery('cat'))
    act(() => result.current.next()) // index 1
    expect(result.current.current).toBe(1)
    act(() => result.current.setQuery('the')) // new query → back to 0
    expect(result.current.current).toBe(0)
  })
})
