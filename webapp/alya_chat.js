// ==========================================================================
// Аля ИИ — WebApp (Серверный прокси)
// Безопасный чат: все запросы к Groq идут через серверный эндпоинт /api/ai_chat.
// API-ключ никогда не покидает сервер.
// ==========================================================================

const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

const chat = document.getElementById('chat');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const typingIndicator = document.getElementById('typing');

const userName = tg.initDataUnsafe?.user?.first_name || "Пользователь";
const SYSTEM_PROMPT = `Тебя зовут Аля (Алиса Михайлова). Ты цундере-девушка из аниме. Общайся с ${userName}. Будь краткой и милой. Пиши 1-3 предложения. Отвечай на русском.`;

let messageHistory = [{ role: "system", content: SYSTEM_PROMPT }];

// === Определяем URL API-сервера ===
// Если WebApp открыт через Telegram, используем origin сервера бота.
// Fallback: относительный путь (если бот и WebApp на одном хосте).
const urlParams = new URLSearchParams(window.location.search);
const API_URL = urlParams.get('api') || (window.location.hostname !== 'localhost' && !window.location.hostname.includes('github.io') ? window.location.origin : '');

// === API Wrapper ===
async function apiFetch(url, options = {}) {
    options.headers = options.headers || {};
    if (typeof tg !== 'undefined' && tg.initData) {
        options.headers['Authorization'] = 'tma ' + tg.initData;
    }
    return fetch(url, options);
}


if (!API_URL) {
    userInput.disabled = true;
    sendBtn.disabled = true;
    userInput.placeholder = "ИИ-чат доступен только внутри бота";
    setTimeout(() => {
        addMessage("❌ Системная ошибка: Чат заблокирован. Пожалуйста, откройте его через кнопку в Telegram-боте.", false);
    }, 100);
}

// === Утилиты ===
function scrollToBottom() { chat.scrollTop = chat.scrollHeight; }

function addMessage(text, isUser = false) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${isUser ? 'user' : 'bot'}`;
    msgDiv.innerText = text;
    chat.insertBefore(msgDiv, typingIndicator);
    scrollToBottom();
}

// === Запрос к серверному прокси /api/ai_chat ===
async function callAI(messages) {
    const response = await apiFetch(`${API_URL}/api/ai_chat`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ messages })
    });

    if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.error || `Ошибка ${response.status}`);
    }

    const data = await response.json();
    return data.reply;
}

// === Отправка сообщения ===
async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;

    userInput.value = '';
    sendBtn.disabled = true;
    addMessage(text, true);
    messageHistory.push({ role: "user", content: text });
    typingIndicator.classList.remove('hidden');
    scrollToBottom();

    try {
        const reply = await callAI(messageHistory);
        messageHistory.push({ role: "assistant", content: reply });
        // Ограничиваем историю — system + последние 16 сообщений
        if (messageHistory.length > 17) {
            messageHistory = [messageHistory[0], ...messageHistory.slice(-16)];
        }
        typingIndicator.classList.add('hidden');
        addMessage(reply, false);
    } catch (e) {
        typingIndicator.classList.add('hidden');
        addMessage(`❌ ${e.message}`, false);
    } finally {
        sendBtn.disabled = false;
        userInput.focus();
    }
}

// === Обработчики ===
sendBtn.onclick = sendMessage;
userInput.onkeypress = (e) => { if (e.key === 'Enter') sendMessage(); };
tg.setHeaderColor('bg_color');