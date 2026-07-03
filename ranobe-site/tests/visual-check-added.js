const { chromium } = require('playwright');

const addedIds = [
  'our-party-nearly-wiped',
  'venus-mission',
  'azure-sword-distortions',
  'shanti',
  'four-child-life',
  'fluffy-cafe-world',
  'reborn-assassins-apprentice',
  'far-east-savior',
  'monster-i-love',
  'mmo-world-way-to-you',
  'flower-blooms-hill',
  'true-love-one-star',
  'thou-as-my-knight',
  'tough-necromancer',
  'new-game-plus-last-boss',
  'substitute-harvest-goddess',
  'petty-villain-rules',
  'old-knight-new-post',
  'clueless-fps-player',
  'kinki-region',
  'little-alchemist-spirits',
  'sowing-vengeance',
  'cats-and-books',
  'repeated-vice',
  'beautiful-daydream',
  'bone-ash',
  'lila-winds-war',
  'miss-blossom-standards',
  'dragon-blade-saint',
  'bs-situation-tougetsu',
  'kept-man-princess-knight',
  'dark-elf-middle-aged',
  'zilbagias-demon-prince',
  'hero-killing-bride',
  'girl-wants-hero',
  'tiny-witch-deep-woods',
  'moon-blossom-asura',
];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });

  await page.goto('http://127.0.0.1:5500', { waitUntil: 'networkidle', timeout: 60000 });
  for (const id of addedIds) {
    await page.locator(`[data-id="${id}"]`).scrollIntoViewIfNeeded();
    await page.waitForTimeout(35);
  }
  await page.waitForLoadState('networkidle');
  await page.screenshot({
    path: 'C:/bot – копія/ranobe-site/output/playwright/catalog-verified-jnovels.png',
    fullPage: false,
  });

  const result = await page.evaluate((ids) => {
    const missing = ids.filter((id) => !document.querySelector(`[data-id="${id}"]`));
    const noImg = ids.filter((id) => {
      const img = document.querySelector(`[data-id="${id}"] img.cover-img`);
      return !img || !img.complete || img.naturalWidth === 0;
    });
    return {
      count: document.querySelectorAll('.card').length,
      kpi: document.querySelector('#kpi-titles')?.textContent,
      missing,
      noImg,
    };
  }, addedIds);

  await browser.close();

  if (errors.length || result.missing.length || result.noImg.length) {
    console.error(JSON.stringify({ errors, ...result }, null, 2));
    process.exit(1);
  }

  console.log(JSON.stringify(result));
})();
