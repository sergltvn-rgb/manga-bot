const { test, expect } = require("@playwright/test");

const ADMIN_USER_ID = 6210312655;
const SOCIAL_SECTION_SCREENSHOT_OPTIONS = {
  animations: "disabled",
  caret: "hide",
  maxDiffPixels: 8,
};

function chapterKey(seriesId, volume, chapter) {
  return `${seriesId}_v${volume}_ch${chapter}`;
}

function daysAgoSql(days) {
  const date = new Date(Date.now() - (days * 24 * 60 * 60 * 1000));
  return date.toISOString().slice(0, 19).replace("T", " ");
}

function createVisualState() {
  const chapterOneKey = chapterKey("manga_ru", 1, "1");

  return {
    readerData: {
      bot_username: "AlyaTestBot",
      admin_ids: [ADMIN_USER_ID],
      series: [
        {
          id: "manga_ru",
          title: "Visual Test Series",
          volumes: [
            {
              volume: 1,
              chapters: [
                {
                  chapter: "1",
                  custom_name: "Chapter 1",
                  text: "Paragraph one for visual regression state checks.\n\nParagraph two with enough text to show reader hierarchy and controls.",
                  url: ""
                },
                {
                  chapter: "2",
                  custom_name: "Chapter 2",
                  text: "Second chapter for navigation state.",
                  url: ""
                }
              ]
            }
          ]
        }
      ]
    },
    commentsByChapter: {
      [chapterOneKey]: [
        {
          id: 1,
          chapter_key: chapterOneKey,
          user_id: "101",
          user_name: "ReaderOne",
          text: "Очень зашло, жду продолжение.",
          parent_id: null,
          likes: 3,
          user_reaction: "like",
          created_at: daysAgoSql(2)
        },
        {
          id: 2,
          chapter_key: chapterOneKey,
          user_id: "102",
          user_name: "Mika",
          text: "Согласна, ритм отличный.",
          parent_id: 1,
          likes: 1,
          user_reaction: null,
          created_at: daysAgoSql(2)
        }
      ]
    },
    chapterReactionsByChapter: {
      [chapterOneKey]: {
        like: 8,
        heart: 4,
        fire: 2,
        funny: 1
      }
    },
    userReactionByChapter: {
      [chapterOneKey]: "like"
    },
    likesByChapter: {
      [chapterOneKey]: {
        count: 12,
        liked: true
      }
    }
  };
}

function safeJson(request) {
  const body = request.postData();
  if (!body) return {};
  try {
    return JSON.parse(body);
  } catch {
    return {};
  }
}

function renderInlineChapterHtml(text) {
  return String(text || "")
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => `<p>${part}</p>`)
    .join("");
}

async function fulfillJson(route, payload, status = 200) {
  await route.fulfill({
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "access-control-allow-origin": "*"
    },
    body: JSON.stringify(payload)
  });
}

async function installVisualMocks(page, state) {
  await page.addInitScript(({ adminUserId }) => {
    window.Telegram = {
      WebApp: {
        expand: () => {},
        ready: () => {},
        close: () => {},
        openTelegramLink: () => {},
        showConfirm: (_text, cb) => cb(true),
        HapticFeedback: {
          impactOccurred: () => {},
          notificationOccurred: () => {}
        },
        initData: "mocked-init-data",
        initDataUnsafe: {
          user: {
            id: adminUserId,
            first_name: "Admin"
          }
        }
      }
    };
  }, { adminUserId: ADMIN_USER_ID });

  await page.route("https://telegram.org/js/telegram-web-app.js", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: "/* mocked telegram web app script */"
    });
  });
  await page.route("https://telegram.org/js/telegram-widget.js**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: "/* mocked telegram login widget */"
    });
  });

  await page.route("https://fonts.googleapis.com/**", (route) => route.abort());
  await page.route("https://fonts.gstatic.com/**", (route) => route.abort());

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method().toUpperCase();
    const pathname = url.pathname;

    if (method === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET,POST,PUT,DELETE,OPTIONS",
          "access-control-allow-headers": "Content-Type, Authorization"
        },
        body: ""
      });
      return;
    }

    if (pathname === "/api/reader" && method === "GET") {
      await fulfillJson(route, state.readerData);
      return;
    }

    if (pathname === "/api/chapter-content" && method === "GET") {
      const seriesId = url.searchParams.get("series_id") || "";
      const volumeId = url.searchParams.get("volume") || "";
      const chapterId = url.searchParams.get("chapter") || "";
      const series = state.readerData.series.find((item) => String(item.id) === String(seriesId));
      const volume = series?.volumes.find((item) => String(item.volume) === String(volumeId));
      const chapter = volume?.chapters.find((item) => String(item.chapter) === String(chapterId));
      if (!chapter) {
        await fulfillJson(route, { error: "not found" }, 404);
        return;
      }
      await fulfillJson(route, {
        ok: true,
        source_type: "inline",
        html: renderInlineChapterHtml(chapter.text || ""),
        fallback_url: chapter.url || null,
        cache_status: "miss",
      });
      return;
    }

    if (pathname === "/api/progress" && method === "GET") {
      await fulfillJson(route, { bookmarks: [] });
      return;
    }

    if (pathname === "/api/progress" && method === "POST") {
      await fulfillJson(route, { ok: true });
      return;
    }

    if (pathname === "/api/likes" && method === "GET") {
      const key = url.searchParams.get("chapter_key") || "";
      await fulfillJson(route, state.likesByChapter[key] || { count: 0, liked: false });
      return;
    }

    if (pathname === "/api/comments" && method === "GET") {
      const key = url.searchParams.get("chapter_key") || "";
      await fulfillJson(route, { comments: state.commentsByChapter[key] || [] });
      return;
    }

    if (pathname === "/api/comments" && method === "POST") {
      const body = safeJson(request);
      const key = String(body.chapter_key || "");
      const comments = state.commentsByChapter[key] || [];
      comments.unshift({
        id: Date.now(),
        chapter_key: key,
        user_id: String(ADMIN_USER_ID),
        user_name: "Admin",
        text: String(body.text || ""),
        parent_id: body.parent_id || null,
        likes: 0,
        user_reaction: null,
        created_at: "2026-04-21 12:00:00"
      });
      state.commentsByChapter[key] = comments;
      await fulfillJson(route, { ok: true });
      return;
    }

    if (pathname === "/api/comments/react" && method === "POST") {
      await fulfillJson(route, { ok: true });
      return;
    }

    if (pathname === "/api/comments/report" && method === "POST") {
      await fulfillJson(route, { ok: true });
      return;
    }

    if (pathname === "/api/reactions" && method === "GET") {
      const key = url.searchParams.get("chapter_key") || "";
      await fulfillJson(route, {
        reactions: state.chapterReactionsByChapter[key] || {},
        user_reaction: state.userReactionByChapter[key] || null
      });
      return;
    }

    if (pathname === "/api/reactions" && method === "POST") {
      await fulfillJson(route, { ok: true });
      return;
    }

    if (pathname === "/api/avatar" && method === "GET") {
      await route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": "*"
        },
        body: ""
      });
      return;
    }

    await fulfillJson(route, { ok: true });
  });
}

async function installPublicVisualMocks(page, state) {
  await installVisualMocks(page, state);
  await page.addInitScript(() => {
    delete window.Telegram;
  });
}

test.describe("Reader visual regression", () => {
  test.use({ viewport: { width: 393, height: 852 } });

  test("key states: series, chapters, reader top/bottom, settings, library filters", async ({ page }) => {
    const state = createVisualState();
    await installVisualMocks(page, state);

    const runtimeErrors = [];
    page.on("pageerror", (err) => runtimeErrors.push(`pageerror: ${err.message}`));

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/reader.html?api=http://127.0.0.1:4173");

    await expect(page.locator("#series-list .series-card")).toHaveCount(1);
    await expect(page.locator("#screen-series .content-area")).toHaveScreenshot("state-series-list-mobile.png", {
      animations: "disabled",
      caret: "hide"
    });

    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#screen-chapters")).toHaveClass(/active/);
    await expect(page.locator("#chapters-list .chapter-item")).toHaveCount(2);
    await expect(page.locator("#screen-chapters .content-area")).toHaveScreenshot("state-chapters-list-mobile.png", {
      animations: "disabled",
      caret: "hide"
    });

    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await expect(page.locator("#chapter-title-header")).toContainText("1");

    await expect(page.locator("#reader-top-bar")).toHaveScreenshot("state-reader-top-mobile.png", {
      animations: "disabled",
      caret: "hide"
    });

    await page.locator("#social-section").scrollIntoViewIfNeeded();
    await expect(page.locator("#social-section")).toBeVisible();
    await expect(page.locator("#social-section")).toHaveScreenshot(
      "state-reader-bottom-comments-mobile.png",
      SOCIAL_SECTION_SCREENSHOT_OPTIONS
    );

    await page.evaluate(() => {
      if (typeof toggleSettings === "function") {
        toggleSettings();
      }
    });
    await expect(page.locator("#settings-panel")).not.toHaveClass(/hidden/);
    await expect(page.locator("#settings-panel")).toHaveScreenshot("state-settings-mobile.png", {
      animations: "disabled",
      caret: "hide"
    });

    await page.evaluate(() => {
      if (typeof showScreen === "function") {
        showScreen("library");
      }
    });

    await expect(page.locator("#screen-library")).toHaveClass(/active/);
    await expect(page.locator("#library-filters")).toBeVisible();
    await expect(page.locator("#screen-library .content-area")).toHaveScreenshot("state-library-filters-mobile.png", {
      animations: "disabled",
      caret: "hide"
    });

    expect(runtimeErrors, `Runtime errors:\n${runtimeErrors.join("\n")}`).toEqual([]);
  });

  test("theme readability: reader comments in light/dark/sepia/gray/amoled", async ({ page }) => {
    const state = createVisualState();
    await installVisualMocks(page, state);

    const runtimeErrors = [];
    page.on("pageerror", (err) => runtimeErrors.push(`pageerror: ${err.message}`));

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/reader.html?api=http://127.0.0.1:4173");

    await expect(page.locator("#series-list .series-card")).toHaveCount(1);
    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#screen-chapters")).toHaveClass(/active/);

    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await expect(page.locator("#social-section")).toBeVisible();
    await page.locator("#social-section").scrollIntoViewIfNeeded();

    const themes = ["light", "dark", "sepia", "gray", "amoled"];
    for (const theme of themes) {
      await page.evaluate((nextTheme) => {
        if (typeof setTheme === "function") {
          setTheme(nextTheme);
        }
      }, theme);

      await expect(page.locator("#social-section")).toHaveScreenshot(
        `state-theme-${theme}-reader-comments-mobile.png`,
        SOCIAL_SECTION_SCREENSHOT_OPTIONS
      );
    }

    expect(runtimeErrors, `Runtime errors:\n${runtimeErrors.join("\n")}`).toEqual([]);
  });

  test("public mode: unauthenticated comments CTA", async ({ page }) => {
    const state = createVisualState();
    const key = chapterKey("manga_ru", 1, "1");
    state.likesByChapter[key].liked = false;
    state.userReactionByChapter[key] = null;
    await installPublicVisualMocks(page, state);

    const runtimeErrors = [];
    page.on("pageerror", (err) => runtimeErrors.push(`pageerror: ${err.message}`));

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=public-visual");

    await expect(page.locator("#series-list .series-card")).toHaveCount(1);
    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await expect(page.locator("body")).toHaveClass(/public-read-mode/);
    await expect(page.locator("#comment-form")).toHaveClass(/auth-required/);
    await expect(page.locator("#comment-auth-cta")).toBeVisible();
    await expect(page.locator("#comments-list .c-reply")).toHaveCount(0);

    await page.locator("#social-section").scrollIntoViewIfNeeded();
    await expect(page.locator("#social-section")).toHaveScreenshot(
      "state-public-reader-comments-mobile.png",
      SOCIAL_SECTION_SCREENSHOT_OPTIONS
    );

    expect(runtimeErrors, `Runtime errors:\n${runtimeErrors.join("\n")}`).toEqual([]);
  });

  test("audit viewport matrix: primary screens stay inside viewport", async ({ page }) => {
    const state = createVisualState();
    state.readerData.series[0].title = "Visual Test Series With A Very Long Title That Must Wrap Cleanly";
    state.readerData.series[0].volumes[0].custom_name = "Volume With A Long Label";
    state.readerData.series[0].volumes[0].chapters[0].custom_name =
      "Chapter 1 With A Long Name That Should Not Push Controls Outside The Screen";
    await installVisualMocks(page, state);

    const runtimeErrors = [];
    page.on("pageerror", (err) => runtimeErrors.push(`pageerror: ${err.message}`));

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=viewport-matrix");
    const viewports = await page.evaluate(() => window.READER_AUDIT_MAP.visualViewports);

    for (const viewport of viewports) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.locator("#series-list .series-card").first().click();
      await expect(page.locator("#screen-chapters")).toHaveClass(/active/);
      await page.locator("#chapters-list .chapter-item").first().click();
      await expect(page.locator("#screen-reader")).toHaveClass(/active/);
      await expect(page.locator("#reader-text")).not.toBeEmpty();

      const layout = await page.evaluate(() => {
        const active = document.querySelector(".screen.active");
        const topBar = document.querySelector("#reader-top-bar");
        const bottomBar = document.querySelector("#reader-bottom-bar");
        const content = document.querySelector("#reader-content");
        const doc = document.documentElement;
        const rectFor = (el) => {
          if (!el) return null;
          const rect = el.getBoundingClientRect();
          return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height };
        };
        return {
          viewport: { width: window.innerWidth, height: window.innerHeight },
          bodyMargin: getComputedStyle(document.body).margin,
          horizontalOverflow: doc.scrollWidth - window.innerWidth,
          active: rectFor(active),
          topBar: rectFor(topBar),
          bottomBar: rectFor(bottomBar),
          content: rectFor(content),
        };
      });

      expect(layout.bodyMargin, `${viewport.name} body margin reset`).toBe("0px");
      expect(layout.horizontalOverflow, `${viewport.name} horizontal overflow`).toBeLessThanOrEqual(2);
      expect(layout.active.width, `${viewport.name} active screen width`).toBeGreaterThan(0);
      expect(layout.topBar.bottom, `${viewport.name} top bar inside viewport`).toBeLessThanOrEqual(viewport.height + 2);
      expect(layout.bottomBar.top, `${viewport.name} bottom bar inside viewport`).toBeGreaterThanOrEqual(-2);
      expect(layout.content.bottom, `${viewport.name} content reaches bottom chrome`).toBeGreaterThan(layout.topBar.bottom);

      await page.locator("#reader-top-bar .back-btn").click();
      await page.locator("#screen-chapters .back-btn").click();
      await expect(page.locator("#screen-series")).toHaveClass(/active/);
    }

    expect(runtimeErrors, `Runtime errors:\n${runtimeErrors.join("\n")}`).toEqual([]);
  });

  test("admin compact surfaces stay inside viewport", async ({ page }) => {
    const state = createVisualState();
    state.readerData.series[0].title = "Admin Visual Series With Long Names";
    state.readerData.series[0].volumes = Array.from({ length: 8 }, (_, idx) => ({
      volume: idx + 1,
      custom_name: `Том ${idx + 1} с длинной подписью`,
      chapters: [
        {
          chapter: "1",
          custom_name: "Очень длинное название главы, которое не должно ломать админскую строку",
          text: "Compact admin visual body.\n\nSecond paragraph for typo and social layout.",
          url: ""
        }
      ]
    }));
    await installVisualMocks(page, state);

    const assertViewportFit = async (label, selectors) => {
      const layout = await page.evaluate((checkedSelectors) => {
        const rectFor = (selector) => {
          const el = document.querySelector(selector);
          if (!el) return null;
          const rect = el.getBoundingClientRect();
          return {
            selector,
            left: rect.left,
            right: rect.right,
            top: rect.top,
            bottom: rect.bottom,
            width: rect.width,
            height: rect.height,
          };
        };
        return {
          width: window.innerWidth,
          height: window.innerHeight,
          horizontalOverflow: document.documentElement.scrollWidth - window.innerWidth,
          rects: checkedSelectors.map(rectFor).filter(Boolean),
        };
      }, selectors);

      expect(layout.horizontalOverflow, `${label} horizontal overflow`).toBeLessThanOrEqual(2);
      for (const rect of layout.rects) {
        expect(rect.left, `${label} ${rect.selector} left`).toBeGreaterThanOrEqual(-2);
        expect(rect.right, `${label} ${rect.selector} right`).toBeLessThanOrEqual(layout.width + 2);
        expect(rect.top, `${label} ${rect.selector} top`).toBeGreaterThanOrEqual(-2);
        expect(rect.bottom, `${label} ${rect.selector} bottom`).toBeLessThanOrEqual(layout.height + 2);
      }
    };

    await page.setViewportSize({ width: 360, height: 740 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=admin-compact-surfaces");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);
    await page.evaluate(() => toggleAdminMode(true));
    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#screen-chapters")).toHaveClass(/active/);
    await expect(page.locator("#global-admin-fab-btn")).toBeVisible();
    await assertViewportFit("chapters-admin", ["#screen-chapters", ".vol-tabs", "#global-admin-fab"]);

    await page.click("#global-admin-fab-btn");
    await expect(page.locator("#global-admin-menu")).toBeVisible();
    await assertViewportFit("global-admin-menu", ["#global-admin-menu", "#global-admin-fab"]);
    await page.click("#global-admin-fab-btn");
    await expect(page.locator("#global-admin-menu")).toBeHidden();

    await page.click(".admin-bulk-btn");
    await expect(page.locator("#bulk-upload-modal")).not.toHaveClass(/hidden/);
    await assertViewportFit("bulk-modal", ["#bulk-upload-modal"]);
    await page.evaluate(() => closeBulkModal());

    await page.setViewportSize({ width: 360, height: 640 });
    await page.locator("#chapters-list .admin-link-btn").first().click();
    await expect(page.locator("#add-chapter-modal")).not.toHaveClass(/hidden/);
    await assertViewportFit("chapter-editor", ["#add-chapter-modal", ".chapter-editor-shell"]);
    const editorHeaderLayout = await page.evaluate(() => {
      const brand = document.querySelector(".chapter-editor-brand").getBoundingClientRect();
      const context = document.querySelector(".chapter-editor-context").getBoundingClientRect();
      const close = document.querySelector(".chapter-editor-site-actions").getBoundingClientRect();
      const breadcrumb = document.querySelector(".chapter-editor-breadcrumb").getBoundingClientRect();
      const seriesName = document.querySelector("#chapter-editor-series-name").getBoundingClientRect();
      return {
        brandClearOfClose: brand.right <= close.left - 4,
        contextBelowBrand: context.top >= brand.bottom - 1,
        breadcrumbOneLine: breadcrumb.height <= 46,
        seriesNameInsideBreadcrumb: seriesName.left >= breadcrumb.left && seriesName.right <= breadcrumb.right,
      };
    });
    expect(editorHeaderLayout.brandClearOfClose).toBe(true);
    expect(editorHeaderLayout.contextBelowBrand).toBe(true);
    expect(editorHeaderLayout.breadcrumbOneLine).toBe(true);
    expect(editorHeaderLayout.seriesNameInsideBreadcrumb).toBe(true);
    await page.evaluate(() => closeAddChapterModal({ skipConfirm: true }));
    const adminChapterLayout = await page.evaluate(() => {
      const name = document.querySelector("#chapters-list .chapter-name");
      const actions = document.querySelector("#chapters-list .chapter-admin-actions");
      const item = document.querySelector("#chapters-list .chapter-item");
      const nameRect = name?.getBoundingClientRect();
      const actionsRect = actions?.getBoundingClientRect();
      const itemRect = item?.getBoundingClientRect();
      return {
        nameWidth: nameRect?.width || 0,
        actionsInsideItem: !!actionsRect && !!itemRect && actionsRect.left >= itemRect.left - 1 && actionsRect.right <= itemRect.right + 1,
        actionsBelowName: !!actionsRect && !!nameRect && actionsRect.top >= nameRect.top,
      };
    });
    expect(adminChapterLayout.nameWidth).toBeGreaterThanOrEqual(240);
    expect(adminChapterLayout.actionsInsideItem).toBe(true);
    expect(adminChapterLayout.actionsBelowName).toBe(true);

    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await page.evaluate(() => {
      const paragraph = document.querySelector("#reader-text p");
      const range = document.createRange();
      range.selectNodeContents(paragraph);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      showTypoModal();
    });
    await expect(page.locator("#typo-modal")).not.toHaveClass(/hidden/);
    await assertViewportFit("typo-modal", ["#typo-modal"]);
  });

  test("admin controls use grouped hierarchy and explicit motion properties", async ({ page }) => {
    const state = createVisualState();
    state.readerData.series[0].volumes = Array.from({ length: 3 }, (_, idx) => ({
      volume: idx + 1,
      custom_name: `Том ${idx + 1}`,
      chapters: [
        {
          chapter: "1",
          custom_name: "Глава с админскими действиями",
          text: "Admin hierarchy body.",
          url: ""
        }
      ]
    }));
    await installVisualMocks(page, state);

    await page.setViewportSize({ width: 320, height: 568 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=admin-hierarchy-motion");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);
    await page.evaluate(() => toggleAdminMode(true));
    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#screen-chapters")).toHaveClass(/active/);
    await expect(page.locator("#global-admin-fab-btn")).toBeVisible();

    await page.click("#global-admin-fab-btn");
    await expect(page.locator("#global-admin-menu")).toBeVisible();
    await expect(page.locator("#global-admin-menu .admin-menu-section-label").first()).toContainText("Главы");
    await expect(page.locator("#global-admin-menu .global-admin-menu-item-detail").first()).toBeVisible();
    const globalMenuLayer = await page.evaluate(() => {
      const firstLabel = document.querySelector("#global-admin-menu .admin-menu-section-label");
      const menu = document.querySelector("#global-admin-menu");
      const rect = firstLabel.getBoundingClientRect();
      const topElement = document.elementFromPoint(rect.left + 8, rect.top + rect.height / 2);
      const menuRect = menu.getBoundingClientRect();
      return {
        labelIsTopTarget: !!topElement?.closest("#global-admin-menu"),
        topInsideViewport: menuRect.top >= 0,
        bottomInsideViewport: menuRect.bottom <= innerHeight,
      };
    });
    expect(globalMenuLayer.labelIsTopTarget).toBe(true);
    expect(globalMenuLayer.topInsideViewport).toBe(true);
    expect(globalMenuLayer.bottomInsideViewport).toBe(true);
    await page.click("#global-admin-fab-btn");

    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await page.click("#admin-fab-btn");
    await expect(page.locator("#admin-menu")).toBeVisible();
    await expect(page.locator("#admin-menu .admin-menu-section-label")).toHaveCount(3);
    await expect(page.locator("#admin-menu .admin-menu-item.is-danger")).toContainText("Удалить");
    const readerMenuLayout = await page.evaluate(() => {
      const menu = document.querySelector("#admin-menu").getBoundingClientRect();
      return {
        topInsideViewport: menu.top >= 0,
        bottomInsideViewport: menu.bottom <= innerHeight,
      };
    });
    expect(readerMenuLayout.topInsideViewport).toBe(true);
    expect(readerMenuLayout.bottomInsideViewport).toBe(true);

    const motion = await page.evaluate(() => {
      const search = getComputedStyle(document.querySelector("#reader-search-panel")).transitionProperty;
      const editor = getComputedStyle(document.querySelector("#add-chapter-modal")).transitionProperty;
      return { search, editor };
    });
    expect(motion.search.split(",").map((part) => part.trim())).not.toContain("all");
    expect(motion.editor.split(",").map((part) => part.trim())).not.toContain("all");
  });

  test("polish A+B: immersive reader chrome and chapter navigation use calm constraints", async ({ page }) => {
    const state = createVisualState();
    state.readerData.series[0].title = "Alya Reader Polish With A Long Title That Still Needs Quiet Layout";
    state.readerData.series[0].volumes = Array.from({ length: 6 }, (_, idx) => ({
      volume: idx + 1,
      custom_name: `Том ${idx + 1} с очень длинным названием`,
      chapters: [
        {
          chapter: "1",
          custom_name: "Очень длинное название главы без горизонтального сдвига и без наложения на статус",
          text: "A polished reader needs a calm measure on desktop.\n\nIt should feel focused instead of stretched across the whole screen.",
          url: ""
        },
        {
          chapter: "2",
          custom_name: "Следующая глава для проверки навигации",
          text: "Second chapter body.",
          url: ""
        }
      ]
    }));
    await installVisualMocks(page, state);

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=polish-ab");
    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#screen-chapters")).toHaveClass(/active/);
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await page.locator("#reader-top-bar .back-btn").click();
    await expect(page.locator("#screen-chapters")).toHaveClass(/active/);

    const chapterLayout = await page.evaluate(() => {
      const tabs = document.querySelector(".volume-tabs");
      const current = document.querySelector("#chapters-list .chapter-item.current-chapter");
      const name = document.querySelector("#chapters-list .chapter-name");
      const tabsStyle = getComputedStyle(tabs);
      const currentStyle = getComputedStyle(current);
      return {
        overflow: document.documentElement.scrollWidth - window.innerWidth,
        tabsPosition: tabsStyle.position,
        tabsTop: tabsStyle.top,
        tabsBackground: tabsStyle.backgroundColor,
        currentRadius: parseFloat(currentStyle.borderRadius),
        currentShadow: currentStyle.boxShadow,
        nameLines: Math.round(name.getBoundingClientRect().height / parseFloat(getComputedStyle(name).lineHeight)),
      };
    });
    expect(chapterLayout.overflow).toBeLessThanOrEqual(2);
    expect(chapterLayout.tabsPosition).toBe("sticky");
    expect(chapterLayout.tabsTop).not.toBe("auto");
    expect(chapterLayout.tabsBackground).not.toBe("rgba(0, 0, 0, 0)");
    expect(chapterLayout.currentRadius).toBeGreaterThanOrEqual(18);
    expect(chapterLayout.currentShadow).not.toBe("none");
    expect(chapterLayout.nameLines).toBeLessThanOrEqual(3);

    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await page.setViewportSize({ width: 1920, height: 1080 });

    const desktopReader = await page.evaluate(() => {
      const text = document.querySelector("#reader-text");
      const bottom = document.querySelector("#reader-bottom-bar");
      const scrubber = document.querySelector("#reader-scrubber");
      const textStyle = getComputedStyle(text);
      const bottomStyle = getComputedStyle(bottom);
      const scrubberTrack = getComputedStyle(scrubber, "::-webkit-slider-runnable-track");
      return {
        textWidth: text.getBoundingClientRect().width,
        textPaddingTop: parseFloat(textStyle.paddingTop),
        bottomRadius: parseFloat(bottomStyle.borderTopLeftRadius),
        bottomBottom: bottom.getBoundingClientRect().bottom,
        scrubberHeight: parseFloat(scrubberTrack.height || "0"),
        viewportHeight: window.innerHeight,
      };
    });
    expect(desktopReader.textWidth).toBeLessThanOrEqual(880);
    expect(desktopReader.textPaddingTop).toBeGreaterThanOrEqual(34);
    expect(desktopReader.bottomRadius).toBeGreaterThanOrEqual(18);
    expect(desktopReader.bottomBottom).toBeLessThanOrEqual(desktopReader.viewportHeight + 2);
    expect(desktopReader.scrubberHeight).toBeLessThanOrEqual(10);

    await page.setViewportSize({ width: 360, height: 740 });
    await page.evaluate(() => toggleSettings());
    await expect(page.locator("#settings-panel")).not.toHaveClass(/hidden/);
    const settingsLayout = await page.evaluate(() => {
      const panel = document.querySelector("#settings-panel");
      const preview = document.querySelector("#settings-preview");
      const close = document.querySelector(".close-settings-btn");
      const themeChips = [...document.querySelectorAll("#settings-panel .theme-chip")].slice(0, 4);
      const closeTop = close.getBoundingClientRect().top;
      return {
        panelHeight: panel.getBoundingClientRect().height,
        previewHeight: preview.getBoundingClientRect().height,
        previewDisplay: getComputedStyle(preview).display,
        themeChipsOverlapClose: themeChips.some((chip) => chip.getBoundingClientRect().bottom > closeTop),
        viewportHeight: window.innerHeight,
      };
    });
    expect(settingsLayout.panelHeight).toBeLessThanOrEqual(settingsLayout.viewportHeight * 0.92);
    expect(settingsLayout.previewHeight).toBeLessThanOrEqual(132);
    expect(settingsLayout.previewDisplay).toBe("none");
    expect(settingsLayout.themeChipsOverlapClose).toBe(false);

    await page.setViewportSize({ width: 360, height: 640 });
    const tinySettingsLayout = await page.evaluate(() => {
      const close = document.querySelector(".close-settings-btn");
      const themeChips = [...document.querySelectorAll("#settings-panel .theme-chip")].slice(0, 4);
      const closeTop = close.getBoundingClientRect().top;
      return {
        themeChipsOverlapClose: themeChips.some((chip) => chip.getBoundingClientRect().bottom > closeTop),
        panelBottom: document.querySelector("#settings-panel").getBoundingClientRect().bottom,
        viewportHeight: window.innerHeight,
      };
    });
    expect(tinySettingsLayout.themeChipsOverlapClose).toBe(false);
    expect(tinySettingsLayout.panelBottom).toBeLessThanOrEqual(tinySettingsLayout.viewportHeight + 1);
  });

  test("polish V: social actions, reactions, comments, and typo modal form one bottom surface", async ({ page }) => {
    const state = createVisualState();
    await installVisualMocks(page, state);

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=polish-social");
    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await page.locator("#social-section").scrollIntoViewIfNeeded();

    const socialLayout = await page.evaluate(() => {
      const social = document.querySelector("#social-section");
      const actions = document.querySelector("#chapter-actions-bar");
      const reactions = document.querySelector("#reaction-bar");
      const comments = document.querySelector(".comments-section");
      const authCta = document.querySelector("#comment-auth-cta");
      const socialStyle = getComputedStyle(social);
      const actionsStyle = getComputedStyle(actions);
      const reactionsStyle = getComputedStyle(reactions);
      const commentsStyle = getComputedStyle(comments);
      return {
        socialBackground: socialStyle.backgroundColor,
        socialRadius: parseFloat(socialStyle.borderRadius),
        socialShadow: socialStyle.boxShadow,
        actionsDisplay: actionsStyle.display,
        actionsGap: parseFloat(actionsStyle.gap),
        reactionsBackground: reactionsStyle.backgroundColor,
        commentsBorderTopWidth: parseFloat(commentsStyle.borderTopWidth),
        authVisibleWidth: authCta.getBoundingClientRect().width,
        overflow: document.documentElement.scrollWidth - window.innerWidth,
      };
    });
    expect(socialLayout.overflow).toBeLessThanOrEqual(2);
    expect(socialLayout.socialBackground).not.toBe("rgba(0, 0, 0, 0)");
    expect(socialLayout.socialRadius).toBeGreaterThanOrEqual(20);
    expect(socialLayout.socialShadow).not.toBe("none");
    expect(["grid", "flex"]).toContain(socialLayout.actionsDisplay);
    expect(socialLayout.actionsGap).toBeGreaterThanOrEqual(10);
    expect(socialLayout.reactionsBackground).not.toBe("rgba(0, 0, 0, 0)");
    expect(socialLayout.commentsBorderTopWidth).toBeGreaterThanOrEqual(1);

    await page.evaluate(() => {
      const paragraph = document.querySelector("#reader-text p");
      const range = document.createRange();
      range.selectNodeContents(paragraph);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      showTypoModal();
    });
    await expect(page.locator("#typo-modal")).not.toHaveClass(/hidden/);
    const typoLayout = await page.evaluate(() => {
      const modal = document.querySelector("#typo-modal");
      const context = document.querySelector("#typo-modal-context");
      const modalStyle = getComputedStyle(modal);
      const contextStyle = getComputedStyle(context);
      return {
        modalRadius: parseFloat(modalStyle.borderRadius),
        modalMaxWidth: modal.getBoundingClientRect().width,
        contextBackground: contextStyle.backgroundColor,
        contextRadius: parseFloat(contextStyle.borderRadius),
      };
    });
    expect(typoLayout.modalRadius).toBeGreaterThanOrEqual(18);
    expect(typoLayout.modalMaxWidth).toBeLessThanOrEqual(420);
    expect(typoLayout.contextBackground).not.toBe("rgba(0, 0, 0, 0)");
    expect(typoLayout.contextRadius).toBeGreaterThanOrEqual(12);
  });

  test("reader overlays suppress floating action chrome", async ({ page }) => {
    const state = createVisualState();
    state.readerData.series[0].volumes[0].chapters = Array.from({ length: 8 }, (_, idx) => ({
      chapter: String(idx + 1),
      custom_name: idx === 0
        ? "Very long chapter title that should not compete with floating admin controls"
        : `Chapter ${idx + 1}`,
      text: `Chapter ${idx + 1} body.`,
      url: ""
    }));
    await installVisualMocks(page, state);

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=overlay-floating-controls");
    await page.evaluate(() => toggleAdminMode(true));
    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await expect(page.locator("#admin-fab-container")).toBeVisible();

    await page.locator(".header-title-container").click();
    await expect(page.locator("#quick-switcher")).toHaveClass(/active/);
    const quickOverlayChrome = await page.evaluate(() => {
      const adminFab = document.querySelector("#admin-fab-container");
      const adminMenu = document.querySelector("#admin-menu");
      const style = getComputedStyle(adminFab);
      return {
        bodyClass: document.body.classList.contains("reader-overlay-open"),
        opacity: style.opacity,
        pointerEvents: style.pointerEvents,
        menuHidden: adminMenu.classList.contains("hidden"),
      };
    });
    expect(quickOverlayChrome.bodyClass).toBe(true);
    expect(Number(quickOverlayChrome.opacity)).toBeLessThanOrEqual(0.01);
    expect(quickOverlayChrome.pointerEvents).toBe("none");
    expect(quickOverlayChrome.menuHidden).toBe(true);

    await page.locator("#quick-switcher-overlay").click({ force: true });
    await expect(page.locator("#quick-switcher")).not.toHaveClass(/active/);
    await page.locator("#header-toc-btn").click();
    await expect(page.locator("#toc-panel")).toHaveClass(/active/);
    await page.locator("#admin-fab-btn").click({ force: true });
    const tocOverlayChrome = await page.evaluate(() => ({
      bodyClass: document.body.classList.contains("reader-overlay-open"),
      adminMenuHidden: document.querySelector("#admin-menu").classList.contains("hidden"),
      adminFabPointerEvents: getComputedStyle(document.querySelector("#admin-fab-container")).pointerEvents,
    }));
    expect(tocOverlayChrome.bodyClass).toBe(true);
    expect(tocOverlayChrome.adminMenuHidden).toBe(true);
    expect(tocOverlayChrome.adminFabPointerEvents).toBe("none");
  });

  test("search and comment composition controls stay tappable on mobile", async ({ page }) => {
    const state = createVisualState();
    await installVisualMocks(page, state);

    await page.setViewportSize({ width: 360, height: 568 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=search-compose-surfaces");
    await expect(page.locator("#reader-search-panel")).not.toHaveClass(/hidden/);
    await page.locator("#reader-search-input").fill("Chapter 1");
    await expect(page.locator("#reader-search-results")).toBeVisible();
    await expect(page.locator(".reader-search-result").first()).toContainText("Visual Test Series");

    const searchResultLayout = await page.evaluate(() => {
      const panel = document.querySelector("#reader-search-panel").getBoundingClientRect();
      const results = document.querySelector("#reader-search-results").getBoundingClientRect();
      const firstResult = document.querySelector(".reader-search-result").getBoundingClientRect();
      const topElement = document.elementFromPoint(firstResult.left + firstResult.width / 2, firstResult.top + firstResult.height / 2);
      return {
        panelInsideViewport: panel.left >= 0 && panel.right <= innerWidth,
        resultsInsideViewport: results.left >= 0 && results.right <= innerWidth && results.bottom <= innerHeight,
        firstResultTappable: !!topElement?.closest(".reader-search-result"),
        overflow: document.documentElement.scrollWidth - innerWidth,
      };
    });
    expect(searchResultLayout.panelInsideViewport).toBe(true);
    expect(searchResultLayout.resultsInsideViewport).toBe(true);
    expect(searchResultLayout.firstResultTappable).toBe(true);
    expect(searchResultLayout.overflow).toBeLessThanOrEqual(2);

    await page.locator("#reader-search-input").fill("no results with a long query");
    await expect(page.locator("#reader-search-results")).toHaveClass(/hidden/);
    await expect(page.locator("#reader-search-clear")).not.toHaveClass(/hidden/);

    const searchHitTarget = await page.evaluate(() => {
      const clear = document.querySelector("#reader-search-clear");
      const input = document.querySelector("#reader-search-input");
      const header = document.querySelector("#screen-series .reader-header");
      const clearRect = clear.getBoundingClientRect();
      const inputRect = input.getBoundingClientRect();
      const topElement = document.elementFromPoint(clearRect.left + clearRect.width / 2, clearRect.top + clearRect.height / 2);
      return {
        clearIsTopTarget: topElement === clear || clear.contains(topElement),
        searchBelowHeader: inputRect.top >= header.getBoundingClientRect().bottom,
        overflow: document.documentElement.scrollWidth - innerWidth,
      };
    });
    expect(searchHitTarget.clearIsTopTarget).toBe(true);
    expect(searchHitTarget.searchBelowHeader).toBe(true);
    expect(searchHitTarget.overflow).toBeLessThanOrEqual(2);
    await page.locator("#reader-search-clear").click();
    await expect(page.locator("#reader-search-input")).toHaveValue("");

    await page.evaluate(() => toggleAdminMode(true));
    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#reader-search-panel")).not.toHaveClass(/hidden/);
    await page.locator("#reader-search-input").fill("chapter");
    await page.locator("#reader-search-clear").click();
    await expect(page.locator("#reader-search-input")).toHaveValue("");

    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await page.locator("#social-section").scrollIntoViewIfNeeded();
    await page.locator("#comment-format-toggle").click();

    const commentComposeChrome = await page.evaluate(() => {
      const adminFab = document.querySelector("#admin-fab-container");
      const style = getComputedStyle(adminFab);
      const toolbar = document.querySelector("#comment-toolbar").getBoundingClientRect();
      const form = document.querySelector("#comment-form").getBoundingClientRect();
      return {
        bodyClass: document.body.classList.contains("reader-comment-compose-open"),
        adminFabOpacity: Number(style.opacity),
        adminFabPointerEvents: style.pointerEvents,
        toolbarInsideForm: toolbar.left >= form.left && toolbar.right <= form.right,
      };
    });
    expect(commentComposeChrome.bodyClass).toBe(true);
    expect(commentComposeChrome.adminFabOpacity).toBeLessThanOrEqual(0.01);
    expect(commentComposeChrome.adminFabPointerEvents).toBe("none");
    expect(commentComposeChrome.toolbarInsideForm).toBe(true);
  });
});
