const fs = require('fs');

const app = fs.readFileSync('app.js', 'utf8');
const html = fs.readFileSync('index.html', 'utf8');
const css = fs.readFileSync('styles.css', 'utf8');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(app.includes('translationDecisionFor'), 'app.js should compute a translation decision for each title');
assert(app.includes("decision: 'all'"), 'app state should track the decision filter');
assert(app.includes("f.decision !== 'all'"), 'passesFilter should apply the decision filter');
assert(app.includes("hasScoutResource(t, 'Nyaa')"), 'source filtering should support the Nyaa audit source');
assert(html.includes('data-filter-group="decision"'), 'catalog should render a decision preset filter group');
assert(html.includes('data-filter-value="nyaa"'), 'catalog should expose a Nyaa source filter');
assert(css.includes('.decision-panel'), 'styles should define the card decision panel');
assert(css.includes('.filter-strip'), 'styles should define the quick preset filter strip');

console.log('Decision filter UI validated.');
