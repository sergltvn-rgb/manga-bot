const { test, expect } = require("@playwright/test");

const ADMIN_USER_ID = 6210312655;

function chapterKey(seriesId, volume, chapter) {
  return `${seriesId}_v${volume}_ch${chapter}`;
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
          created_at: "2026-04-21 11:30:00"
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
          created_at: "2026-04-21 11:34:00"
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

    await expect(page.locator("#reader-header")).toHaveScreenshot("state-reader-top-mobile.png", {
      animations: "disabled",
      caret: "hide"
    });

    await page.locator("#social-section").scrollIntoViewIfNeeded();
    await expect(page.locator("#social-section")).toBeVisible();
    await expect(page.locator("#social-section")).toHaveScreenshot("state-reader-bottom-comments-mobile.png", {
      animations: "disabled",
      caret: "hide"
    });

    await page.click("#header-settings-btn");
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

      await expect(page.locator("#social-section")).toHaveScreenshot(`state-theme-${theme}-reader-comments-mobile.png`, {
        animations: "disabled",
        caret: "hide"
      });
    }

    expect(runtimeErrors, `Runtime errors:\n${runtimeErrors.join("\n")}`).toEqual([]);
  });
});
