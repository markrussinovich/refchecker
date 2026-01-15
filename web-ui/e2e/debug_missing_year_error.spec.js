// @ts-check
import { test, expect } from '@playwright/test';

/**
 * Quick test to verify the API returns missing year/venue as errors, not warnings.
 */
test.describe('Missing Year/Venue Error Display', () => {
  test('API should return missing year and venue as errors', async ({ page, request }) => {
    // Just test the API directly - get the latest history entry with Many-shot jailbreaking
    const historyResponse = await request.get('http://localhost:8000/api/history?limit=50');
    const history = await historyResponse.json();
    
    // Find a check with "Many-shot jailbreaking" reference
    let ref7Data = null;
    for (const check of history) {
      if (check.results_json) {
        const results = JSON.parse(check.results_json);
        const ref = results.find(r => r.title && r.title.includes('Many-shot jailbreaking'));
        if (ref) {
          ref7Data = ref;
          console.log('Found Many-shot jailbreaking reference:', JSON.stringify(ref, null, 2));
          break;
        }
      }
    }
    
    if (!ref7Data) {
      console.log('No Many-shot jailbreaking reference found in history');
      return;
    }
    
    // Check: status should be 'error', not 'warning'
    console.log(`Status: ${ref7Data.status}`);
    console.log(`Errors count: ${ref7Data.errors?.length || 0}`);
    console.log(`Warnings count: ${ref7Data.warnings?.length || 0}`);
    
    // Year missing and venue missing should be in errors, not warnings
    const yearInErrors = ref7Data.errors?.some(e => e.error_details?.includes('Year missing'));
    const venueInErrors = ref7Data.errors?.some(e => e.error_details?.includes('Venue missing'));
    const yearInWarnings = ref7Data.warnings?.some(e => e.error_details?.includes('Year missing'));
    const venueInWarnings = ref7Data.warnings?.some(e => e.error_details?.includes('Venue missing'));
    
    console.log(`Year missing in errors: ${yearInErrors}`);
    console.log(`Venue missing in errors: ${venueInErrors}`);
    console.log(`Year missing in warnings: ${yearInWarnings}`);
    console.log(`Venue missing in warnings: ${venueInWarnings}`);
    
    // Assertions
    expect(ref7Data.status).toBe('error');
    expect(yearInErrors).toBe(true);
    expect(venueInErrors).toBe(true);
    expect(yearInWarnings).toBeFalsy();
    expect(venueInWarnings).toBeFalsy();
  });
});
