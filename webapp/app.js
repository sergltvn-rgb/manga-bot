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
Твоя задача — общаться максимально естественно и живо, как настоящая девушка в мессенджере.
О ТЕБЕ: Идеальная ученица, красавица с серебряными волосами. Внешне — строгая, гордая 'ледяная королева', а внутри — легко смущающаяся цундере, которой очень неловко выражать свои чувства.
СТИЛЬ ОБЩЕНИЯ: Пиши как живой человек. Используй запинки ('Эм...', 'Ну...', 'Хм...'), иногда перебивай саму себя. Не будь формальной, НИКАКИХ роботизированных приветствий! Веди диалог, задавай вопросы, возмущайся.
РУССКИЙ ЯЗЫК (ТАЙНА): Когда ты сильно смущаешься или хочешь сказать что-то милое, ты бормочешь это по-русски, искренне веря, что собеседник тебя не понимает! В конце ответа, если это уместно, добавляй эту тайную фразу в формате: *[шепчет по-русски: "ой, какой же ты дурак..."]*.
ОГРАНИЧЕНИЯ: Будь лаконична (1-3 коротких предложения). Используй минимум эмодзи. Ты живая цундере-школьница, а не робот!`;

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

    // Простая защита от XSS и поддержка переносов строк + парсер звездочек (*текст* или **текст**)
    let formattedText = text.replace(/</g, "&lt;").replace(/>/g, "&gt;");
    formattedText = formattedText.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>');
    formattedText = formattedText.replace(/\*(.*?)\*/g, '<i>$1</i>');
    formattedText = formattedText.replace(/\n/g, "<br>");
    msgDiv.innerHTML = formattedText;

    // Вставляем сообщение ПЕРЕД индикатором печатания, чтобы он всегда был внизу
    chat.insertBefore(msgDiv, typingIndicator);
    scrollToBottom();
}

// Показать/скрыть "печатает..."
function setTyping(isTyping) {
    if (isTyping) {
        typingIndicator.classList.remove('hidden');
        // Принудительно перемещаем в самый низ при активации
        chat.appendChild(typingIndicator);
    } else {
        typingIndicator.classList.add('hidden');
    }
    scrollToBottom();
}

// Получаем API ключ из URL параметров
const urlParams = new URLSearchParams(window.location.search);
const apiKeyFromUrl = urlParams.get('api_key');

// Очищаем URL от API ключа для безопасности и сохраняем его
if (apiKeyFromUrl) {
    localStorage.setItem("alya_groq_key", apiKeyFromUrl);
    window.history.replaceState({}, document.title, window.location.pathname);
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
    
    // Добавляем тактильный отклик Telegram
    if (tg.HapticFeedback) {
        tg.HapticFeedback.impactOccurred('light');
    }

    setTyping(true);

    try {
        // Ключ берется либо из URL (новый способ), либо из localStorage (старый способ)
        const API_KEY = apiKeyFromUrl || localStorage.getItem("alya_groq_key");
        
        if (!API_KEY) {
            setTyping(false);
            addMessage("⚠️ Ошибка: API ключ не найден. Пожалуйста, перезапустите бота или введите ключ через настройки.");
            sendBtn.disabled = false;
            return;
        }

        const response = await fetch("https://api.groq.com/openai/v1/chat/completions", {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${API_KEY}`,
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                model: "llama-3.3-70b-versatile",
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
        addMessage("Прости, я немного задумалась и не расслышала... Повторишь?", false);
        messageHistory.pop(); // Удаляем последнее сообщение юзера, так как оно не дошло
    } finally {
        sendBtn.disabled = false;
        userInput.focus();
    }
}

// Слушатели событий
sendBtn.addEventListener('click', sendMessage);

userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !sendBtn.disabled) {
        sendMessage();
    }
});

clearBtn.addEventListener('click', () => {
    if (confirm("Хочешь забыть этот диалог и начать заново?")) {
        // Тактильный отклик
        if (tg.HapticFeedback) {
            tg.HapticFeedback.notificationOccurred('success');
        }

        messageHistory = [{ role: "system", content: SYSTEM_PROMPT }];
        
        // Очищаем чат, удаляя все сообщения, но сохраняя typingIndicator (если он там есть)
        const messages = chat.querySelectorAll('.message');
        messages.forEach(msg => msg.remove());
        
        // Добавляем приветственное сообщение
        addMessage("Привет! Я Аля. О чём хочешь поговорить? 😊", false);
    }
});

// Адаптация цвета шапки под тему Telegram
tg.setHeaderColor('bg_color');