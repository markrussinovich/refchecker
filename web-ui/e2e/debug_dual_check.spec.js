// @ts-check
import { test, expect } from '@playwright/test'

/**
 * Debug test to understand why first check loses updates when second check starts
 */
test.describe('Debug dual check issue', () => {
  test('start two checks and monitor state', async ({ page }) => {
    // Enable console logging
    page.on('console', msg => {
      const text = msg.text()
      if (text.includes('WebSocket') || text.includes('CheckStore') || text.includes('HistoryStore')) {
        console.log(`[BROWSER] ${text}`)
      }
    })

    await page.goto('http://localhost:5173')
    await page.waitForLoadState('networkidle')

    // Wait for initial load
    await page.waitForTimeout(1000)

    // Start first check
    console.log('\n=== STARTING FIRST CHECK ===')
    const urlInput = page.locator('input[placeholder*="ArXiv"]')
    await urlInput.fill('2310.02238')
    
    const checkButton = page.locator('button:has-text("Check References")')
    await checkButton.click()

    // Wait for first check to start
    await page.waitForTimeout(2000)

    // Get state after first check starts
    const state1 = await page.evaluate(() => {
      const checkStore = window.__ZUSTAND_DEVTOOLS__?.['useCheckStore'] || {}
      const historyStore = window.__ZUSTAND_DEVTOOLS__?.['useHistoryStore'] || {}
      return {
        check: {
          status: checkStore.status,
          sessionId: checkStore.sessionId,
          currentCheckId: checkStore.currentCheckId,
          sessionToCheckMap: checkStore.sessionToCheckMap,
        },
        history: historyStore.history?.slice(0, 3).map(h => ({
          id: h.id,
          status: h.status,
          title: h.paper_title?.substring(0, 30),
        })),
        selectedCheckId: historyStore.selectedCheckId,
      }
    })
    console.log('State after first check starts:', JSON.stringify(state1, null, 2))

    // Get first check's history item status
    const firstHistoryItem = page.locator('[class*="cursor-pointer"]').filter({ hasText: /Verifying|Extracting|refs/ }).first()
    const firstItemText1 = await firstHistoryItem.textContent().catch(() => 'not found')
    console.log('First history item text:', firstItemText1)

    // Wait a bit more for references to start extracting
    await page.waitForTimeout(3000)

    // Now start second check - click the + button next to "New refcheck" text
    console.log('\n=== STARTING SECOND CHECK ===')
    // The button has title "Create new refcheck" and is in the same container as "New refcheck" text
    const newRefcheckButton = page.locator('button[title="Create new refcheck"]')
    if (await newRefcheckButton.isVisible()) {
      console.log('Found New refcheck button, clicking it')
      await newRefcheckButton.click()
      await page.waitForTimeout(500)
    } else {
      console.log('New refcheck button not visible - might already be on input')
    }

    // Fill in second URL
    await urlInput.fill('2311.12022')
    await checkButton.click()

    // Wait for second check to start
    await page.waitForTimeout(2000)

    // Get state after second check starts
    const state2 = await page.evaluate(() => {
      const checkStore = window.__ZUSTAND_DEVTOOLS__?.['useCheckStore'] || {}
      const historyStore = window.__ZUSTAND_DEVTOOLS__?.['useHistoryStore'] || {}
      return {
        check: {
          status: checkStore.status,
          sessionId: checkStore.sessionId,
          currentCheckId: checkStore.currentCheckId,
          sessionToCheckMap: checkStore.sessionToCheckMap,
        },
        history: historyStore.history?.slice(0, 5).map(h => ({
          id: h.id,
          status: h.status,
          title: h.paper_title?.substring(0, 30),
        })),
        selectedCheckId: historyStore.selectedCheckId,
      }
    })
    console.log('State after second check starts:', JSON.stringify(state2, null, 2))

    // Check first history item status now
    const firstItemText2 = await firstHistoryItem.textContent().catch(() => 'not found')
    console.log('First history item text after second check starts:', firstItemText2)

    // Wait and observe
    console.log('\n=== WAITING TO OBSERVE UPDATES ===')
    for (let i = 0; i < 10; i++) {
      await page.waitForTimeout(2000)
      
      const historyItems = await page.evaluate(() => {
        const historyStore = window.__ZUSTAND_DEVTOOLS__?.['useHistoryStore'] || {}
        return historyStore.history?.slice(0, 5).map(h => ({
          id: h.id,
          status: h.status,
          total_refs: h.total_refs,
          title: h.paper_title?.substring(0, 20),
        }))
      })
      console.log(`[${i * 2}s] History:`, JSON.stringify(historyItems))
    }

    // Final state
    const finalState = await page.evaluate(() => {
      const checkStore = window.__ZUSTAND_DEVTOOLS__?.['useCheckStore'] || {}
      const historyStore = window.__ZUSTAND_DEVTOOLS__?.['useHistoryStore'] || {}
      return {
        check: {
          status: checkStore.status,
          sessionId: checkStore.sessionId,
          currentCheckId: checkStore.currentCheckId,
          sessionToCheckMap: checkStore.sessionToCheckMap,
        },
        history: historyStore.history?.slice(0, 5).map(h => ({
          id: h.id,
          status: h.status,
          total_refs: h.total_refs,
        })),
      }
    })
    console.log('\nFinal state:', JSON.stringify(finalState, null, 2))
  })
})
