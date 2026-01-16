// @ts-check
import { test, expect } from '@playwright/test';

test.describe('Debug File Upload', () => {
  test('upload file and verify display', async ({ page }) => {
    test.setTimeout(120000);
    await page.goto('http://localhost:5173');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    await page.click('text=Upload File');
    await page.waitForTimeout(500);

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

    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: 'test_bibliography.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from(testContent),
    });

    await page.waitForTimeout(500);
    await page.screenshot({ path: 'test-results/debug-01-before-submit.png', fullPage: true });

    const submitButton = page.locator('button:has-text("Check References")');
    await expect(submitButton).toBeEnabled();
    await submitButton.click();

    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'test-results/debug-02-in-progress.png', fullPage: true });

    const statusSection = page.locator('[class*="rounded-lg"]').first();

    console.log('=== Status Section Content ===');
    const statusText = await statusSection.textContent();
    console.log('Status text:', statusText);

    const titleElement = page.locator('h3').first();
    const titleText = await titleElement.textContent();
    console.log('Title:', titleText);

    const storeState = await page.evaluate(() => {
      try {
        return 'Cannot access stores directly from page';
      } catch (e) {
        return e.message;
      }
    });
    console.log('Store access attempt:', storeState);

    const sourceLinks = page.locator('a:has-text("Uploaded file")');
    const sourceCount = await sourceLinks.count();
    console.log('Source links found:', sourceCount);

    const thumbnails = page.locator('img[alt="Paper thumbnail"]');
    const thumbnailCount = await thumbnails.count();
    console.log('Thumbnails found:', thumbnailCount);

    if (thumbnailCount > 0) {
      const thumbnailSrc = await thumbnails.first().getAttribute('src');
      console.log('Thumbnail src:', thumbnailSrc);

      const isVisible = await thumbnails.first().isVisible();
      console.log('Thumbnail visible:', isVisible);
    }

    await page.waitForSelector('text=Check completed', { timeout: 60000 }).catch(() => {
      console.log('Check did not complete in time');
    });

    await page.screenshot({ path: 'test-results/debug-03-completed.png', fullPage: true });

    console.log('\n=== Final State ===');

    const finalTitle = await page.locator('h3').first().textContent();
    console.log('Final title:', finalTitle);

    await expect(page.locator('h3').first()).toContainText('test_bibliography.txt');
    await expect(page.locator('text=Source:')).toBeVisible();
    await expect(page.locator('a:has-text("Uploaded file")')).toBeVisible();

    const finalThumbnails = page.locator('img[alt="Paper thumbnail"]');
    await expect(finalThumbnails.first()).toBeVisible();

    console.log('\n=== History Sidebar ===');
    const historyItems = page.locator('[class*="HistoryItem"]');
    const historyCount = await historyItems.count();
    console.log('History items:', historyCount);

    await page.screenshot({ path: 'test-results/debug-04-final.png', fullPage: true });
  });
});
