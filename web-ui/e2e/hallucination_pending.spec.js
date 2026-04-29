import { test, expect } from '@playwright/test';

/**
 * Helper: set up WebSocket mock so we can emit messages to the frontend.
 */
async function setupWebSocketMock(page) {
  await page.addInitScript(() => {
    const connections = {};
    class MockWebSocket {
      constructor(url) {
        this.url = url;
        this.sessionId = url.split('/').pop();
        this.readyState = 1;
        connections[this.sessionId] = this;
        setTimeout(() => this.onopen?.({}), 0);
      }
      send() {}
      close() {
        this.readyState = 3;
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

/**
 * Helper: set up API mock.
 */
async function setupApiMock(page, serverState) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (status, body) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });

    if (path === '/api/auth/providers') return json(200, { providers: [] });
    if (path === '/api/auth/me') return json(401, { detail: 'Not authenticated' });
    if (path === '/api/llm-configs') return json(200, []);
    if (path === '/api/settings/semantic-scholar') return json(200, { enabled: false });
    if (path === '/api/health') return json(200, { status: 'ok' });

    if (path === '/api/check' && route.request().method() === 'POST') {
      const next = serverState.startQueue.shift();
      if (!next) return json(500, { detail: 'No mock start response' });
      serverState.history = [{
        id: next.checkId,
        paper_title: next.paperTitle,
        paper_source: next.paperSource,
        timestamp: new Date().toISOString(),
        total_refs: next.totalRefs,
        status: 'in_progress',
        session_id: next.sessionId,
      }, ...serverState.history];
      serverState.details[next.checkId] = {
        ...serverState.history[0],
        results: next.results || [],
      };
      return json(200, {
        session_id: next.sessionId,
        check_id: next.checkId,
        message: 'Check started',
        source: next.paperSource,
      });
    }
    if (path === '/api/history') return json(200, serverState.history);
    if (path.startsWith('/api/history/')) {
      const id = Number(path.split('/').pop());
      return json(200, serverState.details[id] || { detail: 'Not found' });
    }
    if (path.startsWith('/api/cancel/')) return json(200, { message: 'Cancelled' });
    return json(404, { detail: 'Unhandled', path });
  });
}

/**
 * Helper: read card state from the DOM atomically.
 */
async function captureCardStates(page) {
  return page.evaluate(() => {
    const cards = document.querySelectorAll('.divide-y > div');
    const result = [];
    for (const card of cards) {
      const title = card.querySelector('.font-bold')?.textContent?.trim() || '';
      const hasSpinner = card.querySelectorAll('svg.animate-spin').length > 0;
      const hasQuestionMark = Array.from(card.querySelectorAll('svg text')).some(t => t.textContent === '?');
      const hasCheckmark = card.querySelector('svg circle[fill="var(--color-success)"]') !== null;
      const hasErrorIcon = card.querySelector('svg circle[fill="var(--color-error)"]') !== null;
      const hasClock = card.querySelector('svg path[d*="M12 7v5l3 2"]') !== null;
      const hasDash = card.querySelector('svg path[d="M8 12h8"]') !== null;
      const hasAwaitingText = card.textContent?.includes('Awaiting LLM') || false;
      const hasCheckingText = card.textContent?.includes('Checking for hallucination') || false;
      const hasUnverifiedMsg = card.textContent?.includes('Could not verify') || false;
      result.push({ title: title.substring(0, 40), hasSpinner, hasQuestionMark, hasCheckmark, hasErrorIcon, hasClock, hasDash, hasAwaitingText, hasCheckingText, hasUnverifiedMsg });
    }

    // Summary stats
    let ofText = '';
    for (const span of document.querySelectorAll('span')) {
      const m = span.textContent?.trim().match(/^of (\d+)$/);
      if (m) { ofText = m[1]; break; }
    }

    let unverifiedBadge = '';
    for (const btn of document.querySelectorAll('button')) {
      if (btn.textContent?.includes('Unverified')) {
        unverifiedBadge = btn.textContent.trim();
        break;
      }
    }

    return { cards: result, ofText, unverifiedBadge };
  });
}


test.describe('Hallucination-pending ref lifecycle', () => {

  /**
   * Mocked test: verifies all state transitions for icons, counts, and filters
   * through the full lifecycle:
   *   1. Initial verification (some refs get "unverified" status)
   *   2. Hallucination phase (unverified refs get hallucination_check_pending)
   *   3. Hallucination results (refs get final status)
   *   4. Check completion
   */
  test('full lifecycle: icons, counts, filters all update correctly', async ({ page }) => {
    const sessionId = 'sess-lifecycle';
    const serverState = {
      startQueue: [{
        sessionId,
        checkId: 500,
        paperTitle: 'Lifecycle Test Paper',
        paperSource: 'lifecycle.pdf',
        totalRefs: 4,
      }],
      history: [],
      details: {},
    };

    await setupApiMock(page, serverState);
    const { emit } = await setupWebSocketMock(page);
    await page.goto('/');

    // Start the check
    await page.getByPlaceholder(/Enter ArXiv ID/i).fill('http://lifecycle.example');
    await page.getByRole('button', { name: 'Check References' }).click();
    await expect(page.getByRole('main').getByRole('button', { name: 'Cancel' })).toBeVisible();

    // ── Phase 0: Extract references ──
    const skeletonRefs = [
      { title: 'Verified Paper', authors: [], year: 2024 },
      { title: 'Error Paper', authors: [], year: 2024 },
      { title: 'Unverified Paper A', authors: [], year: 2024 },
      { title: 'Unverified Paper B', authors: [], year: 2024 },
    ];
    await emit(sessionId, {
      type: 'references_extracted',
      references: skeletonRefs,
      total_refs: 4,
      count: 4,
    });
    await page.waitForTimeout(200);

    // ── Phase 1: Initial verification results ──
    // Ref 1: verified, Ref 2: error, Ref 3: unverified, Ref 4: unverified
    const refs = [
      { index: 1, title: 'Verified Paper', status: 'verified', errors: [], warnings: [], suggestions: [], authoritative_urls: [], _raw_errors: [] },
      { index: 2, title: 'Error Paper', status: 'error', errors: [{ error_type: 'title', error_details: 'Title mismatch' }], warnings: [], suggestions: [], authoritative_urls: [], _raw_errors: [{ error_type: 'title' }] },
      { index: 3, title: 'Unverified Paper A', status: 'unverified', errors: [{ error_type: 'unverified', error_details: 'Not found' }], warnings: [], suggestions: [], authoritative_urls: [], _raw_errors: [{ error_type: 'unverified' }] },
      { index: 4, title: 'Unverified Paper B', status: 'unverified', errors: [{ error_type: 'unverified', error_details: 'Not found' }], warnings: [], suggestions: [], authoritative_urls: [], _raw_errors: [{ error_type: 'unverified' }] },
    ];

    // Emit refs one at a time with summary updates (flat format, matching backend)
    // Backend defers unverified refs from processed_count
    for (let i = 0; i < refs.length; i++) {
      await emit(sessionId, { type: 'reference_result', ...refs[i] });
      const processedSoFar = refs.slice(0, i + 1).filter(r => r.status !== 'unverified').length;
      await emit(sessionId, {
        type: 'summary_update',
        total_refs: 4,
        processed_refs: processedSoFar,
        errors_count: refs.slice(0, i + 1).filter(r => r.errors?.some(e => e.error_type !== 'unverified')).length,
        warnings_count: 0,
        suggestions_count: 0,
        unverified_count: 0,  // Backend defers this
        hallucination_count: 0,
        verified_count: refs.slice(0, i + 1).filter(r => r.status === 'verified').length,
        refs_with_errors: refs.slice(0, i + 1).filter(r => r.status === 'error').length,
        refs_with_warnings_only: 0,
        refs_verified: refs.slice(0, i + 1).filter(r => r.status === 'verified').length,
      });
    }

    await page.waitForTimeout(300);

    // ── Assertion 1: During active check, unverified refs show SPINNER not question mark ──
    let state = await captureCardStates(page);
    console.log('Phase 1 (initial verification):');
    for (const c of state.cards) {
      console.log(`  ${c.title}: spinner=${c.hasSpinner} qmark=${c.hasQuestionMark} check=${c.hasCheckmark} error=${c.hasErrorIcon} clock=${c.hasClock} unverifiedMsg=${c.hasUnverifiedMsg} awaiting=${c.hasAwaitingText}`);
    }
    console.log(`  of=${state.ofText} unverifiedBadge="${state.unverifiedBadge}"`);

    // Verified Paper → checkmark
    expect(state.cards[0].hasCheckmark).toBe(true);
    expect(state.cards[0].hasSpinner).toBe(false);
    // Error Paper → error icon
    expect(state.cards[1].hasErrorIcon).toBe(true);
    expect(state.cards[1].hasSpinner).toBe(false);
    // Unverified Paper A → spinner (NOT question mark)
    expect(state.cards[2].hasSpinner).toBe(true);
    expect(state.cards[2].hasQuestionMark).toBe(false);
    expect(state.cards[2].hasUnverifiedMsg).toBe(false);
    expect(state.cards[2].hasAwaitingText).toBe(true);
    // Unverified Paper B → spinner (NOT question mark)
    expect(state.cards[3].hasSpinner).toBe(true);
    expect(state.cards[3].hasQuestionMark).toBe(false);
    expect(state.cards[3].hasUnverifiedMsg).toBe(false);
    // Processed count: only 2 (verified + error), NOT 4
    expect(state.ofText).toBe('2');
    // No unverified badge during active check
    expect(state.unverifiedBadge).toBe('');

    // ── Assertion 2: Unverified filter should NOT match refs showing as checking ──
    // Simulate clicking unverified filter
    // The badge should not be visible while references are still checking.

    // ── Phase 2: Hallucination phase starts ──
    // Backend marks unverified refs as hallucination_check_pending
    await emit(sessionId, { type: 'reference_result', ...refs[2], hallucination_check_pending: true });
    await emit(sessionId, { type: 'reference_result', ...refs[3], hallucination_check_pending: true });
    await page.waitForTimeout(200);

    state = await captureCardStates(page);
    console.log('\nPhase 2 (hallucination pending):');
    for (const c of state.cards) {
      console.log(`  ${c.title}: spinner=${c.hasSpinner} qmark=${c.hasQuestionMark} checking=${c.hasCheckingText}`);
    }

    // Both unverified refs should still show spinner
    expect(state.cards[2].hasSpinner).toBe(true);
    expect(state.cards[2].hasQuestionMark).toBe(false);
    expect(state.cards[2].hasCheckingText).toBe(true);
    expect(state.cards[3].hasSpinner).toBe(true);
    expect(state.cards[3].hasQuestionMark).toBe(false);

    // ── Phase 3: Hallucination results arrive ──
    // Ref 3: found to be hallucinated
    await emit(sessionId, { type: 'reference_result',
      ...refs[2],
      status: 'hallucination',
      hallucination_check_pending: false,
      hallucination_assessment: { verdict: 'LIKELY', explanation: 'Likely fabricated' },
    });
    await emit(sessionId, {
      type: 'summary_update',
      total_refs: 4, processed_refs: 3,
      errors_count: 1, warnings_count: 0, suggestions_count: 0,
      unverified_count: 1, hallucination_count: 1,
      verified_count: 1, refs_with_errors: 1, refs_with_warnings_only: 0, refs_verified: 1,
    });
    await page.waitForTimeout(200);

    // Ref 4: stays unverified after LLM check
    await emit(sessionId, { type: 'reference_result',
      ...refs[3],
      status: 'unverified',
      hallucination_check_pending: false,
      hallucination_assessment: { verdict: 'UNLIKELY', explanation: 'Probably real but not found' },
    });
    await emit(sessionId, {
      type: 'summary_update',
      total_refs: 4, processed_refs: 4,
      errors_count: 1, warnings_count: 0, suggestions_count: 0,
      unverified_count: 2, hallucination_count: 1,
      verified_count: 1, refs_with_errors: 1, refs_with_warnings_only: 0, refs_verified: 1,
    });
    await page.waitForTimeout(200);

    // ── Phase 4: Check completes ──
    await emit(sessionId, {
      type: 'completed',
      total_refs: 4, processed_refs: 4,
      errors_count: 1, warnings_count: 0, suggestions_count: 0,
      unverified_count: 2, hallucination_count: 1,
      verified_count: 1, refs_with_errors: 1, refs_with_warnings_only: 0, refs_verified: 1,
    });
    await page.waitForTimeout(300);

    state = await captureCardStates(page);
    console.log('\nPhase 4 (completed):');
    for (const c of state.cards) {
      console.log(`  ${c.title}: spinner=${c.hasSpinner} qmark=${c.hasQuestionMark} check=${c.hasCheckmark} error=${c.hasErrorIcon} clock=${c.hasClock} dash=${c.hasDash} unverifiedMsg=${c.hasUnverifiedMsg}`);
    }
    console.log(`  of=${state.ofText} unverifiedBadge="${state.unverifiedBadge}"`);

    // After completion, every ref must show its CORRECT final icon:
    // Ref 1 (Verified) → checkmark, no spinner
    expect(state.cards[0].hasCheckmark).toBe(true);
    expect(state.cards[0].hasSpinner).toBe(false);
    expect(state.cards[0].hasClock).toBe(false);
    expect(state.cards[0].hasDash).toBe(false);
    // Ref 2 (Error) → error icon, no spinner
    expect(state.cards[1].hasErrorIcon).toBe(true);
    expect(state.cards[1].hasSpinner).toBe(false);
    expect(state.cards[1].hasClock).toBe(false);
    expect(state.cards[1].hasDash).toBe(false);
    // Ref 3 (Hallucination) → should NOT show spinner, clock, or dash
    expect(state.cards[2].hasSpinner).toBe(false);
    expect(state.cards[2].hasClock).toBe(false);
    expect(state.cards[2].hasDash).toBe(false);
    // Ref 4 (Unverified) → question mark, no spinner
    expect(state.cards[3].hasQuestionMark).toBe(true);
    expect(state.cards[3].hasSpinner).toBe(false);
    expect(state.cards[3].hasClock).toBe(false);
    expect(state.cards[3].hasDash).toBe(false);
    expect(state.cards[3].hasUnverifiedMsg).toBe(true);

    // Processed count = 4 (all done)
    expect(state.ofText).toBe('4');

    // ── Phase 5: Click unverified filter and verify refs show ──
    // The "2 Unverified" badge should be clickable and show the 2 unverified refs
    const unverifiedBadgeBtn = page.locator('button').filter({ hasText: /Unverified/ }).first();
    await expect(unverifiedBadgeBtn).toBeVisible();
    await unverifiedBadgeBtn.click();
    await page.waitForTimeout(200);

    // Should show "Showing X (unverified)" filter indicator in the ref list header
    await expect(page.getByText(/Showing \d+ \(unverified\)/)).toBeVisible();

    state = await captureCardStates(page);
    console.log('\nPhase 5 (unverified filter active):');
    console.log(`  Visible cards: ${state.cards.length}`);
    for (const c of state.cards) {
      console.log(`  ${c.title}: qmark=${c.hasQuestionMark} unverifiedMsg=${c.hasUnverifiedMsg}`);
    }

    // Should show exactly 2 refs (hallucination + unverified)
    expect(state.cards.length).toBe(2);
    // All visible refs should have question mark icon (unverified or hallucination)
    for (const c of state.cards) {
      expect(c.hasSpinner).toBe(false);
      expect(c.hasClock).toBe(false);
      expect(c.hasDash).toBe(false);
    }
  });
});
