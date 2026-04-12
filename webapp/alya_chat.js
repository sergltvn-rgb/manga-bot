const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

const chat = document.getElementById('chat');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const typingIndicator = document.getElementById('typing');
const providerToggle = document.getElementById('providerToggle');
const providerLabel = document.getElementById('providerLabel');
const openSettings = document.getElementById('openSettings');
const settingsModal = document.getElementById('settingsModal');
const closeSettings = document.getElementById('closeSettings');
const saveSettings = document.getElementById('saveSettings');
const apiUrlInput = document.getElementById('apiUrlInput');

const userName = tg.initDataUnsafe?.user?.first_name || "Пользователь";
const SYSTEM_PROMPT = `Тебя зовут Аля. Ты цундере. Общайся с ${userName}. Будь краткой. Пиши 1-2 предложения.`;

let messageHistory = [{ role: "system", content: SYSTEM_PROMPT }];

// --- URL сервера бота (приходит автоматически из бота через ?server=) ---
const urlParams = new URLSearchParams(window.location.search);
const serverFromUrl = urlParams.get('server');
if (serverFromUrl) {
    localStorage.setItem("alya_api_url", serverFromUrl);
    // Чистим URL, чтобы не мозолил глаза
    window.history.replaceState({}, document.title, window.location.pathname);
}
let API_BASE_URL = localStorage.getItem("alya_api_url") || "";

// Текущий провайдер
let currentProvider = localStorage.getItem("alya_provider") || "groq";

function updateProviderUI() {
    if (providerLabel) {
        providerLabel.textContent = currentProvider === "gemma"
            ? "🖥 Локально (Gemma 4)"
            : "☁️ Облако (Groq)";
    }
    if (providerToggle) {
        providerToggle.checked = currentProvider === "gemma";
    }
}

function scrollToBottom() { chat.scrollTop = chat.scrollHeight; }

function addMessage(text, isUser = false) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${isUser ? 'user' : 'bot'}`;
    msgDiv.innerText = text;
    chat.insertBefore(msgDiv, typingIndicator);
    scrollToBottom();
}

async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;

    if (!API_BASE_URL) {
        addMessage("⚠️ Нажми ⚙️ и введи URL твоего ngrok-сервера (например: https://xxxx.ngrok-free.app)", false);
        return;
    }

    userInput.value = '';
    sendBtn.disabled = true;
    addMessage(text, true);
    messageHistory.push({ role: "user", content: text });
    typingIndicator.classList.remove('hidden');
    scrollToBottom();

    try {
        const response = await fetch(`${API_BASE_URL}/api/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                messages: messageHistory,
                provider: currentProvider
            })
        });

        if (!response.ok) {
            const errText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errText.substring(0, 100)}`);
        }

        const data = await response.json();
        const reply = data.choices[0].message.content;

        messageHistory.push({ role: "assistant", content: reply });
        typingIndicator.classList.add('hidden');

        const badge = currentProvider === "gemma" ? "🖥" : "☁️";
        addMessage(`${reply}`, false);
    } catch (e) {
        typingIndicator.classList.add('hidden');
        addMessage(`❌ Ошибка: ${e.message}\nПроверь, запущен ли бот и ngrok.`, false);
    } finally {
        sendBtn.disabled = false;
        userInput.focus();
    }
}

// --- Переключатель провайдера ---
if (providerToggle) {
    providerToggle.addEventListener('change', () => {
        currentProvider = providerToggle.checked ? "gemma" : "groq";
        localStorage.setItem("alya_provider", currentProvider);
        updateProviderUI();
        addMessage(`🔄 Переключено на ${currentProvider === "gemma" ? "🖥 Gemma 4 (Локально)" : "☁️ Groq (Облако)"}`, false);
    });
}

// --- Настройки (только URL сервера) ---
if (openSettings) {
    openSettings.onclick = () => {
        if (apiUrlInput) apiUrlInput.value = API_BASE_URL;
        settingsModal.classList.remove('hidden');
    };
}

if (closeSettings) {
    closeSettings.onclick = () => settingsModal.classList.add('hidden');
}

if (saveSettings) {
    saveSettings.onclick = () => {
        if (apiUrlInput) {
            let url = apiUrlInput.value.trim();
            // Убираем слеш на конце
            if (url.endsWith('/')) url = url.slice(0, -1);
            API_BASE_URL = url;
            localStorage.setItem("alya_api_url", API_BASE_URL);
        }
        settingsModal.classList.add('hidden');
        addMessage("✅ Настройки сохранены! Теперь можешь писать.", false);
    };
}

sendBtn.onclick = sendMessage;
userInput.onkeypress = (e) => { if(e.key === 'Enter') sendMessage(); };
tg.setHeaderColor('bg_color');

// Инициализация UI
updateProviderUI();

// Если URL уже есть — показываем подсказку
if (!API_BASE_URL) {
    addMessage("⚙️ Нажми на шестерёнку сверху и введи URL сервера бота (ngrok).", false);
}