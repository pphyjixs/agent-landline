// Execute the actual adapter-generated operation in an isolated Edge fixture.
const fs = require('node:fs');
const {createRequire} = require('node:module');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const req = createRequire(input.tools + '/package.json');
const {chromium} = req('playwright');
(async () => {
  const browser = await chromium.launch({executablePath:input.edge,headless:true});
  try {
    const context = await browser.newContext();
    await context.route('http://127.0.0.1:3080/**', route => route.fulfill({contentType:'text/html; charset=utf-8', body:input.html}));
    const page = await context.newPage();
    await page.goto('http://127.0.0.1:3080/');
    if (input.setup) await page.evaluate(input.setup);
    let result, error;
    try { result = await eval('(' + input.code + ')')(page); }
    catch (e) { error = e.message; }
    const clicks = await page.evaluate(() => window.clicks || 0);
    const draft = await page.locator('[data-composer-input]').textContent();
    process.stdout.write(JSON.stringify({result,error,clicks,draft}));
  } finally { await browser.close(); }
})().catch(error => { process.stderr.write(error.stack); process.exitCode=1; });
