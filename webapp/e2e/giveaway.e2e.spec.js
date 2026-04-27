const { expect, test } = require("@playwright/test");

test.describe("giveaway mini app", () => {
  test("uses clean mascot art on high-density screens and has motion", async ({ browser }) => {
    const context = await browser.newContext({
      viewport: { width: 430, height: 932 },
      deviceScaleFactor: 2,
      reducedMotion: "no-preference",
    });
    const page = await context.newPage();
    await page.route("https://telegram.org/js/telegram-web-app.js", route =>
      route.fulfill({
        status: 200,
        contentType: "application/javascript",
        body: `
          window.Telegram = {
            WebApp: {
              initData: "user=fake",
              initDataUnsafe: { start_param: "giveaway_1" },
              ready() {},
              expand() {},
              close() {},
              openTelegramLink(url) { window.__opened = url; }
            }
          };
        `,
      }),
    );
    await page.route("**/api/giveaway/status?**", route =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          status: "active",
          is_active: true,
          joined: true,
          is_allowed: true,
          required_channels: [],
          missing_channels: [],
        }),
      }),
    );

    await page.goto("/giveaway.html?giveaway_id=1");

    await expect(page.locator("#title")).toHaveText("Вы уже участвуете");
    await expect(page.locator("#mascot")).toHaveJSProperty("complete", true);
    await expect(page.locator("#mascot")).toHaveJSProperty("naturalWidth", 1254);
    await expect.poll(() => page.locator("#mascot").evaluate(img => img.currentSrc)).toMatch(/giveaway-success-clean\.webp$/);
    await expect(page.locator(".mascot")).not.toHaveCSS("animation-name", "none");
    await expect(page.locator("#mascot")).not.toHaveCSS("animation-name", "none");

    await context.close();
  });
});
