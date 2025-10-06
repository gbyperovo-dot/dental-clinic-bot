// static/js/script.js — Основной скрипт чат-бота D-Space
// Обновлено: добавлен голосовой ввод и озвучка ответов

document.addEventListener('DOMContentLoaded', function () {
    initializeChat();
    loadDisplayMenu();
    setupEventListeners();
    setupCalculator();

    // === ГОЛОСОВОЙ ВВОД И ОТВЕТ ===
    const voiceInputBtn = document.getElementById('voice-input-btn');
    const recordingIndicator = document.getElementById('recording-indicator');

    // Утилиты для очистки Markdown при озвучке
    function stripMarkdown(text) {
        return text
            .replace(/\*\*(.*?)\*\*/g, '$1')           // жирный
            .replace(/\*(.*?)\*/g, '$1')               // курсив
            .replace(/~~(.*?)~~/g, '$1')               // зачеркнутый
            .replace(/`(.*?)`/g, '$1')                 // инлайн-код
            .replace(/!\[.*?\]\(.*?\)/g, '')           // изображения
            .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')   // ссылки
            .replace(/[#>*\-+=[\]{}()|]/g, ' ')        // прочие символы
            .replace(/\s+/g, ' ')                      // лишние пробелы
            .trim();
    }

    // Функция озвучивания текста
    function speakText(text) {
        if ('speechSynthesis' in window) {
            const utterance = new SpeechSynthesisUtterance(stripMarkdown(text));
            utterance.lang = 'ru-RU';
            utterance.rate = 0.9;
            utterance.pitch = 1;
            utterance.volume = 1;
            speechSynthesis.speak(utterance);
        }
    }

    // Поддержка Web Speech API
    if ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window) {
        const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognition = new Recognition();

        recognition.lang = 'ru-RU';
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript.trim();
            if (transcript) {
                sendMessage(transcript);
            }
            stopVoiceRecording();
        };

        recognition.onerror = (event) => {
            console.error('Ошибка распознавания:', event.error);
            alert('Не удалось распознать речь. Попробуйте снова.');
            stopVoiceRecording();
        };

        recognition.onend = () => {
            stopVoiceRecording();
        };

        function startVoiceRecording() {
            try {
                recognition.start();
                recordingIndicator.style.display = 'block';
                voiceInputBtn.disabled = true;
                voiceInputBtn.innerHTML = '🔴';
            } catch (error) {
                console.error('Ошибка запуска микрофона:', error);
                alert('Не удалось запустить микрофон. Проверьте доступ к микрофону.');
            }
        }

        function stopVoiceRecording() {
            recognition.stop();
            recordingIndicator.style.display = 'none';
            voiceInputBtn.disabled = false;
            voiceInputBtn.innerHTML = '🎤';
        }

        if (voiceInputBtn) {
            voiceInputBtn.addEventListener('click', startVoiceRecording);
        }
    } else {
        // Скрыть кнопку, если не поддерживается
        if (voiceInputBtn) {
            voiceInputBtn.style.display = 'none';
        }
        console.warn('Web Speech API не поддерживается в этом браузере.');
    }

    // Интеграция озвучки в получение ответа бота
    const originalSendMessage = window.sendMessage || sendMessage;

    // Переопределяем или расширяем sendMessage
    window.sendMessage = function (message = null) {
        const userMessage = message || document.getElementById('user-input')?.value.trim();
        if (!userMessage) return;

        // Отправляем как пользовательское сообщение
        if (!message) {
            addMessage(userMessage, true);
            document.getElementById('user-input').value = '';
        }

        // Показываем индикатор загрузки
        const loadingElement = document.createElement('div');
        loadingElement.className = 'message bot-message loading';
        loadingElement.innerHTML = `
            <div class="message-text">
                <div class="typing-indicator">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
            </div>
        `;
        document.getElementById('chat-messages').appendChild(loadingElement);
        scrollToBottom();

        fetch('/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                question: userMessage,
                user_id: "user_" + (Date.now() % 10000)
            })
        })
        .then(r => r.json())
        .then(data => {
            // Удаляем индикатор загрузки
            const loadingElements = document.querySelectorAll('.loading');
            loadingElements.forEach(el => el.remove());

            // Добавляем ответ бота
            addMessage(data.answer, false, data.source ? (data.source === 'knowledge_base' ? 'База знаний' : 'Yandex GPT') : null);

            // 🔊 Озвучиваем ответ
            speakText(data.answer);

            // Показываем контекстные подсказки
            if (data.topic) {
                showSuggestionsForAnswer(data.answer);
            }

            saveChatHistory();
        })
        .catch(err => {
            const loadingElements = document.querySelectorAll('.loading');
            loadingElements.forEach(el => el.remove());
            addMessage('🚫 Ошибка подключения. Попробуйте позже.', false, 'error');
        });
    };
});

// === ОСНОВНЫЕ ФУНКЦИИ ЧАТА ===

function initializeChat() {
    const chatMessages = document.getElementById('chat-messages');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');

    loadChatHistory();
    userInput.focus();

    function handleSendMessage() {
        const message = userInput.value.trim();
        if (message) {
            window.sendMessage(message);
        }
    }

    sendButton?.addEventListener('click', handleSendMessage);
    userInput?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleSendMessage();
    });
}

function setupEventListeners() {
    const clearButton = document.getElementById('clear-chat');
    const bookingButton = document.getElementById('booking-button');
    const calculatorButton = document.getElementById('calculator-button');

    clearButton?.addEventListener('click', clearChat);
    bookingButton?.addEventListener('click', () => window.location.href = '/booking');
    calculatorButton?.addEventListener('click', toggleCalculator);

    setupFeedbackHandlers();
}

function setupFeedbackHandlers() {
    document.addEventListener('click', function (e) {
        if (e.target.classList.contains('feedback-btn')) {
            const messageElement = e.target.closest('.message');
            const question = messageElement?.querySelector('.message-text')?.textContent;
            const feedback = e.target.classList.contains('feedback-good') ? 1 : 0;

            if (question) {
                submitFeedback(question, feedback);
                e.target.style.opacity = '0.5';
                e.target.disabled = true;

                const otherBtn = e.target.classList.contains('feedback-good')
                    ? messageElement.querySelector('.feedback-bad')
                    : messageElement.querySelector('.feedback-good');
                if (otherBtn) otherBtn.style.opacity = '0.3';
            }
        }
    });
}

function addMessage(text, isUser = false, source = null) {
    const chatMessages = document.getElementById('chat-messages');
    const messageElement = document.createElement('div');
    messageElement.className = `message ${isUser ? 'user-message' : 'bot-message'}`;

    let messageHTML = `
        <div class="message-text">${formatMessage(text)}</div>
        <div class="message-time">${getCurrentTime()}</div>
    `;

    if (!isUser && source) {
        messageHTML += `
            <div class="message-source">Источник: ${source}</div>
            <div class="feedback-buttons">
                <button class="feedback-btn feedback-good" title="Понравилось">👍</button>
                <button class="feedback-btn feedback-bad" title="Не понравилось">👎</button>
            </div>
        `;
    }

    messageElement.innerHTML = messageHTML;
    chatMessages.appendChild(messageElement);
    scrollToBottom();
}

function formatMessage(text) {
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>')
        .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');
}

async function loadDisplayMenu() {
    try {
        const response = await fetch('/api/menu-display');
        const menuItems = await response.json();
        const menuContainer = document.getElementById('main-menu');
        if (!menuContainer) return;

        menuContainer.innerHTML = '';
        menuItems.forEach(item => {
            const button = document.createElement('button');
            button.className = 'menu-btn';
            button.textContent = item.text;
            button.onclick = () => handleMenuButtonClick(item.question, item.suggestion_topic);
            menuContainer.appendChild(button);
        });
    } catch (error) {
        console.error('Ошибка загрузки меню:', error);
    }
}

async function handleMenuButtonClick(question, suggestionTopic = null) {
    window.sendMessage(question);

    if (suggestionTopic) {
        const suggestions = await loadSuggestions(suggestionTopic);
        displaySuggestions(suggestions);
    } else {
        document.getElementById('suggestions')?.style.display = 'none';
    }
}

async function loadSuggestions(topic) {
    try {
        const response = await fetch(`/suggestions/${topic}`);
        const data = await response.json();
        return data.suggestions || [];
    } catch (error) {
        console.error('Ошибка загрузки подсказок:', error);
        return [];
    }
}

function displaySuggestions(suggestions) {
    const container = document.getElementById('suggestions');
    if (!container) return;

    container.innerHTML = '';
    if (suggestions.length > 0) {
        suggestions.forEach(suggestion => {
            const button = document.createElement('button');
            button.className = 'suggestion-btn';
            button.textContent = suggestion.text;
            button.onclick = () => window.sendMessage(suggestion.question);
            container.appendChild(button);
        });
        container.style.display = 'flex';
    } else {
        container.style.display = 'none';
    }
}

function scrollToBottom() {
    const chat = document.getElementById('chat-messages');
    if (chat) chat.scrollTop = chat.scrollHeight;
}

function getCurrentTime() {
    return new Date().toLocaleTimeString('ru-RU', {
        hour: '2-digit',
        minute: '2-digit'
    });
}

function clearChat() {
    if (confirm('Очистить всю историю чата?')) {
        const chat = document.getElementById('chat-messages');
        if (chat) chat.innerHTML = '';
        localStorage.removeItem('chatHistory');

        const suggestions = document.getElementById('suggestions');
        if (suggestions) {
            suggestions.innerHTML = '';
            suggestions.style.display = 'none';
        }
    }
}

function loadChatHistory() {
    try {
        const saved = localStorage.getItem('chatHistory');
        if (saved) {
            const history = JSON.parse(saved);
            history.forEach(msg => addMessage(msg.text, msg.isUser, msg.source));
        }
    } catch (e) {
        console.error('Ошибка загрузки истории:', e);
    }
}

function saveChatHistory() {
    try {
        const messages = [];
        document.querySelectorAll('.message').forEach(el => {
            const isUser = el.classList.contains('user-message');
            const textEl = el.querySelector('.message-text');
            const sourceEl = el.querySelector('.message-source');
            if (textEl) {
                messages.push({
                    text: textEl.textContent,
                    isUser,
                    source: sourceEl ? sourceEl.textContent.replace('Источник: ', '') : null
                });
            }
        });
        localStorage.setItem('chatHistory', JSON.stringify(messages));
    } catch (e) {
        console.error('Ошибка сохранения истории:', e);
    }
}

async function submitFeedback(question, feedback) {
    try {
        await fetch('/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, feedback })
        });
    } catch (e) {
        console.error('Ошибка отправки отзыва:', e);
    }
}

// === Калькулятор ===
function setupCalculator() {
    const calc = document.getElementById('calculator');
    const toggle = document.getElementById('calculator-button');
    const form = document.getElementById('calc-form');
    const result = document.getElementById('calc-result');

    toggle?.addEventListener('click', () => {
        calc.style.display = calc.style.display === 'none' ? 'block' : 'none';
    });

    form?.addEventListener('submit', function (e) {
        e.preventDefault();
        const guests = parseInt(document.getElementById('calc-guests').value);
        const hours = parseInt(document.getElementById('calc-hours').value);
        const activity = document.getElementById('calc-activity').value;

        if (guests && hours) {
            const priceData = calculatePrice(guests, hours, activity);
            result.innerHTML = `
                <h4>Результат:</h4>
                <p>Гости: ${guests} чел.</p>
                <p>Часы: ${hours}</p>
                <p>Активность: ${getActivityName(activity)}</p>
                <p class="calc-total">Итого: ${priceData.total} ₽</p>
            `;
            saveToCalcHistory({ guests, hours, activity, total: priceData.total, timestamp: new Date().toISOString() });
        }
    });

    loadCalcHistory();
}

function calculatePrice(guests, hours, activity) {
    const prices = { vr: 300, batuts: 500, nerf: 700, birthday: 1000, events: 800 };
    const ppg = prices[activity] || 500;
    return { pricePerGuest: ppg, total: guests * hours * ppg };
}

function getActivityName(activity) {
    return {
        vr: 'VR-зоны',
        batuts: 'Батутный центр',
        nerf: 'Нерф-арена',
        birthday: 'День рождения',
        events: 'Мероприятия'
    }[activity] || activity;
}

function saveToCalcHistory(calc) {
    try {
        let history = JSON.parse(localStorage.getItem('calcHistory') || '[]');
        history.unshift(calc);
        if (history.length > 10) history = history.slice(0, 10);
        localStorage.setItem('calcHistory', JSON.stringify(history));
        updateCalcHistoryDisplay();
    } catch (e) {
        console.error('Ошибка сохранения истории калькулятора:', e);
    }
}

function loadCalcHistory() {
    updateCalcHistoryDisplay();
}

function updateCalcHistoryDisplay() {
    const container = document.getElementById('calc-history');
    if (!container) return;

    try {
        const history = JSON.parse(localStorage.getItem('calcHistory') || '[]');
        if (history.length === 0) {
            container.innerHTML = '<p>История пуста</p>';
            return;
        }

        container.innerHTML = '<h4>История:</h4>' + history.map(item => `
            <div class="calc-history-item">
                <p>${getActivityName(item.activity)}: ${item.guests}×${item.hours}ч</p>
                <p class="calc-total-sm">${item.total} ₽</p>
                <small>${new Date(item.timestamp).toLocaleDateString('ru-RU')}</small>
            </div>
        `).join('');
    } catch (e) {
        console.error('Ошибка отображения истории:', e);
    }
}

function toggleCalculator() {
    const calc = document.getElementById('calculator');
    if (calc) calc.style.display = calc.style.display === 'none' ? 'block' : 'none';
}

// Экспорт для внешнего использования
window.chatFunctions = {
    sendMessage: window.sendMessage,
    addMessage,
    clearChat,
    loadDisplayMenu,
    handleMenuButtonClick
};