from telethon import TelegramClient, events, Button
import logging
from datetime import datetime, timedelta
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights
from telethon.tl.types import PeerUser
from telethon.tl.types import User
from telethon import types
from telethon.tl.types import Channel, ChatAdminRights, User
from telethon.tl.functions.channels import EditAdminRequest
from telethon.tl.types import InputPeerChat
from telethon.errors import ChatAdminRequiredError, UserNotParticipantError
from telethon.tl.types import ChatBannedRights, ChannelParticipantsAdmins
from telethon.tl.types import UserStatusRecently
from telethon.tl.custom import Button
import json
import os
import asyncio
import sqlite3
from threading import Lock
import requests
import random
import re
import hashlib
import uuid
from datetime import datetime, timedelta  # Правильный импорт
from collections import defaultdict
import functools
import time
import sys
import signal

user_scammers_count = {}
user_states = {}
checks_count = 0

# ============ ЗАЩИТА ОТ СПАМА ДЛЯ КНОПОК ============
button_cooldowns = {}
BUTTON_COOLDOWN_TIME = 2  # секунды между нажатиями кнопок
user_button_presses = {}  # Счетчик нажатий кнопок для каждого пользователя
MAX_BUTTON_PRESSES = 3  # Максимальное количество нажатий за период
BUTTON_PRESS_WINDOW = 10  # Окно времени в секундах
button_loading_messages = {}  # Хранит ID сообщений о загрузке для каждого пользователя

last_check_time = {}
last_button_click = {}
check_cooldown = 3  # секунды между запросами
button_cooldown = 2  # секунды между нажатиями кнопок

# Глобальный счетчик активных проверок
active_checks = {}

user_message_count = defaultdict(list)

# Настройки логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
API_ID = '27231812'
API_HASH = '59d6d299a99f9bb97fcbf5645d9d91e9'
BOT_TOKEN = '8719083106:AAHSMvJ2LsBLNPVbQMysdNrybEL03bSCvRg'
ADMINS = [8687960828, 6257985367]  # ID администраторов
LOG_CHANNEL = 'https://t.me/+D2EwGUL3M0oxMTM5'  # Ссылка на канал логов


DEFAULT_OWNER_IDS = [8687960828, 6257985367]
DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = "/data/Ice.db"

REVOKED_OWNER_FILE = os.path.join(DATA_DIR, "forget_revoked_owners.json")

def _load_revoked_owner_ids():
    try:
        with open(REVOKED_OWNER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {int(x) for x in data if str(x).isdigit()}
    except Exception:
        return set()

def _save_revoked_owner_ids(ids):
    try:
        with open(REVOKED_OWNER_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted({int(x) for x in ids}), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Не удалось сохранить список снятых владельцев: {e}")

REVOKED_OWNER_IDS = _load_revoked_owner_ids()
OWNER_ID = [uid for uid in DEFAULT_OWNER_IDS if uid not in REVOKED_OWNER_IDS]

def is_owner(user_id):
    return user_id in OWNER_ID


# ФУНКЦИЯ ЗАЩИТЫ ОТ СПАМА ДЛЯ КНОПОК
def check_button_spam_protection(user_id):
    """Проверяет защиту от спама для кнопок"""
    current_time = time.time()

    # Инициализация данных пользователя
    if user_id not in user_button_presses:
        user_button_presses[user_id] = {
            'count': 0,
            'window_start': current_time,
            'last_press': 0
        }

    user_data = user_button_presses[user_id]

    # Сброс счетчика если окно времени истекло
    if current_time - user_data['window_start'] > BUTTON_PRESS_WINDOW:
        user_data['count'] = 0
        user_data['window_start'] = current_time

    # Проверка кулдауна между нажатиями
    if current_time - user_data['last_press'] < BUTTON_COOLDOWN_TIME:
        remaining = BUTTON_COOLDOWN_TIME - (current_time - user_data['last_press'])
        return False, f"⏳ Подождите {remaining:.1f} секунд перед повторным нажатием"

    # Проверка лимита нажатий в окне времени
    if user_data['count'] >= MAX_BUTTON_PRESSES:
        reset_time = BUTTON_PRESS_WINDOW - (current_time - user_data['window_start'])
        return False, f"🚫 Слишком много нажатий! Подождите {reset_time:.1f} секунд"

    # Обновляем данные пользователя
    user_data['count'] += 1
    user_data['last_press'] = current_time

    return True, "OK"


async def show_button_loading(event, button_name):
    """Показывает сообщение о загрузке для кнопки"""
    user_id = event.sender_id

    # Показываем сообщение о загрузке
    loading_text = f"🔄 Загружаем {button_name}..."
    try:
        if user_id in button_loading_messages:
            try:
                await bot.delete_messages(event.chat_id, button_loading_messages[user_id])
            except:
                pass

        loading_msg = await event.respond(loading_text)
        button_loading_messages[user_id] = loading_msg.id

        # Небольшая задержка для имитации загрузки
        await asyncio.sleep(0.5)

    except Exception as e:
        logging.error(f"Ошибка показа загрузки: {e}")

class Database:
    def __init__(self, db_name=None):
        logging.info("Инициализация базы данных...")
        if db_name is None:
            db_name = DB_PATH
        elif not os.path.isabs(db_name):
            db_name = os.path.join(DATA_DIR, db_name)
        self.users = {}
        self.conn = sqlite3.connect(db_name, isolation_level=None)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.cursor = self.conn.cursor()
        self.conn.row_factory = sqlite3.Row
        self.lock = asyncio.Lock()
        self.create_tables()
        self.check_table_structure()
        self.check_and_fix_database()

    def is_connected(self):
        """Проверяет, открыто ли соединение с БД"""
        try:
            self.cursor.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    def create_tables(self):
        logging.info("Проверка и создание таблиц если не существуют...")

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS user_ratings (
                       user_id INTEGER PRIMARY KEY,
                       total_rating REAL DEFAULT 5.0,
                       rating_count INTEGER DEFAULT 1,
                       average_rating REAL DEFAULT 5.0
                   )''')
        logging.info("Таблица user_ratings проверена/создана")

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS user_votes (
                       vote_id INTEGER PRIMARY KEY AUTOINCREMENT,
                       voter_id INTEGER NOT NULL,
                       target_id INTEGER NOT NULL,
                       vote_type TEXT NOT NULL,
                       vote_date TEXT DEFAULT CURRENT_TIMESTAMP,
                       UNIQUE(voter_id, target_id)
                   )''')
        logging.info("Таблица user_votes проверена/создана")

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                role_id INTEGER DEFAULT 0,
                check_count INTEGER DEFAULT 0,
                last_check_date TEXT,
                country TEXT,
                channel TEXT,
                custom_photo TEXT,
                custom_photo_url TEXT,
                description TEXT,
                scammers_count INTEGER DEFAULT 0,
                scammers_slept INTEGER DEFAULT 0,
                warnings INTEGER DEFAULT 0,
                role TEXT,
                custom_status TEXT,
                granted_by_id INTEGER,
                curator_id INTEGER,
                allowance INTEGER DEFAULT 0,
                last_spin TEXT,
                premium_until INTEGER DEFAULT NULL,
                FOREIGN KEY(curator_id) REFERENCES users(user_id)
            )''')
        logging.info("Таблица users проверена/создана")

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS checks (
                check_id INTEGER PRIMARY KEY AUTOINCREMENT,
                checker_id INTEGER,
                target_id INTEGER,
                check_date TEXT,
                description TEXT,
                FOREIGN KEY(checker_id) REFERENCES users(user_id),
                FOREIGN KEY(target_id) REFERENCES users(user_id)
            )''')
        logging.info("Таблица checks проверена/создана")

        # ✅ ИСПРАВЛЕНО: Только создаем если не существует
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS scammers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                scammer_id INTEGER,
                reason TEXT,
                reported_by TEXT,
                description TEXT,
                reporter_id INTEGER,
                unique_id VARCHAR(255),
                proof_link TEXT,
                added_date TEXT DEFAULT CURRENT_TIMESTAMP
            )''')
        logging.info("Таблица scammers проверена/создана")

        # Проверяем и добавляем недостающие поля
        self.check_and_add_missing_columns('scammers')

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS statistics (
                total_messages INTEGER DEFAULT 0
            )''')
        self.cursor.execute('INSERT OR IGNORE INTO statistics (total_messages) VALUES (0)')
        logging.info("Таблица statistics проверена/создана")

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS reasons (
                user_id INTEGER PRIMARY KEY,
                reason TEXT
            )''')
        logging.info("Таблица reasons проверена/создана")

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS trainees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE
            )''')
        logging.info("Таблица trainees проверена/создана")

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                content TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )''')
        logging.info("Таблица messages проверена/создана")

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS trust (
                user_id INTEGER PRIMARY KEY,
                granted_by INTEGER,
                grant_date TEXT
            )''')
        logging.info("Таблица trust проверена/создана")

        self.conn.commit()
        logging.info("Все таблицы проверены/созданы")


    def check_table_structure(self):
        logging.info("Проверка структуры таблицы users...")
        self.cursor.execute("PRAGMA table_info(users);")
        columns = self.cursor.fetchall()
        for column in columns:
            print(column)  # Вывод структуры таблицы

    def cooldown(seconds):
        """Декоратор для защиты от спама"""

        def decorator(func):
            last_called = {}

            @functools.wraps(func)
            async def wrapper(event, *args, **kwargs):
                user_id = event.sender_id
                current_time = time.time()

                if user_id in last_called:
                    elapsed = current_time - last_called[user_id]
                    if elapsed < seconds:
                        remaining = seconds - elapsed
                        await event.answer(f"⏳ Подождите {remaining:.1f} секунд", alert=False)
                        return

                last_called[user_id] = current_time
                return await func(event, *args, **kwargs)

            return wrapper

        return decorator

    def check_and_fix_database(self):
        """Проверяет и добавляет недостающие столбцы в таблицу users"""
        try:
            # Проверяем существующие столбцы
            self.cursor.execute("PRAGMA table_info(users)")
            existing_columns = [column[1] for column in self.cursor.fetchall()]

            # Столбцы, которые должны быть
            required_columns = [
                'scammers_count',
                'allowance',
                'last_spin',
                'premium_until'
            ]

            # Добавляем недостающие столбцы
            # Миграция удалённой роли 5 в роль 2.
            self.cursor.execute("UPDATE users SET role_id = 2 WHERE role_id = 5")

            for column in required_columns:
                if column not in existing_columns:
                    if column == 'scammers_count':
                        self.cursor.execute(f"ALTER TABLE users ADD COLUMN {column} INTEGER DEFAULT 0")
                    elif column == 'allowance':
                        self.cursor.execute(f"ALTER TABLE users ADD COLUMN {column} INTEGER DEFAULT 0")
                    elif column == 'last_spin':
                        self.cursor.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")
                    elif column == 'premium_until':
                        self.cursor.execute(f"ALTER TABLE users ADD COLUMN {column} INTEGER DEFAULT NULL")
                    logging.info(f"Добавлен столбец {column} в таблицу users")

            self.conn.commit()
        except Exception as e:
            logging.error(f"Ошибка при проверке/исправлении базы данных: {e}")

    def check_and_add_missing_columns(self, table_name):
        """Проверяет и добавляет отсутствующие столбцы в таблицу"""
        try:
            # Требуемые поля для таблицы scammers
            required_columns = {
                'id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
                'user_id': 'INTEGER',
                'scammer_id': 'INTEGER',
                'reason': 'TEXT',
                'reported_by': 'TEXT',
                'description': 'TEXT',
                'reporter_id': 'INTEGER',
                'unique_id': 'VARCHAR(255)',
                'proof_link': 'TEXT',
                'added_date': 'TEXT DEFAULT CURRENT_TIMESTAMP'
            }

            # Получаем текущие столбцы
            self.cursor.execute(f"PRAGMA table_info({table_name})")
            existing_columns = {row[1]: row[2] for row in self.cursor.fetchall()}

            # Добавляем недостающие столбцы
            for column, column_type in required_columns.items():
                if column not in existing_columns:
                    try:
                        self.cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} {column_type}")
                        logging.info(f"Добавлен столбец {column} в таблицу {table_name}")
                    except Exception as e:
                        logging.error(f"Ошибка добавления столбца {column}: {e}")

            self.conn.commit()

        except Exception as e:
            logging.error(f"Ошибка проверки таблицы {table_name}: {e}")

    def get_user_rating(self, user_id):
        """Получает рейтинг пользователя с ограничением от 2.0 до 10.0"""
        try:
            self.cursor.execute('SELECT average_rating FROM user_ratings WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()

            if result:
                rating = float(result[0]) if result[0] is not None else 5.0
                # Ограничиваем рейтинг в пределах 2.0-10.0
                rating = max(2.0, min(10.0, rating))
                logging.info(f"Рейтинг пользователя {user_id}: {rating}")
                return round(rating, 1)
            else:
                # Создаем запись с начальным рейтингом 5.0
                self.cursor.execute('''
                    INSERT INTO user_ratings (user_id, total_rating, rating_count, average_rating)
                    VALUES (?, 5.0, 1, 5.0)
                ''', (user_id,))
                self.conn.commit()
                logging.info(f"Создана новая запись рейтинга для пользователя {user_id}")
                return 5.0
        except Exception as e:
            logging.error(f"Ошибка получения рейтинга для {user_id}: {e}")
            return 5.0

    def can_user_vote(self, voter_id, target_id):
        """Проверяет, может ли пользователь голосовать за другого"""
        try:
            # Нельзя голосовать за себя
            if voter_id == target_id:
                return False, "❌ Нельзя голосовать за себя!"

            # Проверяем, голосовал ли уже пользователь
            self.cursor.execute('SELECT 1 FROM user_votes WHERE voter_id = ? AND target_id = ?',
                                (voter_id, target_id))
            if self.cursor.fetchone():
                return False, "❌ Вы уже оценили этого пользователя!"

            return True, "Можно голосовать"
        except Exception as e:
            logging.error(f"Ошибка проверки возможности голосования: {e}")
            return False, "Произошла ошибка"

    def add_user_vote(self, voter_id, target_id, vote_type):
        """Добавляет голос пользователя и обновляет рейтинг"""
        try:
            # Проверяем тип голоса
            if vote_type not in ['like', 'dislike']:
                return False, "Неверный тип голоса"

            # Проверяем, может ли пользователь голосовать
            can_vote, message = self.can_user_vote(voter_id, target_id)
            if not can_vote:
                return False, message

            # Добавляем запись о голосе
            self.cursor.execute('''
                INSERT INTO user_votes (voter_id, target_id, vote_type, vote_date)
                VALUES (?, ?, ?, datetime('now'))
            ''', (voter_id, target_id, vote_type))

            # Обновляем рейтинг
            success, rating_message = self.update_user_rating(target_id, vote_type)
            if not success:
                return False, rating_message

            self.conn.commit()
            logging.info(f"Пользователь {voter_id} проголосовал за {target_id}: {vote_type}")
            return True, "✅ Ваш голос учтен!"

        except sqlite3.IntegrityError:
            return False, "❌ Вы уже оценили этого пользователя!"
        except Exception as e:
            logging.error(f"Ошибка добавления голоса: {e}")
            return False, "❌ Произошла ошибка при обработке голоса"

    def update_user_rating(self, target_id, vote_type):
        """Обновляет рейтинг пользователя на основе голоса"""
        try:
            # Определяем изменение рейтинга
            rating_change = 1.0 if vote_type == 'like' else -1.0

            # Получаем текущий рейтинг
            self.cursor.execute('''
                SELECT total_rating, rating_count, average_rating 
                FROM user_ratings WHERE user_id = ?
            ''', (target_id,))
            result = self.cursor.fetchone()

            if result:
                total_rating, rating_count, average_rating = result
                # Преобразуем в float
                total_rating = float(total_rating) if total_rating is not None else 5.0
                rating_count = int(rating_count) if rating_count is not None else 1
                average_rating = float(average_rating) if average_rating is not None else 5.0

                # Обновляем значения
                new_total_rating = total_rating + rating_change
                new_rating_count = rating_count + 1
                new_average_rating = new_total_rating / new_rating_count

                # Ограничиваем от 2.0 до 10.0
                new_average_rating = max(2.0, min(10.0, new_average_rating))

                self.cursor.execute('''
                    UPDATE user_ratings 
                    SET total_rating = ?, rating_count = ?, average_rating = ?
                    WHERE user_id = ?
                ''', (new_total_rating, new_rating_count, new_average_rating, target_id))

                logging.info(f"Рейтинг пользователя {target_id} обновлен: {new_average_rating:.1f}")
                return True, f"Новый рейтинг: {new_average_rating:.1f}/10"
            else:
                # Создаем новую запись
                initial_rating = 6.0 if vote_type == 'like' else 4.0
                self.cursor.execute('''
                    INSERT INTO user_ratings (user_id, total_rating, rating_count, average_rating)
                    VALUES (?, ?, 1, ?)
                ''', (target_id, initial_rating, initial_rating))

                logging.info(f"Создан новый рейтинг для пользователя {target_id}: {initial_rating}")
                return True, f"Начальный рейтинг: {initial_rating:.1f}/10"

        except Exception as e:
            logging.error(f"Ошибка обновления рейтинга для {target_id}: {e}")
            return False, "Ошибка обновления рейтинга"

    def get_user_vote_history(self, user_id, limit=10):
        """Получает историю голосования пользователя"""
        try:
            self.cursor.execute('''
                SELECT v.vote_type, v.vote_date, u.username,
                       CASE 
                           WHEN v.vote_type = 'like' THEN '👍 Лайк'
                           ELSE '👎 Дизлайк'
                       END as vote_text
                FROM user_votes v
                LEFT JOIN users u ON v.target_id = u.user_id
                WHERE v.voter_id = ?
                ORDER BY v.vote_date DESC
                LIMIT ?
            ''', (user_id, limit))

            votes = self.cursor.fetchall()
            return votes
        except Exception as e:
            logging.error(f"Ошибка получения истории голосования: {e}")
            return []

    def has_user_voted(self, voter_id, target_id):
        """Проверяет, голосовал ли пользователь уже за целевого пользователя"""
        try:
            self.cursor.execute('SELECT 1 FROM user_votes WHERE voter_id = ? AND target_id = ?',
                                (voter_id, target_id))
            return self.cursor.fetchone() is not None
        except Exception as e:
            logging.error(f"Ошибка проверки голоса: {e}")
            return False

    def user_exists(self, user_id):
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE user_id = ?", (user_id,))
        exists = self.cursor.fetchone()[0] > 0
        return exists

    def execute(self, query, params=()):
        """
        Выполняет SQL-запрос с передачей параметров.
        """
        try:
            self.cursor.execute(query, params)  # Выполнение запроса
            self.conn.commit()  # Сохранение изменений
        except sqlite3.Error as e:
            print(f"Ошибка при выполнении запроса: {e}")  # Обработка ошибок

    def increment_scammers_count_all_roles(self, user_id):
        """Увеличивает счетчик скамеров для ЛЮБОЙ роли пользователя"""
        try:
            self.cursor.execute('UPDATE users SET scammers_count = scammers_count + 1 WHERE user_id = ?', (user_id,))
            self.conn.commit()
            logging.info(f"Счетчик скамеров увеличен для пользователя {user_id} (любая роль)")
        except sqlite3.Error as e:
            logging.error(f"Ошибка увеличения счетчика скамеров: {e}")

    def update_total_messages(self, count):
        try:
            logging.info("Обновление количества сообщений...")
            self.cursor.execute('UPDATE statistics SET total_messages = total_messages + ?', (count,))
            self.conn.commit()
            current_count = self.get_total_messages()
            logging.info(f"Текущее количество сообщений в базе данных: {current_count}")
        except sqlite3.Error as e:
            logging.error(f"Ошибка обновления количества сообщений: {e}")

    def get_total_messages(self):
        self.cursor.execute('SELECT total_messages FROM statistics')
        result = self.cursor.fetchone()
        return result[0] if result is not None else 0

    def get_granted_by(self, user_id):
        """Получает ID гаранта для указанного user_id."""
        self.cursor.execute("SELECT granted_by_id FROM users WHERE user_id = ?", (user_id,))
        result = self.cursor.fetchone()
        if result:
            logging.info(f"Гарант найден для user_id {user_id}: {result[0]}")
        else:
            logging.warning(f"Гарант не найден для user_id {user_id}.")
        return result[0] if result else None

    def increment_scammers_count(self, user_id):
        """Увеличивает общий счетчик скамеров для любого пользователя"""
        try:
            # Проверяем, есть ли столбец
            self.cursor.execute("PRAGMA table_info(users)")
            columns = [col[1] for col in self.cursor.fetchall()]

            if 'scammers_count' not in columns:
                logging.error(f"Столбец scammers_count не найден!")
                return False

            # Получаем текущее значение
            current = self.get_user_reported_scammers_count(user_id)
            new_count = current + 1

            self.cursor.execute('UPDATE users SET scammers_count = ? WHERE user_id = ?', (new_count, user_id))
            self.conn.commit()

            logging.info(f"Общий счетчик скамеров для {user_id} увеличен: {current} -> {new_count}")
            return True
        except Exception as e:
            logging.error(f"Ошибка увеличения общего счетчика для {user_id}: {e}")
            return False

    def add_user(self, user_id, username, role_id=0):
        """Безопасно регистрирует пользователя. Повторный вызов не ломает БД."""
        try:
            user_id = int(user_id)
            username = username or str(user_id)
            self.cursor.execute(
                "SELECT user_id, username, role_id FROM users WHERE user_id = ?",
                (user_id,)
            )
            existing = self.cursor.fetchone()
            if existing:
                # Обновляем username только если Telegram дал более актуальное значение.
                if username and (not existing[1] or existing[1] != username):
                    self.cursor.execute(
                        "UPDATE users SET username = ? WHERE user_id = ?",
                        (username, user_id)
                    )
                    self.conn.commit()
                return True

            self.cursor.execute('''
                INSERT INTO users (user_id, username, role_id)
                VALUES (?, ?, ?)
            ''', (user_id, username, int(role_id) if isinstance(role_id, int) and role_id >= 0 else 0))
            self.conn.commit()
            logging.info(f"Пользователь {username} с ID {user_id} зарегистрирован в БД.")
            return True
        except Exception as e:
            logging.error(f"Ошибка регистрации пользователя {user_id}: {e}")
            return False

    def ensure_user(self, user_id, username=None, role_id=0):
        """Гарантирует наличие пользователя в БД перед любой операцией."""
        if not user_id:
            return None
        user_id = int(user_id)
        if username is None:
            username = str(user_id)
        self.add_user(user_id, username, role_id)
        return self.get_user(user_id)

    def get_premium_until(self, user_id):
        """Возвращает срок Premium: None = нет Premium, 0 = навсегда, timestamp = до указанного момента."""
        try:
            self.cursor.execute('SELECT premium_until FROM users WHERE user_id = ?', (int(user_id),))
            row = self.cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            logging.error(f"Ошибка получения Premium для {user_id}: {e}")
            return None

    def is_premium_user(self, user_id):
        """Проверяет активность Premium и очищает просроченный срок."""
        until = self.get_premium_until(user_id)
        if until is None:
            return False
        if int(until) == 0:
            return True
        if int(until) > int(time.time()):
            return True
        try:
            self.cursor.execute('UPDATE users SET premium_until = NULL WHERE user_id = ?', (int(user_id),))
            self.conn.commit()
        except Exception as e:
            logging.error(f"Ошибка очистки просроченного Premium для {user_id}: {e}")
        return False

    def set_premium(self, user_id, until_timestamp):
        """Выдаёт Premium. until_timestamp=0 означает навсегда."""
        try:
            self.ensure_user(int(user_id), str(user_id), 0)
            value = int(until_timestamp) if until_timestamp is not None else 0
            self.cursor.execute('UPDATE users SET premium_until = ? WHERE user_id = ?', (value, int(user_id)))
            self.conn.commit()
            return True
        except Exception as e:
            logging.error(f"Ошибка выдачи Premium {user_id}: {e}")
            return False

    def clear_premium(self, user_id):
        try:
            self.cursor.execute('UPDATE users SET premium_until = NULL WHERE user_id = ?', (int(user_id),))
            self.conn.commit()
            return True
        except Exception as e:
            logging.error(f"Ошибка снятия Premium {user_id}: {e}")
            return False

    def get_user_role(self, user_id):
        """Получает роль пользователя с проверкой соединения"""
        if not self.is_connected():
            self.reconnect()

        try:
            self.cursor.execute('SELECT role_id FROM users WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()
            role = result[0] if result else 0
            logging.info(f"Роль пользователя {user_id}: {role}")
            return role
        except Exception as e:
            logging.error(f"Ошибка получения роли для {user_id}: {e}")
            self.reconnect()
            return 0

    def update_user(self, user_id, country=None, channel=None):
        logging.info(f"Обновление пользователя {user_id}: страна - {country}, канал - {channel}")

        # Явная проверка на None для страны
        if country is not None:
            logging.info(f"Обновляем страну на: {country}")
            self.cursor.execute('UPDATE users SET country = ? WHERE user_id = ?', (country, user_id))

        # Явная проверка на None для канала
        if channel is not None:
            logging.info(f"Обновляем канал на: {channel}")
            self.cursor.execute('UPDATE users SET channel = ? WHERE user_id = ?', (channel, user_id))

        # Выполнение коммита для сохранения изменений
        self.conn.commit()

        # Проверка обновленных данных
        self.cursor.execute('SELECT country, channel FROM users WHERE user_id = ?', (user_id,))
        user_data = self.cursor.fetchone()

        # Логирование обновленных данных
        if user_data:
            logging.info(
                f"Данные пользователя после обновления: id={user_id}, страна={user_data[0]}, канал={user_data[1]}")
        else:
            logging.warning(f"Пользователь с id={user_id} не найден после обновления.")

    def get_user_allowance(self, user_id):
        """Получает сумму ручения для указанного пользователя."""
        try:
            self.cursor.execute("SELECT allowance FROM users WHERE user_id = ?", (user_id,))
            result = self.cursor.fetchone()
            if result:
                allowance = result[0]
                logging.info(f"Сумма ручения для пользователя {user_id}: {allowance}")
                return allowance
            else:
                logging.warning(f"Пользователь с ID {user_id} не найден.")
                return None
        except sqlite3.Error as e:
            logging.error(f"Ошибка при получении суммы ручения для пользователя {user_id}: {e}")
            return None

    def get_user_custom_photo(self, user_id):
        logging.info(f"Attempting to retrieve custom photo for user_id: {user_id}")

        try:
            # Изменяем запрос на правильный столбец
            self.cursor.execute('SELECT custom_photo_url FROM users WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()

            logging.info(f"SQL query executed for user_id {user_id}. Result: {result}")

            if result:
                custom_photo = result[0]
                logging.info(f"Retrieved custom photo for user {user_id}: {custom_photo}")
            else:
                logging.warning(f"No custom photo found for user_id: {user_id}. Result was None.")
                custom_photo = None

        except Exception as e:
            logging.error(f"Error retrieving custom photo for user_id {user_id}: {str(e)}")
            custom_photo = None

        if custom_photo is None:
            logging.info(f"Custom photo for user_id {user_id} is None or not found.")
        else:
            logging.info(f"Custom photo URL for user_id {user_id}: {custom_photo}")

        return custom_photo

    def get_user_custom_photo_url(self, user_id):
        """Получает URL кастомного фото пользователя"""
        try:
            self.cursor.execute('SELECT custom_photo_url FROM users WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()
            return result[0] if result and result[0] else None
        except Exception as e:
            logging.error(f"Error getting custom photo for {user_id}: {e}")
            return None

    def get_user_curator(self, user_id):
        query = "SELECT curator_id FROM users WHERE user_id = ?"
        self.cursor.execute(query, (user_id,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def get_user_name(self, user_id):
        query = "SELECT username FROM users WHERE user_id = ?"
        self.cursor.execute(query, (user_id,))
        result = self.cursor.fetchone()
        return result[0] if result else "Не указано"

    def get_last_spin(self, user_id):
        """Получает время последнего использования команды рулетки для указанного пользователя."""
        self.cursor.execute('SELECT last_spin FROM users WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def update_last_spin(self, user_id):
        """Обновляет время последнего использования команды рулетки для указанного пользователя."""
        self.cursor.execute('UPDATE users SET last_spin = ? WHERE user_id = ?', (datetime.now(), user_id))
        self.conn.commit()

    def add_grant(self, user_id, granted_by_id):
        """Добавляет запись о гарантии для пользователя."""
        try:
            self.cursor.execute('''
                INSERT INTO trust (user_id, granted_by, grant_date)
                VALUES (?, ?, ?)
            ''', (user_id, granted_by_id, datetime.now().isoformat()))
            self.conn.commit()
            logging.info(f"Запись о гарантии для user_id {user_id} добавлена. Granted by ID: {granted_by_id}.")
        except sqlite3.Error as e:
            logging.error(f"Ошибка при добавлении записи о гарантии для user_id {user_id}: {e}")

    def set_profile_checks_count(self, user_id, checks_count):
        # Устанавливаем количество проверок для пользователя
        logging.info(f"Устанавливаем количество проверок для пользователя {user_id}: {checks_count}")

        # Проверяем, существует ли пользователь
        if self.get_user(user_id) is None:
            logging.warning(f"Пользователь {user_id} не найден. Не удается установить количество проверок.")
            return

        self.cursor.execute("UPDATE users SET checks_count = ? WHERE user_id = ?", (checks_count, user_id))
        self.conn.commit()
        logging.info(f"Количество проверок для пользователя {user_id} успешно установлено на {checks_count}")

    def get_profile_checks_count(self, user_id):
        # Получаем количество проверок для пользователя
        logging.info(f"Запрос количества проверок для пользователя {user_id}")
        self.cursor.execute("SELECT checks_count FROM users WHERE user_id = ?", (user_id,))
        result = self.cursor.fetchone()

        if result is not None:
            logging.info(f"Количество проверок для пользователя {user_id}: {result[0]}")
        else:
            logging.warning(f"Пользователь {user_id} не найден в базе данных.")

        return result[0] if result else None

    def update_profile_checks_count(self, user_id, checks_count):
        # Обновляем количество проверок профиля
        if checks_count < 0:
            logging.warning(
                f"Попытка установить отрицательное количество проверок для пользователя {user_id}. Устанавливаем 0.")
            checks_count = 0

        logging.info(f"Обновляем количество проверок для пользователя {user_id} на {checks_count}")
        self.cursor.execute("UPDATE users SET checks_count = ? WHERE user_id = ?", (checks_count, user_id))
        self.conn.commit()
        logging.info(f"Количество проверок для пользователя {user_id} успешно обновлено на {checks_count}")


    def increment_check_count(self, user_id):
        """Увеличивает счетчик проверок для пользователя с указанным user_id, добавляя пользователя в базу, если он не найден."""
        try:
            # Проверяем, существует ли пользователь
            self.cursor.execute('SELECT COUNT(*) FROM users WHERE user_id = ?', (user_id,))
            user_exists = self.cursor.fetchone()[0] > 0

            if not user_exists:
                # Если пользователь не найден, добавляем его в базу данных
                self.cursor.execute('INSERT INTO users (user_id, check_count) VALUES (?, ?)', (user_id, 0))
                logging.info(f"Пользователь с ID {user_id} добавлен в базу данных.")

            # Увеличиваем счетчик
            self.cursor.execute('UPDATE users SET check_count = check_count + 1 WHERE user_id = ?', (user_id,))
            self.conn.commit()
            logging.info(f"Счетчик проверок для пользователя {user_id} увеличен.")
        except sqlite3.Error as e:
            logging.error(f"Ошибка обновления счетчика проверок для {user_id}: {e}")

    def update_warnings(self, user_id):
        try:
            self.cursor.execute('UPDATE users SET warnings = warnings + 1 WHERE user_id = ?', (user_id,))
            self.conn.commit()
            logging.info(f"Количество выговоров для пользователя {user_id} увеличено.")
        except sqlite3.Error as e:
            logging.error(f"Ошибка обновления выговоров для {user_id}: {e}")

    def get_warnings_count(self, user_id):
        result = self.cursor.execute('SELECT warnings FROM users WHERE user_id = ?', (user_id,)).fetchone()
        return result[0] if result is not None else 0

    def reset_warnings(self, user_id):
        """Сбрасывает количество выговоров до 0 для указанного пользователя."""
        self.cursor.execute('UPDATE users SET warnings = 0 WHERE user_id = ?', (user_id,))
        self.conn.commit()
        logging.info(f"Количество выговоров для пользователя {user_id} сброшено до 0.")

    def delete_old_description(self, user_id):
        """Удаляет старое описание."""
        self.cursor.execute("DELETE FROM reasons WHERE user_id = ?", (user_id,))
        self.conn.commit()


    def update_description(self, user_id, new_description):
        try:
            # Обновление описания пользователя в базе данных
            self.cursor.execute("UPDATE users SET description = ? WHERE user_id = ?", (new_description, user_id))
            self.conn.commit()  # Зафиксировать изменения

            # Логирование успешного обновления
            logging.info(f"Описание для пользователя {user_id} обновлено на: {new_description}")

            # Вставка нового описания в статус
            self.update_status(user_id, new_description)
        except Exception as e:
            logging.error(f"Ошибка при обновлении описания: {str(e)}")

    def is_user_in_db(self, user_id):
        """Проверяет, есть ли пользователь в базе данных."""
        self.cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone() is not None

    def get_user_info(self, user_id):
        self.cursor.execute('''
            SELECT user_id, username, role 
            FROM users 
            WHERE user_id = ?
        ''', (user_id,))
        return self.cursor.fetchone()  # Возвращает sqlite3.Row

    def update_status(self, user_id, new_description):
        try:
            # Обновление статуса с новым описанием
            status_message = f"Новое описание: {new_description}"
            self.cursor.execute("UPDATE users SET status = ? WHERE user_id = ?", (status_message, user_id))
            self.conn.commit()  # Зафиксировать изменения

            logging.info(f"Статус для пользователя {user_id} обновлен на: {status_message}")
        except Exception as e:
            logging.error(f"Ошибка при обновлении статуса: {str(e)}")

    def update_user_description(self, user_id, description):
        """Обновляет описание пользователя."""
        try:
            logging.info(f"Попытка обновления описания пользователя {user_id} на: {description}.")

            # Проверяем, существует ли пользователь перед обновлением
            existing_user = self.get_user(user_id)
            if not existing_user:
                logging.warning(f"Пользователь с ID {user_id} не найден. Описание не может быть обновлено.")
                return False

            # Обновляем описание
            self.cursor.execute('UPDATE users SET description = ? WHERE user_id = ?', (description, user_id))
            self.conn.commit()

            # Проверяем, обновилось ли описание
            updated_description = self.get_user_description(user_id)
            if updated_description == description:
                logging.info(f"Описание пользователя {user_id} успешно обновлено на: {description}.")
            else:
                logging.error(
                    f"Описание пользователя {user_id} не обновилось. Текущее значение: {updated_description}.")

            return True
        except sqlite3.Error as e:
            logging.error(f"Ошибка обновления описания для {user_id}: {e}")
            return False

    def get_user_description(self, user_id):
        try:
            self.cursor.execute('SELECT description FROM scammers WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()
            if result and result[0]:
                logging.info(f"Описание для пользователя {user_id}: {result[0]}.")
                return result[0]
            else:
                logging.warning(f"Описание для пользователя {user_id} не найдено.")
                return "Описание отсутствует"
        except sqlite3.Error as e:
            logging.error(f"Ошибка при получении описания для пользователя {user_id}: {e}")
            return "Ошибка базы данных"

    def update_role(self, user_id, role_id, granted_by_id=None):
        """Обновляет роль пользователя"""
        try:
            # Обновляем роль
            self.cursor.execute('UPDATE users SET role_id = ? WHERE user_id = ?', (role_id, user_id))
            role_name = ROLES.get(int(role_id), {}).get('name') if 'ROLES' in globals() else None
            if role_name is not None:
                self.cursor.execute('UPDATE users SET role = ? WHERE user_id = ?', (role_name, user_id))

            if granted_by_id is not None:
                self.cursor.execute('UPDATE users SET granted_by_id = ? WHERE user_id = ?', (granted_by_id, user_id))

            # ВСЕГДА делаем commit
            self.conn.commit()
            logging.info(f"Роль пользователя {user_id} обновлена на {role_id}. Granted by ID: {granted_by_id}.")
            return True
        except sqlite3.Error as e:
            logging.error(f"Ошибка обновления роли для {user_id}: {e}")
            return False

    def add_scammer(self, scammer_id, reason, reported_by, description, unique_id, proof_link=None, reporter_id=None):
        """Надёжно добавляет запись о скаммере и поддерживает старые Ice.db."""
        try:
            scammer_id = int(scammer_id)
            reporter_id = int(reporter_id) if reporter_id is not None else None
            self.check_and_add_missing_columns('scammers')

            if reporter_id:
                self.ensure_user(reporter_id, str(reporter_id), 0)
            self.ensure_user(scammer_id, str(scammer_id), 0)

            self.cursor.execute(
                """
                INSERT INTO scammers
                    (user_id, scammer_id, reason, reported_by, description,
                     reporter_id, unique_id, proof_link)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (scammer_id, scammer_id, reason or '', reported_by or '',
                 description or '', reporter_id, unique_id or str(uuid.uuid4()),
                 proof_link or '')
            )

            if reporter_id:
                self.cursor.execute(
                    "UPDATE users SET scammers_count = COALESCE(scammers_count, 0) + 1 WHERE user_id = ?",
                    (reporter_id,)
                )

            self.conn.commit()
            logging.info(f"Скаммер {scammer_id} добавлен в базу; reporter_id={reporter_id}")
            return True
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass
            logging.error(f"Ошибка при добавлении скаммера {scammer_id}: {e}", exc_info=True)
            return False

    def get_scammer_details(self, user_id):
        """Получает все записи о скамере с доказательствами и причинами"""
        try:
            self.cursor.execute('''
                SELECT reason, proof_link, reported_by, added_date 
                FROM scammers 
                WHERE user_id = ? 
                ORDER BY added_date DESC
            ''', (user_id,))
            return self.cursor.fetchall()
        except Exception as e:
            logging.error(f"Ошибка получения данных скамера: {e}")
            return []

    def update_reason(self, user_id, reason):
        """Обновляет причину заноса для указанного пользователя."""
        self.cursor.execute('''
            INSERT INTO reasons (user_id, reason) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET reason=excluded.reason
        ''', (user_id, reason))
        self.conn.commit()

    def add_additional_reason(self, user_id, additional_reason):
        """Добавляет дополнительное описание для указанного пользователя."""
        # Предполагаем, что у вас есть отдельная таблица для дополнительных описаний
        self.cursor.execute('''
            INSERT INTO additional_reasons (user_id, additional_reason) VALUES (?, ?)
        ''', (user_id, additional_reason))
        self.conn.commit()

    def get_user_reported_scammers_count(self, user_id):
        """Получает количество СЛИТЫХ скамеров (сколько занес в базу scammers)"""
        try:
            # Вариант 1: Ищем по reporter_id если есть такое поле
            self.cursor.execute("PRAGMA table_info(scammers)")
            columns = [col[1] for col in self.cursor.fetchall()]

            if 'reporter_id' in columns:
                self.cursor.execute('SELECT COUNT(*) FROM scammers WHERE reporter_id = ?', (user_id,))
                result = self.cursor.fetchone()
                count = result[0] if result else 0

                if count > 0:
                    logging.info(f"Найдено {count} слитых скамеров для {user_id} (по reporter_id)")
                    return count

            # Вариант 2: Ищем по имени в reported_by
            # Получаем имя пользователя из базы
            self.cursor.execute('SELECT username, first_name FROM users WHERE user_id = ?', (user_id,))
            user_info = self.cursor.fetchone()

            if user_info:
                username = user_info[0] or user_info[1] or str(user_id)
                # Ищем упоминания имени в reported_by
                self.cursor.execute('SELECT COUNT(*) FROM scammers WHERE reported_by LIKE ?', (f'%{username}%',))
                result = self.cursor.fetchone()
                count = result[0] if result else 0

                logging.info(f"Найдено {count} слитых скамеров для {user_id} (по имени в reported_by)")
                return count

            return 0
        except Exception as e:
            logging.error(f"Ошибка получения количества слитых скамеров для {user_id}: {e}")
            return 0

    def update_user_scammers_count(self, user_id, new_count):
        """Обновляет количество слитых скаммеров для указанного пользователя."""
        try:
            self.cursor.execute('UPDATE users SET scammers_slept = ? WHERE user_id = ?', (new_count, user_id))
            self.conn.commit()
            logging.info(f"Количество слитых скаммеров для пользователя {user_id} обновлено на {new_count}.")
        except sqlite3.Error as e:
            logging.error(f"Ошибка при обновлении количества слитых скаммеров для {user_id}: {e}")

    def get_user(self, user_id):
        self.cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        if result:
            logging.info(f"Пользователь найден: {result}")
        else:
            logging.info(f"Пользователь с ID {user_id} не найден.")
        return result

    def is_scammer(self, user_id):
        self.cursor.execute("SELECT * FROM scammers WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone() is not None

    async def update_user_check_count(self, user_id):
        async with self.lock:
            try:
                self.cursor.execute('UPDATE users SET check_count = check_count + 1 WHERE user_id = ?', (user_id,))
                self.conn.commit()
                logging.info(f"Счетчик проверок для пользователя {user_id} обновлен.")
            except sqlite3.Error as e:
                logging.error(f"Ошибка при обновлении счетчика проверок для {user_id}: {e}")

    def get_check_count(self, user_id):
        try:
            self.cursor.execute('SELECT check_count FROM users WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()
            count = result[0] if result else 0
            logging.info(f"Количество проверок для пользователя {user_id}: {count}")
            return count
        except Exception as e:
            logging.error(f"Ошибка базы данных в get_check_count: {e}")
            return 0

    def get_display_scammers_count(self, user_id):
        """Получает количество для отображения в чеке"""
        try:
            # 1. Получаем из поля scammers_count таблицы users
            self.cursor.execute('SELECT scammers_count FROM users WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()

            if result:
                count_from_users = result[0] if result[0] is not None else 0
            else:
                count_from_users = 0
                # Если пользователя нет, добавляем запись
                self.cursor.execute('INSERT OR IGNORE INTO users (user_id, scammers_count) VALUES (?, 0)', (user_id,))
                self.conn.commit()

            logging.info(f"📊 Из поля scammers_count для {user_id}: {count_from_users}")

            # 2. Проверяем таблицу scammers
            real_count = 0

            # Проверяем есть ли поле reporter_id
            self.cursor.execute("PRAGMA table_info(scammers)")
            columns = [col[1] for col in self.cursor.fetchall()]

            if 'reporter_id' in columns:
                # Ищем по reporter_id
                self.cursor.execute('SELECT COUNT(*) FROM scammers WHERE reporter_id = ?', (user_id,))
                real_result = self.cursor.fetchone()
                real_count = real_result[0] if real_result else 0

                if real_count > 0:
                    logging.info(f"🔍 Найдено {real_count} записей в scammers для {user_id} по reporter_id")

            # 3. Если не нашли по reporter_id, ищем в reported_by
            if real_count == 0:
                try:
                    # Получаем username для поиска
                    self.cursor.execute('SELECT username FROM users WHERE user_id = ?', (user_id,))
                    user_result = self.cursor.fetchone()

                    if user_result and user_result[0]:
                        username = user_result[0]
                        self.cursor.execute('SELECT COUNT(*) FROM scammers WHERE reported_by LIKE ?',
                                            (f'%{username}%',))
                        real_result = self.cursor.fetchone()
                        real_count = real_result[0] if real_result else 0

                        if real_count > 0:
                            logging.info(f"🔍 Найдено {real_count} записей в scammers для {user_id} по username")
                except Exception as e:
                    logging.error(f"Ошибка поиска по username: {e}")

            # 4. Возвращаем большее значение
            final_count = max(count_from_users, real_count)
            logging.info(
                f"🎯 Финальное значение для {user_id}: users={count_from_users}, scammers={real_count}, итого={final_count}")
            return final_count

        except Exception as e:
            logging.error(f"❌ Ошибка в get_display_scammers_count для {user_id}: {e}")
            return 0

    def get_user_scammers_slept(self, user_id):
        """Получает количество слитых скаммеров для указанного пользователя."""
        logging.info(f"Запрос на получение количества слитых скаммеров для пользователя {user_id}.")
        query = 'SELECT scammers_slept FROM users WHERE user_id = ?'
        self.cursor.execute(query, (user_id,))
        result = self.cursor.fetchone()
        if result:
            logging.info(f"Пользователь {user_id} имеет {result[0]} слитых скаммеров.")
            return result[0]
        else:
            logging.warning(f"Пользователь {user_id} не найден, возвращаем 0.")
            return 0

    def update_user_scammers_slept(self, user_id, new_count):
        logging.info(f"Обновление количества слитых скаммеров для пользователя {user_id} на {new_count}.")
        try:
            self.cursor.execute('''
                UPDATE users SET scammers_slept = ? WHERE user_id = ?
            ''', (new_count, user_id))
            self.conn.commit()
            logging.info(f"Количество слитых скаммеров для пользователя {user_id} успешно обновлено на {new_count}.")
            return True
        except sqlite3.Error as e:
            logging.error(f"Ошибка обновления количества слитых скаммеров для пользователя {user_id}: {e}")
            return False

    def remove_scammer_status(self, user_id):
        try:
            # Проверка, есть ли пользователь в базе скаммеров
            if not self.is_scammer(user_id):  # Если пользователя уже нет в базе
                return False  # Возвращаем False, чтобы бот сообщил об ошибке

            # Удаление пользователя из таблицы скаммеров
            self.cursor.execute("DELETE FROM scammers WHERE user_id = ?", (user_id,))
            self.conn.commit()

            # Обновление роли пользователя на "Нет в базе" (0)
            self.cursor.execute("UPDATE users SET role_id = 0 WHERE user_id = ?", (user_id,))
            self.conn.commit()
            logging.info(f"Статус скамера для пользователя {user_id} успешно снят.")

            return True  # Возвращаем True, если всё прошло успешно
        except sqlite3.Error as e:
            logging.error(f"Ошибка при удалении статуса скамера для пользователя {user_id}: {e}")
            return False  # Возвращаем False, если произошла ошибка


    def set_user_allowance(self, user_id, amount):
        try:
            self.cursor.execute("UPDATE users SET allowance = ? WHERE user_id = ?", (amount, user_id))
            self.conn.commit()

            if self.cursor.rowcount == 0:
                logging.warning(f"Пользователь с ID {user_id} не найден.")
            else:
                logging.info(f"Сумма ручения для пользователя с ID {user_id} успешно обновлена на {amount}.")
        except sqlite3.Error as e:
            logging.error(f"Ошибка при обновлении суммы ручения: {e}")


    def add_check(self, checker_id, target_id):
        """Добавляет запись о проверке."""
        try:
            self.cursor.execute('''
                INSERT INTO checks (checker_id, target_id, check_date)
                VALUES (?, ?, ?)
            ''', (checker_id, target_id, datetime.now().isoformat()))
            self.conn.commit()
            logging.info(f"Запись о проверке добавлена: checker_id={checker_id}, target_id={target_id}")
        except sqlite3.Error as e:
            logging.error(f"Ошибка при добавлении записи о проверке: {e}")

    async def __aenter__(self):
        await self.lock.acquire()
        logging.info("База данных открыта для асинхронного доступа.")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.lock.release()
        logging.info("База данных закрыта для асинхронного доступа.")

    def close(self):
        try:
            self.conn.close()
            logging.info("Соединение с базой данных закрыто.")
            return True
        except sqlite3.Error as e:
            logging.error(f"Ошибка закрытия БД: {e}")
            return False

main_buttons = [
    [Button.text("🎭 Профиль", resize=True)],
    [Button.text("👥 Состав базы", resize=True), Button.text("🔰 Проверенные пользователи", resize=True)],
    [Button.text("📊 Статистика базы", resize=True), Button.text("🚫 Слить скаммера!", resize=True)],
]

# Роли пользователей
ROLES = {
    0: {"name": "Нет в базе 📝", "preview_url": "https://i.ibb.co/8LQLcmcV/1000049443.jpg", "scam_chance": 31},
    1: {"name": "Гарант 🛡️", "preview_url": "https://i.ibb.co/YFrbHTD3/1000049442.jpg", "scam_chance": 1},
    2: {"name": "Возможно скамер ⚠️", "preview_url": "https://i.ibb.co/P2Xf9NQ/1000049445.jpg", "scam_chance": 65},
    3: {"name": "Скамер ❌", "preview_url": "https://i.ibb.co/Pbf1StL/1000049528.jpg", "scam_chance": 99},
    4: {"name": "Петух 🐓", "preview_url": "https://i.ibb.co/Pbf1StL/1000049528.jpg", "scam_chance": 45},
    6: {"name": "Стажёр 🎓", "preview_url": "https://i.ibb.co/yBbbsxHN/processed-01-1280x720.jpg", "scam_chance": 20},
    7: {"name": "Админ 👮", "preview_url": "https://i.ibb.co/pB4r6dv5/1000049522.jpg", "scam_chance": 15},
    8: {"name": "Директор 👔", "preview_url": "https://i.ibb.co/HDcsG0Dz/1000049523.jpg", "scam_chance": 10},
    9: {"name": "Президент 👑", "preview_url": "https://i.ibb.co/d0rHVp3g/1000049524.jpg", "scam_chance": 5},
    10: {"name": "Создатель ⭐", "preview_url": "https://i.ibb.co/RpSLfGqW/1000049520.jpg", "scam_chance": 1},
    11: {"name": "Кодер 💻", "preview_url": "https://i.ibb.co/r24QRqBs/1000049521.jpg", "scam_chance": 3},
    12: {"name": "Проверен гарантом ✅", "preview_url": "https://i.ibb.co/Q3RFxhSx/1000049444.jpg", "scam_chance": 5},
    13: {"name": "сын шлюхи⭐", "preview_url": "", "scam_chance": 50}
}

# Добавьте в начало файла после ROLES:

# Все роли персонала базы (кто защищен от заноса)
STAFF_ROLES = [1, 6, 7, 8, 9, 10, 11, 12, 13]

def can_manage_profile_features(user_id):
    # Кастомное фото и канал — платные функции. Доступ есть только при активном Premium.
    try:
        return db.is_premium_user(user_id)
    except Exception:
        return False

def can_grant_premium(user_id):
    # Выдавать Premium могут только Президент (9) и Владелец (10).
    try:
        role_id = db.get_user_role(user_id)
        return role_id in (9, 10) or user_id in OWNER_ID
    except Exception:
        return False

MUTE_ALLOWED_ROLES = {6, 7, 8, 9, 10}  # Стажёр -> Админ -> Директор -> Президент -> Владелец
BAN_ALLOWED_ROLES = {7, 8, 9, 10}      # Админ -> Директор -> Президент -> Владелец

# Роли, которым разрешено заносить (все персоналы кроме некоторых)
CAN_ADD_SCAMMER_ROLES = [1, 6, 7, 8, 9, 10, 11]  # Все могут заносить, но...
# 12 (Проверен гарантом) не может заносить



# Инициализация бота
bot = TelegramClient(os.path.join(DATA_DIR, 'sosot.session'), API_ID, API_HASH).start(bot_token=BOT_TOKEN)
db = Database()

# Автоматическая регистрация: любой пользователь, взаимодействующий с ботом,
# получает запись в users ещё до открытия профиля/проверки.
@bot.on(events.NewMessage)
async def ensure_sender_registered(event):
    try:
        user_id = event.sender_id
        if not user_id:
            return
        sender = await event.get_sender()
        if getattr(sender, 'bot', False):
            return
        username = getattr(sender, 'username', None) or getattr(sender, 'first_name', None) or str(user_id)
        db.ensure_user(user_id, username, 0)
    except Exception as e:
        logging.error(f"Ошибка авто-регистрации пользователя: {e}")

# Гарантируем наличие владельцев в БД при каждом запуске.
for _owner_id in DEFAULT_OWNER_IDS:
    try:
        db.ensure_user(_owner_id, str(_owner_id), 10)
        db.update_role(_owner_id, 10, granted_by_id=_owner_id)
    except Exception as e:
        logging.error(f"Ошибка инициализации владельца {_owner_id}: {e}")

def get_guarantors():
    """Получает список гарантов из базы данных"""
    try:
        db.cursor.execute('SELECT user_id FROM users WHERE role_id = 1')  # role_id = 1 - гарант
        guarantors = db.cursor.fetchall()
        return [guarantor[0] for guarantor in guarantors]
    except Exception as e:
        logging.error(f"Ошибка при получении гарантов: {e}")
        return []

def get_trainees():
    """Получает список стажеров из базы данных"""
    try:
        db.cursor.execute("SELECT * FROM trainees")
        trainees = db.cursor.fetchall()
        return trainees
    except Exception as e:
        logging.error(f"Ошибка при получении стажеров: {e}")
        return []


@bot.on(events.NewMessage(pattern="👥 Состав базы"))
async def members_menu(event):
    if not event.is_private:
        return

    user_id = event.sender_id

    # Проверка защиты от спама
    can_press, message = check_button_spam_protection(user_id)
    if not can_press:
        await event.respond(message)
        return

    # Показываем загрузку
    await show_button_loading(event, "состав базы")

    buttons = [
        [Button.text("✅ Гаранты базы", resize=True)],
        [Button.text("👨‍🎓 Волонтёры базы", resize=True)],
        [Button.text("↩ Назад", resize=True)]
    ]

    # Удаляем сообщение о загрузке если есть
    if user_id in button_loading_messages:
        try:
            await bot.delete_messages(event.chat_id, button_loading_messages[user_id])
            del button_loading_messages[user_id]
        except:
            pass

    await event.respond(
        "👥 **Меню состава базы**\n\n"
        "Выберите категорию участников для просмотра:",
        buttons=buttons,
        parse_mode='md'
    )


@bot.on(events.NewMessage(pattern="↩ Назад"))
async def back_to_main(event):
    if not event.is_private:
        return

    user_id = event.sender_id

    # Проверка защиты от спама (но менее строгая для кнопки Назад)
    can_press, message = check_button_spam_protection(user_id)
    if not can_press:
        await event.respond(message)
        return

    # Показываем загрузку
    await show_button_loading(event, "главное меню")

    # Удаляем сообщение о загрузке если есть
    if user_id in button_loading_messages:
        try:
            await bot.delete_messages(event.chat_id, button_loading_messages[user_id])
            del button_loading_messages[user_id]
        except:
            pass

    await event.respond(
        "Главное меню:",
        buttons=main_buttons
    )


@bot.on(events.NewMessage(pattern="📊 Статистика базы"))
async def statistics(event):
    if not event.is_private:
        return

    user_id = event.sender_id

    # Проверка защиты от спама
    can_press, message = check_button_spam_protection(user_id)
    if not can_press:
        await event.respond(message)
        return

    # Показываем загрузку
    await show_button_loading(event, "статистику")

    try:
        # Получаем общую статистику
        total_scammers = db.cursor.execute('SELECT COUNT(*) FROM scammers').fetchone()[0] or 0
        total_users = db.cursor.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        total_checks = db.cursor.execute('SELECT SUM(check_count) FROM users').fetchone()[0] or 0

        # Получаем топ персонала по количеству слитых скамеров
        top_staff = db.cursor.execute('''
            SELECT u.user_id, u.username, u.role_id, u.scammers_count 
            FROM users u 
            WHERE u.role_id IN (6, 7, 8, 9, 10, 11, 13) 
            AND u.scammers_count > 0
            ORDER BY u.scammers_count DESC 
            LIMIT 10
        ''').fetchall()

        # Формируем текст статистики
        text = f"""📊 **СТАТИСТИКА БАЗЫ FORGET**
━━━━━━━━━━━━━━━━━━━━


🚫 **Скаммеров в базе:** `{total_scammers}`
👥 **Пользователей бота:** `{total_users}`
🔍 **Всего проверок:** `{total_checks}`

🏆 **ТОП ПЕРСОНАЛА ПО СЛИТЫМ СКАМЕРАМ:**
"""

        # Создаем кнопки для топ персонала
        buttons = []

        for i, (user_id_staff, username, role_id, scammers_count) in enumerate(top_staff, 1):
            # Получаем имя роли
            role_name = ROLES.get(role_id, {}).get('name', 'Неизвестно')
            role_emoji = get_role_emoji(role_id)

            # Формируем отображаемое имя
            if username:
                display_name = f"{username}"
            else:
                display_name = f"ID:{user_id_staff}"

            # Сокращаем слишком длинные имена
            if len(display_name) > 15:
                display_name = display_name[:12] + "..."

            # Добавляем кнопку
            button_text = f"{role_emoji} {display_name} - {scammers_count}🔪"
            buttons.append([Button.inline(button_text, f"staff_stats_{user_id_staff}")])

        # Если нет топ персонала
        if not top_staff:
            text += "\n📭 Пока нет активного персонала"

        # Добавляем разделитель
        text += "\n━━━━━━━━━━━━━━━━━━━━\n"

        # Кнопки навигации
        nav_buttons = [
            [Button.inline("🏆 Топ Стажеров", b"top_trainees")],
            [Button.inline("😎 Топ Активных", b"top_day")],
            [Button.inline("🔄 Обновить", b"refresh_stats")]
        ]

        buttons.extend(nav_buttons)

        # Добавляем кнопку чата
        buttons.append([Button.url("🎇 Наша База", 'https://t.me/Forget_base')])

        # Удаляем сообщение о загрузке если есть
        if user_id in button_loading_messages:
            try:
                await bot.delete_messages(event.chat_id, button_loading_messages[user_id])
                del button_loading_messages[user_id]
            except:
                pass

        stat_message = await event.respond(text, parse_mode='md', link_preview=True, buttons=buttons)
        bot.stat_message_id = stat_message.id

    except Exception as e:
        logging.error(f"Ошибка в статистике: {e}")
        await event.respond(f"⚠️ Ошибка загрузки статистики: {str(e)}")


# Вспомогательная функция для эмодзи ролей


@bot.on(events.NewMessage(pattern=r'(?i)^/fullstats|/полнаястата'))
async def full_statistics(event):
    """Полная статистика по всем ролям"""
    if not event.is_private:
        return

    user_id = event.sender_id

    try:
        # Получаем статистику по каждой роли
        stats_by_role = {}

        for role_id in [6, 7, 8, 9, 10, 11, 13]:  # Все роли персонала
            role_name = ROLES.get(role_id, {}).get('name', 'Неизвестно')

            # Количество пользователей с этой ролью
            db.cursor.execute('SELECT COUNT(*) FROM users WHERE role_id = ?', (role_id,))
            count_users = db.cursor.fetchone()[0] or 0

            # Общее количество слитых скамеров для этой роли
            db.cursor.execute('SELECT SUM(scammers_count) FROM users WHERE role_id = ?', (role_id,))
            total_scammers = db.cursor.fetchone()[0] or 0

            # Топ 3 пользователя этой роли
            db.cursor.execute('''
                SELECT user_id, username, scammers_count 
                FROM users 
                WHERE role_id = ? AND scammers_count > 0
                ORDER BY scammers_count DESC 
                LIMIT 3
            ''', (role_id,))
            top_users = db.cursor.fetchall()

            stats_by_role[role_id] = {
                'name': role_name,
                'count_users': count_users,
                'total_scammers': total_scammers,
                'top_users': top_users
            }

        # Формируем сообщение
        text = "🏆 **ПОЛНАЯ СТАТИСТИКА ПЕРСОНАЛА**\n━━━━━━━━━━━━━━━━━━━━\n\n"

        # Создаем кнопки по ролям
        role_buttons = []

        for role_id in [6, 7, 8, 9, 10, 11, 13]:
            stats = stats_by_role[role_id]
            emoji = get_role_emoji(role_id)
            button_text = f"{emoji} {stats['name']} - {stats['total_scammers']}🔪"
            role_buttons.append([Button.inline(button_text, f"role_stats_{role_id}")])

        # Кнопки навигации
        nav_buttons = [
            [Button.inline("📊 Общая статистика", b"general_stats")],
            [Button.inline("👥 Все пользователи", b"all_users_stats")],
            [Button.inline("🔄 Обновить", b"refresh_fullstats")]
        ]

        all_buttons = role_buttons + nav_buttons

        await event.respond(text, parse_mode='md', link_preview=True, buttons=all_buttons)

    except Exception as e:
        logging.error(f"Ошибка в полной статистике: {e}")
        await event.respond(f"⚠️ Ошибка: {str(e)}")

def get_role_emoji(role_id):
    """Возвращает эмодзи для роли"""
    emoji_map = {
        6: "👨‍🎓",  # Стажер
        7: "👮",   # Админ
        8: "🎩",   # Директор
        9: "👑",   # Президент
        10: "⭐",  # Владелец
        11: "💻",  # Кодер
        13: "🌟"   # Айдош
    }
    return emoji_map.get(role_id, "👤")

@bot.on(events.NewMessage(pattern='/check_my_photo'))
async def check_my_photo(event):
    user_id = event.sender_id

    # Проверяем структуру таблицы
    db.cursor.execute("PRAGMA table_info(users)")
    columns = db.cursor.fetchall()
    print("Структура таблицы users:")
    for i, col in enumerate(columns):
        print(f"{i}: {col}")

    # Проверяем конкретно нашу запись
    db.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user_data = db.cursor.fetchone()
    print(f"Все данные пользователя: {user_data}")

    if user_data:
        print(f"custom_photo_url: {user_data[8] if len(user_data) > 8 else 'NO COLUMN'}")

    await event.respond("Проверка завершена, смотрите консоль")


@bot.on(events.CallbackQuery(pattern=r'rate_user_(\d+)'))
async def rate_user_handler(event):
    """Обработчик оценки пользователя"""
    try:
        target_user_id = int(event.pattern_match.group(1))
        voter_id = event.sender_id

        # Проверяем, может ли пользователь голосовать
        can_vote, message = db.can_user_vote(voter_id, target_user_id)

        if not can_vote:
            await event.answer(message, alert=True)
            return

        # Получаем информацию о целевом пользователе
        try:
            target_user = await bot.get_entity(target_user_id)
            target_name = target_user.first_name
        except:
            target_name = f"Пользователь {target_user_id}"

        # Получаем текущий рейтинг
        current_rating = db.get_user_rating(target_user_id)
        rating_stars = "⭐" * int(current_rating / 2)

        # Создаем inline-клавиатуру для оценки
        buttons = [
            [
                Button.inline("👍 Лайк (+1)", f"vote_like_{target_user_id}"),
                Button.inline("👎 Дизлайк (-1)", f"vote_dislike_{target_user_id}")
            ],
            [
                Button.inline("📊 История голосов", f"vote_history_{target_user_id}"),
                Button.inline("❌ Отмена", "cancel_rate")
            ]
        ]

        # ВМЕСТО event.edit() используем event.respond() для нового сообщения
        await event.answer()  # Сначала отвечаем на callback
        await event.respond(
            f"📊 **Оцените пользователя**\n\n"
            f"👤 **Пользователь:** {target_name}\n"
            f"⭐ **Текущий рейтинг:** {current_rating:.1f}/10\n"
            f"{rating_stars}\n\n"
            f"Выберите оценку:",
            buttons=buttons
        )

    except Exception as e:
        logging.error(f"Ошибка в rate_user_handler: {e}")
        await event.answer("❌ Произошла ошибка", alert=True)


@bot.on(events.CallbackQuery(pattern=r'vote_(like|dislike)_(\d+)'))
async def vote_handler(event):
    """Обработчик голосования"""
    try:
        vote_type = event.pattern_match.group(1).decode('utf-8')  # Декодируем из bytes в str
        target_user_id = int(event.pattern_match.group(2))
        voter_id = event.sender_id

        # Добавляем голос
        success, message = db.add_user_vote(voter_id, target_user_id, vote_type)

        if success:
            # Получаем новый рейтинг
            new_rating = db.get_user_rating(target_user_id)
            rating_stars = "⭐" * int(new_rating / 2)

            vote_text = "👍 Лайк" if vote_type == 'like' else "👎 Дизлайк"

            # Редактируем сообщение вместо удаления
            await event.edit(
                f"✅ **Оценка принята!**\n\n"
                f"📊 **Новый рейтинг:** {new_rating:.1f}/10\n"
                f"{rating_stars}\n\n"
                f"📝 Ваша оценка: {vote_text}",
                buttons=None
            )

            # Уведомляем пользователя (если он не заблокировал бота)
            try:
                voter_user = await bot.get_entity(voter_id)
                voter_name = voter_user.first_name

                notification_text = (
                    f"📢 **Вас оценили!**\n\n"
                    f"Пользователь {voter_name} поставил вам {vote_text.lower()}.\n"
                    f"Ваш новый рейтинг: {new_rating:.1f}/10\n"
                    f"⭐ {'⭐' * int(new_rating / 2)}"
                )

                await bot.send_message(target_user_id, notification_text)
            except:
                pass  # Пользователь заблокировал бота

        else:
            await event.answer(message, alert=True)

    except Exception as e:
        logging.error(f"Ошибка в vote_handler: {e}")
        await event.answer("❌ Произошла ошибка при обработке голоса", alert=True)


@bot.on(events.CallbackQuery(pattern=r'vote_history_(\d+)'))
async def vote_history_handler(event):
    """Показывает историю голосования"""
    try:
        target_user_id = int(event.pattern_match.group(1))
        voter_id = event.sender_id

        # Получаем историю голосования
        votes = db.get_user_vote_history(voter_id, limit=5)

        if not votes:
            await event.answer("📭 У вас пока нет истории голосования", alert=True)
            return

        history_text = "📋 **Последние оценки:**\n\n"
        for vote in votes:
            vote_type, vote_date, username, vote_text = vote
            user_display = username or f"ID:{target_user_id}"

            # Форматируем дату
            try:
                vote_date_obj = datetime.strptime(vote_date, '%Y-%m-%d %H:%M:%S')
                formatted_date = vote_date_obj.strftime('%d.%m.%Y')
            except:
                formatted_date = vote_date

            history_text += f"• {vote_text} для {user_display} ({formatted_date})\n"

        # Добавляем статистику
        total_votes = len(votes)
        likes = sum(1 for v in votes if v[0] == 'like')
        dislikes = total_votes - likes

        history_text += f"\n📊 **Статистика:**\n"
        history_text += f"Всего оценок: {total_votes}\n"
        history_text += f"Лайков: {likes} | Дизлайков: {dislikes}"

        await event.edit(
            history_text,
            buttons=[
                [Button.inline("« Назад к оценке", f"rate_user_{target_user_id}")]
            ]
        )

    except Exception as e:
        logging.error(f"Ошибка в vote_history_handler: {e}")
        await event.answer("❌ Произошла ошибка", alert=True)


@bot.on(events.CallbackQuery(pattern='cancel_rate'))
async def cancel_rate_handler(event):
    """Отмена оценки"""
    await event.delete()
    await event.answer("❌ Оценка отменена", alert=False)


async def get_user_profile_response(event, user, user_data):
    user_id = user.id
    role_id = db.get_user_role(user_id)

    print(f"User ID: {user_id}, Role: {role_id}")

    premium_active = db.is_premium_user(user_id)
    custom_image_url = db.get_user_custom_photo_url(user_id) if premium_active else None
    print(f"Custom image URL: {custom_image_url}")

    logging.info(f"Проверка профиля для user_id: {user_id}, role_id: {role_id}")

    # Получаем данные пользователя из user_data или базы
    if user_data:
        country = user_data[5].strip() if len(user_data) > 5 and user_data[5] else "❓"
        channel = user_data[6].strip() if len(user_data) > 6 and user_data[6] else "❓"
    else:
        country = "❓"
        channel = "❓"

    description = db.get_user_description(user_id) or "Нет описания"
    checks_count = db.get_check_count(user_id)
    logging.info(f"Количество проверок для user_id {user_id} после увеличения: {checks_count}")

    # ✅ ИСПРАВЛЕНО: Получаем ПРАВИЛЬНОЕ количество для отображения
    # Используем новый метод get_display_scammers_count
    scammers_display_count = db.get_display_scammers_count(user_id)

    # Для обратной совместимости
    scammers_slept = scammers_display_count

    logging.info(f"Custom image URL retrieved for user {user_id}: {custom_image_url}")

    current_time = datetime.now().strftime("%d.%m.%Y")

    try:
        user_rating = db.get_user_rating(user_id)
        rating_stars = "⭐" * int(user_rating / 2)
        rating_display = f"{rating_stars} {user_rating:.1f}/10"
    except Exception as e:
        logging.error(f"Ошибка получения рейтинга для {user_id}: {e}")
        rating_display = "⭐ 5.0/10"

    # Получаем имя пользователя для отображения
    if hasattr(user, 'first_name') and user.first_name:
        user_name = user.first_name
    elif hasattr(user, 'title') and user.title:
        user_name = user.title
    elif hasattr(user, 'username') and user.username:
        user_name = f"@{user.username}"
    else:
        user_name = f"ID: {user.id}"

    if hasattr(user, 'username') and user.username:
        profile_url = f"https://t.me/{user.username}"
    else:
        profile_url = f"tg://user?id={user.id}"

    # Получаем все записи о скамере для отображения в профиле
    scammer_details = ""
    if role_id in [2, 3, 4]:  # Все типы скамеров
        details = db.get_scammer_details(user_id)
        if details:
            scammer_details = "\n\n📋 **История заносов:**\n"
            for i, (reason, proof_link, reported_by, added_date) in enumerate(details, 1):
                # Форматируем дату
                if added_date:
                    try:
                        if isinstance(added_date, str):
                            date_obj = datetime.strptime(added_date, '%Y-%m-%d %H:%M:%S')
                            formatted_date = date_obj.strftime('%d.%m.%Y %H:%M')
                        else:
                            formatted_date = str(added_date)[:16]
                    except:
                        formatted_date = str(added_date)
                else:
                    formatted_date = "Неизвестно"

                # Формируем текст доказательств
                if proof_link and proof_link.startswith(('http://', 'https://')):
                    proof_text = f"[Доказательства]({proof_link})"
                elif proof_link:
                    proof_text = f"📎 {proof_link[:50]}..."
                else:
                    proof_text = "Нет доказательств"

                scammer_details += f"**{i}. 📝 Причина:** {reason}\n"
                scammer_details += f"   🔗 **{proof_text}**\n"
                scammer_details += f"   👮 **Занес:** {reported_by}\n"
                scammer_details += f"   📅 **Дата:** {formatted_date}\n\n"

    profile_url = f"tg://user?id={user.id}"
    buttons = [
        [
            Button.url("🎧 Профиль", profile_url),
        ],
        [
            Button.inline("🚫 Слить скаммера", f"sliv_scammers_{user_id}".encode())
        ]
    ]

    if role_id in [2, 3, 4]:  # Возможно скамер, Скамер, Петух
        buttons.append([Button.inline("🚫 Вынести из базы", f"remove_from_db_{user_id}".encode())])

    warnings_count = db.get_warnings_count(user_id)

    emojis = ["🧛‍♂️", "👩‍💻", "🎮", "🔥", "⛄", "☃", "🌟", "🐻", "🐳", "🐵", "🦢", "💸", "🌸", "💥", "🌈", "🐹", "🦉"]

    message_text = ""

    random_emoji = random.choice(emojis) if country == "❓" else ""

    country_display = f"[Не указана](https://telegra.ph/Kak-ustanovit-stranu-v-bote-05-29)" if country == "❓" else country

    granted_by_id = db.get_granted_by(user.id) if hasattr(user, 'id') else None
    logging.info(f"Получен ID гаранта: {granted_by_id}")

    granted_by_username = "Неизвестный гарант"
    if granted_by_id is not None:
        try:
            logging.info(f"Попытка получить информацию о гаранте с ID {granted_by_id}")
            granted_by_user = await bot.get_entity(granted_by_id)
            granted_by_username = granted_by_user.username if hasattr(granted_by_user,
                                                                      'username') and granted_by_user.username else (
                granted_by_user.first_name if hasattr(granted_by_user, 'first_name') else f"ID: {granted_by_id}")
            logging.info(f"Имя гаранта: {granted_by_username}")
        except Exception as e:
            logging.error(f"Ошибка при получении информации о гаранте с ID {granted_by_id}: {e}")
    else:
        logging.warning("granted_by_id равен None, гарант не найден.")

    theme_url = ROLES.get(role_id, {}).get('preview_url', '')

    if not theme_url:
        theme_url = "https://i.ibb.co/SDkF5cSc/1000049441.jpg"  # Стандартная картинка

    theme_preview = f"{theme_url}\n\n"

    # ============ ФОРМИРОВАНИЕ ТЕКСТА ПО РОЛЯМ ============
    # ✅ ИСПРАВЛЕНО: Везде используется scammers_display_count вместо scammers_slept

    if role_id == 0:
        preview_url = custom_image_url or ROLES[role_id]['preview_url']
        message_text = (
            f"[👤][ {user_name} ](tg://user?id={user_id}) #id{user_id} [⠀]({preview_url})\n\n"
            f"[❌] Статус: не найден в базе. Риск скама: **44%**\n"
            f"[ℹ️] [Узнайте о гарантах](https://telegra.ph/Kto-takoj-GARANT-05-29)\n\n"
            f"[📍] Регион: {country_display}\n"
            f"[🚫] Разоблачено скаммеров: {scammers_display_count}\n\n"  # ✅ ИСПРАВЛЕНО
            f"[🔒] Используйте Гарантов Forget AntiScam для безопасных сделок.\n\n"
            f"[📅] Дата: {current_time} | 🔎Проверок: {checks_count}\n"
        )

    elif role_id == 12:
        preview_url = custom_image_url or ROLES[role_id]['preview_url']
        message_text = (
            f"[👤][ {user_name} ](tg://user?id={user_id}) #id{user_id} [⠀]({preview_url})\n\n"
            f"[❌] Статус: Проверен(а) гарантом | [ {granted_by_username} ](tg://user?id={granted_by_id}) ✅\n"
            f"[ℹ️] [Узнайте о гарантам](https://telegra.ph/Kto-takoj-GARANT-05-29)\n\n"
            f"[📍] Регион: {country_display}\n"
            f"[🚫] Разоблачено скаммеров: {scammers_display_count}\n\n"  # ✅ ИСПРАВЛЕНО
            f"[🔒] Используйте Гарантов Forget AntiScam для безопасных сделок.\n\n"
            f"[📅] Дата: {current_time} | 🔎Проверок: {checks_count}\n"
        )

    elif role_id == 1:
        preview_url = custom_image_url or ROLES[role_id]['preview_url']
        message_text = (
            f"[👤][ {user_name} ](tg://user?id={user_id}) #id{user_id} [⠀]({preview_url})\n\n"
            f"[✅] Статус: Гарант\n"
            f"[ℹ️] [Узнайте о гарантах](https://telegra.ph/Kto-takoj-GARANT-05-29)\n\n"
            f"[📍] Регион: {country_display}\n"
            f"[🚫] Разоблачено скаммеров: {scammers_display_count}\n\n"  # ✅ ИСПРАВЛЕНО
            f"[🔒] Данный пользователь является проверенным гарантом Forget AntiScam\n\n"
            f"[📅] Дата: {current_time} | 🔎Проверок: {checks_count}\n"
        )

    elif role_id == 10:
        preview_url = custom_image_url or ROLES[role_id]['preview_url']
        message_text = (
            f"[👤][ {user_name} ](tg://user?id={user_id}) #id{user_id} [⠀]({preview_url})\n\n"
            f"[💢] Статус: Владелец\n"
            f"[💖] [Персонал Forget AntiScam](https://t.me/Forget_base)\n\n"
            f"[📍] Регион: {country_display}\n"
            f"[🚫] Разоблачено скаммеров: {scammers_display_count}\n\n"  # ✅ ИСПРАВЛЕНО
            f"[🔒] Данный пользователь является Cоздателем базы Forget AntiScam\n\n"
            f"[📅] Дата: {current_time} | 🔎Проверок: {checks_count}\n"
        )

    elif role_id == 9:
        preview_url = custom_image_url or ROLES[role_id]['preview_url']
        message_text = (
            f"[👤][ {user_name} ](tg://user?id={user_id}) #id{user_id} [⠀]({preview_url})\n\n"
            f"[🧿] Статус: Президент\n"
            f"[💖] [Персонал Forget AntiScam](https://t.me/Forget_base)\n\n"
            f"[📍] Регион: {country_display}\n"
            f"[🚫] Разоблачено скаммеров: {scammers_display_count}\n\n"  # ✅ ИСПРАВЛЕНО
            f"[⚠] Выговоры: {warnings_count} "
            f"[🔒] Данный пользователь является надёжным президентом базы Forget AntiScam\n\n"
            f"[📅] Дата: {current_time} | 🔎Проверок: {checks_count}\n"
        )

    elif role_id == 4:  # Петух
        preview_url = custom_image_url or ROLES[role_id]['preview_url']
        message_text = (
            f"[👤][ {user_name} ](tg://user?id={user_id}) #id{user_id} [⠀]({preview_url})\n\n"
            f"[🐓] Статус: Петух\n\n"
            f"[📍] Регион: {country_display}\n"
            f"[🚫] Разоблачено скаммеров: {scammers_display_count}\n\n"  # ✅ ИСПРАВЛЕНО
            f"📚 Описание: {description}\n"
            f"{scammer_details}"
            f"[❌] Данный пользователь является подозрительной личностью! \n\n"
            f"[📅] Дата: {current_time} | 🔎Проверок: {checks_count}\n"
        )

    elif role_id == 3:  # Скамер
        preview_url = custom_image_url or ROLES[role_id]['preview_url']
        message_text = (
            f"[👤][ {user_name} ](tg://user?id={user_id}) #id{user_id} [⠀]({preview_url})\n\n"
            f"[🛑] Статус: Скаммер\n\n"
            f"[📍] Регион: {country_display}\n"
            f"[🚫] Разоблачено скаммеров: {scammers_display_count}\n\n"  # ✅ ИСПРАВЛЕНО
            f"📚 Описание: {description}\n"
            f"{scammer_details}"
            f"[❌] Данный пользователь Является скаммером! Не идите первыми!\n\n"
            f"[📅] Дата: {current_time} | 🔎Проверок: {checks_count}\n"
        )

    elif role_id == 7:
        preview_url = custom_image_url or ROLES[role_id]['preview_url']
        message_text = (
            f"[👤][ {user_name} ](tg://user?id={user_id}) #id{user_id} [⠀]({preview_url})\n\n"
            f"[🔍] Статус: Админ\n"
            f"[💖] [Персонал Forget AntiScam](https://t.me/Forget_base)\n\n"
            f"[📍] Регион: {country_display}\n"
            f"[🚫] Разоблачено скаммеров: {scammers_display_count}\n\n"  # ✅ ИСПРАВЛЕНО
            f"[⚠] Выговоры: {warnings_count} "
            f"[🔒] Данный пользователь является Администратором Базы Forget AntiScam\n\n"
            f"[📅] Дата: {current_time} | 🔎Проверок: {checks_count}\n"
        )


    elif role_id == 2:  # Возможно скамер
        preview_url = custom_image_url or ROLES[role_id]['preview_url']
        message_text = (
            f"[👤][ {user_name} ](tg://user?id={user_id}) #id{user_id} [⠀]({preview_url})\n\n"
            f"[🛑] Статус: Возможно скаммер\n\n"
            f"[📍] Регион: {country_display}\n"
            f"[🚫] Разоблачено скаммеров: {scammers_display_count}\n\n"  # ✅ ИСПРАВЛЕНО
            f"📚 Описание: {description}\n"
            f"{scammer_details}"
            f"[❌] Данный пользователь Является Потонциальным скаммером, будьте осторожны!\n\n"
            f"[📅] Дата: {current_time} | 🔎Проверок: {checks_count}\n"
        )

    elif role_id == 6:
        preview_url = custom_image_url or ROLES[role_id]['preview_url']
        message_text = (
            f"[👤][ {user_name} ](tg://user?id={user_id}) #id{user_id} [⠀]({preview_url})\n\n"
            f"[👨‍🎓] Статус: Стажер\n"
            f"[💖] [Персонал Forget AntiScam](https://t.me/Forget_base)\n\n"
            f"[📍] Регион: {country_display}\n"
            f"[🚫] Разоблачено скаммеров: {scammers_display_count}\n\n"  # ✅ ИСПРАВЛЕНО
            f"[⚠] Выговоры: {warnings_count}\n"
            f"[🔒] Данный пользователь является Стажёром Базы Forget AntiScam\n\n"
            f"[📅] Дата: {current_time} | 🔎Проверок: {checks_count}\n"
        )

    elif role_id == 8:
        preview_url = custom_image_url or ROLES[role_id]['preview_url']
        message_text = (
            f"[👤][ {user_name} ](tg://user?id={user_id}) #id{user_id} [⠀]({preview_url})\n\n"
            f"[‍🎩] Статус: Директор\n"
            f"[💖] [Персонал Forget AntiScam](https://t.me/Forget_base)\n\n"
            f"[📍] Регион: {country_display}\n"
            f"[🚫] Разоблачено скаммеров: {scammers_display_count}\n\n"  # ✅ ИСПРАВЛЕНО
            f"[⚠] Выговоры: {warnings_count}\n"
            f"[🔒] Данный пользователь является Директором Базы Forget AntiScam\n\n"
            f"[📅] Дата: {current_time} | 🔎Проверок: {checks_count}\n"
        )

    elif role_id == 11:
        preview_url = custom_image_url or ROLES[role_id]['preview_url']
        message_text = (
            f"[👤][ {user_name} ](tg://user?id={user_id}) #id{user_id} [⠀]({preview_url})\n\n"
            f"[👨‍💻] Статус: Кодер\n"
            f"[💖] [Персонал Forget AntiScam](https://t.me/Forget_base)\n\n"
            f"[📍] Регион: {country_display}\n"
            f"[🚫] Разоблачено скаммеров: {scammers_display_count}\n\n"  # ✅ ИСПРАВЛЕНО
            f"[⚠] Выговоры: {warnings_count}\n"
            f"[🔒] Данный пользователь является Техническим Специалистом Базы Forget AntiScam\n\n"
            f"[📅] Дата: {current_time} | 🔎Проверок: {checks_count}\n"
        )
    else:
        logging.warning(f"Неизвестная роль: {role_id}")
        message_text = "❌ Неизвестная роль"
        return message_text, buttons

    if premium_active and channel != "❓":
        message_text += f"\n[📣] Канал: {channel}\n"

    return message_text, buttons


@bot.on(events.NewMessage(pattern='/profile'))
async def handler(event):
    await my_profile(event)

async def send_response(event, response_text, buttons=None):
    if buttons:
        await event.respond(response_text, buttons=buttons, parse_mode='md')
    else:
        await event.respond(response_text, parse_mode='md')


@bot.on(events.CallbackQuery(data=re.compile(r"^profile_(\d+)$")))
async def profile_callback_handler(event):
    target_id = int(event.pattern_match.group(1))
    try:
        target = await event.client.get_entity(target_id)
        username = getattr(target, 'username', None) or getattr(target, 'first_name', None) or str(target_id)
        user_data = db.ensure_user(target_id, username, 0)
        if not user_data:
            await event.answer("❌ Не удалось загрузить профиль.", alert=True)
            return
        message_text, buttons = await get_user_profile_response(event, target, user_data)
        await event.edit(message_text[:4096], buttons=buttons, parse_mode='md', link_preview=True)
        await event.answer()
    except Exception as e:
        logging.error(f"Ошибка открытия профиля {target_id}: {e}")
        await event.answer("❌ Не удалось открыть профиль.", alert=True)


last_check_time = {}

# Глобальная переменная для хранения кэша
joined_users_cache = set()


# Функция для сброса кэша
def reset_cache():
    global joined_users_cache
    joined_users_cache.clear()  # Очищаем кэш
    logging.info('Кэш успешно сброшен.')


@bot.on(events.NewMessage(pattern=r'(?i)^(чек|чек ми|чек я|чек себя|check|/check).*'))
@Database.cooldown(3)
async def check_user(event):
    global checks_count
    user_id = event.sender_id
    user = await event.get_sender()

    # Проверка на спам
    current_time = time.time()

    # Проверяем, не выполняется ли уже проверка
    if user_id in active_checks and active_checks[user_id]:
        await event.respond("⏳ Ваш предыдущий запрос еще обрабатывается...")
        return

    # Проверяем время последнего вызова
    if user_id in last_check_time:
        elapsed_time = current_time - last_check_time[user_id]
        if elapsed_time < check_cooldown:
            remaining_time = check_cooldown - elapsed_time
            await event.respond(f"⏳ Подождите {remaining_time:.1f} секунд перед повторной проверкой!")
            return

    # Устанавливаем блокировку
    active_checks[user_id] = True
    last_check_time[user_id] = current_time

    loading_msg = None
    try:
        loading_msg = await event.respond("🔍 Ищу данные о пользователе в базе...")
        await asyncio.sleep(0.5)

        user_to_check = None
        user_data = None

        # Определяем пользователя для проверки
        if event.reply_to_msg_id:
            replied = await event.get_reply_message()
            try:
                user_to_check = await event.client.get_entity(replied.sender_id)
                user_data = db.get_user(user_to_check.id) if db else None
            except Exception as e:
                await loading_msg.delete()
                active_checks[user_id] = False
                return await send_response(event, "❌ | Не удалось получить информацию о пользователе.")
        else:
            text_lower = event.raw_text.lower()
            if any(keyword in text_lower for keyword in ["чек ми", "чек я", "чек себя", "check me"]):
                user_to_check = user
                user_data = db.get_user(user.id) if db else None
            else:
                # Парсим аргументы
                args = event.raw_text.split()
                if len(args) > 1:
                    target = args[1].strip()

                    try:
                        # Пытаемся получить пользователя из Telegram
                        if target.isdigit():
                            # Для ID сначала пытаемся получить через get_entity
                            try:
                                user_to_check = await event.client.get_entity(int(target))
                            except:
                                # Если не получается, проверяем в базе данных
                                user_id_to_check = int(target)
                                user_data = db.get_user(user_id_to_check)
                                if user_data:
                                    # Создаем минимальный объект с данными из базы
                                    user_to_check = type('UserObject', (), {
                                        'id': user_id_to_check,
                                        'first_name': f"ID: {user_id_to_check}",
                                        'username': user_data[1] if len(user_data) > 1 and user_data[1] else None
                                    })()
                                else:
                                    # ДОБАВЛЯЕМ ПОЛЬЗОВАТЕЛЯ С РОЛЬЮ 0, ЕСЛИ ЕГО НЕТ В БАЗЕ
                                    db.add_user(user_id_to_check, str(user_id_to_check), 0)
                                    user_data = db.get_user(user_id_to_check)
                                    user_to_check = type('UserObject', (), {
                                        'id': user_id_to_check,
                                        'first_name': f"ID: {user_id_to_check}",
                                        'username': None
                                    })()
                        else:
                            # Для юзернейма
                            if target.startswith('@'):
                                target = target[1:]
                            user_to_check = await event.client.get_entity(target)

                        # Получаем данные из базы
                        user_data = db.get_user(user_to_check.id) if db and user_to_check else None

                    except Exception as e:
                        logging.error(f"Ошибка при получении пользователя: {e}")
                        await loading_msg.delete()
                        active_checks[user_id] = False
                        return await send_response(event, "❌ | Не удалось найти пользователя.")
                else:
                    # Если нет аргументов, проверяем себя
                    user_to_check = user
                    user_data = db.get_user(user.id) if db else None

        if user_to_check is None:
            await loading_msg.delete()
            active_checks[user_id] = False
            return await send_response(event, "❌ | Не удалось определить пользователя.")

        # Получаем данные, если они еще не загружены
        if not user_data and db:
            # ДОБАВЛЯЕМ ПОЛЬЗОВАТЕЛЯ С РОЛЬЮ 0, ЕСЛИ ЕГО НЕТ В БАЗЕ
            username = getattr(user_to_check, 'username', None) or getattr(user_to_check, 'first_name', f"ID: {user_to_check.id}")
            db.add_user(user_to_check.id, username, 0)
            user_data = db.get_user(user_to_check.id)

        # Увеличиваем счетчики проверок
        if db and user_to_check:
            db.increment_check_count(user_to_check.id)
        checks_count += 1

        # Формируем ответ
        response = await get_user_profile_response(event, user_to_check, user_data)

        if isinstance(response, tuple):
            message_text, buttons = response
        else:
            message_text = response
            buttons = []

        # Отправка результата
        try:
            await send_response(event, message_text[:4096] if len(message_text) > 4096 else message_text, buttons)
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения: {e}")

        # Удаляем сообщение о загрузке
        if loading_msg:
            await loading_msg.delete()

    except Exception as e:
        logging.error(f"Ошибка в check_user: {e}")
        try:
            if loading_msg:
                await loading_msg.delete()
        except:
            pass
    finally:
        # Снимаем блокировку
        if user_id in active_checks:
            active_checks[user_id] = False


@bot.on(events.NewMessage(pattern=r'(?i)^/on$'))
async def enable_chat(event):
    """Команда для разрешения участникам чата писать сообщения."""
    user_id = event.sender_id

    # Проверяем, является ли пользователь с ролью 10
    if db.get_user_role(user_id) != 10:
        await event.respond("❌ У вас нет прав для выполнения этой команды.")
        return

    # Разрешаем всем участникам писать сообщения
    await bot.edit_permissions(event.chat_id, send_messages=True)

    await event.respond(
        "🔓 Предложка открыта, вы снова можете писать сообщения в чат![⠀](https://i.ibb.co/JFq2r3Dg/image.jpg)")


@bot.on(events.NewMessage(pattern=r'(?i)^/off$'))
async def disable_chat(event):
    """Команда для запрета участникам чата писать сообщения."""
    user_id = event.sender_id

    # Проверяем, является ли пользователь с ролью 10
    if db.get_user_role(user_id) != 10:
        await event.respond("❌ У вас нет прав для выполнения этой команды.")
        return

    # Запрещаем всем участникам писать сообщения
    await bot.edit_permissions(event.chat_id, send_messages=False)

    await event.respond(
        "🔒 Предложка закрыта на время, скоро мы вернёмся в строй, следите за новостями![⠀](https://i.ibb.co/JFq2r3Dg/image.jpg)")


@bot.on(events.CallbackQuery(pattern=r'remove_from_db_(\d+)'))
async def remove_from_db_handler(event):
    user_id = int(event.pattern_match.group(1))

    # Проверяем права пользователя
    sender_role = db.get_user_role(event.sender_id)
    allowed_roles = [6, 7, 8, 9, 10, 11, 13]  # Стажер, Админ, Директор, Президент, Создатель, Кодер, Заместитель

    if sender_role not in allowed_roles:
        await event.answer("❌ У вас нет прав для выполнения этого действия!", alert=True)
        return

    try:
        # Получаем информацию о пользователе, которого нужно вынести из базы
        target_user = await bot.get_entity(user_id)
        target_role = db.get_user_role(user_id)

        # Проверяем, что пользователь действительно имеет одну из ролей скамера
        if target_role not in [2, 3, 4]:
            await event.answer("❌ Этот пользователь не является скамером!", alert=True)
            return

        # Снимаем статус скамера - устанавливаем роль "Нет в базе" (0)
        db.update_role(user_id, 0)

        # Удаляем из таблицы scammers
        db.cursor.execute('DELETE FROM scammers WHERE user_id = ?', (user_id,))
        db.conn.commit()

        # Получаем информацию о пользователе, который выполнил действие
        admin_user = await bot.get_entity(event.sender_id)

        await event.answer("✅ Пользователь успешно вынесен из базы!", alert=True)

        # Редактируем сообщение, убирая кнопку
        await event.edit(
            f"👤 Пользователь [{target_user.first_name}](tg://user?id={user_id}) был вынесен из базы\n"
            f"👮 Вынес: [{admin_user.first_name}](tg://user?id={event.sender_id})\n"
            f"📅 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            buttons=[
                [
                    Button.url("🎧 Профиль",
                               f"https://t.me/{target_user.username}" if target_user.username else f"tg://user?id={user_id}")
                ]
            ],
            parse_mode='md'
        )

        logging.info(f"Пользователь {user_id} вынесен из базы пользователем {event.sender_id}")

    except Exception as e:
        logging.error(f"Ошибка при выносе пользователя из базы: {e}")
        await event.answer("❌ Произошла ошибка при выносе из базы!", alert=True)


@bot.on(events.NewMessage(pattern=r'(?i)^/cur|/курировать|/кур'))
async def cur_command(event):
    try:
        sender = await event.get_sender()
        user_id = sender.id

        user_role = db.get_user_role(user_id)
        allowed_roles = [8, 9, 13, 10]  # Директор, Президент, Заместитель, Владелец

        if user_role not in allowed_roles:
            await event.respond("❌ У вас нет прав для назначения кураторов.")
            return

        if event.is_reply:
            replied = await event.get_reply_message()
            target_id = replied.sender_id
            try:
                target = await event.client.get_entity(target_id)
            except ValueError:
                await event.reply("❌ Не могу найти пользователя.")
                return
        else:
            args = event.raw_text.split()
            if len(args) < 2:
                await event.reply("❌ Используйте: /cur @username или ответьте на сообщение.")
                return

            username = args[1].lstrip('@')
            try:
                target = await event.client.get_entity(username)
            except Exception as e:
                await event.reply("❌ Не могу найти указанного пользователя.")
                return

        # Проверяем, что целевой пользователь - стажёр
        target_role = db.get_user_role(target.id)
        if target_role != 6:
            await event.reply("❌ Указанный пользователь не является стажёром.")
            return

        # Назначаем куратора
        db.cursor.execute('UPDATE users SET curator_id = ? WHERE user_id = ?', (user_id, target.id))
        db.conn.commit()

        # Получаем имена для отображения
        try:
            target_user = await event.client.get_entity(target.id)
            target_name = target_user.first_name
        except:
            target_name = f"ID:{target.id}"

        sender_name = sender.first_name

        await event.reply(
            f"✅ Стажёру {target_name} назначен куратор: {sender_name}.\n\n"
            f"Теперь стажёр может использовать команду /скам для отправки заявок на скаммеров, "
            f"которые будут приходить вам на проверку."
        )

    except Exception as e:
        print(f"Ошибка в команде /cur: {e}")
        await event.reply("❌ Произошла ошибка при выполнении команды.")


@bot.on(events.NewMessage(pattern=r'(?i)^/mycur|/мойкуратор'))
async def my_curator_command(event):
    user_id = event.sender_id

    curator_id = db.get_user_curator(user_id)

    if not curator_id:
        await event.respond("❌ У вас нет назначенного куратора.")
        return

    try:
        curator = await event.client.get_entity(curator_id)
        curator_name = curator.first_name

        await event.respond(
            f"👨‍🏫 **Ваш куратор:** {curator_name}\n"
            f"🆔 ID: {curator_id}\n\n"
            f"Для отправки заявок на скаммеров используйте команду:\n"
            f"`/скам @username причина`\n\n"
            f"Заявки будут приходить вашему куратору на проверку."
        )
    except:
        await event.respond(f"👨‍🏫 **Ваш куратор:** ID {curator_id}")


# Функция для периодической очистки старых данных о нажатиях
async def cleanup_old_button_data():
    """Очищает старые данные о нажатиях кнопок"""
    while True:
        await asyncio.sleep(3600)  # Каждый час
        current_time = time.time()
        to_remove = []

        for user_id, data in user_button_presses.items():
            if current_time - data['window_start'] > BUTTON_PRESS_WINDOW * 2:  # Двойное окно времени
                to_remove.append(user_id)

        for user_id in to_remove:
            del user_button_presses[user_id]

        logging.info(f"Очищены данные о нажатиях для {len(to_remove)} пользователей")


@bot.on(events.NewMessage(pattern=r'(?i)^(выговор|/выговор)'))
async def warning_handler(event):
    if event.is_reply:
        replied = await event.get_reply_message()
        target_user = await event.client.get_entity(replied.sender_id)
    else:
        await event.reply("❌ Пожалуйста, используйте команду в ответ на сообщение пользователя.")
        return

    # Проверяем права
    user_role = db.get_user_role(event.sender_id)
    logging.info(f"Пользователь {event.sender_id} с ролью {user_role} пытается выдать выговор.")

    # Проверяем, чтобы создающий пользователь (роль 10) не получал выговоры
    target_user_role = db.get_user_role(target_user.id)
    if target_user_role == 10:
        await event.reply("Ты шо ахуел?, нельзя владельцу выговоры выдавать!.")
        return

    # Проверяем, что у пользователя есть права на выдачу выговоров
    if user_role not in [13, 8, 9, 10]:  # Только админ, директор, президент
        await event.reply("❌ У вас нет прав для выдачи выговора.")
        return

    # Получаем количество выговоров
    result = db.cursor.execute('SELECT warnings FROM users WHERE user_id = ?', (target_user.id,)).fetchone()

    if result is None:
        # Если пользователь не найден, добавляем его в базу с 0 выговорами
        db.add_user(target_user.id, target_user.username, 0)  # Добавляем пользователя с нулевым количеством выговоров
        warnings_count = 0
    else:
        warnings_count = result[0]

    # Увеличиваем количество выговоров
    db.update_warnings(target_user.id)

    # Получаем обновленное количество выговоров
    new_warnings_count = \
        db.cursor.execute('SELECT warnings FROM users WHERE user_id = ?', (target_user.id,)).fetchone()[0]

    if new_warnings_count >= 3:
        # Снимаем статус пользователя
        db.update_role(target_user.id, 0)

        # Сбрасываем количество выговоров до 0
        db.reset_warnings(target_user.id)

        await event.reply(
            f"✅ Пользователь [{target_user.first_name}](tg://user/{target_user.id}) получил 3 выговора и теперь имеет статус 'Нет в базе'.")
    else:
        await event.reply(
            f"✅ Выговор выдан пользователю [{target_user.first_name}](tg://user/{target_user.id})")


@bot.on(events.NewMessage(pattern=r'(?i)^(/-выговор|снять выговор)'))
async def remove_warnings_handler(event):
    if event.is_reply:
        replied = await event.get_reply_message()
        target_user = await event.client.get_entity(replied.sender_id)
    else:
        await event.reply("❌ Пожалуйста, используйте команду в ответ на сообщение пользователя.")
        return

    # Проверяем права
    user_role = db.get_user_role(event.sender_id)
    logging.info(f"Пользователь {event.sender_id} с ролью {user_role} пытается снять выговоры.")

    # Проверяем, что у пользователя есть права на снятие выговоров
    if user_role not in [13, 8, 9, 10]:  # Только админ, директор, президент
        await event.reply("❌ У вас нет прав для снятия выговоров.")
        return

    # Получаем текущее количество выговоров
    result = db.cursor.execute('SELECT warnings FROM users WHERE user_id = ?', (target_user.id,)).fetchone()
    if result is None:
        await event.reply("❌ Пользователь не найден в базе.")
        return

    warnings_count = result[0]

    if warnings_count <= 0:
        await event.reply(f"❌ У пользователя [{target_user.first_name}](tg://user/{target_user.id}) нет выговоров.")
        return

    # Уменьшаем количество выговоров на 1
    db.cursor.execute('UPDATE users SET warnings = warnings - 1 WHERE user_id = ?', (target_user.id,))
    db.conn.commit()

    # Получаем обновленное количество выговоров
    new_warnings_count = \
        db.cursor.execute('SELECT warnings FROM users WHERE user_id = ?', (target_user.id,)).fetchone()[0]

    await event.reply(
        f"✅ выговор снят у пользователя [{target_user.first_name}](tg://user/{target_user.id})."
    )


# Глобальная переменная для хранения времени последнего использования команды
last_sell_command_time = {}


@bot.on(events.NewMessage(pattern=r'продать (.+)'))
async def sell_command(event):
    user_id = event.sender_id
    item_to_sell = event.pattern_match.group(1)  # Получаем то, что пользователь хочет продать

    # Проверка колдауна
    current_time = time.time()
    if user_id in last_sell_command_time:
        if current_time - last_sell_command_time[user_id] < 10:  # 10 секунд колдаун
            await event.respond("Потерпи брадок, 10 секунд не так уж и много.")
            return

    # Устанавливаем время последнего использования команды
    last_sell_command_time[user_id] = current_time

    # Шанс на успех (15%)
    if random.randint(1, 100) <= 15:
        # Успех
        success_texts = [
            f"ЁЁЁЁЁЁУУУУУУУУУ😎😎😎 Да ты своего {item_to_sell} продал цыганам за 5 копеек, хочешь вернуть да?, того пиздуй искать в бд неуч!",
            f"Нихуя себе какой важный хуй бумажный🎴, ты продал своего {item_to_sell} на органы! Хочешь сохранить друга\n\n Тогда Ищи в бд! Неуч блять!",
            f"О!, а куда это твой {item_to_sell} делся? Кажись его цыгани спиздили! Смотреть надо за своим {item_to_sell}, а не хуи пинать!\n\n Вы на базаре всё-таки! Всего проёбано {random.randint(1, 10)}."
        ]
        await event.respond(random.choice(success_texts))
    else:
        # Проигрыш
        losses = random.randint(1, 10)  # Случайное количество проигрышей
        response_texts = [
            f"БЛЯЯЯЯЯЯЯЯЯЯЯ😭😭 Ты проебал своего {item_to_sell} в казик, кажись его логи схавали.\n\nВсего ты проебал {losses}. Поищи в логах!",
            f"АХХХПАХХАХАХАПХПАХАПХ ЕБАТЬ ТЫ ЛОХ🤣🤣, Ты где-то проебал {item_to_sell} ищи в бд!\n\nВсего проёбано {losses}.",
            f"Лелелелелеле😑, тебе чё занятся нехуй? своего {item_to_sell} на базаре продавать. пиздуй ищи в логах!\n\nВсего проёбано {losses}.",
            f"ААХХАХАХАХАХАХХА😂😂😂😂😂, Кажись твой {item_to_sell} обосрался и убежал😂 ищи в логах!\n\nВсего проёбано {losses}.",
            f"АХХАПХАХПХАПХАПХАПХ🤣🤣🤣🤣, Ты успешно продал своего {item_to_sell} цыганам! теперь нету смысла искать в логах!",
            f"Ох ебааать😨, а кто это там с зади тебя стоит?, хахаха! наебал!, ты как обычно проебал своего {item_to_sell}, пиздуй искать в бд!\n\nВсего проёбано {losses}.",
            f"Стапе!😱, а где твой {item_to_sell}😨, Кажись он потерялся на базаре!, скорее вызывай ментов пока его бабки костылями не отпиздили!\n\nВсего проёбано {losses}."
        ]

        # Выбираем случайное сообщение для проигрыша
        response_message = random.choice(response_texts)

        # Создаем кнопки
        buttons = [
            [Button.inline("🔍Искать ещё раз!", f"search_again_{user_id}"),
             Button.inline("🤑Гойда продадим что-то?", f"sell_something_{user_id}")]
        ]

        # Отправляем сообщение с кнопками
        message = await event.respond(response_message, buttons=buttons)


@bot.on(events.CallbackQuery(pattern=r'search_again_(\d+)'))
async def search_again_handler(event):
    user_id = int(event.pattern_match.group(1))
    await event.answer("Да мне лень работать чё-то🥱🥱", alert=False)  # Ответ пользователю в виде окошка


@bot.on(events.CallbackQuery(pattern=r'sell_something_(\d+)'))
async def sell_something_handler(event):
    user_id = int(event.pattern_match.group(1))
    await event.answer("Напиши продать (что-то твоё)", alert=False)  # Ответ пользователю в виде окошка


@bot.on(events.NewMessage(pattern='/профиль'))
async def profile_command(event):
    user = await event.get_sender()  # Получаем пользователя, который отправил команду
    user_id = user.id
    role = db.get_user_role(user_id)  # Получаем роль пользователя

    # Получаем данные пользователя из базы
    user_data = db.ensure_user(user_id, getattr(user, 'username', None) or getattr(user, 'first_name', None), 0)
    premium_active = db.is_premium_user(user_id)
    custom_photo = user_data[8] if (user_data and premium_active) else None
    preview_url = custom_photo if custom_photo else ROLES[role]['preview_url']
    checks_count = db.get_check_count(user_id)

    # Инициализация scammers_count
    scammers_count = 0
    scammers_info = ""

    # Для персонала показываем количество слитых скамеров
    if role in [6, 7, 8, 9, 10]:  # Проверяем, если это персонал
        scammers_count = db.get_user_reported_scammers_count(user_id)  # Получаем количество слитых скаммеров
        scammers_info = f"🔥 **Скаммеров слито:** `{scammers_count}`\n"
    else:
        scammers_info = "🔥 **Скаммеров слито:** `0`\n"  # Если не персонал, показываем 0

    # Формируем текст профиля
    profile_text = f"""
**👤 Профиль пользователя в базе: [{user.first_name}](tg://user?id={user_id})**

🔍 **Вас проверяли:** `{checks_count}` раз
{scammers_info}
**📝 Роль в базе:** {ROLES[role]['name']}

"""

    await event.respond(profile_text, parse_mode='md')


@bot.on(events.NewMessage(pattern=r'(?i)^\+спасибо'))
async def thank_command(event):
    logging.info("Команда +спасибо была вызвана.")
    user_id = event.sender_id

    # Проверка роли пользователя, который вызывает команду
    user_role = db.get_user_role(user_id)
    allowed_roles = [6, 7, 8, 9, 10, 11, 13]  # Стажер, Админ, Директор, Президент, Создатель, Кодер, Заместитель

    if user_role not in allowed_roles:
        await event.respond("❌ Только персонал базы может выдавать +спасибо!")
        return

    if event.reply_to_msg_id:
        reply_message = await event.get_reply_message()
        target_user_id = reply_message.sender_id

        # Получаем текущее РЕАЛЬНОЕ количество слитых скамеров
        current_real_count = db.get_user_reported_scammers_count(target_user_id)

        # Увеличиваем счетчик в таблице users (scammers_count)
        try:
            # Получаем текущее значение
            db.cursor.execute('SELECT scammers_count FROM users WHERE user_id = ?', (target_user_id,))
            result = db.cursor.fetchone()

            if result:
                current_count = result[0] if result[0] is not None else 0
                new_count = current_count + 1
            else:
                new_count = 1

            # Обновляем значение
            db.cursor.execute('UPDATE users SET scammers_count = ? WHERE user_id = ?', (new_count, target_user_id))
            db.conn.commit()

            logging.info(f"Счетчик scammers_count для {target_user_id} увеличен: {new_count}")
        except Exception as e:
            logging.error(f"Ошибка обновления scammers_count: {e}")
            new_count = current_real_count + 1

        try:
            sender = await event.get_sender()
            target_user = await bot.get_entity(target_user_id)

            # Формируем сообщение с ПРАВИЛЬНЫМИ данными
            response_text = (
                f"📛 **Пользователю выдано +спасибо!**\n\n"
                f"👤 **Получил:** [{target_user.first_name}](tg://user?id={target_user_id})\n"
                f"👮 **Выдал:** [{sender.first_name}](tg://user?id={user_id})\n"
                f"🔥 **Общий счетчик:** {new_count}\n"
                f"🎯 **Реально слито скамеров:** {current_real_count}\n\n"
                f"📈 Спасибо, что боретесь со скамом вместе с Forget AntiScam!"
            )

            await event.respond(response_text, parse_mode='md')

            # Уведомляем получателя
            try:
                await bot.send_message(
                    target_user_id,
                    f"🎉 **Вам выдано +спасибо!**\n\n"
                    f"👮 **Выдал:** {sender.first_name}\n"
                    f"🔥 **Ваш счетчик:** {new_count}\n"
                    f"🎯 **Реально слито скамеров:** {current_real_count}\n\n"
                    f"Спасибо за ваш вклад в борьбу со скамом!",
                    buttons=Button.inline("↩Скрыть", b"hide_message")
                )
            except:
                pass  # Пользователь мог заблокировать бота

        except Exception as e:
            logging.error(f"Ошибка получения данных пользователя: {e}")
            await event.respond(f"✅ +спасибо выдано пользователю с ID: {target_user_id}\n🔥 Новый счетчик: {new_count}")
    else:
        await event.respond("❌ Ответьте на сообщение пользователя, которому хотите выдать +спасибо.")


@bot.on(events.NewMessage())
async def message_handler(event):
    user_id = event.sender_id

    # Игнорируем сообщения от ботов
    if event.sender.bot:
        return

    # ПРОВЕРКА: только для групп/супергрупп
    if not event.is_group and not event.is_channel:
        return  # Игнорируем личные сообщения

    # Получаем текущее время
    current_time = datetime.now()

    # Добавляем временную метку сообщения
    user_message_count[user_id].append(current_time)

    # Удаляем временные метки старше 30 секунд
    user_message_count[user_id] = [timestamp for timestamp in user_message_count[user_id]
                                   if current_time - timestamp < timedelta(seconds=30)]

    # Проверяем количество сообщений
    if len(user_message_count[user_id]) > 8:
        try:
            # Выдаём мут на 10 минут (ТОЛЬКО В ГРУППАХ)
            await bot.edit_permissions(
                event.chat_id,
                user_id,
                until_date=current_time + timedelta(minutes=10),
                send_messages=False,
                send_media=False,
                send_stickers=False,
                send_gifs=False,
                send_games=False,
                send_inline=False
            )

            await event.respond(f"🔇 Пользователь {event.sender.first_name} был замучен за спам на 10 минут!")
            logging.info(f"Пользователь {user_id} замучен за спам.")

            # Очищаем записи сообщений после мута
            del user_message_count[user_id]

        except Exception as e:
            logging.error(f"Ошибка при выдаче мута: {e}")
            # Игнорируем ошибки, не прерываем работу бота

# Глобальные переменные
games = {}
joined_users_cache = set()
guesses = {}
muted_users = {}  # {user_id: expiry_time}
last_scam_times = {}
START_USERS = set()  # Пользователи, использовавшие /start
BOT_CHATS = set()  # Чаты, где есть бот
LAST_CHECKED = {}  # Последний проверенный пользователь
TEMP_STORAGE = {}  # Временное хранилище данных
COUNTRIES = [
    "США 🇺🇸", "Канада 🇨🇦", "Мексика 🇲🇽", "Бразилия 🇧🇷",
    "Аргентина 🇦🇷", "Великобритания 🇬🇧", "Франция 🇫🇷",
    "Германия 🇩🇪", "Италия 🇮🇹", "Испания 🇪🇸", "Китай 🇨🇳",
    "Япония 🇯🇵", "Австралия 🇦🇺", "Индия 🇮🇳", "Россия 🇷🇺",
    "Южноафриканская Республика 🇿🇦", "Египет 🇪🇬", "ОАЭ 🇦🇪",
    "Турция 🇹🇷", "Греция 🇬🇷", "Швеция 🇸🇪", "Норвегия 🇳🇴",
    "Финляндия 🇫🇮", "Дания 🇩🇰", "Польша 🇵🇱", "Чехия 🇨🇿",
    "Австрия 🇦🇹", "Швейцария 🇨🇭", "Нидерланды 🇳🇱", "Бельгия 🇧🇪",
    "Ирландия 🇮🇪", "Португалия 🇵🇹", "Румыния 🇷🇴", "Словакия 🇸🇰",
    "Словения 🇸🇮", "Хорватия 🇭🇷", "Латвия 🇱🇻", "Литва 🇱🇹",
    "Эстония 🇪🇪", "Мальта 🇲🇹", "Кипр 🇨🇾", "Исландия 🇮🇸",
    "Албания 🇦🇱", "Сербия 🇷🇸", "Босния и Герцеговина 🇧🇦",
    "Черногория 🇲🇪", "Македония 🇲🇰", "Косово 🇽🇰", "Беларусь 🇧🇾",
    "Украина 🇺🇦", "Грузия 🇬🇪", "Армения 🇦🇲", "Азербайджан 🇦🇿",
    "Казахстан 🇰🇿", "Узбекистан 🇺🇿", "Таджикистан 🇹🇯",
    "Туркменистан 🇹🇲", "Кыргызстан 🇰🇬", "Монголия 🇲🇳",
    "Иран 🇮🇷", "Ирак 🇮🇶", "Сирия 🇸🇾", "Ливан 🇱🇧",
    "Иордания 🇯🇴", "Катар 🇶🇦", "Бахрейн 🇧🇭", "Кувейт 🇰🇼",
    "Саудовская Аравия 🇸🇦", "Йемен 🇾🇪", "Вьетнам 🇻🇳",
    "Таиланд 🇹🇭", "Малайзия 🇲🇾", "Индонезия 🇮🇩", "Филиппины 🇵🇭",
    "Сингапур 🇸🇬", "Непал 🇳🇵", "Шри-Ланка 🇱🇰", "Бангладеш 🇧🇩",
    "Пакистан 🇵🇰", "Мьянма 🇲🇲", "Лаос 🇱🇦", "Камбоджа 🇰🇭",
    "Тайвань 🇹🇼", "Гонконг 🇭🇰", "Южная Корея 🇰🇷", "Северная Корея 🇰🇵",
    "Австралия 🇦🇺", "Новая Зеландия 🇳🇿", "Папуа — Новая Гвинея 🇵🇬",
    "Фиджи 🇫🇯", "Самоа 🇼🇸", "Тонга 🇹🇴", "Вануату 🇻🇺",
    "Микронезия 🇫🇲", "Науру 🇳🇷", "Тувалу 🇹🇻", "Соломоновы Острова 🇸🇧",
    "Кирибати 🇰🇷", "Сент-Люсия 🇱🇨", "Сент-Винсент и Гренадины 🇻🇨",
    "Барбадос 🇧🇧", "Ямайка 🇯🇲", "Тринидад и Тобаго 🇹🇹",
    "Багамы 🇧🇸", "Гренада 🇬🇩", "Антигуа и Барбуда 🇦🇬",
    "Сент-Китс и Невис 🇰🇳"
]

# API для загрузки изображений
IMG_API_KEY = "cb21b904cc405cdfc05731896bc29c64"


@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    sender = await event.get_sender()
    db.ensure_user(event.sender_id, getattr(sender, 'username', None) or getattr(sender, 'first_name', None) or str(event.sender_id), 0)
    START_USERS.add(event.sender_id)

    # Основное сообщение с reply-кнопками
    await event.respond(
        "👋 Добро пожаловать в Forget AntiScam!\n\n"
        "Мы — официальный бот антискам базы Forget AntiScam, созданный для обеспечения вашей безопасности в мире обменов и сделок.\n\n"
        "🔒 Ваше доверие — наша приоритетная задача!\n\n"
        "Спасибо, что выбрали Forget AntiScam! Вместе мы сделаем все безопаснее!",
        buttons=main_buttons
    )

    # Дополнительные inline-кнопки
    inline_buttons = [
        [Button.url("🌍 Предложка", "https://t.me/Forget_base")],
        [Button.url("🔐 Кодер Бота", "https://t.me/HellssMor")],
        [Button.url("🔍 Трейдинг Чат", "https://t.me/Forget_base")]
    ]

    await event.respond(
        "📌 **Дополнительные функции:**",
        buttons=inline_buttons,
        parse_mode='md'
    )

    # Сообщение с кнопкой добавления в чат
    await event.respond(
        "Спасибо за выбор Forget AntiScam🤗\n\nВы можете поддержать нас, добавив нашего бота в чат",
        buttons=[
            [Button.url("💌 добавить в чат",
                        "https://t.me/Forget_base")]
        ]
    )


@bot.on(events.CallbackQuery(pattern='about_project'))
async def about_project(event):
    about_text = (
        "спасибо за выбор Forget AntiScam🤗\n"
       f"вы можете поддержать нас,добавив нашего бота в чат\n"
   )


    buttons = [
        [Button.inline("🤔 Как стать гарантом?", "how_to_become_guarantor")],
        [Button.inline("🤑 У кого и как купить траст?", "how_to_buy_trust")],
        [Button.inline("😈 Как слить вам скаммера?", "how_to_report_scammer")]
    ]

    await event.respond(
        about_text,
        buttons=buttons,
        parse_mode='md'
    )


# Обработчики для других кнопок
@bot.on(events.CallbackQuery(pattern='how_to_become_guarantor'))
async def how_to_become_guarantor(event):
    response_text = (
        "Чтобы стать гарантом, нужно пройти набор в нашу базу. "
        "Владельцы регулярно проводят наборы на многие роли, в том числе гарантов. "
        "Если ты хочешь стать гарантом, просто пройди набор в нашу базу🤗[⠀](https://i.ibb.co/ZR8qJ80N/1.jpg)"
    )
    await event.respond(response_text)


@bot.on(events.CallbackQuery(pattern='how_to_buy_trust'))
async def how_to_buy_trust(event):
    response_text = (
        "Хочешь купить траст? Да ты богач🤗. Чтобы купить траст, тебе нужно написать нашим гарантам "
        "Гарантов ты можешь найти в чате или же нажав на кнопку 'Гаранты' в главном меню🤑[⠀](https://i.ibb.co/rGBBGyng/photo-2025-04-17-17-44-20.jpg)"
    )
    await event.respond(response_text)


@bot.on(events.CallbackQuery(pattern='how_to_report_scammer'))
async def how_to_report_scammer(event):
    response_text = (
        "Ох, тебя тоже задрали скаммеры? Меня тоже😡 Если ты действительно хочешь слить скаммера, "
        "то тебе нужно зайти в нашу базу и написать в чат доказательства скама и юзернейм-айди. "
        "Наши волонтёры занесут этого скаммера😈[⠀](https://i.ibb.co/bj4g7h3y/photo-2025-04-17-17-44-19-3.jpg)"
    )
    await event.respond(response_text)


# Обработчик кнопки "Поддержать"
@bot.on(events.CallbackQuery(pattern='support_handler'))
async def support_handler(event):
    support_text = (
        "Если вы хотите помочь кодеру для продвижения ботов, "
        "то вы можете поддержать кодера этими вариантами:\n\n"
        "Если вы хотите поддержать кодера в ттд ник: **pisun11000**[⠀](https://i.ibb.co/0x7KTr0/image.jpg)"
    )

    buttons = [
        [Button.url("💌 Крипто ботом", "https://t.me/send?start=IVdGVHgwlEsa")],
        [Button.url("💞 Наш кодер", "https://t.me/Steach_Garant")]
    ]

    await event.respond(
        support_text,
        buttons=buttons,
        parse_mode='md'
    )


# ==================== PREMIUM ====================
@bot.on(events.NewMessage(pattern=r'(?i)^/premium(?:\s+.*)?$'))
async def premium_command(event):
    """Выдача Premium владельцем/президентом. Примеры: /premium 5м, /premium 1ч, /premium 1д, /premium 1н, /premium навсегда."""
    if not can_grant_premium(event.sender_id):
        await event.respond("⛔️ Premium могут выдавать только Президент и Владелец.")
        return

    args = event.raw_text.split()
    target = None
    duration_token = None

    if event.is_reply:
        replied = await event.get_reply_message()
        try:
            target = await event.client.get_entity(replied.sender_id)
        except Exception:
            target = None
        if len(args) >= 2:
            duration_token = args[1]
    elif len(args) >= 3:
        target_token = args[1]
        duration_token = args[2]
        try:
            target = await event.client.get_entity(int(target_token)) if target_token.lstrip('-').isdigit() else await event.client.get_entity(target_token)
        except Exception:
            target = None
    elif len(args) == 2:
        # Без цели команда выдаёт Premium самому себе.
        target = await event.client.get_entity(event.sender_id)
        duration_token = args[1]
    else:
        target = await event.client.get_entity(event.sender_id)
        duration_token = "навсегда"

    if target is None:
        await event.respond("❌ Не удалось найти получателя. Используйте ответом или /premium @username 5м")
        return

    parsed = parse_duration(duration_token, allow_forever=True)
    if parsed is None:
        await event.respond("⚠️ Неверный срок. Примеры: 5м, 1ч, 1д, 1н или навсегда.")
        return

    if parsed == 0:
        until_timestamp = 0
        duration_text = "навсегда"
    else:
        seconds, duration_text = parsed
        until_timestamp = int(time.time() + seconds)

    username = getattr(target, 'username', None) or getattr(target, 'first_name', None) or str(target.id)
    db.ensure_user(target.id, username, 0)
    if not db.set_premium(target.id, until_timestamp):
        await event.respond("❌ Не удалось сохранить Premium в базе данных.")
        return

    await event.respond(
        f"💎 **Premium выдан!**\n👤 Получатель: [{getattr(target, 'first_name', username)}](tg://user?id={target.id})\n⏳ Срок: **{duration_text}**"
    )

# Обработчик команды /help
@bot.on(events.NewMessage(pattern='/help'))
async def help_cmd(event):
    help_text = """
🤖 **Команды бота:**

📋 **Проверка пользователей:**
• `Чек [юзернейм/ID]` - проверить пользователя
• `Чек` (ответом на сообщение) - проверить пользователя
• `Чек ми/я/себя` - проверить себя

💎 **Premium:**
• `/premium 5м` — выдать Premium себе на 5 минут
• `/premium 1ч` — на 1 час
• `/premium 1д` — на 1 день
• `/premium 1н` — на 1 неделю
• `/premium навсегда` — навсегда
• `/premium @username 1д` или ответом — выдать другому пользователю

👮‍♂️ **Выдача ролей:**
• `+стажер` (ответом) - выдать роль стажера  
• `+админ` (ответом) - выдать роль админа
• `+директор` (ответом) - выдать роль директора
• `+президент` (ответом) - выдать роль президента 
• `+создатель` (ответом) - выдать роль создателя
• `+владелец` (ответом) - назначить владельца (только владелец)
• `+кодер` (ответом) - выдать роль кодера
• `+гарант` (ответом) - выдать роль гаранта

🔄 **Снятие ролей:**
• `-стажер` (ответом) - снять роль стажера
• `-админ` (ответом) - снять роль админа  
• `-директор` (ответом) - снять роль директора
• `-президент` (ответом) - снять роль президента
• `-создатель` (ответом) - снять роль создателя  
• `-владелец` (ответом) - снять владельца (только другой владелец)
• `-кодер` (ответом) - снять роль кодера
• `-гарант` (ответом) - снять роль гаранта

⚠️ **Примечание:**
Premium выдают только Президент и Владелец. Сроки: м=минута, ч=час, д=день, н=неделя.
"""
    await event.respond(help_text, parse_mode='md')


# Переменные для хранения статистики
guarantors_count = len(get_guarantors())  # Получаем количество гарантов
trainees_count = len(get_trainees())  # Получаем количество стажеров
total_messages = 0
verified_guarantors_count = 0
checks_count = 0
scammers_count = 0

# Словари для хранения времени последнего вызова команд
admin_cooldowns = {}
guarantor_cooldowns = {}


# Обработчик команды "админы!"
@bot.on(events.NewMessage(pattern=r'(?i)^админы!$'))
async def call_admins(event):
    user_id = event.sender_id
    current_time = datetime.now()

    # Проверка времени последнего вызова команды
    if user_id in admin_cooldowns:
        time_diff = current_time - admin_cooldowns[user_id]
        if time_diff < timedelta(hours=4):
            remaining = timedelta(hours=4) - time_diff
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds % 3600) // 60
            await event.respond(
                f"**⏳ Подождите {hours} ч. {minutes} мин. прежде чем снова вызывать админов!**"
            )
            return

    admin_cooldowns[user_id] = current_time

    # Получение администраторов из базы данных
    conn =get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id FROM users 
        WHERE role IN ("Стажер", "Админ", "Директор", "Президент", "Создатель", "Заместитель")
    ''')
    admins = cursor.fetchall()
    conn.close()

    # Создаем текст с невидимыми упоминаниями
    mentions_text = "**✅ Админы вызваны!**"
    for admin in admins:
        mentions_text += f"[\u200b](tg://user?id={admin[0]})"  # Невидимое упоминание

        # Отправка личного сообщения админам
        caller_username = event.sender.username
        caller_mention = f"@{caller_username}" if caller_username else event.sender.mention

        admin_message = f"**🚨 В чате пользователь {caller_mention} вызывает админов!**"

        await bot.send_message(admin[0], admin_message)
        logging.info(f"Сообщение отправлено администратору: {admin[0]}")

    # Отправляем одно сообщение с текстом и скрытыми упоминаниями
    await event.respond(mentions_text)


# Обработчик команды "гаранты!"
@bot.on(events.NewMessage(pattern=r'(?i)^гаранты!$'))
async def call_guarantors(event):
    user_id = event.sender_id
    current_time = datetime.now()

    # Проверка времени последнего вызова команды
    if user_id in guarantor_cooldowns:
        time_diff = current_time - guarantor_cooldowns[user_id]
        if time_diff < timedelta(hours=1):
            remaining = timedelta(hours=1) - time_diff
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds % 3600) // 60
            await event.respond(
                f"**⏳ Подождите {hours} ч. {minutes} мин. прежде чем снова вызывать гарантов!**"
            )
            return

    guarantor_cooldowns[user_id] = current_time

    # Получение гарантов из базы данных
    guarantors = get_guarantors()

    # Создаем текст с невидимыми упоминаниями
    mentions_text = "**🔰 Гаранты вызваны!**"
    for guarantor_id in guarantors:
        mentions_text += f"[\u200b](tg://user?id={guarantor_id})"  # Невидимое упоминание

        # Отправка личного сообщения гарантам
        caller_username = event.sender.username
        caller_mention = f"@{caller_username}" if caller_username else event.sender.mention

        guarantor_message = f"**🚨 В чате пользователь {caller_mention} вызывает гарантов!**"

        await bot.send_message(guarantor_id, guarantor_message)
        logging.info(f"Сообщение отправлено гаранту: {guarantor_id}")

    # Отправляем одно сообщение с текстом и скрытыми упоминаниями
    await event.respond(mentions_text)


# Обработчик команды "/stata"
@bot.on(events.NewMessage(pattern=r'(?i)^/stata$'))
async def show_statistics(event):
    global total_messages, verified_guarantors_count, checks_count, scammers_count, trainees_count

    # Получаем общее количество сообщений через экземпляр db
    total_messages = db.get_total_messages()  # Используйте экземпляр db

    # Получаем количество гарантов
    guarantors_count = len(get_guarantors())  # Получаем актуальное количество гарантов

    statistics = (
        f"📊 **Статистика чата:**\n"
        f"👥 Гаранты: {guarantors_count}\n"
        f"👨‍🎓 Стажеры: {trainees_count}\n"
        f"📩 Общее количество сообщений: {total_messages}\n"
        f"✅ Проверены гарантом: {verified_guarantors_count}\n"
        f"🔍 Число проверок: {checks_count}\n"
        f"🚫 Скаммеры в базе: {scammers_count}"
    )

    await event.respond(statistics)


@bot.on(events.NewMessage())
async def count_messages(event):
    global total_messages
    total_messages += 1
    db.update_total_messages(1)
    logging.info(f"Общее количество сообщений: {total_messages}")


@bot.on(events.NewMessage(pattern=r'(?i)^/del'))
async def delete_message(event):
    if event.is_reply:
        replied_message = await event.get_reply_message()
        await replied_message.delete()  # Удаляем сообщение, на которое ответили
    else:
        await event.reply("❌ Пожалуйста, ответьте на сообщение, которое хотите удалить.")

@bot.on(events.NewMessage)
async def debug_all_messages(event):
    if event.sender_id in OWNER_ID:  # Только владельцы
        logging.info(f"DEBUG: Получено сообщение от {event.sender_id}: {event.raw_text}")

@bot.on(events.NewMessage(pattern=r'[+-](?:[А-Яа-яёЁ]+)(?:\s+(?:@?\w+|\d+))?'))
async def handle_role_command(event):
    logging.info(f"=== ПОПЫТКА ОБРАБОТКИ КОМАНДЫ РОЛИ ===")
    logging.info(f"Сообщение: {event.raw_text}")
    logging.info(f"Отправитель ID: {event.sender_id}")

    user_role = db.get_user_role(event.sender_id)
    is_admin = event.sender_id in OWNER_ID or user_role == 10

    if not is_admin:
        msg = await event.reply("❌ У вас нет прав для выполнения этой команды",
                                buttons=Button.inline("↩Скрыть", b"hide_message"))
        bot.last_message_id = msg.id
        return

    command_parts = event.raw_text.split()
    action = command_parts[0][0]  # + или -
    role = command_parts[0][1:].lower()

    # Получаем целевого пользователя
    try:
        if len(command_parts) > 1:
            target = command_parts[1]
            if target.isdigit():
                user = await event.client.get_entity(int(target))
            else:
                if target.startswith('@'):
                    target = target[1:]
                user = await event.client.get_entity(target)
        else:
            if not event.is_reply:
                msg = await event.reply("❌ Укажите пользователя или ответьте на его сообщение",
                                        buttons=Button.inline("↩Скрыть", b"hide_message"))
                bot.last_message_id = msg.id
                return
            replied = await event.get_reply_message()
            user = await event.client.get_entity(replied.sender_id)
    except:
        msg = await event.reply("❌ Не удалось найти пользователя!",
                                buttons=Button.inline("↩Скрыть", b"hide_message"))
        bot.last_message_id = msg.id
        return

    role_mapping = {
        'стажер': 6,
        'админ': 7,
        'директор': 8,
        'президент': 9,
        'гарант': 1,
        'кодер': 11,
        'владелец': 10,
        'айдош': 13,
        'создатель': 10
    }

    current_role = db.get_user_role(user.id)

    # Проверяем, есть ли пользователь в базе
    user_exists = db.get_user(user.id) is not None

    if action == '+':
        # Проверка для президента
        if user_role == 9 and role in ['президент']:
            msg = await event.reply("❌ Президент не может выдавать роль президента.",
                                    buttons=Button.inline("↩Скрыть", b"hide_message"))
            bot.last_message_id = msg.id
            return

        # Владельца может назначить только действующий владелец.
        if role == 'владелец':
            if event.sender_id not in OWNER_ID:
                msg = await event.reply("❌ Только владелец может назначать владельца.", buttons=Button.inline("↩Скрыть", b"hide_message"))
                bot.last_message_id = msg.id
                return
            if user.id == event.sender_id:
                msg = await event.reply("❌ Нельзя назначить владельцем самого себя повторно.", buttons=Button.inline("↩Скрыть", b"hide_message"))
                bot.last_message_id = msg.id
                return
            if not user_exists:
                db.add_user(user.id, user.username)
            db.update_role(user.id, 10, granted_by_id=event.sender_id)
            if user.id not in OWNER_ID:
                OWNER_ID.append(user.id)
            REVOKED_OWNER_IDS.discard(user.id)
            _save_revoked_owner_ids(REVOKED_OWNER_IDS)
            msg = await event.reply(
                f"✅ Пользователь [{user.first_name}](tg://user?id={user.id}) назначен владельцем.",
                buttons=Button.inline("↩Скрыть", b"hide_message"))
            bot.last_message_id = msg.id
            return

        # Специальные права для действующих владельцев.
        if event.sender_id in OWNER_ID and role in ['кодер', 'создатель']:
            if not user_exists:
                db.add_user(user.id, user.username)
            db.update_role(user.id, role_mapping[role], granted_by_id=event.sender_id)
            msg = await event.reply(
                f"✅ Роль {role} выдана пользователю [{user.first_name}](tg://user?id={user.id})",
                buttons=Button.inline("↩Скрыть", b"hide_message"))
            bot.last_message_id = msg.id
            return

        # Обычная выдача ролей - проверяем что у пользователя роль 0 (нет в базе)
        if current_role == 0 or not user_exists:
            # Добавляем пользователя если его нет
            if not user_exists:
                db.add_user(user.id, user.username)
            # Обновляем роль
            db.update_role(user.id, role_mapping[role])
            msg = await event.reply(
                f"✅ Роль {role} выдана пользователю [{user.first_name}](tg://user?id={user.id})",
                buttons=Button.inline("↩Скрыть", b"hide_message"))
            bot.last_message_id = msg.id
        else:
            msg = await event.reply("❌ У пользователя уже есть роль.",
                                    buttons=Button.inline("↩Скрыть", b"hide_message"))
            bot.last_message_id = msg.id
    else:  # action == '-'
        # Снятие ролей
        # Владелец может снять другого владельца, включая одного из стартовых OWNER_ID.
        if role == 'владелец':
            if event.sender_id not in OWNER_ID:
                msg = await event.reply("❌ Только владелец может снимать владельца.", buttons=Button.inline("↩Скрыть", b"hide_message"))
                bot.last_message_id = msg.id
                return
            if user.id == event.sender_id:
                msg = await event.reply("❌ Нельзя снять владельца с самого себя.", buttons=Button.inline("↩Скрыть", b"hide_message"))
                bot.last_message_id = msg.id
                return
            if user.id not in OWNER_ID and current_role != 10:
                msg = await event.reply("❌ У пользователя нет роли владельца.", buttons=Button.inline("↩Скрыть", b"hide_message"))
                bot.last_message_id = msg.id
                return
            db.update_role(user.id, 0, granted_by_id=event.sender_id)
            if user.id in OWNER_ID:
                OWNER_ID.remove(user.id)
            REVOKED_OWNER_IDS.add(user.id)
            _save_revoked_owner_ids(REVOKED_OWNER_IDS)
            msg = await event.reply(
                f"✅ Владелец снят с пользователя [{user.first_name}](tg://user?id={user.id})",
                buttons=Button.inline("↩Скрыть", b"hide_message"))
            bot.last_message_id = msg.id
            return

        if current_role == 10 and event.sender_id not in OWNER_ID:
            msg = await event.reply("❌ Только владелец может снять роль владельца.",
                                    buttons=Button.inline("↩Скрыть", b"hide_message"))
            bot.last_message_id = msg.id
            return

        if current_role > 0:
            db.update_role(user.id, 0)
            msg = await event.reply(
                f"✅ Роль снята с пользователя [{user.first_name}](tg://user?id={user.id})",
                buttons=Button.inline("↩Скрыть", b"hide_message"))
            bot.last_message_id = msg.id
        else:
            msg = await event.reply("❌ У пользователя нет роли",
                                    buttons=Button.inline("↩Скрыть", b"hide_message"))
            bot.last_message_id = msg.id


@bot.on(events.CallbackQuery(data=b"hide_message"))
async def hide_message_handler(event):
    try:
        await event.delete()
    except Exception as e:
        print(f"Ошибка при удалении сообщения: {e}")


# Права для мута (ограничения)
MUTE_RIGHTS = ChatBannedRights(
    until_date=None,
    send_messages=True,
    send_media=True,
    send_stickers=True,
    send_gifs=True,
    send_games=True,
    send_inline=True,
)

# Права для размута (снятие ограничений)
UNMUTE_RIGHTS = ChatBannedRights(
    until_date=None,
    send_messages=False,
    send_media=False,
    send_stickers=False,
    send_gifs=False,
    send_games=False,
    send_inline=False,
)


def parse_duration(value, allow_forever=False):
    """Поддерживает 5м, 2ч, 1д, 1н; m/h/d/w тоже принимаются. m = минута."""
    if not value:
        return None
    raw = value.strip().lower()
    if allow_forever and raw in {"навсегда", "навсегда!", "forever", "perm", "permanent"}:
        return 0
    m = re.fullmatch(r'(\d+)\s*(м|мин|m|ч|h|д|d|н|нед|w|week|weeks)', raw)
    if not m:
        return None
    amount = int(m.group(1))
    if amount <= 0:
        return None
    unit = m.group(2)
    if unit in {"м", "мин", "m"}:
        seconds = amount * 60
        label = f"{amount} мин."
    elif unit in {"ч", "h"}:
        seconds = amount * 3600
        label = f"{amount} ч."
    elif unit in {"д", "d"}:
        seconds = amount * 86400
        label = f"{amount} дн."
    else:
        seconds = amount * 604800
        label = f"{amount} нед."
    return int(seconds), label

async def get_target_from_moderation_command(event):
    """Цель: reply, @username или числовой ID."""
    if event.is_reply:
        replied = await event.get_reply_message()
        return await event.client.get_entity(replied.sender_id)
    args = event.raw_text.split()
    if len(args) < 2:
        return None
    target = args[1]
    try:
        if target.startswith('@'):
            return await event.client.get_entity(target)
        if target.lstrip('-').isdigit():
            return await event.client.get_entity(int(target))
        return await event.client.get_entity(target)
    except Exception:
        return None

async def moderation_role_allowed(user_id, allowed_roles):
    role = db.get_user_role(user_id)
    return role in allowed_roles or (role == 10 and user_id in OWNER_ID)

async def send_log(action, admin, user, duration, chat, reason=None, message_link=None):
    """Отправляет логи в канал, не ломая основное действие при недоступном лог-чате."""
    text = (
        f"**{action.upper()}**\n\n"
        f"👤 **Пользователь:** {getattr(user, 'first_name', user.id)} (`{user.id}`)\n"
        f"👮 **Администратор:** {getattr(admin, 'first_name', admin.id)} (`{admin.id}`)\n"
        f"💬 **Чат:** {getattr(chat, 'title', str(getattr(chat, 'id', '')))} (`{getattr(chat, 'id', '')}`)\n"
    )
    if duration:
        text += f"⏳ **Длительность:** {duration}\n"
    if reason:
        text += f"📝 **Причина:** {reason}\n"
    if message_link:
        text += f"🔗 **Сообщение:** [ссылка]({message_link})"
    try:
        await bot.send_message(LOG_CHANNEL, text, link_preview=False)
    except Exception as e:
        logger.warning(f"Не удалось отправить лог {action}: {e}")

@bot.on(events.NewMessage(pattern=r'(?i)^(/|\.)?(mute|мут)'))
async def mute_handler(event):
    if not await moderation_role_allowed(event.sender_id, MUTE_ALLOWED_ROLES):
        await event.reply("⛔️ Мут могут выдавать только стажёр, админ, директор, президент и владелец.")
        return
    target = await get_target_from_moderation_command(event)
    if not target:
        await event.reply("⚠️ Ответьте на сообщение или используйте: /mute @username 5м [причина]")
        return
    args = event.raw_text.split()
    if event.is_reply:
        duration_token = args[1] if len(args) > 1 else None
        reason = ' '.join(args[2:]) if len(args) > 2 else 'Не указана'
    else:
        duration_token = args[2] if len(args) > 2 else None
        reason = ' '.join(args[3:]) if len(args) > 3 else 'Не указана'
    parsed = parse_duration(duration_token)
    if not parsed:
        await event.reply("⚠️ Неверное время. Примеры: /mute 5м, /mute 2ч, /mute 1д или ответом /mute 5м")
        return
    seconds, duration_text = parsed
    expiry_timestamp = int(time.time() + seconds)
    try:
        await bot.edit_permissions(
            event.chat_id, target.id,
            until_date=expiry_timestamp,
            send_messages=False,
            send_media=False,
            send_stickers=False,
            send_gifs=False,
            send_games=False,
            send_inline=False
        )
        muted_users[(event.chat_id, target.id)] = expiry_timestamp
        msg = await event.reply(
            f"📛 **Мут выдан**\n👤 {getattr(target, 'first_name', target.id)} (`{target.id}`)\n⏳ {duration_text}\n📝 {reason}",
            buttons=[[Button.inline("🕐 Снять мут", f"unmute_{target.id}")]]
        )
        await send_log("Мут", event.sender, target, duration_text, await event.get_chat(), reason,
                       f"https://t.me/c/{event.chat_id}/{msg.id}")
    except Exception as e:
        await event.reply(f"❌ Не удалось выдать мут: {e}")

@bot.on(events.NewMessage(pattern=r'(?i)^(/|\.)?(unmute|анмут)'))
async def unmute_handler(event):
    if not await moderation_role_allowed(event.sender_id, MUTE_ALLOWED_ROLES):
        await event.reply("⛔️ Размут могут выполнять только стажёр, админ, директор, президент и владелец.")
        return
    target = await get_target_from_moderation_command(event)
    if not target:
        await event.reply("⚠️ Ответьте на сообщение или используйте: /unmute @username")
        return
    try:
        await bot.edit_permissions(
            event.chat_id, target.id,
            until_date=None,
            view_messages=True,
            send_messages=True,
            send_media=True,
            send_stickers=True,
            send_gifs=True,
            send_games=True,
            send_inline=True
        )
        muted_users.pop((event.chat_id, target.id), None)
        msg = await event.reply(f"🔊 **Мут снят** с {getattr(target, 'first_name', target.id)} (`{target.id}`).")
        await send_log("Размут", event.sender, target, "Досрочно", await event.get_chat(), message_link=f"https://t.me/c/{event.chat_id}/{msg.id}")
    except Exception as e:
        await event.reply(f"❌ Не удалось снять мут: {e}")

@bot.on(events.NewMessage(pattern=r'(?i)^(/|\.)?(ban|бан)'))
async def ban_handler(event):
    if not await moderation_role_allowed(event.sender_id, BAN_ALLOWED_ROLES):
        await event.reply("⛔️ Бан могут выдавать только админ, директор, президент и владелец.")
        return
    target = await get_target_from_moderation_command(event)
    if not target:
        await event.reply("⚠️ Ответьте на сообщение или используйте: /ban @username 5м [причина]")
        return
    args = event.raw_text.split()
    if event.is_reply:
        duration_token = args[1] if len(args) > 1 else None
        reason = ' '.join(args[2:]) if len(args) > 2 else 'Не указана'
    else:
        duration_token = args[2] if len(args) > 2 else None
        reason = ' '.join(args[3:]) if len(args) > 3 else 'Не указана'
    parsed = parse_duration(duration_token)
    if not parsed:
        await event.reply("⚠️ Неверное время. Примеры: /ban 5м, /ban 2ч, /ban 1д или ответом /ban 5м")
        return
    seconds, duration_text = parsed
    expiry_timestamp = int(time.time() + seconds)
    try:
        await bot.edit_permissions(event.chat_id, target.id, until_date=expiry_timestamp, view_messages=False)
        msg = await event.reply(
            f"📛 **Бан выдан**\n👤 {getattr(target, 'first_name', target.id)} (`{target.id}`)\n⏳ {duration_text}\n📝 {reason}",
            buttons=[[Button.inline("🔓 Снять бан пользователю", f"unban_{target.id}")]]
        )
        await send_log("Бан", event.sender, target, duration_text, await event.get_chat(), reason,
                       f"https://t.me/c/{event.chat_id}/{msg.id}")
    except Exception as e:
        await event.reply(f"❌ Не удалось выдать бан: {e}")

@bot.on(events.NewMessage(pattern=r'(?i)^(/|\.)?(unban|разбан)'))
async def unban_handler(event):
    if not await moderation_role_allowed(event.sender_id, BAN_ALLOWED_ROLES):
        await event.reply("⛔️ Разбан могут выполнять только админ, директор, президент и владелец.")
        return
    target = await get_target_from_moderation_command(event)
    if not target:
        await event.reply("⚠️ Ответьте на сообщение или используйте: /unban @username")
        return
    try:
        await bot.edit_permissions(
            event.chat_id, target.id,
            until_date=None,
            view_messages=True,
            send_messages=True,
            send_media=True,
            send_stickers=True,
            send_gifs=True,
            send_games=True,
            send_inline=True
        )
        muted_users.pop((event.chat_id, target.id), None)
        msg = await event.reply(f"🔓 **Бан снят** с {getattr(target, 'first_name', target.id)} (`{target.id}`).")
        await send_log("Разбан", event.sender, target, "Досрочно", await event.get_chat(), message_link=f"https://t.me/c/{event.chat_id}/{msg.id}")
    except Exception as e:
        await event.reply(f"❌ Не удалось снять бан: {e}")

# Кнопки, отправленные прямо в чате, используют те же проверки прав.
@bot.on(events.CallbackQuery(pattern=r'unmute_(\d+)'))
async def unmute_button_handler(event):
    if not await moderation_role_allowed(event.sender_id, MUTE_ALLOWED_ROLES):
        await event.answer("⛔ Нет прав на размут.", alert=True)
        return
    target_id = int(event.pattern_match.group(1))
    try:
        await bot.edit_permissions(
            event.chat_id, target_id,
            until_date=None, view_messages=True, send_messages=True,
            send_media=True, send_stickers=True, send_gifs=True,
            send_games=True, send_inline=True
        )
        muted_users.pop((event.chat_id, target_id), None)
        await event.answer("✅ Мут снят.")
        try:
            await event.edit("🔊 **Мут снят.**")
        except Exception:
            pass
    except Exception as e:
        await event.answer(f"❌ {str(e)[:180]}", alert=True)

@bot.on(events.CallbackQuery(pattern=r'unban_(\d+)'))
async def unban_button_handler(event):
    if not await moderation_role_allowed(event.sender_id, BAN_ALLOWED_ROLES):
        await event.answer("⛔ Нет прав на разбан.", alert=True)
        return
    target_id = int(event.pattern_match.group(1))
    try:
        await bot.edit_permissions(
            event.chat_id, target_id,
            until_date=None, view_messages=True, send_messages=True,
            send_media=True, send_stickers=True, send_gifs=True,
            send_games=True, send_inline=True
        )
        muted_users.pop((event.chat_id, target_id), None)
        await event.answer("✅ Бан снят.")
        try:
            await event.edit("🔓 **Бан снят.**")
        except Exception:
            pass
    except Exception as e:
        await event.answer(f"❌ {str(e)[:180]}", alert=True)


@bot.on(events.CallbackQuery(pattern=rb'accept_scam_(.+)'))
async def accept_scam_handler(event):
    data = event.data.decode('utf-8')
    unique_id = data.split('_')[2]

    if unique_id not in TEMP_STORAGE:
        await event.answer("❌ Заявка не найдена или уже обработана", alert=True)
        return

    scam_data = TEMP_STORAGE[unique_id]

    # Проверяем, что отвечает куратор
    curator_id = event.sender_id
    trainee_curator = db.get_user_curator(scam_data['user_id'])

    if curator_id != trainee_curator:
        await event.answer("❌ Вы не являетесь куратором этого стажёра", alert=True)
        return

    try:
        # Получаем выбранную роль стажёром
        role_id = scam_data.get('selected_role', 3)  # По умолчанию скамер
        role_name = scam_data.get('selected_role_name', '❌ Скамер')

        # Добавляем пользователя если его нет
        if not db.get_user(scam_data['scammer_id']):
            db.add_user(scam_data['scammer_id'], scam_data['scammer_name'])

        # Обновляем роль
        db.update_role(scam_data['scammer_id'], role_id)

        # Добавляем запись в таблицу scammers
        scammer_added = db.add_scammer(
            scam_data['scammer_id'],
            scam_data['reason'],
            scam_data['user_name'],
            scam_data['reason'],
            unique_id,
            scam_data['proof_link'],
            scam_data['user_id']
        )

        if scammer_added:
            # Увеличиваем счётчик слитых скаммеров у стажёра
            current_count = db.get_user_reported_scammers_count(scam_data['user_id'])
            new_count = current_count + 1
            db.update_user_scammers_count(scam_data['user_id'], new_count)

            # Обновляем статус заявки
            TEMP_STORAGE[unique_id]['status'] = 'accepted'

            # Уведомляем стажёра
            await bot.send_message(
                scam_data['user_id'],
                f"✅ Ваша заявка на скаммера {scam_data['scammer_name']} принята куратором!\n"
                f"🎯 Роль: {role_name}\n"
                f"📎 Доказательства: {scam_data['proof_link']}\n"
                f"📝 Причина: {scam_data['reason']}\n"
                f"🎉 Теперь у вас {new_count} слитых скаммеров!"
            )

            # Редактируем сообщение у куратора
            await event.edit(
                f"✅ **Заявка принята!**\n\n"
                f"👤 Скаммер: {scam_data['scammer_name']}\n"
                f"🎯 Роль: {role_name}\n"
                f"📎 Доказательства: {scam_data['proof_link']}\n"
                f"📝 Причина: {scam_data['reason']}\n"
                f"👨‍🎓 Стажёр: {scam_data['user_name']}\n\n"
                f"📊 У стажёра теперь: {new_count} слитых скаммеров",
                buttons=None
            )

            # Удаляем из временного хранилища
            if unique_id in TEMP_STORAGE:
                del TEMP_STORAGE[unique_id]

            await event.answer("✅ Заявка принята!", alert=True)
        else:
            await event.answer("❌ Ошибка при добавлении скаммера", alert=True)

    except Exception as e:
        logging.error(f"Ошибка при принятии заявки: {e}")
        await event.answer("❌ Произошла ошибка", alert=True)


@bot.on(events.CallbackQuery(pattern=rb'reject_scam_(.+)'))
async def reject_scam_handler(event):
    data = event.data.decode('utf-8')
    unique_id = data.split('_')[2]

    if unique_id not in TEMP_STORAGE:
        await event.answer("❌ Заявка не найдена или уже обработана", alert=True)
        return

    scam_data = TEMP_STORAGE[unique_id]

    # Проверяем, что отвечает куратор
    curator_id = event.sender_id
    trainee_curator = db.get_user_curator(scam_data['user_id'])

    if curator_id != trainee_curator:
        await event.answer("❌ Вы не являетесь куратором этого стажёра", alert=True)
        return

    # Получаем выбранную роль для отображения
    role_name = scam_data.get('selected_role_name', 'Не выбрана')

    # Обновляем статус заявки
    TEMP_STORAGE[unique_id]['status'] = 'rejected'

    # Уведомляем стажёра
    await bot.send_message(
        scam_data['user_id'],
        f"❌ Ваша заявка на скаммера {scam_data['scammer_name']} отклонена куратором.\n"
        f"🎯 Выбранная роль: {role_name}\n"
        f"📎 Доказательства: {scam_data['proof_link']}\n"
        f"📝 Причина заявки: {scam_data['reason']}\n\n"
        f"❌ **Причина отклонения:** недостаточно доказательств или неверная информация."
    )

    # Редактируем сообщение у куратора
    await event.edit(
        f"❌ **Заявка отклонена!**\n\n"
        f"👤 Скаммер: {scam_data['scammer_name']}\n"
        f"🎯 Выбранная роль: {role_name}\n"
        f"📎 Доказательства: {scam_data['proof_link']}\n"
        f"📝 Причина заявки: {scam_data['reason']}\n"
        f"👨‍🎓 Стажёр: {scam_data['user_name']}",
        buttons=None
    )

    # Удаляем из временного хранилища
    if unique_id in TEMP_STORAGE:
        del TEMP_STORAGE[unique_id]

    await event.answer("❌ Заявка отклонена", alert=True)


@bot.on(events.NewMessage(pattern=r'(?i)^(?:/скам|/sc|/scam)'))
async def scam_command(event):
    logging.info("Команда /скам была вызвана.")
    user_id = event.sender_id

    user_role = db.get_user_role(user_id)

    # Проверяем, может ли пользователь заносить
    if user_role not in CAN_ADD_SCAMMER_ROLES:
        await event.respond("❌ Только персонал базы может заносить скамеров!")
        return

    args = event.raw_text.split(maxsplit=2)
    if len(args) < 3:
        await event.respond("❌ Используйте: /скам @username/ID *ссылка_на_доказательства причина*")
        return

    target = args[1]
    full_reason = args[2].strip('*')

    # Разделяем ссылку на доказательства и причину
    parts = full_reason.split(' ', 1)
    if len(parts) >= 2:
        proof_link = parts[0]
        reason = parts[1]
    else:
        proof_link = full_reason
        reason = "Без подробного описания"

    logging.info(f"Пользователь {user_id} (роль: {user_role}) пытается добавить скамера: {target}")

    try:
        scammer_user = None
        # Проверка по ID
        if target.isdigit():
            user_id_to_check = int(target)
            # Пытаемся получить пользователя из Telegram
            try:
                scammer_user = await event.client.get_entity(user_id_to_check)
            except:
                # Если не можем получить из Telegram, создаем фейковый объект
                scammer_user = type('UserObject', (), {
                    'id': user_id_to_check,
                    'first_name': f"ID: {user_id_to_check}"
                })()
        else:
            # Проверка по юзернейму
            if target.startswith('@'):
                target = target[1:]
            scammer_user = await event.client.get_entity(target)

    except Exception as e:
        await event.respond("❌ Не могу найти пользователя")
        logging.error(f"Ошибка при получении пользователя: {e}")
        return

    # Проверяем, является ли целевой пользователь персоналом?
    scammer_role = db.get_user_role(scammer_user.id)

    if scammer_role in STAFF_ROLES:
        scammer_role_name = ROLES.get(scammer_role, {}).get('name', 'Неизвестно')
        user_role_name = ROLES.get(user_role, {}).get('name', 'Неизвестно')

        await event.respond(
            f"🚫 **ЗАПРЕЩЕНО ЗАНОСИТЬ ПЕРСОНАЛ!**\n\n"
            f"👤 **Вы:** {user_role_name}\n"
            f"🎯 **Пытаетесь занести:** {scammer_role_name}\n\n"
            f"❌ Персонал базы Forget AntiScam не может быть занесен в базу скамеров!"
        )
        return

    # Получаем имя пользователя
    if hasattr(scammer_user, 'first_name'):
        scammer_name = scammer_user.first_name
    elif hasattr(scammer_user, 'title'):
        scammer_name = scammer_user.title
    else:
        scammer_name = f"ID: {scammer_user.id}"

    # Сохраняем временные данные о заносе
    unique_id = str(uuid.uuid4())
    TEMP_STORAGE[unique_id] = {
        'scammer_id': scammer_user.id,
        'scammer_name': scammer_name,
        'user_id': user_id,
        'user_name': (await event.get_sender()).first_name,
        'user_role': user_role,
        'reason': reason,
        'proof_link': proof_link,
        'status': 'pending',
        'selected_role': None,
        'selected_role_name': None
    }

    # Для стажёров показываем окно выбора роли
    if user_role == 6:  # Стажёр
        buttons = [
            [Button.inline("🐓 Петух", f"select_role_petuh_{unique_id}".encode()),
             Button.inline("❌ Скамер", f"select_role_scammer_{unique_id}".encode())],
            [Button.inline("⚠️ Возможно скамер", f"select_role_possible_{unique_id}".encode())]
        ]

        await event.respond(
            f"Выберите роль для скамера {scammer_name}:\n\n"
            f"📋 **Проверка:** Целевой пользователь НЕ является персоналом базы ✅\n"
            f"🐓 **Петух** - пользователь с плохой репутацией\n"
            f"❌ **Скамер** - доказанный мошенник\n"
            f"⚠️ **Возможно скамер** - потенциальный мошенник\n\n"
            f"📎 **Доказательства:** {proof_link}\n"
            f"📝 **Причина:** {reason}",
            buttons=buttons
        )
    else:
        # Для остального персонала сразу показываем окно выбора роли
        buttons = [
            [Button.inline("🐓 Петух", f"direct_role_petuh_{unique_id}".encode()),
             Button.inline("❌ Скамер", f"direct_role_scammer_{unique_id}".encode())],
            [Button.inline("⚠️ Возможно скамер", f"direct_role_possible_{unique_id}".encode())]
        ]

        await event.respond(
            f"Выберите роль для скамера {scammer_name}:\n\n"
            f"📋 **Проверка:** Целевой пользователь НЕ является персоналом базы ✅\n"
            f"🐓 **Петух** - пользователь с плохой репутацией\n"
            f"❌ **Скамер** - доказанный мошенник\n"
            f"⚠️ **Возможно скамер** - потенциальный мошенник\n\n"
            f"📎 **Доказательства:** {proof_link}\n"
            f"📝 **Причина:** {reason}",
            buttons=buttons
        )


@bot.on(events.CallbackQuery(pattern=rb'select_role_petuh_(.+)'))
async def select_role_petuh_handler(event):
    await process_trainee_role_selection(event, 4, "🐓 Петух")


@bot.on(events.CallbackQuery(pattern=rb'select_role_scammer_(.+)'))
async def select_role_scammer_handler(event):
    await process_trainee_role_selection(event, 3, "❌ Скамер")


@bot.on(events.CallbackQuery(pattern=rb'select_role_possible_(.+)'))
async def select_role_possible_handler(event):
    await process_trainee_role_selection(event, 2, "⚠️ Возможно скамер")


async def process_trainee_role_selection(event, role_id, role_name):
    data = event.data.decode('utf-8')
    unique_id = data.split('_')[3]

    if unique_id not in TEMP_STORAGE:
        await event.answer("❌ Заявка не найдена или уже обработана", alert=True)
        return

    scam_data = TEMP_STORAGE[unique_id]

    # Двойная проверка: что нажимает тот же пользователь
    if event.sender_id != scam_data['user_id']:
        await event.answer("❌ Вы не можете нажимать на чужие кнопки", alert=True)
        return

    # ПОВТОРНАЯ ПРОВЕРКА: является ли скамер персоналом
    scammer_role = db.get_user_role(scam_data['scammer_id'])
    if scammer_role in STAFF_ROLES:
        scammer_role_name = ROLES.get(scammer_role, {}).get('name', 'Неизвестно')

        await event.edit(
            f"🚫 **ОШИБКА!**\n\n"
            f"❌ Нельзя заносить персонал базы!\n"
            f"👤 **Целевой пользователь:** {scam_data['scammer_name']}\n"
            f"🎯 **Роль:** {scammer_role_name}\n\n"
            f"ℹ️ Персонал Forget AntiScam не может быть занесен в базу скамеров.\n"
            f"Если у вас есть жалобы на персонал, обратитесь к создателю базы.",
            buttons=None
        )
        return

    # Сохраняем выбранную роль
    TEMP_STORAGE[unique_id]['selected_role'] = role_id
    TEMP_STORAGE[unique_id]['selected_role_name'] = role_name

    # Получаем куратора стажёра
    curator_id = db.get_user_curator(scam_data['user_id'])
    if not curator_id:
        await event.edit("❌ У вас нет назначенного куратора!")
        return

    # Формируем сообщение для куратора
    scammer_info = f"""
🚨 **Новая заявка на скаммера от стажёра**

👤 **Скаммер:** {scam_data['scammer_name']} (ID: {scam_data['scammer_id']})
🎯 **Выбранная роль:** {role_name}
📎 **Доказательства:** {scam_data['proof_link']}
📝 **Причина:** {scam_data['reason']}

👨‍🎓 **Стажёр:** {scam_data['user_name']} (ID: {scam_data['user_id']})
⏰ **Время:** {datetime.now().strftime('%d.%m.%Y %H:%M')}

🆔 **ID заявки:** {unique_id}
    """

    buttons = [
        [Button.inline("✅ Принять", f"accept_scam_{unique_id}".encode()),
         Button.inline("❌ Отклонить", f"reject_scam_{unique_id}".encode())]
    ]

    try:
        # Отправляем куратору в ЛС
        await bot.send_message(
            curator_id,
            scammer_info,
            buttons=buttons,
            parse_mode='md'
        )

        # Редактируем сообщение стажёру
        await event.edit(
            f"✅ Заявка на скамера {scam_data['scammer_name']} отправлена вашему куратору.\n"
            f"🎯 Выбранная роль: {role_name}\n"
            f"📎 Доказательства: {scam_data['proof_link']}\n"
            f"📝 Причина: {scam_data['reason']}\n\n"
            f"Ожидайте рассмотрения заявки.",
            buttons=None
        )

    except Exception as e:
        logging.error(f"Ошибка отправки заявки куратору: {e}")
        await event.edit("❌ Не удалось отправить заявку куратору")


@bot.on(events.CallbackQuery(pattern=rb'direct_role_petuh_(.+)'))
async def direct_role_petuh_handler(event):
    data = event.data.decode('utf-8')
    unique_id = data.split('_')[3]

    if unique_id not in TEMP_STORAGE:
        await event.answer("❌ Заявка не найдена или уже обработана", alert=True)
        return

    scam_data = TEMP_STORAGE[unique_id]

    # ЗАЩИТА: проверяем, что нажимает тот же пользователь
    if event.sender_id != scam_data['user_id']:
        await event.answer("❌ Вы не можете нажимать на чужие кнопки", alert=True)
        return

    await process_direct_role_selection(event, unique_id, 4, "🐓 Петух")


@bot.on(events.CallbackQuery(pattern=rb'direct_role_scammer_(.+)'))
async def direct_role_scammer_handler(event):
    data = event.data.decode('utf-8')
    unique_id = data.split('_')[3]

    if unique_id not in TEMP_STORAGE:
        await event.answer("❌ Заявка не найдена или уже обработана", alert=True)
        return

    scam_data = TEMP_STORAGE[unique_id]

    # ЗАЩИТА: проверяем, что нажимает тот же пользователь
    if event.sender_id != scam_data['user_id']:
        await event.answer("❌ Вы не можете нажимать на чужие кнопки", alert=True)
        return

    await process_direct_role_selection(event, unique_id, 3, "❌ Скамер")


@bot.on(events.CallbackQuery(pattern=rb'direct_role_possible_(.+)'))
async def direct_role_possible_handler(event):
    data = event.data.decode('utf-8')
    unique_id = data.split('_')[3]

    if unique_id not in TEMP_STORAGE:
        await event.answer("❌ Заявка не найдена или уже обработана", alert=True)
        return

    scam_data = TEMP_STORAGE[unique_id]

    # ЗАЩИТА: проверяем, что нажимает тот же пользователь
    if event.sender_id != scam_data['user_id']:
        await event.answer("❌ Вы не можете нажимать на чужие кнопки", alert=True)
        return

    await process_direct_role_selection(event, unique_id, 2, "⚠️ Возможно скамер")


async def process_direct_role_selection(event, unique_id, role_id, role_name):
    scam_data = TEMP_STORAGE[unique_id]

    # Проверка, что нажимает тот же пользователь
    if event.sender_id != scam_data['user_id']:
        await event.answer("❌ Вы не можете нажимать на чужие кнопки", alert=True)
        return

    # ПРОВЕРКА: является ли скамер персоналом
    scammer_role = db.get_user_role(scam_data['scammer_id'])
    if scammer_role in STAFF_ROLES:
        scammer_role_name = ROLES.get(scammer_role, {}).get('name', 'Неизвестно')
        user_role_name = ROLES.get(scam_data['user_role'], {}).get('name', 'Неизвестно')

        await event.edit(
            f"🚫 **ЗАПРЕЩЕНО!**\n\n"
            f"👤 **Вы:** {user_role_name}\n"
            f"🎯 **Цель:** {scammer_role_name}\n\n"
            f"❌ Нельзя заносить персонал базы Forget AntiScam!\n"
            f"📋 Защищенные роли:\n"
            f"• Гаранты (1) 🛡️\n• Стажёры (6) 🎓\n• Админы (7) 👮\n"
            f"• Директора (8) 👔\n• Президенты (9) 👑\n• Владельцы (10) ⭐\n"
            f"• Кодеры (11) 💻\n• Проверенные (12) ✅\n• Айдош (13) ⭐\n\n"
            f"ℹ️ Если у вас есть жалобы на персонал, обратитесь к создателю базы.",
            buttons=None
        )
        return

    try:
        # Добавляем пользователя если его нет
        if not db.get_user(scam_data['scammer_id']):
            db.add_user(scam_data['scammer_id'], scam_data['scammer_name'])

        # Обновляем роль
        db.update_role(scam_data['scammer_id'], role_id)

        # Добавляем запись в таблицу scammers
        scammer_added = db.add_scammer(
            scam_data['scammer_id'],
            scam_data['reason'],
            scam_data['user_name'],
            scam_data['reason'],
            unique_id,
            scam_data['proof_link'],
            scam_data['user_id']
        )

        if scammer_added:
            # Увеличиваем счётчик слитых скамеров у пользователя
            if scam_data['user_role'] in STAFF_ROLES:
                current_count = db.get_user_reported_scammers_count(scam_data['user_id'])
                new_count = current_count + 1
                db.update_user_scammers_count(scam_data['user_id'], new_count)

                # Уведомляем пользователя
                await bot.send_message(
                    scam_data['user_id'],
                    f"✅ Скаммер {scam_data['scammer_name']} успешно занесён!\n"
                    f"🎯 Роль: {role_name}\n"
                    f"📎 Доказательства: {scam_data['proof_link']}\n"
                    f"📝 Причина: {scam_data['reason']}\n"
                    f"🎉 Теперь у вас {new_count} слитых скаммеров!"
                )
            else:
                await bot.send_message(
                    scam_data['user_id'],
                    f"✅ Скаммер {scam_data['scammer_name']} успешно занесён!\n"
                    f"🎯 Роль: {role_name}\n"
                    f"📎 Доказательства: {scam_data['proof_link']}\n"
                    f"📝 Причина: {scam_data['reason']}"
                )

            # Редактируем сообщение с выбором роли
            await event.edit(
                f"✅ **Скаммер занесён!**\n\n"
                f"👤 Скаммер: {scam_data['scammer_name']}\n"
                f"🎯 Роль: {role_name}\n"
                f"📎 Доказательства: {scam_data['proof_link']}\n"
                f"📝 Причина: {scam_data['reason']}",
                buttons=None
            )

            # Удаляем из временного хранилища
            if unique_id in TEMP_STORAGE:
                del TEMP_STORAGE[unique_id]

        else:
            await event.answer("❌ Ошибка при добавлении скаммера в базу", alert=True)

    except Exception as e:
        logging.error(f"Ошибка при добавлении скаммера: {e}")
        await event.answer("❌ Произошла ошибка при заносе", alert=True)


@bot.on(events.CallbackQuery(pattern=r'mark_(scammer|possible|rooster)_(\d+)_(.+)'))
async def mark_user_handler(event):
    logging.info(f"Обработчик вызван с данными: {event.pattern_match.groups()}")

    role_mapping = {
        'scammer': 3,
        'possible': 2,
        'rooster': 4
    }

    role_type = event.pattern_match.group(1)
    user_id = int(event.pattern_match.group(2))
    reason = event.pattern_match.group(3).strip()

    logging.info(f"Попытка изменить роль пользователя {user_id} на {role_type} с причиной: {reason}")

    # ПРОВЕРКА: является ли целевой пользователь персоналом?
    target_role = db.get_user_role(user_id)
    if target_role in STAFF_ROLES:
        target_role_name = ROLES.get(target_role, {}).get('name', 'Неизвестно')

        await event.answer(
            f"🚫 Нельзя заносить персонал базы!\n"
            f"👤 Роль: {target_role_name}\n"
            f"ℹ️ Персонал Forget AntiScam защищен от заноса.",
            alert=True
        )
        return

    # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: Уже ли пользователь имеет роль скаммера
    current_role = db.get_user_role(user_id)
    if current_role in [2, 3, 4]:  # Если уже имеет роль скаммера
        await event.answer("❌ Этот пользователь уже находится в базе!", alert=True)
        return

    # Получаем роль отправителя
    user_role = db.get_user_role(event.sender_id)
    logging.info(f"Роль пользователя {event.sender_id}: {user_role}")

    # Проверка прав для изменения роли
    if user_role not in [1, 6, 8, 10, 11, 9] and event.sender_id not in OWNER_ID:
        await event.answer("⛔ У вас нет прав лол.", alert=True)
        return

    if not reason:
        await event.answer("❌ Причина не может быть пустой!", alert=True)
        return

    # Обновление роли в базе данных
    db.update_role(user_id, role_mapping[role_type])

    # Увеличиваем количество слитых скаммеров для пользователя, который инициировал команду
    current_count = db.get_user_reported_scammers_count(event.sender_id)
    logging.info(f"Текущее количество слитых скаммеров для пользователя {event.sender_id}: {current_count}")

    scammers_slept = current_count + 1
    logging.info(f"Пользователь {event.sender_id} теперь должен иметь {scammers_slept} слитых скаммеров.")

    if not db.update_user_scammers_slept(event.sender_id, scammers_slept):
        logging.error(f"Не удалось обновить количество слитых скаммеров для пользователя {event.sender_id}.")
        await event.answer("Ошибка при обновлении количества слитых скаммеров.", alert=True)
        return

    logging.info(
        f"Количество слитых скаммеров для пользователя {event.sender_id} успешно обновлено на {scammers_slept}.")

    chat_id = event.chat_id
    await event.client.send_message(
        chat_id,
        message=f"🔥 Вы успешно занесли скаммера! | Скаммеров слито: {scammers_slept}"
    )




@bot.on(events.CallbackQuery(pattern=rb'sliv_scammers_(\d+)'))
async def sliv_scammers_handler(event):
    sender_id = event.sender_id

    try:
        # Сначала показываем окошко что инструкция отправлена в ЛС
        await event.answer("📨 Инструкции отправлены вам в личные сообщения", alert=True)

        # Ждём немного перед отправкой в ЛС
        await asyncio.sleep(0.5)

        # Отправляем ОДНО сообщение с инструкцией и кнопкой
        instruction_text = (
            f"чтобы слить скаммера, вам надо зайти в чат-слива скаммеров👇.\n\n"
            "просто скиньте в чат следующие данные:\n"
            "- все доказательства (фото, видео, сообщения)\n"
            "- айди или юзернейм скамера\n\n"
            "если вы сделали все это, и наши волонтеры занесут скаммера, то вам выдадут +спасибо"
        )

        keyboard = [[Button.url("предложка🔍", "https://t.me/Forget_base")]]

        # Отправляем одно сообщение с инструкцией и кнопкой
        await bot.send_message(
            sender_id,
            instruction_text,
            buttons=keyboard
        )

    except Exception as e:
        await event.answer("❌ Не удалось отправить сообщение. Пожалуйста, запустите бота", alert=True)
        logging.error(f"Ошибка отправки сообщения в ЛС: {e}")


@bot.on(events.NewMessage(pattern=r'(?i)^(/|\.)?(add) (@\w+) (.+)'))
async def add_reason_handler(event):
    """Обработчик для обновления описания заноса"""
    # Получаем роль отправителя
    user_role = db.get_user_role(event.sender_id)

    # Проверяем права (только админы/владельцы)
    if event.sender_id not in OWNER_ID and user_role not in [6, 8, 10, 11]:
        await event.reply("❌ Только администраторы могут использовать эту команду")
        return

    # Получаем целевого пользователя и текст нового описания
    target_username = event.pattern_match.group(3)  # Юзернейм
    new_description = event.pattern_match.group(4).strip()  # Новое описание

    # Проверка формата юзернейма
    if not target_username.startswith('@'):
        await event.reply("❌ Юзернейм должен начинаться с '@'.")
        return

    # Проверка, что новое описание не пустое
    if not new_description:
        await event.reply("❌ Описание не может быть пустым.")
        return

    # Логируем информацию о попытке получения пользователя
    logging.info(f"Попытка получить пользователя по юзернейму: {target_username}")

    try:
        target = await event.client.get_entity(target_username)
        logging.info(f"Пользователь найден: {target.first_name} (ID: {target.id})")
    except Exception as e:
        logging.error(f"Ошибка при получении пользователя {target_username}: {str(e)}")
        await event.reply("❌ Не могу найти указанного пользователя. Проверьте правильность юзернейма.")
        return

    # Логируем информацию о целевом пользователе и новом описании
    logging.info(
        f"Попытка обновления описания для пользователя {target.first_name} ({target.id}) с новым описанием: {new_description}")

    # Обновляем описание в базе данных
    try:
        # Обновляем описание (предполагается, что эта функция обновляет поле description)
        db.update_description(target.id, new_description)  # Убедитесь, что эта функция обновляет поле description
        logging.info(
            f"Описание для пользователя {target.first_name} ({target.id}) успешно обновлено на: {new_description}")
        await event.reply(
            f"✅ Описание для пользователя [{target.first_name}](tg://user/{target.id}) обновлено: {new_description}",
            parse_mode='md')
    except Exception as e:
        logging.error(f"Ошибка при обновлении описания для пользователя {target.id}: {str(e)}")
        await event.reply(f"❌ Произошла ошибка при обновлении описания: {str(e)}")


@bot.on(events.NewMessage(pattern=r'(?i)^(/add1) (@\w+) (.+)'))
async def add_additional_reason_handler(event):
    """Обработчик для добавления дополнительного описания"""
    # Получаем роль отправителя
    user_role = db.get_user_role(event.sender_id)

    # Проверяем права (только админы/владельцы)
    if event.sender_id not in OWNER_ID and user_role not in [6, 8, 10, 11]:
        await event.reply("❌ Только администраторы могут использовать эту команду")
        return

    # Получаем целевого пользователя и текст дополнительного описания
    target_username = event.pattern_match.group(2)
    additional_reason_text = event.pattern_match.group(3).strip()

    try:
        target = await event.client.get_entity(target_username)
    except Exception as e:
        await event.reply("❌ Не могу найти указанного пользователя")
        return

    # Добавляем дополнительное описание в базе данных
    db.add_additional_reason(target.id, additional_reason_text)

    await event.reply(
        f"✅ Дополнительное описание для пользователя [{target.first_name}](tg://user/{target.id}) добавлено: {additional_reason_text}",
        parse_mode='md')


@bot.on(events.NewMessage(pattern=r'/траст|!trust'))
async def trust_command(event):
    sender = await event.get_sender()

    # Проверка роли: разрешено гарантам и создателям
    if db.get_user_role(sender.id) not in [1, 10]:
        await event.reply(
            "**⚠️ Отказано в доступе!**\n\n"
            f"**👤 Пользователь:** [{sender.first_name}](tg://user/{sender.id})\n"
            "**📛 Причина:** Недостаточно прав\n"
            "**ℹ️ Информация:** Выдавать траст могут только гаранты и создатель\n"
            "[⠀](https://i.ibb.co/rGBBGyng/photo-2025-04-17-17-44-20.jpg)",
            parse_mode='md',
            link_preview=True
        )
        return

    # Получаем целевого пользователя
    target = await get_target_user(event)
    if not target:
        return

    # Получаем ID гаранта (того, кто выдает роль)
    granted_by_username = sender.username if sender.username else f"ID: {sender.id}"

    # Проверяем, является ли целевой пользователь владельцем, кодером, стажером, гарантом, президентом, админом или директором
    target_role = db.get_user_role(target.id)
    if target_role in [6, 7, 8, 9, 10, 11, 12]:
        await event.reply(
            "**❌ Ошибка!**\n\n"
            "**📛 Причина:** Нельзя выдавать траст владельцу, кодеру, стажеру, гаранту, президенту, админу или директору.\n"
            f"**📝 Текущая роль:** {ROLES.get(target_role, {}).get('name', 'Неизвестно')}"
        )
        return

    try:
        # Проверяем, есть ли пользователь в базе
        if not db.get_user(target.id):
            # Добавляем пользователя если его нет
            db.add_user(target.id, target.username if hasattr(target, 'username') else target.first_name)

        # Устанавливаем роль "Проверен гарантом" (роль 12)
        success = db.update_role(target.id, 12, granted_by_id=sender.id)

        if not success:
            await event.reply("❌ Ошибка при обновлении роли в базе данных")
            return

        # Сохраняем информацию о трасте в таблицу trust
        db.add_grant(target.id, sender.id)

        # Отправляем сообщение об успешной выдаче траста
        await event.reply(
            f"**✅ Траст успешно выдан!**\n\n"
            f"**👤 Получатель:** [{target.first_name if hasattr(target, 'first_name') else target.title}](tg://user/{target.id})\n"
            f"**👮 Выдал:** [{sender.first_name}](tg://user/{sender.id})\n"
            f"💙 Репутация: Проверен(а) гарантом {granted_by_username} ✅",
            parse_mode='md'
        )

        # Логируем
        logging.info(f"Траст выдан: {target.id} -> {sender.id}")

    except Exception as e:
        await event.reply(f"**❌ Ошибка:** `{str(e)}`")
        logging.error(f"Ошибка выдачи траста: {e}")


async def get_target_user(event):
    if event.is_reply:
        replied = await event.get_reply_message()
        return await event.client.get_entity(replied.sender_id)
    else:
        args = event.raw_text.split()
        if len(args) < 2:
            await event.reply(
                "**❌ Ошибка использования команды!**\n\n"
                "**✏️ Правильное использование:**\n"
                "• `/trust` (ответом на сообщение)\n"
                "• `/trust @username`\n"
                "• `/trust ID`",
                parse_mode='md'
            )
            return None
        try:
            return await event.client.get_entity(args[1])
        except:
            await event.reply(
                "**❌ Ошибка!**\n\n"
                "**📛 Причина:** Не удалось найти пользователя\n"
                "**💡 Совет:** Проверьте правильность указанного юзернейма/ID",
                parse_mode='md'
            )
            return None




# Обработчик команды /untrust
@bot.on(events.NewMessage(pattern=r'/untrust|/антраст|-антраст'))
async def untrust_command(event):
    sender = await event.get_sender()

    # Проверяем права (гарант, создатель, владельцы или кодер)
    sender_role = db.get_user_role(sender.id)
    if sender_role != 1 and sender.id not in OWNER_ID and sender_role not in [10, 11]:
        await event.reply(
            "**⚠️ Отказано!**\n\n"
            f"**👤 Пользователь:** [{sender.first_name}](tg://user/{sender.id})\n"
            "**📛 Причина:** У тя прав нету пон?\n"
            "**ℹ️ Информация:** Снимать траст могут только гаранты, создатель и владельцы\n"
            "[⠀](https://i.ibb.co/rGBBGyng/photo-2025-04-17-17-44-20.jpg)",
            parse_mode='md',
            link_preview=True
        )
        return

    # Получаем целевого пользователя
    if event.is_reply:
        replied = await event.get_reply_message()
        target = await event.client.get_entity(replied.sender_id)
    else:
        args = event.raw_text.split()
        if len(args) < 2:
            await event.reply(
                "**❌ Ошибка использования команды!**\n\n"
                "**✏️ Правильное использование:**\n"
                "• `/untrust` (ответом на сообщение)\n"
                "• `/untrust @username`\n"
                "• `/untrust ID`",
                parse_mode='md'
            )
            return

        try:
            target = await event.client.get_entity(args[1])
        except:
            await event.reply(
                "**❌ ну, ошибочка вышла):**\n\n"
                "**📛 Причина:** Не удалось найти пользователя\n"
                "**💡 Совет:** Дебик, правильно ник введи или айди, заебали уже честно.",
                parse_mode='md'
            )
            return

    # Проверяем, есть ли у пользователя траст
    if db.get_user_role(target.id) != 12:
        await event.reply(
            "**❌ Ну не плач только ошибочка получилась**\n\n"
            "**📛 Причина:** Его нет в базе даун..",
            parse_mode='md'
        )
        return

    # Снимаем траст (устанавливаем стандартную роль)
    await db.update_role(target.id, 0)

    await event.reply(
        "**✅ Траст успешно снят!, плаки плаки ):**\n\n"
        f"**👤 Пользователь:** [{target.first_name}](tg://user/{target.id})\n"
        f"**👮 Снял:** [{sender.first_name}](tg://user/{sender.id})",
        parse_mode='md'
    )


# Команда /гаранты
@bot.on(events.NewMessage(pattern='/гаранты'))
async def list_online_garants(event):
    await event.respond("Ищу онлайн гарантов...")

    # Получаем всех гарантов из базы (роль 1)
    try:
        garants = [row[0] for row in db.cursor.execute('SELECT user_id FROM users WHERE role_id = 1')]
        logging.info(f"Найдено {len(garants)} гарантов с ролью 1.")
    except Exception as e:
        logging.error(f"Ошибка при получении гарантов из базы: {e}")
        await event.respond("Не удалось получить список гарантов из базы данных.")
        return

    online_garants = []

    for uid in garants:
        try:
            user = await bot.get_entity(uid)
            logging.info(f"Проверяем пользователя: {user.id}, Имя: {user.first_name}, Статус: {user.status}")

            # Проверяем статус пользователя
            if user.status is None:
                online_garants.append(user)
                logging.info(f"Пользователь {user.first_name} ({user.id}) онлайн (нет статуса).")
            elif user.status == "online":
                online_garants.append(user)
                logging.info(f"Пользователь {user.first_name} ({user.id}) онлайн.")
            elif isinstance(user.status, UserStatusRecently):
                # Учитываем пользователей с состоянием Recently как онлайн
                online_garants.append(user)
                logging.info(f"Пользователь {user.first_name} ({user.id}) был в сети недавно.")
            else:
                logging.info(f"Пользователь {user.first_name} ({user.id}) не онлайн. Статус: {user.status}")
        except Exception as e:
            logging.error(f"Ошибка при получении пользователя {uid}: {e}")
            continue

    if not online_garants:
        await event.respond("На данный момент онлайн гарантов нет ⛔")
        logging.info("Нет онлайн гарантов.")
        return

    # Формируем текст ответа
    text = "📊 Вот наш список онлайн гарантов:\n"
    buttons = []

    for user in online_garants:
        buttons.append([Button.inline(f"🛡️ {user.first_name}", f"check_{user.id}")])

    await event.respond(text, buttons=buttons, parse_mode='markdown', link_preview=True)
    logging.info("Список онлайн гарантов успешно отправлен.")




@bot.on(events.CallbackQuery(pattern=r'staff_stats_(\d+)'))
async def staff_stats_handler(event):
    staff_id = int(event.pattern_match.group(1))
    try:
        row = db.cursor.execute(
            "SELECT user_id, username, role_id, COALESCE(scammers_count,0), COALESCE(check_count,0), COALESCE(warnings,0) FROM users WHERE user_id = ?",
            (staff_id,)
        ).fetchone()
        if not row:
            await event.answer("❌ Пользователь не найден.", alert=True)
            return
        uid, username, role_id, scammers_count, check_count, warnings = row
        role_name = ROLES.get(role_id, {}).get('name', 'Неизвестная роль')
        real_count = db.cursor.execute('SELECT COUNT(*) FROM scammers WHERE reporter_id = ?', (uid,)).fetchone()[0] or 0
        total = max(scammers_count or 0, real_count)
        text = (
            f"👤 **Статистика персонала**\n\n"
            f"Имя: **{username or uid}**\n"
            f"ID: `{uid}`\n"
            f"Роль: **{role_name}**\n\n"
            f"🔪 Занесено скамеров: **{total}**\n"
            f"🔍 Проверок: **{check_count or 0}**\n"
            f"⚠️ Выговоров: **{warnings or 0}**"
        )
        await event.edit(text, buttons=[[Button.inline("👤 Профиль", f"check_{uid}"), Button.inline("📊 Назад", b"return_to_stats")]], parse_mode='md')
        await event.answer()
    except Exception as e:
        logging.error(f"Ошибка staff_stats_handler: {e}")
        await event.answer("❌ Не удалось загрузить статистику.", alert=True)


@bot.on(events.CallbackQuery(pattern=r'role_stats_(\d+)'))
async def role_stats_handler(event):
    role_id = int(event.pattern_match.group(1))
    try:
        role = ROLES.get(role_id)
        if not role:
            await event.answer("❌ Роль не найдена.", alert=True)
            return
        count = db.cursor.execute('SELECT COUNT(*) FROM users WHERE role_id = ?', (role_id,)).fetchone()[0] or 0
        total = db.cursor.execute('SELECT COALESCE(SUM(scammers_count),0) FROM users WHERE role_id = ?', (role_id,)).fetchone()[0] or 0
        text = f"{role['name']}\n\n👥 Пользователей: **{count}**\n🔪 Всего заносов: **{total}**"
        await event.edit(text, buttons=[[Button.inline("📊 Общая статистика", b"general_stats")]], parse_mode='md')
        await event.answer()
    except Exception as e:
        logging.error(f"Ошибка role_stats_handler: {e}")
        await event.answer("❌ Не удалось загрузить статистику роли.", alert=True)


@bot.on(events.CallbackQuery(data=b"refresh_stats"))
async def refresh_stats_handler(event):
    try:
        await event.delete()
    except Exception:
        pass
    await statistics(event)


@bot.on(events.CallbackQuery(data=b"general_stats"))
async def general_stats_handler(event):
    try:
        await event.delete()
    except Exception:
        pass
    await statistics(event)


@bot.on(events.CallbackQuery(data=b"refresh_fullstats"))
async def refresh_fullstats_handler(event):
    try:
        await event.delete()
    except Exception:
        pass
    await full_statistics(event)


@bot.on(events.CallbackQuery(data=b"all_users_stats"))
async def all_users_stats_handler(event):
    try:
        rows = db.cursor.execute(
            'SELECT user_id, username, role_id, COALESCE(check_count,0) FROM users ORDER BY check_count DESC, user_id ASC LIMIT 30'
        ).fetchall()
        text = "👥 **Пользователи базы (топ 30 по проверкам)**\n\n"
        buttons = []
        for uid, username, role_id, checks in rows:
            name = (username or f"ID:{uid}")[:24]
            role = ROLES.get(role_id, {}).get('name', 'Неизвестно')
            text += f"• **{name}** — {role} — 🔍 {checks}\n"
            buttons.append([Button.inline(f"👤 {name}", f"check_{uid}")])
        if not rows:
            text += "Нет пользователей."
        buttons.append([Button.inline("📊 Общая статистика", b"general_stats")])
        await event.edit(text[:4096], buttons=buttons, parse_mode='md')
        await event.answer()
    except Exception as e:
        logging.error(f"Ошибка all_users_stats_handler: {e}")
        await event.answer("❌ Не удалось загрузить пользователей.", alert=True)


@bot.on(events.CallbackQuery(data=b"top_admins"))
async def top_admins_handler(event):
    """Топ админов по слитым скамерам"""
    try:
        await bot.delete_messages(event.chat_id, event.message_id)
    except:
        pass

    # Получаем топ админов
    top_admins = db.cursor.execute('''
        SELECT u.user_id, u.username, u.scammers_count, u.role_id,
               (SELECT COUNT(*) FROM scammers WHERE reporter_id = u.user_id) as real_scammers
        FROM users u 
        WHERE u.role_id IN (7, 8, 9, 10, 11, 13) 
        AND COALESCE(scammers_count, 0) > 0
        ORDER BY COALESCE(scammers_count, 0) DESC 
        LIMIT 10
    ''').fetchall()

    if not top_admins:
        text = """👮 **ТОП АДМИНИСТРАЦИИ**
━━━━━━━━━━━━━━━━━━━━


📭 **Администраторы пока не занесли скамеров**

👮 Администрация базы Forget AntiScam
🔪 Заносите скамеров и подавайте пример!
🎯 Ваши заносы вдохновляют стажёров

━━━━━━━━━━━━━━━━━━━━
"""
        buttons = [
            [Button.inline("🔄 Обновить", b"top_admins")],
            [Button.inline("🏆 Топ Стажёров", b"top_trainees")],
            [Button.inline("📊 Назад к статистике", b"return_to_stats")]
        ]

        msg = await event.respond(text, parse_mode='md', link_preview=True, buttons=buttons)
        return

    text = f"""👮 **ТОП-{len(top_admins)} АДМИНИСТРАЦИИ**
━━━━━━━━━━━━━━━━━━━━


🏆 **Топ администраторов по заносам:**
━━━━━━━━━━━━━━━━━━━━
"""

    buttons = []

    for i, (user_id, username, scammers_count, role_id, real_scammers) in enumerate(top_admins, 1):
        # Медальки
        if i == 1:
            medal = "👑"
        elif i == 2:
            medal = "🥈"
        elif i == 3:
            medal = "🥉"
        else:
            medal = f"{i}."

        # Имя для отображения
        if username:
            display_name = f"@{username}" if not username.startswith('@') else username
        else:
            display_name = f"ID:{user_id}"

        if len(display_name) > 18:
            display_name = display_name[:15] + "..."

        # Роль
        role_name = ROLES.get(role_id, {}).get('name', 'Админ')
        role_emoji = get_role_emoji(role_id)

        # Количество
        final_count = max(scammers_count or 0, real_scammers or 0)

        text += f"{medal} **{display_name}** ({role_emoji}{role_name}) - `{final_count}`🔪\n"

        # Кнопка
        if i <= 5:
            button_text = f"{role_emoji} {display_name} - {final_count}🔪"
            if len(button_text) > 20:
                display_short = display_name[:8] + ".." if len(display_name) > 8 else display_name
                button_text = f"{role_emoji} {display_short} - {final_count}🔪"

            buttons.append([Button.inline(button_text, f"admin_stats_{user_id}")])

    # Статистика
    total_scammers = sum(max(row[2] or 0, row[4] or 0) for row in top_admins)
    avg_scammers = total_scammers / len(top_admins) if top_admins else 0

    text += f"""
━━━━━━━━━━━━━━━━━━━━
📊 **СТАТИСТИКА:**
• Всего заносов админов: `{total_scammers}`
• В среднем на админа: `{avg_scammers:.1f}`
• Админов в топе: `{len(top_admins)}`

👮 **Администрация ведёт за собой!**
• Подавайте пример стажёрам
• Активно работайте со скамерами
• Поддерживайте порядок в базе

━━━━━━━━━━━━━━━━━━━━
"""

    # Кнопки
    nav_buttons = [
        [Button.inline("🔄 Обновить", b"top_admins")],
        [Button.inline("🏆 Топ Стажёров", b"top_trainees")],
        [Button.inline("📊 Общая статистика", b"return_to_stats")]
    ]

    if buttons:
        paired_buttons = []
        for i in range(0, len(buttons), 2):
            if i + 1 < len(buttons):
                paired_buttons.append([buttons[i][0], buttons[i + 1][0]])
            else:
                paired_buttons.append([buttons[i][0]])

        for nav_row in nav_buttons:
            paired_buttons.append(nav_row)

        buttons = paired_buttons
    else:
        buttons = nav_buttons

    msg = await event.respond(text, parse_mode='md', link_preview=True, buttons=buttons)


@bot.on(events.CallbackQuery(pattern=r'admin_stats_(\d+)'))
async def admin_stats_handler(event):
    admin_id = int(event.pattern_match.group(1))
    try:
        row = db.cursor.execute(
            "SELECT user_id, username, role_id, COALESCE(scammers_count,0), COALESCE(check_count,0), COALESCE(warnings,0) FROM users WHERE user_id = ?",
            (admin_id,)
        ).fetchone()
        if not row:
            await event.answer("❌ Пользователь не найден.", alert=True)
            return
        uid, username, role_id, scammers_count, check_count, warnings = row
        role_name = ROLES.get(role_id, {}).get('name', 'Неизвестно')
        real_count = db.cursor.execute('SELECT COUNT(*) FROM scammers WHERE reporter_id = ?', (uid,)).fetchone()[0] or 0
        total = max(scammers_count or 0, real_count)
        text = (
            f"👤 **Статистика персонала**\n\n"
            f"Имя: **{username or uid}**\n"
            f"ID: `{uid}`\n"
            f"Роль: **{role_name}**\n\n"
            f"🔪 Занесено скамеров: **{total}**\n"
            f"🔍 Проверок: **{check_count or 0}**\n"
            f"⚠️ Выговоров: **{warnings or 0}**"
        )
        await event.edit(text, buttons=[
            [Button.inline("🔄 Обновить", f"admin_stats_{uid}"), Button.inline("📊 Назад", b"return_to_stats")]
        ], parse_mode='md')
        await event.answer()
    except Exception as e:
        logging.error(f"Ошибка admin_stats: {e}")
        await event.answer("❌ Не удалось загрузить статистику.", alert=True)

@bot.on(events.CallbackQuery(pattern=rb'trainee_stats_(\d+)'))
async def trainee_stats_handler(event):
    """Статистика конкретного стажера"""
    trainee_id = int(event.pattern_match.group(1))

    try:
        # Получаем данные стажера
        db.cursor.execute('''
            SELECT u.user_id, u.username, u.scammers_count, u.check_count, 
                   u.warnings, u.curator_id,
                   (SELECT COUNT(*) FROM scammers WHERE reporter_id = u.user_id) as real_scammers,
                   (SELECT COUNT(*) FROM scammers WHERE reported_by LIKE '%' || u.username || '%') as by_name
            FROM users u 
            WHERE u.user_id = ? AND u.role_id = 6
        ''', (trainee_id,))

        trainee_data = db.cursor.fetchone()

        if not trainee_data:
            await event.answer("❌ Стажёр не найден", alert=True)
            return

        (user_id, username, scammers_count, check_count,
         warnings, curator_id, real_scammers, by_name) = trainee_data

        # Имя для отображения
        display_name = username or f"ID:{user_id}"

        # Куратор
        curator_name = "Не назначен"
        if curator_id:
            db.cursor.execute('SELECT username FROM users WHERE user_id = ?', (curator_id,))
            curator_data = db.cursor.fetchone()
            if curator_data and curator_data[0]:
                curator_name = curator_data[0]

        # Общее количество
        total_scammers = max(scammers_count or 0, real_scammers or 0, by_name or 0)

        # Получаем последние заносы
        db.cursor.execute('''
            SELECT scammer_id, reason, added_date 
            FROM scammers 
            WHERE reporter_id = ? OR reported_by LIKE '%' || ? || '%'
            ORDER BY added_date DESC 
            LIMIT 5
        ''', (user_id, username or str(user_id)))

        last_scams = db.cursor.fetchall()

        # Формируем текст
        text = f"""👨‍🎓 **СТАТИСТИКА СТАЖЁРА**
━━━━━━━━━━━━━━━━━━━━


**👤 Имя:** {display_name}
**🆔 ID:** `{user_id}`

📊 **ПОКАЗАТЕЛИ:**
• 🔪 Слито скамеров: `{total_scammers}`
• 📝 В поле scammers_count: `{scammers_count or 0}`
• 🎯 Реально занесено: `{real_scammers or 0}`
• 🔍 Проверок: `{check_count or 0}`
• ⚠️ Выговоры: `{warnings or 0}`
• 👨‍🏫 Куратор: {curator_name}

"""

        if last_scams:
            text += "📋 **ПОСЛЕДНИЕ ЗАНОСЫ:**\n"
            for scam_id, reason, date in last_scams:
                # Форматируем дату
                try:
                    date_str = date[:10] if date else "Неизвестно"
                except:
                    date_str = "Неизвестно"

                # Сокращаем причину
                short_reason = reason[:30] + "..." if len(reason) > 30 else reason
                text += f"• `{scam_id}` - {short_reason} ({date_str})\n"

        text += """
━━━━━━━━━━━━━━━━━━━━
🎯 **СОВЕТЫ ДЛЯ РОСТА:**
• Активно ищите скамеров в чатах
• Всегда предоставляйте пруфы
• Следуйте инструкциям куратора
• Избегайте выговоров

━━━━━━━━━━━━━━━━━━━━
"""

        # Кнопки
        buttons = [
            [Button.inline("🔄 Обновить", f"trainee_stats_{trainee_id}")],
            [Button.inline("🏆 Назад к топу", b"top_trainees")],
            [Button.inline("📊 Общая статистика", b"return_to_stats")],
            [Button.inline("👤 Профиль", f"check_{trainee_id}")]
        ]

        await event.edit(text, buttons=buttons, parse_mode='md', link_preview=True)

    except Exception as e:
        logging.error(f"Ошибка в trainee_stats_handler: {e}")
        await event.answer("❌ Ошибка загрузки", alert=True)


# Глобальная переменная для хранения ID последнего сообщения с топом
last_top_message = {}


@bot.on(events.CallbackQuery(data=b"top_trainees"))
async def top_trainees_handler(event):
    """Топ стажеров по слитым скамерам с защитой от дублирования"""
    user_id = event.sender_id
    chat_id = event.chat_id

    try:
        # Проверяем, не обрабатывается ли уже запрос
        if user_id in last_top_message and time.time() - last_top_message[user_id].get('timestamp', 0) < 2:
            await event.answer("⏳ Подождите, загрузка уже идет...", alert=False)
            return

        # Сохраняем время запроса
        last_top_message[user_id] = {
            'timestamp': time.time(),
            'chat_id': chat_id
        }

        # Удаляем предыдущее сообщение если оно есть в этом же чате
        if user_id in last_top_message and 'message_id' in last_top_message[user_id]:
            try:
                await bot.delete_messages(chat_id, last_top_message[user_id]['message_id'])
            except:
                pass

        # Удаляем сообщение с кнопкой (если возможно)
        try:
            await event.delete()
        except:
            pass

        # Получаем топ стажеров
        top_trainees = db.cursor.execute('''
            SELECT u.user_id, u.username, u.scammers_count, 
                   u.check_count, u.warnings,
                   (SELECT COUNT(*) FROM scammers WHERE reporter_id = u.user_id) as real_scammers
            FROM users u 
            WHERE u.role_id = 6 
            ORDER BY COALESCE(scammers_count, 0) DESC 
            LIMIT 15
        ''').fetchall()

        if not top_trainees:
            text = """🏆 **ТОП СТАЖЁРОВ**
━━━━━━━━━━━━━━━━━━━━


📭 **Список стажёров пока пуст!**

👨‍🎓 Станьте первым в этом топе!
🔪 Заносите скамеров через /скам
🎯 Получайте +спасибо от персонала

━━━━━━━━━━━━━━━━━━━━
"""
            buttons = [
                [Button.inline("🔄 Обновить", b"top_trainees")],
                [Button.inline("📊 Назад к статистике", b"return_to_stats")],
                [Button.url("📚 Как стать стажёром?", "https://t.me/Forget_base")]
            ]

            msg = await event.respond(text, parse_mode='md', link_preview=True, buttons=buttons)
            last_top_message[user_id]['message_id'] = msg.id
            return

        # Формируем текст
        text = f"""🏆 **ТОП-{len(top_trainees)} СТАЖЁРОВ**
━━━━━━━━━━━━━━━━━━━━


👑 **Топ по количеству слитых скамеров:**
━━━━━━━━━━━━━━━━━━━━
"""

        buttons = []

        for i, (user_id_trainee, username, scammers_count, check_count, warnings, real_scammers) in enumerate(
                top_trainees, 1):
            if i == 1:
                medal = "🥇"
            elif i == 2:
                medal = "🥈"
            elif i == 3:
                medal = "🥉"
            else:
                medal = f"{i}."

            display_name = f"@{username}" if username else f"ID:{user_id_trainee}"
            if len(display_name) > 20:
                display_name = display_name[:17] + "..."

            final_count = max(scammers_count or 0, real_scammers or 0)
            text += f"{medal} **{display_name}** - `{final_count}`🔪\n"

            if i <= 5:
                if final_count >= 50:
                    knife_emoji = "🔪🔪🔪"
                elif final_count >= 20:
                    knife_emoji = "🔪🔪"
                elif final_count >= 10:
                    knife_emoji = "🔪"
                else:
                    knife_emoji = "🗡️"

                button_text = f"{medal} {display_name} {final_count}{knife_emoji}"
                if len(button_text) > 25:
                    display_short = display_name[:10] + ".." if len(display_name) > 10 else display_name
                    button_text = f"{medal} {display_short} {final_count}{knife_emoji}"

                buttons.append([Button.inline(button_text, f"trainee_stats_{user_id_trainee}")])

        # Статистика
        total_scammers = sum(max(row[2] or 0, row[5] or 0) for row in top_trainees)
        avg_scammers = total_scammers / len(top_trainees) if top_trainees else 0

        text += f"""
━━━━━━━━━━━━━━━━━━━━
📊 **СТАТИСТИКА ТОПА:**
• Всего скамеров в топе: `{total_scammers}`
• В среднем на стажёра: `{avg_scammers:.1f}`
• Стажёров в топе: `{len(top_trainees)}`

🎯 **Как попасть в топ?**
• Активно заносите скамеров через /скам
• Получайте +спасибо от персонала
• Не получайте выговоров

━━━━━━━━━━━━━━━━━━━━
"""

        # Кнопки
        nav_buttons = [
            [Button.inline("🔄 Обновить", b"top_trainees")],
            [Button.inline("📊 Общая статистика", b"return_to_stats")],
            [Button.inline("🏅 Топ Админов", b"top_admins")]
        ]

        if buttons:
            paired_buttons = []
            for i in range(0, len(buttons), 2):
                if i + 1 < len(buttons):
                    paired_buttons.append([buttons[i][0], buttons[i + 1][0]])
                else:
                    paired_buttons.append([buttons[i][0]])

            for nav_row in nav_buttons:
                paired_buttons.append(nav_row)

            buttons = paired_buttons
        else:
            buttons = nav_buttons

        buttons.append([Button.url("👨‍🎓 Чат стажёров", "https://t.me/Forget_base")])

        # Отправляем ОДНО сообщение
        msg = await event.respond(text, parse_mode='md', link_preview=True, buttons=buttons)

        # Сохраняем ID сообщения
        last_top_message[user_id]['message_id'] = msg.id

        # Отвечаем на callback чтобы убрать "часики"
        await event.answer()

    except Exception as e:
        logging.error(f"Ошибка в top_trainees_handler: {e}")
        await event.answer("❌ Ошибка загрузки", alert=True)


@bot.on(events.CallbackQuery(data=b"return_to_stats"))
async def return_to_stats_handler(event):
    """Вернуться к статистике с защитой от дублирования"""
    user_id = event.sender_id
    chat_id = event.chat_id

    try:
        # Защита от быстрых кликов
        if user_id in last_top_message and time.time() - last_top_message[user_id].get('timestamp', 0) < 2:
            await event.answer("⏳ Подождите...", alert=False)
            return

        last_top_message[user_id] = {
            'timestamp': time.time(),
            'chat_id': chat_id
        }

        # Удаляем текущее сообщение
        try:
            await event.delete()
        except:
            pass

        # Удаляем предыдущее сообщение топа если есть
        if user_id in last_top_message and 'message_id' in last_top_message[user_id]:
            try:
                await bot.delete_messages(chat_id, last_top_message[user_id]['message_id'])
                del last_top_message[user_id]['message_id']
            except:
                pass

        # Вызываем статистику через имитацию события
        from telethon import events

        # Создаем фейковое событие
        class FakeEvent:
            def __init__(self):
                self.is_private = True
                self.sender_id = user_id
                self.chat_id = chat_id
                self._respond_called = False

            async def respond(self, *args, **kwargs):
                if not self._respond_called:
                    self._respond_called = True
                    msg = await event.respond(*args, **kwargs)
                    last_top_message[user_id]['message_id'] = msg.id
                    return msg

        fake_event = FakeEvent()
        await statistics(fake_event)

        await event.answer()

    except Exception as e:
        logging.error(f"Ошибка в return_to_stats_handler: {e}")
        await event.answer("❌ Ошибка", alert=True)


# Функция для периодической очистки
async def cleanup_old_messages():
    """Очищает старые записи о сообщениях"""
    while True:
        await asyncio.sleep(3600)  # Каждый час
        current_time = time.time()
        to_remove = []

        for user_id, data in last_top_message.items():
            if current_time - data.get('timestamp', 0) > 7200:  # 2 часа
                to_remove.append(user_id)

        for user_id in to_remove:
            del last_top_message[user_id]

        if to_remove:
            logging.info(f"Очищено {len(to_remove)} старых записей сообщений")


# Добавьте в main() перед запуском бота:
bot.loop.create_task(cleanup_old_messages())


@bot.on(events.CallbackQuery(data=b"top_day"))
async def top_day_handler(event):
    try:
        await bot.delete_messages(event.chat_id, bot.stat_message_id)
    except Exception as e:
        print(f"Ошибка при удалении сообщения: {e}")

    try:
        # Проверяем существование таблицы messages
        db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
        if not db.cursor.fetchone():
            msg = await event.respond("⚠️ Таблица сообщений ещё не создана. Активность не отслеживается.",
                                      buttons=Button.inline("↩Скрыть", b"hide_message"))
            bot.last_message_id = msg.id
            return

        # ИСПРАВЛЕННЫЙ ЗАПРОС - используем message_id вместо id
        top_users = db.cursor.execute('''
            SELECT u.user_id, u.username, COUNT(m.message_id) as count
            FROM users u
            JOIN messages m ON u.user_id = m.user_id
            WHERE m.timestamp >= datetime('now', '-1 day')
            GROUP BY u.user_id
            ORDER BY count DESC
            LIMIT 10
        ''').fetchall()

        if not top_users:
            msg = await event.respond("📭 Пока нет активности за последние 24 часа!",
                                      buttons=Button.inline("↩Скрыть", b"hide_message"))
            bot.last_message_id = msg.id
            return

        response = "😎 Топ 10 активных пользователей за 24 часа:\n\n"
        for i, (user_id, username, count) in enumerate(top_users, 1):
            user_link = f"[{username or f'ID:{user_id}'}](tg://user?id={user_id})"
            response += f"{i}. {user_link} — ✉️ {count} сообщений\n"

        msg = await event.respond(response, buttons=Button.inline("↩Скрыть", b"hide_message"))
        bot.last_message_id = msg.id

    except sqlite3.Error as e:
        await event.respond(f"⚠️ Ошибка базы данных: {str(e)}", buttons=Button.inline("↩Скрыть", b"hide_message"))
    except Exception as e:
        await event.respond(f"⚠️ Произошла ошибка: {str(e)}", buttons=Button.inline("↩Скрыть", b"hide_message"))


@bot.on(events.NewMessage(pattern="🚫 Слить скаммера!"))
async def report_scammer(event):
    if not event.is_private:
        return  # Игнорируем, если не в ЛС

    user_id = event.sender_id

    # Проверка защиты от спама
    can_press, message = check_button_spam_protection(user_id)
    if not can_press:
        await event.respond(message)
        return

    # Показываем загрузку
    await show_button_loading(event, "меню слива скаммера")

    keyboard = types.KeyboardButtonUrl(text="🚨 Отправить жалобу", url="https://t.me/Forget_base")

    # Удаляем сообщение о загрузке если есть
    if user_id in button_loading_messages:
        try:
            await bot.delete_messages(event.chat_id, button_loading_messages[user_id])
            del button_loading_messages[user_id]
        except:
            pass

    await event.respond(
        """🔥 Вы хотите слить скаммера? 🔥

⚡️ Лучшее решение:
• Нажмите кнопку "🚨 Отправить жалобу"
• Наш персонал примет меры в течение некоторого времени, просто скиньте пруфы!

🔒 Как избежать скама?:
1. ✅ Всегда проверяйте пользователя через /check
2. ✅ Используйте только официальных гарантов
3. ✅ Требуйте подтверждающие скриншоты
4. ✅ При малейших сомнениях - отменяйте сделку

📛 Помните: 95% скама можно избежать, следуя этим правилам!
[⠀](https://i.ibb.co/bj4g7h3y/photo-2025-04-17-17-44-19-3.jpg)""",
        parse_mode='md',
        link_preview=True,
        buttons=keyboard
    )


@bot.on(events.NewMessage(pattern="✅ Гаранты базы"))
async def list_garants(event):
    if not event.is_private:
        return

    user_id = event.sender_id

    # Проверка защиты от спама
    can_press, message =  check_button_spam_protection(user_id)
    if not can_press:
        await event.respond(message)
        return

    # Показываем загрузку
    await show_button_loading(event, "список гарантов")

    # Получаем всех гарантов из базы
    try:
        garants = [row[0] for row in db.cursor.execute('SELECT user_id FROM users WHERE role_id = 1')]
    except Exception as e:
        # Удаляем сообщение о загрузке если есть
        if user_id in button_loading_messages:
            try:
                await bot.delete_messages(event.chat_id, button_loading_messages[user_id])
                del button_loading_messages[user_id]
            except:
                pass
        return

    if not garants:
        # Удаляем сообщение о загрузке если есть
        if user_id in button_loading_messages:
            try:
                await bot.delete_messages(event.chat_id, button_loading_messages[user_id])
                del button_loading_messages[user_id]
            except:
                pass
        await event.respond("На данный момент Гарантов нету ⛔")
        return

    # Формируем текст с актуальным списком
    text = f"""💢 Актуальный список гарантов Forget AntiScam
━━━━━━━━━━━━━━
• Всего: {len(garants)}
━━━━━━━━━━━━━━
💡 Если хотите стать гарантом, пройдите набор!
[⠀](https://i.ibb.co/rGBBGyng/photo-2025-04-17-17-44-20.jpg)"""

    buttons = []

    for uid in garants:
        try:
            user = await bot.get_entity(uid)
            buttons.append([Button.inline(f"🛡️ {user.first_name}", f"check_{uid}")])
        except Exception as e:
            print(f"Ошибка при получении данных пользователя {uid}: {e}")
            continue

    # Удаляем сообщение о загрузке если есть
    if user_id in button_loading_messages:
        try:
            await bot.delete_messages(event.chat_id, button_loading_messages[user_id])
            del button_loading_messages[user_id]
        except:
            pass

    await event.respond(text, buttons=buttons, parse_mode='md', link_preview=True)


@bot.on(events.NewMessage(pattern="👨‍🎓 Волонтёры базы"))
async def list_volunteers(event):
    if not event.is_private:
        return

    user_id = event.sender_id

    # Проверка защиты от спама
    can_press, message =  check_button_spam_protection(user_id)
    if not can_press:
        await event.respond(message)
        return

    # Показываем загрузку
    await show_button_loading(event, "список волонтёров")

    # Получаем всех волонтеров (роли 6-10)
    volunteers = []
    for role_id in [6, 7, 8, 9, 10, 13]:  # Добавлена роль 13 (Айдош)
        volunteers.extend(
            [row[0] for row in db.cursor.execute('SELECT user_id FROM users WHERE role_id = ?', (role_id,))])

    if not volunteers:
        # Удаляем сообщение о загрузке если есть
        if user_id in button_loading_messages:
            try:
                await bot.delete_messages(event.chat_id, button_loading_messages[user_id])
                del button_loading_messages[user_id]
            except:
                pass
        await event.respond("На данный момент Волонтёров нету ⛔")
        return

    # Формируем текст с актуальным списком
    text = f"""🤝 Актуальный список волонтёров Forget AntiScam
━━━━━━━━━━━━━━
• Всего: {len(volunteers)}
━━━━━━━━━━━━━━
💡 Если вы хотите стать волонтёром базы, просто пройдите набор!
[⠀](https://i.ibb.co/rGKnW46r/photo-2025-04-17-17-44-19.jpg)"""

    buttons = []

    for uid in volunteers:
        try:
            user = await bot.get_entity(uid)
            role_id = db.get_user_role(uid)
            role_name = ROLES[role_id]["name"]
            buttons.append([Button.inline(f"{role_name} {user.first_name}", f"check_{uid}")])
        except:
            continue

    # Удаляем сообщение о загрузке если есть
    if user_id in button_loading_messages:
        try:
            await bot.delete_messages(event.chat_id, button_loading_messages[user_id])
            del button_loading_messages[user_id]
        except:
            pass

    await event.respond(text, buttons=buttons, parse_mode='md', link_preview=True)


@bot.on(events.NewMessage(pattern="🔰 Проверенные пользователи"))
async def list_verified_users(event):
    if not event.is_private:
        return

    user_id = event.sender_id

    # Проверка защиты от спама
    can_press, message =  check_button_spam_protection(user_id)
    if not can_press:
        await event.respond(message)
        return

    # Показываем загрузку
    await show_button_loading(event, "проверенных пользователей")

    # Получаем всех проверенных пользователей (роль 12)
    verified_users = [row[0] for row in db.cursor.execute('SELECT user_id FROM users WHERE role_id = 12')]

    if not verified_users:
        # Удаляем сообщение о загрузке если есть
        if user_id in button_loading_messages:
            try:
                await bot.delete_messages(event.chat_id, button_loading_messages[user_id])
                del button_loading_messages[user_id]
            except:
                pass
        await event.respond("На данный момент проверенных пользователей нет ⛔")
        return

    text = "📊 Вот наш список проверенных пользователей:\n"
    buttons = []

    for uid in verified_users:
        try:
            user = await bot.get_entity(uid)
            buttons.append([Button.inline(f"✅ {user.first_name}", f"check_{uid}")])
        except:
            continue

    # Удаляем сообщение о загрузке если есть
    if user_id in button_loading_messages:
        try:
            await bot.delete_messages(event.chat_id, button_loading_messages[user_id])
            del button_loading_messages[user_id]
        except:
            pass

    await event.respond(text, buttons=buttons, parse_mode='md', link_preview=True)


@bot.on(events.NewMessage(pattern="🎭 Профиль"))
async def my_profile(event):
    if not event.is_private:
        await event.delete()
        return

    user_id = event.sender_id

    # Проверка защиты от спама
    can_press, message = check_button_spam_protection(user_id)
    if not can_press:
        await event.respond(message)
        return

    # Показываем загрузку
    await show_button_loading(event, "профиль")

    # Получаем user_id из события
    user_id = event.sender_id

    # Получаем данные пользователя из базы
    user = await event.get_sender()
    username = getattr(user, 'username', None) or getattr(user, 'first_name', None) or str(user_id)
    user_data = db.ensure_user(user_id, username, 0)
    if user_data is None:
        logging.error(f"Не удалось создать запись пользователя {user_id}")
        if user_id in button_loading_messages:
            try:
                await bot.delete_messages(event.chat_id, button_loading_messages[user_id])
                del button_loading_messages[user_id]
            except Exception:
                pass
        await event.respond("❌ Ошибка базы данных. Попробуйте ещё раз через несколько секунд.")
        return

    role_id = user_data[2] if user_data[2] in ROLES else 0
    role_info = ROLES[role_id]

    custom_photo = user_data[8] if user_data else None
    preview_url = custom_photo if custom_photo else role_info['preview_url']

    checks_count = db.get_check_count(user_id)

    # Определяем количество слитых скамеров
    scammers_slept = 0
    if role_id in [6, 7, 8, 9, 10, 13]:
        scammers_slept = \
            db.cursor.execute('SELECT COUNT(*) FROM scammers WHERE reporter_id = ?', (user_id,)).fetchone()[0]
    # Определяем текст кнопки для кастомного изображения
    custom_button_text = "🎆 Снять кастомное изображение" if custom_photo else "🎆 Установить кастомку"
    custom_callback_data = "remove_custom" if custom_photo else "custom_soon"

    profile_text = f"""
👤 **Профиль пользователя** [{user.first_name}](tg://user/{user_id})

📛 **Роль:** {role_info['name']}
🆔 **ID:** {user_id}[ ](https://i.ibb.co/SDkF5cSc/1000049441.jpg)
🔍 **Проверок:** {checks_count}
"""

    # Удаляем сообщение о загрузке если есть
    if user_id in button_loading_messages:
        try:
            await bot.delete_messages(event.chat_id, button_loading_messages[user_id])
            del button_loading_messages[user_id]
        except:
            pass

    profile_buttons = [
        [Button.inline("🔎 Проверить себя", "check_soon")],
        [Button.inline("🌍 Страна", "country_soon")]
    ]
    if can_manage_profile_features(user_id):
        profile_buttons[1].insert(0, Button.inline("📢 Канал", "channel_soon"))
        profile_buttons.append([Button.inline(custom_button_text, custom_callback_data)])

    await event.respond(
        profile_text,
        buttons=profile_buttons,
        parse_mode='md',
        link_preview=True
    )


# Обработчик команды /bt (показать кнопки)
@bot.on(events.NewMessage(pattern='/bt'))
async def show_buttons(event):
    # Проверяем права (только создатель, кодер или владельцы)
    user_id = event.sender_id
    user_role = db.get_user_role(user_id)

    if user_id not in OWNER_ID and user_role not in [10, 11]:
        await event.respond("❌ У вас нет прав для использования этой команды")
        return

    await event.respond(
        "Кнопки активированы ✅",
        buttons=main_buttons
    )


# Обработчик команды /unbt (убрать кнопки)
@bot.on(events.NewMessage(pattern='/unbt'))
async def remove_buttons(event):
    # Проверяем права (только создатель, кодер или владельцы)
    user_id = event.sender_id
    user_role = db.get_user_role(user_id)

    if user_id not in OWNER_ID and user_role not in [10, 11]:
        await event.respond("❌ У вас нет прав для использования этой команды")
        return

    await event.respond(
        "Кнопки деактивированы ✅",
        buttons=[]  # Пустой список кнопок
    )


@bot.on(events.NewMessage(pattern=r'(?i)^/оффтоп$'))
async def handle_offtopic_command(event):
    """Выдаёт стандартный 30-минутный мут за оффтоп без ссылки на отдельный чат."""
    if db.get_user_role(event.sender_id) not in MUTE_ALLOWED_ROLES and event.sender_id not in OWNER_ID:
        await event.respond("❌ У вас нет прав для использования этой команды.")
        return
    if not event.is_reply:
        await event.respond("❌ Ответьте на сообщение пользователя, которому нужно выдать мут.")
        return
    replied = await event.get_reply_message()
    target_user = await event.client.get_entity(replied.sender_id)
    try:
        expiry_timestamp = int(time.time() + 30 * 60)
        await bot.edit_permissions(
            event.chat_id, target_user.id,
            until_date=expiry_timestamp,
            send_messages=False,
            send_media=False,
            send_stickers=False,
            send_gifs=False,
            send_games=False,
            send_inline=False
        )
        muted_users[(event.chat_id, target_user.id)] = expiry_timestamp
        await event.respond(f"📛 {target_user.first_name} выдан мут на 30 минут.\nПричина: Оффтоп")
        try:
            await replied.delete()
        except Exception:
            pass
    except Exception as e:
        await event.respond(f"❌ Не могу выдать мут: {e}")


# Обработчик сообщений для проверки мута
@bot.on(events.NewMessage())
async def check_message(event):
    user_id = event.sender_id
    mute_key = (event.chat_id, user_id)
    expiry_time = muted_users.get(mute_key)
    if expiry_time is not None:
        if time.time() < expiry_time:
            try:
                await event.delete()
            except Exception:
                pass
            return
        muted_users.pop(mute_key, None)


joined_users_cache = set()


@bot.on(events.ChatAction)
async def handle_chat_join(event):
    if not (event.user_joined or event.user_added):
        return  # Не обрабатываем другие действия

    user = await event.get_user()
    user_id = user.id

    # Исключаем ботов
    if user.bot:
        return

    # Кэш от повторов
    if user_id in joined_users_cache:
        return
    joined_users_cache.add(user_id)
    asyncio.create_task(remove_from_cache_later(user_id))

    # УПРОЩЕННОЕ ПРИВЕТСТВИЕ ДЛЯ ВСЕХ РОЛЕЙ
    text = f"""
👋 Добро пожаловать! [{user.first_name}](tg://user?id={user.id})

[🤗]()
"""
    await event.respond(text, parse_mode='md', link_preview=True)


# Очистка кэша
async def remove_from_cache_later(user_id, delay=600):
    await asyncio.sleep(delay)
    joined_users_cache.discard(user_id)


# Обработчик кнопки "Добавить в группу"
@bot.on(events.CallbackQuery(pattern='add_group'))
async def add_group_handler(event):
    url = "https://t.me/ROBLOXpvsb_bot?startgroup=newgroup&admin=manage_chat+delete_messages+restrict_members+invite_users+restrict_members+change_info+pin_messages+manage_video_chats"
    keyboard = types.KeyboardButtonUrl(text="добавить в группу", url=url)
    await event.edit(
        "Нажмите кнопку ниже, чтобы добавить бота в группу:",
        buttons=keyboard
    )


# Обработчик кнопки "Пожаловаться на скамера"
@bot.on(events.CallbackQuery(pattern='report_scammer'))
async def report_handler(event):
    await event.respond(
        "Для того что бы пожаловатся на скамера вы должны перейти в наш [специальный чат](https://t.me/Forget_base)\nВам нужны пруфы и скрины переписок!")


# Обработчик кнопки "Создатель"
@bot.on(events.CallbackQuery(pattern='creator'))
async def creator_handler(event):
    user_id = event.original_update.user_id
    try:
        user = await bot.get_entity(user_id)
        username = user.username
        if username:
            user_info = f"@{username}"
        else:
            user_info = f"ID: {user_id}"
    except Exception as e:
        user_info = f"ID: {user_id} (не удалось получить имя)"

    await event.edit(f"{user_info}, вот информация:\nСоздатель - @half50k\nКодер - @MyNameIsLiner")


@bot.on(events.CallbackQuery(pattern='custom_soon'))
async def custom_soon_handler(event):
    user_id = event.sender_id
    if not can_manage_profile_features(user_id):
        await event.answer("❌ Кастомное изображение доступно только персоналу базы.", alert=True)
        return

    await event.respond("Отправьте изображение или видео")
    logger.info(f"User {user_id} initiated custom image/video upload.")

    @bot.on(events.NewMessage(from_users=user_id))
    async def media_handler(media_event):
        if not can_manage_profile_features(user_id):
            await media_event.reply("❌ У вас больше нет прав персонала для установки кастомного изображения.")
            bot.remove_event_handler(media_handler)
            return
        logger.info(f"User {user_id} sent a media message.")
        try:
            if not (media_event.photo or media_event.video):
                await media_event.reply("❌ Пожалуйста, отправьте изображение или видео.")
                return

            media_path = await bot.download_media(media_event.photo or media_event.video)
            if not media_path:
                await media_event.reply("❌ Не удалось скачать файл.")
                return

            try:
                if media_event.photo:
                    with open(media_path, "rb") as image_file:
                        response = requests.post(
                            "https://api.imgbb.com/1/upload",
                            params={"key": IMG_API_KEY},
                            files={"image": image_file},
                            timeout=30
                        )
                    response.raise_for_status()
                    data = response.json()
                    image_url = data.get("data", {}).get("url") if data.get("success") else None
                    if not image_url:
                        await media_event.reply("❌ Не удалось получить URL изображения.")
                        return

                    db.cursor.execute(
                        'UPDATE users SET custom_photo_url = ? WHERE user_id = ?',
                        (image_url, user_id)
                    )
                    db.conn.commit()
                    await media_event.reply("✅ Кастомное изображение успешно установлено в профиль!")
                    logger.info(f"Custom image set for user {user_id}: {image_url}")
                else:
                    await media_event.reply("❌ Видео для кастомного профиля временно недоступно. Отправьте изображение.")
            finally:
                try:
                    os.remove(media_path)
                except OSError:
                    pass
        except Exception as e:
            await media_event.reply(f"❌ Произошла ошибка: {e}")
            logger.error(f"Error while processing custom media for user {user_id}: {e}")
        finally:
            bot.remove_event_handler(media_handler)




async def back_to_profile_handler(event):
    user_id = event.sender_id
    try:
        user = await event.client.get_entity(user_id)
        username = getattr(user, 'username', None) or getattr(user, 'first_name', None) or str(user_id)
        user_data = db.ensure_user(user_id, username, 0)
        if not user_data:
            await event.answer("❌ Не удалось загрузить профиль.", alert=True)
            return
        message_text, buttons = await get_user_profile_response(event, user, user_data)
        await event.edit(message_text[:4096], buttons=buttons, parse_mode='md', link_preview=True)
    except Exception as e:
        logging.error(f"Ошибка возврата в профиль: {e}")
        await event.answer("❌ Не удалось обновить профиль.", alert=True)


@bot.on(events.CallbackQuery(pattern='remove_custom'))
async def remove_custom_handler(event):
    user_id = event.sender_id
    if not can_manage_profile_features(user_id):
        await event.answer("❌ Управление кастомным изображением доступно только персоналу базы.", alert=True)
        return
    db.cursor.execute('UPDATE users SET custom_photo_url = NULL WHERE user_id = ?', (user_id,))
    db.conn.commit()
    await event.answer("✅ Кастомное изображение успешно удалено.")
    await back_to_profile_handler(event)


@bot.on(events.CallbackQuery(pattern='channel_soon'))
async def channel_soon_handler(event):
    user_id = event.sender_id
    if not can_manage_profile_features(user_id):
        await event.answer("❌ Установка канала доступна только персоналу базы.", alert=True)
        return

    # Остальной код без изменений
    await event.respond("Отправьте username канала (например, @channelname)")

    @bot.on(events.NewMessage(from_users=user_id))
    async def channel_handler(channel_event):
        if not can_manage_profile_features(channel_event.sender_id):
            await channel_event.reply("❌ У вас больше нет прав персонала для установки канала.")
            bot.remove_event_handler(channel_handler)
            return
        channel_name = channel_event.text.strip()
        if not channel_name.startswith('@'):
            await channel_event.reply("❌ Имя канала должно начинаться с @")
        elif len(channel_name) > 32:
            await channel_event.reply("❌ Имя канала слишком длинное (макс. 32 символа)")
        else:
            db.update_user(channel_event.sender_id, channel=channel_name)
            await channel_event.reply(f"✅ Канал {channel_name} успешно сохранен!")
        bot.remove_event_handler(channel_handler)


# Обработчик кнопки "Страна"


@bot.on(events.CallbackQuery(pattern=r'check_(\d+)'))
async def check_profile_button_handler(event):
    """Показывает профиль пользователя из кнопок списков."""
    target_id = int(event.pattern_match.group(1))
    try:
        target = await event.client.get_entity(target_id)
        username = getattr(target, 'username', None) or getattr(target, 'first_name', None) or str(target_id)
        user_data = db.ensure_user(target_id, username, 0)
        if not user_data:
            await event.answer("❌ Не удалось загрузить пользователя.", alert=True)
            return
        message_text, buttons = await get_user_profile_response(event, target, user_data)
        await event.edit(message_text[:4096], buttons=buttons, parse_mode='md', link_preview=True)
        await event.answer()
    except Exception as e:
        logging.error(f"Ошибка кнопки профиля {target_id}: {e}")
        await event.answer("❌ Не удалось открыть профиль.", alert=True)


@bot.on(events.CallbackQuery(pattern='check_soon'))
async def check_self_button_handler(event):
    user_id = event.sender_id
    try:
        user = await event.client.get_entity(user_id)
        username = getattr(user, 'username', None) or getattr(user, 'first_name', None) or str(user_id)
        user_data = db.ensure_user(user_id, username, 0)
        if not user_data:
            await event.answer("❌ Не удалось загрузить ваш профиль.", alert=True)
            return
        message_text, buttons = await get_user_profile_response(event, user, user_data)
        await event.edit(message_text[:4096], buttons=buttons, parse_mode='md', link_preview=True)
        await event.answer()
    except Exception as e:
        logging.error(f"Ошибка кнопки проверки себя: {e}")
        await event.answer("❌ Не удалось открыть профиль.", alert=True)


@bot.on(events.CallbackQuery(pattern='country_soon'))
async def country_soon_handler(event):
    countries = [
        "США 🇺🇸", "Канада 🇨🇦", "Мексика 🇲🇽", "Бразилия 🇧🇷",
        "Аргентина 🇦🇷", "Великобритания 🇬🇧", "Франция 🇫🇷",
        "Германия 🇩🇪", "Италия 🇮🇹", "Испания 🇪🇸", "Китай 🇨🇳",
        "Япония 🇯🇵", "Австралия 🇦🇺", "Индия 🇮🇳", "Россия 🇷🇺",
        "Южноафриканская Республика 🇿🇦", "Египет 🇪🇬", "ОАЭ 🇦🇪",
        "Турция 🇹🇷", "Греция 🇬🇷", "Швеция 🇸🇪", "Норвегия 🇳🇴",
        "Финляндия 🇫🇮", "Дания 🇩🇰", "Польша 🇵🇱", "Чехия 🇨🇿",
        "Австрия 🇦🇹", "Швейцария 🇨🇭", "Нидерланды 🇳🇱", "Бельгия 🇧🇪",
        "Ирландия 🇮🇪", "Португалия 🇵🇹", "Румыния 🇷🇴", "Словакия 🇸🇰",
        "Словения 🇸🇮", "Хорватия 🇭🇷", "Латвия 🇱🇻", "Литва 🇱🇹",
        "Эстония 🇪🇪", "Мальта 🇲🇹", "Кипр 🇨🇾", "Исландия 🇮🇸",
        "Албания 🇦🇱", "Сербия 🇷🇸", "Босния и Герцеговина 🇧🇦",
        "Черногория 🇲🇪", "Македония 🇲🇰", "Косово 🇽🇰", "Беларусь 🇧🇾",
        "Украина 🇺🇦", "Грузия 🇬🇪", "Армения 🇦🇲", "Азербайджан 🇦🇿",
        "Казахстан 🇰🇿", "Узбекистан 🇺🇿", "Таджикистан 🇹🇯",
        "Туркменистан 🇹🇲", "Кыргызстан 🇰🇬", "Монголия 🇲🇳",
        "Иран 🇮🇷", "Ирак 🇮🇶", "Сирия 🇸🇾", "Ливан 🇱🇧",
        "Иордания 🇯🇴", "Катар 🇶🇦", "Бахрейн 🇧🇭", "Кувейт 🇰🇼",
        "Саудовская Аравия 🇸🇦", "Йемен 🇾🇪", "Вьетнам 🇻🇳"
    ]

    buttons = [Button.inline(country, f"set_country_{i}")
               for i, country in enumerate(countries)]

    # Создаём новое сообщение с кнопками выбора страны
    await event.respond(
        "🌍 Выберите страну, выбраная вами страна будет стоять у вас в профиле!",
        buttons=[buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    )


# Обработчик выбора страны
@bot.on(events.CallbackQuery(pattern=r'set_country_(\d+)'))
async def set_country_handler(event):
    country_idx = int(event.data.decode().split('_')[2])
    country = [
        "США 🇺🇸", "Канада 🇨🇦", "Мексика 🇲🇽", "Бразилия 🇧🇷",
        "Аргентина 🇦🇷", "Великобритания 🇬🇧", "Франция 🇫🇷",
        "Германия 🇩🇪", "Италия 🇮🇹", "Испания 🇪🇸", "Китай 🇨🇳",
        "Япония 🇯🇵", "Австралия 🇦🇺", "Индия 🇮🇳", "Россия 🇷🇺",
        "Южноафриканская Республика 🇿🇦", "Египет 🇪🇬", "ОАЭ 🇦🇪",
        "Турция 🇹🇷", "Греция 🇬🇷", "Швеция 🇸🇪", "Норвегия 🇳🇴",
        "Финляндия 🇫🇮", "Дания 🇩🇰", "Польша 🇵🇱", "Чехия 🇨🇿",
        "Австрия 🇦🇹", "Швейцария 🇨🇭", "Нидерланды 🇳🇱", "Бельгия 🇧🇪",
        "Ирландия 🇮🇪", "Португалия 🇵🇹", "Румыния 🇷🇴", "Словакия 🇸🇰",
        "Словения 🇸🇮", "Хорватия 🇭🇷", "Латвия 🇱🇻", "Литва 🇱🇹",
        "Эстония 🇪🇪", "Мальта 🇲🇹", "Кипр 🇨🇾", "Исландия 🇮🇸",
        "Албания 🇦🇱", "Сербия 🇷🇸", "Босния и Герцеговина 🇧🇦",
        "Черногория 🇲🇪", "Македония 🇲🇰", "Косово 🇽🇰", "Беларусь 🇧🇾",
        "Украина 🇺🇦", "Грузия 🇬🇪", "Армения 🇦🇲", "Азербайджан 🇦🇿",
        "Казахстан 🇰🇿", "Узбекистан 🇺🇿", "Таджикистан 🇹🇯",
        "Туркменистан 🇹🇲", "Кыргызстан 🇰🇬", "Монголия 🇲🇳",
        "Иран 🇮🇷", "Ирак 🇮🇶", "Сирия 🇸🇾", "Ливан 🇱🇧",
        "Иордания 🇯🇴", "Катар 🇶🇦", "Бахрейн 🇧🇭", "Кувейт 🇰🇼",
        "Саудовская Аравия 🇸🇦", "Йемен 🇾🇪", "Вьетнам 🇻🇳"
    ][country_idx]

    db.update_user(event.sender_id, country=country)

    # Создаём новое сообщение с подтверждением
    await event.respond(f"✅ Страна установлена: {country}")


def shutdown_handler(signal, frame):
    """Обработчик завершения работы бота"""
    logging.info("Завершение работы бота...")
    db.close()  # ТОЛЬКО ЗДЕСЬ закрываем БД
    sys.exit(0)


def main():
    print("Bot started...")
    bot.loop.create_task(cleanup_old_button_data())
    bot.run_until_disconnected()


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    logger.info("Бот запущен и готов к работе.")
    bot.run_until_disconnected()