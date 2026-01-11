import { test, expect } from '@playwright/test';

async function setupWebSocketMock(page) {
  await page.addInitScript(() => {
    const connections = {};

    class MockWebSocket {
      constructor(url) {
        this.url = url;
        this.sessionId = url.split('/').pop();
        this.readyState = 1; // OPEN
        connections[this.sessionId] = this;
        setTimeout(() => {
          this.onopen?.({});
        }, 0);
      }

      send() {}

      close() {
        this.readyState = 3; // CLOSED
        delete connections[this.sessionId];
        this.onclose?.({ code: 1000, reason: 'mock-close' });
      }

      _emit(data) {
        this.onmessage?.({ data: JSON.stringify(data) });
      }
    }

    window.__wsConnections = connections;
    window.WebSocket = MockWebSocket;
  });

  const emit = async (sessionId, payload) => {
    await page.waitForFunction((id) => !!window.__wsConnections?.[id], sessionId);
    await page.evaluate(([id, data]) => {
      window.__wsConnections[id]?._emit(data);
    }, [sessionId, payload]);
  };

  return { emit };
}

async function setupApiMock(page, serverState) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    const json = (status, body) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });

    if (path === '/api/llm-configs') return json(200, []);
    if (path === '/api/settings/semantic-scholar') return json(200, { enabled: false });
    if (path === '/api/health') return json(200, { status: 'ok' });

    if (path === '/api/check' && route.request().method() === 'POST') {
      const next = serverState.startQueue.shift();
      if (!next) return json(500, { detail: 'No mock start response available' });

      const historyEntry = {
        id: next.checkId,
        paper_title: next.paperTitle,
        paper_source: next.paperSource,
        timestamp: new Date().toISOString(),
        total_refs: next.totalRefs,
        errors_count: next.stats?.errors_count ?? 0,
        warnings_count: next.stats?.warnings_count ?? 0,
        suggestions_count: next.stats?.suggestions_count ?? 0,
        unverified_count: next.stats?.unverified_count ?? 0,
        refs_with_errors: next.stats?.refs_with_errors ?? 0,
        refs_with_warnings_only: next.stats?.refs_with_warnings_only ?? 0,
        refs_verified: next.stats?.refs_verified ?? 0,
        status: 'in_progress',
        session_id: next.sessionId,
      };

      serverState.history = [historyEntry, ...serverState.history.filter((h) => h.id !== historyEntry.id)];
      serverState.details[next.checkId] = {
        ...historyEntry,
        results: next.results || [],
      };

      return json(200, {
        session_id: next.sessionId,
        check_id: next.checkId,
        message: 'Check started',
        source: next.paperSource,
      });
    }

    if (path === '/api/history') {
      return json(200, serverState.history);
    }

    if (path.startsWith('/api/history/')) {
      const id = Number(path.split('/').pop());
      const detail = serverState.details[id];
      if (!detail) return json(404, { detail: 'Not found' });
      return json(200, detail);
    }

    if (path.startsWith('/api/cancel/')) {
      return json(200, { message: 'Cancelled' });
    }

    return json(404, { detail: 'Unhandled mock path', path });
  });
}

test.describe('RefChecker Web UI', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should load the homepage', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('RefChecker');
    // Check main panel is visible
    await expect(page.getByText('Check Paper References')).toBeVisible();
  });

  test('should show URL input by default', async ({ page }) => {
    const urlButton = page.getByRole('button', { name: 'URL / ArXiv ID' });
    await expect(urlButton).toBeVisible();

    const input = page.getByPlaceholder(/Enter ArXiv ID/i);
    await expect(input).toBeVisible();
  });

  test('should switch to file upload mode', async ({ page }) => {
    const fileButton = page.getByRole('button', { name: 'Upload File' });
    await fileButton.click();

    await expect(fileButton).toBeVisible();
    await expect(page.getByText(/Click to upload/i)).toBeVisible();
  });

  test('should disable submit button when URL is empty', async ({ page }) => {
    const submitButton = page.getByRole('button', { name: 'Check References' });
    // Button should be disabled when no URL entered
    await expect(submitButton).toBeDisabled();
  });

  test('should submit ArXiv ID and show processing state', async ({ page }) => {
    // Mock backend response
    await page.route('**/api/check', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: 'test-session-123',
          check_id: 42,
          message: 'Check started'
        })
      });
    });

    // Enter ArXiv ID
    const input = page.getByPlaceholder(/Enter ArXiv ID/i);
    await input.fill('1706.03762');

    // Submit form
    const submitButton = page.getByRole('button', { name: 'Check References' });
    await submitButton.click();

    // Should show cancel button (indicating checking state)
    await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible();
  });

  test('isolates concurrent sessions, history clicks, and per-paper references', async ({ page }) => {
    const serverState = {
      startQueue: [
        {
          sessionId: 'sess-one',
          checkId: 201,
          paperTitle: 'Paper One',
          paperSource: 'paper-one.pdf',
          totalRefs: 2,
          stats: { errors_count: 0, warnings_count: 1, unverified_count: 0 },
          results: [
            { index: 1, title: 'Paper One Ref A', status: 'verified', errors: [], warnings: [], authoritative_urls: [] },
            { index: 2, title: 'Paper One Ref B', status: 'warning', errors: [], warnings: [{ warning_type: 'note', warning_details: 'Minor discrepancy' }], authoritative_urls: [] },
          ],
        },
        {
          sessionId: 'sess-two',
          checkId: 202,
          paperTitle: 'Paper Two',
          paperSource: 'paper-two.pdf',
          totalRefs: 1,
          stats: { errors_count: 1, warnings_count: 0, unverified_count: 0 },
          results: [
            { index: 1, title: 'Paper Two Ref A', status: 'error', errors: [{ error_type: 'title', error_details: 'Mismatch' }], warnings: [], authoritative_urls: [] },
          ],
        },
      ],
      history: [
        {
          id: 301,
          paper_title: 'Historical Paper',
          paper_source: 'history.pdf',
          timestamp: '2024-05-01T12:00:00Z',
          total_refs: 3,
          errors_count: 1,
          warnings_count: 1,
          unverified_count: 1,
          status: 'completed',
          results: [
            { index: 1, title: 'Historical Ref A', status: 'verified', errors: [], warnings: [], authoritative_urls: [] },
            { index: 2, title: 'Historical Ref B', status: 'warning', errors: [], warnings: [{ warning_type: 'note', warning_details: 'Minor' }], authoritative_urls: [] },
            { index: 3, title: 'Historical Ref C', status: 'unverified', errors: [], warnings: [], authoritative_urls: [] },
          ],
        },
      ],
      details: {},
    };
    serverState.details[301] = serverState.history[0];

    await setupApiMock(page, serverState);
    await setupWebSocketMock(page);

    await page.goto('/');

    // Start first check
    const sidebar = page.locator('aside');

    await page.getByPlaceholder(/Enter ArXiv ID/i).fill('http://paper-one.example');
    await page.getByRole('button', { name: 'Check References' }).click();

    await expect(sidebar.getByText('Paper One', { exact: true })).toBeVisible();
    // During in-progress, the sidebar shows "X/Y refs" or "Extracting refs..."
    await expect(sidebar.getByText(/\d+\/\d+ refs|Extracting refs/)).toBeVisible();

    // Start second check while first is in progress
    await page.getByRole('button', { name: 'New refcheck' }).click();
    await page.getByPlaceholder(/Enter ArXiv ID/i).fill('http://paper-two.example');
    await page.getByRole('button', { name: 'Check References' }).click();

    await expect(sidebar.getByText('Paper Two', { exact: true })).toBeVisible();
    // Second check also shows similar progress format
    await expect(sidebar.getByText(/\d+\/\d+ refs|Extracting refs/).first()).toBeVisible();

    // Switch to Paper Two and confirm its data
    await sidebar.getByText('Paper Two', { exact: true }).click();
    await expect(page.getByText('References (1)')).toBeVisible();
    await expect(page.getByText('Paper Two Ref A')).toBeVisible();
    await expect(page.getByText('Paper One Ref B')).not.toBeVisible({ timeout: 1000 });

    // Switch to Paper One and confirm its data is intact
    await sidebar.getByText('Paper One', { exact: true }).click();
    await expect(page.getByText('References (2)')).toBeVisible();
    await expect(page.getByText('Paper One Ref A')).toBeVisible();
    await expect(page.getByText('Paper Two Ref A')).not.toBeVisible({ timeout: 1000 });

    // Switch to historical completed run and ensure correct results render
    await sidebar.getByText('Historical Paper', { exact: true }).click();
    await expect(page.getByText('References (3)')).toBeVisible();
    await expect(page.getByText('Historical Ref A')).toBeVisible();
  });

  test('should display history sidebar', async ({ page }) => {
    await expect(page.getByText('History')).toBeVisible();
  });

  test.skip('should load and display history items', async ({ page }) => {
    // This test requires backend to be running or proper API mocking
    // Mock history API response before navigation
    await page.route('**/api/history', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          history: [
            {
              id: 1,
              paper_title: 'Attention Is All You Need',
              paper_source: '1706.03762',
              timestamp: '2024-01-08T10:00:00',
              total_refs: 45,
              errors_count: 12,
              warnings_count: 8,
              unverified_count: 3
            }
          ]
        })
      });
    });

    await page.goto('/');

    // Wait for history to load
    await expect(page.getByText('Attention Is All You Need')).toBeVisible();
    // History items show "X refs" label
    await expect(page.getByText('45 refs')).toBeVisible();
  });

  test.skip('should click on history item and load details', async ({ page }) => {
    // This test requires backend to be running
    await page.route('**/api/history', async (route) => {
      const url = route.request().url();
      if (url.endsWith('/history/1')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 1,
            paper_title: 'Test Paper',
            paper_source: 'test.pdf',
            total_refs: 10,
            errors_count: 2,
            warnings_count: 1,
            unverified_count: 0,
            results: [
              {
                index: 1,
                title: 'Sample Reference',
                authors: ['Author One', 'Author Two'],
                year: '2020',
                status: 'verified',
                errors: [],
                warnings: [],
                authoritative_urls: [
                  { type: 'semantic_scholar', url: 'https://example.com' }
                ]
              }
            ]
          })
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            history: [
              {
                id: 1,
                paper_title: 'Test Paper',
                paper_source: 'test.pdf',
                timestamp: '2024-01-08T10:00:00',
                total_refs: 10,
                errors_count: 2,
                warnings_count: 1,
                unverified_count: 0
              }
            ]
          })
        });
      }
    });

    await page.goto('/');

    // Click on history item
    await page.getByText('Test Paper').click();

    // Should display results
    await expect(page.getByText('Sample Reference')).toBeVisible();
  });

  test.skip('should display summary panel with statistics', async ({ page }) => {
    // This test requires backend to be running
    await page.route('**/api/history**', async (route) => {
      if (route.request().url().includes('/1')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 1,
            paper_title: 'Test Paper',
            paper_source: 'test.pdf',
            total_refs: 100,
            errors_count: 15,
            warnings_count: 10,
            unverified_count: 5,
            results: []
          })
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            history: [
              {
                id: 1,
                paper_title: 'Test Paper',
                paper_source: 'test.pdf',
                timestamp: '2024-01-08T10:00:00',
                total_refs: 100,
                errors_count: 15,
                warnings_count: 10,
                unverified_count: 5
              }
            ]
          })
        });
      }
    });

    await page.goto('/');
    await page.getByText('Test Paper').click();

    // Check summary statistics - looking at stats cards
    await expect(page.locator('text=Total').first()).toBeVisible();
    await expect(page.locator('text=100').first()).toBeVisible();
  });

  test.skip('should display reference with errors', async ({ page }) => {
    // This test requires backend to be running
    await page.route('**/api/history**', async (route) => {
      if (route.request().url().includes('/1')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 1,
            paper_title: 'Test Paper',
            total_refs: 1,
            errors_count: 1,
            warnings_count: 0,
            unverified_count: 0,
            results: [
              {
                index: 1,
                title: 'Reference with Error',
                authors: ['Test Author'],
                year: '2020',
                status: 'error',
                errors: [
                  {
                    error_type: 'author',
                    error_details: 'First author mismatch',
                    cited_value: 'Test Author',
                    actual_value: 'Real Author'
                  }
                ],
                warnings: [],
                authoritative_urls: []
              }
            ]
          })
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ history: [
            {
              id: 1,
              paper_title: 'Test Paper',
              timestamp: '2024-01-08T10:00:00',
              total_refs: 1,
              errors_count: 1,
              warnings_count: 0,
              unverified_count: 0
            }
          ]})
        });
      }
    });

    await page.goto('/');
    await page.getByText('Test Paper').click();

    // Check that reference shows - detailed error checking depends on component structure
    await expect(page.getByText('Reference with Error')).toBeVisible();
  });

  test.skip('should display clickable authoritative URLs', async ({ page }) => {
    // This test requires backend to be running
    await page.route('**/api/history**', async (route) => {
      if (route.request().url().includes('/1')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 1,
            paper_title: 'Test Paper',
            total_refs: 1,
            errors_count: 0,
            warnings_count: 0,
            unverified_count: 0,
            results: [
              {
                index: 1,
                title: 'Reference with URLs',
                authors: ['Author'],
                year: '2020',
                status: 'verified',
                errors: [],
                warnings: [],
                authoritative_urls: [
                  { type: 'semantic_scholar', url: 'https://semanticscholar.org/paper/123' },
                  { type: 'arxiv', url: 'https://arxiv.org/abs/1234.5678' },
                  { type: 'doi', url: 'https://doi.org/10.1234/test' }
                ]
              }
            ]
          })
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ history: [
            {
              id: 1,
              paper_title: 'Test Paper',
              timestamp: '2024-01-08T10:00:00',
              total_refs: 1,
              errors_count: 0,
              warnings_count: 0,
              unverified_count: 0
            }
          ]})
        });
      }
    });

    await page.goto('/');
    await page.getByText('Test Paper').click();

    // Check that reference with URLs is visible
    await expect(page.getByText('Reference with URLs')).toBeVisible();
  });

  test.skip('should display history item and show action buttons on hover', async ({ page }) => {
    // This test requires backend to be running or proper API mocking
    await page.route('**/api/history', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          history: [
            {
              id: 1,
              paper_title: 'Test Paper',
              timestamp: '2024-01-08T10:00:00',
              total_refs: 10,
              errors_count: 2,
              warnings_count: 1,
              unverified_count: 0
            }
          ]
        })
      });
    });

    await page.goto('/');

    // History item should be visible
    const historyItem = page.getByText('Test Paper');
    await expect(historyItem).toBeVisible();

    // Hover to show action buttons
    await historyItem.hover();

    // Edit and delete buttons should be visible on hover
    await expect(page.getByTitle('Edit label')).toBeVisible();
    await expect(page.getByTitle('Delete')).toBeVisible();
  });

  test('summary section height stays constant when filter is toggled', async ({ page }) => {
    // Set up a completed check with some warnings so we have filter buttons
    const serverState = {
      startQueue: [
        {
          sessionId: 'sess-height-test',
          checkId: 999,
          paperTitle: 'Height Test Paper',
          paperSource: 'height-test.pdf',
          totalRefs: 3,
          stats: { 
            errors_count: 1, 
            warnings_count: 1, 
            unverified_count: 0,
            refs_with_errors: 1,
            refs_with_warnings_only: 1,
            refs_verified: 1
          },
          results: [
            { index: 1, title: 'Ref A', status: 'verified', errors: [], warnings: [], suggestions: [], authoritative_urls: [] },
            { index: 2, title: 'Ref B', status: 'warning', errors: [], warnings: [{ warning_type: 'year', warning_details: 'Year mismatch' }], suggestions: [], authoritative_urls: [] },
            { index: 3, title: 'Ref C', status: 'error', errors: [{ error_type: 'title', error_details: 'Title mismatch' }], warnings: [], suggestions: [], authoritative_urls: [] },
          ],
        },
      ],
      history: [],
      details: {},
    };

    await setupApiMock(page, serverState);
    await setupWebSocketMock(page);

    await page.goto('/');

    // Start check
    await page.getByPlaceholder(/Enter ArXiv ID/i).fill('http://height-test.example');
    await page.getByRole('button', { name: 'Check References' }).click();

    // Wait for completion - summary should be visible
    await expect(page.getByText('Summary')).toBeVisible();
    
    // Find the summary section container and measure its height
    const summarySection = page.locator('.rounded-lg.border.p-3').first();
    await expect(summarySection).toBeVisible();
    
    const initialBoundingBox = await summarySection.boundingBox();
    const initialHeight = initialBoundingBox.height;

    // Click on the warnings filter to activate it
    const warningsButton = page.getByTitle('Filter by warnings only');
    if (await warningsButton.isVisible()) {
      await warningsButton.click();
      
      // Wait a moment for any re-render
      await page.waitForTimeout(100);
      
      // Filter indicator should be visible
      await expect(page.getByText(/Showing warnings/i)).toBeVisible();
      
      // Measure height again
      const filteredBoundingBox = await summarySection.boundingBox();
      const filteredHeight = filteredBoundingBox.height;
      
      // Height should remain constant (within 2px tolerance for sub-pixel rendering)
      expect(Math.abs(filteredHeight - initialHeight)).toBeLessThanOrEqual(2);
      
      // Click again to toggle off
      await page.getByText(/Showing warnings/i).click();
      
      // Wait a moment
      await page.waitForTimeout(100);
      
      // Measure height after clearing filter
      const clearedBoundingBox = await summarySection.boundingBox();
      const clearedHeight = clearedBoundingBox.height;
      
      // Height should still be constant
      expect(Math.abs(clearedHeight - initialHeight)).toBeLessThanOrEqual(2);
    }
  });

  test('paper-level counts are correct and suggestions display properly', async ({ page }) => {
    // Set up a check with specific issue counts to validate
    const serverState = {
      startQueue: [
        {
          sessionId: 'sess-counts-test',
          checkId: 1000,
          paperTitle: 'Counts Test Paper',
          paperSource: 'counts-test.pdf',
          totalRefs: 4,
          stats: { 
            errors_count: 1, 
            warnings_count: 2, 
            suggestions_count: 1,
            unverified_count: 0,
            refs_with_errors: 1,
            refs_with_warnings_only: 1,
            refs_verified: 2
          },
          results: [
            { index: 1, title: 'Verified Ref', status: 'verified', errors: [], warnings: [], suggestions: [], authoritative_urls: [] },
            { index: 2, title: 'Warning Only Ref', status: 'warning', errors: [], warnings: [{ warning_type: 'author', warning_details: 'Author mismatch' }], suggestions: [], authoritative_urls: [] },
            { index: 3, title: 'Error Ref', status: 'error', errors: [{ error_type: 'title', error_details: 'Title mismatch' }], warnings: [{ warning_type: 'year', warning_details: 'Year mismatch' }], suggestions: [], authoritative_urls: [] },
            { index: 4, title: 'Suggestion Ref', status: 'suggestion', errors: [], warnings: [], suggestions: [{ suggestion_type: 'url', suggestion_details: 'Reference could include arXiv URL: https://arxiv.org/abs/1234.5678' }], authoritative_urls: [] },
          ],
        },
      ],
      history: [],
      details: {},
    };

    await setupApiMock(page, serverState);
    const { emit } = await setupWebSocketMock(page);

    await page.goto('/');

    // Start check
    await page.getByPlaceholder(/Enter ArXiv ID/i).fill('http://counts-test.example');
    await page.getByRole('button', { name: 'Check References' }).click();

    // Wait for check to start - use the Cancel button in main panel, not sidebar
    await expect(page.getByRole('main').getByRole('button', { name: 'Cancel' })).toBeVisible();

    // Emit WebSocket messages to simulate check completion
    const sessionId = 'sess-counts-test';

    // Emit stats_update with suggestions_count
    await emit(sessionId, {
      type: 'stats_update',
      stats: {
        total_refs: 4,
        processed_refs: 4,
        errors_count: 1,
        warnings_count: 2,
        suggestions_count: 1,
        unverified_count: 0,
        refs_with_errors: 1,
        refs_with_warnings_only: 1,
        refs_verified: 2,
      }
    });

    // Emit reference results - results are in the details object after api mock processes them
    const results = [
      { index: 1, title: 'Verified Ref', status: 'verified', errors: [], warnings: [], suggestions: [], authoritative_urls: [] },
      { index: 2, title: 'Warning Only Ref', status: 'warning', errors: [], warnings: [{ warning_type: 'author', warning_details: 'Author mismatch' }], suggestions: [], authoritative_urls: [] },
      { index: 3, title: 'Error Ref', status: 'error', errors: [{ error_type: 'title', error_details: 'Title mismatch' }], warnings: [{ warning_type: 'year', warning_details: 'Year mismatch' }], suggestions: [], authoritative_urls: [] },
      { index: 4, title: 'Suggestion Ref', status: 'suggestion', errors: [], warnings: [], suggestions: [{ suggestion_type: 'url', suggestion_details: 'Reference could include arXiv URL: https://arxiv.org/abs/1234.5678' }], authoritative_urls: [] },
    ];
    for (const ref of results) {
      await emit(sessionId, { type: 'reference_result', result: ref });
    }

    // Emit completion
    await emit(sessionId, { type: 'complete' });

    // Wait for summary to be visible
    await expect(page.getByText('Summary')).toBeVisible();
    
    // Verify the issue chips show correct counts (the rounded pill buttons with "X Errors", "X Warnings", etc.)
    // These are the chips on the right side of the StatsSection
    // Use getByRole with exact name to target the correct buttons
    await expect(page.getByRole('button', { name: '1 Errors', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '2 Warnings', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '1 Suggestions', exact: true })).toBeVisible();
    
    // Verify suggestion is displayed as "Suggestion:" not "Error:"
    await expect(page.getByText('Suggestion Ref')).toBeVisible();
    // Click to expand if needed
    const suggestionRef = page.getByText('Suggestion Ref');
    await suggestionRef.click();
    
    // The suggestion should show "Suggestion:" label with the arXiv URL
    await expect(page.getByText(/Suggestion:.*arXiv/i)).toBeVisible();
    
    // Verify the suggestion ref card specifically doesn't have "Error:" for the arXiv content
    // Get the parent container of the Suggestion Ref and verify it doesn't contain "Error:" before "arXiv"
    const suggestionCard = page.locator('.divide-y > div').filter({ hasText: 'Suggestion Ref' });
    // The suggestion card should contain "Suggestion:" but NOT "Error:" before the arXiv URL
    await expect(suggestionCard.getByText(/Suggestion:.*arXiv/i)).toBeVisible();
    // The arXiv text should not be labeled as "Error" in this card
    await expect(suggestionCard.locator('text=/^Error:.*arXiv/i')).not.toBeVisible();
  });
});
