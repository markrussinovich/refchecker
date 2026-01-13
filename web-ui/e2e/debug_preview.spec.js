// @ts-check
import { test, expect } from '@playwright/test'

test.describe('Debug Preview Overlay', () => {
  test('should show larger preview when clicking thumbnail', async ({ page }) => {
    // Go to the app
    await page.goto('http://localhost:5173')
    
    // Wait for app to load and history to appear
    await page.waitForTimeout(2000)
    
    // Wait specifically for history items to load - look for text containing 'Attention' or similar
    try {
      await page.waitForSelector('aside button:has-text("Attention"), aside button:has-text("GPQA"), aside button:has-text("Learning")', { timeout: 10000 })
      console.log('History items loaded')
    } catch (e) {
      console.log('Timeout waiting for history items, checking what loaded...')
    }
    
    // Take screenshot of initial state
    await page.screenshot({ path: 'test-results/debug-preview-01-initial.png', fullPage: true })
    
    // Find history items in the sidebar - look for any clickable items
    const sidebar = page.locator('aside').first()
    await sidebar.waitFor({ state: 'visible', timeout: 10000 })
    
    // Look for buttons/links in the sidebar that might be history items
    const historyButtons = sidebar.locator('button, a').filter({ hasText: /.+/ })
    const count = await historyButtons.count()
    console.log(`Found ${count} clickable items in sidebar`)
    
    // Log all items found
    for (let i = 0; i < Math.min(count, 5); i++) {
      const text = await historyButtons.nth(i).textContent()
      console.log(`  Item ${i}: ${text?.substring(0, 50)}...`)
    }
    
    // Find an item that looks like a paper
    const paperItem = sidebar.locator('button').filter({ hasText: /arxiv|Attention|Neural|Layer|Model/i }).first()
    const paperExists = await paperItem.count()
    console.log(`Found paper item: ${paperExists > 0}`)
    
    if (paperExists > 0) {
      await paperItem.click()
      console.log('Clicked on paper item')
      await page.waitForTimeout(2000)
      await page.screenshot({ path: 'test-results/debug-preview-02-selected.png', fullPage: true })
      
      // Look for thumbnail in the main content area
      const thumbnail = page.locator('img[alt="Paper thumbnail"]')
      const thumbExists = await thumbnail.count()
      console.log(`Found ${thumbExists} thumbnails`)
      
      if (thumbExists > 0) {
        const thumbSrc = await thumbnail.first().getAttribute('src')
        console.log(`Thumbnail src: ${thumbSrc}`)
        
        // Find the button wrapping the thumbnail
        const thumbButton = page.locator('button:has(img[alt="Paper thumbnail"])').first()
        const buttonExists = await thumbButton.count()
        console.log(`Found ${buttonExists} thumbnail buttons`)
        
        if (buttonExists > 0) {
          await thumbButton.click()
          console.log('Clicked thumbnail button')
          await page.waitForTimeout(1500)
          
          await page.screenshot({ path: 'test-results/debug-preview-03-after-click.png', fullPage: true })
          
          // Check for overlay with fixed positioning
          const overlay = page.locator('div.fixed.inset-0.z-50')
          const overlayExists = await overlay.count()
          console.log(`Found ${overlayExists} overlays with class 'fixed inset-0 z-50'`)
          
          if (overlayExists > 0) {
            const previewImg = overlay.locator('img').first()
            const previewSrc = await previewImg.getAttribute('src')
            console.log(`Preview src: ${previewSrc}`)
            
            // Verify it's using the preview endpoint, not thumbnail
            if (previewSrc?.includes('/api/preview/')) {
              console.log('✓ Preview is using correct /api/preview/ endpoint')
            } else if (previewSrc?.includes('/api/thumbnail/')) {
              console.log('✗ Preview is still using /api/thumbnail/ endpoint!')
            }
            
            const imgSize = await previewImg.boundingBox()
            console.log(`Preview image rendered size: ${imgSize?.width}x${imgSize?.height}`)
            
            await page.screenshot({ path: 'test-results/debug-preview-04-overlay.png', fullPage: true })
          } else {
            console.log('No overlay found - looking for any fixed divs')
            const fixedDivs = page.locator('div.fixed')
            const fixedCount = await fixedDivs.count()
            console.log(`Found ${fixedCount} fixed divs`)
          }
        } else {
          // Click thumbnail image directly
          console.log('Clicking thumbnail directly')
          await thumbnail.first().click()
          await page.waitForTimeout(1500)
          await page.screenshot({ path: 'test-results/debug-preview-03-direct-click.png', fullPage: true })
        }
      } else {
        console.log('No thumbnail found')
      }
    } else {
      console.log('No paper items found - trying first button in sidebar')
      if (count > 0) {
        await historyButtons.first().click()
        await page.waitForTimeout(2000)
        await page.screenshot({ path: 'test-results/debug-preview-02-fallback.png', fullPage: true })
      }
    }
  })
  
  test('check if preview endpoint works', async ({ page, request }) => {
    // Test the preview API directly
    const response = await request.get('http://localhost:8001/api/preview/11')
    console.log(`Preview API status: ${response.status()}`)
    console.log(`Preview API content-type: ${response.headers()['content-type']}`)
    
    if (response.status() === 200) {
      const buffer = await response.body()
      console.log(`Preview size: ${buffer.length} bytes`)
    } else {
      const text = await response.text()
      console.log(`Preview error: ${text}`)
    }
    
    // Also test thumbnail
    const thumbResponse = await request.get('http://localhost:8001/api/thumbnail/11')
    console.log(`Thumbnail API status: ${thumbResponse.status()}`)
    
    if (thumbResponse.status() === 200) {
      const buffer = await thumbResponse.body()
      console.log(`Thumbnail size: ${buffer.length} bytes`)
    }
  })
})
