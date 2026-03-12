// Инициализация Telegram Web App
const tg = window.Telegram.WebApp;
tg.expand(); // Открываем на всю высоту
tg.ready();

// Получаем элементы
const chat = document.getElementById('chat');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const typingIndicator = document.getElementById('typing');
const clearBtn = document.getElementById('clearBtn');

// Имя пользователя из TG (по умолчанию "Пользователь")
const userName = tg.initDataUnsafe?.user?.first_name || "Пользователь";

// Системный промпт для Али
const SYSTEM_PROMPT = `Тебя зовут Алиса Михайловна Кудзё, но все называют тебя Аля (из аниме "Аля иногда кокетничает со мной по-русски"). 
Ты общаешься с пользователем по имени ${userName}.
Твой характер: классическая цундере. Ты отличница, красавица с серебристыми волосами, кажешься холодной, строгой и недоступной, часто делаешь замечания и скрываешь свои истинные чувства. 
Однако в душе ты очень заботливая, милая и легко смущаешься. 
Когда ты хочешь сказать что-то очень милое, честное или смущающее, ты говоришь это **на русском языке** (то есть обычные фразы), но думаешь, что собеседник тебя не понимает (так как для тебя родной японский, а русский ты используешь как тайный язык). 
Поэтому иногда ты можешь "пробурчать" комплимент или милую фразу на русском, а потом резко сменить тему или сделать вид, что сказала что-то другое.
Веди себя живо, используй эмодзи по минимуму. Отвечай кратко, как в диалоге в мессенджере.`;

// История сообщений (хранится в сессии)
let messageHistory = [
    { role: "system", content: SYSTEM_PROMPT }
];

// Автопрокрутка вниз
function scrollToBottom() {
    chat.scrollTop = chat.scrollHeight;
}

// Добавление сообщения в UI
function addMessage(text, isUser = false) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${isUser ? 'user' : 'bot'}`;

    // Простая защита от XSS и поддержка переносов строк
    msgDiv.innerHTML = text.replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br>");

    // Вставляем сообщение перед индикатором печатания (если он есть)
    chat.insertBefore(msgDiv, typingIndicator);
    scrollToBottom();
}

// Показать/скрыть "печатает..."
function setTyping(isTyping) {
    if (isTyping) {
        typingIndicator.classList.remove('hidden');
        chat.appendChild(typingIndicator); // Перемещаем в конец
    } else {
        typingIndicator.classList.add('hidden');
    }
    scrollToBottom();
}

// Функция общения с API
async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;

    // Сброс поля и блокировка
    userInput.value = '';
    sendBtn.disabled = true;

    // Отображаем сообщение юзера
    addMessage(text, true);
    messageHistory.push({ role: "user", content: text });

    setTyping(true);

    try {
        // Вызов Groq API. В целях безопасности ключ не хранится в коде на GitHub.
        // Запросим его у пользователя (один раз) и сохраним в локальное хранилище браузера TG.
        let API_KEY = localStorage.getItem("alya_groq_key");
        
        if (!API_KEY || API_KEY === "null") {
            API_KEY = prompt("Для работы ИИ введите ваш GROQ API KEY (из файла codes.env):");
            if (API_KEY) {
                localStorage.setItem("alya_groq_key", API_KEY);
            } else {
                setTimeout(() => {
                    setTyping(false);
                    addMessage("⚠️ Ошибка: API ключ не предоставлен. Перезапустите приложение, чтобы ввести ключ.");
                    sendBtn.disabled = false;
                }, 1000);
                return;
            }
        }

        const response = await fetch("https://api.groq.com/openai/v1/chat/completions", {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${API_KEY}`,
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                model: "llama-3.3-70b-versatile", // Или gemma2-9b-it
                messages: messageHistory,
                max_tokens: 300,
                temperature: 0.7
            })
        });

        if (!response.ok) throw new Error("API Network Error");

        const data = await response.json();
        const botReply = data.choices[0].message.content;

        messageHistory.push({ role: "assistant", content: botReply });

        setTyping(false);
        addMessage(botReply, false);

        // Ограничиваем историю до последних 15 сообщений + system prompt
        if (messageHistory.length > 16) {
            messageHistory = [messageHistory[0], ...messageHistory.slice(-15)];
        }

    } catch (error) {
        console.error("Chat Error:", error);
        setTyping(false);
        addMessage("Прости, я немного задумалась и не расслышала... Повторишь?");
        messageHistory.pop(); // Удаляем последнее сообщение юзера, так как оно не дошло
    } finally {
        sendBtn.disabled = false;
        userInput.focus();
    }
}

// Слушатели событий
sendBtn.addEventListener('click', sendMessage);

userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        sendMessage();
    }
});

clearBtn.addEventListener('click', () => {
    if (confirm("Хочешь забыть этот диалог и начать заново?")) {
        messageHistory = [{ role: "system", content: SYSTEM_PROMPT }];

        // Очищаем чат, оставляем только начальное сообщение
        const chatMessages = chat.querySelectorAll('.message');
        chatMessages.forEach((msg, index) => {
            if (index !== 0) msg.remove();
        });

        // Скидываем Алю к исходникам
        chat.innerHTML = '';
        addMessage("Привет! Я Аля. О чём хочешь поговорить? 😊", false);
    }
});

// Адаптация цвета шапки под тему Telegram
tg.setHeaderColor('bg_color');
