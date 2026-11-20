const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

exports.launchBrowser = () => chromium.launch({
  headless: true,
  ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {}),
  ...(process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {}),
});
