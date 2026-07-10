const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', (err) => errors.push(String(err)));

  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  await page.waitForSelector('.skill-card', { timeout: 5000 });
  const cardTexts = await page.$$eval('.skill-card h3', (els) => els.map((e) => e.textContent.trim()));
  console.log('LIST_CARDS:', JSON.stringify(cardTexts));
  await page.screenshot({ path: 'e2e-list.png', fullPage: true });

  await page.click('.skill-card a');
  await page.waitForSelector('.install-box', { timeout: 5000 });
  const installCmd = await page.$eval('.install-row code', (e) => e.textContent.trim());
  console.log('INSTALL_CMD:', installCmd);
  const tabs = await page.$$eval('.tabs button', (els) => els.map((e) => ({ text: e.textContent, disabled: e.disabled })));
  console.log('TABS:', JSON.stringify(tabs));
  await page.screenshot({ path: 'e2e-detail.png', fullPage: true });

  console.log('CONSOLE_ERRORS:', JSON.stringify(errors));

  await browser.close();
})().catch((err) => {
  console.error('SCRIPT_FAILED:', err);
  process.exit(1);
});
