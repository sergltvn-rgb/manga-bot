const { test, expect } = require("@playwright/test");

test("diagnose fab overlap", async ({ page }) => {
  await page.addInitScript(() => {
    const inject = () => {
      if (document.getElementById("__pw_no_motion")) return;
      const s = document.createElement("style");
      s.id = "__pw_no_motion";
      s.textContent = "*, *::before, *::after { transition: none !important; animation-duration: 0s !important; animation-delay: 0s !important; }";
      (document.head || document.documentElement).appendChild(s);
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", inject, { once: true });
    else inject();
  });
  await page.addInitScript(() => {
    window.Telegram = {
      WebApp: {
        expand: () => {}, ready: () => {}, close: () => {},
        openTelegramLink: () => {}, showConfirm: (_t, cb) => cb(true),
        HapticFeedback: { impactOccurred: () => {}, notificationOccurred: () => {} },
        initData: "x",
        initDataUnsafe: { user: { id: 6210312655, first_name: "Admin" } },
      },
    };
  });
  await page.route("https://telegram.org/js/telegram-web-app.js", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/javascript", body: "/*mock*/" });
  });
  await page.route("**/api/**", async (route) => {
    const u = new URL(route.request().url());
    if (u.pathname === "/api/reader") {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        body: JSON.stringify({
          bot_username: "x", admin_ids: [6210312655],
          series: [{ id: "manga_ru", title: "T", volumes: [{ volume: 1, chapters: [
            { chapter: "1", custom_name: "C1", text: "hello", url: "" },
            { chapter: "2", custom_name: "C2", text: "world", url: "" },
          ]}]}]
        })
      });
      return;
    }
    if (u.pathname === "/api/chapter-content") {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        body: JSON.stringify({ ok: true, source_type: "inline", html: "<p>Text of chapter.</p>", cache_status: "miss" })
      });
      return;
    }
    await route.fulfill({ status: 200, headers: { "content-type": "application/json", "access-control-allow-origin": "*" }, body: "{}" });
  });

  await page.goto("/reader.html?api=http://127.0.0.1:4173");
  await expect(page.locator("#series-list .series-card")).toHaveCount(1);
  await page.locator("#series-list .series-card").first().click();
  await page.locator("#chapters-list .chapter-item").first().click();
  await expect(page.locator("#screen-reader")).toHaveClass(/active/);
  // Verify no animation delays under reducedMotion.
  await page.evaluate(() => document.getElementById("next-chapter-btn").scrollIntoView({ block: "center", behavior: "instant" }));

  const prefs = await page.evaluate(() => ({
    reduceMatches: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    htmlOverflow: getComputedStyle(document.documentElement).overflow,
    bodyOverflow: getComputedStyle(document.body).overflow,
    screenTransition: getComputedStyle(document.getElementById("screen-reader")).transitionProperty,
  }));
  console.log("PREFS", JSON.stringify(prefs));

  const info = await page.evaluate(() => {
    const b = document.getElementById("next-chapter-btn").getBoundingClientRect();
    const fab = document.getElementById("fab-container").getBoundingClientRect();
    const bar = document.getElementById("reader-bottom-bar").getBoundingClientRect();
    const sr = document.getElementById("screen-reader").getBoundingClientRect();
    const body = document.body.getBoundingClientRect();
    const html = document.documentElement.getBoundingClientRect();
    const cx = b.left + b.width / 2, cy = b.top + b.height / 2;
    const top = document.elementFromPoint(cx, cy);
    const screens = [...document.querySelectorAll(".screen")].map(s => ({
      id: s.id,
      cls: s.className,
      rect: s.getBoundingClientRect(),
      transform: getComputedStyle(s).transform,
    }));
    return {
      viewport: { w: window.innerWidth, h: window.innerHeight },
      scroll: { x: window.scrollX, y: window.scrollY, docW: document.documentElement.scrollWidth },
      btn: b,
      fab,
      bar,
      screenReader: { rect: sr, transform: getComputedStyle(document.getElementById("screen-reader")).transform },
      body,
      html,
      screens,
      topAt: { cx, cy, id: top?.id, cls: top?.className, tag: top?.tagName },
    };
  });
  console.log("DIAG", JSON.stringify(info, null, 2));
});
