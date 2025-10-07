# web_app.py
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, send_from_directory, abort, make_response, Response
import os
import json
import time
import shutil
from datetime import datetime
from dotenv import load_dotenv
import requests
import socket
import logging
import re
import functools
from urllib.parse import unquote, quote

# - Настройка логирования -
logging.basicConfig(filename='audit.log',
                    level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# - Загрузка переменных окружения -
load_dotenv()

# - Создание приложения -
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "super-secret-key-for-d-space-bot")

# - ОТКЛЮЧЕНИЕ КЭШИРОВАНИЯ -
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# - Глобальные переменные -
KNOWLEDGE_BASE = {}
BOOKINGS = []
conversation_history = {}
LOG_FILE = "bot_log.json"
BACKUPS_DIR = "backups"
os.makedirs(BACKUPS_DIR, exist_ok=True)

# - Пути -
KNOWLEDGE_FILE = "knowledge_base.json"
BOOKINGS_FILE = "bookings.json"
SUGGESTIONS_FILE = "suggestions.json"
MENU_FILE = "menu.json"
MENU_CATEGORIES_FILE = "menu_categories.json"

# - Константы системных категорий меню -
SYSTEM_CATEGORIES = ['attractions', 'events', 'services', 'info']

# - Глобальная переменная -
suggestionMap = {}
MENU_CACHE = None

# --- Умная система базы знаний: PostgreSQL или файловая ---
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    import urllib.parse as urlparse
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    print("ℹ️  psycopg2 не установлен, используем файловую базу знаний")

def get_db_connection():
    """Создает подключение к PostgreSQL с SSL"""
    if not POSTGRES_AVAILABLE:
        return None
        
    try:
        database_url = os.getenv('DATABASE_URL')
        
        if not database_url:
            return None
            
        # Парсим URL для Render
        url = urlparse.urlparse(database_url)
        
        # Подключение с SSL для Render
        conn = psycopg2.connect(
            database=url.path[1:],
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port,
            sslmode='require',  # 🔥 Ключевое изменение
            sslrootcert=''      # Пустая строка для автоматического определения
        )
        return conn
    except Exception as e:
        print(f"❌ Ошибка подключения к PostgreSQL: {e}")
        return None

def init_knowledge_db():
    """Создает таблицу для базы знаний при первом запуске (только если есть DATABASE_URL)"""
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("ℹ️  DATABASE_URL не найден, используем файловую базу знаний")
        return False
        
    conn = get_db_connection()
    if not conn:
        return False
        
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id SERIAL PRIMARY KEY,
                question TEXT UNIQUE NOT NULL,
                answer TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255) DEFAULT 'system'
            )
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Таблица knowledge_base готова в PostgreSQL")
        return True
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")
        return False

def get_default_knowledge():
    """Возвращает базовую базу знаний"""
    return {
        "привет": "👋 Привет! Рад вас видеть в D-Space! \nГотов помочь с выбором услуг",
        "пока": "👋 До свидания! Приходите еще!",
        "спасибо": "Пожалуйста! Рад был помочь! 😊"
    }

def load_knowledge_base():
    """Загружает базу знаний из PostgreSQL или файла"""
    global KNOWLEDGE_BASE
    
    # Пытаемся загрузить из PostgreSQL
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT question, answer FROM knowledge_base ORDER BY question")
            rows = cur.fetchall()
            KNOWLEDGE_BASE = {row['question']: row['answer'] for row in rows}
            print(f"✅ База знаний загружена из PostgreSQL ({len(KNOWLEDGE_BASE)} записей)")
            cur.close()
            conn.close()
            return
        except Exception as e:
            print(f"❌ Ошибка загрузки из PostgreSQL: {e}")
    
    # Если PostgreSQL недоступен, загружаем из файла
    if os.path.exists(KNOWLEDGE_FILE):
        try:
            with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
                KNOWLEDGE_BASE = json.load(f)
            print(f"✅ База знаний загружена из файла ({len(KNOWLEDGE_BASE)} записей)")
        except Exception as e:
            print(f"❌ Ошибка загрузки из файла: {e}")
            KNOWLEDGE_BASE = get_default_knowledge()
    else:
        KNOWLEDGE_BASE = get_default_knowledge()
        # Сохраняем дефолтную базу в файл
        try:
            with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
                json.dump(KNOWLEDGE_BASE, f, ensure_ascii=False, indent=4)
            print("✅ Создана файловая база знаний по умолчанию")
        except Exception as e:
            print(f"❌ Ошибка создания файла: {e}")

def save_knowledge_base():
    """Сохраняет базу знаний в PostgreSQL или файл"""
    # Пытаемся сохранить в PostgreSQL
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM knowledge_base")
            
            for question, answer in KNOWLEDGE_BASE.items():
                cur.execute(
                    "INSERT INTO knowledge_base (question, answer) VALUES (%s, %s)",
                    (question.strip().lower(), answer.strip())
                )
            
            conn.commit()
            cur.close()
            conn.close()
            print("✅ База знаний сохранена в PostgreSQL")
            return True
        except Exception as e:
            print(f"❌ Ошибка сохранения в PostgreSQL: {e}")
    
    # Сохраняем в файл
    try:
        with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
            json.dump(KNOWLEDGE_BASE, f, ensure_ascii=False, indent=4)
        print("✅ База знаний сохранена в файл")
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения в файл: {e}")
        return False

def add_knowledge_item(question, answer, created_by="admin"):
    """Добавляет новый вопрос-ответ в базу знаний"""
    # Пытаемся добавить в PostgreSQL
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO knowledge_base (question, answer, created_by) 
                VALUES (%s, %s, %s)
                ON CONFLICT (question) 
                DO UPDATE SET 
                    answer = EXCLUDED.answer,
                    updated_at = CURRENT_TIMESTAMP
            """, (question.strip().lower(), answer.strip(), created_by))
            
            conn.commit()
            cur.close()
            conn.close()
            print(f"✅ Вопрос добавлен в PostgreSQL: '{question}'")
        except Exception as e:
            print(f"❌ Ошибка добавления в PostgreSQL: {e}")
    
    # Добавляем в локальную переменную и сохраняем в файл
    KNOWLEDGE_BASE[question.strip().lower()] = answer.strip()
    
    # Сохраняем в файл (для резервной копии)
    try:
        with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
            json.dump(KNOWLEDGE_BASE, f, ensure_ascii=False, indent=4)
        print(f"✅ Вопрос сохранен в файл: '{question}'")
    except Exception as e:
        print(f"❌ Ошибка сохранения в файл: {e}")
    
    return True

def update_knowledge_item(old_question, new_question, answer, created_by="admin"):
    """Обновляет вопрос-ответ в базе знаний"""
    # Пытаемся обновить в PostgreSQL
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            
            if old_question != new_question:
                # Если вопрос изменился, нужно удалить старую запись и создать новую
                cur.execute("DELETE FROM knowledge_base WHERE question = %s", (old_question,))
            
            cur.execute("""
                INSERT INTO knowledge_base (question, answer, created_by) 
                VALUES (%s, %s, %s)
                ON CONFLICT (question) 
                DO UPDATE SET 
                    answer = EXCLUDED.answer,
                    updated_at = CURRENT_TIMESTAMP
            """, (new_question.strip().lower(), answer.strip(), created_by))
            
            conn.commit()
            cur.close()
            conn.close()
            print(f"✅ Вопрос обновлен в PostgreSQL: '{old_question}' -> '{new_question}'")
        except Exception as e:
            print(f"❌ Ошибка обновления в PostgreSQL: {e}")
    
    # Обновляем в локальной переменной
    if old_question in KNOWLEDGE_BASE:
        del KNOWLEDGE_BASE[old_question]
    KNOWLEDGE_BASE[new_question.strip().lower()] = answer.strip()
    
    # Сохраняем в файл
    try:
        with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
            json.dump(KNOWLEDGE_BASE, f, ensure_ascii=False, indent=4)
        print(f"✅ Вопрос обновлен в файле: '{old_question}' -> '{new_question}'")
    except Exception as e:
        print(f"❌ Ошибка сохранения в файл: {e}")
    
    return True

def delete_knowledge_item(question):
    """Удаляет вопрос из базы знаний"""
    # Пытаемся удалить из PostgreSQL
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM knowledge_base WHERE question = %s", (question.strip().lower(),))
            conn.commit()
            cur.close()
            conn.close()
            print(f"✅ Вопрос удален из PostgreSQL: '{question}'")
        except Exception as e:
            print(f"❌ Ошибка удаления из PostgreSQL: {e}")
    
    # Удаляем из локальной переменной и сохраняем в файл
    if question in KNOWLEDGE_BASE:
        del KNOWLEDGE_BASE[question]
        
        # Сохраняем в файл
        try:
            with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
                json.dump(KNOWLEDGE_BASE, f, ensure_ascii=False, indent=4)
            print(f"✅ Вопрос удален из файла: '{question}'")
            return True
        except Exception as e:
            print(f"❌ Ошибка сохранения в файл: {e}")
            return False
    
    return False

def search_knowledge(query):
    """Ищет вопросы в базе знаний"""
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT question, answer 
                FROM knowledge_base 
                WHERE question ILIKE %s
                ORDER BY question
            """, (f'%{query}%',))
            
            results = cur.fetchall()
            cur.close()
            conn.close()
            return results
        except Exception as e:
            print(f"❌ Ошибка поиска в PostgreSQL: {e}")
    
    # Если PostgreSQL недоступен, ищем в локальной базе
    results = []
    for question, answer in KNOWLEDGE_BASE.items():
        if query.lower() in question.lower():
            results.append({'question': question, 'answer': answer})
    return results

# - Декоратор для отключения кэширования -
def no_cache(view):
    @functools.wraps(view)
    def no_cache_view(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    return no_cache_view

# - Вспомогательные функции -

def normalize_text(text):
    """Нормализует текст для поиска: приводит к нижнему регистру, удаляет знаки препинания"""
    if not text:
        return ""
    
    # Приводим к нижнему регистру
    text = text.lower()
    
    # Удаляем знаки препинания (сохраняем только буквы, цифры и пробелы)
    text = re.sub(r'[^\w\s]', '', text)
    
    # Заменяем множественные пробелы на один
    text = re.sub(r'\s+', ' ', text)
    
    # Удаляем пробелы в начале и конце
    return text.strip()

def find_in_knowledge_base(question):
    """Ищет наиболее релевантный ответ в базе знаний с учетом нормализации"""
    normalized_question = normalize_text(question)
    
    # Сначала проверяем точное совпадение (оригинальный вопрос)
    if question in KNOWLEDGE_BASE:
        return KNOWLEDGE_BASE[question]
    
    # Проверяем точное совпадение после нормализации
    for key, value in KNOWLEDGE_BASE.items():
        if normalize_text(key) == normalized_question:
            return value
    
    # Ищем частичное совпадение (если нормализованный вопрос содержит ключ)
    for key, value in KNOWLEDGE_BASE.items():
        normalized_key = normalize_text(key)
        if normalized_key in normalized_question or normalized_question in normalized_key:
            return value
    
    # Ищем совпадение по словам (если есть общие значимые слова)
    question_words = set(normalized_question.split())
    if len(question_words) > 1:  # Только если в вопросе больше одного слова
        best_match = None
        best_score = 0
        
        for key, value in KNOWLEDGE_BASE.items():
            normalized_key = normalize_text(key)
            key_words = set(normalized_key.split())
            
            # Считаем количество совпадающих слов
            common_words = question_words.intersection(key_words)
            score = len(common_words)
            
            # Учитываем длину вопроса чтобы избежать ложных срабатываний
            if score > best_score and score >= max(1, len(question_words) * 0.5):
                best_score = score
                best_match = value
        
        if best_match:
            return best_match
    
    return None

def load_bookings():
    """Загружает бронирования из JSON"""
    global BOOKINGS
    if os.path.exists(BOOKINGS_FILE):
        try:
            with open(BOOKINGS_FILE, "r", encoding="utf-8") as f:
                BOOKINGS = json.load(f)
            print("✅ Бронирования загружены")
        except Exception as e:
            print(f"❌ Ошибка загрузки бронирований: {e}")
    else:
        BOOKINGS = []
        print("✅ Создан файл бронирований по умолчанию")

def save_bookings():
    """Сохраняет бронирования в JSON"""
    try:
        with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(BOOKINGS, f, ensure_ascii=False, indent=4)
        print("✅ Бронирования сохранены")
    except Exception as e:
        print(f"❌ Ошибка сохранения бронирований: {e}")

def load_suggestion_map():
    """Загружает контекстные подсказки из JSON"""
    global suggestionMap
    # Пытаемся загрузить из файла
    if os.path.exists(SUGGESTIONS_FILE):
        try:
            with open(SUGGESTIONS_FILE, "r", encoding="utf-8") as f:
                suggestionMap = json.load(f)
            print("✅ Подсказки загружены из файла")
            return  # Выходим после успешной загрузки
        except Exception as e:
            print(f"❌ Ошибка загрузки подсказок: {e}")
            suggestionMap = {}
    # Создаем дефолтные подсказки ТОЛЬКО если файла нет или ошибка загрузки
    suggestionMap = {
        "vr": [
            {"text": "Игры", "question": "игры в vr", "answer": "У нас есть различные VR-игры: экшены, гонки, головоломки! 🎮"},
            {"text": "Цены", "question": "стоимость vr", "answer": "VR-сеанс стоит от 300 рублей за 30 минут! 💰"},
            {"text": "Забронировать", "question": "забронировать vr", "answer": "Чтобы забронировать VR, перейдите на страницу бронирования! 📅"},
            {"text": "Правила", "question": "правила безопасности в vr", "answer": "В VR-зоне необходимо соблюдать технику безопасности! ⚠️"}
        ],
        "батуты": [
            {"text": "Для деток?", "question": "можно ли на батуты с маленькими детьми", "answer": "Да, у нас есть специальные батуты для детей от 3 лет! 👶"},
            {"text": "Цены", "question": "стоимость батутов", "answer": "Батутный центр - от 500 рублей за час! 🏀"},
            {"text": "Забронировать", "question": "забронировать батуты", "answer": "Забронируйте батуты через нашу систему бронирования! 🎯"},
            {"text": "Аниматор", "question": "есть ли аниматор на батуты", "answer": "Да, мы предоставляем услуги аниматора для детских праздников! 🎪"}
        ],
        "default": [
            {"text": "Забронировать", "question": "хочу забронировать", "answer": "Перейдите на страницу бронирования для оформления заказа! 📋"},
            {"text": "Цены", "question": "цены", "answer": "Цены зависят от выбранного аттракциона. Уточните у нашего менеджера! 💵"}
        ]
    }
    # Сохраняем дефолтные подсказки только при первом создании
    try:
        with open(SUGGESTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(suggestionMap, f, ensure_ascii=False, indent=4)
        print("✅ Создан файл suggestions.json по умолчанию")
    except Exception as e:
        print(f"❌ Ошибка сохранения подсказок: {e}")

def save_suggestion_map():
    """Сохраняет контекстные подсказки в JSON"""
    try:
        with open(SUGGESTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(suggestionMap, f, ensure_ascii=False, indent=4)
        print("✅ Подсказки сохранены")
    except Exception as e:
        print(f"❌ Ошибка сохранения подсказок: {e}")

def load_menu_categories():
    """Загружает категории меню из JSON файла."""
    if os.path.exists(MENU_CATEGORIES_FILE):
        try:
            with open(MENU_CATEGORIES_FILE, 'r', encoding='utf-8') as f:
                categories = json.load(f)
            # Преобразуем в структуру, ожидаемую шаблоном
            return {
                "system_categories": {
                    "attractions": "🎪 Аттракционы",
                    "events": "🎉 Мероприятия",
                    "services": "🛠️ Услуги",
                    "info": "ℹ️ Информация"
                },
                "custom_categories": {k: v for k, v in categories.items() 
                                    if k not in ['attractions', 'events', 'services', 'info']}
            }
        except Exception as e:
            print(f"❌ Ошибка загрузки категорий меню: {e}")
            return {
                "system_categories": {
                    "attractions": "🎪 Аттракционы",
                    "events": "🎉 Мероприятия",
                    "services": "🛠️ Услуги",
                    "info": "ℹ️ Информация"
                },
                "custom_categories": {}
            }
    else:
        default_categories = {
            "attractions": "🎪 Аттракционы",
            "events": "🎉 Мероприятия",
            "services": "🛠️ Услуги",
            "info": "ℹ️ Информация"
        }
        save_menu_categories(default_categories)
        return {
            "system_categories": default_categories,
            "custom_categories": {}
        }

def save_menu_categories(categories_dict):
    """Сохраняет категории меню в JSON файл."""
    try:
        # Сохраняем как плоский словарь для обратной совместимости
        flat_categories = {}
        if "system_categories" in categories_dict:
            flat_categories.update(categories_dict["system_categories"])
        if "custom_categories" in categories_dict:
            flat_categories.update(categories_dict["custom_categories"])
        with open(MENU_CATEGORIES_FILE, 'w', encoding='utf-8') as f:
            json.dump(flat_categories, f, ensure_ascii=False, indent=2)
        print("✅ Категории меню сохранены")
    except Exception as e:
        print(f"❌ Ошибка сохранения категорий меню: {e}")

def load_menu():
    """Загружает меню из JSON"""
    global MENU_CACHE
    # Используем кэш если есть
    if MENU_CACHE is not None:
        return MENU_CACHE
    menu_items = []
    if os.path.exists(MENU_FILE):
        try:
            with open(MENU_FILE, "r", encoding="utf-8") as f:
                menu_items = json.load(f)
            print("✅ Меню загружено")
            MENU_CACHE = menu_items
        except Exception as e:
            print(f"❌ Ошибка загрузки меню: {e}")
    else:
        menu_items = [
            {"admin_text": "VR-зоны", "display_text": "🎮 VR-зоны — от 300 ₽", "question": "vr", "category": "attractions", "price_info": "от 300 ₽", "suggestion_topic": "vr"},
            {"admin_text": "Батуты", "display_text": "🏀 Батутный центр — от 500 ₽", "question": "батуты", "category": "attractions", "price_info": "от 500 ₽", "suggestion_topic": "батуты"},
            {"admin_text": "Нерф", "display_text": "🔫 Нерф-арена — от 2500 ₽", "question": "нерф", "category": "attractions", "price_info": "от 2500 ₽", "suggestion_topic": "default"},
            {"admin_text": "День рождения", "display_text": "🎉 День рождения", "question": "день рождения", "category": "events", "price_info": "", "suggestion_topic": "default"},
            {"admin_text": "Выпускные", "display_text": "🎓 Выпускные", "question": "выпускные", "category": "events", "price_info": "", "suggestion_topic": "default"},
            {"admin_text": "Мероприятия", "display_text": "🎪 Мероприятия", "question": "мероприятия", "category": "events", "price_info": "", "suggestion_topic": "default"}
        ]
        with open(MENU_FILE, "w", encoding="utf-8") as f:
            json.dump(menu_items, f, ensure_ascii=False, indent=4)
        print("✅ Создан файл menu.json по умолчанию")
        MENU_CACHE = menu_items
    return menu_items

def save_menu(menu_items):
    """Сохраняет меню в JSON"""
    try:
        with open(MENU_FILE, "w", encoding="utf-8") as f:
            json.dump(menu_items, f, ensure_ascii=False, indent=4)
        print("✅ Меню сохранено")
        # 🔥 Принудительно обновляем глобальную переменную
        global MENU_CACHE
        MENU_CACHE = menu_items
    except Exception as e:
        print(f"❌ Ошибка сохранения меню: {e}")

# - Загрузка данных при старте -
load_knowledge_base()
load_bookings()
load_suggestion_map()
load_menu()

# - Маршруты -

@app.route("/debug-database")
def debug_database():
    """Диагностика базы данных"""
    database_url = os.getenv('DATABASE_URL')
    file_exists = os.path.exists(KNOWLEDGE_FILE)
    
    # Пытаемся подключиться к PostgreSQL
    postgres_status = "unknown"
    postgres_count = 0
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as count FROM knowledge_base")
            result = cur.fetchone()
            postgres_count = result[0] if result else 0
            postgres_status = "connected"
            cur.close()
            conn.close()
        except Exception as e:
            postgres_status = f"error: {e}"
    else:
        postgres_status = "not_connected"
    
    # Считаем записи в файле
    file_count = len(KNOWLEDGE_BASE) if KNOWLEDGE_BASE else 0
    
    debug_info = {
        "postgres_available": POSTGRES_AVAILABLE,
        "database_url_set": bool(database_url),
        "postgres_status": postgres_status,
        "postgres_record_count": postgres_count,
        "file_exists": file_exists,
        "file_record_count": file_count,
        "knowledge_base_keys": list(KNOWLEDGE_BASE.keys())[:10] if KNOWLEDGE_BASE else [],
        "current_mode": "PostgreSQL" if postgres_status == "connected" else "File"
    }
    
    return jsonify(debug_info)

@app.route("/clear-menu-cache")
def clear_menu_cache():
    global MENU_CACHE
    MENU_CACHE = None
    load_menu()
    return "✅ Кэш меню очищен!"

@app.route("/voice-ask", methods=["POST"])
def voice_ask():
    """Обработка голосовых запросов"""
    try:
        data = request.json
        question = data.get("question", "").strip().lower()
        
        if not question:
            return jsonify({"answer": "Голосовое сообщение не распознано. Попробуйте еще раз."})
        
        # Логируем голосовой запрос
        logging.info(f"🎤 Голосовой запрос: {question}")
        
        # Обрабатываем как обычный текстовый запрос
        response = find_in_knowledge_base(question)
        source = "knowledge_base"
        
        if not response:
            try:
                response = call_yandex_gpt(question)
                source = "yandex_gpt"
            except Exception as e:
                response = f"❌ Ошибка обработки запроса: {str(e)}"
                source = "error"
        
        log_interaction(f"[VOICE] {question}", response, source)
        return jsonify({"answer": response})
        
    except Exception as e:
        print(f"❌ Ошибка обработки голосового запроса: {e}")
        return jsonify({"answer": "❌ Произошла ошибка при обработке голосового запроса"})

@app.route("/")
def index():
    """Главная страница"""
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    """Упрощенная и исправленная версия обработки чата"""
    try:
        data = request.json
        question = data.get("message", "").strip()
        
        print(f"\n🔍 ===== НОВЫЙ ЗАПРОС: '{question}' =====")

        if not question:
            return jsonify({"response": "Пожалуйста, задайте вопрос.", "source": "error", "suggestions": []})

        # 🔥 УПРОЩЕННАЯ ЛОГИКА - ШАГ 1: Ищем тему в меню
        menu_items = load_menu()
        menu_topic = None
        
        for item in menu_items:
            # Используем нормализацию для поиска в меню
            if normalize_text(item["question"]) == normalize_text(question):
                menu_topic = item.get("suggestion_topic")
                print(f"✅ Найдена тема в меню: '{menu_topic}'")
                break
        
        # 🔥 ШАГ 2: Если тема не найдена, используем дефолтные подсказки
        if not menu_topic:
            print("❌ Тема не найдена в меню, используем дефолтные подсказки")
            suggestions = [{"text": s["text"], "question": s["question"]} for s in suggestionMap.get("default", [])]
            
            # 🔥 ИСПОЛЬЗУЕМ ИНТЕЛЛЕКТУАЛЬНЫЙ ПОИСК В БАЗЕ ЗНАНИЙ
            response = find_in_knowledge_base(question) or call_yandex_gpt(question)
            source = "knowledge_base" if find_in_knowledge_base(question) else "yandex_gpt"
            
            # ✅ ДОБАВЛЕНО: Записываем в лог
            log_interaction(question, response, source)
            
            return jsonify({
                "response": response,
                "source": source,
                "suggestions": suggestions
            })
        
        # 🔥 ШАГ 3: Получаем подсказки для темы
        topic_suggestions = suggestionMap.get(menu_topic, [])
        suggestions = [{"text": s["text"], "question": s["question"]} for s in topic_suggestions]
        print(f"📋 Подсказок для темы '{menu_topic}': {len(suggestions)}")
        
        # 🔥 ШАГ 4: Ищем ответ в подсказках этой темы с нормализацией
        response = None
        source = "suggestion_map"
        
        for suggestion in topic_suggestions:
            if normalize_text(suggestion["question"]) == normalize_text(question):
                response = suggestion["answer"]
                print(f"✅ Ответ найден в подсказках")
                break
        
        # 🔥 ШАГ 5: Если не нашли в подсказках, используем интеллектуальный поиск в базе знаний
        if not response:
            response = find_in_knowledge_base(question)
            source = "knowledge_base"
            if response:
                print(f"✅ Ответ найден в базе знаний (интеллектуальный поиск)")
        
        # 🔥 ШАГ 6: Если все еще нет ответа, используем GPT
        if not response:
            response = call_yandex_gpt(question)
            source = "yandex_gpt"
            print(f"✅ Ответ от Yandex GPT")
        
        print(f"📊 Результат: ответ='{response[:50]}...', подсказок={len(suggestions)}")
        
        # ✅ ДОБАВЛЕНО: Записываем в лог перед возвратом ответа
        log_interaction(question, response, source)
        
        return jsonify({
            "response": response,
            "source": source,
            "suggestions": suggestions
        })
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        # ✅ ДОБАВЛЕНО: Логируем ошибку
        log_interaction(question, f"❌ Произошла ошибка: {str(e)}", "error")
        return jsonify({"response": "❌ Произошла ошибка", "source": "error", "suggestions": []})

@app.route("/debug-suggestions")
def debug_suggestions():
    """Диагностический маршрут для проверки подсказок"""
    menu_items = load_menu()
    debug_info = {
        "menu_items": menu_items,
        "suggestion_topics": list(suggestionMap.keys()),
        "menu_categories": load_menu_categories()
    }
    
    # Проверяем конкретно кнопку "Платные услуги"
    platnie_uslugi_item = None
    for item in menu_items:
        if normalize_text(item.get("question")) == normalize_text("платные услуги"):
            platnie_uslugi_item = item
            break
    
    debug_info["platnie_uslugi"] = platnie_uslugi_item
    debug_info["platnie_uslugi_suggestions"] = suggestionMap.get("maniuslugi", [])
    
    return jsonify(debug_info)

@app.route("/ask", methods=["POST"])
def ask():
    """Обработка вопросов с интеллектуальным поиском"""
    data = request.json
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"answer": "Пожалуйста, задайте вопрос."})
    
    # Используем интеллектуальный поиск
    response = find_in_knowledge_base(question)
    source = "knowledge_base"
    
    if not response:
        try:
            response = call_yandex_gpt(question)
            source = "yandex_gpt"
        except Exception as e:
            response = f"❌ Ошибка: {str(e)}"
            source = "error"
    
    log_interaction(question, response, source)
    return jsonify({"answer": response})

@app.route("/feedback", methods=["POST"])
def feedback():
    """Сохранение оценки ответа"""
    data = request.json
    question = data.get("question")
    feedback = data.get("feedback")
    feedback_file = "feedback.json"
    logs = []
    if os.path.exists(feedback_file):
        try:
            with open(feedback_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    logs = json.loads(content)
        except:
            pass
    logs.append({
        "timestamp": datetime.now().isoformat(),
        "question": question,
        "feedback": feedback
    })
    try:
        with open(feedback_file, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=4)
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"❌ Ошибка сохранения оценки: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route("/suggestions/<topic>")
def get_suggestions_by_topic(topic):
    """Возвращает подсказки для указанной темы"""
    try:
        # Ищем подсказки для указанной темы
        suggestions = suggestionMap.get(topic.lower(), [])
        # Если для темы нет подсказок, используем дефолтные
        if not suggestions:
            suggestions = suggestionMap.get("default", [])
        return jsonify({"suggestions": suggestions})
    except Exception as e:
        print(f"❌ Ошибка получения подсказок для темы {topic}: {e}")
        return jsonify({"suggestions": []})

@app.route("/api/menu-display")
def get_menu_display():
    """API для получения меню с отображаемым текстом"""
    menu_items = load_menu()
    display_items = []
    for item in menu_items:
        display_items.append({
            "text": item.get("display_text", item.get("admin_text", "")),
            "question": item.get("question", ""),
            "suggestion_topic": item.get("suggestion_topic", "default")
        })
    return jsonify(display_items)

@app.route("/admin/suggestions")
def admin_suggestions():
    """Редактирование контекстных подсказки"""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    return render_template("admin/suggestions.html", suggestion_map=suggestionMap)

@app.route("/admin/suggestions", methods=["POST"])
def add_suggestion():
    """Добавление новой подсказки с ответом"""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    topic = request.form.get("topic").strip().lower()
    text = request.form.get("suggestion-text").strip()
    question = request.form.get("suggestion-question").strip().lower()
    answer = request.form.get("suggestion-answer").strip()
    if not topic or not text or not question or not answer:
        flash("❌ Все поля обязательны", "error")
        return redirect(url_for("admin_suggestions"))
    if topic not in suggestionMap:
        suggestionMap[topic] = []
    if any(s["text"] == text for s in suggestionMap[topic]):
        flash("❌ Подсказка с таким названием уже существует", "error")
        return redirect(url_for("admin_suggestions"))
    # Добавляем answer в подсказку
    suggestionMap[topic].append({
        "text": text,
        "question": question,
        "answer": answer
    })
    save_suggestion_map()
    flash("✅ Подсказка добавлена", "success")
    return redirect(url_for("admin_suggestions"))

@app.route("/suggestion-answer", methods=["POST"])
def get_suggestion_answer():
    """Возвращает ответ для подсказки с учетом нормализации"""
    data = request.json
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"answer": "❌ Вопрос не указан"}), 400

    normalized_question = normalize_text(question)
    
    # Ищем ответ в suggestionMap с нормализацией
    for topic, suggestions in suggestionMap.items():
        for suggestion in suggestions:
            suggestion_question = suggestion.get("question", "").strip()
            if normalize_text(suggestion_question) == normalized_question:
                return jsonify({"answer": suggestion.get("answer", "❌ Ответ не найден")})

    return jsonify({"answer": "❌ Ответ не найден"}), 404

@app.route("/admin/suggestions/delete/<topic>/<text>")
def delete_suggestion(topic, text):
    """Удаление подсказки"""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    # Декодируем текст из URL
    text = unquote(text)
    if topic in suggestionMap:
        suggestionMap[topic] = [s for s in suggestionMap[topic] if s["text"] != text]
        save_suggestion_map()
        flash("✅ Подсказка удалена", "success")
    else:
        flash("❌ Ошибка удаления", "error")
    return redirect(url_for("admin_suggestions"))

@app.route("/admin/suggestions/edit/<topic>/<text>", methods=["GET", "POST"])
def edit_suggestion(topic, text):
    """Редактирование подсказки"""
    if not session.get("admin_logged_in"):
        flash("❌ Доступ запрещён", "error")
        return redirect(url_for("admin_login"))
    # Декодируем текст из URL
    text = unquote(text)
    if request.method == "GET":
        # Находим подсказку для редактирования
        suggestion_to_edit = None
        if topic in suggestionMap:
            for suggestion in suggestionMap[topic]:
                if suggestion["text"] == text:
                    suggestion_to_edit = suggestion
                    break
        if not suggestion_to_edit:
            flash("❌ Подсказка не найдена", "error")
            return redirect(url_for("admin_suggestions"))
        return render_template("admin/suggestions.html", 
                             suggestion_map=suggestionMap,
                             edit_suggestion=suggestion_to_edit,
                             edit_topic=topic)
    else:  # POST - сохранение изменений
        new_topic = request.form.get("topic").strip().lower()
        new_text = request.form.get("suggestion-text").strip()
        new_question = request.form.get("suggestion-question").strip().lower()
        new_answer = request.form.get("suggestion-answer").strip()
        if not new_topic or not new_text or not new_question or not new_answer:
            flash("❌ Все поля обязательны", "error")
            return redirect(url_for("admin_suggestions"))
        # Находим и обновляем подсказку
        updated = False
        if topic in suggestionMap:
            for i, suggestion in enumerate(suggestionMap[topic]):
                if suggestion["text"] == text:
                    # Если изменилась тема, перемещаем подсказку
                    if new_topic != topic:
                        # Удаляем из старой темы
                        suggestionMap[topic].pop(i)
                        # Добавляем в новую тему
                        if new_topic not in suggestionMap:
                            suggestionMap[new_topic] = []
                        suggestionMap[new_topic].append({
                            "text": new_text,
                            "question": new_question,
                            "answer": new_answer
                        })
                    else:
                        # Обновляем в текущей теме
                        suggestionMap[topic][i] = {
                            "text": new_text,
                            "question": new_question,
                            "answer": new_answer
                        }
                    save_suggestion_map()
                    flash("✅ Подсказка обновлена", "success")
                    logging.info(f"Подсказка обновлена: {topic}/{text} -> {new_topic}/{new_text}")
                    updated = True
                    break
        if not updated:
            flash("❌ Подсказка не найдена", "error")
        return redirect(url_for("admin_suggestions"))

@app.route("/admin/suggestions/update", methods=["POST"])
def update_suggestion():
    """API для обновления подсказки"""
    if not session.get("admin_logged_in"):
        return jsonify({"success": False, "error": "Доступ запрещён"}), 403
    try:
        topic = request.form.get("topic")
        old_text = request.form.get("old_text")
        new_text = request.form.get("text")
        new_question = request.form.get("question")
        new_answer = request.form.get("answer")
        if not all([topic, old_text, new_text, new_question, new_answer]):
            return jsonify({"success": False, "error": "Все поля обязательны"})
        if topic in suggestionMap:
            for i, suggestion in enumerate(suggestionMap[topic]):
                if suggestion["text"] == old_text:
                    suggestionMap[topic][i] = {
                        "text": new_text,
                        "question": new_question,
                        "answer": new_answer
                    }
                    save_suggestion_map()
                    return jsonify({"success": True})
        return jsonify({"success": False, "error": "Подсказка не найдена"})
    except Exception as e:
        return jsonify({"success": False, "error": f"Ошибка сервера: {str(e)}"})

@app.route("/admin/menu")
def admin_menu():
    """Страница редактирования меню"""
    if not session.get("admin_logged_in"):
        flash("❌ Доступ запрещён", "error")
        return redirect(url_for("admin_login"))
    menu_items = load_menu()
    categories = load_menu_categories()
    return render_template("admin/menu_edit.html", 
                         menu_items=menu_items,
                         categories=categories)

@app.route("/admin/menu/add", methods=["POST"])
def add_menu_item():
    """Добавление новой кнопки в меню"""
    if not session.get("admin_logged_in"):
        return jsonify({"success": False, "error": "Доступ запрещён"}), 403
    try:
        admin_text = request.form.get("admin_text", "").strip()
        display_text = request.form.get("display_text", "").strip()
        question = request.form.get("question", "").strip().lower()
        category = request.form.get("category", "attractions")
        price_info = request.form.get("price_info", "")
        suggestion_topic = request.form.get("suggestion_topic", "default")
        if not admin_text or not display_text or not question:
            return jsonify({"success": False, "error": "Все поля обязательны"})
        menu_items = load_menu()
        # Проверка на дубликаты
        if any(item.get("admin_text") == admin_text for item in menu_items):
            return jsonify({"success": False, "error": "Кнопка с таким текстом для админки уже существует"})
        if any(item.get("question") == question for item in menu_items):
            return jsonify({"success": False, "error": "Кнопка с таким вопросом уже существует"})
        # Создаем новую кнопку
        new_item = {
            "admin_text": admin_text,
            "display_text": display_text,
            "question": question,
            "category": category,
            "price_info": price_info,
            "suggestion_topic": suggestion_topic
        }
        menu_items.append(new_item)
        save_menu(menu_items)
        logging.info(f"Администратор добавил кнопку в меню: {admin_text} -> {question} (категория: {category})")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": f"Ошибка сервера: {str(e)}"})

@app.route("/admin/menu/edit/<int:index>", methods=["GET"])
def edit_menu_item_form(index):
    """Отображение формы редактирования кнопки меню"""
    if not session.get("admin_logged_in"):
        flash("❌ Доступ запрещён", "error")
        return redirect(url_for("admin_login"))
    menu_items = load_menu()
    categories = load_menu_categories()
    if 0 <= index < len(menu_items):
        item_to_edit = menu_items[index]
        return render_template("admin/menu_edit.html", 
                             menu_items=menu_items,
                             categories=categories,
                             edit_item=item_to_edit,
                             edit_index=index)
    else:
        flash("❌ Неверный индекс кнопки", "error")
        return redirect(url_for("admin_menu"))

@app.route("/admin/menu/edit/<int:index>", methods=["POST"])
def edit_menu_item(index):
    """Обработка данных из формы редактирования кнопки меню"""
    if not session.get("admin_logged_in"):
        return jsonify({"success": False, "error": "Доступ запрещён"}), 403
    try:
        menu_items = load_menu()
        if not (0 <= index < len(menu_items)):
            return jsonify({"success": False, "error": "Неверный индекс кнопки"})
        admin_text = request.form.get("admin_text", "").strip()
        display_text = request.form.get("display_text", "").strip()
        question = request.form.get("question", "").strip().lower()
        category = request.form.get("category", "attractions")
        price_info = request.form.get("price_info", "")
        suggestion_topic = request.form.get("suggestion_topic", "default")
        if not admin_text or not display_text or not question:
            return jsonify({"success": False, "error": "Все поля обязательны"})
        # Проверка на дубликаты (кроме самого редактируемого элемента)
        for i, item in enumerate(menu_items):
            if i != index:
                if item.get("admin_text") == admin_text:
                    return jsonify({"success": False, "error": "Кнопка с таким текстом для админки уже существует"})
                if item.get("question") == question:
                    return jsonify({"success": False, "error": "Кнопка с таким вопросом уже существует"})
        # Обновляем элемент
        menu_items[index] = {
            "admin_text": admin_text,
            "display_text": display_text,
            "question": question,
            "category": category,
            "price_info": price_info,
            "suggestion_topic": suggestion_topic
        }
        save_menu(menu_items)
        logging.info(f"Администратор обновил кнопку в меню: {admin_text} -> {question} (категория: {category})")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": f"Ошибка сервера: {str(e)}"})

@app.route("/admin/menu/delete/<int:index>")
def delete_menu_item(index):
    """Удаление кнопки из меню"""
    if not session.get("admin_logged_in"):
        flash("❌ Доступ запрещён", "error")
        return redirect(url_for("admin_login"))
    try:
        menu_items = load_menu()
        if 0 <= index < len(menu_items):
            removed = menu_items.pop(index)
            save_menu(menu_items)
            flash(f"✅ Кнопка '{removed['admin_text']}' удалена", "success")
            logging.info(f"Администратор удалил кнопку из меню: {removed['admin_text']}")
        else:
            flash("❌ Неверный индекс кнопки", "error")
    except Exception as e:
        flash(f"❌ Ошибка при удалении: {str(e)}", "error")
    return redirect(url_for("admin_menu"))

@app.route('/menu-items')
@no_cache
def get_menu_items():
    """Возвращает меню для фронтенда"""
    menu_items = load_menu()
    return jsonify({"items": menu_items})

@app.route('/menu-items/<category>')
@no_cache
def get_menu_items_by_category(category):
    """Возвращает меню отфильтрованное по категории"""
    menu_items = load_menu()
    filtered_items = [item for item in menu_items if item.get("category") == category]
    return jsonify({"items": filtered_items})

@app.route("/admin/menu/categories/data")
def get_categories_data():
    """API для получения данных категорий"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Доступ запрещён"}), 403
    categories = load_menu_categories()
    return jsonify(categories)

@app.route("/admin/menu/categories")
def admin_menu_categories():
    """Страница управления темами (категориями) меню"""
    if not session.get("admin_logged_in"):
        flash("❌ Доступ запрещён", "error")
        return redirect(url_for("admin_login"))
    categories = load_menu_categories()
    return render_template("admin/menu_categories.html", 
                         categories=categories,
                         system_categories=SYSTEM_CATEGORIES)

@app.route("/admin/menu/categories", methods=["POST"])
def add_menu_category():
    """Добавление новой темы (категории)"""
    if not session.get("admin_logged_in"):
        flash("❌ Доступ запрещён", "error")
        return redirect(url_for("admin_login"))
    key = request.form.get("category_key", "").strip().lower()
    name = request.form.get("category_name", "").strip()
    if not key or not name:
        flash("❌ Оба поля обязательны для заполнения", "error")
        return redirect(url_for("admin_menu_categories"))
    if not re.match(r'^[a-z0-9_]+$', key):
         flash("❌ Ключ категории может содержать только латинские буквы в нижнем регистре, цифры и подчеркивание", "error")
         return redirect(url_for("admin_menu_categories"))
    categories = load_menu_categories()
    if key in categories.get("system_categories", {}) or key in categories.get("custom_categories", {}):
        flash("❌ Категория с таким ключом уже существует", "error")
        return redirect(url_for("admin_menu_categories"))
    # Обновляем пользовательские категории
    custom_categories = categories.get("custom_categories", {})
    custom_categories[key] = name
    categories["custom_categories"] = custom_categories
    save_menu_categories(categories)
    flash(f"✅ Категория '{name}' успешно добавлена", "success")
    logging.info(f"Администратор добавил категорию меню: {key} -> {name}")
    return redirect(url_for("admin_menu_categories"))

@app.route("/admin/menu/categories/delete/<string:key>")
def delete_menu_category(key):
    """Удаление темы (категории)"""
    if not session.get("admin_logged_in"):
        flash("❌ Доступ запрещён", "error")
        return redirect(url_for("admin_login"))
    if key in SYSTEM_CATEGORIES:
        flash("❌ Нельзя удалить системную категорию", "error")
        return redirect(url_for("admin_menu_categories"))
    categories = load_menu_categories()
    if key in categories.get("custom_categories", {}):
        # Проверка: нельзя удалить категорию, если есть кнопки с этой категорией
        menu_items = load_menu()
        if any(item.get("category") == key for item in menu_items):
            flash("❌ Нельзя удалить категорию, к которой привязаны кнопки меню", "error")
            return redirect(url_for("admin_menu_categories"))
        del categories["custom_categories"][key]
        save_menu_categories(categories)
        flash(f"✅ Категория '{key}' успешно удалена", "success")
        logging.info(f"Администратор удалил категорию меню: {key}")
    else:
        flash("❌ Категория не найдена", "error")
    return redirect(url_for("admin_menu_categories"))

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Страница входа в админку"""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == os.getenv("ADMIN_USER", "admin") and password == os.getenv("ADMIN_PASS", "1"):
            session["admin_logged_in"] = True
            session["admin_user"] = username
            logging.info("Администратор вошёл в систему")
            return redirect(url_for("admin_dashboard"))
        flash("❌ Неверный логин или пароль", "error")
        logging.warning("Неудачная попытка входа в админку")
    return render_template("admin/login.html")

@app.route("/admin")
def admin_dashboard():
    """Главная админки"""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    return render_template("admin/dashboard.html", bookings=BOOKINGS)

@app.route("/admin/knowledge", methods=["GET", "POST"])
def knowledge_edit():
    """Редактирование базы знаний с PostgreSQL"""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
        
    if request.method == "POST":
        action = request.form.get("action")
        question = request.form.get("question", "").strip().lower()
        answer = request.form.get("answer", "").strip()
        old_question = request.form.get("old_question", "").strip().lower()
        
        if action == "add":
            if question and answer:
                if add_knowledge_item(question, answer, session.get("admin_user", "admin")):
                    flash("✅ Вопрос добавлен", "success")
                    logging.info(f"Добавлен вопрос: '{question}'")
                else:
                    flash("❌ Ошибка добавления вопроса", "error")
            else:
                flash("❌ Все поля обязательны", "error")
                
        elif action == "edit":
            if question and answer and old_question:
                if update_knowledge_item(old_question, question, answer, session.get("admin_user", "admin")):
                    flash("✅ Вопрос обновлён", "success")
                    logging.info(f"Изменён вопрос: '{old_question}' -> '{question}'")
                else:
                    flash("❌ Ошибка обновления вопроса", "error")
            else:
                flash("❌ Неверные данные", "error")
                
        elif action == "delete":
            if question:
                if delete_knowledge_item(question):
                    flash("✅ Вопрос удалён", "success")
                    logging.info(f"Удалён вопрос: '{question}'")
                else:
                    flash("❌ Ошибка удаления вопроса", "error")
            else:
                flash("❌ Вопрос не найден", "error")
                
        elif action == "search":
            search_query = request.form.get("search_query", "").strip()
            if search_query:
                results = search_knowledge(search_query)
                knowledge = {result['question']: result['answer'] for result in results}
                return render_template("admin/knowledge_edit.html", 
                                    knowledge=knowledge, 
                                    search_query=search_query)
            else:
                flash("❌ Введите поисковый запрос", "error")
    
    # Загружаем актуальные данные из БД
    load_knowledge_base()
    return render_template("admin/knowledge_edit.html", knowledge=KNOWLEDGE_BASE)

@app.route("/admin/logs")
def view_logs():
    """Просмотр истории диалогов"""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    logs = json.loads(content)
            logs = sorted(logs, key=lambda x: x["timestamp"], reverse=True)
        except Exception as e:
            logging.error(f"Ошибка чтения логов: {e}")
            flash("❌ Ошибка загрузки логов", "error")
    return render_template("admin/logs.html", logs=logs)

@app.route("/admin/edit_response", methods=["POST"])
def edit_response():
    """Редактирование ответа из логов с сохранением в PostgreSQL"""
    if not session.get("admin_logged_in"):
        return jsonify({"status": "error", "message": "Доступ запрещён"}), 403
        
    question = request.form.get("question")
    new_answer = request.form.get("answer")
    
    if question and new_answer:
        if add_knowledge_item(question, new_answer, session.get("admin_user", "admin")):
            return jsonify({"status": "ok"})
        else:
            return jsonify({"status": "error", "message": "Ошибка сохранения в БД"}), 500
            
    return jsonify({"status": "error", "message": "Некорректные данные"}), 400

@app.route("/admin/export_logs")
def export_logs():
    """Экспорт логов диалогов"""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    if os.path.exists(LOG_FILE):
        return send_from_directory(".", "bot_log.json", as_attachment=True)
    flash("❌ Файл логов не найден", "error")
    return redirect(url_for("view_logs"))

@app.route("/admin/logout")
def admin_logout():
    """Выход из админки"""
    session.pop("admin_logged_in", None)
    session.pop("admin_user", None)
    flash("Вы вышли из админки", "info")
    logging.info("Администратор вышел из системы")
    return redirect(url_for("index"))

@app.route("/static/<path:path>")
def send_static(path):
    """Раздача статики"""
    return send_from_directory("static", path)

@app.route("/booking", methods=["GET", "POST"])
def booking():
    """Страница бронирования"""
    if request.method == "POST":
        name = request.form.get("name")
        phone = request.form.get("phone")
        date = request.form.get("date")
        guests = request.form.get("guests")
        event_type = request.form.get("event_type")
        if name and phone and date and guests and event_type:
            new_booking = {
                "name": name,
                "phone": phone,
                "date": date,
                "guests": guests,
                "event_type": event_type,
                "timestamp": datetime.now().isoformat()
            }
            BOOKINGS.append(new_booking)
            save_bookings()
            logging.info(f"Новая бронь: {name}, {phone}")
            return render_template("booking.html", success="Спасибо! Мы свяжемся с вами.")
    return render_template("booking.html")

@app.route("/birthday_calc")
def birthday_calc():
    """Калькулятор дня рождения"""
    return render_template("birthday_calc.html")

@app.route("/suggestions/all")
def get_all_suggestions():
    """Возвращает все подсказки для frontend"""
    return jsonify({"suggestions": suggestionMap})

@app.route("/debug-all-buttons")
def debug_all_buttons():
    """Диагностика всех кнопок меню"""
    menu_items = load_menu()
    debug_info = {}
    
    for item in menu_items:
        topic = item.get("suggestion_topic")
        debug_info[item["admin_text"]] = {
            "question": item["question"],
            "suggestion_topic": topic,
            "suggestions_count": len(suggestionMap.get(topic, [])),
            "suggestions": suggestionMap.get(topic, [])
        }
    
    return jsonify(debug_info)

@app.route("/debug-platnie-uslugi")
def debug_platnie_uslugi():
    """Диагностика проблемы с платными услугами"""
    menu_items = load_menu()
    platnie_item = None
    
    for item in menu_items:
        if item.get("admin_text") == "Платные услуги":
            platnie_item = item
            break
    
    debug_info = {
        "platnie_item": platnie_item,
        "suggestion_topic": platnie_item.get("suggestion_topic") if platnie_item else None,
        "suggestions_for_topic": suggestionMap.get(platnie_item.get("suggestion_topic", "")) if platnie_item else None,
        "all_topics": list(suggestionMap.keys())
    }
    
    return jsonify(debug_info)

@app.route("/debug-current-menu")
def debug_current_menu():
    """Текущее состояние меню"""
    menu_items = load_menu()
    return jsonify({
        "menu_items": menu_items,
        "menu_cache": MENU_CACHE is not None
    })

@app.route("/clear-cache-now")
def clear_cache_now():
    """Срочная очистка кэша меню"""
    global MENU_CACHE
    MENU_CACHE = None
    load_menu()
    return "✅ Кэш меню очищен! Теперь обновите страницу чата."

@app.route("/debug-normalize")
def debug_normalize():
    """Диагностика работы нормализации"""
    test_questions = [
        "как записаться к врачу на платный прием?",
        "как записаться к врачу на платный прием",
        "Как записаться к врачу на платный прием!",
        "как записаться к врачу на платный прием.",
        "как записаться к врачу на платный прием ",
        " записаться к врачу на платный прием ",
        "как записаться врачу платный прием"
    ]
    
    results = []
    for q in test_questions:
        results.append({
            "original": q,
            "normalized": normalize_text(q),
            "in_knowledge_base": normalize_text(q) in [normalize_text(k) for k in KNOWLEDGE_BASE.keys()]
        })
    
    return jsonify(results)

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        print(f"❌ Ошибка определения IP: {e}")
        return "127.0.0.1"

def call_yandex_gpt(prompt, history=None):
    """Вызов Yandex GPT с повторными попытками"""
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    headers = {
        "Authorization": f"Api-Key {os.getenv('YANDEX_API_KEY')}",
        "x-folder-id": os.getenv("YANDEX_FOLDER_ID"),
        "Content-Type": "application/json"
    }
    system_prompt = """
    Ты - консультант стоматологической поликлиники. Отвечай дружелюбно и информативно.
    Используй профессиональные знания стоматолога, соблюдай врачебную этику.
    Ты – дружелюбный консультант стоматолог. Отвечай кратко, структурированно.
    Если пользователь хочет узнать про услуги поликлиники:
    Предложи задавать тебе вопросы или связаться со специалистом.
    Не выдумывай цены – если не знаешь, скажи честно, но предложи помощь.
    Всегда завершай свой ответ открытым вопросом, чтобы продолжить диалог.
    """
    messages = [{"role": "system", "text": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "text": prompt})
    payload = {
        "modelUri": f"gpt://{os.getenv('YANDEX_FOLDER_ID')}/yandexgpt-lite",
        "completionOptions": {
            "stream": False,
            "temperature": 0.3,
            "maxTokens": 1000
        },
        "messages": messages
    }
    for attempt in range(3):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                return response.json()["result"]["alternatives"][0]["message"]["text"]
            elif response.status_code == 401:
                return "❌ Ошибка авторизации. Проверьте API-ключ."
            elif response.status_code == 400:
                return "❌ Ошибка параметров. Проверьте folder_id."
            else:
                print(f"⚠️ Ошибка GPT (попытка {attempt + 1}): {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Ошибка подключения (попытка {attempt + 1}): {str(e)}")
        time.sleep(1)
    return "❌ Не удалось получить ответ. Попробуйте позже."

def log_interaction(question, answer, source):
    """Логирует диалог в bot_log.json"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "question": question,
        "answer": answer,
        "source": source
    }
    try:
        logs = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    logs = json.loads(content)
        logs.append(log_entry)
        if len(logs) % 100 == 0:
            backup_path = os.path.join(BACKUPS_DIR, f"bot_log_{int(time.time())}.json")
            shutil.copy2(LOG_FILE, backup_path)
            print(f"🔄 Создана резервная копия: {backup_path}")
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=4)
        print("✅ Диалог сохранен в лог")
        logging.info("Диалог сохранен в лог")
    except Exception as e:
        print(f"❌ Ошибка сохранения лога: {e}")
        logging.error(f"Ошибка сохранения лога: {e}")

# ===================================================================================
# 🔊 НОВЫЙ МАРШРУТ: TTS через Yandex SpeechKit
# ===================================================================================

@app.route('/tts')
def text_to_speech():
    """
    Преобразует текст или SSML в речь через Yandex SpeechKit.
    Поддержка пауз, голосов и интонаций через <speak> и <break>
    """
    text = request.args.get('text', '').strip()
    use_ssml = request.args.get('ssml', 'false').lower() == 'true'
    voice = request.args.get('voice', 'alena')  # Можно менять голос
    if not text:
        return '', 400

    # Декодируем URL-encoded текст
    text = unquote(text)
    
    # Функция для преобразования чисел в порядковые числительные для списков
    def convert_number_to_text(number):
        numbers = {
            1: 'первое',
            2: 'второе', 
            3: 'третье',
            4: 'четвертое',
            5: 'пятое',
            6: 'шестое',
            7: 'седьмое',
            8: 'восьмое',
            9: 'девятое',
            10: 'десятое',
            11: 'одиннадцатое',
            12: 'двенадцатое',
            13: 'тринадцатое',
            14: 'четырнадцатое',
            15: 'пятнадцатое',
            16: 'шестнадцатое',
            17: 'семнадцатое',
            18: 'восемнадцатое',
            19: 'девятнадцатое',
            20: 'двадцатоe'
        }
        return numbers.get(number, str(number))
    
    # Функция для преобразования дат
    def convert_day_to_text(day):
        days = {
            1: 'первое', 2: 'второе', 3: 'третье', 4: 'четвертое', 5: 'пятое',
            6: 'шестое', 7: 'седьмое', 8: 'восьмое', 9: 'девятое', 10: 'десятое',
            11: 'одиннадцатое', 12: 'двенадцатое', 13: 'тринадцатое', 14: 'четырнадцатое',
            15: 'пятнадцатое', 16: 'шестнадцатое', 17: 'семнадцатое', 18: 'восемнадцатое',
            19: 'девятнадцатое', 20: 'двадцатое', 21: 'двадцать первое', 22: 'двадцать второе',
            23: 'двадцать третье', 24: 'двадцать четвертое', 25: 'двадцать пятое',
            26: 'двадцать шестое', 27: 'двадцать седьмое', 28: 'двадцать восьмое',
            29: 'двадцать девятое', 30: 'тридцатое', 31: 'тридцать первое'
        }
        return days.get(day, str(day))
    
    # Обрабатываем текст для TTS
   
       # Обрабатываем текст для TTS
    import re
    
    # Функция для определения телефонных номеров
    def is_phone_number(text):
        phone_patterns = [
            r'\(\d{3}\)\s?\d{3}\s?\d{2}\s?\d{2}',  # (495) 123 45 67
            r'\d{3}-\d{2}-\d{2}',                   # 123-45-67
            r'\d{3}\s\d{2}\s\d{2}',                 # 123 45 67
        ]
        return any(re.search(pattern, text) for pattern in phone_patterns)

    # Функция для преобразования отдельных цифр
    def convert_single_digit(digit):
        digits = {
            0: 'ноль',
            1: 'один', 
            2: 'два',
            3: 'три',
            4: 'четыре',
            5: 'пять',
            6: 'шесть',
            7: 'семь',
            8: 'восемь',
            9: 'девять'
        }
        return digits.get(digit, str(digit))

    # Функция для преобразования двузначных чисел
    def convert_two_digit_number(number):
        if number < 10:
            return convert_single_digit(number)
        
        numbers = {
            10: 'десять',
            11: 'одиннадцать',
            12: 'двенадцать', 
            13: 'тринадцать',
            14: 'четырнадцать',
            15: 'пятнадцать',
            16: 'шестнадцать',
            17: 'семнадцать',
            18: 'восемнадцать',
            19: 'девятнадцать',
            20: 'двадцать',
            30: 'тридцать',
            40: 'сорок',
            50: 'пятьдесят',
            60: 'шестьдесят',
            70: 'семьдесят',
            80: 'восемьдесят',
            90: 'девяносто'
        }
        
        if number in numbers:
            return numbers[number]
        else:
            tens = (number // 10) * 10
            units = number % 10
            if units == 0:
                return numbers.get(tens, str(tens))
            else:
                return f"{numbers.get(tens, str(tens))} {convert_single_digit(units)}"

        # Функция для преобразования телефонных номеров
    def convert_phone_number(text):
        def replace_phone_numbers(match):
            # Извлекаем все числа из телефонного номера
            numbers = re.findall(r'\d+', match.group())
            result = []
            
            for num in numbers:
                if num == '00':  # Особый случай для двойного нуля
                    result.append('ноль ноль')
                elif len(num) == 1:  # Одиночные цифры
                    result.append(convert_single_digit(int(num)))
                elif len(num) == 2:  # Двузначные числа
                    # В телефонах двузначные числа обычно произносятся как целые числа
                    result.append(convert_two_digit_number(int(num)))
                else:  # Трехзначные и более (коды городов)
                    # Произносим по отдельным цифрам
                    result.append(' '.join([convert_single_digit(int(d)) for d in num]))
            
            return ' '.join(result)
        
        # Паттерн для телефонных номеров
        phone_pattern = r'\(\d{3}\)\s?\d{3}\s?\d{2}\s?\d{2}'
        return re.sub(phone_pattern, replace_phone_numbers, text)

    # Основная обработка текста
    if is_phone_number(text):
        processed_text = convert_phone_number(text)
    else:
        # Обычная обработка для не-телефонных текстов
        # Преобразуем нумерованные списки (1., 2., 3. и т.д.)
        processed_text = re.sub(r'(\d+)\.\s+', lambda m: f"{convert_number_to_text(int(m.group(1)))}. ", text)
        
        # Преобразуем даты (дд.мм.гггг)
        date_pattern = r'(\d{2})\.(\d{2})\.(\d{4})'
        def replace_date(match):
            day = int(match.group(1))
            month = int(match.group(2))
            year = int(match.group(3))
            
            months = [
                '', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
            ]
            
            day_text = convert_day_to_text(day)
            month_text = months[month] if 1 <= month <= 12 else str(month)
            
            # Простое преобразование года
            year_text = str(year)
            if year >= 2000:
                year_text = f"две тысячи {convert_number_to_text(year - 2000)}" if year > 2000 else "двухтысячного"
            
            return f"{day_text} {month_text} {year_text} года"
        
        processed_text = re.sub(date_pattern, replace_date, processed_text)
        
        # Добавляем паузы между абзацами
        processed_text = re.sub(r'\n\s*\n', ' <break time="900ms"/> ', processed_text)
        
        # Убираем лишние пробелы
        processed_text = re.sub(r'\s+', ' ', processed_text).strip()
    
    # Убираем Markdown-разметку
    processed_text = re.sub(r'\*\*|\*|~~|`', '', processed_text)
    
    url = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
    headers = {
        "Authorization": f"Api-Key {os.getenv('YANDEX_API_KEY')}"
    }

    # Если use_ssml=True — обрамляем текст в <speak>
    final_text = f"<speak>{processed_text}</speak>" if use_ssml else processed_text

    data = {
        "text": final_text,
        "lang": "ru-RU",
        "voice": voice,
        "format": "mp3",
        "sampleRateHertz": 48000
    }

    # Для SSML можно использовать PCM (если нужно)
    if use_ssml:
        data["format"] = "lpcm"
        data["sampleRateHertz"] = 48000

    try:
        tts_response = requests.post(url, headers=headers, data=data, stream=True)
        if tts_response.status_code != 200:
            print("TTS Error:", tts_response.text)
            return '', 500

        return Response(
            tts_response.iter_content(chunk_size=1024),
            mimetype="audio/mpeg"  # или "audio/x-lpcm", если format=lpcm
        )
    except Exception as e:
        print("TTS Request failed:", str(e))
        return '', 500

# ===================================================================================

@app.route("/admin/knowledge/import", methods=["POST"])
def import_knowledge():
    """Массовый импорт вопросов-ответов"""
    if not session.get("admin_logged_in"):
        return jsonify({"success": False, "error": "Доступ запрещён"}), 403
        
    try:
        data = request.json
        if not data or not isinstance(data, dict):
            return jsonify({"success": False, "error": "Некорректные данные"})
            
        success_count = 0
        error_count = 0
        
        for question, answer in data.items():
            if question and answer:
                if add_knowledge_item(question, answer, session.get("admin_user", "admin")):
                    success_count += 1
                else:
                    error_count += 1
        
        return jsonify({
            "success": True,
            "message": f"Импорт завершен: {success_count} успешно, {error_count} ошибок"
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": f"Ошибка импорта: {str(e)}"})


if __name__ == "__main__":
    # Инициализация базы знаний
    if init_knowledge_db():
        load_knowledge_base()
    else:
        print("ℹ️  Используем файловую базу знаний")
        load_knowledge_base()
    
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    local_ip = get_local_ip()
    print(f"🌐 Запуск сервера на:")
    print(f"   🖥️  В локальной сети: http://{local_ip}:{port}")
    print(f"   🔐  На этом устройстве: http://localhost:{port} или http://127.0.0.1:{port}")
    print("💡 Для остановки сервера нажмите CTRL+C")
    app.run(host="0.0.0.0", port=port, debug=debug)
