const { expect, test } = require("@playwright/test");

test.describe("admin giveaway monitor", () => {
  test("renders live counters, risk flags, filters, and moderation controls", async ({ page }) => {
    await page.route("https://telegram.org/js/telegram-web-app.js", route =>
      route.fulfill({
        status: 200,
        contentType: "application/javascript",
        body: `
          window.Telegram = {
            WebApp: {
              initData: "user=fake",
              initDataUnsafe: { user: { id: 10, first_name: "Admin" } },
              ready() {},
              expand() {}
            }
          };
        `,
      }),
    );
    await page.route("**/api/admin/summary", route => route.fulfill({ json: { ok: true, counts: { giveaways_active: 1, giveaways_running: 1, webapp_errors: 0 } } }));
    await page.route("**/api/admin/health", route => route.fulfill({ json: { ok: true, health: { database: { ok: true }, git: { hash: "test" }, recent_errors: [] } } }));
    await page.route("**/api/reader", route => route.fulfill({ json: { ok: true, series: [] } }));
    await page.route("**/api/arts?limit=12", route => route.fulfill({ json: { ok: true, items: [] } }));
    await page.route("**/api/admin/audit?**", route => route.fulfill({ json: { ok: true, items: [], total: 0, offset: 0, limit: 20 } }));
    await page.route("**/api/admin/giveaways", route =>
      route.fulfill({
        json: {
          ok: true,
          active: [{ id: 7, status: "active", post_text: "VIP launch", prize: "VIP", participants: 12, winners_count: 1, ends_at: "02.05.2026 20:00", monitor: { suspicious: 3, removed: 1, new_1m: 2 } }],
          recent: [],
          total: 1,
          status_counts: { active: 1, scheduled: 0, finished: 0, cancelled: 0, all: 1 },
        },
      }),
    );
    await page.route("**/api/admin/giveaways/7/participants?**", route =>
      route.fulfill({
        json: {
          ok: true,
          giveaway_id: 7,
          filter: "all",
          counters: { total: 12, suspicious: 3, removed: 1, winners: 0, new_1m: 2, new_5m: 5, new_15m: 9, active_now: 4 },
          referrals: [{ source: "promoA", participants: 8, suspicious: 3 }],
          timeline: [{ bucket: "12:00", count: 6 }],
          participants: [{
            user_id: 1001,
            first_name: "Fast User",
            username: "fastuser",
            joined_at: "2026-05-01T12:00:04+00:00",
            referral_source: "promoA",
            language_code: "ar",
            is_premium: false,
            status: "joined",
            risk_score: 75,
            risk_flags: [{ code: "fast_registration", reason: "Registered 4s after first seen.", weight: 30 }],
          }],
        },
      }),
    );

    await page.goto("/admin.html");
    await page.locator("nav").getByRole("button", { name: /Розыгрыши/ }).click();
    await page.getByRole("button", { name: /Подробности|Карточка/ }).first().click();

    await expect(page.locator("#giveawayStatus")).toContainText("Подозрительных");
    await expect(page.locator("#participantFilter")).toBeVisible();
    await expect(page.locator("#participantRows")).toContainText("Fast User");
    await expect(page.locator("#participantRows")).toContainText("75");
    await expect(page.locator("#participantRows")).toContainText("fast_registration");
    await expect(page.locator("[data-entry-action='exclude']")).toBeVisible();
    await expect(page.locator("[data-entry-action='trust']")).toBeVisible();
  });
});
