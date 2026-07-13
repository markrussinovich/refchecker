import React from 'react'

// Lightweight, dependency-free markdown renderer for LLM chat/summary output.
//
// Why not a library: the assistant emits a small, predictable subset of markdown
// (bold, italics, inline code, fenced code, bullet/numbered lists, headings,
// blockquotes, links). Rendering it ourselves avoids pulling remark/rehype and,
// crucially, is XSS-safe by construction: we only ever build React elements from
// parsed tokens — never dangerouslySetInnerHTML — so no author-supplied HTML can
// execute. URLs are scheme-checked before becoming links.

// Only allow links we know are safe to open; anything else renders as plain text
// (prevents javascript:, data:, etc.).
function safeHref(url) {
  const u = String(url || '').trim()
  if (/^https?:\/\//i.test(u) || /^mailto:/i.test(u) || u.startsWith('/')) return u
  return null
}

// Inline formatting: scan for the EARLIEST of the supported markers, emit the
// preceding plain text, render the marker, then continue after it. Code is
// considered first so ** / _ inside `code` stay literal. Recurses for nesting.
function renderInline(text, kp) {
  const out = []
  let rest = String(text ?? '')
  let key = 0
  const rules = [
    // inline code
    { re: /`([^`]+)`/, make: (m) => (
      <code key={`${kp}-${key}`} style={{
        fontFamily: 'var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
        background: 'var(--color-bg-tertiary)', borderRadius: 4, padding: '0 4px', fontSize: '0.92em',
      }}>{m[1]}</code>
    ) },
    // links
    { re: /\[([^\]]+)\]\(([^)\s]+)\)/, make: (m) => {
      const href = safeHref(m[2])
      if (!href) return <React.Fragment key={`${kp}-${key}`}>{m[0]}</React.Fragment>
      return (
        <a key={`${kp}-${key}`} href={href} target="_blank" rel="noopener noreferrer"
          style={{ color: 'var(--color-accent, #3b82f6)', textDecoration: 'underline' }}>
          {renderInline(m[1], `${kp}-${key}l`)}
        </a>
      )
    } },
    // bold
    { re: /\*\*([\s\S]+?)\*\*|__([\s\S]+?)__/, make: (m) => (
      <strong key={`${kp}-${key}`}>{renderInline(m[1] ?? m[2], `${kp}-${key}b`)}</strong>
    ) },
    // strikethrough
    { re: /~~([\s\S]+?)~~/, make: (m) => (
      <del key={`${kp}-${key}`}>{renderInline(m[1], `${kp}-${key}s`)}</del>
    ) },
    // italic (single * or _), not the ** / __ already handled above
    { re: /\*([^*\n]+)\*|_([^_\n]+)_/, make: (m) => (
      <em key={`${kp}-${key}`}>{renderInline(m[1] ?? m[2], `${kp}-${key}i`)}</em>
    ) },
  ]
  while (rest.length) {
    let best = null
    for (const r of rules) {
      const m = r.re.exec(rest)
      if (m && (best === null || m.index < best.index)) best = { index: m.index, len: m[0].length, make: r.make, m }
    }
    if (!best) { out.push(<React.Fragment key={`${kp}-t${key++}`}>{rest}</React.Fragment>); break }
    if (best.index > 0) out.push(<React.Fragment key={`${kp}-t${key++}`}>{rest.slice(0, best.index)}</React.Fragment>)
    out.push(best.make(best.m))
    key++
    rest = rest.slice(best.index + best.len)
  }
  return out
}

// Split raw text into block-level elements: fenced code, headings, blockquotes,
// unordered/ordered lists, horizontal rules, and paragraphs (blank-line
// separated). Line breaks inside a paragraph become <br>.
function parseBlocks(src) {
  const lines = String(src ?? '').replace(/\r\n?/g, '\n').split('\n')
  const blocks = []
  let i = 0
  let k = 0
  const isUl = (l) => /^\s*[-*+]\s+/.test(l)
  const isOl = (l) => /^\s*\d+\.\s+/.test(l)
  while (i < lines.length) {
    const line = lines[i]
    // fenced code block
    const fence = line.match(/^\s*```(.*)$/)
    if (fence) {
      const body = []
      i++
      while (i < lines.length && !/^\s*```/.test(lines[i])) { body.push(lines[i]); i++ }
      if (i < lines.length) i++ // consume closing fence
      blocks.push(
        <pre key={`b${k++}`} style={{
          background: 'var(--color-bg-tertiary)', borderRadius: 6, padding: '8px 10px',
          overflowX: 'auto', margin: '6px 0', fontSize: '0.85em',
          fontFamily: 'var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
        }}><code>{body.join('\n')}</code></pre>
      )
      continue
    }
    // blank line
    if (/^\s*$/.test(line)) { i++; continue }
    // horizontal rule
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { blocks.push(<hr key={`b${k++}`} style={{ border: 0, borderTop: '1px solid var(--color-border)', margin: '8px 0' }} />); i++; continue }
    // heading
    const h = line.match(/^\s*(#{1,6})\s+(.*)$/)
    if (h) {
      const level = h[1].length
      const size = [null, '1.25em', '1.15em', '1.05em', '1em', '0.95em', '0.9em'][level]
      blocks.push(
        <div key={`b${k++}`} style={{ fontWeight: 700, fontSize: size, margin: '8px 0 4px' }}>
          {renderInline(h[2], `b${k}`)}
        </div>
      )
      i++
      continue
    }
    // blockquote
    if (/^\s*>\s?/.test(line)) {
      const body = []
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) { body.push(lines[i].replace(/^\s*>\s?/, '')); i++ }
      blocks.push(
        <blockquote key={`b${k++}`} style={{
          borderLeft: '3px solid var(--color-border)', paddingLeft: 10, margin: '6px 0',
          color: 'var(--color-text-secondary)',
        }}>{parseBlocks(body.join('\n'))}</blockquote>
      )
      continue
    }
    // unordered list
    if (isUl(line)) {
      const items = []
      while (i < lines.length && isUl(lines[i])) { items.push(lines[i].replace(/^\s*[-*+]\s+/, '')); i++ }
      blocks.push(
        <ul key={`b${k++}`} style={{ margin: '4px 0', paddingLeft: 20, listStyle: 'disc' }}>
          {items.map((it, idx) => <li key={idx} style={{ margin: '2px 0' }}>{renderInline(it, `b${k}-${idx}`)}</li>)}
        </ul>
      )
      continue
    }
    // ordered list
    if (isOl(line)) {
      const items = []
      let start = parseInt((line.match(/^\s*(\d+)\./) || [])[1] || '1', 10)
      while (i < lines.length && isOl(lines[i])) { items.push(lines[i].replace(/^\s*\d+\.\s+/, '')); i++ }
      blocks.push(
        <ol key={`b${k++}`} start={start} style={{ margin: '4px 0', paddingLeft: 22 }}>
          {items.map((it, idx) => <li key={idx} style={{ margin: '2px 0' }}>{renderInline(it, `b${k}-${idx}`)}</li>)}
        </ol>
      )
      continue
    }
    // paragraph: gather consecutive non-blank, non-structural lines
    const para = []
    while (
      i < lines.length && !/^\s*$/.test(lines[i]) && !/^\s*```/.test(lines[i]) &&
      !/^\s*(#{1,6})\s+/.test(lines[i]) && !/^\s*>\s?/.test(lines[i]) &&
      !isUl(lines[i]) && !isOl(lines[i]) && !/^\s*([-*_])\1{2,}\s*$/.test(lines[i])
    ) { para.push(lines[i]); i++ }
    blocks.push(
      <p key={`b${k++}`} style={{ margin: '4px 0', lineHeight: 1.5 }}>
        {para.map((ln, idx) => (
          <React.Fragment key={idx}>
            {idx > 0 && <br />}
            {renderInline(ln, `b${k}-${idx}`)}
          </React.Fragment>
        ))}
      </p>
    )
  }
  return blocks
}

/**
 * Render a markdown string as safe React elements.
 * Supports: **bold**, _italic_, `code`, fenced code, # headings, blockquotes,
 * - / * bullet lists, 1. numbered lists, [links](url), ~~strikethrough~~, ---.
 */
export default function Markdown({ text, className, style }) {
  return (
    <div className={className} style={{ ...(style || {}) }}>
      {parseBlocks(text)}
    </div>
  )
}

// safeHref is exported for unit testing of URL sanitization. Co-located per the
// project's existing pattern (see StatusSection/NativePdfViewer helper exports).
// eslint-disable-next-line react-refresh/only-export-components
export { safeHref }
