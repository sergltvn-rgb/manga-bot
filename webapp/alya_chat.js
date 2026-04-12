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

// ==========================================================================
// КОНФИГУРАЦИЯ: бот передаёт ключ через ?key= и URL сервера через ?server=
// Ключ сохраняется в localStorage — пользователь ничего не вводит вручную.
// ==========================================================================
const urlParams = new URLSearchParams(window.location.search);

// Забираем параметры из URL (если есть)
const keyFromUrl = urlParams.get('key');
const serverFromUrl = urlParams.get('server');

if (keyFromUrl) localStorage.setItem("alya_groq_key", keyFromUrl);
if (serverFromUrl) localStorage.setItem("alya_api_url", serverFromUrl);

// Чистим URL, чтобы ключ не торчал в адресной строке
if (keyFromUrl || serverFromUrl) {
    window.history.replaceState({}, document.title, window.location.pathname);
}

// Groq API ключ (получен от бота)
const GROQ_KEY = localStorage.getItem("alya_groq_key") || "";
// URL прокси-сервера бота (для локальной модели, если сервер доступен)
const SERVER_URL = localStorage.getItem("alya_api_url") || "";

// Текущий провайдер
let currentProvider = localStorage.getItem("alya_provider") || "groq";

// Если Groq ключ есть — принудительно ставим groq как основной
if (GROQ_KEY && !SERVER_URL) {
    currentProvider = "groq";
    localStorage.setItem("alya_provider", "groq");
}

function updateProviderUI() {
    if (providerLabel) {
        if (currentProvider === "gemma") {
            providerLabel.textContent = "🖥 Локально (Gemma 4)";
        } else {
            providerLabel.textContent = "☁️ Облако (Groq)";
        }
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

// ==========================================================================
// ОТПРАВКА ЧЕРЕЗ GROQ НАПРЯМУЮ (без прокси-сервера)
// ==========================================================================
async function sendViaGroq(messages) {
    const response = await fetch("https://api.groq.com/openai/v1/chat/completions", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${GROQ_KEY}`
        },
        body: JSON.stringify({
            model: "llama-3.3-70b-versatile",
            messages: messages,
            temperature: 0.65,
            max_tokens: 300
        })
    });

    if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Groq ${response.status}: ${errText.substring(0, 100)}`);
    }

    const data = await response.json();
    return data.choices[0].message.content;
}

// ==========================================================================
// ОТПРАВКА ЧЕРЕЗ ПРОКСИ-СЕРВЕР БОТА (для локальной модели / если нет ключа)
// ==========================================================================
async function sendViaProxy(messages, provider) {
    if (!SERVER_URL) throw new Error("URL сервера бота не настроен");

    const response = await fetch(`${SERVER_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages, provider })
    });

    if (!response.ok) {
        const errText = await response.text();
        throw new Error(`HTTP ${response.status}: ${errText.substring(0, 100)}`);
    }

    const data = await response.json();
    return data.choices[0].message.content;
}

// ==========================================================================
// ОСНОВНАЯ ФУНКЦИЯ ОТПРАВКИ
// ==========================================================================
async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;

    // Проверяем, есть ли хоть какой-то способ общения с ИИ
    if (!GROQ_KEY && !SERVER_URL) {
        addMessage("⚠️ Нет подключения к ИИ. Открой бота в Telegram заново — ключ передастся автоматически.", false);
        return;
    }

    userInput.value = '';
    sendBtn.disabled = true;
    addMessage(text, true);
    messageHistory.push({ role: "user", content: text });
    typingIndicator.classList.remove('hidden');
    scrollToBottom();

    try {
        let reply;

        if (currentProvider === "gemma" && SERVER_URL) {
            // Локальная модель — только через прокси-сервер бота
            reply = await sendViaProxy(messageHistory, "gemma");
        } else if (GROQ_KEY) {
            // Groq — напрямую через API
            reply = await sendViaGroq(messageHistory);
        } else if (SERVER_URL) {
            // Fallback: через прокси
            reply = await sendViaProxy(messageHistory, currentProvider);
        } else {
            throw new Error("Нет доступных провайдеров");
        }

        messageHistory.push({ role: "assistant", content: reply });
        typingIndicator.classList.add('hidden');
        addMessage(reply, false);
    } catch (e) {
        typingIndicator.classList.add('hidden');
        addMessage(`❌ Ошибка: ${e.message}`, false);
    } finally {
        sendBtn.disabled = false;
        userInput.focus();
    }
}

// --- Переключатель провайдера ---
if (providerToggle) {
    providerToggle.addEventListener('change', () => {
        const wantGemma = providerToggle.checked;

        if (wantGemma && !SERVER_URL) {
            addMessage("⚠️ Для локальной модели нужен прокси-сервер бота (ngrok). Пока доступен только Groq.", false);
            providerToggle.checked = false;
            return;
        }

        currentProvider = wantGemma ? "gemma" : "groq";
        localStorage.setItem("alya_provider", currentProvider);
        updateProviderUI();
        addMessage(`🔄 Переключено на ${currentProvider === "gemma" ? "🖥 Gemma 4 (Локально)" : "☁️ Groq (Облако)"}`, false);
    });
}

// --- Настройки ---
if (openSettings) {
    openSettings.onclick = () => {
        if (apiUrlInput) apiUrlInput.value = SERVER_URL;
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
            if (url.endsWith('/')) url = url.slice(0, -1);
            localStorage.setItem("alya_api_url", url);
        }
        settingsModal.classList.add('hidden');
        addMessage("✅ Настройки сохранены!", false);
    };
}

sendBtn.onclick = sendMessage;
userInput.onkeypress = (e) => { if(e.key === 'Enter') sendMessage(); };
tg.setHeaderColor('bg_color');

// Инициализация UI
updateProviderUI();

// Стартовое сообщение
if (!GROQ_KEY && !SERVER_URL) {
    addMessage("⚙️ Подключение не настроено. Открой WebApp через кнопку в Telegram-боте — ключ передастся автоматически.", false);
}