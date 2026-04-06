import { test, expect } from '@playwright/test';

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
      close() { this.readyState = 3; delete connections[this.sessionId]; this.onclose?.({ code: 1000 }); }
      _emit(data) { this.onmessage?.({ data: JSON.stringify(data) }); }
    }
    window.__wsConnections = connections;
    window.WebSocket = MockWebSocket;
  });
  return async (sessionId, payload) => {
    await page.waitForFunction((id) => !!window.__wsConnections?.[id], sessionId);
    await page.evaluate(([id, data]) => { window.__wsConnections[id]?._emit(data); }, [sessionId, payload]);
  };
}

async function setupApiMock(page, serverState) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (s, b) => route.fulfill({ status: s, contentType: 'application/json', body: JSON.stringify(b) });
    if (path === '/api/auth/providers') return json(200, { providers: [] });
    if (path === '/api/auth/me') return json(401, {});
    if (path === '/api/llm-configs') return json(200, []);
    if (path === '/api/settings/semantic-scholar') return json(200, { enabled: false });
    if (path === '/api/health') return json(200, { status: 'ok' });
    if (path === '/api/check' && route.request().method() === 'POST') {
      const next = serverState.startQueue.shift();
      if (!next) return json(500, {});
      serverState.history = [{ id: next.checkId, paper_title: next.paperTitle, paper_source: next.paperSource, timestamp: new Date().toISOString(), total_refs: next.totalRefs, status: 'in_progress', session_id: next.sessionId }, ...serverState.history];
      serverState.details[next.checkId] = { ...serverState.history[0], results: [] };
      return json(200, { session_id: next.sessionId, check_id: next.checkId, message: 'Started', source: next.paperSource });
    }
    if (path === '/api/history') return json(200, serverState.history);
    if (path.startsWith('/api/history/')) { const id = Number(path.split('/').pop()); return json(200, serverState.details[id] || {}); }
    if (path.startsWith('/api/cancel/')) return json(200, {});
    return json(404, {});
  });
}

/**
 * Simulate the full 77-ref check lifecycle and verify icons NEVER regress.
 * Specifically: once a ref gets verified/error/warning status, it must NEVER
 * revert to pending/checking/unchecked.
 */
test('icons never regress: verified refs never show clock/unchecked', async ({ page }) => {
  const totalRefs = 10; // Smaller than 77 for speed, same logic
  const unverifiedCount = 3;
  const sessionId = 'sess-stability';

  const serverState = {
    startQueue: [{ sessionId, checkId: 700, paperTitle: 'Stability Test', paperSource: 'stability.pdf', totalRefs }],
    history: [],
    details: {},
  };

  await setupApiMock(page, serverState);
  const emit = await setupWebSocketMock(page);
  await page.goto('/');

  await page.getByPlaceholder(/Enter ArXiv ID/i).fill('http://stability.example');
  await page.getByRole('button', { name: 'Check References' }).click();
  await expect(page.getByRole('main').getByRole('button', { name: 'Cancel' })).toBeVisible();

  // Extract refs
  const skeletons = Array.from({ length: totalRefs }, (_, i) => ({ title: `Ref ${i + 1}`, authors: [], year: 2024 }));
  await emit(sessionId, { type: 'references_extracted', references: skeletons, total_refs: totalRefs, count: totalRefs });
  await page.waitForTimeout(200);

  // Build ref results: first N-unverifiedCount are verified/error, last unverifiedCount are unverified
  const refResults = [];
  for (let i = 0; i < totalRefs; i++) {
    const isUnverified = i >= totalRefs - unverifiedCount;
    refResults.push({
      index: i + 1,
      title: `Ref ${i + 1}`,
      authors: [],
      year: 2024,
      status: isUnverified ? 'unverified' : (i % 3 === 0 ? 'verified' : (i % 3 === 1 ? 'error' : 'warning')),
      errors: isUnverified
        ? [{ error_type: 'unverified', error_details: 'Not found' }]
        : (i % 3 === 1 ? [{ error_type: 'title', error_details: 'Mismatch' }] : []),
      warnings: i % 3 === 2 ? [{ error_type: 'year', error_details: 'Year off' }] : [],
      suggestions: [],
      authoritative_urls: [],
      _raw_errors: isUnverified ? [{ error_type: 'unverified' }] : (i % 3 !== 0 ? [{ error_type: 'other' }] : []),
    });
  }

  // ── Phase 1: Emit all ref results (simulating initial verification) ──
  let processedCount = 0;
  for (const ref of refResults) {
    if (ref.status !== 'unverified') processedCount++;
    await emit(sessionId, { type: 'reference_result', ...ref });
    await emit(sessionId, { type: 'summary_update', total_refs: totalRefs, processed_refs: processedCount,
      errors_count: 0, warnings_count: 0, suggestions_count: 0, unverified_count: 0,
      hallucination_count: 0, verified_count: processedCount, refs_with_errors: 0,
      refs_with_warnings_only: 0, refs_verified: processedCount });
  }
  await page.waitForTimeout(300);

  // ── Snapshot after initial verification ──
  let state = await page.evaluate(() => {
    const cards = document.querySelectorAll('.divide-y > div');
    return Array.from(cards).map(card => {
      const title = card.querySelector('.font-bold')?.textContent?.trim() || '';
      const hasClock = card.querySelector('svg path[d*="M12 7v5l3 2"]') !== null;
      const hasDash = card.querySelector('svg path[d="M8 12h8"]') !== null;
      const hasSpinner = card.querySelectorAll('svg.animate-spin').length > 0;
      const hasCheckmark = card.querySelector('svg circle[fill="var(--color-success)"]') !== null;
      const hasErrorIcon = card.querySelector('svg circle[fill="var(--color-error)"]') !== null;
      return { title: title.substring(0, 20), hasClock, hasDash, hasSpinner, hasCheckmark, hasErrorIcon };
    });
  });

  console.log('After initial verification:');
  for (const c of state) console.log(`  ${c.title}: clock=${c.hasClock} dash=${c.hasDash} spinner=${c.hasSpinner} check=${c.hasCheckmark} error=${c.hasErrorIcon}`);

  // Non-unverified refs (0-6) must NOT have clock or dash
  for (let i = 0; i < totalRefs - unverifiedCount; i++) {
    expect(state[i].hasClock).toBe(false);
    expect(state[i].hasDash).toBe(false);
  }
  // Unverified refs (7-9) must have spinner
  for (let i = totalRefs - unverifiedCount; i < totalRefs; i++) {
    expect(state[i].hasSpinner).toBe(true);
  }

  // ── Phase 2: Hallucination phase ──
  // Mark unverified refs as pending
  for (let i = totalRefs - unverifiedCount; i < totalRefs; i++) {
    await emit(sessionId, { type: 'reference_result', ...refResults[i], hallucination_check_pending: true });
  }
  await page.waitForTimeout(200);

  // Complete hallucination checks one by one
  for (let i = totalRefs - unverifiedCount; i < totalRefs; i++) {
    processedCount++;
    const isHallucinated = i === totalRefs - 1; // Last one is hallucinated
    await emit(sessionId, { type: 'reference_result', ...refResults[i],
      status: isHallucinated ? 'hallucination' : 'unverified',
      hallucination_check_pending: false,
      hallucination_assessment: isHallucinated
        ? { verdict: 'LIKELY', explanation: 'Fabricated' }
        : { verdict: 'UNLIKELY', explanation: 'Not found but real' },
    });
    await emit(sessionId, { type: 'summary_update', total_refs: totalRefs, processed_refs: processedCount,
      errors_count: 0, warnings_count: 0, suggestions_count: 0, unverified_count: processedCount - (totalRefs - unverifiedCount),
      hallucination_count: isHallucinated ? 1 : 0, verified_count: totalRefs - unverifiedCount,
      refs_with_errors: 0, refs_with_warnings_only: 0, refs_verified: totalRefs - unverifiedCount });
  }
  await page.waitForTimeout(200);

  // ── Snapshot after hallucination phase, BEFORE completion ──
  state = await page.evaluate(() => {
    const cards = document.querySelectorAll('.divide-y > div');
    return Array.from(cards).map(card => {
      const title = card.querySelector('.font-bold')?.textContent?.trim() || '';
      const hasClock = card.querySelector('svg path[d*="M12 7v5l3 2"]') !== null;
      const hasDash = card.querySelector('svg path[d="M8 12h8"]') !== null;
      const hasSpinner = card.querySelectorAll('svg.animate-spin').length > 0;
      return { title: title.substring(0, 20), hasClock, hasDash, hasSpinner };
    });
  });

  console.log('\nAfter hallucination phase (before completion):');
  for (const c of state) console.log(`  ${c.title}: clock=${c.hasClock} dash=${c.hasDash} spinner=${c.hasSpinner}`);

  // NO ref should have clock or dash at this point
  for (const c of state) {
    expect(c.hasClock).toBe(false);
    expect(c.hasDash).toBe(false);
  }

  // ── Phase 3: Complete ──
  await emit(sessionId, { type: 'completed', total_refs: totalRefs, processed_refs: totalRefs,
    errors_count: 0, warnings_count: 0, suggestions_count: 0, unverified_count: unverifiedCount,
    hallucination_count: 1, verified_count: totalRefs - unverifiedCount,
    refs_with_errors: 0, refs_with_warnings_only: 0, refs_verified: totalRefs - unverifiedCount });
  await page.waitForTimeout(300);

  state = await page.evaluate(() => {
    const cards = document.querySelectorAll('.divide-y > div');
    return Array.from(cards).map(card => {
      const title = card.querySelector('.font-bold')?.textContent?.trim() || '';
      const hasClock = card.querySelector('svg path[d*="M12 7v5l3 2"]') !== null;
      const hasDash = card.querySelector('svg path[d="M8 12h8"]') !== null;
      const hasSpinner = card.querySelectorAll('svg.animate-spin').length > 0;
      const hasCheckmark = card.querySelector('svg circle[fill="var(--color-success)"]') !== null;
      const hasErrorIcon = card.querySelector('svg circle[fill="var(--color-error)"]') !== null;
      const hasQuestionMark = Array.from(card.querySelectorAll('svg text')).some(t => t.textContent === '?');
      return { title: title.substring(0, 20), hasClock, hasDash, hasSpinner, hasCheckmark, hasErrorIcon, hasQuestionMark };
    });
  });

  console.log('\nAfter completion:');
  for (const c of state) console.log(`  ${c.title}: clock=${c.hasClock} dash=${c.hasDash} spinner=${c.hasSpinner} check=${c.hasCheckmark} error=${c.hasErrorIcon} qmark=${c.hasQuestionMark}`);

  // After completion: NO ref should have clock, dash, or spinner
  for (const c of state) {
    expect(c.hasClock).toBe(false);
    expect(c.hasDash).toBe(false);
    expect(c.hasSpinner).toBe(false);
  }

  // Non-unverified refs must have their correct icon
  for (let i = 0; i < totalRefs - unverifiedCount; i++) {
    const expectedStatus = refResults[i].status;
    if (expectedStatus === 'verified') expect(state[i].hasCheckmark).toBe(true);
    if (expectedStatus === 'error') expect(state[i].hasErrorIcon).toBe(true);
  }
});
