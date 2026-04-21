const { test, expect } = require("@playwright/test");

const ADMIN_USER_ID = 6210312655;

function nowSql() {
  return new Date().toISOString().slice(0, 19).replace("T", " ");
}

function createMockState() {
  return {
    nextCommentId: 1,
    commentsByChapter: {},
    chapterReactionsByChapter: {},
    userReactionByChapter: {},
    likesByChapter: {},
    calls: {
      reader: 0,
      commentsPost: 0,
      reactionsPost: 0,
      typoPost: 0,
      renameRequest: 0,
      chapterEdit: 0,
      chapterBulk: 0,
      sortPut: 0,
    },
    readerData: {
      bot_username: "AlyaTestBot",
      admin_ids: [ADMIN_USER_ID],
      series: [
        {
          id: "manga_ru",
          title: "Test Series",
          volumes: [
            {
              volume: 1,
              chapters: [
                {
                  chapter: "1",
                  custom_name: "Chapter 1",
                  text: "This is chapter one text for UI smoke test. It has enough content for typo selection.",
                  url: "",
                },
                {
                  chapter: "2",
                  custom_name: "Chapter 2",
                  text: "This is chapter two text for prev and next navigation checks.",
                  url: "",
                },
              ],
            },
          ],
        },
      ],
    },
  };
}

function createMobileSelectionState() {
  return {
    nextCommentId: 1,
    commentsByChapter: {},
    chapterReactionsByChapter: {},
    userReactionByChapter: {},
    likesByChapter: {},
    calls: {
      reader: 0,
      commentsPost: 0,
      reactionsPost: 0,
      typoPost: 0,
      renameRequest: 0,
      chapterEdit: 0,
      chapterBulk: 0,
      sortPut: 0,
    },
    readerData: {
      bot_username: "AlyaTestBot",
      admin_ids: [ADMIN_USER_ID],
      series: [
        {
          id: "akashic_records",
          title: "Хроники Акаши",
          volumes: [
            {
              volume: 11,
              chapters: [
                { chapter: "1", custom_name: "Глава 1", text: "Akashic chapter one." },
                { chapter: "2", custom_name: "Глава 2", text: "Akashic chapter two." },
              ],
            },
          ],
        },
        {
          id: "ranobe_alya",
          title: "Воительница Аля",
          volumes: [
            {
              volume: 1,
              chapters: [
                {
                  chapter: "1",
                  custom_name: "Часть 1",
                  url: "https://teletype.in/@slitvin/The_warrior_Alya_part_1",
                  __chapterContent: {
                    ok: true,
                    source_type: "teletype",
                    html: "<p>Воительница Аля — часть 1.</p>",
                  },
                },
                {
                  chapter: "2",
                  custom_name: "Часть 2",
                  url: "https://teletype.in/@slitvin/The_warrior_Alya_part_2",
                  __chapterContent: {
                    ok: true,
                    source_type: "teletype",
                    html: "<p>Воительница Аля — часть 2.</p>",
                  },
                },
              ],
            },
          ],
        },
        {
          id: "manga_ru",
          title: "Аля иногда... Манга",
          volumes: [
            {
              volume: 1,
              chapters: [
                {
                  chapter: "75",
                  custom_name: "Глава 75",
                  url: "https://example.org/manga-75",
                  __chapterContent: {
                    ok: false,
                    source_type: "fallback",
                    html: "",
                    fallback_url: "https://example.org/manga-75",
                  },
                },
                {
                  chapter: "76",
                  custom_name: "Глава 76",
                  url: "https://example.org/manga-76",
                  __chapterContent: {
                    ok: false,
                    source_type: "fallback",
                    html: "",
                    fallback_url: "https://example.org/manga-76",
                  },
                },
              ],
            },
          ],
        },
      ],
    },
  };
}

function chapterKey(seriesId, volume, chapter) {
  return `${seriesId}_v${volume}_ch${chapter}`;
}

function findVolume(state, seriesId, volumeId) {
  const series = state.readerData.series.find((s) => String(s.id) === String(seriesId));
  if (!series) return null;
  return series.volumes.find((v) => String(v.volume) === String(volumeId)) || null;
}

function findChapter(state, seriesId, volumeId, chapterId) {
  const volume = findVolume(state, seriesId, volumeId);
  if (!volume) return null;
  return volume.chapters.find((ch) => String(ch.chapter) === String(chapterId)) || null;
}

function renderInlineChapterHtml(text) {
  return String(text || "")
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => `<p>${part}</p>`)
    .join("");
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

async function fulfillJson(route, payload, status = 200) {
  await route.fulfill({
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "access-control-allow-origin": "*",
    },
    body: JSON.stringify(payload),
  });
}

async function installTelegramAndApiMocks(page, state) {
  await page.addInitScript(({ adminUserId }) => {
    window.Telegram = {
      WebApp: {
        expand: () => {},
        ready: () => {},
        close: () => {
          window.__tgClosed = true;
        },
        openTelegramLink: (url) => {
          window.__tgLinks = window.__tgLinks || [];
          window.__tgLinks.push(String(url));
        },
        showConfirm: (_text, cb) => cb(true),
        HapticFeedback: {
          impactOccurred: () => {},
          notificationOccurred: () => {},
        },
        initData: "mocked-init-data",
        initDataUnsafe: {
          user: {
            id: adminUserId,
            first_name: "Admin",
          },
        },
      },
    };
  }, { adminUserId: ADMIN_USER_ID });

  await page.route("https://telegram.org/js/telegram-web-app.js", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: "/* mocked telegram web app script */",
    });
  });

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
          "access-control-allow-headers": "Content-Type, Authorization",
        },
        body: "",
      });
      return;
    }

    if (pathname === "/api/reader" && method === "GET") {
      state.calls.reader += 1;
      await fulfillJson(route, state.readerData);
      return;
    }

    if (pathname === "/api/chapter-content" && method === "GET") {
      const seriesId = url.searchParams.get("series_id") || "";
      const volumeId = url.searchParams.get("volume") || "";
      const chapterId = url.searchParams.get("chapter") || "";
      const chapter = findChapter(state, seriesId, volumeId, chapterId);
      if (!chapter) {
        await fulfillJson(route, { error: "not found" }, 404);
        return;
      }

      const fallbackUrl = chapter.url || (Array.isArray(chapter.urls) ? chapter.urls[0] : null) || null;
      if (chapter.__chapterContent) {
        await fulfillJson(route, {
          cache_status: "miss",
          ...chapter.__chapterContent,
          fallback_url: chapter.__chapterContent.fallback_url ?? fallbackUrl,
        });
        return;
      }

      if (chapter.text) {
        await fulfillJson(route, {
          ok: true,
          source_type: "inline",
          html: renderInlineChapterHtml(chapter.text),
          fallback_url: fallbackUrl,
          cache_status: "miss",
        });
        return;
      }

      await fulfillJson(route, {
        ok: false,
        source_type: "fallback",
        html: "",
        fallback_url: fallbackUrl,
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
      const payload = state.likesByChapter[key] || { count: 0, liked: false };
      await fulfillJson(route, payload);
      return;
    }

    if (pathname === "/api/likes" && method === "POST") {
      const body = safeJson(request);
      const key = String(body.chapter_key || "");
      const prev = state.likesByChapter[key] || { count: 0, liked: false };
      const nextLiked = !prev.liked;
      state.likesByChapter[key] = {
        count: Math.max(0, prev.count + (nextLiked ? 1 : -1)),
        liked: nextLiked,
      };
      await fulfillJson(route, state.likesByChapter[key]);
      return;
    }

    if (pathname === "/api/comments" && method === "GET") {
      const key = url.searchParams.get("chapter_key") || "";
      const comments = state.commentsByChapter[key] || [];
      await fulfillJson(route, { comments });
      return;
    }

    if (pathname === "/api/comments" && method === "POST") {
      state.calls.commentsPost += 1;
      const body = safeJson(request);
      const key = String(body.chapter_key || "");
      const comments = state.commentsByChapter[key] || [];
      comments.unshift({
        id: state.nextCommentId++,
        chapter_key: key,
        user_id: String(ADMIN_USER_ID),
        user_name: "Admin",
        text: String(body.text || ""),
        parent_id: body.parent_id || null,
        likes: 0,
        user_reaction: null,
        created_at: nowSql(),
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
        user_reaction: state.userReactionByChapter[key] || null,
      });
      return;
    }

    if (pathname === "/api/reactions" && method === "POST") {
      state.calls.reactionsPost += 1;
      const body = safeJson(request);
      const key = String(body.chapter_key || "");
      const type = String(body.reaction || "");
      const reactionBucket = state.chapterReactionsByChapter[key] || {};
      const previousType = state.userReactionByChapter[key] || null;

      if (previousType === type) {
        reactionBucket[type] = Math.max(0, Number(reactionBucket[type] || 0) - 1);
        state.userReactionByChapter[key] = null;
      } else {
        if (previousType) {
          reactionBucket[previousType] = Math.max(0, Number(reactionBucket[previousType] || 0) - 1);
        }
        reactionBucket[type] = Number(reactionBucket[type] || 0) + 1;
        state.userReactionByChapter[key] = type;
      }

      state.chapterReactionsByChapter[key] = reactionBucket;
      await fulfillJson(route, { ok: true });
      return;
    }

    if (pathname === "/api/typo" && method === "POST") {
      state.calls.typoPost += 1;
      await fulfillJson(route, { ok: true });
      return;
    }

    if (pathname === "/api/rename/request" && method === "POST") {
      state.calls.renameRequest += 1;
      await fulfillJson(route, { ok: true, short_id: `mock${state.calls.renameRequest}` });
      return;
    }

    if (pathname === "/api/rename" && method === "DELETE") {
      await fulfillJson(route, { ok: true });
      return;
    }

    if (pathname === "/api/chapters" && method === "PUT") {
      state.calls.chapterEdit += 1;
      const body = safeJson(request);
      const volume = findVolume(state, body.series_id, body.volume);
      if (volume) {
        const chapter = volume.chapters.find((ch) => String(ch.chapter) === String(body.chapter));
        if (chapter) {
          chapter.url = String(body.url || "");
          chapter.urls = chapter.url
            .split("\n")
            .map((x) => x.trim())
            .filter(Boolean);
        }
      }
      await fulfillJson(route, { ok: true });
      return;
    }

    if (pathname === "/api/chapters/bulk" && method === "POST") {
      state.calls.chapterBulk += 1;
      const body = safeJson(request);
      const volume = findVolume(state, body.series_id, body.volume);
      const urls = Array.isArray(body.urls) ? body.urls : [];
      let chapterNumber = Number(body.start_chapter || 1);
      if (volume) {
        for (const urlText of urls) {
          const chapterId = String(chapterNumber++);
          volume.chapters.push({
            chapter: chapterId,
            custom_name: `Chapter ${chapterId}`,
            text: `Autogenerated chapter ${chapterId} from bulk upload.`,
            url: String(urlText || ""),
            urls: [String(urlText || "")],
          });
        }
      }
      await fulfillJson(route, { ok: true, added: urls.length });
      return;
    }

    if (pathname === "/api/sort" && method === "PUT") {
      state.calls.sortPut += 1;
      const body = safeJson(request);
      const volume = findVolume(state, body.series_id, body.volume);
      if (volume && Array.isArray(body.order)) {
        const byId = new Map(volume.chapters.map((ch) => [String(ch.chapter), ch]));
        volume.chapters = body.order.map((id) => byId.get(String(id))).filter(Boolean);
      }
      await fulfillJson(route, { ok: true });
      return;
    }

    if (pathname === "/api/avatar" && method === "GET") {
      await route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
        },
        body: "",
      });
      return;
    }

    await fulfillJson(route, { ok: true });
  });
}

test.describe("Reader E2E smoke", () => {
  test("user flow: open chapter, navigate, comment, react, typo report", async ({ page }) => {
    const state = createMockState();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);

    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#screen-chapters")).toHaveClass(/active/);
    await expect(page.locator("#chapters-list .chapter-item")).toHaveCount(2);

    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await expect(page.locator("#chapter-title-header")).toContainText("1");

    await page.click("#next-chapter-btn");
    await expect(page.locator("#chapter-title-header")).toContainText("2");
    await expect(page.locator("#chapter-indicator")).toContainText("2 / 2");

    await page.click("#prev-chapter-btn");
    await expect(page.locator("#chapter-title-header")).toContainText("1");
    await expect(page.locator("#chapter-indicator")).toContainText("1 / 2");

    const commentText = "playwright comment smoke";
    await page.fill("#comment-input", commentText);
    await page.click("#comment-form .comment-submit-btn");
    await expect(page.locator("#comments-list .comment-text").first()).toContainText("playwright comment smoke");
    await expect.poll(() => state.calls.commentsPost).toBeGreaterThan(0);

    await page.click("#reaction-bar .reaction-item.type-like");
    await expect(page.locator("#reaction-bar .reaction-item.type-like")).toHaveClass(/active/);
    await expect.poll(() => state.calls.reactionsPost).toBeGreaterThan(0);

    await page.evaluate(() => {
      const paragraph = document.querySelector("#reader-text p");
      if (!paragraph || !paragraph.firstChild) throw new Error("Paragraph for typo test not found");
      const node = paragraph.firstChild;
      const range = document.createRange();
      const endOffset = Math.min(12, node.textContent.length);
      range.setStart(node, 0);
      range.setEnd(node, endOffset);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      handleSelection();
      showTypoModal();
    });

    await expect(page.locator("#typo-modal")).not.toHaveClass(/hidden/);
    await page.fill("#typo-comment", "typo smoke report");
    await page.click("#typo-submit-btn");
    await expect.poll(() => state.calls.typoPost).toBe(1);
  });

  test("admin flow: rename request, edit url, bulk upload, sort", async ({ page }) => {
    const state = createMockState();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);

    await page.evaluate(() => {
      toggleAdminMode(true);
    });

    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#screen-chapters")).toHaveClass(/active/);
    await expect(page.locator("#chapters-list .chapter-item")).toHaveCount(2);

    await page.evaluate(async () => {
      await renameItem("series_manga_ru");
    });
    await expect.poll(() => state.calls.renameRequest).toBe(1);
    await expect.poll(async () => {
      return page.evaluate(() => (window.__tgLinks || []).length);
    }).toBe(1);

    await page.evaluate(() => {
      openEditUrlModal(0);
    });
    await expect(page.locator("#edit-url-modal")).not.toHaveClass(/hidden/);
    await page.fill("#edit-url-input", "https://example.org/chapter-1-updated");
    await page.click("#edit-url-save");
    await expect.poll(() => state.calls.chapterEdit).toBe(1);

    await expect(page.locator(".admin-bulk-btn")).toBeVisible();
    await page.click(".admin-bulk-btn");
    await page.fill("#bulk-upload-input", "https://example.org/chapter-3\nhttps://example.org/chapter-4");
    await page.click("#bulk-upload-save");
    await expect.poll(() => state.calls.chapterBulk).toBe(1);
    await expect.poll(() => {
      const volume = findVolume(state, "manga_ru", 1);
      return volume ? volume.chapters.length : 0;
    }).toBe(4);

    await page.click("#screen-chapters .back-btn");
    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#chapters-list .chapter-item")).toHaveCount(4);

    await page.evaluate(async () => {
      await reorderChapters(0, 1);
    });
    await expect.poll(() => state.calls.sortPut).toBe(1);
  });

  test("mobile flow: selects the correct title and keeps chapter list tappable after fallback", async ({ browser }) => {
    const state = createMobileSelectionState();
    const context = await browser.newContext({
      viewport: { width: 393, height: 852 },
      userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 7)",
    });
    const page = await context.newPage();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=mobile-a");
    await expect(page.locator("#series-list .series-card")).toHaveCount(3);

    await page.locator("#series-list .series-card").nth(1).click();
    await expect(page.locator("#chapters-title")).toHaveText("Воительница Аля");
    await expect(page.locator("#chapters-list .chapter-item")).toHaveCount(2);

    await page.locator("#screen-chapters .back-btn").click();
    await page.locator("#series-list .series-card").nth(2).click();
    await expect(page.locator("#chapters-title")).toHaveText("Аля иногда... Манга");

    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await expect(page.locator("#reader-text")).toContainText("Не удалось загрузить главу");
    await expect(page.locator("#reader-text .state-action-btn")).toHaveText("Открыть источник");

    await page.locator("#screen-reader .back-btn").click();
    await expect(page.locator("#screen-chapters")).toHaveClass(/active/);
    await page.locator("#chapters-list .chapter-item").nth(1).click();
    await expect(page.locator("#chapter-title-header")).toContainText("76");

    await context.close();
  });

  test("cache snapshot rotates when rev changes", async ({ page }) => {
    const state = createMockState();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=rev-a");
    await expect.poll(() => page.evaluate(() => localStorage.getItem("reader_api_snapshot_v2_rev-a") !== null)).toBe(true);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=rev-b");
    await expect.poll(() => page.evaluate(() => ({
      currentRev: JSON.parse(localStorage.getItem("reader_api_snapshot_rev") || '""'),
      hasOldKey: localStorage.getItem("reader_api_snapshot_v2_rev-a") !== null,
      hasNewKey: localStorage.getItem("reader_api_snapshot_v2_rev-b") !== null,
    }))).toEqual({
      currentRev: "rev-b",
      hasOldKey: false,
      hasNewKey: true,
    });
  });
});
