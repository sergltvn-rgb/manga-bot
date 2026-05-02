const fs = require('fs');
const vm = require('vm');

const src = fs.readFileSync('data.js', 'utf8');
const sandbox = {};
vm.runInNewContext(`${src}; this.TITLES = TITLES; this.COVER_URLS = COVER_URLS;`, sandbox);

const titles = sandbox.TITLES;
const coverUrls = sandbox.COVER_URLS || {};
const oceanRomcomIds = [
  'alya-russian',
  'angel-next-door',
  'friends-little-sister',
  'stepmom-daughter-ex',
  'chitose-ramune',
  'days-stepsister',
  'tomozaki',
  'haibara-new-game',
  'introvert-hookup',
  'like-me-not-daughter',
  'ice-queen-heart',
];

const untranslatedJapaneseRomanceIds = [
  'girl-saved-train',
  'toxic-classmate',
  'seatmate-killer',
  'side-character-popular',
  'win-heart-nth-try',
];

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

assert(titles.length >= 89, `Expected at least 89 titles, got ${titles.length}`);

for (const id of oceanRomcomIds) {
  const title = titles.find((item) => item.id === id);
  assert(title, `Missing OceanOfPDF romcom title: ${id}`);
  assert(title.language === 'ja', `${id} should be marked as a Japanese-origin title`);
  assert((title.tags || []).includes('Ромком'), `${id} should be tagged as Ромком`);
  assert(
    title.translation_scout?.sources?.some((source) => source.resource === 'OceanOfPDF'),
    `${id} should include OceanOfPDF scout source`
  );
  assert(
    title.translation_scout?.sources?.some((source) => source.scope === 'Русский аудит'),
    `${id} should include a Russian-site audit source`
  );
  assert(
    title.translation_scout?.sources?.some((source) =>
      /Rulate|RanobeLib|Ranobes|Ранобэлиб|Рулейт|ранобэс/i.test(`${source.resource || ''} ${source.amount || ''} ${source.note || ''}`)
    ),
    `${id} should name Russian sites checked`
  );
  assert(coverUrls[id], `${id} should have a cover image`);
  assert(
    !String(title.url || '').includes('oceanofpdf.com'),
    `${id} should not link directly to OceanOfPDF as the primary title URL`
  );
  assert(
    !(title.free_access || []).some((item) => String(item.url || '').includes('oceanofpdf.com')),
    `${id} should not expose OceanOfPDF in free_access links`
  );
}

for (const id of untranslatedJapaneseRomanceIds) {
  const title = titles.find((item) => item.id === id);
  assert(title, `Missing untranslated Japanese romance title: ${id}`);
  assert(title.language === 'ja', `${id} should be marked as a Japanese-origin title`);
  assert(title.translation_scout?.status === 'not_found', `${id} should be marked as not found in Russian`);
  assert(
    (title.tags || []).some((tag) => tag === 'Ромком' || tag === 'Романтика'),
    `${id} should be tagged as Japanese romance/romcom`
  );
  assert(
    title.translation_scout?.sources?.some((source) => source.scope === 'Русский аудит'),
    `${id} should include a Russian-site audit source`
  );
  assert(
    title.translation_scout?.sources?.some((source) =>
      /Rulate|RanobeLib|Ranobes|Ранобэлиб|Рулейт|ранобэс/i.test(`${source.resource || ''} ${source.amount || ''} ${source.note || ''}`)
    ),
    `${id} should name Russian sites checked`
  );
  assert(coverUrls[id], `${id} should have a real cover image`);
  assert(
    title.translation_scout?.sources?.some((source) => source.resource === 'JNovels'),
    `${id} should include a JNovels audit source`
  );
}

console.log(
  `Validated ${titles.length} titles, including ${oceanRomcomIds.length} OceanOfPDF romcoms and ${untranslatedJapaneseRomanceIds.length} untranslated Japanese romance picks.`
);
