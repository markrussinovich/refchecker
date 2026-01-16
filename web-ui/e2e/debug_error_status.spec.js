import { test, expect } from '@playwright/test';

test.describe('Debug Error Status', () => {
  test('error status updates history sidebar', async ({ page }) => {
    page.on('console', msg => {
      const text = msg.text();
      if (text.includes('CheckStore') || text.includes('HistoryStore') || text.includes('error') || text.includes('Error')) {
        console.log('[Browser]', text.substring(0, 200));
      }
    });

    await page.goto('http://localhost:5173');
    await page.waitForSelector('text=Check Paper References', { timeout: 10000 });
    console.log('\n=== Starting Error Status Test ===');

    const badUrl = 'https://openreview.net/forum?id=INVALID_ID_12345';
    await page.fill('input[type="text"]', badUrl);
    await page.click('button:has-text("Check References")');

    console.log('Submitted bad URL, waiting for "Check failed" to appear in first history item...');

    let success = false;
    for (let i = 0; i < 30; i++) {
      await page.waitForTimeout(1000);
      const firstHistoryItemStats = page.locator('.flex.items-center.gap-1\\.5.mt-1.text-xs').first();
      const statsText = await firstHistoryItemStats.textContent();
      console.log(`[${i + 1}s] First history item stats: "${statsText}"`);

      if (statsText?.includes('Check failed')) {
        console.log('\nSUCCESS: First history item shows "Check failed"');
        success = true;
        break;
      } else if (statsText?.includes('Extracting')) {
        console.log(`[${i + 1}s] Still shows "Extracting..." - waiting...`);
      }
    }

    await page.screenshot({ path: 'test-results/error-final.png', fullPage: true });
    if (!success) {
      console.log('\nFAILED: First history item never showed "Check failed" - still shows "Extracting..."');
    }

    expect(success).toBe(true);
  });
});
