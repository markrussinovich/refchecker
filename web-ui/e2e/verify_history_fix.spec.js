// @ts-check
import { test, expect } from '@playwright/test'

/**
 * Simpler test to verify history updates work correctly
 */
test.describe('Verify history updates', () => {
  test('first check updates sidebar correctly after second check starts', async ({ page }) => {
    // Capture console logs
    const logs = []
    page.on('console', msg => {
      const text = msg.text()
      if (text.includes('HistoryStore') && text.includes('updateHistoryProgress')) {
        logs.push(text)
        console.log(`[LOG] ${text}`)
      }
      if (text.includes('completed')) {
        console.log(`[COMPLETED] ${text}`)
      }
    })

    await page.goto('http://localhost:5173')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1000)

    // Start first check (GPQA - 36 refs, completes relatively quickly)
    console.log('\n=== STARTING FIRST CHECK (GPQA) ===')
    const urlInput = page.locator('input[placeholder*="ArXiv"]')
    await urlInput.fill('2311.12022')
    
    const checkButton = page.locator('button:has-text("Check References")')
    await checkButton.click()
    await page.waitForTimeout(3000)

    // Start second check
    console.log('\n=== STARTING SECOND CHECK (Harry Potter) ===')
    const newRefcheckButton = page.locator('button[title="Create new refcheck"]')
    await newRefcheckButton.click()
    await page.waitForTimeout(500)
    await urlInput.fill('2310.02238')
    await checkButton.click()
    await page.waitForTimeout(2000)

    // Get initial status of both checks in sidebar
    const getHistoryStatus = async (searchText) => {
      return page.evaluate((text) => {
        const items = Array.from(document.querySelectorAll('[class*="cursor-pointer"]'))
        const item = items.find(el => el.textContent?.includes(text))
        if (!item) return null
        return {
          text: item.textContent?.substring(0, 100),
          hasSpinner: !!item.querySelector('svg.animate-spin'),
        }
      }, searchText)
    }

    let gpqaStatus = await getHistoryStatus('GPQA')
    let harryStatus = await getHistoryStatus('Harry Potter')
    console.log('Initial GPQA status:', gpqaStatus)
    console.log('Initial Harry status:', harryStatus)

    // Wait for GPQA to complete (it should complete before Harry Potter)
    console.log('\n=== WAITING FOR GPQA TO COMPLETE ===')
    for (let i = 0; i < 30; i++) {
      await page.waitForTimeout(2000)
      
      gpqaStatus = await getHistoryStatus('GPQA')
      console.log(`[${(i+1)*2}s] GPQA: ${gpqaStatus?.hasSpinner ? '🔄 in-progress' : '✅ completed'} - ${gpqaStatus?.text?.substring(50, 100)}`)
      
      if (gpqaStatus && !gpqaStatus.hasSpinner) {
        console.log('\n✅ SUCCESS: GPQA sidebar shows completed!')
        
        // Verify it shows refs count not "Verifying..."
        if (gpqaStatus.text?.includes('refs') && !gpqaStatus.text?.includes('Verifying')) {
          console.log('✅ Shows completed refs count, not "Verifying..."')
        } else if (gpqaStatus.text?.includes('Verifying')) {
          console.log('❌ BUG: Still shows "Verifying..." text even though spinner is gone')
        }
        break
      }
    }

    // Final verification
    console.log('\n=== FINAL STATUS ===')
    gpqaStatus = await getHistoryStatus('GPQA')
    harryStatus = await getHistoryStatus('Harry Potter')
    console.log('GPQA:', gpqaStatus)
    console.log('Harry:', harryStatus)

    // Check for the specific bug condition
    if (gpqaStatus?.hasSpinner && gpqaStatus?.text?.includes('refs')) {
      console.log('❌ BUG DETECTED: GPQA has spinner but shows "refs" (not "Verifying")')
    }

    // Log all updateHistoryProgress calls for analysis
    console.log('\n=== updateHistoryProgress LOGS ===')
    logs.forEach(l => console.log(l))
  })
})
