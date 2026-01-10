// @ts-check
import { test, expect } from '@playwright/test'

/**
 * Trace exactly what happens when updateHistoryProgress is called
 */
test.describe('Trace history update', () => {
  test('observe history item status changes', async ({ page }) => {
    // Capture ALL console logs
    page.on('console', msg => {
      const text = msg.text()
      // Filter to relevant logs
      if (text.includes('HistoryStore') || text.includes('updateHistoryProgress') || text.includes('completed')) {
        console.log(`[CONSOLE] ${text}`)
      }
    })

    await page.goto('http://localhost:5173')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1000)

    // Start first check
    console.log('\n========== STARTING FIRST CHECK ==========')
    const urlInput = page.locator('input[placeholder*="ArXiv"]')
    await urlInput.fill('2311.12022')  // GPQA paper - 36 refs
    
    const checkButton = page.locator('button:has-text("Check References")')
    await checkButton.click()

    // Wait for first check to start processing
    console.log('Waiting for first check to start...')
    await page.waitForTimeout(5000)

    // Check sidebar for first check's status
    const getHistoryItemStatuses = async () => {
      return page.evaluate(() => {
        const items = Array.from(document.querySelectorAll('[class*="cursor-pointer"]'))
        return items.slice(0, 5).map(item => ({
          text: item.textContent?.substring(0, 80),
          hasSpinner: !!item.querySelector('svg.animate-spin'),
        }))
      })
    }

    let statuses = await getHistoryItemStatuses()
    console.log('History items after first check starts:', JSON.stringify(statuses, null, 2))

    // Start second check
    console.log('\n========== STARTING SECOND CHECK ==========')
    const newRefcheckButton = page.locator('button[title="Create new refcheck"]')
    await newRefcheckButton.click()
    await page.waitForTimeout(500)

    await urlInput.fill('2310.02238')  // Another paper
    await checkButton.click()

    console.log('Second check started, waiting...')
    await page.waitForTimeout(2000)

    statuses = await getHistoryItemStatuses()
    console.log('History items after second check starts:', JSON.stringify(statuses, null, 2))

    // Now wait and observe - the first check should complete and update
    console.log('\n========== OBSERVING UPDATES ==========')
    for (let i = 0; i < 20; i++) {
      await page.waitForTimeout(3000)
      
      statuses = await getHistoryItemStatuses()
      console.log(`[${(i+1) * 3}s] History items:`)
      statuses.forEach((s, idx) => {
        console.log(`  ${idx}: ${s.hasSpinner ? '🔄' : '✓'} ${s.text}`)
      })
      
      // Check if first check completed (GPQA with 36 refs)
      const gpqaItem = statuses.find(s => s.text?.includes('GPQA') || s.text?.includes('36 ref'))
      if (gpqaItem && !gpqaItem.hasSpinner) {
        console.log('\n✅ GPQA check completed and sidebar updated correctly!')
        break
      }
    }

    // Final check
    console.log('\n========== FINAL STATE ==========')
    statuses = await getHistoryItemStatuses()
    console.log('Final history items:', JSON.stringify(statuses, null, 2))
    
    // Check for the bug: if GPQA has spinner but says "36 refs" (not "Verifying"), it's the bug
    const gpqaItem = statuses.find(s => s.text?.includes('GPQA') || s.text?.includes('Graduate'))
    if (gpqaItem) {
      console.log('GPQA item:', gpqaItem)
      if (gpqaItem.hasSpinner && gpqaItem.text?.includes('refs') && !gpqaItem.text?.includes('Verifying')) {
        console.log('❌ BUG DETECTED: GPQA shows completed refs but still has spinner!')
      }
    }
  })
})
