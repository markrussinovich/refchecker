import { test, expect } from '@playwright/test';

// The author hover card must not (a) grow under the pointer after it opens, or
// (b) reserve blank space for sections it doesn't have. Those two pull against
// each other — pinning the height stops the growth but leaves a dead band on
// every author with no recent-work list — so the growth is instead headed off
// by fetching the profile partway through the hover delay, and the height is
// left to follow the content.
//
// jsdom has no layout, so only a real browser can tell whether the card
// actually grew or is actually padded out.

// Locally the bundled browser may not be downloaded; PW_CHANNEL=msedge (or
// chrome) runs the same test against an installed one.
if (process.env.PW_CHANNEL) test.use({ channel: process.env.PW_CHANNEL });

const SPARSE_ID = '81001';
const RICH_ID = '81002';

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

// The two profiles differ only in whether they have a recent-work list — that
// section is the whole reason a fixed height left a gap.
const PROFILES = {
  [SPARSE_ID]: {
    available: true, name: 'Sparse Author', affiliations: ['Institute of Nothing Much'],
    hIndex: 61, i10Index: 180, citationCount: 40000, paperCount: 643,
    orcid: '0000-0002-1825-0097', papers: [],
  },
  [RICH_ID]: {
    available: true, name: 'Rich Author', affiliations: ['University of Plenty'],
    hIndex: 30, i10Index: 44, citationCount: 9000, paperCount: 120,
    orcid: '0000-0001-5109-3700',
    papers: [
      { title: 'The First Of Several Recent Works', year: 2024 },
      { title: 'The Second Of Several Recent Works', year: 2023 },
      { title: 'The Third Of Several Recent Works', year: 2022 },
    ],
  },
};

async function setupApiMock(page, serverState) {
  await page.route('**/api/**', async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const json = (s, b) => route.fulfill({ status: s, contentType: 'application/json', body: JSON.stringify(b) });
    if (path === '/api/auth/providers') return json(200, { providers: [] });
    if (path === '/api/auth/me') return json(401, {});
    if (path === '/api/llm-configs') return json(200, []);
    if (path === '/api/settings/semantic-scholar') return json(200, { enabled: false });
    if (path === '/api/health') return json(200, { status: 'ok' });
    if (path === '/api/authors/profile') {
      const body = req.postDataJSON() || {};
      serverState.profileCalls.push(body.author_id);
      return json(200, PROFILES[body.author_id] || { available: false });
    }
    if (path === '/api/authors/find') return json(200, { available: false });
    if (path === '/api/check' && req.method() === 'POST') {
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

// One reference whose two authors are linked to the two profiles above.
async function runCheckWithAuthors(page, emit, sessionId, checkId) {
  await page.getByPlaceholder(/Enter ArXiv ID/i).fill('http://authors.example');
  await page.getByRole('button', { name: 'Check References' }).click();

  const authors = ['Sparse Author', 'Rich Author'];
  const enrichment = {
    authors: [
      { name: 'Sparse Author', s2_author_id: SPARSE_ID },
      { name: 'Rich Author', s2_author_id: RICH_ID },
    ],
  };
  await emit(sessionId, { type: 'references_extracted', references: [{ title: 'An Authored Reference', authors, year: 2024 }], total_refs: 1, count: 1, extraction_method: 'llm' });
  await emit(sessionId, {
    type: 'reference_result', index: 1, title: 'An Authored Reference', authors, year: 2024,
    status: 'verified', errors: [], warnings: [], suggestions: [], authoritative_urls: [], enrichment,
  });
  const counts = {
    total_refs: 1, processed_refs: 1, errors_count: 0, warnings_count: 0, suggestions_count: 0,
    unverified_count: 0, hallucination_count: 0, verified_count: 1,
    refs_with_errors: 0, refs_with_warnings_only: 0, refs_verified: 1, extraction_method: 'llm',
  };
  await emit(sessionId, { type: 'summary_update', ...counts });
  await emit(sessionId, { type: 'completed', check_id: checkId, ...counts });
  await expect(page.getByTitle('Export results')).toBeVisible();
}

async function openCard(page, name) {
  await page.getByRole('main').getByText(name, { exact: true }).first().hover();
  const card = page.getByRole('tooltip');
  await expect(card).toBeVisible();
  return card;
}

async function dismiss(page) {
  await page.mouse.move(5, 5);
  await expect(page.getByRole('tooltip')).toHaveCount(0);
}

test('the author card fits its content and does not grow after it opens', async ({ page }) => {
  const sessionId = 'sess-author-card';
  const checkId = 910;
  const serverState = {
    startQueue: [{ sessionId, checkId, paperTitle: 'Author Card Paper', paperSource: 'authors.pdf', totalRefs: 1 }],
    history: [], details: {}, profileCalls: [],
  };

  await setupApiMock(page, serverState);
  const emit = await setupWebSocketMock(page);
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.goto('/');
  await runCheckWithAuthors(page, emit, sessionId, checkId);

  // --- The author with no recent work ---
  let card = await openCard(page, 'Sparse Author');
  await expect(card.getByText(/0000-0002-1825-0097/)).toBeVisible();
  const sparseOnOpen = await card.boundingBox();
  await page.waitForTimeout(600);
  const sparseSettled = await card.boundingBox();

  // It arrived complete: nothing appeared late and pushed the card taller.
  expect(Math.abs(sparseSettled.height - sparseOnOpen.height), 'sparse card grew after opening').toBeLessThan(1);
  expect(Math.abs(sparseSettled.width - sparseOnOpen.width), 'sparse card widened after opening').toBeLessThan(1);

  // No dead band: no container inside the card is stretched taller than its
  // own content, i.e. nothing is padded out to fit a recent-work list this
  // author doesn't have. (Measuring only below the *last* element wouldn't
  // catch it — the footer is pinned to the bottom, so the gap pools above it.)
  const slack = await card.evaluate((el) => {
    let worst = 0;
    const scan = (n) => {
      const kids = Array.from(n.children).filter((c) => c.getBoundingClientRect().height > 0);
      if (!kids.length) return;
      const last = kids[kids.length - 1].getBoundingClientRect();
      worst = Math.max(worst, n.getBoundingClientRect().bottom - last.bottom);
      kids.forEach(scan);
    };
    scan(el);
    return worst;
  });
  expect(slack, 'blank space stretched into the card').toBeLessThan(24);
  await expect(card.getByText('Recent work', { exact: true })).toHaveCount(0);

  await dismiss(page);

  // --- The author who does have recent work ---
  card = await openCard(page, 'Rich Author');
  await expect(card.getByText('Recent work', { exact: true })).toBeVisible();
  const richOnOpen = await card.boundingBox();
  await page.waitForTimeout(600);
  const richSettled = await card.boundingBox();

  expect(Math.abs(richSettled.height - richOnOpen.height), 'rich card grew after opening').toBeLessThan(1);

  // Width is pinned — it's the dimension that made the card change shape from
  // author to author — while height genuinely follows the content.
  expect(Math.abs(richSettled.width - sparseSettled.width), 'cards are different widths').toBeLessThan(1);
  expect(richSettled.height, 'the card with three papers should be taller than the one with none')
    .toBeGreaterThan(sparseSettled.height + 30);

  // The card is a hover affordance, not a page: it must stay compact.
  expect(richSettled.height).toBeLessThan(400);
});
