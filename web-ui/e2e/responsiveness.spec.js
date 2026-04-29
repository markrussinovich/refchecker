import { test, expect } from '@playwright/test';

/**
 * Shared mock helpers – keep in sync with other spec files.
 */
async function setupWebSocketMock(page) {
  await page.addInitScript(() => {
    const connections = {};
    class MockWebSocket {
      constructor(url) {
        this.url = url;
        this.sessionId = url.split('/').pop();
        this.readyState = 1; // OPEN
        connections[this.sessionId] = this;
        setTimeout(() => this.onopen?.({}), 0);
      }
      send() {}
      close() {
        this.readyState = 3;
        delete connections[this.sessionId];
        this.onclose?.({ code: 1000 });
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
    await page.evaluate(
      ([id, data]) => window.__wsConnections[id]?._emit(data),
      [sessionId, payload],
    );
  };
  return { emit };
}

function setupApiMock(page, serverState) {
  return page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (s, b) =>
      route.fulfill({ status: s, contentType: 'application/json', body: JSON.stringify(b) });

    if (path === '/api/auth/providers') return json(200, { providers: [] });
    if (path === '/api/auth/me') return json(401, {});
    if (path === '/api/llm-configs') return json(200, []);
    if (path === '/api/settings/semantic-scholar') return json(200, { enabled: false });
    if (path === '/api/health') return json(200, { status: 'ok' });

    if (path === '/api/check' && route.request().method() === 'POST') {
      const next = serverState.startQueue.shift();
      if (!next) return json(500, { detail: 'No mock start' });

      const entry = {
        id: next.checkId,
        paper_title: next.paperTitle,
        paper_source: next.paperSource,
        timestamp: new Date().toISOString(),
        total_refs: next.totalRefs,
        status: 'in_progress',
        session_id: next.sessionId,
      };
      serverState.history = [entry, ...serverState.history];
      serverState.details[next.checkId] = { ...entry, results: [] };
      return json(200, {
        session_id: next.sessionId,
        check_id: next.checkId,
        message: 'Started',
        source: next.paperSource,
      });
    }

    if (path === '/api/history') return json(200, serverState.history);
    if (path.startsWith('/api/history/')) {
      const id = Number(path.split('/').pop());
      return json(200, serverState.details[id] || {});
    }
    if (path.startsWith('/api/cancel/')) return json(200, { message: 'Cancelled' });
    return json(404, { detail: 'Unhandled', path });
  });
}

// ---------- helpers ----------

/** Build skeleton references for extraction. */
function skeletonRefs(count) {
  return Array.from({ length: count }, (_, i) => ({
    title: `Reference ${i + 1}`,
    authors: [`Author ${i + 1}`],
    year: 2020 + (i % 5),
  }));
}

/** Build a reference_result message. */
function refResult(index, status = 'verified') {
  return {
    type: 'reference_result',
    index, // 1-based
    title: `Reference ${index}`,
    authors: [`Author ${index}`],
    year: 2020 + (index % 5),
    status,
    errors: status === 'error' ? [{ error_type: 'title', error_details: 'Mismatch' }] : [],
    warnings: status === 'warning' ? [{ error_type: 'year', error_details: 'Year off' }] : [],
    suggestions: [],
    authoritative_urls: [],
  };
}

/** Build a summary_update message. */
function summaryUpdate(processed, total, errCount = 0, warnCount = 0) {
  return {
    type: 'summary_update',
    total_refs: total,
    processed_refs: processed,
    progress_percent: total > 0 ? (processed / total) * 100 : 0,
    errors_count: errCount,
    warnings_count: warnCount,
    suggestions_count: 0,
    unverified_count: 0,
    hallucination_count: 0,
    verified_count: processed - errCount - warnCount,
    refs_with_errors: errCount,
    refs_with_warnings_only: warnCount,
    refs_verified: processed - errCount - warnCount,
  };
}

// ==========================================================================
// Tests
// ==========================================================================

test.describe('UI responsiveness during active scans', () => {
  const TOTAL_REFS = 50; // large enough to stress-test renders
  const SESSION = 'sess-responsive';
  const CHECK_ID = 900;

  let serverState;

  test.beforeEach(async ({ page }) => {
    serverState = {
      startQueue: [
        {
          sessionId: SESSION,
          checkId: CHECK_ID,
          paperTitle: 'Responsiveness Test Paper',
          paperSource: 'responsive.pdf',
          totalRefs: TOTAL_REFS,
        },
      ],
      history: [],
      details: {},
    };

    await setupApiMock(page, serverState);
  });

  // ---------- Test 1: UI stays interactive during rapid WS messages ----------
  test('page remains responsive during a burst of reference results', async ({ page }) => {
    const { emit } = await setupWebSocketMock(page);
    await page.goto('/');

    // Start the check
    await page.getByPlaceholder(/Enter ArXiv ID/i).fill('http://responsive.example');
    await page.getByRole('button', { name: 'Check References' }).click();
    await expect(page.getByRole('main').getByRole('button', { name: 'Cancel' })).toBeVisible();

    // Extract references
    await emit(SESSION, {
      type: 'references_extracted',
      references: skeletonRefs(TOTAL_REFS),
      total_refs: TOTAL_REFS,
      count: TOTAL_REFS,
    });
    await page.waitForTimeout(200);

    // Burst-emit all reference results + summary updates rapidly
    const burstStart = Date.now();
    for (let i = 1; i <= TOTAL_REFS; i++) {
      const status = i % 5 === 0 ? 'error' : i % 7 === 0 ? 'warning' : 'verified';
      await emit(SESSION, refResult(i, status));
      // Emit a summary update every 5 refs (like the real backend)
      if (i % 5 === 0) {
        const errs = Math.floor(i / 5);
        const warns = Array.from({ length: i }, (_, j) => (j + 1) % 7 === 0 && (j + 1) % 5 !== 0).filter(Boolean).length;
        await emit(SESSION, summaryUpdate(i, TOTAL_REFS, errs, warns));
      }
    }
    expect(Date.now() - burstStart).toBeGreaterThanOrEqual(0);

    // After burst, the UI must be interactive: we test by clicking a button
    // and checking it responds within a reasonable time (< 2s).
    const interactionStart = Date.now();

    // Scroll the reference list - this requires the main thread to be free
    const main = page.locator('main');
    await main.evaluate((el) => el.scrollTo({ top: 9999 }));

    // The last reference should be visible after scroll
    await expect(page.getByText(`Reference ${TOTAL_REFS}`)).toBeVisible({ timeout: 3000 });
    const interactionDuration = Date.now() - interactionStart;

    // The interaction should be quick (< 3s). If the UI were blocked,
    // this would time out or take many seconds.
    expect(interactionDuration).toBeLessThan(3000);

    // Verify correct reference count rendered
    await expect(page.getByText(`References (${TOTAL_REFS})`)).toBeVisible();
  });

  // ---------- Test 2: Window resize is responsive during scan ----------
  test('window resize works during active scan', async ({ page }) => {
    const { emit } = await setupWebSocketMock(page);
    await page.goto('/');

    // Start the check
    await page.getByPlaceholder(/Enter ArXiv ID/i).fill('http://responsive.example');
    await page.getByRole('button', { name: 'Check References' }).click();
    await expect(page.getByRole('main').getByRole('button', { name: 'Cancel' })).toBeVisible();

    // Extract references
    await emit(SESSION, {
      type: 'references_extracted',
      references: skeletonRefs(TOTAL_REFS),
      total_refs: TOTAL_REFS,
      count: TOTAL_REFS,
    });
    await page.waitForTimeout(200);

    // Emit half the results to simulate an active scan
    for (let i = 1; i <= TOTAL_REFS / 2; i++) {
      await emit(SESSION, refResult(i, 'verified'));
    }
    await emit(SESSION, summaryUpdate(TOTAL_REFS / 2, TOTAL_REFS));

    // Now resize the window several times while messages are still flowing
    const originalSize = page.viewportSize();
    const resizeStart = Date.now();

    await page.setViewportSize({ width: 800, height: 600 });
    // Emit more results during resize
    for (let i = TOTAL_REFS / 2 + 1; i <= TOTAL_REFS / 2 + 5; i++) {
      await emit(SESSION, refResult(i, 'verified'));
    }

    await page.setViewportSize({ width: 1200, height: 900 });
    for (let i = TOTAL_REFS / 2 + 6; i <= TOTAL_REFS / 2 + 10; i++) {
      await emit(SESSION, refResult(i, 'error'));
    }

    await page.setViewportSize({ width: 600, height: 400 });
    await page.waitForTimeout(100);
    await page.setViewportSize({ width: originalSize.width, height: originalSize.height });

    const resizeDuration = Date.now() - resizeStart;

    // Resize operations + concurrent WS messages should complete quickly
    expect(resizeDuration).toBeLessThan(5000);

    // UI should still be functional after resize stress
    await expect(page.getByText(`References (${TOTAL_REFS})`)).toBeVisible({ timeout: 3000 });

    // Verify the cancel button is still clickable (UI not frozen)
    const cancelBtn = page.getByRole('main').getByRole('button', { name: 'Cancel' });
    await expect(cancelBtn).toBeEnabled({ timeout: 2000 });
  });

  // ---------- Test 3: Memoization correctness ----------
  test('reference cards update correctly with memoized rendering', async ({ page }) => {
    const { emit } = await setupWebSocketMock(page);
    await page.goto('/');

    // Start check
    await page.getByPlaceholder(/Enter ArXiv ID/i).fill('http://responsive.example');
    await page.getByRole('button', { name: 'Check References' }).click();
    await expect(page.getByRole('main').getByRole('button', { name: 'Cancel' })).toBeVisible();

    // Extract a smaller set of references
    const smallCount = 6;
    await emit(SESSION, {
      type: 'references_extracted',
      references: skeletonRefs(smallCount),
      total_refs: smallCount,
      count: smallCount,
    });
    await page.waitForTimeout(200);

    // All 6 should initially be pending (clock icons or similar)
    await expect(page.getByText(`References (${smallCount})`)).toBeVisible();

    // Emit results one-by-one and check each card updates
    // Ref 1: verified
    await emit(SESSION, refResult(1, 'verified'));
    await emit(SESSION, summaryUpdate(1, smallCount));
    await page.waitForTimeout(100);

    // Ref 1 should show checkmark (verified)
    const ref1Card = page.locator('.divide-y > div').nth(0);
    await expect(ref1Card.locator('svg circle[fill="var(--color-success)"]')).toBeVisible({ timeout: 2000 });

    // Ref 2: error
    await emit(SESSION, refResult(2, 'error'));
    await emit(SESSION, summaryUpdate(2, smallCount, 1));
    await page.waitForTimeout(100);

    // Ref 2 should show error icon (circle with error color)
    const ref2Card = page.locator('.divide-y > div').nth(1);
    await expect(ref2Card.locator('svg circle[fill="var(--color-error)"]')).toBeVisible({ timeout: 2000 });

    // Ref 1 should STILL show verified (not regressed)
    await expect(ref1Card.locator('svg circle[fill="var(--color-success)"]')).toBeVisible();

    // Ref 3: warning
    await emit(SESSION, refResult(3, 'warning'));
    await emit(SESSION, summaryUpdate(3, smallCount, 1, 1));
    await page.waitForTimeout(100);

    // Warning icon uses a triangle path, not a circle
    const ref3Card = page.locator('.divide-y > div').nth(2);
    await expect(ref3Card.locator('svg path[fill="var(--color-warning)"]')).toBeVisible({ timeout: 2000 });

    // Refs 4-6 should still show pending/checking (not yet processed)
    const ref4Card = page.locator('.divide-y > div').nth(3);
    const ref4HasSpinner = await ref4Card.locator('svg.animate-spin').count();
    const ref4HasClock = await ref4Card.locator('svg path[d*="M12 7v5l3 2"]').count();
    // Should have either spinner or clock (pending state)
    expect(ref4HasSpinner + ref4HasClock).toBeGreaterThan(0);

    // Complete remaining refs
    for (let i = 4; i <= smallCount; i++) {
      await emit(SESSION, refResult(i, 'verified'));
    }
    await emit(SESSION, summaryUpdate(smallCount, smallCount, 1, 1));
    await page.waitForTimeout(200);

    // All refs should now show final status
    // Summary should show all as processed
    await expect(page.getByText(`of ${smallCount}`, { exact: true })).toBeVisible({ timeout: 2000 });

    // Complete the check
    await emit(SESSION, {
      type: 'completed',
      check_id: CHECK_ID,
      total_refs: smallCount,
      processed_refs: smallCount,
      errors_count: 1,
      warnings_count: 1,
      suggestions_count: 0,
      unverified_count: 0,
      hallucination_count: 0,
      verified_count: smallCount - 2,
      refs_with_errors: 1,
      refs_with_warnings_only: 1,
      refs_verified: smallCount - 2,
    });

    await page.waitForTimeout(300);
    // Status should show completed
    await expect(page.getByText('Check completed')).toBeVisible({ timeout: 3000 });
  });

  // ---------- Test 4: Sidebar interaction during scan ----------
  test('sidebar remains clickable during active scan', async ({ page }) => {
    // Add a completed history item so sidebar has something to click
    serverState.history = [
      {
        id: 800,
        paper_title: 'Old Paper',
        paper_source: 'old.pdf',
        timestamp: '2024-01-01T00:00:00Z',
        total_refs: 2,
        errors_count: 0,
        warnings_count: 0,
        status: 'completed',
      },
    ];
    serverState.details[800] = {
      ...serverState.history[0],
      results: [
        { index: 1, title: 'Old Ref A', status: 'verified', errors: [], warnings: [], authoritative_urls: [] },
        { index: 2, title: 'Old Ref B', status: 'verified', errors: [], warnings: [], authoritative_urls: [] },
      ],
    };

    const { emit } = await setupWebSocketMock(page);
    await page.goto('/');

    const sidebar = page.locator('aside.sidebar-desktop');

    // Start the scan
    await page.getByPlaceholder(/Enter ArXiv ID/i).fill('http://responsive.example');
    await page.getByRole('button', { name: 'Check References' }).click();
    await expect(page.getByRole('main').getByRole('button', { name: 'Cancel' })).toBeVisible();

    // Extract and start emitting results
    await emit(SESSION, {
      type: 'references_extracted',
      references: skeletonRefs(TOTAL_REFS),
      total_refs: TOTAL_REFS,
      count: TOTAL_REFS,
    });

    // Emit some results
    for (let i = 1; i <= 10; i++) {
      await emit(SESSION, refResult(i, 'verified'));
    }
    await emit(SESSION, summaryUpdate(10, TOTAL_REFS));

    // While scan is in progress, click the old history item in sidebar
    const clickStart = Date.now();
    await sidebar.getByText('Old Paper', { exact: true }).click();
    const clickDuration = Date.now() - clickStart;

    // Sidebar click should respond quickly
    expect(clickDuration).toBeLessThan(2000);

    // Should show the old paper's references
    await expect(page.getByText('References (2)')).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('Old Ref A')).toBeVisible();

    // Switch back to the active check
    await sidebar.getByText('Responsiveness Test Paper').click();
    // Verify we navigated back — the status section should show the active check
    await expect(page.getByText('Responsiveness Test Paper').first()).toBeVisible({ timeout: 3000 });
  });

  // ---------- Test 5: Main-thread jank measurement during progress updates ----------
  test('main thread stays responsive while progress bar updates', async ({ page }) => {
    const { emit } = await setupWebSocketMock(page);
    await page.goto('/');

    // Start the check
    await page.getByPlaceholder(/Enter ArXiv ID/i).fill('http://responsive.example');
    await page.getByRole('button', { name: 'Check References' }).click();
    await expect(page.getByRole('main').getByRole('button', { name: 'Cancel' })).toBeVisible();

    // Extract references
    await emit(SESSION, {
      type: 'references_extracted',
      references: skeletonRefs(TOTAL_REFS),
      total_refs: TOTAL_REFS,
      count: TOTAL_REFS,
    });
    await page.waitForTimeout(200);

    // Inject a rAF jank monitor that tracks the longest gap between frames
    await page.evaluate(() => {
      window.__frameTimes = [];
      window.__jankMonitorRunning = true;
      let last = performance.now();
      function tick() {
        if (!window.__jankMonitorRunning) return;
        const now = performance.now();
        window.__frameTimes.push(now - last);
        last = now;
        requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    });

    // Emit reference results with summary_update after each one (worst-case)
    // This simulates the real backend which sends checking_reference +
    // reference_result + summary_update per reference
    for (let i = 1; i <= TOTAL_REFS; i++) {
      const status = i % 5 === 0 ? 'error' : 'verified';
      await emit(SESSION, { type: 'checking_reference', index: i });
      await emit(SESSION, refResult(i, status));
      await emit(SESSION, summaryUpdate(i, TOTAL_REFS, i % 5 === 0 ? Math.floor(i / 5) : Math.floor((i - 1) / 5)));
    }

    // Let the UI settle
    await page.waitForTimeout(500);

    // Stop the jank monitor and collect results
    const jankStats = await page.evaluate(() => {
      window.__jankMonitorRunning = false;
      const times = window.__frameTimes;
      if (times.length === 0) return { maxFrame: 0, avgFrame: 0, jankyFrames: 0, totalFrames: 0 };
      const maxFrame = Math.max(...times);
      const avgFrame = times.reduce((a, b) => a + b, 0) / times.length;
      // Frames > 100ms are "janky" (6+ frames dropped at 60fps)
      const jankyFrames = times.filter(t => t > 100).length;
      // Frames > 300ms are "frozen" (user-noticeable hang)
      const frozenFrames = times.filter(t => t > 300).length;
      return { maxFrame: Math.round(maxFrame), avgFrame: Math.round(avgFrame), jankyFrames, frozenFrames, totalFrames: times.length };
    });

    console.log('Jank stats:', JSON.stringify(jankStats));

    // The main thread should never be blocked for > 300ms (frozen)
    // which is the threshold where resize/interaction feels broken
    expect(jankStats.frozenFrames).toBe(0);
    // Max frame gap should be under 500ms
    expect(jankStats.maxFrame).toBeLessThan(500);

    // Also verify the progress bar reached ~100%
    const progressText = await page.locator('main').locator('text=/\\d+% complete/').first().textContent();
    expect(parseInt(progressText)).toBeGreaterThanOrEqual(90);

    // Verify a resize works right now
    const origSize = page.viewportSize();
    await page.setViewportSize({ width: 800, height: 500 });
    await page.waitForTimeout(100);
    // The progress bar should still be visible after resize
    await expect(page.locator('main').locator('text=/\\d+% complete/').first()).toBeVisible({ timeout: 1000 });
    await page.setViewportSize(origSize);
  });
});
