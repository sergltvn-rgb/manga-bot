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
    let rerollCalls = 0;
    let publishCalls = 0;
    const fulfillGiveaways = route =>
      route.fulfill({
        json: {
          ok: true,
          active: [{ id: 7, status: "review_pending", post_text: "VIP launch", prize: "VIP", participants: 12, winners_count: 1, ends_at: "02.05.2026 20:00", monitor: { suspicious: 3, watch: 4, removed: 1, new_1m: 2 } }],
          recent: [],
          total: 1,
          status_counts: { active: 1, review_pending: 1, scheduled: 0, finished: 0, cancelled: 0, all: 1 },
        },
      });
    await page.route("**/api/admin/giveaways", fulfillGiveaways);
    await page.route("**/api/admin/giveaways?**", fulfillGiveaways);
    await page.route("**/api/admin/giveaways/7/participants?**", route =>
      route.fulfill({
        json: {
          ok: true,
          giveaway_id: 7,
          status: "review_pending",
          filter: "all",
          counters: { total: 12, suspicious: 3, watch: 4, removed: 1, winners: 1, new_1m: 2, new_5m: 5, new_15m: 9, active_now: 4 },
          referrals: [{ source: "promoA", participants: 8, suspicious: 3, watch: 4 }],
          timeline: [{ bucket: "12:00", count: 6 }],
          winners: [{
            user_id: 1002,
            first_name: "Warm User",
            username: "warmuser",
            display_name: "Warm User",
            status: "joined",
            is_winner: true,
            winner_place: 1,
            risk_score: 45,
          }],
          participants: [{
            user_id: 1001,
            first_name: "Fast User",
            username: "fastuser",
            joined_at: "2026-05-01T12:00:04+00:00",
            referral_source: "promoA",
            language_code: "ar",
            is_premium: "0",
            status: "joined",
            risk_score: 35,
            risk_level: "watch",
            risk_label: "Низкий",
            risk_flags: [{ code: "time_burst", label: "Всплеск регистраций", reason: "16 регистраций в одну минуту.", weight: 20 }],
            activity: { actions: 0, telemetry_available: false, label: "активность не собиралась" },
          }, {
            user_id: 1002,
            first_name: "Warm User",
            username: "warmuser",
            joined_at: "2026-05-01T12:09:28.291902+00:00",
            joined_at_label: "01.05.2026 15:09 МСК",
            referral_source: "",
            referral_label: "прямой вход",
            language_code: "ru",
            language_label: "язык ru",
            is_premium: true,
            premium_label: "Premium да",
            status: "joined",
            is_winner: true,
            winner_place: 1,
            risk_score: 45,
            risk_level: "watch",
            risk_label: "Низкий",
            risk_flags: [
              { code: "fast_registration", label: "Слишком быстрое участие", reason: "Вступил через 6 сек. после первого открытия бота или WebApp.", weight: 30 },
              { code: "low_activity", label: "Мало активности", reason: "Видны только действия вокруг участия в конкурсе.", weight: 15 },
            ],
            activity: { actions: 2, telemetry_available: true, label: "2 действия" },
          }],
        },
      }),
    );
    await page.route("**/api/admin/giveaways/7/reroll", async route => {
      rerollCalls += 1;
      await route.fulfill({ json: { ok: true, giveaway_id: 7, result: { place: 1, old_user_id: 1002, new_user_id: 1003 }, history: [] } });
    });
    await page.route("**/api/admin/giveaways/7/publish-results", async route => {
      publishCalls += 1;
      await route.fulfill({ json: { ok: true, giveaway_id: 7, status: "finished" } });
    });

    await page.goto("/admin.html");
    await page.locator("nav").getByRole("button", { name: /Розыгрыши/ }).click();
    await page.getByRole("button", { name: /Подробности|Карточка/ }).first().click();

    await expect(page.locator("#giveawayStatus")).toContainText("Подозрительных");
    await expect(page.locator("#participantFilter")).toBeVisible();
    await expect(page.locator("#participantRows")).toContainText("Fast User");
    await expect(page.locator("#participantRows")).toContainText("35");
    await expect(page.locator("#participantRows")).toContainText("Premium нет");
    await expect(page.locator("#winnerReviewPanel")).toContainText("Проверка победителей");
    await expect(page.locator("#winnerReviewPanel")).toContainText("Warm User");
    await expect(page.locator("#winnerReviewPanel")).toContainText("Опубликовать итоги");
    await expect(page.locator("#winnerReviewPanel")).toContainText("Перевыбрать");
    await expect(page.locator("#participantRows")).toContainText("1 место");
    await expect(page.locator("#participantRows")).toContainText("01.05.2026 15:09 МСК");
    await expect(page.locator("#participantRows")).toContainText("прямой вход");
    await expect(page.locator("#participantRows")).toContainText("язык ru");
    await expect(page.locator("#participantRows")).toContainText("Premium да");
    await expect(page.locator("#participantRows")).toContainText("2 действия");
    await expect(page.locator("#participantRows")).toContainText("активность не собиралась");
    await expect(page.locator("#participantRows")).toContainText("Низкий");
    await expect(page.locator("#participantRows")).toContainText("Всплеск регистраций");
    await expect(page.locator("#participantRows")).toContainText("Слишком быстрое участие");
    await expect(page.locator("#participantRows")).toContainText("Мало активности");
    await expect(page.locator("#participantRows")).not.toContainText("time_burst");
    await expect(page.locator("#participantRows")).not.toContainText("fast_registration");
    await expect(page.locator("#participantRows")).not.toContainText("low_activity");
    await expect(page.locator("#participantRows")).not.toContainText("Registered");
    await expect(page.locator("#participantRows")).not.toContainText("+00:00");
    await expect(page.locator("#participantRows")).not.toContainText(" actions");
    await expect(page.locator("#participantRows")).not.toContainText("direct");
    await expect(page.locator("#participantRows")).not.toContainText("lang ?");
    await expect(page.locator("[data-entry-action='exclude']").first()).toBeVisible();
    await expect(page.locator("[data-entry-action='trust']").first()).toBeVisible();

    page.once("dialog", dialog => dialog.accept("review"));
    await page.locator("#winnerReviewPanel [data-giveaway-reroll-place='1']").click();
    await expect.poll(() => rerollCalls).toBe(1);

    await page.locator("[data-giveaway-publish-results='7']").click();
    await page.getByRole("button", { name: "Опубликовать", exact: true }).click();
    await expect.poll(() => publishCalls).toBe(1);
  });
});
