const fs = require('fs');
const jsdom = require('jsdom');
const { JSDOM } = jsdom;

const html = fs.readFileSync('reader.html', 'utf8');
const dom = new JSDOM(html, { runScripts: "dangerously", url: "http://localhost/" });

const window = dom.window;
global.window = window;
global.document = window.document;
global.localStorage = {
    getItem: () => null,
    setItem: () => {}
};
global.URLSearchParams = window.URLSearchParams;
global.fetch = async (url) => {
    return {
        ok: true,
        json: async () => JSON.parse(fs.readFileSync('chapters_data.json'))
    }
};
global.Date.now = () => 123;
global.tg = { expand: ()=>{}, ready: ()=>{} };
global.window.Telegram = { WebApp: global.tg };
global.console.warn = console.warn;
global.console.error = console.error;

// Mock observers
global.IntersectionObserver = class { observe(){} disconnect(){} };
global.AbortSignal = { timeout: () => ({}) };

const script = fs.readFileSync('reader.js', 'utf8');

process.on('unhandledRejection', r => console.log('unhandledRejection', r));

try {
    window.eval(script);
} catch (e) {
    console.error("ERROR EVALUATING SCRIPT:", e);
}

// wait a bit for promises
setTimeout(() => {
    console.log("Series list innerHTML length:", document.getElementById('series-list').innerHTML.length);
    console.log("If length is small, maybe it failed. Let's see if there is an error.");
}, 1000);
