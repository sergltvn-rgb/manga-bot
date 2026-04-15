const fs = require('fs');
const jsdom = require('jsdom');
const { JSDOM } = jsdom;

const html = fs.readFileSync('reader.html', 'utf8');
const dom = new JSDOM(html, { runScripts: "dangerously", url: "http://localhost/" });
const window = dom.window;

window.localStorage = {
    getItem: () => null,
    setItem: () => {}
};
window.fetch = async (url) => {
    return {
        ok: true,
        json: async () => JSON.parse(fs.readFileSync('chapters_data.json'))
    }
};
window.Telegram = { WebApp: { expand: ()=>{}, ready: ()=>{}, initDataUnsafe: { user: { id: 1234, first_name: "Test" } } } };
window.IntersectionObserver = class { observe(){} disconnect(){} };
window.AbortSignal = { timeout: () => ({}) };

const script = fs.readFileSync('reader.js', 'utf8');

try {
    window.eval(script);
} catch (e) {
    console.error("ERROR EVALUATING SCRIPT:", e);
}

setTimeout(() => {
    console.log("Series list innerHTML length:", window.document.getElementById('series-list').innerHTML.length);
    const seriesCards = window.document.querySelectorAll('.series-card');
    console.log("Number of series cards:", seriesCards.length);
    seriesCards.forEach(card => {
        console.log("Card HTML snippet:", card.innerHTML.substring(0, 100));
    });
}, 1000);
