import { useState } from 'react'
import { getArticleSummary, postArticleChat } from '../../utils/api'
import { useConfigStore } from '../../stores/useConfigStore'

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
 */

const SOURCE_LABEL = { pdf: 'full text', abstract: 'abstract only', none: 'no text' }

function SourceBadge({ source }) {
  if (!source) return null
  const isAbstract = source === 'abstract'
  const color = source === 'pdf' ? 'var(--color-success)'
    : isAbstract ? 'var(--color-warning)' : 'var(--color-text-muted)'
  return (
    <span className="px-2 py-0.5 rounded-full text-xs font-semibold"
      style={{ color, background: 'var(--color-bg-tertiary)', border: `1px solid ${color}` }}
      title="Where the answer is grounded">
      grounded: {SOURCE_LABEL[source] || source}
    </span>
  )
}

function AbstractBanner({ source }) {
  if (source !== 'abstract') return null
  return (
    <div className="text-xs mt-2 rounded-md px-2.5 py-1.5"
      style={{ color: 'var(--color-warning)', background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-warning)' }}>
      Answering from the abstract only — the full text wasn’t available for this article, so answers are limited to what the abstract states.
    </div>
  )
}

export default function ArticleAssistant({ checkId }) {
  const getSelectedChatConfig = useConfigStore(s => s.getSelectedChatConfig)
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState('summarize')

  // Summarize state
  const [sum, setSum] = useState({ loading: false, data: null, error: null })
  // Chat state
  const [messages, setMessages] = useState([]) // [{role, content}]
  const [input, setInput] = useState('')
  const [chatSource, setChatSource] = useState(null)
  const [chat, setChat] = useState({ loading: false, error: null })

  if (!checkId || checkId <= 0) return null

  const configPayload = () => {
    const c = getSelectedChatConfig?.()
    return c ? { llm_config_id: c.id } : {}
  }

  const runSummary = async () => {
    setSum({ loading: true, data: null, error: null })
    try {
      const res = await getArticleSummary(checkId, configPayload())
      setSum({ loading: false, data: res.data, error: null })
    } catch (e) {
      setSum({ loading: false, data: null, error: e?.response?.data?.detail || e?.message || 'Summarize failed' })
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
      const res = await postArticleChat(checkId, nextMessages, configPayload())
      const d = res.data || {}
      setChatSource(d.source || null)
      if (d.source === 'none') {
        setChat({ loading: false, error: d.detail || 'No article text is available to chat about.' })
        return
      }
      setMessages([...nextMessages, { role: 'assistant', content: d.answer || '' }])
      setChat({ loading: false, error: null })
    } catch (e) {
      setChat({ loading: false, error: e?.response?.data?.detail || e?.message || 'Chat failed' })
    }
  }

  const summary = sum.data
  const summaryNone = summary && summary.source === 'none'

  return (
    <div className="mb-3">
      {!open ? (
        <button type="button" onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border"
          style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-primary)', borderColor: 'var(--color-border)' }}
          title="Summarize this article or ask questions, answered only from the article’s own text">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
          Chat &amp; Summarize
        </button>
      ) : (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          {/* Tabs */}
          <div className="flex items-center gap-1 mb-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
            {['summarize', 'chat'].map(t => (
              <button key={t} type="button" onClick={() => setTab(t)}
                className="px-3 py-1.5 text-xs font-medium -mb-px border-b-2"
                style={{
                  color: tab === t ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  borderColor: tab === t ? 'var(--color-accent)' : 'transparent',
                }}>
                {t === 'summarize' ? 'Summarize' : 'Chat'}
              </button>
            ))}
            <div className="ml-auto">
              <button type="button" onClick={() => setOpen(false)}
                className="px-2 py-1 text-xs" style={{ color: 'var(--color-text-muted)' }} title="Close">✕</button>
            </div>
          </div>

          {tab === 'summarize' ? (
            <div>
              {!summary && (
                <button type="button" onClick={runSummary} disabled={sum.loading}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border"
                  style={{ background: 'var(--color-bg-primary)', color: 'var(--color-text-primary)', borderColor: 'var(--color-border)', opacity: sum.loading ? 0.6 : 1 }}>
                  {sum.loading ? 'Summarizing…' : 'Summarize this article'}
                </button>
              )}
              {sum.error && <div className="text-xs mt-1" style={{ color: 'var(--color-error)' }}>{sum.error}</div>}
              {summaryNone && (
                <div className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                  {summary.detail || 'No article text is available to summarize.'}
                </div>
              )}
              {summary && !summaryNone && (
                <div>
                  <div className="flex items-center gap-2 mb-1.5">
                    <span style={{ fontWeight: 700, color: 'var(--color-text-primary)' }}>Summary</span>
                    <SourceBadge source={summary.source} />
                  </div>
                  <AbstractBanner source={summary.source} />
                  <div className="text-sm mt-2 whitespace-pre-wrap" style={{ color: 'var(--color-text-primary)' }}>
                    {summary.summary}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div>
              {chatSource && (
                <div className="flex items-center gap-2 mb-1.5">
                  <SourceBadge source={chatSource} />
                </div>
              )}
              <AbstractBanner source={chatSource} />
              <div className="space-y-2 mb-2 max-h-72 overflow-y-auto">
                {messages.length === 0 && (
                  <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    Ask a question about this article. Answers come only from the article’s own text — if it isn’t in the article, the assistant will say so.
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
                      {m.role === 'user' ? 'You' : 'Article'}:
                    </span>{' '}
                    {m.content}
                  </div>
                ))}
                {chat.loading && (
                  <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Reading the article…</div>
                )}
              </div>
              {chat.error && <div className="text-xs mb-1" style={{ color: 'var(--color-error)' }}>{chat.error}</div>}
              <div className="flex items-center gap-2">
                <input
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat() } }}
                  placeholder="Ask about the article…"
                  className="flex-1 px-2.5 py-1.5 rounded-md text-sm border"
                  style={{ background: 'var(--color-bg-primary)', color: 'var(--color-text-primary)', borderColor: 'var(--color-border)' }}
                  disabled={chat.loading}
                />
                <button type="button" onClick={sendChat} disabled={chat.loading || !input.trim()}
                  className="px-3 py-1.5 rounded-md text-xs font-medium border"
                  style={{ background: 'var(--color-accent)', color: 'white', borderColor: 'var(--color-accent)', opacity: (chat.loading || !input.trim()) ? 0.6 : 1 }}>
                  Send
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
