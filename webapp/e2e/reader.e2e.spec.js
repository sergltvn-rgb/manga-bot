const { test, expect } = require("@playwright/test");

const ADMIN_USER_ID = 6210312655;

function nowSql() {
  return new Date().toISOString().slice(0, 19).replace("T", " ");
}

function createMockState() {
  return {
    nextCommentId: 1,
    progressBookmarks: [],
    commentsByChapter: {},
    chapterReactionsByChapter: {},
    userReactionByChapter: {},
    likesByChapter: {},
    sortFailure: null,
    webAuthUser: null,
    loginPersistsSession: true,
    calls: {
      reader: 0,
      authMe: 0,
      authLogin: 0,
      authLogout: 0,
      chapterContent: 0,
      commentsPost: 0,
      commentsReact: 0,
      commentsReport: 0,
      likesPost: 0,
      reactionsPost: 0,
      typoPost: 0,
      renameRequest: 0,
      chapterEdit: 0,
      chapterBulk: 0,
      chapterBulkPreview: 0,
      chapterAdd: 0,
      chapterDelete: 0,
      seriesUpdate: 0,
      sortPut: 0,
    },
    chapterContentRequests: [],
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
    progressBookmarks: [
      {
        series_id: "ranobe_alya",
        volume_id: "1",
        chapter_key: "2",
        scroll_pos: 0,
        updated_at: nowSql(),
      },
    ],
    commentsByChapter: {},
    chapterReactionsByChapter: {},
    userReactionByChapter: {},
    likesByChapter: {},
    webAuthUser: null,
    calls: {
      reader: 0,
      authMe: 0,
      authLogin: 0,
      authLogout: 0,
      chapterContent: 0,
      commentsPost: 0,
      reactionsPost: 0,
      typoPost: 0,
      renameRequest: 0,
      chapterEdit: 0,
      chapterBulk: 0,
      chapterBulkPreview: 0,
      sortPut: 0,
    },
    chapterContentRequests: [],
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
                  url: "https://teletype.in/@slitvin/Zk5q_UBkJ37",
                  __chapterContent: {
                    ok: true,
                    source_type: "teletype",
                    html: '<figure><img src="https://example.org/manga-75.png" alt="Page 1"></figure>',
                    fallback_url: "https://teletype.in/@slitvin/Zk5q_UBkJ37",
                  },
                },
                {
                  chapter: "76",
                  custom_name: "Глава 76",
                  url: "https://teletype.in/@slitvin/iOzOzGNO2t3",
                  __chapterContent: {
                    ok: true,
                    source_type: "teletype",
                    html: "<figure><div><div></div></div></figure>",
                    fallback_url: "https://teletype.in/@slitvin/iOzOzGNO2t3",
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
  // Disable CSS transitions/animations globally for deterministic click targets.
  await page.addInitScript(() => {
    const injectNoMotionCss = () => {
      const existing = document.getElementById("__pw_no_motion");
      if (existing) return;
      const style = document.createElement("style");
      style.id = "__pw_no_motion";
      style.textContent = `
        *, *::before, *::after {
          transition: none !important;
          animation-duration: 0s !important;
          animation-delay: 0s !important;
        }
      `;
      (document.head || document.documentElement).appendChild(style);
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", injectNoMotionCss, { once: true });
    } else {
      injectNoMotionCss();
    }
  });

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

  await page.route("https://example.org/manga-75.png", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1200"><rect width="800" height="1200" fill="#d8d8d8"/></svg>',
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
      state.calls.chapterContent += 1;
      const seriesId = url.searchParams.get("series_id") || "";
      const volumeId = url.searchParams.get("volume") || "";
      const chapterId = url.searchParams.get("chapter") || "";
      state.chapterContentRequests = state.chapterContentRequests || [];
      state.chapterContentRequests.push(`${seriesId}::${volumeId}::${chapterId}`);
      if (state.chapterContentDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, state.chapterContentDelayMs));
      }
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
      await fulfillJson(route, { bookmarks: state.progressBookmarks || [] });
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

    if (pathname === "/api/chapters/bulk/preview" && method === "POST") {
      state.calls.chapterBulkPreview += 1;
      const body = safeJson(request);
      const volume = findVolume(state, body.series_id, body.volume);
      const urls = Array.isArray(body.urls) ? body.urls : [];
      let chapterNumber = Number(body.start_chapter || 1);
      const items = [];
      const duplicates = [];
      const invalid = [];
      const warnings = [];
      for (let idx = 0; idx < urls.length; idx += 1) {
        const chapter = String(chapterNumber++);
        const urlText = String(urls[idx] || "");
        if (!/^https?:\/\//i.test(urlText)) {
          invalid.push({ index: idx + 1, chapter, url: urlText, reason: "invalid_url" });
          warnings.push(`Глава ${chapter}: невалидная ссылка`);
          continue;
        }
        const exists = !!volume?.chapters.some((ch) => String(ch.chapter) === chapter);
        const item = { index: idx + 1, chapter, url: urlText, status: exists ? "duplicate" : "new" };
        items.push(item);
        if (exists) {
          duplicates.push(item);
          warnings.push(`Глава ${chapter}: уже есть в БД`);
        }
      }
      await fulfillJson(route, {
        ok: invalid.length === 0,
        items,
        duplicates,
        invalid,
        warnings,
        summary: {
          total: urls.length,
          valid: items.length,
          new: items.filter((item) => item.status === "new").length,
          duplicates: duplicates.length,
          invalid: invalid.length,
        },
      });
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
      if (state.sortFailure) {
        await fulfillJson(route, state.sortFailure.payload, state.sortFailure.status);
        return;
      }
      const body = safeJson(request);
      const volume = findVolume(state, body.series_id, body.volume);
      if (volume && Array.isArray(body.order)) {
        const byId = new Map(volume.chapters.map((ch) => [String(ch.chapter), ch]));
        volume.chapters = body.order.map((id) => byId.get(String(id))).filter(Boolean);
      }
      await fulfillJson(route, { ok: true });
      return;
    }

    if (pathname === "/api/chapters" && method === "POST") {
      state.calls.chapterAdd += 1;
      const body = safeJson(request);
      const volume = findVolume(state, body.series_id, body.volume);
      if (!volume) {
        await fulfillJson(route, { error: "unknown volume" }, 400);
        return;
      }
      const chapterId = String(body.chapter || "").trim();
      if (!chapterId) {
        await fulfillJson(route, { error: "missing chapter" }, 400);
        return;
      }
      if (volume.chapters.some((ch) => String(ch.chapter) === chapterId)) {
        await fulfillJson(route, { error: "chapter already exists" }, 409);
        return;
      }
      volume.chapters.push({
        chapter: chapterId,
        custom_name: String(body.name || "") || `Chapter ${chapterId}`,
        text: "Added by e2e add-chapter flow.",
        url: String(body.url || ""),
        urls: [String(body.url || "")],
      });
      await fulfillJson(route, { ok: true, chapter: chapterId });
      return;
    }

    if (pathname === "/api/chapters" && method === "DELETE") {
      state.calls.chapterDelete += 1;
      const body = safeJson(request);
      const volume = findVolume(state, body.series_id, body.volume);
      if (!volume) {
        await fulfillJson(route, { error: "unknown volume" }, 400);
        return;
      }
      const before = volume.chapters.length;
      volume.chapters = volume.chapters.filter((ch) => String(ch.chapter) !== String(body.chapter));
      const deleted = before - volume.chapters.length;
      if (deleted === 0) {
        await fulfillJson(route, { error: "chapter not found" }, 404);
        return;
      }
      await fulfillJson(route, { ok: true, deleted });
      return;
    }

    if (pathname === "/api/series" && method === "PUT") {
      state.calls.seriesUpdate += 1;
      const body = safeJson(request);
      const series = state.readerData.series.find((s) => String(s.id) === String(body.series_id));
      if (!series) {
        await fulfillJson(route, { error: "unknown series" }, 400);
        return;
      }
      series.cover_url = String(body.cover_url || "");
      await fulfillJson(route, { ok: true, cover_url: series.cover_url });
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

async function installPublicApiMocks(page, state) {
  await page.addInitScript(() => {
    const injectNoMotionCss = () => {
      const existing = document.getElementById("__pw_no_motion");
      if (existing) return;
      const style = document.createElement("style");
      style.id = "__pw_no_motion";
      style.textContent = `
        *, *::before, *::after {
          transition: none !important;
          animation-duration: 0s !important;
          animation-delay: 0s !important;
        }
      `;
      (document.head || document.documentElement).appendChild(style);
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", injectNoMotionCss, { once: true });
    } else {
      injectNoMotionCss();
    }
  });

  await page.route("https://telegram.org/js/telegram-web-app.js", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: "/* public browser mode: Telegram WebApp is absent */",
    });
  });
  await page.route("https://telegram.org/js/telegram-widget.js**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: "/* mocked telegram login widget */",
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

    if (pathname === "/api/auth/me" && method === "GET") {
      state.calls.authMe += 1;
      await fulfillJson(route, {
        authenticated: Boolean(state.webAuthUser),
        user: state.webAuthUser,
        is_admin: Boolean(state.webAuthUser && state.readerData.admin_ids.includes(Number(state.webAuthUser.id))),
      });
      return;
    }

    if (pathname === "/api/auth/telegram-login" && method === "POST") {
      state.calls.authLogin += 1;
      const body = safeJson(request);
      const loggedInUser = {
        id: Number(body.id || ADMIN_USER_ID),
        first_name: String(body.first_name || "SiteUser"),
        username: body.username || "site_user",
      };
      if (state.loginPersistsSession !== false) {
        state.webAuthUser = loggedInUser;
      }
      await fulfillJson(route, {
        ok: true,
        authenticated: true,
        user: loggedInUser,
        is_admin: state.readerData.admin_ids.includes(Number(loggedInUser.id)),
      });
      return;
    }

    if (pathname === "/api/auth/logout" && method === "POST") {
      state.calls.authLogout += 1;
      state.webAuthUser = null;
      await fulfillJson(route, { ok: true, authenticated: false });
      return;
    }

    if (pathname === "/api/chapter-content" && method === "GET") {
      state.calls.chapterContent += 1;
      const seriesId = url.searchParams.get("series_id") || "";
      const volumeId = url.searchParams.get("volume") || "";
      const chapterId = url.searchParams.get("chapter") || "";
      const chapter = findChapter(state, seriesId, volumeId, chapterId);
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
      await fulfillJson(route, state.webAuthUser ? { ok: true } : { error: "auth required" }, state.webAuthUser ? 200 : 401);
      return;
    }

    if (pathname === "/api/likes" && method === "GET") {
      const key = url.searchParams.get("chapter_key") || "";
      const payload = state.likesByChapter[key] || { count: 0, liked: false };
      await fulfillJson(route, {
        count: payload.count,
        liked: Boolean(state.webAuthUser && payload.liked),
      });
      return;
    }

    if (pathname === "/api/comments" && method === "GET") {
      const key = url.searchParams.get("chapter_key") || "";
      await fulfillJson(route, { comments: state.commentsByChapter[key] || [] });
      return;
    }

    if (pathname === "/api/reactions" && method === "GET") {
      const key = url.searchParams.get("chapter_key") || "";
      await fulfillJson(route, {
        reactions: state.chapterReactionsByChapter[key] || {},
        user_reaction: state.webAuthUser ? (state.userReactionByChapter[key] || null) : null,
      });
      return;
    }

    if (pathname === "/api/likes" && method === "POST") {
      state.calls.likesPost += 1;
      if (!state.webAuthUser) {
        await fulfillJson(route, { error: "auth required" }, 401);
        return;
      }
      const body = safeJson(request);
      const key = String(body.chapter_key || "");
      const prev = state.likesByChapter[key] || { count: 0, liked: false };
      const nextLiked = !prev.liked;
      state.likesByChapter[key] = {
        count: Math.max(0, Number(prev.count || 0) + (nextLiked ? 1 : -1)),
        liked: nextLiked,
      };
      await fulfillJson(route, state.likesByChapter[key]);
      return;
    }

    if (pathname === "/api/comments" && method === "POST") {
      state.calls.commentsPost += 1;
      if (!state.webAuthUser) {
        await fulfillJson(route, { error: "auth required" }, 401);
        return;
      }
      const body = safeJson(request);
      const key = String(body.chapter_key || "");
      const comments = state.commentsByChapter[key] || [];
      comments.unshift({
        id: state.nextCommentId++,
        chapter_key: key,
        user_id: String(state.webAuthUser.id),
        user_name: state.webAuthUser.first_name || "SiteUser",
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
      state.calls.commentsReact += 1;
      await fulfillJson(route, state.webAuthUser ? { ok: true } : { error: "auth required" }, state.webAuthUser ? 200 : 401);
      return;
    }

    if (pathname === "/api/comments/report" && method === "POST") {
      state.calls.commentsReport += 1;
      await fulfillJson(route, state.webAuthUser ? { ok: true } : { error: "auth required" }, state.webAuthUser ? 200 : 401);
      return;
    }

    if (pathname === "/api/reactions" && method === "POST") {
      state.calls.reactionsPost += 1;
      if (!state.webAuthUser) {
        await fulfillJson(route, { error: "auth required" }, 401);
        return;
      }
      const body = safeJson(request);
      const key = String(body.chapter_key || "");
      const type = String(body.reaction || "");
      const reactionBucket = state.chapterReactionsByChapter[key] || {};
      const previousType = state.userReactionByChapter[key] || null;
      if (previousType === type) {
        reactionBucket[type] = Math.max(0, Number(reactionBucket[type] || 0) - 1);
        state.userReactionByChapter[key] = null;
      } else {
        if (previousType) reactionBucket[previousType] = Math.max(0, Number(reactionBucket[previousType] || 0) - 1);
        reactionBucket[type] = Number(reactionBucket[type] || 0) + 1;
        state.userReactionByChapter[key] = type;
      }
      state.chapterReactionsByChapter[key] = reactionBucket;
      await fulfillJson(route, { ok: true });
      return;
    }

    if (pathname === "/api/chapters" && method === "POST") {
      state.calls.chapterAdd += 1;
      if (!state.webAuthUser || !state.readerData.admin_ids.includes(Number(state.webAuthUser.id))) {
        await fulfillJson(route, { error: "forbidden" }, state.webAuthUser ? 403 : 401);
        return;
      }
      const body = safeJson(request);
      const volume = findVolume(state, body.series_id, body.volume);
      if (!volume) {
        await fulfillJson(route, { error: "unknown volume" }, 400);
        return;
      }
      volume.chapters.push({
        chapter: String(body.chapter || ""),
        custom_name: String(body.name || "") || `Chapter ${body.chapter}`,
        text: "Added through site login.",
        url: String(body.url || ""),
      });
      await fulfillJson(route, { ok: true, chapter: body.chapter });
      return;
    }

    if (pathname === "/api/sort" && method === "PUT") {
      state.calls.sortPut += 1;
      if (!state.webAuthUser || !state.readerData.admin_ids.includes(Number(state.webAuthUser.id))) {
        await fulfillJson(route, { error: "forbidden" }, state.webAuthUser ? 403 : 401);
        return;
      }
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
  test("public browser mode: reads chapter and comments without authenticated actions", async ({ page }) => {
    const state = createMockState();
    const key = chapterKey("manga_ru", 1, "1");
    state.likesByChapter[key] = { count: 7, liked: false };
    state.chapterReactionsByChapter[key] = { like: 3, heart: 2 };
    state.commentsByChapter[key] = [
      {
        id: 11,
        chapter_key: key,
        user_id: "101",
        user_name: "PublicReader",
        text: "public comment is visible",
        parent_id: null,
        likes: 4,
        user_reaction: null,
        created_at: nowSql(),
      },
    ];
    await installPublicApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=public-mode");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);
    await expect(page.locator("#global-telegram-login-widget")).toBeVisible();
    await expect(page.locator("#global-telegram-login-widget script[data-telegram-login='AlyaTestBot']")).toHaveCount(1);

    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await expect(page.locator("#reader-text")).toContainText("This is chapter one text");

    await expect(page.locator("#comments-list .comment-text").first()).toContainText("public comment is visible");
    await expect(page.locator("#comment-form")).toHaveClass(/auth-required/);
    await expect(page.locator("#comment-auth-cta")).toBeVisible();
    await expect(page.locator("#comment-auth-cta")).toContainText("Telegram");
    await expect(page.locator("#comments-list .c-reply")).toHaveCount(0);
    await expect(page.locator("#comments-list .c-like")).toHaveCount(0);

    await expect(page.locator("#like-btn")).toHaveAttribute("aria-disabled", "true");
    await page.locator("#like-btn").dispatchEvent("click");
    await page.click("#reaction-bar .reaction-item.type-like");

    expect(state.calls.likesPost).toBe(0);
    expect(state.calls.reactionsPost).toBe(0);
    expect(state.calls.commentsPost).toBe(0);
    expect(state.calls.commentsReact).toBe(0);
    expect(state.calls.commentsReport).toBe(0);
  });

  test("public site login enables comments, likes, and reactions", async ({ page }) => {
    const state = createMockState();
    await installPublicApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=site-login");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);

    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#comment-form")).toHaveClass(/auth-required/);

    await page.evaluate(({ id }) => {
      return window.onTelegramLogin({
        id,
        first_name: "SiteUser",
        username: "site_user",
        auth_date: "1700000000",
        hash: "mocked",
      });
    }, { id: 987654 });

    await expect.poll(() => state.calls.authLogin).toBe(1);
    await expect(page.locator("#comment-form")).not.toHaveClass(/auth-required/);
    await expect(page.locator("#comment-auth-cta")).toBeHidden();

    await page.fill("#comment-input", "site login comment");
    await page.click("#comment-form .comment-send-btn");
    await expect.poll(() => state.calls.commentsPost).toBe(1);
    await expect(page.locator("#comments-list .comment-text").first()).toContainText("site login comment");

    await page.locator("#like-btn").click();
    await expect.poll(() => state.calls.likesPost).toBe(1);

    await page.click("#reaction-bar .reaction-item.type-heart");
    await expect.poll(() => state.calls.reactionsPost).toBe(1);
    await expect(page.locator("#reaction-bar .reaction-item.type-heart")).toHaveClass(/active/);
  });

  test("public site login stays read-only when the session cookie is not confirmed", async ({ page }) => {
    const state = createMockState();
    state.loginPersistsSession = false;
    await installPublicApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=site-login-no-cookie");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);

    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#comment-form")).toHaveClass(/auth-required/);

    const loginResult = await page.evaluate(({ id }) => {
      return window.onTelegramLogin({
        id,
        first_name: "SiteUser",
        username: "site_user",
        auth_date: "1700000000",
        hash: "mocked",
      });
    }, { id: 987654 });

    expect(loginResult).toBe(false);
    await expect.poll(() => state.calls.authLogin).toBe(1);
    await expect.poll(() => state.calls.authMe).toBeGreaterThanOrEqual(2);
    await expect(page.locator("#comment-form")).toHaveClass(/auth-required/);
    await expect(page.locator("#comment-auth-cta")).toBeVisible();

    await page.locator("#like-btn").dispatchEvent("click");
    await page.click("#reaction-bar .reaction-item.type-heart");

    expect(state.calls.likesPost).toBe(0);
    expect(state.calls.reactionsPost).toBe(0);
    expect(state.calls.commentsPost).toBe(0);
  });

  test("site write auth rejection disables composer and restores comment draft", async ({ page }) => {
    const state = createMockState();
    await installPublicApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=site-session-rejected");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);

    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await page.evaluate(({ id }) => {
      return window.onTelegramLogin({
        id,
        first_name: "SiteUser",
        username: "site_user",
        auth_date: "1700000000",
        hash: "mocked",
      });
    }, { id: 987654 });
    await expect(page.locator("#comment-form")).not.toHaveClass(/auth-required/);

    state.webAuthUser = null;
    await page.fill("#comment-input", "draft survives rejected auth");
    await page.click("#comment-form .comment-send-btn");

    await expect.poll(() => state.calls.commentsPost).toBe(1);
    await expect(page.locator("#comment-form")).toHaveClass(/auth-required/);
    await expect(page.locator("#comment-input")).toHaveValue("draft survives rejected auth");
    await expect(page.locator("#comment-auth-cta")).toBeVisible();
    await expect(page.locator("#comments-list")).not.toContainText("draft survives rejected auth");
  });

  test("admin site login unlocks editor add and move actions", async ({ page }) => {
    const state = createMockState();
    await installPublicApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=site-admin");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);

    await page.evaluate(({ id }) => {
      return window.onTelegramLogin({
        id,
        first_name: "Admin",
        username: "admin_site",
        auth_date: "1700000000",
        hash: "mocked",
      });
    }, { id: ADMIN_USER_ID });
    await expect.poll(() => state.calls.authLogin).toBe(1);

    await page.evaluate(() => toggleAdminMode(true));
    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#screen-chapters")).toHaveClass(/admin-enabled/);

    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await page.evaluate(() => openAddChapterModal());
    await page.fill("#add-chapter-url", "https://example.org/site-admin-added");
    await page.fill("#add-chapter-name", "Site admin added chapter");
    await page.click("#add-chapter-save");
    await expect.poll(() => state.calls.chapterAdd).toBe(1);

    await page.locator("#screen-reader .back-btn").click();
    await expect(page.locator("#chapters-list .chapter-item")).toHaveCount(3);
    await page.locator('#chapters-list [data-move-chapter="up"][data-chapter-idx="2"]').click();
    await expect.poll(() => state.calls.sortPut).toBe(1);
  });

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
    await page.click("#comment-form .comment-send-btn");
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
    await expect(page.locator("#screen-chapters")).toHaveClass(/admin-enabled/);

    await page.evaluate(() => {
      toggleAdminMode(false);
    });
    await expect(page.locator("#screen-chapters")).not.toHaveClass(/admin-enabled/);

    await page.evaluate(() => {
      toggleAdminMode(true);
    });
    await expect(page.locator("#screen-chapters")).toHaveClass(/admin-enabled/);

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

  test("reader search filters series and chapters", async ({ page }) => {
    const state = createMockState();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=search-a");
    await expect(page.locator("#reader-search-input")).toBeVisible();

    await page.fill("#reader-search-input", "Test Series");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);

    await page.fill("#reader-search-input", "nothing here");
    await expect(page.locator("#series-list .series-card")).toHaveCount(0);
    await expect(page.locator("#reader-search-empty")).toBeVisible();

    await page.fill("#reader-search-input", "");
    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#chapters-list .chapter-item")).toHaveCount(2);

    await page.fill("#reader-search-input", "Chapter 2");
    await expect(page.locator("#chapters-list .chapter-item")).toHaveCount(1);
    await expect(page.locator("#chapters-list .chapter-item").first()).toContainText("Chapter 2");
  });

  test("reader startup does not start background polling before reading", async ({ page }) => {
    const state = createMockState();
    await page.addInitScript(() => {
      const nativeSetInterval = window.setInterval.bind(window);
      window.__readerIntervalDelays = [];
      window.setInterval = (handler, delay, ...args) => {
        window.__readerIntervalDelays.push(Number(delay));
        return nativeSetInterval(handler, delay, ...args);
      };
    });
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=interval-audit");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);

    let delays = await page.evaluate(() => window.__readerIntervalDelays || []);
    expect(delays).not.toContain(1500);
    expect(delays).not.toContain(5000);

    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);

    delays = await page.evaluate(() => window.__readerIntervalDelays || []);
    expect(delays).toContain(5000);
  });

  test("chapter payload cache survives reload and renders before slow network refresh", async ({ page }) => {
    const state = createMockState();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=persistent-cache");
    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#reader-text")).toContainText("This is chapter one text");

    state.chapterContentDelayMs = 1000;
    await page.reload();
    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#reader-text")).toContainText("This is chapter one text", { timeout: 250 });
    await expect.poll(() => state.calls.chapterContent).toBeGreaterThan(1);
  });

  test("opening a chapter warms previous one and the next two chapters", async ({ page }) => {
    const state = createMockState();
    state.readerData.series[0].volumes[0].chapters.push(
      { chapter: "3", custom_name: "Chapter 3", text: "Third chapter text.", url: "" },
      { chapter: "4", custom_name: "Chapter 4", text: "Fourth chapter text.", url: "" }
    );
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=prefetch-window");
    await page.locator("#series-list .series-card").first().click();
    state.chapterContentRequests = [];
    await page.locator("#chapters-list .chapter-item").nth(1).click();

    await expect.poll(() => Array.from(new Set(state.chapterContentRequests)).sort()).toEqual([
      "manga_ru::1::1",
      "manga_ru::1::2",
      "manga_ru::1::3",
      "manga_ru::1::4",
    ]);
  });

  test("jumping chapters cancels delayed warmups from the previous chapter", async ({ page }) => {
    const state = createMockState();
    state.readerData.series[0].volumes[0].chapters.push(
      { chapter: "3", custom_name: "Chapter 3", text: "Third chapter text.", url: "" },
      { chapter: "4", custom_name: "Chapter 4", text: "Fourth chapter text.", url: "" }
    );
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=prefetch-cancel");
    await page.evaluate(() => {
      const originalWarmChapterPayloadByIndex = window.warmChapterPayloadByIndex;
      window.__warmChapterIndexes = [];
      window.warmChapterPayloadByIndex = (idx, options) => {
        window.__warmChapterIndexes.push(idx);
        return originalWarmChapterPayloadByIndex(idx, options);
      };
    });
    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await page.waitForTimeout(230);

    state.chapterContentRequests = [];
    await page.evaluate(() => {
      window.__warmChapterIndexes = [];
    });
    await page.evaluate(() => openChapter(3));
    await expect(page.locator("#reader-text")).toContainText("Fourth chapter text.");
    await page.waitForTimeout(500);

    const warmedIndexes = await page.evaluate(() => window.__warmChapterIndexes);
    expect(warmedIndexes).not.toContain(1);
    expect(state.chapterContentRequests).not.toContain("manga_ru::1::2");
  });

  test("admin bulk upload preview validates before publishing", async ({ page }) => {
    const state = createMockState();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=bulk-preview");
    await page.evaluate(() => toggleAdminMode(true));
    await page.locator("#series-list .series-card").first().click();
    await page.click(".admin-bulk-btn");
    await page.fill("#bulk-upload-input", "https://example.org/chapter-3\nbad-url");

    await page.click("#bulk-upload-preview");
    await expect.poll(() => state.calls.chapterBulkPreview).toBe(1);
    await expect(page.locator(".bulk-preview-row")).toHaveCount(2);
    await expect(page.locator("#bulk-upload-preview-panel")).toContainText("Глава 3");
    await expect(page.locator("#bulk-upload-preview-panel")).toContainText("невалидная ссылка");
    expect(state.calls.chapterBulk).toBe(0);

    await page.fill("#bulk-upload-input", "https://example.org/chapter-3\nhttps://example.org/chapter-4");
    await page.click("#bulk-upload-preview");
    await expect.poll(() => state.calls.chapterBulkPreview).toBe(2);
    await page.click("#bulk-upload-save");
    await expect.poll(() => state.calls.chapterBulk).toBe(1);
  });

  test("mobile flow: keeps series selection stable and handles teletype image chapters", async ({ browser }) => {
    const state = createMobileSelectionState();
    const context = await browser.newContext({
      viewport: { width: 393, height: 852 },
      userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 7)",
    });
    const page = await context.newPage();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=mobile-a");
    await expect(page.locator("#series-list .series-card")).toHaveCount(3);

    await expect(page.locator("#continue-reading-container")).toBeVisible();
    await page.locator("#continue-reading-container .continue-reading-card").click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await expect(page.locator("#chapter-title-header")).toContainText("2");
    await expect(page.locator("#reader-text")).toContainText("Воительница Аля");

    await page.locator("#screen-reader .back-btn").click();
    await page.locator("#screen-chapters .back-btn").click();
    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#chapters-title")).toHaveText("Хроники Акаши");
    await page.locator("#screen-chapters .back-btn").click();

    await page.locator("#series-list .series-card").nth(1).click();
    await expect(page.locator("#chapters-title")).toHaveText("Воительница Аля");
    await expect(page.locator("#chapters-list .chapter-item")).toHaveCount(2);
    await expect(page.locator("#chapters-list .chapter-item").first()).toContainText("Часть 1");

    await page.locator("#screen-chapters .back-btn").click();
    await page.locator("#series-list .series-card").nth(2).click();
    await expect(page.locator("#chapters-title")).toHaveText("Аля иногда... Манга");

    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await expect(page.locator("#reader-text img")).toHaveCount(1);
    const imageWidthBeforeTextNarrow = await page.locator("#reader-text img").first().evaluate((img) => img.getBoundingClientRect().width);
    await page.evaluate(() => {
      setTextWidth(50);
    });
    await expect
      .poll(() => page.locator("#reader-text img").first().evaluate((img) => img.getBoundingClientRect().width))
      .toBeGreaterThanOrEqual(imageWidthBeforeTextNarrow - 2);
    await expect(page.locator("#reader-text")).not.toContainText("Не удалось загрузить главу");

    await page.locator("#screen-reader .back-btn").click();
    await expect(page.locator("#screen-chapters")).toHaveClass(/active/);
    await page.locator("#chapters-list .chapter-item").nth(1).click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await expect(page.locator("#reader-text")).toContainText("Не удалось загрузить главу");
    await expect(page.locator("#reader-text .state-action-btn")).toHaveText("Открыть источник");

    await page.locator("#screen-reader .back-btn").click();
    await expect(page.locator("#screen-chapters")).toHaveClass(/active/);
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#reader-text img")).toHaveCount(1);

    await context.close();
  });

  test("tablet settings: restores an over-dark dimmer to a safe value", async ({ browser }) => {
    const state = createMockState();
    const context = await browser.newContext({
      viewport: { width: 834, height: 1112 },
      userAgent: "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    });
    const page = await context.newPage();
    await installTelegramAndApiMocks(page, state);
    await page.addInitScript(() => {
      localStorage.setItem("reader_settings", JSON.stringify({ theme: "light", dimmerValue: 85 }));
    });

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=tablet-dimmer");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);
    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);

    const dimmerState = await page.evaluate(() => ({
      value: settings.dimmerValue,
      inputMax: document.getElementById("input-dimmerValue")?.getAttribute("max"),
      overlay: getComputedStyle(document.getElementById("dimmer-overlay")).backgroundColor,
    }));

    expect(dimmerState.value).toBeLessThanOrEqual(45);
    expect(dimmerState.inputMax).toBe("45");
    expect(dimmerState.overlay).not.toBe("rgba(0, 0, 0, 0.85)");

    await page.evaluate(() => toggleSettings());
    await expect(page.locator("#settings-panel")).not.toHaveClass(/hidden/);
    await expect(page.locator("#label-dimmerValue")).toHaveText("45%");
    await expect(page.locator("#input-dimmerValue")).toHaveValue("45");

    await context.close();
  });

  test("reader chrome uses a single progress bar and one immersive state", async ({ page }) => {
    const state = createMockState();
    state.readerData.series[0].volumes[0].chapters[0].text = Array.from(
      { length: 80 },
      (_, idx) => `Long reader paragraph ${idx + 1} for scroll state verification.`
    ).join("\n\n");
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=chrome-state");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);
    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);

    await expect(page.locator(".reading-progress-bar")).toHaveCount(1);

    await page.locator("#reader-content").evaluate((el) => {
      el.scrollTop = el.scrollHeight;
      el.dispatchEvent(new Event("scroll", { bubbles: true }));
    });

    await expect(page.locator("#screen-reader")).toHaveClass(/immersive/);
    await expect(page.locator("#reader-top-bar")).not.toHaveClass(/bars-hidden|bar-hidden|header-hidden/);
    await expect(page.locator("#reader-bottom-bar")).not.toHaveClass(/bars-hidden|bar-hidden/);
    await expect
      .poll(() => page.locator("#reader-scrubber").evaluate((el) => Number(el.value)))
      .toBeGreaterThan(0);
  });

  test("settings can hide progress and chapter header without blocking close", async ({ page }) => {
    const state = createMockState();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=compact-settings");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);
    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);

    await page.evaluate(() => toggleSettings());
    await expect(page.locator("#settings-panel")).not.toHaveClass(/hidden/);
    await expect(page.locator('label[for="hide-progress-toggle"]')).toBeVisible();
    await expect(page.locator('label[for="hide-chapter-header-toggle"]')).toBeVisible();
    await expect(page.locator(".close-settings-btn")).toBeInViewport();

    await page.locator('label[for="hide-progress-toggle"]').click();
    await page.locator('label[for="hide-chapter-header-toggle"]').click();
    await page.click(".close-settings-btn");

    await expect(page.locator("#settings-panel")).toHaveClass(/hidden/);
    await expect(page.locator("#reading-progress-container")).toBeHidden();
    await expect(page.locator("#chapter-title-header")).toBeHidden();
    await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("reader_settings") || "{}"))).toMatchObject({
      hideProgress: true,
      hideChapterHeader: true,
    });
  });

  test("library screen covers global search chrome behind translucent headers", async ({ page }) => {
    const state = createMockState();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=library-cover");
    await page.locator("#tab-library").click();
    await expect(page.locator("#screen-library")).toHaveClass(/active/);
    await expect(page.locator("#reader-search-panel")).toHaveClass(/hidden/);

    const screenBackgroundAlpha = await page.evaluate(() => {
      const screen = document.getElementById("screen-library");
      const panel = document.getElementById("reader-search-panel");
      panel?.classList.remove("hidden");
      const bg = getComputedStyle(screen).backgroundColor;
      const match = bg.match(/rgba?\(([^)]+)\)/);
      if (!match) return 0;
      const parts = match[1].split(",").map((part) => Number.parseFloat(part.trim()));
      return parts.length >= 4 ? parts[3] : 1;
    });
    expect(screenBackgroundAlpha).toBe(1);
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

  test("chapters screen warms likely chapter and reader reuses cached payload while revalidating", async ({ page }) => {
    const state = createMockState();
    state.readerData.series[0].volumes[0].chapters = [
      {
        chapter: "1",
        custom_name: "Warm Me Up",
        text: "Prefetched chapter body for cache reuse verification.",
        url: "",
      },
    ];
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=warm-cache");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);
    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#screen-chapters")).toHaveClass(/active/);

    await expect.poll(() => state.calls.chapterContent).toBe(1);
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await expect(page.locator("#reader-text")).toContainText("Prefetched chapter body");
    await page.waitForTimeout(250);
    await expect.poll(() => state.calls.chapterContent).toBeGreaterThanOrEqual(2);
  });

  test("admin persist: toggle survives reload and FAB appears in reader", async ({ page }) => {
    const state = createMockState();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=persist-a");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);

    // Enable admin-mode then open the reader — FAB must be visible without reload.
    await page.evaluate(() => toggleAdminMode(true));
    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);
    await expect(page.locator("#admin-fab-container")).toBeVisible();
    await expect(page.locator(".admin-mode-badge")).toBeVisible();

    // Persist across reload.
    await page.reload();
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);
    const persisted = await page.evaluate(() => ({
      stored: localStorage.getItem("reader_admin_mode"),
      isAdmin: isAdminMode,
    }));
    expect(persisted.stored).toBe("1");
    expect(persisted.isAdmin).toBe(true);
  });

  test("admin add chapter flow", async ({ page }) => {
    const state = createMockState();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=add-a");
    await page.evaluate(() => toggleAdminMode(true));
    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);

    await page.evaluate(() => openAddChapterModal());
    await expect(page.locator("#add-chapter-modal")).not.toHaveClass(/hidden/);
    await expect(page.locator("#add-chapter-number")).toHaveValue("3");

    await page.fill("#add-chapter-url", "https://example.org/added-chapter");
    await page.fill("#add-chapter-name", "E2E added chapter");
    await page.click("#add-chapter-save");

    await expect.poll(() => state.calls.chapterAdd).toBe(1);
    await expect.poll(() => {
      const v = findVolume(state, "manga_ru", 1);
      return v ? v.chapters.length : 0;
    }).toBe(3);
  });

  test("admin delete chapter flow", async ({ page }) => {
    const state = createMockState();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=del-a");
    await page.evaluate(() => toggleAdminMode(true));
    await page.locator("#series-list .series-card").first().click();
    await page.locator("#chapters-list .chapter-item").first().click();
    await expect(page.locator("#screen-reader")).toHaveClass(/active/);

    await page.evaluate(() => deleteChapterCurrent());

    await expect.poll(() => state.calls.chapterDelete).toBe(1);
    await expect.poll(() => {
      const v = findVolume(state, "manga_ru", 1);
      return v ? v.chapters.length : 0;
    }).toBe(1);
    await expect(page.locator("#screen-chapters")).toHaveClass(/active/);
  });

  test("admin cover edit flow", async ({ page }) => {
    const state = createMockState();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=cover-a");
    await page.evaluate(() => toggleAdminMode(true));

    await page.evaluate(() => openCoverEditModal("manga_ru"));
    await expect(page.locator("#cover-edit-modal")).not.toHaveClass(/hidden/);

    await page.fill("#cover-edit-input", "https://example.org/cover.png");
    await page.click("#cover-edit-save");

    await expect.poll(() => state.calls.seriesUpdate).toBe(1);
    await expect.poll(() => {
      const s = state.readerData.series.find((x) => x.id === "manga_ru");
      return s ? s.cover_url : "";
    }).toBe("https://example.org/cover.png");
  });

  test("admin move chapter: up/down buttons reorder and persist via /api/sort", async ({ page }) => {
    const state = createMockState();
    // Expand to 3 chapters so up/down has something to do.
    state.readerData.series[0].volumes[0].chapters.push({
      chapter: "3",
      custom_name: "Chapter 3",
      text: "Third chapter text.",
      url: "",
    });
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=move-a");
    await page.evaluate(() => toggleAdminMode(true));

    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#chapters-list .chapter-item")).toHaveCount(3);

    const names = async () =>
      page.$$eval("#chapters-list .chapter-item .chapter-name", (els) =>
        els.map((el) => (el.childNodes[0]?.textContent || "").trim())
      );

    expect(await names()).toEqual(["Chapter 1", "Chapter 2", "Chapter 3"]);

    // Click "down" on first chapter — should swap with second.
    await page.locator('#chapters-list [data-move-chapter="down"][data-chapter-idx="0"]').click();
    await expect.poll(() => state.calls.sortPut).toBe(1);
    expect(await names()).toEqual(["Chapter 2", "Chapter 1", "Chapter 3"]);

    // Click "up" on the chapter now at index 2 — should move it to index 1.
    await page.locator('#chapters-list [data-move-chapter="up"][data-chapter-idx="2"]').click();
    await expect.poll(() => state.calls.sortPut).toBe(2);
    expect(await names()).toEqual(["Chapter 2", "Chapter 3", "Chapter 1"]);

    // The "up" button on the first item must be disabled, and "down" on the last item must be disabled.
    await expect(page.locator('#chapters-list [data-move-chapter="up"][data-chapter-idx="0"]')).toBeDisabled();
    await expect(page.locator('#chapters-list [data-move-chapter="down"][data-chapter-idx="2"]')).toBeDisabled();
  });

  test("admin move chapter: 409 from /api/sort rolls back and explains missing DB chapter", async ({ page }) => {
    const state = createMockState();
    state.readerData.series[0].volumes[0].chapters.push({
      chapter: "Иллюстрации",
      custom_name: "Иллюстрации",
      text: "",
      url: "",
    });
    state.sortFailure = {
      status: 409,
      payload: {
        error: "Missing chapters in database",
        unmatched: ["Иллюстрации"],
      },
    };
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=move-conflict");
    await page.evaluate(() => toggleAdminMode(true));

    await page.locator("#series-list .series-card").first().click();
    await expect(page.locator("#chapters-list .chapter-item")).toHaveCount(3);

    const names = async () =>
      page.$$eval("#chapters-list .chapter-item .chapter-name", (els) =>
        els.map((el) => (el.childNodes[0]?.textContent || "").trim())
      );

    expect(await names()).toEqual(["Chapter 1", "Chapter 2", "Иллюстрации"]);

    await page.locator('#chapters-list [data-move-chapter="up"][data-chapter-idx="2"]').click();

    await expect.poll(() => state.calls.sortPut).toBe(1);
    await expect(page.locator(".toast").last()).toContainText("Порядок не сохранён: глава отсутствует в БД");
    await expect.poll(names).toEqual(["Chapter 1", "Chapter 2", "Иллюстрации"]);
    await expect(page.locator(".toast").last()).not.toContainText("Порядок сохранён");
  });

  test("series selection: chapters never bleed between different series", async ({ browser }) => {
    const state = createMobileSelectionState();
    const ctx = await browser.newContext({
      viewport: { width: 393, height: 852 },
      userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 7)",
    });
    const page = await ctx.newPage();
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=no-bleed");
    await expect(page.locator("#series-list .series-card")).toHaveCount(3);

    // Read chapters list text for current screen.
    const listNames = async () =>
      page.$$eval("#chapters-list .chapter-item .chapter-name", (els) =>
        els.map((el) => (el.childNodes[0]?.textContent || "").trim())
      );

    // Open akashic, then rapidly go back and open alya.
    await page.locator('.series-card[data-series-id="akashic_records"]').click();
    await expect(page.locator("#chapters-title")).toHaveText("Хроники Акаши");
    await page.locator("#screen-chapters .back-btn").click();
    await page.locator('.series-card[data-series-id="ranobe_alya"]').click();
    await expect(page.locator("#chapters-title")).toHaveText("Воительница Аля");
    await expect(page.locator("#chapters-list .chapter-item")).toHaveCount(2);
    expect(await listNames()).toEqual(["Часть 1", "Часть 2"]);

    // Rapid synchronous switch via evaluate.
    await page.evaluate(() => {
      document.querySelector("#screen-chapters .back-btn").click();
      document.querySelector('.series-card[data-series-id="akashic_records"]').click();
      document.querySelector("#screen-chapters .back-btn").click();
      document.querySelector('.series-card[data-series-id="manga_ru"]').click();
    });
    await expect(page.locator("#chapters-title")).toHaveText("Аля иногда... Манга");
    const mangaNames = await listNames();
    expect(mangaNames, "manga chapters should not include akashic/alya names").not.toContain("Глава 1");
    expect(mangaNames).toContain("Глава 75");

    // Simulate stale `currentSeries` object ref (as if background refresh swapped allData).
    // After this, any selectSeries should still produce the correct list for the new series.
    await page.evaluate(() => {
      // Re-parse allData to force new object identity for currentSeries
      const cloned = JSON.parse(JSON.stringify(allData));
      allData = cloned;
    });
    await page.locator("#screen-chapters .back-btn").click();
    await page.locator('.series-card[data-series-id="ranobe_alya"]').click();
    await expect(page.locator("#chapters-title")).toHaveText("Воительница Аля");
    expect(await listNames()).toEqual(["Часть 1", "Часть 2"]);

    await ctx.close();
  });

  test("non-admin cannot enable editor mode", async ({ page }) => {
    const state = createMockState();
    state.readerData.admin_ids = []; // strip admin rights
    await installTelegramAndApiMocks(page, state);

    await page.goto("/reader.html?api=http://127.0.0.1:4173&rev=nonadmin-a");
    await expect(page.locator("#series-list .series-card")).toHaveCount(1);

    await page.evaluate(() => toggleAdminMode(true));
    const result = await page.evaluate(() => ({
      isAdmin: isAdminMode,
      stored: localStorage.getItem("reader_admin_mode"),
    }));
    expect(result.isAdmin).toBe(false);
    expect(result.stored).toBeNull();
  });
});
