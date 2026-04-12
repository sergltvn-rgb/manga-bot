// ==========================================================================
// Аля ИИ — WebApp (Groq Cloud)
// Простой чат: получает API ключ от бота, вызывает Groq напрямую.
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

// === Получаем ключ Groq от бота (через ?key= в URL) ===
const urlParams = new URLSearchParams(window.location.search);
const keyFromUrl = urlParams.get('key');

if (keyFromUrl) {
    localStorage.setItem("alya_groq_key", keyFromUrl);
    // Чистим URL чтобы ключ не торчал
    window.history.replaceState({}, document.title, window.location.pathname);
}

const GROQ_KEY = localStorage.getItem("alya_groq_key") || "";

// === Утилиты ===
function scrollToBottom() { chat.scrollTop = chat.scrollHeight; }

function addMessage(text, isUser = false) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${isUser ? 'user' : 'bot'}`;
    msgDiv.innerText = text;
    chat.insertBefore(msgDiv, typingIndicator);
    scrollToBottom();
}

// === Запрос к Groq API ===
async function callGroq(messages) {
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
        throw new Error(`Ошибка ${response.status}: ${errText.substring(0, 100)}`);
    }

    const data = await response.json();
    return data.choices[0].message.content;
}

// === Отправка сообщения ===
async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;

    if (!GROQ_KEY) {
        addMessage("⚠️ Нет ключа API. Открой этот чат через кнопку в Telegram-боте — ключ передастся автоматически.", false);
        return;
    }

    userInput.value = '';
    sendBtn.disabled = true;
    addMessage(text, true);
    messageHistory.push({ role: "user", content: text });
    typingIndicator.classList.remove('hidden');
    scrollToBottom();

    try {
        const reply = await callGroq(messageHistory);
        messageHistory.push({ role: "assistant", content: reply });
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

// === Стартовое сообщение ===
if (!GROQ_KEY) {
    addMessage("⚙️ Открой этот чат через кнопку «🌐 Веб-чат с Алей» в Telegram-боте.", false);
}