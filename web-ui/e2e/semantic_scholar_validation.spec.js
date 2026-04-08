import { test, expect } from '@playwright/test';

/**
 * Tests for Semantic Scholar API key validation in the Settings panel.
 * Uses a single catch-all API mock to ensure all requests are intercepted.
 *
 * The save flow: click Set → enter key → click Save → button shows '…' while
 * validating → on success editing closes and button becomes 'Edit';
 * on failure an error message appears below the input.
 */

const json = (route, status, body) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

function mockAllApi(page, overrides = {}) {
  return page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();

    if (path === '/api/auth/providers') return json(route, 200, { providers: [] });
    if (path === '/api/auth/me') return json(route, 401, {});
    if (path === '/api/llm-configs') return json(route, 200, []);
    if (path === '/api/health') return json(route, 200, { status: 'ok' });
    if (path === '/api/history') return json(route, 200, []);

    // SS validate endpoint — overridable
    if (path === '/api/settings/semantic-scholar/validate' && method === 'POST') {
      if (overrides.onValidate) return overrides.onValidate(route);
      return json(route, 200, { valid: true, message: 'API key is valid' });
    }

    if (path === '/api/settings/semantic-scholar') {
      if (method === 'GET') return json(route, 200, { has_key: false });
      if (method === 'PUT') return json(route, 200, { message: 'Saved', has_key: true });
      if (method === 'DELETE') return json(route, 200, { message: 'Deleted' });
    }

    if (path.startsWith('/api/settings')) return json(route, 200, {});
    return json(route, 404, { detail: 'Unhandled mock path', path });
  });
}

/** Navigate to Settings → API Keys */
async function openApiKeysPanel(page) {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  await page.locator('aside.sidebar-desktop').getByRole('button', { name: 'Settings' }).click();
  await page.waitForTimeout(300);
  await page.getByText('API Keys').click();
  await page.waitForTimeout(300);
}

test.describe('Semantic Scholar API Key Validation', () => {

  test('should show validation state when saving a key', async ({ page }) => {
    await mockAllApi(page, {
      onValidate: async (route) => {
        // 1.5s delay so the ellipsis state is observable
        await new Promise(resolve => setTimeout(resolve, 1500));
        return json(route, 200, { valid: true, message: 'API key is valid' });
      },
    });

    await openApiKeysPanel(page);

    // SS row should show "Set" (not "Edit") because mock returns has_key: false
    const setButton = page.locator('button:has-text("Set")').last();
    await expect(setButton).toBeVisible({ timeout: 5000 });
    await setButton.click();

    // Fill in the API key
    const input = page.locator('input[type="password"]').last();
    await expect(input).toBeVisible();
    await input.fill('test_api_key_12345');

    // Click Save — button text changes from "Save" to the ellipsis while validating
    const saveButton = page.locator('button:has-text("Save")').last();
    await expect(saveButton).toBeVisible();
    await saveButton.click();

    // The Save button should change to the ellipsis indicator
    await expect(page.locator('button').filter({ hasText: '\u2026' })).toBeVisible({ timeout: 3000 });

    // After validation + save complete, editing closes and SS shows "Edit"
    await expect(page.locator('button:has-text("Edit")')).toBeVisible({ timeout: 10000 });
  });

  test('should show error for invalid API key', async ({ page }) => {
    await mockAllApi(page, {
      onValidate: async (route) => {
        await new Promise(resolve => setTimeout(resolve, 500));
        return json(route, 400, { detail: 'Invalid API key' });
      },
    });

    await openApiKeysPanel(page);

    const setButton = page.locator('button:has-text("Set")').last();
    await expect(setButton).toBeVisible({ timeout: 5000 });
    await setButton.click();

    const input = page.locator('input[type="password"]').last();
    await expect(input).toBeVisible();
    await input.fill('invalid_key');

    const saveButton = page.locator('button:has-text("Save")').last();
    await saveButton.click();

    // Error message appears after validation fails
    await expect(page.getByText('Invalid API key')).toBeVisible({ timeout: 10000 });

    // Editing mode should remain open (input still visible)
    await expect(input).toBeVisible();
  });
});
