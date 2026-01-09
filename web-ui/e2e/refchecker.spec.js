import { test, expect } from '@playwright/test';

test.describe('RefChecker Web UI', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should load the homepage', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('RefChecker');
    // Check main panel is visible
    await expect(page.getByText('Check Paper References')).toBeVisible();
  });

  test('should show URL input by default', async ({ page }) => {
    const urlButton = page.getByRole('button', { name: 'URL / ArXiv ID' });
    await expect(urlButton).toBeVisible();

    const input = page.getByPlaceholder(/Enter ArXiv ID/i);
    await expect(input).toBeVisible();
  });

  test('should switch to file upload mode', async ({ page }) => {
    const fileButton = page.getByRole('button', { name: 'Upload File' });
    await fileButton.click();

    await expect(fileButton).toBeVisible();
    await expect(page.getByText(/Click to upload/i)).toBeVisible();
  });

  test('should disable submit button when URL is empty', async ({ page }) => {
    const submitButton = page.getByRole('button', { name: 'Check References' });
    // Button should be disabled when no URL entered
    await expect(submitButton).toBeDisabled();
  });

  test('should submit ArXiv ID and show processing state', async ({ page }) => {
    // Mock backend response
    await page.route('**/api/check', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: 'test-session-123',
          message: 'Check started'
        })
      });
    });

    // Enter ArXiv ID
    const input = page.getByPlaceholder(/Enter ArXiv ID/i);
    await input.fill('1706.03762');

    // Submit form
    const submitButton = page.getByRole('button', { name: 'Check References' });
    await submitButton.click();

    // Should show cancel button (indicating checking state)
    await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible();
  });

  test('should display history sidebar', async ({ page }) => {
    await expect(page.getByText('History')).toBeVisible();
  });

  test.skip('should load and display history items', async ({ page }) => {
    // This test requires backend to be running or proper API mocking
    // Mock history API response before navigation
    await page.route('**/api/history', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          history: [
            {
              id: 1,
              paper_title: 'Attention Is All You Need',
              paper_source: '1706.03762',
              timestamp: '2024-01-08T10:00:00',
              total_refs: 45,
              errors_count: 12,
              warnings_count: 8,
              unverified_count: 3
            }
          ]
        })
      });
    });

    await page.goto('/');

    // Wait for history to load
    await expect(page.getByText('Attention Is All You Need')).toBeVisible();
    // History items show "X refs" label
    await expect(page.getByText('45 refs')).toBeVisible();
  });

  test.skip('should click on history item and load details', async ({ page }) => {
    // This test requires backend to be running
    await page.route('**/api/history', async (route) => {
      const url = route.request().url();
      if (url.endsWith('/history/1')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 1,
            paper_title: 'Test Paper',
            paper_source: 'test.pdf',
            total_refs: 10,
            errors_count: 2,
            warnings_count: 1,
            unverified_count: 0,
            results: [
              {
                index: 1,
                title: 'Sample Reference',
                authors: ['Author One', 'Author Two'],
                year: '2020',
                status: 'verified',
                errors: [],
                warnings: [],
                authoritative_urls: [
                  { type: 'semantic_scholar', url: 'https://example.com' }
                ]
              }
            ]
          })
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            history: [
              {
                id: 1,
                paper_title: 'Test Paper',
                paper_source: 'test.pdf',
                timestamp: '2024-01-08T10:00:00',
                total_refs: 10,
                errors_count: 2,
                warnings_count: 1,
                unverified_count: 0
              }
            ]
          })
        });
      }
    });

    await page.goto('/');

    // Click on history item
    await page.getByText('Test Paper').click();

    // Should display results
    await expect(page.getByText('Sample Reference')).toBeVisible();
  });

  test.skip('should display summary panel with statistics', async ({ page }) => {
    // This test requires backend to be running
    await page.route('**/api/history**', async (route) => {
      if (route.request().url().includes('/1')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 1,
            paper_title: 'Test Paper',
            paper_source: 'test.pdf',
            total_refs: 100,
            errors_count: 15,
            warnings_count: 10,
            unverified_count: 5,
            results: []
          })
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            history: [
              {
                id: 1,
                paper_title: 'Test Paper',
                paper_source: 'test.pdf',
                timestamp: '2024-01-08T10:00:00',
                total_refs: 100,
                errors_count: 15,
                warnings_count: 10,
                unverified_count: 5
              }
            ]
          })
        });
      }
    });

    await page.goto('/');
    await page.getByText('Test Paper').click();

    // Check summary statistics - looking at stats cards
    await expect(page.locator('text=Total').first()).toBeVisible();
    await expect(page.locator('text=100').first()).toBeVisible();
  });

  test.skip('should display reference with errors', async ({ page }) => {
    // This test requires backend to be running
    await page.route('**/api/history**', async (route) => {
      if (route.request().url().includes('/1')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 1,
            paper_title: 'Test Paper',
            total_refs: 1,
            errors_count: 1,
            warnings_count: 0,
            unverified_count: 0,
            results: [
              {
                index: 1,
                title: 'Reference with Error',
                authors: ['Test Author'],
                year: '2020',
                status: 'error',
                errors: [
                  {
                    error_type: 'author',
                    error_details: 'First author mismatch',
                    cited_value: 'Test Author',
                    actual_value: 'Real Author'
                  }
                ],
                warnings: [],
                authoritative_urls: []
              }
            ]
          })
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ history: [
            {
              id: 1,
              paper_title: 'Test Paper',
              timestamp: '2024-01-08T10:00:00',
              total_refs: 1,
              errors_count: 1,
              warnings_count: 0,
              unverified_count: 0
            }
          ]})
        });
      }
    });

    await page.goto('/');
    await page.getByText('Test Paper').click();

    // Check that reference shows - detailed error checking depends on component structure
    await expect(page.getByText('Reference with Error')).toBeVisible();
  });

  test.skip('should display clickable authoritative URLs', async ({ page }) => {
    // This test requires backend to be running
    await page.route('**/api/history**', async (route) => {
      if (route.request().url().includes('/1')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 1,
            paper_title: 'Test Paper',
            total_refs: 1,
            errors_count: 0,
            warnings_count: 0,
            unverified_count: 0,
            results: [
              {
                index: 1,
                title: 'Reference with URLs',
                authors: ['Author'],
                year: '2020',
                status: 'verified',
                errors: [],
                warnings: [],
                authoritative_urls: [
                  { type: 'semantic_scholar', url: 'https://semanticscholar.org/paper/123' },
                  { type: 'arxiv', url: 'https://arxiv.org/abs/1234.5678' },
                  { type: 'doi', url: 'https://doi.org/10.1234/test' }
                ]
              }
            ]
          })
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ history: [
            {
              id: 1,
              paper_title: 'Test Paper',
              timestamp: '2024-01-08T10:00:00',
              total_refs: 1,
              errors_count: 0,
              warnings_count: 0,
              unverified_count: 0
            }
          ]})
        });
      }
    });

    await page.goto('/');
    await page.getByText('Test Paper').click();

    // Check that reference with URLs is visible
    await expect(page.getByText('Reference with URLs')).toBeVisible();
  });

  test.skip('should display history item and show action buttons on hover', async ({ page }) => {
    // This test requires backend to be running or proper API mocking
    await page.route('**/api/history', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          history: [
            {
              id: 1,
              paper_title: 'Test Paper',
              timestamp: '2024-01-08T10:00:00',
              total_refs: 10,
              errors_count: 2,
              warnings_count: 1,
              unverified_count: 0
            }
          ]
        })
      });
    });

    await page.goto('/');

    // History item should be visible
    const historyItem = page.getByText('Test Paper');
    await expect(historyItem).toBeVisible();

    // Hover to show action buttons
    await historyItem.hover();

    // Edit and delete buttons should be visible on hover
    await expect(page.getByTitle('Edit label')).toBeVisible();
    await expect(page.getByTitle('Delete')).toBeVisible();
  });
});
