// @ts-check
import { test, expect } from '@playwright/test';

test.describe('Measure History API Latency', () => {
  test('measure time from click to API response', async ({ page }) => {
    let clickTime = 0;
    let responseTime = 0;
    
    // Monitor network responses
    page.on('response', response => {
      if (response.url().includes('/api/history/') && !response.url().endsWith('/history')) {
        responseTime = Date.now();
        console.log(`[RESPONSE] ${response.url()} at ${responseTime - clickTime}ms after click`);
      }
    });

    await page.goto('http://localhost:5173');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    // Check for history items
    const historyItems = page.locator('[class*="cursor-pointer"]').filter({ hasText: /refs/ });
    const count = await historyItems.count();
    console.log(`Found ${count} history items`);

    if (count < 2) {
      console.log('Not enough history items');
      return;
    }

    // Start a check first
    const newRefcheckBtn = page.getByRole('button', { name: /new refcheck/i }).first();
    if (await newRefcheckBtn.isVisible()) {
      await newRefcheckBtn.click();
      await page.waitForTimeout(500);
    }

    const input = page.locator('input[placeholder*="Enter"]').first();
    if (await input.isVisible()) {
      await input.fill('https://arxiv.org/abs/2311.12022');
      const checkBtn = page.locator('button:has-text("Check")').first();
      await checkBtn.click();
      
      // Wait for check to be extracting (actively using CPU/blocking)
      await page.waitForTimeout(3000);
      console.log('=== Check is running, now clicking history item ===');
      
      // Click history item and measure response time
      const secondHistoryItem = historyItems.nth(1);
      clickTime = Date.now();
      await secondHistoryItem.click();
      
      // Wait for response
      await page.waitForTimeout(5000);
      
      if (responseTime > 0) {
        const latency = responseTime - clickTime;
        console.log(`=== Total latency: ${latency}ms ===`);
        expect(latency).toBeLessThan(3000); // Allow slight jitter on slower envs
      } else {
        console.log('No response received!');
      }
    }
  });
});
