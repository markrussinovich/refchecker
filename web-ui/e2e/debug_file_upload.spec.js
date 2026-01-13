// @ts-check
import { test, expect } from '@playwright/test';

test.describe('Debug File Upload', () => {
  test('upload file and verify display', async ({ page }) => {
    // Navigate to app
    await page.goto('http://localhost:5173');
    await page.waitForLoadState('networkidle');
    
    // Wait for app to load
    await page.waitForTimeout(1000);
    
    // Click file upload tab
    await page.click('text=Upload File');
    await page.waitForTimeout(500);
    
    // Create a test .bbl file
    const testContent = `\\begin{thebibliography}{3}

\\bibitem{ref1}
John Smith and Jane Doe.
\\newblock A Test Paper Title.
\\newblock In \\emph{Proceedings of Test Conference}, pages 1--10, 2024.

\\bibitem{ref2}
Alice Johnson.
\\newblock Another Research Paper.
\\newblock \\emph{Journal of Testing}, 10(2):100--120, 2023.

\\bibitem{ref3}
Bob Williams and Carol Brown.
\\newblock Third Sample Reference.
\\newblock arXiv preprint arXiv:2401.12345, 2024.

\\end{thebibliography}`;

    // Upload file
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: 'test_bibliography.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from(testContent)
    });
    
    await page.waitForTimeout(500);
    
    // Take screenshot before submit
    await page.screenshot({ path: 'test-results/debug-01-before-submit.png', fullPage: true });
    
    // Submit the check
    const submitButton = page.locator('button:has-text("Check References")');
    await expect(submitButton).toBeEnabled();
    await submitButton.click();
    
    // Wait for check to start
    await page.waitForTimeout(2000);
    
    // Take screenshot during progress
    await page.screenshot({ path: 'test-results/debug-02-in-progress.png', fullPage: true });
    
    // Check the status section
    const statusSection = page.locator('[class*="rounded-lg"]').first();
    
    // Log what we see
    console.log('=== Status Section Content ===');
    const statusText = await statusSection.textContent();
    console.log('Status text:', statusText);
    
    // Check for title display
    const titleElement = page.locator('h3').first();
    const titleText = await titleElement.textContent();
    console.log('Title:', titleText);
    
    // Check what the stores contain
    const storeState = await page.evaluate(() => {
      // Try to access stores via React dev tools or window
      try {
        // These might be exposed for debugging
        return 'Cannot access stores directly from page';
      } catch (e) {
        return e.message;
      }
    });
    console.log('Store access attempt:', storeState);
    
    // Check for source line
    const sourceLinks = page.locator('a:has-text("Uploaded file")');
    const sourceCount = await sourceLinks.count();
    console.log('Source links found:', sourceCount);
    
    // Check for thumbnail
    const thumbnails = page.locator('img[alt="Paper thumbnail"]');
    const thumbnailCount = await thumbnails.count();
    console.log('Thumbnails found:', thumbnailCount);
    
    if (thumbnailCount > 0) {
      const thumbnailSrc = await thumbnails.first().getAttribute('src');
      console.log('Thumbnail src:', thumbnailSrc);
      
      // Check if thumbnail loaded
      const isVisible = await thumbnails.first().isVisible();
      console.log('Thumbnail visible:', isVisible);
    }
    
    // Wait for check to complete (up to 60 seconds)
    await page.waitForSelector('text=Check completed', { timeout: 60000 }).catch(() => {
      console.log('Check did not complete in time');
    });
    
    // Take screenshot after completion
    await page.screenshot({ path: 'test-results/debug-03-completed.png', fullPage: true });
    
    // Final checks
    console.log('\n=== Final State ===');
    
    // Check title again
    const finalTitle = await page.locator('h3').first().textContent();
    console.log('Final title:', finalTitle);
    
    // Check if it shows original filename
    await expect(page.locator('h3').first()).toContainText('test_bibliography.txt');
    
    // Check for Source: Uploaded file (clickable link)
    await expect(page.locator('text=Source:')).toBeVisible();
    await expect(page.locator('a:has-text("Uploaded file")')).toBeVisible();
    
    // Check thumbnail is visible
    const finalThumbnails = page.locator('img[alt="Paper thumbnail"]');
    await expect(finalThumbnails.first()).toBeVisible();
    
    // Check the history sidebar
    console.log('\n=== History Sidebar ===');
    const historyItems = page.locator('[class*="HistoryItem"]');
    const historyCount = await historyItems.count();
    console.log('History items:', historyCount);
    
    // Take final screenshot
    await page.screenshot({ path: 'test-results/debug-04-final.png', fullPage: true });
  });
});
