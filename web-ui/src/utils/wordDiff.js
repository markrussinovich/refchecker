/**
 * Word-level diff using LCS. Returns a list of ops:
 *   { type: 'eq' | 'del' | 'add', word: string, sep: string }
 *
 * `sep` is the whitespace that followed the original word, so callers can
 * rebuild a faithful rendering without losing spacing.
 *
 * Designed for short strings (citation lines) — O(n*m) memory is fine here.
 */
export function wordDiff(a, b) {
  const tokenize = (s) => {
    if (!s) return []
    const out = []
    const re = /(\S+)(\s*)/g
    let m
    while ((m = re.exec(s))) out.push({ word: m[1], sep: m[2] || '' })
    return out
  }
  const A = tokenize(a)
  const B = tokenize(b)
  const n = A.length
  const m = B.length
  const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1))
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      dp[i][j] = A[i - 1].word === B[j - 1].word
        ? dp[i - 1][j - 1] + 1
        : Math.max(dp[i - 1][j], dp[i][j - 1])
    }
  }
  const ops = []
  let i = n, j = m
  while (i > 0 && j > 0) {
    if (A[i - 1].word === B[j - 1].word) {
      ops.unshift({ type: 'eq', word: A[i - 1].word, sep: A[i - 1].sep })
      i--; j--
    } else if (dp[i - 1][j] >= dp[i][j - 1]) {
      ops.unshift({ type: 'del', word: A[i - 1].word, sep: A[i - 1].sep })
      i--
    } else {
      ops.unshift({ type: 'add', word: B[j - 1].word, sep: B[j - 1].sep })
      j--
    }
  }
  while (i > 0) { ops.unshift({ type: 'del', word: A[i - 1].word, sep: A[i - 1].sep }); i-- }
  while (j > 0) { ops.unshift({ type: 'add', word: B[j - 1].word, sep: B[j - 1].sep }); j-- }
  return ops
}
