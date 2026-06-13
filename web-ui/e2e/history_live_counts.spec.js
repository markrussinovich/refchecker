import { test, expect } from '@playwright/test'

const json = (status, body) => ({ status, contentType: 'application/json', body: JSON.stringify(body) })

async function setupWebSocketMock(page) {
  await page.addInitScript(() => {
    const connections = {}
    class MockWebSocket {
      constructor(url) {
        this.url = url
        this.sessionId = url.split('/').pop()
        this.readyState = 1
        connections[this.sessionId] = this
        setTimeout(() => this.onopen?.({}), 0)
      }
      send() {}
      close() {
        this.readyState = 3
        delete connections[this.sessionId]
        this.onclose?.({ code: 1000, reason: 'mock-close' })
      }
      _emit(data) {
        this.onmessage?.({ data: JSON.stringify(data) })
      }
    }
    window.__wsConnections = connections
    window.WebSocket = MockWebSocket
  })

  return async (sessionId, payload) => {
    await page.waitForFunction(id => Boolean(window.__wsConnections?.[id]), sessionId)
    await page.evaluate(([id, data]) => {
      window.__wsConnections[id]?._emit(data)
    }, [sessionId, payload])
  }
}

async function setupApiMock(page, serverState) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname

    if (path === '/api/auth/providers') return route.fulfill(json(200, { providers: [] }))
    if (path === '/api/auth/me') return route.fulfill(json(401, { detail: 'Not authenticated' }))
    if (path === '/api/llm-configs') return route.fulfill(json(200, []))
    if (path === '/api/settings/semantic-scholar') return route.fulfill(json(200, { enabled: false }))
    if (path === '/api/health') return route.fulfill(json(200, { status: 'ok' }))
    if (path === '/api/history') return route.fulfill(json(200, serverState.history))

    if (path === '/api/check' && route.request().method() === 'POST') {
      serverState.history = [{
        id: serverState.checkId,
        paper_title: serverState.title,
        paper_source: serverState.source,
        timestamp: '2024-05-01T12:00:00Z',
        total_refs: 6,
        status: 'in_progress',
        session_id: serverState.sessionId,
      }]
      return route.fulfill(json(200, {
        session_id: serverState.sessionId,
        check_id: serverState.checkId,
        message: 'Check started',
        source: serverState.source,
      }))
    }

    if (path.startsWith('/api/history/')) {
      return route.fulfill(json(500, { detail: 'Detail should not be required for fresh live counts' }))
    }

    return route.fulfill(json(404, { detail: 'Unhandled mock path', path }))
  })
}

test('fresh scan history card derives reference buckets from live results before click', async ({ page }) => {
  const serverState = {
    sessionId: 'session-live-counts',
    checkId: 701,
    title: 'Fresh Live Count Paper',
    source: 'https://example.com/live-counts',
    history: [],
  }
  await setupApiMock(page, serverState)
  const emit = await setupWebSocketMock(page)

  await page.goto('/')
  await page.getByPlaceholder(/Enter ArXiv ID/i).fill(serverState.source)
  await page.getByRole('button', { name: 'Check References' }).click()
  await emit(serverState.sessionId, {
    type: 'extracting',
    paper_title: serverState.title,
    source: serverState.source,
  })
  const sidebar = page.locator('aside.sidebar-desktop')
  await expect(sidebar.locator('[data-history-item]').filter({ hasText: serverState.title })).toBeVisible()

  await emit(serverState.sessionId, {
    type: 'references_extracted',
    total_refs: 6,
    count: 6,
    references: [
      { title: 'Verified Ref', authors: [], year: 2024 },
      { title: 'Error Ref', authors: [], year: 2024 },
      { title: 'Warning Ref', authors: [], year: 2024 },
      { title: 'Suggestion Ref', authors: [], year: 2024 },
      { title: 'Unverified Ref', authors: [], year: 2024 },
      { title: 'Hallucinated Ref', authors: [], year: 2024 },
    ],
  })

  const refs = [
    { index: 1, title: 'Verified Ref', status: 'verified', errors: [], warnings: [], suggestions: [] },
    { index: 2, title: 'Error Ref', status: 'error', errors: [{ error_type: 'title', error_details: 'Title mismatch' }], warnings: [], suggestions: [] },
    { index: 3, title: 'Warning Ref', status: 'warning', errors: [], warnings: [{ warning_type: 'venue', warning_details: 'Venue mismatch' }], suggestions: [] },
    { index: 4, title: 'Suggestion Ref', status: 'suggestion', errors: [], warnings: [], suggestions: [{ suggestion_type: 'venue', suggestion_details: 'Use full venue' }] },
    { index: 5, title: 'Unverified Ref', status: 'unverified', errors: [{ error_type: 'unverified', error_details: 'Not found' }], warnings: [], suggestions: [] },
    { index: 6, title: 'Hallucinated Ref', status: 'hallucination', errors: [{ error_type: 'unverified', error_details: 'Likely hallucinated' }], warnings: [], suggestions: [] },
  ]

  for (const ref of refs) {
    await emit(serverState.sessionId, { type: 'reference_result', ...ref })
  }

  await emit(serverState.sessionId, {
    type: 'completed',
    total_refs: 6,
    errors_count: 1,
    warnings_count: 1,
    suggestions_count: 3,
    unverified_count: 6,
    hallucination_count: 6,
    verified_count: 1,
    refs_with_errors: 1,
    refs_with_warnings_only: 1,
    refs_verified: 1,
    extraction_method: 'mock',
  })

  const card = sidebar.locator('[data-history-item]').filter({ hasText: serverState.title })
  await expect(card.locator('[title="1 ref with errors"]')).toBeVisible()
  await expect(card.locator('[title="1 ref with warnings"]')).toBeVisible()
  await expect(card.locator('[title="1 ref with suggestions"]')).toBeVisible()
  await expect(card.locator('[title="2 unverified refs"]')).toBeVisible()
  await expect(card.locator('[title="1 likely hallucinated ref"]')).toBeVisible()
  await expect(card.locator('[title="6 unverified refs"]')).toHaveCount(0)
  await expect(card.locator('[title="6 likely hallucinated refs"]')).toHaveCount(0)
})