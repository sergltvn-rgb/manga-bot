const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

const chat = document.getElementById('chat');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const typingIndicator = document.getElementById('typing');
const openSettings = document.getElementById('openSettings');
const settingsModal = document.getElementById('settingsModal');
const closeSettings = document.getElementById('closeSettings');
const saveSettings = document.getElementById('saveSettings');

const tokenInput = document.getElementById('tokenInput');
const urlInput = document.getElementById('urlInput');
const modelInput = document.getElementById('modelInput');

// Переключатель провайдера
const providerToggle = document.getElementById('providerToggle');
const providerLabel = document.getElementById('providerLabel');

const userName = tg.initDataUnsafe?.user?.first_name || "Пользователь";
const SYSTEM_PROMPT = `Тебя зовут Аля. Ты цундере. Общайся с ${userName}. Будь краткой. Пиши 1-2 предложения.`;

let messageHistory = [{ role: "system", content: SYSTEM_PROMPT }];

// Загрузка настроек из localStorage
let config = {
    token: localStorage.getItem("alya_token") || "",
    url: localStorage.getItem("alya_url") || "https://api.groq.com/openai/v1/chat/completions",
    model: localStorage.getItem("alya_model") || "llama-3.3-70b-versatile",
    provider: localStorage.getItem("alya_provider") || "groq" // groq или gemma
};

// --- Провайдеры ---
const PROVIDERS = {
    groq: {
        name: "☁️ Облако (Groq)",
        url: "https://api.groq.com/openai/v1/chat/completions",
        model: "llama-3.3-70b-versatile",
        tokenKey: "GROQ_API_KEY",
    },
    gemma: {
        name: "🖥 Локально (Gemma 4)",
        url: "http://127.0.0.1:1234/v1/chat/completions",
        model: "google/gemma-4-e4b:2",
        tokenKey: "GEMMA_API_KEY",
    }
};

// Если ключ пришел в URL — сохраняем его приоритетно (для Groq)
const urlParams = new URLSearchParams(window.location.search);
const apiKeyFromUrl = urlParams.get('api_key');
if (apiKeyFromUrl) {
    config.token = apiKeyFromUrl;
    localStorage.setItem("alya_token", apiKeyFromUrl);
    // Очистка URL
    window.history.replaceState({}, document.title, window.location.pathname);
}

// Gemma ключ из URL (если передан)
const gemmaKeyFromUrl = urlParams.get('gemma_key');
if (gemmaKeyFromUrl) {
    localStorage.setItem("alya_gemma_token", gemmaKeyFromUrl);
}

function updateProviderUI() {
    const p = PROVIDERS[config.provider];
    if (providerLabel) {
        providerLabel.textContent = p.name;
    }
    if (providerToggle) {
        providerToggle.checked = config.provider === "gemma";
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

    // Определяем текущий токен и URL на основе провайдера
    let currentUrl, currentModel, currentToken;
    
    if (config.provider === "gemma") {
        currentUrl = PROVIDERS.gemma.url;
        currentModel = PROVIDERS.gemma.model;
        currentToken = localStorage.getItem("alya_gemma_token") || config.token;
    } else {
        currentUrl = PROVIDERS.groq.url;
        currentModel = PROVIDERS.groq.model;
        currentToken = config.token;
    }

    if (!currentToken) {
        addMessage("⚠️ Ошибка: Нажми на ⚙️ сверху и введи свой API токен!", false);
        return;
    }

    userInput.value = '';
    sendBtn.disabled = true;
    addMessage(text, true);
    messageHistory.push({ role: "user", content: text });
    typingIndicator.classList.remove('hidden');
    scrollToBottom();

    try {
        const response = await fetch(currentUrl, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${currentToken}`,
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ 
                model: currentModel, 
                messages: messageHistory, 
                temperature: 0.7 
            })
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        const reply = data.choices[0].message.content;
        
        messageHistory.push({ role: "assistant", content: reply });
        typingIndicator.classList.add('hidden');
        addMessage(reply, false);
    } catch (e) {
        typingIndicator.classList.add('hidden');
        const providerName = PROVIDERS[config.provider].name;
        addMessage(`Ошибка (${providerName}): ${e.message}\nПроверьте настройки ⚙️ и запущен ли сервер.`, false);
    } finally {
        sendBtn.disabled = false;
        userInput.focus();
    }
}

// --- Переключатель провайдера ---
if (providerToggle) {
    providerToggle.addEventListener('change', () => {
        config.provider = providerToggle.checked ? "gemma" : "groq";
        localStorage.setItem("alya_provider", config.provider);
        updateProviderUI();
        addMessage(`🔄 Переключено на ${PROVIDERS[config.provider].name}`, false);
    });
}

// Управление настройками
openSettings.onclick = () => {
    tokenInput.value = config.token;
    urlInput.value = config.url;
    modelInput.value = config.model;
    
    const gemmaTokenInput = document.getElementById('gemmaTokenInput');
    if (gemmaTokenInput) {
        gemmaTokenInput.value = localStorage.getItem("alya_gemma_token") || "";
    }
    
    settingsModal.classList.remove('hidden');
};

closeSettings.onclick = () => settingsModal.classList.add('hidden');

saveSettings.onclick = () => {
    config.token = tokenInput.value.trim();
    config.url = urlInput.value.trim();
    config.model = modelInput.value.trim();
    
    localStorage.setItem("alya_token", config.token);
    localStorage.setItem("alya_url", config.url);
    localStorage.setItem("alya_model", config.model);
    
    const gemmaTokenInput = document.getElementById('gemmaTokenInput');
    if (gemmaTokenInput) {
        localStorage.setItem("alya_gemma_token", gemmaTokenInput.value.trim());
    }
    
    settingsModal.classList.add('hidden');
    addMessage("✅ Настройки сохранены!", false);
};

sendBtn.onclick = sendMessage;
userInput.onkeypress = (e) => { if(e.key === 'Enter') sendMessage(); };
tg.setHeaderColor('bg_color');

// Инициализация UI
updateProviderUI();