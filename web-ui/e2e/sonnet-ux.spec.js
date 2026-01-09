import { test, expect } from '@playwright/test';

test('sonnet 4.5 arxiv check - setup and run', async ({ page }) => {
  // Navigate to the app
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle' });
  
  // Wait for the page to be fully loaded
  await page.waitForTimeout(1000);
  
  // Click on the LLM dropdown (the button with No LLM configured or similar text)
  const dropdown = page.locator('button:has-text("LLM"), button:has-text("No LLM"), button:has-text("Loading"), button:has-text("anthropic"), button:has-text("openai")').first();
  await dropdown.click();
  
  // Click "Add LLM Configuration" button
  await page.click('button:has-text("Add LLM Configuration")');
  
  // Wait for modal to appear
  await page.waitForSelector('input#name', { timeout: 5000 });
  
  // Fill in the LLM configuration form
  await page.fill('input#name', 'Sonnet 4.5 Test');
  await page.selectOption('select#provider', 'anthropic');
  await page.fill('input#model', 'claude-sonnet-4-20250514');
  
  // Get API key from environment
  const apiKey = process.env.ANTHROPIC_API_KEY || '';
  if (!apiKey) {
    console.log('Warning: ANTHROPIC_API_KEY not set, test may fail');
  }
  await page.fill('input#api_key', apiKey);
  
  // Click "Add Configuration" button (not Save - that's for editing)
  await page.click('button:has-text("Add Configuration")');
  
  // Wait for modal to close and config to be saved (may take a few seconds for validation)
  await page.waitForSelector('input#name', { state: 'hidden', timeout: 30000 });
  
  // Wait a moment for the UI to update
  await page.waitForTimeout(500);
  
  // Switch to URL/ArXiv tab
  await page.click('button:has-text("URL"), button:has-text("ArXiv")');
  
  // Enter the ArXiv paper (Attention Is All You Need)
  await page.fill('input[placeholder*="ArXiv"], input[placeholder*="URL"]', '1706.03762');
  
  // Click Check References
  await page.click('button:has-text("Check References")');
  
  // Wait for results - look for reference items in the results (up to 5 minutes)
  // The paper has many references so it may take a while
  await page.waitForSelector('text=References', { timeout: 300000 });
  
  // Verify we see the verification results (format is [1/N])
  await expect(page.getByText(/\[\d+\/\d+\]/)).toBeVisible({ timeout: 300000 });
});
