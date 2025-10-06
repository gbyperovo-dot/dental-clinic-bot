// static/js/script.js (полная обновленная версия)
document.addEventListener('DOMContentLoaded', function() {
    initializeChat();
    loadDisplayMenu();
    setupEventListeners();
    setupCalculator();
});

// Новая функция для загрузки меню с отображаемым текстом
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
        
        // Fallback: попытка загрузить через старый endpoint
        try {
            const fallbackResponse = await fetch('/menu-items');
            const fallbackMenu = await fallbackResponse.json();
            
            const menuContainer = document.getElementById('main-menu');
            if (menuContainer) {
                menuContainer.innerHTML = '';
                fallbackMenu.forEach(item => {
                    const button = document.createElement('button');
                    button.className = 'menu-btn';
                    button.textContent = item.text || item.admin_text || '';
                    button.onclick = () => handleMenuButtonClick(item.question, item.suggestion_topic || 'default');
                    menuContainer.appendChild(button);
                });
            }
        } catch (fallbackError) {
            console.error('Ошибка загрузки fallback меню:', fallbackError);
        }
    }
}

// Обработчик клика по кнопкам меню
async function handleMenuButtonClick(question, suggestionTopic = null) {
    // Отправляем основной вопрос
    sendMessage(question);
    
    // Загружаем и показываем подсказки, если указана тема
    if (suggestionTopic) {
        const suggestions = await loadSuggestions(suggestionTopic);
        displaySuggestions(suggestions);
    } else {
        // Если тема не указана, скрываем подсказки
        document.getElementById('suggestions').style.display = 'none';
    }
}

// Функция для загрузки подсказок по теме
async function loadSuggestions(topic) {
    try {
        const response = await fetch(`/suggestions/${topic}`);
        const data = await response.json();
        return data.suggestions;
    } catch (error) {
        console.error('Ошибка загрузки подсказок:', error);
        return [];
    }
}

// Функция для отображения подсказок
function displaySuggestions(suggestions) {
    const suggestionsContainer = document.getElementById('suggestions');
    if (!suggestionsContainer) return;
    
    suggestionsContainer.innerHTML = '';
    
    if (suggestions && suggestions.length > 0) {
        suggestions.forEach(suggestion => {
            const button = document.createElement('button');
            button.className = 'suggestion-btn';
            button.textContent = suggestion.text;
            button.onclick = () => sendMessage(suggestion.question);
            suggestionsContainer.appendChild(button);
        });
        suggestionsContainer.style.display = 'flex';
    } else {
        suggestionsContainer.style.display = 'none';
    }
}

function initializeChat() {
    const chatMessages = document.getElementById('chat-messages');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    
    // Загрузка истории чата из localStorage
    loadChatHistory();
    
    // Фокус на поле ввода
    userInput.focus();
    
    // Обработчик отправки сообщения
    function handleSendMessage() {
        const message = userInput.value.trim();
        if (message) {
            addMessage(message, true);
            sendMessage(message);
            userInput.value = '';
            
            // Скрываем подсказки при отправке пользовательского сообщения
            document.getElementById('suggestions').style.display = 'none';
        }
    }
    
    // События для отправки
    sendButton.addEventListener('click', handleSendMessage);
    userInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            handleSendMessage();
        }
    });
}

function setupEventListeners() {
    // Обработчики для кнопок интерфейса
    const clearButton = document.getElementById('clear-chat');
    const bookingButton = document.getElementById('booking-button');
    const calculatorButton = document.getElementById('calculator-button');
    
    if (clearButton) {
        clearButton.addEventListener('click', clearChat);
    }
    
    if (bookingButton) {
        bookingButton.addEventListener('click', () => {
            window.location.href = '/booking';
        });
    }
    
    if (calculatorButton) {
        calculatorButton.addEventListener('click', toggleCalculator);
    }
    
    // Обработчики для feedback
    setupFeedbackHandlers();
}

function setupFeedbackHandlers() {
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('feedback-btn')) {
            const messageElement = e.target.closest('.message');
            const question = messageElement?.querySelector('.message-text')?.textContent;
            const feedback = e.target.classList.contains('feedback-good') ? 1 : 0;
            
            if (question) {
                submitFeedback(question, feedback);
                
                // Визуальный feedback
                e.target.style.opacity = '0.5';
                e.target.disabled = true;
                
                const otherBtn = e.target.classList.contains('feedback-good') 
                    ? messageElement.querySelector('.feedback-bad')
                    : messageElement.querySelector('.feedback-good');
                
                if (otherBtn) {
                    otherBtn.style.opacity = '0.3';
                }
            }
        }
    });
}

async function sendMessage(message = null) {
    const userMessage = message || document.getElementById('user-input').value.trim();
    if (!userMessage) return;
    
    if (!message) {
        addMessage(userMessage, true);
        document.getElementById('user-input').value = '';
    }
    
    // Показать индикатор загрузки
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
    
    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ message: userMessage })
        });
        
        const data = await response.json();
        
        // Удалить индикатор загрузки
        const loadingElements = document.querySelectorAll('.loading');
        loadingElements.forEach(el => el.remove());
        
        // Добавить ответ
        addMessage(data.response, false, data.source);
        
        // Показать подсказки
        if (data.suggestions && data.suggestions.length > 0) {
            showSuggestions(data.suggestions);
        }
        
        // Сохранить историю
        saveChatHistory();
        
    } catch (error) {
        console.error('Ошибка:', error);
        
        // Удалить индикатор загрузки
        const loadingElements = document.querySelectorAll('.loading');
        loadingElements.forEach(el => el.remove());
        
        // Показать сообщение об ошибке
        addMessage('Извините, произошла ошибка. Попробуйте позже.', false, 'error');
    }
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
            <div class="message-source">Источник: ${source === 'knowledge_base' ? 'База знаний' : 'Yandex GPT'}</div>
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
    // Простая обработка Markdown
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>')
        .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');
}

function showSuggestions(suggestions) {
    const suggestionsContainer = document.getElementById('suggestions');
    if (!suggestionsContainer) return;
    
    suggestionsContainer.innerHTML = '';
    
    suggestions.forEach(suggestion => {
        const button = document.createElement('button');
        button.className = 'suggestion-btn';
        button.textContent = suggestion.text;
        button.onclick = () => sendMessage(suggestion.question);
        suggestionsContainer.appendChild(button);
    });
    
    suggestionsContainer.style.display = 'flex';
}

function scrollToBottom() {
    const chatMessages = document.getElementById('chat-messages');
    if (chatMessages) {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
}

function getCurrentTime() {
    return new Date().toLocaleTimeString('ru-RU', {
        hour: '2-digit',
        minute: '2-digit'
    });
}

function clearChat() {
    if (confirm('Очистить всю историю чата?')) {
        const chatMessages = document.getElementById('chat-messages');
        if (chatMessages) {
            chatMessages.innerHTML = '';
            localStorage.removeItem('chatHistory');
            
            // Также очищаем подсказки
            const suggestionsContainer = document.getElementById('suggestions');
            if (suggestionsContainer) {
                suggestionsContainer.innerHTML = '';
                suggestionsContainer.style.display = 'none';
            }
        }
    }
}

function loadChatHistory() {
    try {
        const savedHistory = localStorage.getItem('chatHistory');
        if (savedHistory) {
            const history = JSON.parse(savedHistory);
            const chatMessages = document.getElementById('chat-messages');
            
            history.forEach(msg => {
                addMessage(msg.text, msg.isUser, msg.source);
            });
        }
    } catch (error) {
        console.error('Ошибка загрузки истории:', error);
    }
}

function saveChatHistory() {
    try {
        const messages = [];
        const messageElements = document.querySelectorAll('.message');
        
        messageElements.forEach(el => {
            const isUser = el.classList.contains('user-message');
            const textElement = el.querySelector('.message-text');
            const sourceElement = el.querySelector('.message-source');
            
            if (textElement) {
                messages.push({
                    text: textElement.textContent,
                    isUser: isUser,
                    source: sourceElement ? (sourceElement.textContent.includes('База знаний') ? 'knowledge_base' : 'yandex_gpt') : null
                });
            }
        });
        
        localStorage.setItem('chatHistory', JSON.stringify(messages));
    } catch (error) {
        console.error('Ошибка сохранения истории:', error);
    }
}

async function submitFeedback(question, feedback) {
    try {
        await fetch('/feedback', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                question: question,
                feedback: feedback
            })
        });
    } catch (error) {
        console.error('Ошибка отправки feedback:', error);
    }
}

function setupCalculator() {
    const calculator = document.getElementById('calculator');
    const calcToggle = document.getElementById('calculator-button');
    const calcForm = document.getElementById('calc-form');
    const calcResult = document.getElementById('calc-result');
    const calcHistory = document.getElementById('calc-history');
    
    if (!calculator || !calcToggle) return;
    
    // Загрузка истории калькулятора
    loadCalcHistory();
    
    calcToggle.addEventListener('click', function() {
        calculator.style.display = calculator.style.display === 'none' ? 'block' : 'none';
    });
    
    if (calcForm) {
        calcForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const guests = parseInt(document.getElementById('calc-guests').value);
            const hours = parseInt(document.getElementById('calc-hours').value);
            const activity = document.getElementById('calc-activity').value;
            
            if (guests && hours) {
                const result = calculatePrice(guests, hours, activity);
                calcResult.innerHTML = `
                    <h4>Результат расчета:</h4>
                    <p>Гости: ${guests} чел.</p>
                    <p>Время: ${hours} час.</p>
                    <p>Активность: ${getActivityName(activity)}</p>
                    <p class="calc-total">Итого: ${result.total} ₽</p>
                    <p class="calc-price">Цена за гостя: ${result.pricePerGuest} ₽/час</p>
                `;
                
                // Сохранить в историю
                saveToCalcHistory({
                    guests: guests,
                    hours: hours,
                    activity: activity,
                    total: result.total,
                    timestamp: new Date().toISOString()
                });
            }
        });
    }
}

function calculatePrice(guests, hours, activity) {
    const prices = {
        'vr': 300,
        'batuts': 500,
        'nerf': 700,
        'birthday': 1000,
        'events': 800
    };
    
    const pricePerGuest = prices[activity] || 500;
    const total = guests * hours * pricePerGuest;
    
    return {
        pricePerGuest: pricePerGuest,
        total: total
    };
}

function getActivityName(activity) {
    const names = {
        'vr': 'VR-зоны',
        'batuts': 'Батутный центр',
        'nerf': 'Нерф-арена',
        'birthday': 'День рождения',
        'events': 'Мероприятия'
    };
    
    return names[activity] || activity;
}

function saveToCalcHistory(calculation) {
    try {
        let history = JSON.parse(localStorage.getItem('calcHistory') || '[]');
        history.unshift(calculation);
        
        // Ограничить историю 10 записями
        if (history.length > 10) {
            history = history.slice(0, 10);
        }
        
        localStorage.setItem('calcHistory', JSON.stringify(history));
        updateCalcHistoryDisplay();
    } catch (error) {
        console.error('Ошибка сохранения истории калькулятора:', error);
    }
}

function loadCalcHistory() {
    try {
        updateCalcHistoryDisplay();
    } catch (error) {
        console.error('Ошибка загрузки истории калькулятора:', error);
    }
}

function updateCalcHistoryDisplay() {
    const calcHistory = document.getElementById('calc-history');
    if (!calcHistory) return;
    
    try {
        const history = JSON.parse(localStorage.getItem('calcHistory') || '[]');
        
        if (history.length === 0) {
            calcHistory.innerHTML = '<p>История расчетов пуста</p>';
            return;
        }
        
        calcHistory.innerHTML = '<h4>История расчетов:</h4>' + history.map(item => `
            <div class="calc-history-item">
                <p>${getActivityName(item.activity)}: ${item.guests} чел. × ${item.hours} час.</p>
                <p class="calc-total-sm">${item.total} ₽</p>
                <small>${new Date(item.timestamp).toLocaleDateString('ru-RU')}</small>
            </div>
        `).join('');
    } catch (error) {
        console.error('Ошибка отображения истории:', error);
    }
}

function toggleCalculator() {
    const calculator = document.getElementById('calculator');
    if (calculator) {
        calculator.style.display = calculator.style.display === 'none' ? 'block' : 'none';
    }
}

// Глобальные функции для доступа из других скриптов
window.chatFunctions = {
    sendMessage: sendMessage,
    addMessage: addMessage,
    clearChat: clearChat,
    loadDisplayMenu: loadDisplayMenu,
    handleMenuButtonClick: handleMenuButtonClick
};