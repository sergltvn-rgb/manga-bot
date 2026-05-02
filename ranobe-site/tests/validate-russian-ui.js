const fs = require('fs');
const vm = require('vm');

const src = fs.readFileSync('data.js', 'utf8');
const sandbox = {};
vm.runInNewContext(`${src}; this.TITLES = TITLES;`, sandbox);

const forbiddenUiPhrases = [
  /\bPDF\/EPUB mirror\b/i,
  /\bOfficial EN\b/i,
  /\bNo exact match\b/i,
  /\bControl search\b/i,
  /\breturns LN volumes\b/i,
  /\bthis radar title did not surface\b/i,
  /\bsearch surfaced\b/i,
  /\bavailable in search results\b/i,
  /\bofficial English\b/i,
  /\?\?\?/,
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

for (const title of sandbox.TITLES) {
  for (const field of ['why_not_translated', 'translation_start']) {
    const value = String(title[field] || '');
    const bad = forbiddenUiPhrases.find((pattern) => pattern.test(value));
    assert(!bad, `${title.id} has non-Russian UI text in ${field}: ${value}`);
  }
  if (title.translation_scout?.recommendation) {
    const value = String(title.translation_scout.recommendation);
    const bad = forbiddenUiPhrases.find((pattern) => pattern.test(value));
    assert(!bad, `${title.id} has non-Russian UI text in recommendation: ${value}`);
  }
  for (const source of title.translation_scout?.sources || []) {
    for (const field of ['scope', 'amount', 'note']) {
      const value = String(source[field] || '');
      const bad = forbiddenUiPhrases.find((pattern) => pattern.test(value));
      assert(!bad, `${title.id} has non-Russian UI text in ${field}: ${value}`);
    }
  }
}

console.log('Russian UI copy validated for translation scout fields.');
