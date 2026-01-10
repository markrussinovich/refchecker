// @ts-check
import { test, expect } from '@playwright/test'

/**
 * Test that the first check continues getting updates when a second check is started
 */
test.describe('Dual check session routing', () => {
  test('first check maintains progress when second check starts', async ({ page }) => {
    // Enable console logging for debugging
    const logs = []
    page.on('console', msg => {
      const text = msg.text()
      logs.push(text)
      if (text.includes('stale session') || text.includes('Applying completed')) {
        console.log(`[BROWSER] ${text}`)
      }
    })

    await page.goto('http://localhost:5173')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1000)

    // Start first check
    console.log('=== Starting first check ===')
    const urlInput = page.locator('input[placeholder*="ArXiv"]')
    await urlInput.fill('2310.02238')
    
    const checkButton = page.locator('button:has-text("Check References")')
    await checkButton.click()

    // Wait for check to start and extract the session/check IDs
    await page.waitForTimeout(3000)

    const firstState = await page.evaluate(() => {
      // Access Zustand stores directly
      const checkStore = window.__zustand_stores?.useCheckStore?.getState?.() || {}
      const historyStore = window.__zustand_stores?.useHistoryStore?.getState?.() || {}
      return {
        sessionId: checkStore.sessionId,
        currentCheckId: checkStore.currentCheckId,
        sessionToCheckMap: checkStore.sessionToCheckMap,
        status: checkStore.status,
      }
    })
    console.log('First check state:', JSON.stringify(firstState, null, 2))

    // Store first check's info
    const firstSessionId = firstState.sessionId
    const firstCheckId = firstState.currentCheckId

    // Click "New Refcheck" button to start second check
    console.log('=== Starting second check ===')
    
    // Look for the New Refcheck button in sidebar or header
    const newRefcheckBtn = page.locator('button, div').filter({ hasText: /NEW REFCHECK/i }).first()
    if (await newRefcheckBtn.isVisible()) {
      await newRefcheckBtn.click()
      await page.waitForTimeout(500)
    }

    // Start second check with different paper
    await urlInput.fill('2311.12022')
    await checkButton.click()

    // Wait for second check to start
    await page.waitForTimeout(2000)

    const secondState = await page.evaluate(() => {
      const checkStore = window.__zustand_stores?.useCheckStore?.getState?.() || {}
      return {
        sessionId: checkStore.sessionId,
        currentCheckId: checkStore.currentCheckId,
        sessionToCheckMap: checkStore.sessionToCheckMap,
        status: checkStore.status,
      }
    })
    console.log('Second check state:', JSON.stringify(secondState, null, 2))

    // Verify the session changed
    expect(secondState.sessionId).not.toBe(firstSessionId)
    expect(secondState.currentCheckId).not.toBe(firstCheckId)

    // Verify the session map contains both
    console.log('Session to check map:', JSON.stringify(secondState.sessionToCheckMap, null, 2))

    // Wait for first check to complete and observe updates
    console.log('=== Waiting for first check to complete ===')
    
    // Wait up to 60 seconds for the first check to complete in history
    let firstCheckCompleted = false
    for (let i = 0; i < 30; i++) {
      await page.waitForTimeout(2000)
      
      const historyState = await page.evaluate((checkId) => {
        const historyStore = window.__zustand_stores?.useHistoryStore?.getState?.() || {}
        const item = historyStore.history?.find(h => h.id === checkId)
        return {
          checkId,
          status: item?.status,
          total_refs: item?.total_refs,
          errors_count: item?.errors_count,
        }
      }, firstCheckId)
      
      console.log(`[${(i+1)*2}s] First check (${firstCheckId}) history:`, JSON.stringify(historyState))
      
      if (historyState.status === 'completed') {
        firstCheckCompleted = true
        console.log('First check completed!')
        break
      }
    }

    // Verify first check completed
    expect(firstCheckCompleted).toBe(true)

    // Find logs about stale session handling
    const staleSessionLogs = logs.filter(l => l.includes('stale session') || l.includes('prior session'))
    console.log('Stale session logs:', staleSessionLogs.length)
    staleSessionLogs.forEach(l => console.log(l))
  })
})
