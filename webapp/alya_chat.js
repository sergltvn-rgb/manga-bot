const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

const chat = document.getElementById('chat');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const typingIndicator = document.getElementById('typing');
const clearBtn = document.getElementById('clearBtn');
const userName = tg.initDataUnsafe?.user?.first_name || "Пользователь";

const SYSTEM_PROMPT = `Тебя зовут Аля. Ты общаешься с ${userName}. Ты цундере: строгая снаружи, но милая внутри. Пиши кратко (1-2 фразы). Иногда ворчи по-русски в конце сообщения.`;

let messageHistory = [{ role: "system", content: SYSTEM_PROMPT }];

function scrollToBottom() { chat.scrollTop = chat.scrollHeight; }

function addMessage(text, isUser = false) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${isUser ? 'user' : 'bot'}`;
    msgDiv.innerText = text;
    chat.insertBefore(msgDiv, typingIndicator);
    scrollToBottom();
}

const urlParams = new URLSearchParams(window.location.search);
const apiKeyFromUrl = urlParams.get('api_key');
if (apiKeyFromUrl) {
    localStorage.setItem("alya_groq_key", apiKeyFromUrl);
    window.history.replaceState({}, document.title, window.location.pathname);
}

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
        const API_KEY = apiKeyFromUrl || localStorage.getItem("alya_groq_key");
        if (!API_KEY) throw new Error("API ключ не найден. Запустите бота заново.");

        let apiUrl = "https://api.groq.com/openai/v1/chat/completions";
        let model = "llama-3.3-70b-versatile";

        if (API_KEY.startsWith("sk-lm-")) {
            apiUrl = "http://127.0.0.1:1234/v1/chat/completions";
            model = "local-model";
        }

        const response = await fetch(apiUrl, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${API_KEY}`,
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ model, messages: messageHistory, temperature: 0.7 })
        });

        if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
        const data = await response.json();
        const reply = data.choices[0].message.content;
        messageHistory.push({ role: "assistant", content: reply });
        typingIndicator.classList.add('hidden');
        addMessage(reply, false);
    } catch (e) {
        typingIndicator.classList.add('hidden');
        addMessage("Ошибка: " + e.message, false);
    } finally {
        sendBtn.disabled = false;
        userInput.focus();
    }
}

sendBtn.addEventListener('click', sendMessage);
userInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMessage(); });
clearBtn.addEventListener('click', () => {
    if (confirm("Очистить чат?")) {
        messageHistory = [{ role: "system", content: SYSTEM_PROMPT }];
        const msgs = chat.querySelectorAll('.message');
        msgs.forEach(m => m.remove());
        addMessage("Привет! Я Аля. 😊", false);
    }
});
tg.setHeaderColor('bg_color');