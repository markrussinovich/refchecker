import { test, expect } from '@playwright/test'

const json = (status, body) => ({ status, contentType: 'application/json', body: JSON.stringify(body) })

// History entry shows in_progress, but detail reports completed. UI should reconcile to completed.
test('reconciles in-progress history with completed detail on load', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname

    if (path === '/api/llm-configs') return route.fulfill(json(200, []))
    if (path === '/api/settings/semantic-scholar') return route.fulfill(json(200, { enabled: false }))
    if (path === '/api/health') return route.fulfill(json(200, { status: 'ok' }))

    if (path === '/api/history' && route.request().method() === 'GET') {
      return route.fulfill(json(200, [
        {
          id: 99,
          paper_title: 'Reconciled Paper',
          paper_source: 'http://example.com/reconciled',
          timestamp: '2024-05-01T12:00:00Z',
          total_refs: 14,
          errors_count: 1,
          warnings_count: 0,
          unverified_count: 0,
          status: 'in_progress',
          session_id: 'session-99',
          source_type: 'url',
        },
      ]))
    }

    if (path === '/api/history/99') {
      return route.fulfill(json(200, {
        id: 99,
        paper_title: 'Reconciled Paper',
        paper_source: 'http://example.com/reconciled',
        timestamp: '2024-05-01T12:00:00Z',
        total_refs: 14,
        errors_count: 1,
        warnings_count: 0,
        unverified_count: 0,
        status: 'completed',
        results: [],
      }))
    }

    return route.fulfill(json(404, { detail: 'Unhandled mock path', path }))
  })

  await page.goto('/')

  const sidebar = page.locator('aside')

  // Should eventually flip from "Verifying" to completed refs after reconciliation
  await expect(sidebar.getByText('14 refs')).toBeVisible({ timeout: 5000 })
  await expect(sidebar.getByText(/Verifying 14 refs/)).toHaveCount(0)
})
