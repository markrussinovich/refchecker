import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import path from 'path';

const BASE = 'http://localhost:8000';

// ---------------------------------------------------------------------------
// Helper: seed a test user and get a valid JWT token
// ---------------------------------------------------------------------------
function getTestUserToken() {
  const projectRoot = path.resolve(import.meta.dirname, '..', '..');
  const result = execSync('python web-ui/e2e/seed_test_user.py', {
    cwd: projectRoot,
    encoding: 'utf-8',
  });
  return JSON.parse(result.trim());
}

// ---------------------------------------------------------------------------
// Unauthenticated UX tests
// ---------------------------------------------------------------------------
test.describe('Login page UX (unauthenticated)', () => {

  test('shows a centered login card with logo, title, and subtitle', async ({ page }) => {
    await page.goto(BASE);
    await expect(page.getByRole('heading', { name: 'RefChecker' })).toBeVisible();
    await expect(page.getByText('Sign in to check paper references')).toBeVisible();
    // Logo SVG is present
    await expect(page.locator('svg').first()).toBeVisible();
  });

  test('shows only the GitHub sign-in button (only provider configured)', async ({ page }) => {
    await page.goto(BASE);
    const githubBtn = page.getByRole('button', { name: /Continue with GitHub/i });
    await expect(githubBtn).toBeVisible();
    // Google and Microsoft buttons should NOT be visible
    await expect(page.getByRole('button', { name: /Continue with Google/i })).not.toBeVisible();
    await expect(page.getByRole('button', { name: /Continue with Microsoft/i })).not.toBeVisible();
  });

  test('GitHub button contains the GitHub icon', async ({ page }) => {
    await page.goto(BASE);
    const githubBtn = page.getByRole('button', { name: /Continue with GitHub/i });
    await expect(githubBtn).toBeVisible();
    const icon = githubBtn.locator('svg');
    await expect(icon).toBeVisible();
  });

  test('clicking GitHub button navigates to OAuth login endpoint', async ({ page }) => {
    await page.goto(BASE);
    const githubBtn = page.getByRole('button', { name: /Continue with GitHub/i });
    await expect(githubBtn).toBeVisible();
    // Intercept the redirect response from the login endpoint
    const responsePromise = page.waitForResponse(
      resp => resp.url().includes('/api/auth/login/github'),
      { timeout: 10000 },
    );
    await githubBtn.click();
    const response = await responsePromise;
    // Server returns 307 redirect to GitHub
    expect(response.status()).toBe(307);
  });

  test('shows error banner when URL has auth_error param', async ({ page }) => {
    await page.goto(`${BASE}/?auth_error=access_denied`);
    await expect(page.getByText(/Login failed/i)).toBeVisible();
  });

  test('auth_error is removed from the URL after display', async ({ page }) => {
    await page.goto(`${BASE}/?auth_error=access_denied`);
    await expect(page.getByText(/Login failed/i)).toBeVisible();
    await page.waitForFunction(() => !window.location.search.includes('auth_error'));
    const url = new URL(page.url());
    expect(url.searchParams.has('auth_error')).toBeFalsy();
  });

  test('shows disclaimer text at the bottom of the card', async ({ page }) => {
    await page.goto(BASE);
    await expect(
      page.getByText('By signing in you agree to use this service for research purposes')
    ).toBeVisible();
  });

  test('clicking GitHub triggers redirect to GitHub OAuth', async ({ page }) => {
    await page.goto(BASE);
    const githubBtn = page.getByRole('button', { name: /Continue with GitHub/i });
    await expect(githubBtn).toBeVisible({ timeout: 10000 });
    const responsePromise = page.waitForResponse(
      resp => resp.url().includes('/api/auth/login/github'),
      { timeout: 10000 },
    );
    await githubBtn.click();
    const response = await responsePromise;
    expect(response.status()).toBe(307);
  });
});

// ---------------------------------------------------------------------------
// Authenticated UX tests — inject a valid JWT cookie
// ---------------------------------------------------------------------------
test.describe('Authenticated UX', () => {
  let token;

  test.beforeAll(() => {
    const result = getTestUserToken();
    token = result.token;
  });

  test.beforeEach(async ({ context }) => {
    await context.addCookies([{
      name: 'rc_auth',
      value: token,
      domain: 'localhost',
      path: '/',
      httpOnly: true,
      sameSite: 'Lax',
    }]);
  });

  test('authenticated user sees the main app, not the login page', async ({ page }) => {
    await page.goto(BASE);
    // Should NOT see the login page
    await expect(page.getByText('Sign in to check paper references')).not.toBeVisible();
    // Should see the main app header with RefChecker title
    await expect(page.locator('header').getByText('RefChecker')).toBeVisible();
  });

  test('header shows the user menu button', async ({ page }) => {
    await page.goto(BASE);
    const userMenuBtn = page.getByRole('button', { name: /user menu/i });
    await expect(userMenuBtn).toBeVisible();
  });

  test('user menu shows user info and sign-out button', async ({ page }) => {
    await page.goto(BASE);
    const userMenuBtn = page.getByRole('button', { name: /user menu/i });
    await userMenuBtn.click();
    // Should show user name and email
    await expect(page.getByText('Playwright Test User')).toBeVisible();
    await expect(page.getByText('playwright@test.local')).toBeVisible();
    // Provider badge
    await expect(page.getByText(/via github/i)).toBeVisible();
    // Sign out button
    await expect(page.getByRole('button', { name: /sign out/i })).toBeVisible();
  });

  test('clicking sign out returns to login page', async ({ page }) => {
    await page.goto(BASE);
    const userMenuBtn = page.getByRole('button', { name: /user menu/i });
    await userMenuBtn.click();
    const signOutBtn = page.getByRole('button', { name: /sign out/i });
    await signOutBtn.click();
    // Should be back on the login page
    await expect(page.getByText('Sign in to check paper references')).toBeVisible({ timeout: 5000 });
  });

  test('main app has a sidebar and header', async ({ page }) => {
    await page.goto(BASE);
    await expect(page.locator('header')).toBeVisible();
    const appContainer = page.locator('div.flex.h-screen');
    await expect(appContainer).toBeVisible();
  });

  test('header contains an LLM selector area', async ({ page }) => {
    await page.goto(BASE);
    const header = page.locator('header');
    await expect(header).toBeVisible();
    await expect(header.locator('.w-64')).toBeVisible();
  });

  test('header contains a GitHub repo link', async ({ page }) => {
    await page.goto(BASE);
    const githubLink = page.locator('header a[href*="github.com/markrussinovich/refchecker"]');
    await expect(githubLink).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// API auth enforcement tests
// ---------------------------------------------------------------------------
test.describe('API auth enforcement', () => {

  test('/api/auth/providers returns github', async ({ request }) => {
    const res = await request.get(`${BASE}/api/auth/providers`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.providers).toContain('github');
  });

  test('/api/auth/login/github redirects to GitHub OAuth URL', async ({ request }) => {
    const res = await request.get(`${BASE}/api/auth/login/github`, {
      maxRedirects: 0,
    });
    expect(res.status()).toBe(307);
    const location = res.headers()['location'];
    expect(location).toContain('github.com/login/oauth/authorize');
    expect(location).toContain('client_id=');
  });

  test('/api/auth/me returns 401 unauthenticated', async ({ request }) => {
    const res = await request.get(`${BASE}/api/auth/me`);
    expect(res.status()).toBe(401);
  });

  test('/api/check returns 401 unauthenticated', async ({ request }) => {
    const res = await request.post(`${BASE}/api/check`, {
      data: { paper_source: '1706.03762' },
    });
    expect(res.status()).toBe(401);
  });

  test('/api/history returns 401 unauthenticated', async ({ request }) => {
    const res = await request.get(`${BASE}/api/history`);
    expect(res.status()).toBe(401);
  });

  test('WebSocket rejects unauthenticated connection', async ({ page }) => {
    await page.goto(BASE);
    const result = await page.evaluate(async () => {
      return new Promise((resolve) => {
        const ws = new WebSocket(`ws://localhost:8000/api/ws/test-session`);
        ws.onclose = (e) => resolve({ closed: true, code: e.code });
        ws.onerror = () => resolve({ closed: true, code: 'error' });
        setTimeout(() => resolve({ closed: false, code: 'timeout' }), 5000);
      });
    });
    expect(result.closed).toBe(true);
  });

  test('OAuth callback with error redirects with auth_error', async ({ request }) => {
    const res = await request.get(`${BASE}/api/auth/callback/github?error=access_denied`, {
      maxRedirects: 0,
    });
    expect(res.status()).toBe(307);
    expect(res.headers()['location']).toContain('auth_error=access_denied');
  });

  test('OAuth callback with invalid state redirects with auth_error', async ({ request }) => {
    const res = await request.get(
      `${BASE}/api/auth/callback/github?code=fake&state=invalid`,
      { maxRedirects: 0 },
    );
    expect(res.status()).toBe(307);
    expect(res.headers()['location']).toContain('auth_error=');
  });

  test('logout endpoint clears the auth cookie', async ({ request }) => {
    const res = await request.post(`${BASE}/api/auth/logout`);
    expect(res.ok()).toBeTruthy();
    expect(res.headers()['set-cookie'] || '').toContain('rc_auth');
  });
});
