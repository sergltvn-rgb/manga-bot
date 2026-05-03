// Ranobe Radar 2026 — движок сайта: рендер каталога, фильтры, графики, модалка.
// Зависит от data.js (TITLES, PLATFORMS, TAG_COLORS, CONTENT_RATING_LABEL, BADGE_LABEL)
// и глобального Chart (UMD).

(() => {
  'use strict';

  // =============================================
  // State
  // =============================================
  const state = {
    filters: {
      platform: 'all',
      language: 'all',
      rating: 'all',
      priority: 'all',
      scout: 'all',
      source: 'all',
      genre: 'all',
      length: 'all',
    },
    sort: 'priority',
  };

  // =============================================
  // Utilities
  // =============================================
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const fmtNumber = (n) => n.toLocaleString('ru-RU');

  const fmtWords = (w) => {
    if (!w) return '—';
    if (w >= 1_000_000) return (w / 1_000_000).toFixed(2).replace('.', ',') + ' млн';
    if (w >= 1_000) return Math.round(w / 1_000) + 'k';
    return String(w);
  };

  const fmtChapters = (title) => {
    if (['jnovel', 'yenpress', 'sevenseas', 'crossinf', 'tentai'].includes(title.platform)) {
      return title.chapters + (title.chapters === 1 ? ' том' : ' тома');
    }
    return title.chapters + ' гл.';
  };

  const escape = (str) =>
    String(str).replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));

  // Процедурная обложка — детерминированный градиент от строки
  const hash = (str) => {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (h << 5) - h + str.charCodeAt(i);
    return Math.abs(h);
  };

  const PALETTES = [
    ['#ff5fa2', '#8b5cf6'],
    ['#22d3ee', '#8b5cf6'],
    ['#f59e0b', '#ef4444'],
    ['#8b5cf6', '#22d3ee'],
    ['#ec4899', '#f59e0b'],
    ['#0ea5e9', '#a855f7'],
    ['#10b981', '#22d3ee'],
    ['#f472b6', '#8b5cf6'],
    ['#facc15', '#ec4899'],
    ['#6366f1', '#ff5fa2'],
  ];

  const coverGradient = (title) => {
    const [a, b] = PALETTES[hash(title.id) % PALETTES.length];
    const angle = (hash(title.id) % 360) + 15;
    return `background: linear-gradient(${angle}deg, ${a}, ${b});`;
  };

  const kanaPreview = (title) => {
    // Короткий фрагмент оригинала: для JP берём первые иероглифы, для EN — заглавные
    if (title.language === 'ja') {
      return (title.title_original || '').slice(0, 10);
    }
    return (title.title_original || '').slice(0, 24);
  };

  const motifFor = (title) => (typeof COVER_MOTIFS !== 'undefined' && COVER_MOTIFS[title.id]) || '📖';
  const coverUrlFor = (title) => (typeof COVER_URLS !== 'undefined' ? COVER_URLS[title.id] : null) || null;
  const isBookCoverUrl = (url) =>
    /assets\/covers\/|cdn\.j-novel\.club|images\.yenpress\.com|images1\.penguinrandomhouse\.com|images\.ranobedb\.org|crossinfworld\.com|sevenseasentertainment\.com|dynamic\.indigoimages\.ca|royalroadcdn\.com|cdn\.scribblehub\.com|images\.isbndb\.com|cdn\.kdkw\.jp|cdn-ak\.f\.st-hatena\.com|media\.oceanofpdf\.com/.test(url || '');
  const isWideCoverUrl = (url) => /cdn-static\.kakuyomu\.jp|sbo\.syosetu\.com/.test(url || '');
  const joinList = (value) => (Array.isArray(value) ? value.filter(Boolean).join('; ') : value || '—');
  const creatorLineFor = (title) =>
    title.illustrator ? `${title.author || '—'} · илл. ${title.illustrator}` : title.author || '—';
  const scoutMetaFor = (status) =>
    ({
      not_found: { label: 'Свободно', tone: 'open' },
      en_agg: { label: 'Английский есть', tone: 'en' },
      ru_partial: { label: 'RU частично', tone: 'partial' },
      ru_full: { label: 'RU закрыто', tone: 'closed' },
    }[status] || { label: 'Не проверено', tone: 'unknown' });
  const scoutSourcesFor = (title) =>
    Array.isArray(title.translation_scout?.sources) ? title.translation_scout.sources : [];
  const hasScoutResource = (title, resource) =>
    scoutSourcesFor(title).some((item) => String(item.resource || '').toLowerCase() === resource.toLowerCase());
  const hasPdfEpubMirror = (title) =>
    scoutSourcesFor(title).some((item) => /pdf|epub|oceanofpdf|jnovels/i.test(`${item.resource || ''} ${item.amount || ''} ${item.note || ''}`));
  const ruCheckFor = (title) => {
    const scout = title.translation_scout;
    if (!scout) return 'разведка переводов не заполнена';
    if (scout.status === 'not_found') return 'RU-перевод не найден; ниша выглядит свободной';
    if (scout.status === 'en_agg') return 'RU-перевод не найден; EN/агрегаторный след есть';
    if (scout.status === 'ru_partial') return 'частичный русский перевод найден, нужен ручной контроль дубля';
    if (scout.status === 'ru_full') return 'русский перевод уже почти/полностью закрывает тайтл';
    return scout.recommendation || 'статус перевода проверен';
  };

  const ranobeLibDataFor = (title) => {
    const r = title.ranobelib || {};
    return {
      title: r.title || title.title_ru,
      alt_titles: r.alt_titles || [title.title_original, title.title_romaji].filter(Boolean),
      author: title.author || '—',
      illustrator: title.illustrator || '—',
      imprint: joinList([title.publisher, title.jp_publisher].filter(Boolean)),
      status: r.status || `${fmtChapters(title)}, ${title.status}`,
      genres: r.genres || title.tags || [],
      age: CONTENT_RATING_LABEL[title.content_rating] || title.content_rating,
      translation_start: title.translation_start || (title.language === 'ja' ? 'Kakuyomu/Narou, 1話' : 'том 1 / глава 1'),
      description: r.description || title.synopsis,
      ru_check: r.ru_check || ruCheckFor(title),
    };
  };

  const ranobeLibTextFor = (title) => {
    const data = ranobeLibDataFor(title);
    return [
      `Название: ${data.title}`,
      `Альт. названия: ${joinList(data.alt_titles)}`,
      `Автор: ${data.author}`,
      `Иллюстратор: ${data.illustrator}`,
      `Издатель / импринт: ${data.imprint}`,
      `Статус: ${data.status}`,
      `Жанры: ${joinList(data.genres)}`,
      `Возраст: ${data.age}`,
      `Старт перевода: ${data.translation_start}`,
      `Проверка RU: ${data.ru_check}`,
      '',
      data.description,
    ].join('\n');
  };

  const ranobeLibBlock = (title) => {
    const r = ranobeLibDataFor(title);
    const rows = [
      ['Название', r.title || title.title_ru],
      ['Альт. названия', joinList(r.alt_titles)],
      ['Автор / иллюстратор', `${r.author} / ${r.illustrator}`],
      ['Издатель / импринт', r.imprint],
      ['Статус', r.status],
      ['Жанры', joinList(r.genres)],
      ['Возраст', r.age],
      ['Старт перевода', r.translation_start],
    ];
    const rowsHTML = rows
      .map(
        ([label, value]) => `
          <div class="glass rounded-xl p-3">
            <div class="text-[10px] uppercase tracking-widest text-[var(--text-dim)] mb-1">${escape(label)}</div>
            <div class="text-sm text-[var(--text-muted)]">${escape(value)}</div>
          </div>`
      )
      .join('');
    return `
      <div class="mt-5 glass rounded-2xl p-4">
        <div class="flex items-center justify-between gap-3 mb-3">
          <div class="text-xs uppercase tracking-widest text-[var(--text-dim)]">Для карточки на RanobeLib</div>
          <button class="btn !py-1.5 !px-3 text-[11px]" data-copy-ranobelib="${escape(title.id)}">Копировать</button>
        </div>
        <div class="grid md:grid-cols-2 gap-3">${rowsHTML}</div>
        <div class="mt-3 text-sm text-[var(--text-muted)] leading-relaxed">${escape(r.description)}</div>
        <div class="mt-3 text-xs text-[var(--text-dim)]">Проверка RU: ${escape(r.ru_check)}</div>
      </div>`;
  };

  const freeAccessBlock = (title) => {
    const items = Array.isArray(title.free_access) ? title.free_access.filter((item) => item && item.url) : [];
    if (!items.length) return '';
    const itemsHTML = items
      .map(
        (item) => `
          <a target="_blank" rel="noopener" href="${escape(item.url)}" class="glass rounded-xl p-4 hover:border-[var(--line-strong)] transition-colors block">
            <div class="text-xs uppercase tracking-widest text-[var(--text-dim)] mb-1">${escape(item.type || 'free')}</div>
            <div class="font-display text-base mb-1">${escape(item.label)}</div>
            <div class="text-sm text-[var(--text-muted)] leading-relaxed">${escape(item.note || '')}</div>
          </a>`
      )
      .join('');
    return `
      <div class="mt-5 glass rounded-2xl p-4">
        <div class="text-xs uppercase tracking-widest text-[var(--text-dim)] mb-3">Где легально читать бесплатно</div>
        <div class="grid md:grid-cols-2 gap-3">${itemsHTML}</div>
      </div>`;
  };

  const translationScoutBlock = (title) => {
    const scout = title.translation_scout;
    const rows = Array.isArray(scout?.sources) ? scout.sources.filter((item) => item && item.resource) : [];
    if (!scout && !rows.length) return '';
    const statusLabel =
      {
        ru_full: 'RU: почти закрыто',
        ru_partial: 'RU: частично есть',
        en_agg: 'Английский: найдено на агрегаторах',
        not_found: 'Перевод не найден',
      }[scout.status] || scout.status || 'Проверено';
    const rowsHTML = rows
      .map(
        (item) => `
          <div class="glass rounded-xl p-3">
            <div class="text-[10px] uppercase tracking-widest text-[var(--text-dim)] mb-1">${escape(item.scope || 'источник')}</div>
            <div class="font-display text-sm mb-1">${escape(item.resource)}</div>
            <div class="text-sm text-[var(--text-muted)] leading-relaxed">${escape(item.amount || 'объём не указан')}</div>
            ${item.note ? `<div class="mt-1 text-xs text-[var(--text-dim)] leading-relaxed">${escape(item.note)}</div>` : ''}
          </div>`
      )
      .join('');
    return `
      <div class="mt-5 glass rounded-2xl p-4">
        <div class="flex items-start justify-between gap-3 mb-3">
          <div>
            <div class="text-xs uppercase tracking-widest text-[var(--text-dim)] mb-1">Разведка переводов</div>
            <div class="font-display text-lg">${escape(statusLabel)}</div>
          </div>
          <div class="text-right text-sm text-[var(--text-muted)]">${escape(scout.recommendation || '')}</div>
        </div>
        ${rowsHTML ? `<div class="grid md:grid-cols-2 gap-3">${rowsHTML}</div>` : ''}
        ${scout.checked ? `<div class="mt-3 text-xs text-[var(--text-dim)]">Проверено: ${escape(scout.checked)}</div>` : ''}
      </div>`;
  };

  // =============================================
  // Рендер: панель фильтров по платформам
  // =============================================
  const buildPlatformFilter = () => {
    const group = $('[data-filter-group="platform"]');
    const btns = [
      { value: 'all', label: 'Все платформы', color: null },
      ...Object.values(PLATFORMS).map((p) => ({
        value: p.id,
        label: p.name,
        color: p.color,
      })),
    ];
    group.innerHTML = btns
      .map(
        (b) => `<button class="filter-btn ${b.value === 'all' ? 'active' : ''}" data-filter-value="${b.value}">
          ${b.color ? `<span class="inline-block w-2 h-2 rounded-full mr-1.5" style="background:${b.color}"></span>` : ''}
          ${escape(b.label)}
        </button>`
      )
      .join('');
  };

  const buildGenreFilter = () => {
    const group = $('[data-filter-group="genre"]');
    if (!group) return;
    const counts = new Map();
    TITLES.forEach((title) => (title.tags || []).forEach((tag) => counts.set(tag, (counts.get(tag) || 0) + 1)));
    const genres = [...counts.entries()]
      .filter(([, count]) => count >= 2)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'ru'))
      .slice(0, 28);
    group.innerHTML = [
      `<button class="filter-btn active" data-filter-value="all">Все жанры</button>`,
      ...genres.map(([tag, count]) => {
        const c = TAG_COLORS[tag];
        return `<button class="filter-btn" data-filter-value="${escape(tag)}" ${c ? `style="--tag-color:${c}"` : ''}>${escape(tag)} <span class="text-[var(--text-dim)]">${count}</span></button>`;
      }),
    ].join('');
  };

  // =============================================
  // Рендер: каталог карточек
  // =============================================
  const passesFilter = (t) => {
    const f = state.filters;
    if (f.platform !== 'all' && t.platform !== f.platform) return false;
    if (f.language !== 'all' && t.language !== f.language) return false;
    if (f.rating === 'safe' && t.content_rating === 'adult') return false;
    if (f.rating === 'adult' && t.content_rating !== 'adult') return false;
    if (f.priority === 'must' && !t.must_translate_rank) return false;
    if (f.priority === 'high' && t.priority_score < 70) return false;
    if (f.priority === 'mid' && (t.priority_score < 50 || t.priority_score >= 70)) return false;
    if (f.priority === 'low' && t.priority_score >= 50) return false;
    if (f.scout !== 'all' && t.translation_scout?.status !== f.scout) return false;
    if (f.source === 'pdf_epub' && !hasPdfEpubMirror(t)) return false;
    if (f.source === 'ocean' && !hasScoutResource(t, 'OceanOfPDF')) return false;
    if (f.genre !== 'all' && !(t.tags || []).includes(f.genre)) return false;
    if (f.length === 'short' && t.words > 100000) return false;
    if (f.length === 'medium' && (t.words <= 100000 || t.words > 300000)) return false;
    if (f.length === 'long' && (t.words <= 300000 || t.words > 700000)) return false;
    if (f.length === 'mega' && t.words <= 700000) return false;
    return true;
  };

  const sortTitles = (arr) => {
    const s = state.sort;
    const cloned = [...arr];
    cloned.sort((a, b) => {
      if (s === 'priority') return b.priority_score - a.priority_score;
      if (s === 'words') return b.words - a.words;
      if (s === 'chapters') return b.chapters - a.chapters;
      if (s === 'year') return b.year_start - a.year_start;
      if (s === 'alpha') return a.title_ru.localeCompare(b.title_ru, 'ru');
      return 0;
    });
    return cloned;
  };

  const cardHTML = (t) => {
    const p = PLATFORMS[t.platform];
    const badge = t.badge && BADGE_LABEL[t.badge] ? BADGE_LABEL[t.badge] : null;
    const isMust = !!t.must_translate_rank;
    const rating = CONTENT_RATING_LABEL[t.content_rating] || '';
    const isAdult = t.content_rating === 'adult';
    const scout = scoutMetaFor(t.translation_scout?.status);
    const hasMirror = hasPdfEpubMirror(t);
    const tagsHTML = (t.tags || [])
      .slice(0, 4)
      .map((tag) => {
        const c = TAG_COLORS[tag];
        return `<span class="chip" ${c ? `style="color:${c}80;border-color:${c}35"` : ''}>${escape(tag)}</span>`;
      })
      .join('');

    const coverUrl = coverUrlFor(t);
    const coverImgClass = isBookCoverUrl(coverUrl)
      ? 'cover-img book-cover-img'
      : isWideCoverUrl(coverUrl)
        ? 'cover-img wide-cover-img'
        : 'cover-img';
    const motif = motifFor(t);
    return `
      <article class="card glass rounded-3xl overflow-hidden flex flex-col fade-in" data-id="${t.id}">
        <div class="card-glow"></div>
        <div class="card-cover ${coverUrl ? 'has-cover' : 'generated-cover'}" style="${coverGradient(t)}">
          <div class="cover-motif">${motif}</div>
          ${
            coverUrl
              ? `<img class="${coverImgClass}" src="${escape(coverUrl)}" alt="${escape(t.title_ru)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.classList.remove('has-cover'); this.parentElement.classList.add('generated-cover'); this.remove();">`
              : ''
          }
          <div class="cover-overlay"></div>
          ${isMust ? `<span class="chip-priority">#${t.must_translate_rank} Must</span>` : ''}
          ${
            badge
              ? `<span class="chip-badge" style="color:${badge.color}">${escape(badge.text)}</span>`
              : ''
          }
          <span class="chip-scout chip-scout-${escape(scout.tone)}">${escape(scout.label)}</span>
          ${hasMirror ? '<span class="chip-source">PDF/EPUB</span>' : ''}
          <div class="cover-text">
            <div class="card-cover-title">${escape(t.title_ru)}</div>
            <div class="card-cover-kana ${t.language === 'ja' ? 'font-jp' : ''}">${escape(kanaPreview(t))}</div>
          </div>
          <span class="card-cover-platform" style="color:${p.color}">${escape(p.name)}</span>
        </div>
        <div class="p-5 flex-1 flex flex-col">
          <div class="flex items-center gap-2 text-[11px] uppercase tracking-widest text-[var(--text-dim)] mb-2">
            <span>${escape(p.country)}</span>
            <span>·</span>
            <span>${escape(creatorLineFor(t))}</span>
          </div>
          <h3 class="font-display text-[17px] leading-tight mb-1">${escape(t.title_ru)}</h3>
          <div class="text-[12px] text-[var(--text-muted)] ${t.language === 'ja' ? 'font-jp' : ''} line-clamp-1 mb-3">${escape(t.title_original || '')}</div>

          <div class="flex items-center gap-3 text-[12px] text-[var(--text-muted)] mb-3">
            <span>📖 ${escape(fmtChapters(t))}</span>
            <span>·</span>
            <span>✍ ${fmtWords(t.words)}</span>
            <span>·</span>
            <span>${isAdult ? '🔞' : '🟢'} ${escape(rating)}</span>
          </div>

          <div class="flex flex-wrap gap-1.5 mb-4">${tagsHTML}</div>

          <div class="mt-auto">
            <div class="flex items-center justify-between text-[11px] text-[var(--text-muted)] mb-1.5">
              <span>Приоритет перевода</span>
              <span class="font-display text-white">${t.priority_score}<span class="text-[var(--text-dim)]">/100</span></span>
            </div>
            <div class="priority-bar">
              <div class="priority-bar-fill" style="width:${t.priority_score}%"></div>
            </div>
          </div>

          <button class="btn mt-4 justify-center text-[12px] w-full" data-open-modal="${t.id}">Подробнее →</button>
        </div>
      </article>
    `;
  };

  const renderCatalog = () => {
    const grid = $('#catalog-grid');
    const counter = $('#catalog-counter');
    const empty = $('#catalog-empty');

    const filtered = sortTitles(TITLES.filter(passesFilter));
    counter.textContent = `Показано: ${filtered.length} из ${TITLES.length}`;

    if (filtered.length === 0) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');
    grid.innerHTML = filtered.map(cardHTML).join('');
  };

  // =============================================
  // Рендер: Must-Translate топ-5
  // =============================================
  const renderMust = () => {
    const grid = $('#must-grid');
    const items = TITLES.filter((t) => t.must_translate_rank).sort(
      (a, b) => a.must_translate_rank - b.must_translate_rank
    );
    grid.innerHTML = items
      .map((t) => {
        const p = PLATFORMS[t.platform];
        const reasons = (t.must_translate_reasoning || [])
          .map((r) => `<li class="flex gap-2"><span class="text-pink-500 mt-0.5">◆</span><span>${escape(r)}</span></li>`)
          .join('');
        return `
        <article class="must-card p-7 md:p-8 flex flex-col gap-5">
          <div class="flex items-start justify-between">
            <div class="must-rank">#${t.must_translate_rank}</div>
            <div class="text-right">
              <div class="text-[11px] uppercase tracking-widest text-[var(--text-dim)] mb-1">Индекс</div>
              <div class="font-display text-3xl gradient-text">${t.priority_score}</div>
            </div>
          </div>
          <div>
            <div class="text-[11px] uppercase tracking-widest text-[var(--text-dim)] mb-1.5 flex items-center gap-2">
              <span class="inline-block w-2 h-2 rounded-full" style="background:${p.color}"></span>
              ${escape(p.name)} · ${escape(p.country)}
            </div>
            <h3 class="font-display text-2xl md:text-[26px] leading-tight mb-1.5">${escape(t.title_ru)}</h3>
            <div class="text-sm text-[var(--text-muted)] ${t.language === 'ja' ? 'font-jp' : ''}">${escape(t.title_original || '')}</div>
            <div class="text-xs text-[var(--text-dim)] mt-1">${escape(t.author || '')}</div>
          </div>
          <p class="text-sm text-[var(--text-muted)] leading-relaxed">${escape(t.synopsis)}</p>
          <ul class="text-sm space-y-2 text-[var(--text-muted)]">${reasons}</ul>
          <div class="pt-4 border-t border-[var(--line)] flex flex-wrap items-center gap-3 justify-between">
            <div class="flex gap-4 text-xs text-[var(--text-muted)]">
              <span>📖 ${escape(fmtChapters(t))}</span>
              <span>✍ ${fmtWords(t.words)}</span>
              <span>🕐 ${escape(t.last_updated || '')}</span>
            </div>
            <a target="_blank" rel="noopener" href="${escape(t.url)}" class="btn btn-primary !py-1.5 !px-3 text-xs">Открыть оригинал ↗</a>
          </div>
        </article>
      `;
      })
      .join('');
  };

  // =============================================
  // Модалка
  // =============================================
  const openModal = (id) => {
    const t = TITLES.find((x) => x.id === id);
    if (!t) return;
    const p = PLATFORMS[t.platform];
    const tagsHTML = (t.tags || [])
      .map((tag) => {
        const c = TAG_COLORS[tag];
        return `<span class="chip chip-strong" ${c ? `style="color:${c};border-color:${c}40"` : ''}>${escape(tag)}</span>`;
      })
      .join('');
    const reasons =
      t.must_translate_reasoning && t.must_translate_reasoning.length
        ? `<div class="mt-5">
             <div class="text-xs uppercase tracking-widest text-[var(--text-dim)] mb-2">Почему в топ-5</div>
             <ul class="space-y-1.5 text-sm text-[var(--text-muted)]">
               ${t.must_translate_reasoning.map((r) => `<li class="flex gap-2"><span class="text-pink-500">◆</span><span>${escape(r)}</span></li>`).join('')}
             </ul>
           </div>`
        : '';

    const coverUrl = coverUrlFor(t);
    const modalCoverImgClass = isBookCoverUrl(coverUrl)
      ? 'modal-cover-img modal-book-cover-img'
      : isWideCoverUrl(coverUrl)
        ? 'modal-cover-img modal-wide-cover-img'
        : 'modal-cover-img';
    const motif = motifFor(t);
    const body = `
      <header class="relative modal-cover ${coverUrl ? 'has-cover' : 'generated-cover'}" style="${coverGradient(t)}">
        <div class="cover-motif modal-motif">${motif}</div>
        ${
          coverUrl
            ? `<img class="${modalCoverImgClass}" src="${escape(coverUrl)}" alt="${escape(t.title_ru)}" referrerpolicy="no-referrer" onerror="this.parentElement.classList.remove('has-cover'); this.parentElement.classList.add('generated-cover'); this.remove();">`
            : ''
        }
        <div class="modal-cover-overlay"></div>
        <button class="absolute top-4 right-4 w-9 h-9 rounded-full bg-black/70 hover:bg-black/90 flex items-center justify-center text-lg transition-colors z-10" data-close-modal>✕</button>
        ${t.must_translate_rank ? `<span class="chip-priority" style="top:16px;left:16px;z-index:10;">#${t.must_translate_rank} Must-Translate</span>` : ''}
      </header>
      <div class="p-6 md:p-8">
        <div class="text-[11px] uppercase tracking-widest text-[var(--text-dim)] mb-2 flex items-center gap-2">
          <span class="inline-block w-2 h-2 rounded-full" style="background:${p.color}"></span>
          ${escape(p.name)} · ${escape(p.country)} · ${escape(creatorLineFor(t))}
        </div>
        <h2 class="font-display text-2xl md:text-3xl mb-1 leading-tight">${escape(t.title_ru)}</h2>
        <div class="text-base text-[var(--text-muted)] ${t.language === 'ja' ? 'font-jp' : ''} mb-4">${escape(t.title_original || '')}${t.title_romaji ? ` <span class="text-[var(--text-dim)] text-sm">· ${escape(t.title_romaji)}</span>` : ''}</div>
        <div class="flex flex-wrap gap-2 mb-5">${tagsHTML}</div>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <div class="glass rounded-xl p-3">
            <div class="text-[10px] uppercase tracking-widest text-[var(--text-dim)]">Глав/томов</div>
            <div class="font-display text-lg mt-1">${escape(fmtChapters(t))}</div>
          </div>
          <div class="glass rounded-xl p-3">
            <div class="text-[10px] uppercase tracking-widest text-[var(--text-dim)]">Объём</div>
            <div class="font-display text-lg mt-1">${fmtWords(t.words)}</div>
          </div>
          <div class="glass rounded-xl p-3">
            <div class="text-[10px] uppercase tracking-widest text-[var(--text-dim)]">Старт / обновление</div>
            <div class="font-display text-lg mt-1">${t.year_start} <span class="text-[var(--text-dim)] text-xs">→ ${escape(t.last_updated || '')}</span></div>
          </div>
          <div class="glass rounded-xl p-3">
            <div class="text-[10px] uppercase tracking-widest text-[var(--text-dim)]">Приоритет</div>
            <div class="font-display text-lg mt-1 gradient-text">${t.priority_score}/100</div>
          </div>
        </div>

        <div class="text-sm leading-relaxed text-[var(--text-muted)] mb-5">${escape(t.synopsis)}</div>

        <div class="grid md:grid-cols-2 gap-4">
          <div class="glass rounded-xl p-4">
            <div class="text-xs uppercase tracking-widest text-[var(--text-dim)] mb-1.5">Почему нет на русском</div>
            <div class="text-sm text-[var(--text-muted)]">${escape(t.why_not_translated)}</div>
          </div>
          <div class="glass rounded-xl p-4">
            <div class="text-xs uppercase tracking-widest text-[var(--text-dim)] mb-1.5">Рейтинг и статус</div>
            <div class="text-sm text-[var(--text-muted)]">${escape(CONTENT_RATING_LABEL[t.content_rating] || '')} · ${t.status === 'ongoing' ? 'онгоинг' : t.status === 'completed' ? 'завершён' : 'завершён на web'}</div>
          </div>
        </div>

        ${reasons}
        ${translationScoutBlock(t)}
        ${freeAccessBlock(t)}
        ${ranobeLibBlock(t)}

        <div class="mt-6 flex flex-wrap gap-3">
          <a target="_blank" rel="noopener" href="${escape(t.url)}" class="btn btn-primary">Открыть оригинал ↗</a>
          <button class="btn" data-close-modal>Закрыть</button>
        </div>
      </div>
    `;
    $('#modal-content').innerHTML = body;
    const modal = $('#modal');
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
  };

  const closeModal = () => {
    const modal = $('#modal');
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  };

  // =============================================
  // События
  // =============================================
  const bindEvents = () => {
    // фильтры
    $$('.filter-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const group = btn.closest('[data-filter-group]');
        if (!group) return;
        const key = group.dataset.filterGroup;
        $$('.filter-btn', group).forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        state.filters[key] = btn.dataset.filterValue;
        renderCatalog();
      });
    });

    // сортировка
    $('#sort-select').addEventListener('change', (e) => {
      state.sort = e.target.value;
      renderCatalog();
    });

    // делегирование клика на кнопках «Подробнее»
    $('#catalog-grid').addEventListener('click', (e) => {
      const btn = e.target.closest('[data-open-modal]');
      if (btn) openModal(btn.dataset.openModal);
    });

    // модалка — закрытие
    $('#modal').addEventListener('click', (e) => {
      const copyBtn = e.target.closest('[data-copy-ranobelib]');
      if (copyBtn) {
        const title = TITLES.find((item) => item.id === copyBtn.dataset.copyRanobelib);
        if (!title) return;
        navigator.clipboard?.writeText(ranobeLibTextFor(title)).then(() => {
          copyBtn.textContent = 'Скопировано';
          setTimeout(() => {
            copyBtn.textContent = 'Копировать';
          }, 1200);
        });
        return;
      }
      if (e.target.matches('[data-close-modal]') || e.target.id === 'modal') {
        closeModal();
      }
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeModal();
    });

    // nav active
    const navLinks = $$('.nav-link');
    const sections = navLinks
      .map((l) => ({ link: l, el: document.querySelector(l.getAttribute('href')) }))
      .filter((s) => s.el);
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((en) => {
          if (en.isIntersecting) {
            const match = sections.find((s) => s.el === en.target);
            if (match) {
              navLinks.forEach((l) => l.classList.remove('active'));
              match.link.classList.add('active');
            }
          }
        });
      },
      { rootMargin: '-35% 0px -60% 0px', threshold: 0 }
    );
    sections.forEach((s) => io.observe(s.el));
  };

  // =============================================
  // KPI
  // =============================================
  const renderKPI = () => {
    const totalWords = TITLES.reduce((a, t) => a + (t.words || 0), 0);
    $('#kpi-titles').textContent = TITLES.length;
    $('#kpi-words').textContent = fmtWords(totalWords).replace(' ', '\u00A0');
    $('#kpi-platforms').textContent = new Set(TITLES.map((t) => t.platform)).size;
  };

  // =============================================
  // Chart.js — общие настройки
  // =============================================
  const chartDefaults = () => {
    Chart.defaults.color = '#a7a2c2';
    Chart.defaults.font.family = "'Inter', 'Noto Sans JP', sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.borderColor = 'rgba(255,255,255,0.08)';
    Chart.defaults.plugins.legend.labels.boxWidth = 10;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.tooltip.backgroundColor = '#151224';
    Chart.defaults.plugins.tooltip.titleColor = '#fff';
    Chart.defaults.plugins.tooltip.bodyColor = '#a7a2c2';
    Chart.defaults.plugins.tooltip.borderColor = 'rgba(255,255,255,0.16)';
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 10;
  };

  const renderCharts = () => {
    chartDefaults();

    // --- платформы (doughnut) ---
    const platformCounts = {};
    TITLES.forEach((t) => {
      platformCounts[t.platform] = (platformCounts[t.platform] || 0) + 1;
    });
    const platformLabels = Object.keys(platformCounts).map((k) => PLATFORMS[k].name);
    const platformColors = Object.keys(platformCounts).map((k) => PLATFORMS[k].color);
    const platformValues = Object.values(platformCounts);

    new Chart($('#chart-platforms'), {
      type: 'doughnut',
      data: {
        labels: platformLabels,
        datasets: [
          {
            data: platformValues,
            backgroundColor: platformColors,
            borderColor: '#0d0b16',
            borderWidth: 3,
            hoverOffset: 10,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '62%',
        plugins: {
          legend: { position: 'bottom', labels: { padding: 14 } },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.label}: ${ctx.parsed} тайтлов`,
            },
          },
        },
      },
    });

    // --- топ-10 по словам (horizontal bar) ---
    const sortedByWords = [...TITLES].sort((a, b) => b.words - a.words).slice(0, 10);
    new Chart($('#chart-words'), {
      type: 'bar',
      data: {
        labels: sortedByWords.map((t) => t.title_ru),
        datasets: [
          {
            label: 'Объём (тыс. слов)',
            data: sortedByWords.map((t) => Math.round(t.words / 1000)),
            backgroundColor: sortedByWords.map((t) => PLATFORMS[t.platform].color + 'CC'),
            borderColor: sortedByWords.map((t) => PLATFORMS[t.platform].color),
            borderWidth: 1,
            borderRadius: 8,
            borderSkipped: false,
            barThickness: 22,
          },
        ],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const t = sortedByWords[ctx.dataIndex];
                return [
                  `${ctx.parsed.x} тыс. слов`,
                  `Глав/томов: ${fmtChapters(t)}`,
                  `Платформа: ${PLATFORMS[t.platform].name}`,
                ];
              },
            },
          },
        },
        scales: {
          x: {
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: { callback: (v) => v + 'k' },
          },
          y: {
            grid: { display: false },
            ticks: { autoSkip: false },
          },
        },
      },
    });

    // --- жанровая матрица (stacked bar) ---
    const MATRIX_GENRES = ['Ромком', 'Yuri', 'Girls Love', 'Yandere', 'Harem', 'Isekai', 'Исекай', 'LitRPG', 'Villainess', 'Drama', 'Boys Love'];
    const genreNormMap = {
      Юри: 'Yuri',
      'Girls Love': 'Yuri',
      Исекай: 'Isekai',
      Ромком: 'Ромком',
    };
    const normalize = (g) => genreNormMap[g] || g;
    const genreList = ['Ромком', 'Yuri', 'Yandere', 'Harem', 'Isekai', 'LitRPG', 'Villainess', 'Drama', 'Boys Love'];
    const platformIds = Object.keys(PLATFORMS);
    const matrix = {};
    genreList.forEach((g) => {
      matrix[g] = {};
      platformIds.forEach((p) => (matrix[g][p] = 0));
    });
    TITLES.forEach((t) => {
      const set = new Set((t.tags || []).map(normalize));
      genreList.forEach((g) => {
        if (set.has(g)) matrix[g][t.platform] += 1;
      });
    });
    const datasets = platformIds.map((pid) => ({
      label: PLATFORMS[pid].name,
      data: genreList.map((g) => matrix[g][pid]),
      backgroundColor: PLATFORMS[pid].color,
      borderRadius: 6,
      borderSkipped: false,
    }));
    new Chart($('#chart-genre-matrix'), {
      type: 'bar',
      data: { labels: genreList, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'bottom', labels: { padding: 10, boxWidth: 8 } },
        },
        scales: {
          x: {
            stacked: true,
            grid: { display: false },
          },
          y: {
            stacked: true,
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: { stepSize: 1 },
          },
        },
      },
    });

    // --- radar: средние характеристики платформ ---
    // Оценка 0–10: авгэ scoring per platform
    const scoreTitle = (t) => {
      return {
        volume: Math.min(10, t.words / 300000),
        uniqueness: ['unique', 'trending'].includes(t.badge) ? 9 : t.priority_score >= 75 ? 7 : 5,
        psych: (t.tags || []).some((x) => ['Clouding', 'Yandere', 'Drama', 'Психологизм', 'Dark romance'].includes(x)) ? 9 : 5,
        adult: t.content_rating === 'adult' ? 9 : t.content_rating === 'mature' ? 6 : 3,
        freshness: t.year_start >= 2025 ? 9 : t.year_start >= 2023 ? 7 : 4,
        licensed: ['jnovel', 'yenpress'].includes(t.platform) ? 10 : 3,
      };
    };
    const radarPlatforms = ['kakuyomu', 'scribblehub', 'royalroad', 'jnovel'];
    const avgBy = (pid, key) => {
      const arr = TITLES.filter((t) => t.platform === pid).map((t) => scoreTitle(t)[key]);
      return arr.length ? +(arr.reduce((a, b) => a + b, 0) / arr.length).toFixed(1) : 0;
    };
    const radarLabels = ['Объём', 'Уникальность', 'Психологизм', 'Взрослый контент', 'Свежесть', 'Доступность EN'];
    const radarKeys = ['volume', 'uniqueness', 'psych', 'adult', 'freshness', 'licensed'];
    new Chart($('#chart-radar'), {
      type: 'radar',
      data: {
        labels: radarLabels,
        datasets: radarPlatforms.map((pid) => ({
          label: PLATFORMS[pid].name,
          data: radarKeys.map((k) => avgBy(pid, k)),
          backgroundColor: PLATFORMS[pid].color + '25',
          borderColor: PLATFORMS[pid].color,
          pointBackgroundColor: PLATFORMS[pid].color,
          pointRadius: 3,
          borderWidth: 2,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'bottom', labels: { padding: 10, boxWidth: 8 } },
        },
        scales: {
          r: {
            beginAtZero: true,
            suggestedMax: 10,
            angleLines: { color: 'rgba(255,255,255,0.08)' },
            grid: { color: 'rgba(255,255,255,0.06)' },
            pointLabels: { font: { size: 11 }, color: '#a7a2c2' },
            ticks: { display: false, stepSize: 2 },
          },
        },
      },
    });

    // --- scatter: год × слов × приоритет ---
    new Chart($('#chart-scatter'), {
      type: 'bubble',
      data: {
        datasets: Object.values(PLATFORMS)
          .filter((p) => TITLES.some((t) => t.platform === p.id))
          .map((p) => ({
            label: p.name,
            data: TITLES.filter((t) => t.platform === p.id).map((t) => ({
              x: t.year_start,
              y: Math.round(t.words / 1000),
              r: Math.max(6, t.priority_score / 6),
              title: t.title_ru,
              score: t.priority_score,
            })),
            backgroundColor: p.color + 'B0',
            borderColor: p.color,
            borderWidth: 2,
          })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'bottom', labels: { padding: 10, boxWidth: 8 } },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const d = ctx.raw;
                return [`${d.title}`, `${d.y} тыс. слов · ${d.x}`, `Приоритет: ${d.score}/100`];
              },
            },
          },
        },
        scales: {
          x: {
            type: 'linear',
            title: { display: true, text: 'Год старта', color: '#6c6785' },
            min: 2018,
            max: 2027,
            ticks: { stepSize: 1 },
            grid: { color: 'rgba(255,255,255,0.04)' },
          },
          y: {
            type: 'logarithmic',
            title: { display: true, text: 'Объём (тыс. слов, лог.)', color: '#6c6785' },
            min: 10,
            max: 3500,
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: {
              callback: (v) => {
                if (v >= 1000) return v / 1000 + 'M';
                return v + 'k';
              },
            },
          },
        },
      },
    });
  };

  // =============================================
  // Init
  // =============================================
  const init = () => {
    buildPlatformFilter();
    buildGenreFilter();
    renderKPI();
    renderCatalog();
    renderMust();
    renderCharts();
    bindEvents();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
