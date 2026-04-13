import re

def update_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Add apiFetch definition near API_URL
    api_fetch_def = """const API_URL = urlParams.get('api') || (window.location.hostname !== 'localhost' && !window.location.hostname.includes('github.io') ? window.location.origin : '');

// === API Wrapper ===
async function apiFetch(url, options = {}) {
    options.headers = options.headers || {};
    if (typeof tg !== 'undefined' && tg.initData) {
        options.headers['Authorization'] = 'tma ' + tg.initData;
    }
    return fetch(url, options);
}
"""
    content = re.sub(
        r"const API_URL = .*?;", 
        api_fetch_def, 
        content, 
        count=1
    )

    # Replace fetch(API_URL... with apiFetch(API_URL...
    content = content.replace("await fetch(API_URL", "await apiFetch(API_URL")
    content = content.replace("await fetch(`${API_URL}", "await apiFetch(`${API_URL}")
    content = content.replace("fetch(API_URL", "apiFetch(API_URL")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

update_file("webapp/reader.js")
update_file("webapp/alya_chat.js")
