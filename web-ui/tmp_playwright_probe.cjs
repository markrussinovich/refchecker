const { chromium } = require('playwright');
(async() => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.on('console', msg => console.log('CONSOLE', msg.type(), msg.text()));
  page.on('pageerror', err => console.log('PAGEERROR', err.message));
  await page.goto('http://127.0.0.1:4173', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  await browser.close();
})();
