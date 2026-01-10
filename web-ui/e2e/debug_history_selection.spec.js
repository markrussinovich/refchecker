// @ts-check
import { test, expect } from '@playwright/test';

test.describe('Debug History Selection During Active Check', () => {
  test('clicking history item should immediately switch view', async ({ page }) => {
    // Enable verbose console logging
    page.on('console', msg => {
      console.log(`[BROWSER ${msg.type().toUpperCase()}] ${msg.text()}`);
    });

    // Log all network requests
    page.on('request', request => {
      console.log(`[REQUEST] ${request.method()} ${request.url()}`);
    });

    page.on('response', response => {
      console.log(`[RESPONSE] ${response.status()} ${response.url()}`);
    });

    await page.goto('http://localhost:5173');
    await page.waitForLoadState('networkidle');
    
    console.log('=== Page loaded ===');

    // Wait for history to load
    await page.waitForTimeout(1000);

    // Check if there are any history items
    const historyItems = page.locator('[class*="cursor-pointer"]').filter({ hasText: /refs/ });
    const count = await historyItems.count();
    console.log(`=== Found ${count} history items ===`);

    if (count < 2) {
      console.log('Not enough history items to test. Need at least 2.');
      return;
    }

    // Click the "New refcheck" button or find input
    const newRefcheckBtn = page.locator('text=NEW REFCHECK').first();
    if (await newRefcheckBtn.isVisible()) {
      console.log('=== Clicking NEW REFCHECK ===');
      await newRefcheckBtn.click();
      await page.waitForTimeout(500);
    }

    // Find the input and start a check
    const input = page.locator('input[placeholder*="Enter"]').first();
    if (await input.isVisible()) {
      console.log('=== Entering URL ===');
      await input.fill('https://arxiv.org/abs/2311.12022');
      
      const checkBtn = page.locator('button:has-text("Check")').first();
      console.log('=== Starting check ===');
      await checkBtn.click();
      
      // Wait for check to start (should see "Checking..." status)
      await page.waitForTimeout(2000);
      console.log('=== Check should be running ===');
      
      // Now click on a history item (second one, not the current check)
      const secondHistoryItem = historyItems.nth(1);
      const itemText = await secondHistoryItem.textContent();
      console.log(`=== Clicking history item: ${itemText?.substring(0, 50)} ===`);
      
      const startTime = Date.now();
      await secondHistoryItem.click();
      
      // Wait and observe - the main panel should update
      console.log('=== Waiting for main panel to update ===');
      
      // Check what's visible in main panel every 200ms
      for (let i = 0; i < 50; i++) {
        await page.waitForTimeout(200);
        const elapsed = Date.now() - startTime;
        
        // Check for loading state
        const loadingDetails = await page.locator('text=Loading check details').isVisible();
        const completedText = await page.locator('text=Completed').isVisible();
        const hasRefs = await page.locator('[class*="border-l-4"]').count(); // Reference items have border-l-4
        
        console.log(`[${elapsed}ms] loadingDetails=${loadingDetails}, completed=${completedText}, refCount=${hasRefs}`);
        
        // If we see "Completed" text or references, we're done
        if (completedText && !loadingDetails) {
          console.log(`=== History item loaded after ${elapsed}ms ===`);
          expect(elapsed).toBeLessThan(2000); // Should load in under 2 seconds
          break;
        }
      }
    } else {
      console.log('Input not found');
    }
  });
});
