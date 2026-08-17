import { test, expect } from '@playwright/test';

// The Summary card's Export button must not move when a filter is applied.
// A filter changes what's *listed*, not the shape of the header, so a button
// that jumps ~580px left and ~30px down is pure noise — and it lands away from
// wherever the pointer was about to click.
//
// The trigger is the width of the header's left-hand group: with the
// "Extracted: Regex/LLM | Halluc checked" chip present (the normal case for a
// real check) the row is close enough to full that adding the "Filtered: …"
// chip tips the control group onto a second line, where justify-between
// left-aligns it. So this measures real boxes in a real browser across a range
// of widths — jsdom has no layout and cannot see any of it.

// Locally the bundled browser may not be downloaded; PW_CHANNEL=msedge (or
// chrome) runs the same test against an installed one.
if (process.env.PW_CHANNEL) test.use({ channel: process.env.PW_CHANNEL });

async function setupWebSocketMock(page) {
  await page.addInitScript(() => {
    const connections = {};
    const __RealWebSocket = window.WebSocket;
    class MockWebSocket {
      constructor(url, protocols) {
        if (typeof url !== 'string' || url.indexOf('/api/ws/') === -1) return new __RealWebSocket(url, protocols);
        this.url = url; this.sessionId = url.split('/').pop(); this.readyState = 1;
        connections[this.sessionId] = this; setTimeout(() => this.onopen?.({}), 0);
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
    const path = new URL(route.request().url()).pathname;
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
    if (path.startsWith('/api/history/')) return json(200, serverState.details[Number(path.split('/').pop())] || {});
    if (path.startsWith('/api/cancel/')) return json(200, {});
    return json(404, {});
  });
}

// A completed check with a mix of statuses, so several filter chips are live,
// and with the per-stage extraction counts that make the header's left group
// wide enough to reproduce the wrap.
async function runCompletedCheck(page, emit, sessionId, checkId, totalRefs) {
  await page.getByPlaceholder(/Enter ArXiv ID/i).fill('http://anchored.example');
  await page.getByRole('button', { name: 'Check References' }).click();
  await expect(page.getByRole('main').getByRole('button', { name: 'Cancel' })).toBeVisible();

  const skeletons = Array.from({ length: totalRefs }, (_, i) => ({
    title: `A Reference With A Reasonably Long Title Number ${i + 1}`, authors: [], year: 2024,
  }));
  await emit(sessionId, { type: 'references_extracted', references: skeletons, total_refs: totalRefs, count: totalRefs, extraction_method: 'llm' });

  for (let i = 0; i < totalRefs; i++) {
    const bucket = i % 4;
    await emit(sessionId, {
      type: 'reference_result', index: i + 1, title: skeletons[i].title, authors: [], year: 2024,
      status: bucket === 1 ? 'error' : bucket === 2 ? 'warning' : bucket === 3 ? 'unverified' : 'verified',
      errors: bucket === 1 ? [{ error_type: 'title', error_details: 'Mismatch' }]
        : bucket === 3 ? [{ error_type: 'unverified', error_details: 'Not found' }] : [],
      warnings: bucket === 2 ? [{ error_type: 'year', error_details: 'Year off' }] : [],
      suggestions: [], authoritative_urls: [],
    });
  }
  const counts = {
    total_refs: totalRefs, processed_refs: totalRefs,
    errors_count: 3, warnings_count: 3, suggestions_count: 0, unverified_count: 3,
    hallucination_count: 0, verified_count: 3,
    refs_with_errors: 3, refs_with_warnings_only: 3, refs_verified: 3,
    extraction_method: 'llm', llm_count: totalRefs, regex_count: 0, hallucination_llm_count: 4,
    llm_tokens: 123456, llm_cost: 1.234,
  };
  await emit(sessionId, { type: 'summary_update', ...counts });
  await emit(sessionId, { type: 'completed', check_id: checkId, ...counts });

  // Export only enables once the check completes, and the enabled title is
  // what the assertions locate.
  await expect(page.getByTitle('Export results')).toBeVisible();
  // The wide per-stage chip must actually be on screen, or this test would
  // silently stop reproducing the condition.
  await expect(page.getByText(/Halluc checked/)).toBeVisible();
}

test('applying a filter never moves the Summary export button', async ({ page }) => {
  const sessionId = 'sess-export-anchor';
  const checkId = 900;
  const totalRefs = 12;
  const serverState = {
    startQueue: [{ sessionId, checkId, paperTitle: 'Export Anchor Paper', paperSource: 'anchored.pdf', totalRefs }],
    history: [], details: {},
  };

  await setupApiMock(page, serverState);
  const emit = await setupWebSocketMock(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/');
  await runCompletedCheck(page, emit, sessionId, checkId, totalRefs);

  const exportBtn = page.getByTitle('Export results');
  const refExport = page.getByTitle('Copy corrected reference').first();

  // Widths either side of where the header used to tip over. Before the fix
  // this jumped by up to ~580px horizontally and ~31px vertically.
  const moves = [];
  for (const width of [680, 820, 940, 1080, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(200);

    const before = await exportBtn.boundingBox();
    const refBefore = await refExport.boundingBox();

    await page.getByTitle(/references? with (an error|errors)/i).first().click();
    await expect(page.getByTitle(/clear all active filters/i)).toBeVisible();
    await page.waitForTimeout(200);

    const after = await exportBtn.boundingBox();
    const refAfter = await refExport.boundingBox();

    // Clearing it must put everything back too.
    await page.getByTitle(/clear all active filters/i).click();
    await page.waitForTimeout(200);
    const cleared = await exportBtn.boundingBox();

    moves.push({
      width,
      dx: after.x - before.x, dy: after.y - before.y,
      refdx: refAfter.x - refBefore.x,
      clearedDx: cleared.x - before.x, clearedDy: cleared.y - before.y,
    });
  }

  for (const m of moves) {
    // Sub-pixel rounding is tolerable; a visible jump is not.
    expect(Math.abs(m.dx), `x moved at ${m.width}px`).toBeLessThan(1);
    expect(Math.abs(m.dy), `y moved at ${m.width}px`).toBeLessThan(1);
    expect(Math.abs(m.refdx), `reference export x moved at ${m.width}px`).toBeLessThan(1);
    expect(Math.abs(m.clearedDx), `x moved after clearing at ${m.width}px`).toBeLessThan(1);
    expect(Math.abs(m.clearedDy), `y moved after clearing at ${m.width}px`).toBeLessThan(1);
  }
});

test('stacking several filters still does not move the export button', async ({ page }) => {
  const sessionId = 'sess-export-multi';
  const checkId = 901;
  const totalRefs = 12;
  const serverState = {
    startQueue: [{ sessionId, checkId, paperTitle: 'Multi Filter Paper', paperSource: 'multi.pdf', totalRefs }],
    history: [], details: {},
  };

  await setupApiMock(page, serverState);
  const emit = await setupWebSocketMock(page);
  await page.setViewportSize({ width: 1024, height: 900 });
  await page.goto('/');
  await runCompletedCheck(page, emit, sessionId, checkId, totalRefs);

  const exportBtn = page.getByTitle('Export results');
  const before = await exportBtn.boundingBox();

  // The longest the chip label realistically gets.
  await page.getByTitle(/references? with (an error|errors)/i).first().click();
  await page.getByTitle(/references? with (a warning|warnings) only/i).first().click();
  await page.getByTitle(/references? fully verified/i).first().click();
  await expect(page.getByTitle(/clear all active filters/i)).toBeVisible();
  await page.waitForTimeout(250);

  const after = await exportBtn.boundingBox();
  expect(Math.abs(after.x - before.x)).toBeLessThan(1);
  expect(Math.abs(after.y - before.y)).toBeLessThan(1);
});
