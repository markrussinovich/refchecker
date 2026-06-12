import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useActionGrid } from './ActionPanelGrid'

const GRID_ID = 'assistant'
import { getArticleSummary, postArticleChat, postReferenceFulltext } from '../../utils/api'
import { useConfigStore } from '../../stores/useConfigStore'
import { useSettingsStore } from '../../stores/useSettingsStore'
import Button from '../common/Button'
import IconButton from '../common/IconButton'
import LabelSizer from '../common/LabelSizer'

const CHAT_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
)
const CLOSE_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
)

// macOS-native segmented tab with the MANDATED hidden-bold sizer
// (BUTTON_DESIGN §3.4b): a hidden 600-weight copy reserves the active width so
// switching Summarize↔Chat (which changes the weight) can never reflow a tab.
function SegmentedTab({ label, active, onClick }) {
  return (
    <button type="button" role="tab" aria-selected={active} onClick={onClick}
      className="rc-segment rc-control">
      <span aria-hidden="true"
        style={{ fontWeight: 600, visibility: 'hidden', display: 'block', height: 0, overflow: 'hidden', padding: '0 10px' }}>
        {label}
      </span>
      <span style={{
        fontWeight: active ? 600 : 500, position: 'absolute', inset: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        {label}
      </span>
    </button>
  )
}

/**
 * Grounded Chat-with-PDF + Summarize (EPIC-D). Two tabs:
 *   • Summarize — a one-shot grounded summary of the article.
 *   • Chat — ask questions answered ONLY from the article's own text.
 *
 * Honest by construction:
 *   • The backend answers strictly from the delimited document block and
 *     abstains ("the article does not state this") rather than guessing.
 *   • A source badge shows whether the answer is grounded in the full PDF
 *     body or only the abstract. When source==='abstract' an explicit
 *     "answering from abstract only" banner is shown.
 *   • When no article text is available (source==='none') the feature is
 *     disabled honestly — no LLM call is made.
 *   • When no Chat & Summarize LLM is configured, a clear, non-blocking
 *     empty-state links straight to Settings → LLM rather than failing on
 *     the first request.
 */

const SOURCE_LABEL = { pdf: 'full text', abstract: 'abstract only', none: 'no text' }

// Build an honest, real-data-only context block for a single reference. Used by
// the per-reference Chat & Summarize mode: since the grounded backend grounds on
// the HOST paper's document (not each reference's full text), we hand the model
// the reference's own metadata + abstract/claim that we DO have, and tell the
// user plainly what it's grounded in. Returns null when nothing real is known.
function buildReferenceContext(reference) {
  if (!reference) return null
  const e = reference.enrichment || {}
  const title = (reference.title || '').trim()
  const abstract = (e.abstract || '').trim()
  const claim = (e.tldr || '').trim()
  const doi = reference.doi || reference.verified_doi || null
  const ids = []
  if (doi) ids.push(`DOI: ${String(doi).replace(/^https?:\/\/(dx\.)?doi\.org\//i, '')}`)
  if (reference.arxiv_id) ids.push(`arXiv: ${reference.arxiv_id}`)
  const authors = (typeof reference.authors === 'string'
    ? reference.authors
    : Array.isArray(reference.authors)
      ? reference.authors.map(a => (typeof a === 'string' ? a : (a?.name || ''))).filter(Boolean).join(', ')
      : '').trim()
  const year = reference.year ? String(reference.year) : ''
  const venue = (reference.venue || e.venue || '').trim()

  // The strongest real grounding we have for the reference, in priority order.
  const grounding = abstract ? 'abstract' : claim ? 'claim' : title ? 'title' : 'none'
  if (grounding === 'none') return null

  const lines = []
  if (title) lines.push(`Title: ${title}`)
  if (authors) lines.push(`Authors: ${authors}`)
  if (year || venue) lines.push(`Published: ${[venue, year].filter(Boolean).join(', ')}`)
  if (ids.length) lines.push(ids.join('  '))
  if (abstract) lines.push(`Abstract: ${abstract}`)
  else if (claim) lines.push(`Claim (TL;DR): ${claim}`)
  return { text: lines.join('\n'), grounding, title }
}

/**
 * Non-blocking empty-state shown when no Chat & Summarize LLM is configured.
 * Honest: explains why nothing can run yet and links to the exact Settings
 * pane where the model is selected, instead of a silent disable or a
 * confusing backend error on the first request.
 */
function NoModelEmptyState({ verb }) {
  const openSettings = useSettingsStore(s => s.openSettings)
  return (
    <div className="text-sm rounded-md px-3 py-2.5"
      style={{ color: 'var(--color-text-secondary)', background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}>
      No Chat &amp; Summarize model is configured yet, so there’s nothing to {verb} with.
      {' '}
      <button type="button" onClick={() => openSettings('LLM')}
        className="underline font-medium"
        style={{ color: 'var(--color-accent)' }}>
        Configure a Chat &amp; Summarize model in Settings →
      </button>
    </div>
  )
}

function SourceBadge({ source }) {
  if (!source) return null
  const isAbstract = source === 'abstract'
  const color = source === 'pdf' ? 'var(--color-success)'
    : isAbstract ? 'var(--color-warning)' : 'var(--color-text-muted)'
  return (
    <span className="inline-flex items-center text-xs font-semibold"
      style={{
        color, background: 'var(--color-bg-tertiary)', border: `1px solid ${color}`,
        borderRadius: 'var(--control-radius)', padding: '0 var(--control-pad-x-sm)',
        height: 'var(--control-h-sm)', boxSizing: 'border-box',
      }}
      title="Where the answer is grounded">
      grounded: {SOURCE_LABEL[source] || source}
    </span>
  )
}

// Honest grounding banner. Shown when answers are limited by the available
// source text: 'abstract' (abstract only) or 'none' (no document text at all).
function SourceBanner({ source }) {
  if (source !== 'abstract' && source !== 'none') return null
  const text = source === 'abstract'
    ? 'Answering from the abstract only — the full text wasn’t available for this article, so answers are limited to what the abstract states.'
    : 'No document text is available for this article, so there’s nothing to ground answers in. This can happen when the PDF couldn’t be read or hasn’t been processed yet.'
  return (
    <div className="text-xs mt-2 rounded-md px-2.5 py-1.5"
      style={{ color: 'var(--color-warning)', background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-warning)' }}>
      {text}
    </div>
  )
}

// Honest banner for per-reference mode (R43).
//
// We first try to fetch the reference's OWN open-access full text (arXiv →
// OpenAlex best_oa_location / Unpaywall). Three honest states:
//   • fetching  — retrieval is in flight ("Fetching full text…").
//   • 'pdf'     — real full text was fetched → "grounded in the full text".
//   • else      — no OA PDF resolved → fall back to the reference's real
//                 metadata (abstract → TL;DR claim → title) and keep the
//                 existing TL;DR-only disclaimer VERBATIM (no fabrication).
function ReferenceGroundingBanner({ grounding, fetching, hasFullText }) {
  if (fetching) {
    return (
      <div className="text-xs mt-2 mb-2 rounded-md px-2.5 py-1.5"
        style={{ color: 'var(--color-text-secondary)', background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}>
        Fetching full text…
      </div>
    )
  }
  if (hasFullText) {
    return (
      <div className="text-xs mt-2 mb-2 rounded-md px-2.5 py-1.5"
        style={{ color: 'var(--color-success)', background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-success)' }}>
        Grounded in the full text of this reference — answers come only from the fetched document.
        The assistant won’t invent details beyond what it says.
      </div>
    )
  }
  const what = grounding === 'abstract'
    ? 'this reference’s abstract'
    : grounding === 'claim'
      ? 'this reference’s one-line claim (TL;DR)'
      : 'this reference’s title and metadata only'
  return (
    <div className="text-xs mt-2 mb-2 rounded-md px-2.5 py-1.5"
      style={{ color: 'var(--color-warning)', background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-warning)' }}>
      The reference’s full text isn’t available here, so answers are grounded only in {what}.
      The assistant won’t invent details beyond what’s shown — if something isn’t in the reference’s
      available text, it will say so.
    </div>
  )
}

/**
 * @param {object} props
 * @param {number} props.checkId  The host check to ground the grounded backend on.
 * @param {object} [props.reference]  When provided, the assistant chats/summarizes
 *   about THIS reference instead of the host paper. Since the grounded backend
 *   grounds on the host paper's document (not the reference's own full text,
 *   which we don't have), reference-mode hands the model the reference's real
 *   metadata + abstract/claim and labels itself honestly.
 * @param {string} [props.label]  Optional custom trigger-button label.
 */
export default function ArticleAssistant({ checkId, reference = null, label = null }) {
  // R34 — Chat-with-PDF and Summarize route to independently-selectable models.
  // sendChat uses the chat config; runSummary uses the summary config (which
  // falls back to the chat → extraction/default chain when unset).
  const getSelectedChatConfig = useConfigStore(s => s.getSelectedChatConfig)
  const getSelectedSummaryConfig = useConfigStore(s => s.getSelectedSummaryConfig)
  // Reactively track whether any chat/summarize-capable LLM is configured. The
  // resolved configs fall back to the extraction/default config, so this is null
  // only when no LLM is configured at all (subscribe to configs so the
  // empty-state clears the moment a model is added in Settings).
  const hasChatModel = useConfigStore(s => (s.configs?.length || 0) > 0)
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState('summarize')
  // In the 2×2 action grid the open/close state is owned by the grid
  // coordinator (accordion); standalone (reference-card mode) it uses local
  // `open`. The reference-grounding effect below is reference-mode-only, so it
  // never fires in grid (article) mode — driving open via the grid is safe.
  const grid = useActionGrid()
  const isOpen = grid ? grid.isOpen(GRID_ID) : open
  const openPanel = () => { if (grid) grid.open(GRID_ID); else setOpen(true) }
  const closePanel = () => { if (grid) grid.close(); else setOpen(false) }

  // Per-reference mode: real, no-fabrication context block built from the
  // reference's own metadata + abstract/claim (whatever we honestly have).
  const refContext = reference ? buildReferenceContext(reference) : null
  const isRefMode = !!reference

  // R43 — per-reference full-text retrieval. When chat opens for a reference,
  // we try to fetch its OWN open-access PDF and ground on the real document.
  // States: { fetching, fullText|null }. fullText is REAL fetched text only;
  // on a miss it stays null and the existing TL;DR disclaimer is kept verbatim.
  const [refFullText, setRefFullText] = useState({ fetching: false, fullText: null, done: false })

  // Summarize state
  const [sum, setSum] = useState({ loading: false, data: null, error: null })
  // Chat state
  const [messages, setMessages] = useState([]) // [{role, content}]
  const [input, setInput] = useState('')
  const [chatSource, setChatSource] = useState(null)
  const [chat, setChat] = useState({ loading: false, error: null })

  // R43 — trigger the reference full-text fetch the first time the panel opens
  // in reference mode. Soft-fails to the TL;DR fallback on any error; runs once
  // per opened reference. Declared before the early returns to honor the Rules
  // of Hooks (the effect body no-ops in non-ref / closed states).
  const refIdentityKey = isRefMode
    ? (reference?.arxiv_id || reference?.doi || reference?.verified_doi || reference?.title || '')
    : ''
  useEffect(() => {
    if (!open || !isRefMode || !checkId || checkId <= 0) return
    if (refFullText.done || refFullText.fetching) return
    let cancelled = false
    setRefFullText({ fetching: true, fullText: null, done: false })
    postReferenceFulltext(checkId, reference)
      .then((res) => {
        if (cancelled) return
        const d = res?.data || {}
        const ft = d.source === 'pdf' && typeof d.grounding === 'string' && d.grounding.trim()
          ? d.grounding
          : null
        setRefFullText({ fetching: false, fullText: ft, done: true })
      })
      .catch(() => {
        // Honest fallback: keep the TL;DR disclaimer verbatim, never fabricate.
        if (!cancelled) setRefFullText({ fetching: false, fullText: null, done: true })
      })
    return () => { cancelled = true }
    // refIdentityKey changes only when the reference itself changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, isRefMode, checkId, refIdentityKey])

  if (!checkId || checkId <= 0) return null
  // Per-reference mode needs at least one real, citable scrap of the reference's
  // own text (abstract → claim → title). With nothing real to ground on, omit
  // the button entirely rather than offer a chat that would have to fabricate.
  if (isRefMode && !refContext) return null

  // Per-feature model routing (R34): Chat-with-PDF and Summarize each resolve
  // their own selected config. The backend accepts a per-call llm_config_id, so
  // each feature can run on a different model.
  const chatConfigPayload = () => {
    const c = getSelectedChatConfig?.()
    return c ? { llm_config_id: c.id } : {}
  }
  const summaryConfigPayload = () => {
    const c = getSelectedSummaryConfig?.()
    return c ? { llm_config_id: c.id } : {}
  }

  // Whether we have the reference's REAL fetched full text to ground on (R43).
  const hasRefFullText = isRefMode && !!refFullText.fullText
  // The effective per-reference grounding source for the badge/summary:
  // 'pdf' when full text was fetched, else the metadata grounding we hold.
  const refGroundingSource = hasRefFullText
    ? 'pdf'
    : (refContext?.grounding === 'abstract' ? 'abstract' : 'pdf')

  // In reference mode, lead the conversation with the reference's own real
  // context as a user turn so the grounded assistant has the reference text to
  // work from (the grounded backend otherwise grounds on the host paper). When
  // we fetched the reference's real full text (R43), use THAT as the grounding;
  // otherwise fall back to the reference's real metadata. No fabrication: only
  // text we actually hold/fetched is included.
  const groundingPreamble = () => {
    if (!isRefMode || !refContext) return []
    if (hasRefFullText) {
      return [{
        role: 'user',
        content:
          'Here is the full text of the reference I want to ask about. Use ONLY ' +
          'this text; if a detail is not present here, say it is not stated ' +
          'rather than guessing.\n\n' + refFullText.fullText,
      }]
    }
    return [{
      role: 'user',
      content:
        'Here is the reference I want to ask about. Use ONLY this text; if a ' +
        'detail is not present here, say it is not stated rather than guessing.\n\n' +
        refContext.text,
    }]
  }

  const runSummary = async () => {
    setSum({ loading: true, data: null, error: null })
    try {
      if (isRefMode) {
        // Summarize via chat in reference mode: the /summarize endpoint grounds
        // on the host paper, so for a single reference we ask the grounded chat
        // to summarize the reference text we supplied — keeping it honest.
        const msgs = [...groundingPreamble(), {
          role: 'user',
          content:
            'Summarize this reference in 3-5 sentences for a researcher: what it ' +
            'addresses, its approach, and its key findings. Use ONLY the text above; ' +
            'omit anything not stated rather than guessing.',
        }]
        const res = await postArticleChat(checkId, msgs, summaryConfigPayload())
        const d = res.data || {}
        setSum({ loading: false, data: { summary: d.answer || '', source: refGroundingSource }, error: null })
        return
      }
      const res = await getArticleSummary(checkId, summaryConfigPayload())
      setSum({ loading: false, data: res.data, error: null })
    } catch (e) {
      setSum({ loading: false, data: null, error: e?.response?.data?.detail || e?.message || 'Summarize failed' })
    } finally {
      // Summarize spends LLM tokens — nudge the live LLM usage badge to refresh
      // immediately instead of waiting for its next poll (R47).
      try { window.dispatchEvent(new Event('refchecker:usage-changed')) } catch { /* no-op */ }
    }
  }

  const sendChat = async () => {
    const q = input.trim()
    if (!q || chat.loading) return
    const nextMessages = [...messages, { role: 'user', content: q }]
    setMessages(nextMessages)
    setInput('')
    setChat({ loading: true, error: null })
    try {
      // Reference mode prepends the reference's own real context as a leading
      // turn (not shown in the visible thread) so the grounded assistant has
      // the reference text to answer from.
      const wireMessages = isRefMode ? [...groundingPreamble(), ...nextMessages] : nextMessages
      const res = await postArticleChat(checkId, wireMessages, chatConfigPayload())
      const d = res.data || {}
      setChatSource(d.source || null)
      if (d.source === 'none') {
        // Not an error — an honest limitation. The SourceBanner explains it
        // clearly above the thread instead of a red failure message.
        setChat({ loading: false, error: null })
        return
      }
      setMessages([...nextMessages, { role: 'assistant', content: d.answer || '' }])
      setChat({ loading: false, error: null })
    } catch (e) {
      setChat({ loading: false, error: e?.response?.data?.detail || e?.message || 'Chat failed' })
    } finally {
      // Chat spends LLM tokens — refresh the live LLM usage badge right away
      // so the per-flow breakdown ticks up during follow-ups (R47).
      try { window.dispatchEvent(new Event('refchecker:usage-changed')) } catch { /* no-op */ }
    }
  }

  const summary = sum.data
  const summaryNone = summary && summary.source === 'none'

  const triggerPill = (
    <Button size="pill" variant="outline" onClick={openPanel} icon={CHAT_ICON}
      className={grid ? 'rc-grid-trigger' : ''}
      title={isRefMode
        ? 'Chat about this reference or summarize it, grounded only in the reference’s available text'
        : 'Summarize this article or ask questions, answered only from the article’s own text'}>
      {label || (isRefMode ? 'Chat about this reference' : 'Chat & Summarize')}
    </Button>
  )

  const panel = (
    <div className="rounded-lg p-3 text-sm" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          {/* macOS-native segmented control — active state is a filled segment
              (a moving background), never an added border, so Summarize↔Chat
              never reflows (BUTTON_DESIGN §3.4b). */}
          <div className="flex items-center gap-2 mb-3" role="tablist">
            <div className="rc-segmented">
              <SegmentedTab label="Summarize" active={tab === 'summarize'} onClick={() => setTab('summarize')} />
              <SegmentedTab label="Chat" active={tab === 'chat'} onClick={() => setTab('chat')} />
            </div>
            <IconButton onClick={closePanel} title="Close" aria-label="Close assistant" className="ml-auto"
              style={{ color: 'var(--color-text-muted)' }}>
              {CLOSE_ICON}
            </IconButton>
          </div>

          {tab === 'summarize' ? (
            <div>
              {isRefMode && hasChatModel && <ReferenceGroundingBanner grounding={refContext.grounding} fetching={refFullText.fetching} hasFullText={hasRefFullText} />}
              {!hasChatModel && <NoModelEmptyState verb="summarize" />}
              {hasChatModel && !summary && (
                <Button size="pill" variant="outline" onClick={runSummary} loading={sum.loading}>
                  <LabelSizer candidates={[
                    'Summarizing…',
                    isRefMode ? 'Summarize this reference' : 'Summarize this article',
                  ]}>
                    {sum.loading ? 'Summarizing…' : (isRefMode ? 'Summarize this reference' : 'Summarize this article')}
                  </LabelSizer>
                </Button>
              )}
              {sum.error && <div className="text-xs mt-1" style={{ color: 'var(--color-error)' }}>{sum.error}</div>}
              {summaryNone && (
                <div className="mt-1">
                  <SourceBadge source="none" />
                  <SourceBanner source="none" />
                </div>
              )}
              {summary && !summaryNone && (
                <div>
                  <div className="flex items-center gap-2 mb-1.5">
                    <span style={{ fontWeight: 700, color: 'var(--color-text-primary)' }}>Summary</span>
                    {!isRefMode && <SourceBadge source={summary.source} />}
                  </div>
                  {!isRefMode && <SourceBanner source={summary.source} />}
                  <div className="text-sm mt-2 whitespace-pre-wrap" style={{ color: 'var(--color-text-primary)' }}>
                    {summary.summary}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div>
              {isRefMode && hasChatModel && <ReferenceGroundingBanner grounding={refContext.grounding} fetching={refFullText.fetching} hasFullText={hasRefFullText} />}
              {!isRefMode && chatSource && (
                <div className="flex items-center gap-2 mb-1.5">
                  <SourceBadge source={chatSource} />
                </div>
              )}
              {!isRefMode && <SourceBanner source={chatSource} />}
              {!hasChatModel && <div className="mb-2"><NoModelEmptyState verb="chat" /></div>}
              <div className="space-y-2 mb-2 max-h-72 overflow-y-auto">
                {hasChatModel && messages.length === 0 && (
                  <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    {isRefMode
                      ? 'Ask a question about this reference. Answers come only from the reference’s available text shown above — if it isn’t there, the assistant will say so.'
                      : 'Ask a question about this article. Answers come only from the article’s own text — if it isn’t in the article, the assistant will say so.'}
                  </div>
                )}
                {messages.map((m, i) => (
                  <div key={i} className="text-sm rounded-md px-2.5 py-1.5 whitespace-pre-wrap"
                    style={{
                      background: m.role === 'user' ? 'var(--color-bg-tertiary)' : 'var(--color-bg-primary)',
                      color: 'var(--color-text-primary)',
                      border: '1px solid var(--color-border)',
                    }}>
                    <span style={{ fontWeight: 700, color: 'var(--color-text-secondary)' }}>
                      {m.role === 'user' ? 'You' : (isRefMode ? 'Reference' : 'Article')}:
                    </span>{' '}
                    {m.content}
                  </div>
                ))}
                {chat.loading && (
                  <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    {isRefMode ? 'Reading the reference…' : 'Reading the article…'}
                  </div>
                )}
              </div>
              {chat.error && <div className="text-xs mb-1" style={{ color: 'var(--color-error)' }}>{chat.error}</div>}
              <div className="flex items-center" style={{ gap: 8 }}>
                <input
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat() } }}
                  placeholder={hasChatModel ? (isRefMode ? 'Ask about this reference…' : 'Ask about the article…') : 'Configure a model in Settings to chat'}
                  className="flex-1 text-sm"
                  style={{
                    // box-sizing:border-box is REQUIRED (BUTTON_DESIGN §3.4d): without
                    // it the bordered input renders 30px and is 2px taller than the
                    // 28px Send button on a row whose whole goal is alignment.
                    height: 'var(--control-h)', padding: '0 10px',
                    borderRadius: 'var(--control-radius)', border: 'var(--control-border)',
                    background: 'var(--color-bg-primary)', color: 'var(--color-text-primary)',
                    boxSizing: 'border-box',
                  }}
                  disabled={chat.loading || !hasChatModel}
                />
                {/* Fixed minWidth so the disabled↔enabled↔sending states never
                    resize Send; the spinner shows in its icon slot while sending,
                    and the label width is reserved (BUTTON_DESIGN §3.4d). */}
                <Button size="pill" variant="primary" onClick={sendChat} loading={chat.loading}
                  disabled={!input.trim() || !hasChatModel}
                  style={{ minWidth: 64 }}>
                  <LabelSizer candidates={['Send', 'Sending…']}>{chat.loading ? 'Sending…' : 'Send'}</LabelSizer>
                </Button>
              </div>
            </div>
          )}
        </div>
  )

  // Grid mode: "Chat & Summarize" pill sits in its 2×2 cell; the assistant
  // panel portals into the shared full-width region below the grid when open.
  if (grid) {
    return (
      <div className="rc-grid-cell">
        {triggerPill}
        {isOpen && grid.host ? createPortal(panel, grid.host) : null}
      </div>
    )
  }

  // Legacy / reference-card layout (unchanged): pill OR the expanded panel.
  return <div>{!isOpen ? triggerPill : panel}</div>
}
