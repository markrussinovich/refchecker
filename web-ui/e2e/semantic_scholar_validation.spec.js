import { test, expect } from '@playwright/test';

/**
 * Tests for Semantic Scholar API key validation
 */

test.describe('Semantic Scholar API Key Validation', () => {
  
  test('should show validation state when saving a key', async ({ page }) => {
    // Mock the API endpoints
    await page.route('**/api/llm-configs', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([])
    }));
    
    await page.route('**/api/settings/semantic-scholar', route => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ has_key: false })
        });
      }
      if (route.request().method() === 'PUT') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ message: 'Saved', has_key: true })
        });
      }
      return route.continue();
    });
    
    await page.route('**/api/health', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok' })
    }));
    
    await page.route('**/api/history', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([])
    }));
    
    // Mock validation endpoint with a delay to see the "Validating..." state
    await page.route('**/api/settings/semantic-scholar/validate', async route => {
      // Add a delay to make the validating state visible
      await new Promise(resolve => setTimeout(resolve, 1000));
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ valid: true, message: 'API key is valid' })
      });
    });

    // Navigate to the app
    await page.goto('/');
    
    // Wait for the page to load
    await page.waitForLoadState('networkidle');
    
    // Find and click the "Add" button for Semantic Scholar
    const addButton = page.locator('text=Add').first();
    await expect(addButton).toBeVisible({ timeout: 10000 });
    await addButton.click();
    
    // Enter a test API key
    const input = page.locator('input[type="password"]');
    await expect(input).toBeVisible();
    await input.fill('test_api_key_12345');
    
    // Click Save and check for Validating state
    const saveButton = page.locator('button:has-text("Save")');
    await expect(saveButton).toBeVisible();
    await saveButton.click();
    
    // Should show "Validating..." text
    await expect(page.locator('button:has-text("Validating...")')).toBeVisible({ timeout: 5000 });
    
    // Wait for it to complete
    await expect(page.locator('text=✓ Set')).toBeVisible({ timeout: 10000 });
  });

  test('should show error for invalid API key', async ({ page }) => {
    // Mock the API endpoints
    await page.route('**/api/llm-configs', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([])
    }));
    
    await page.route('**/api/settings/semantic-scholar', route => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ has_key: false })
        });
      }
      return route.continue();
    });
    
    await page.route('**/api/health', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok' })
    }));
    
    await page.route('**/api/history', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([])
    }));
    
    // Mock validation endpoint to return invalid
    await page.route('**/api/settings/semantic-scholar/validate', async route => {
      await new Promise(resolve => setTimeout(resolve, 500));
      return route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Invalid API key' })
      });
    });

    // Navigate to the app
    await page.goto('/');
    
    // Wait for the page to load
    await page.waitForLoadState('networkidle');
    
    // Find and click the "Add" button for Semantic Scholar
    const addButton = page.locator('text=Add').first();
    await expect(addButton).toBeVisible({ timeout: 10000 });
    await addButton.click();
    
    // Enter a test API key
    const input = page.locator('input[type="password"]');
    await expect(input).toBeVisible();
    await input.fill('invalid_key');
    
    // Click Save
    const saveButton = page.locator('button:has-text("Save")');
    await saveButton.click();
    
    // Should show "Validating..." first
    await expect(page.locator('button:has-text("Validating...")')).toBeVisible({ timeout: 5000 });
    
    // Then should show error message
    await expect(page.locator('text=Invalid API key')).toBeVisible({ timeout: 10000 });
  });
});
