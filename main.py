import os
import logging
import asyncio
import aiohttp
import io
import base64
import json
import time
import random
import sys
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, FSInputFile, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramAPIError
from aiogram.client.session.aiohttp import AiohttpSession

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"bot_{datetime.now().strftime('%Y-%m-%d')}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Получение токенов из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8151093657:AAFWVxK78kJ11eT1MhaO93WeK7Oxk-O0XGU")
DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY", "sp2xw8vhxJPehPnM0dmLRpX28OCOuoZ9")
STABILITY_API_KEY = os.getenv("STABILITY_API_KEY", "")  # Добавьте свой ключ Stability AI

# URL для API
DEEPINFRA_API_URL = "https://api.deepinfra.com/v1/openai/chat/completions"
STABILITY_TEXT_TO_IMAGE_URL = "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image"

# Заголовки для запросов к API DeepInfra
deepinfra_headers = {
    "Authorization": f"Bearer {DEEPINFRA_API_KEY}",
    "Content-Type": "application/json",
}

# Заголовки для запросов к API Stability
stability_headers = {
    "Authorization": f"Bearer {STABILITY_API_KEY}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# Максимальная длина сообщения в Telegram
MAX_MESSAGE_LENGTH = 4096
# Максимальная длина входящего сообщения
MAX_INPUT_LENGTH = 2000

# Константы для повторных попыток
MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1
MAX_RETRY_DELAY = 30
KEEP_ALIVE_INTERVAL = 10 * 60  # 10 минут

# Определение состояний для FSM
class BotStates(StatesGroup):
    waiting_for_image_prompt = State()

# Создание клавиатуры с кнопками
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🖼 Сгенерировать изображение")],
        [KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

session = AiohttpSession(proxy='http://proxy.server:3128') # в proxy указан прокси сервер pythonanywhere, он нужен для подключения
# Инициализация бота и диспетчера с хранилищем состояний
storage = MemoryStorage()
bot = Bot(token=TELEGRAM_TOKEN, session=session)
dp = Dispatcher(storage=storage)

# Переменная для отслеживания последней активности
last_activity_time = time.time()

# Функция для безопасной отправки сообщений с повторными попытками
async def safe_send_message(chat_id, text, reply_markup=None, retries=3):
    """Безопасная отправка сообщения с повторными попытками"""
    for attempt in range(retries):
        try:
            await bot.send_message(chat_id, text, reply_markup=reply_markup)
            return True
        except TelegramAPIError as e:
            logger.error(f"Ошибка при отправке сообщения (попытка {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(1)
            else:
                logger.error(f"Не удалось отправить сообщение после {retries} попыток")
                return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при отправке сообщения: {e}")
            return False

# Функция для безопасной отправки действия чата с повторными попытками
async def safe_send_chat_action(chat_id, action, retries=3):
    """Безопасная отправка действия чата с повторными попытками"""
    for attempt in range(retries):
        try:
            await bot.send_chat_action(chat_id, action)
            return True
        except TelegramAPIError as e:
            logger.error(f"Ошибка при отправке действия чата (попытка {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(1)
            else:
                return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при отправке действия чата: {e}")
            return False

@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    global last_activity_time
    last_activity_time = time.time()
    
    try:
        await message.answer(
            "Привет! Я бот, который использует API DeepInfra для генерации текстов и Stability AI для генерации изображений.\n\n"
            "Используйте кнопки меню или следующие команды:\n"
            "/help - Получить справку\n"
            "/image - Сгенерировать изображение по текстовому описанию",
            reply_markup=main_keyboard
        )
        logger.info(f"Пользователь {message.from_user.id} запустил бота")
    except TelegramAPIError as e:
        logger.error(f"Ошибка Telegram API при отправке приветствия: {e}")
        await safe_send_message(
            message.chat.id,
            "Произошла ошибка при отправке приветствия. Пожалуйста, попробуйте еще раз с помощью /start.",
            reply_markup=main_keyboard
        )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    global last_activity_time
    last_activity_time = time.time()
    
    try:
        await message.answer(
            "Доступные команды:\n"
            "/start - Начать работу с ботом\n"
            "/help - Показать эту справку\n"
            "/image - Сгенерировать изображение по текстовому описанию\n\n"
            "Вы также можете использовать кнопки меню для выбора действий.\n"
            "Просто напишите сообщение, чтобы получить ответ от ИИ.",
            reply_markup=main_keyboard
        )
        logger.info(f"Пользователь {message.from_user.id} запросил справку")
    except TelegramAPIError as e:
        logger.error(f"Ошибка Telegram API при отправке справки: {e}")
        await safe_send_message(
            message.chat.id,
            "Произошла ошибка при отправке справки. Пожалуйста, попробуйте еще раз.",
            reply_markup=main_keyboard
        )

@dp.message(F.text == "❓ Помощь")
async def button_help(message: Message):
    """Обработчик нажатия кнопки Помощь"""
    await cmd_help(message)

@dp.message(F.text == "🖼 Сгенерировать изображение")
async def button_generate_image(message: Message, state: FSMContext):
    """Обработчик нажатия кнопки Сгенерировать изображение"""
    await cmd_image(message, state)

@dp.message(Command("image"))
async def cmd_image(message: Message, state: FSMContext):
    """Обработчик команды /image"""
    global last_activity_time
    last_activity_time = time.time()
    
    try:
        await message.answer(
            "Опишите изображение, которое хотите сгенерировать:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="Отмена")]],
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )
        await state.set_state(BotStates.waiting_for_image_prompt)
        logger.info(f"Пользователь {message.from_user.id} запросил генерацию изображения")
    except TelegramAPIError as e:
        logger.error(f"Ошибка Telegram API при запросе генерации изображения: {e}")
        await safe_send_message(
            message.chat.id,
            "Произошла ошибка при обработке команды. Пожалуйста, попробуйте позже.",
            reply_markup=main_keyboard
        )

@dp.message(F.text == "Отмена", BotStates.waiting_for_image_prompt)
async def cancel_action(message: Message, state: FSMContext):
    """Обработчик отмены действия"""
    global last_activity_time
    last_activity_time = time.time()
    
    await state.clear()
    try:
        await message.answer("Действие отменено.", reply_markup=main_keyboard)
        logger.info(f"Пользователь {message.from_user.id} отменил действие")
    except TelegramAPIError as e:
        logger.error(f"Ошибка Telegram API при отмене действия: {e}")
        await safe_send_message(
            message.chat.id,
            "Действие отменено.",
            reply_markup=main_keyboard
        )

async def translate_to_english(text, retries=MAX_RETRIES):
    """Функция для перевода текста на английский с помощью DeepInfra с автоматическими повторными попытками"""
    # Подготовка данных для запроса к API DeepInfra
    data = {
        "model": "meta-llama/Meta-Llama-3-8B-Instruct",
        "messages": [
            {"role": "system", "content": "Ты переводчик с русского на английский. Переведи текст пользователя на английский язык. Дай только перевод без дополнительных комментариев."},
            {"role": "user", "content": text}
        ],
        "max_tokens": 500,
        "temperature": 0.3
    }
    
    retry_count = 0
    while retry_count < retries:
        try:
            # Асинхронная отправка запроса к API DeepInfra
            async with aiohttp.ClientSession() as session:
                async with session.post(DEEPINFRA_API_URL, headers=deepinfra_headers, json=data, timeout=30) as response:
                    if response.status == 200:
                        # Извлечение ответа из JSON
                        response_json = await response.json()
                        translation = response_json["choices"][0]["message"]["content"]
                        logger.info(f"Перевод успешно получен")
                        return translation
                    elif response.status == 429:  # Rate limit
                        retry_delay = min(INITIAL_RETRY_DELAY * (2 ** retry_count) + random.uniform(0, 1), MAX_RETRY_DELAY)
                        logger.warning(f"Превышен лимит запросов API (429). Повторная попытка через {retry_delay:.2f} сек.")
                        await asyncio.sleep(retry_delay)
                    else:
                        logger.error(f"Ошибка перевода: {response.status}")
                        error_text = await response.text()
                        logger.error(f"Детали ошибки: {error_text}")
                        
                        # Для некоторых ошибок нет смысла повторять запрос
                        if response.status in [400, 401, 403]:
                            return text
                        
                        # Для других ошибок делаем паузу и повторяем
                        retry_delay = min(INITIAL_RETRY_DELAY * (2 ** retry_count) + random.uniform(0, 1), MAX_RETRY_DELAY)
                        logger.info(f"Повторная попытка через {retry_delay:.2f} сек.")
                        await asyncio.sleep(retry_delay)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"Ошибка сети при переводе: {str(e)}")
            retry_delay = min(INITIAL_RETRY_DELAY * (2 ** retry_count) + random.uniform(0, 1), MAX_RETRY_DELAY)
            logger.info(f"Повторная попытка через {retry_delay:.2f} сек.")
            await asyncio.sleep(retry_delay)
        except Exception as e:
            logger.error(f"Неожиданная ошибка при переводе: {str(e)}")
            return text
            
        retry_count += 1
    
    logger.warning(f"Исчерпаны все попытки перевода. Возвращаем исходный текст.")
    return text  # Возвращаем исходный текст после всех неудачных попыток

@dp.message(BotStates.waiting_for_image_prompt)
async def process_image_prompt(message: Message, state: FSMContext):
    """Обработчик запроса на генерацию изображения"""
    global last_activity_time
    last_activity_time = time.time()
    
    prompt = message.text
    # Проверка длины запроса
    if len(prompt) > MAX_INPUT_LENGTH:
        try:
            await message.answer(
                f"Извините, ваш запрос слишком длинный. Максимальная длина: {MAX_INPUT_LENGTH} символов.",
                reply_markup=main_keyboard
            )
        except TelegramAPIError as e:
            logger.error(f"Ошибка Telegram API при отправке сообщения о превышении длины: {e}")
            await safe_send_message(
                message.chat.id,
                f"Извините, ваш запрос слишком длинный. Максимальная длина: {MAX_INPUT_LENGTH} символов.",
                reply_markup=main_keyboard
            )
        
        await state.clear()
        return
    
    # Сброс состояния
    await state.clear()
    
    # Отправка индикатора загрузки
    await safe_send_chat_action(message.chat.id, "typing")
    
    # Перевод запроса на английский язык
    try:
        await safe_send_message(
            message.chat.id,
            "Перевожу ваш запрос на английский для лучшей генерации изображения..."
        )
        english_prompt = await translate_to_english(prompt)
        
        # Отправка индикатора загрузки для генерации изображения
        await safe_send_chat_action(message.chat.id, "upload_photo")
    except Exception as e:
        logger.error(f"Ошибка при переводе запроса: {e}")
        await safe_send_message(
            message.chat.id,
            "Произошла ошибка при переводе запроса. Попробуем использовать оригинальный текст.",
            reply_markup=main_keyboard
        )
        english_prompt = prompt
    
    # Подготовка данных для запроса к API Stability
    data = {
        "text_prompts": [
            {
                "text": english_prompt,
                "weight": 1.0
            }
        ],
        "cfg_scale": 7,
        "height": 1024,
        "width": 1024,
        "samples": 1,
        "steps": 30
    }
    
    # Проверка наличия ключа API
    if not STABILITY_API_KEY:
        await safe_send_message(
            message.chat.id,
            "Извините, ключ API для генерации изображений не настроен.",
            reply_markup=main_keyboard
        )
        return
    
    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            # Асинхронная отправка запроса к API Stability
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    STABILITY_TEXT_TO_IMAGE_URL, 
                    headers=stability_headers, 
                    json=data,
                    timeout=60  # Увеличенный таймаут для генерации изображений
                ) as response:
                    if response.status == 200:
                        # Извлечение изображения из ответа
                        response_json = await response.json()
                        
                        # Получение base64-закодированного изображения
                        for i, image in enumerate(response_json["artifacts"]):
                            image_data = base64.b64decode(image["base64"])
                            
                            # Создание директории для временных файлов, если она не существует
                            os.makedirs("temp", exist_ok=True)
                            
                            # Сохранение изображения во временный файл
                            image_path = f"temp/generated_image_{message.from_user.id}_{int(time.time())}_{i}.png"
                            with open(image_path, "wb") as f:
                                f.write(image_data)
                            
                            # Отправка изображения пользователю
                            try:
                                await message.answer_photo(
                                    FSInputFile(image_path),
                                    caption=f"Сгенерированное изображение по запросу:\n\n🇷🇺 {prompt}\n\n🇬🇧 {english_prompt}",
                                    reply_markup=main_keyboard
                                )
                                logger.info(f"Изображение успешно отправлено пользователю {message.from_user.id}")
                            except TelegramAPIError as e:
                                logger.error(f"Ошибка при отправке изображения: {e}")
                                # Повторная попытка отправки с использованием другого метода
                                try:
                                    with open(image_path, "rb") as photo:
                                        await bot.send_photo(
                                            message.chat.id,
                                            photo,
                                            caption=f"Сгенерированное изображение по запросу:\n\n🇷🇺 {prompt}\n\n🇬🇧 {english_prompt}",
                                            reply_markup=main_keyboard
                                        )
                                except Exception as e2:
                                    logger.error(f"Вторая попытка отправки изображения также не удалась: {e2}")
                                    await safe_send_message(
                                        message.chat.id,
                                        "Произошла ошибка при отправке изображения. Попробуйте позже.",
                                        reply_markup=main_keyboard
                                    )
                            
                            # Удаление временного файла
                            try:
                                os.remove(image_path)
                            except Exception as e:
                                logger.error(f"Ошибка при удалении временного файла: {e}")
                        
                        # Успешно сгенерировали и отправили изображение, выходим из цикла
                        return
                    elif response.status == 429:  # Rate limit
                        retry_delay = min(INITIAL_RETRY_DELAY * (2 ** retry_count) + random.uniform(0, 1), MAX_RETRY_DELAY)
                        logger.warning(f"Превышен лимит запросов API Stability (429). Повторная попытка через {retry_delay:.2f} сек.")
                        await safe_send_message(
                            message.chat.id,
                            f"Превышен лимит запросов к API. Повторная попытка через {int(retry_delay)} сек..."
                        )
                        await asyncio.sleep(retry_delay)
                    else:
                        error_text = await response.text()
                        logger.error(f"Ошибка API Stability: {response.status} - {error_text}")
                        
                        # Более информативное сообщение об ошибке
                        error_message = "Извините, произошла ошибка при генерации изображения."
                        if response.status == 401:
                            error_message += " Проблема с аутентификацией API."
                        elif response.status == 400:
                            error_message += " Некорректный запрос. Возможно, в запросе есть запрещенный контент."
                        
                        # Для некоторых ошибок нет смысла повторять запрос
                        if response.status in [400, 401, 403]:
                            await safe_send_message(message.chat.id, error_message, reply_markup=main_keyboard)
                            return
                        
                        # Для других ошибок делаем паузу и повторяем
                        retry_delay = min(INITIAL_RETRY_DELAY * (2 ** retry_count) + random.uniform(0, 1), MAX_RETRY_DELAY)
                        logger.info(f"Повторная попытка через {retry_delay:.2f} сек.")
                        await asyncio.sleep(retry_delay)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"Ошибка сети при генерации изображения: {str(e)}")
            retry_delay = min(INITIAL_RETRY_DELAY * (2 ** retry_count) + random.uniform(0, 1), MAX_RETRY_DELAY)
            logger.info(f"Повторная попытка через {retry_delay:.2f} сек.")
            await asyncio.sleep(retry_delay)
        except Exception as e:
            logger.error(f"Неожиданная ошибка при генерации изображения: {str(e)}")
            await safe_send_message(
                message.chat.id,
                "Произошла неожиданная ошибка при генерации изображения. Попробуйте позже.",
                reply_markup=main_keyboard
            )
            return
            
        retry_count += 1
    
    # Если все попытки исчерпаны
    await safe_send_message(
        message.chat.id,
        "К сожалению, не удалось сгенерировать изображение после нескольких попыток. Пожалуйста, попробуйте позже.",
        reply_markup=main_keyboard
    )

@dp.message()
async def process_message(message: Message):
    """Обработчик всех текстовых сообщений"""
    global last_activity_time
    last_activity_time = time.time()
    
    user_message = message.text
    
    # Проверка длины сообщения
    if len(user_message) > MAX_INPUT_LENGTH:
        await safe_send_message(
            message.chat.id,
            f"Извините, ваше сообщение слишком длинное. Максимальная длина: {MAX_INPUT_LENGTH} символов.",
            reply_markup=main_keyboard
        )
        return
    
    # Отправка индикатора набора текста
    await safe_send_chat_action(message.chat.id, "typing")
    
    # Подготовка данных для запроса к API DeepInfra
    data = {
        "model": "meta-llama/Meta-Llama-3-8B-Instruct",  # Модель DeepInfra
        "messages": [
            {"role": "system", "content": "Ты полезный ассистент. Отвечай на русском языке."},
            {"role": "user", "content": user_message}
        ],
        "max_tokens": 800,
        "temperature": 0.7
    }
    
    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            # Асинхронная отправка запроса к API DeepInfra
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    DEEPINFRA_API_URL, 
                    headers=deepinfra_headers, 
                    json=data,
                    timeout=30
                ) as response:
                    if response.status == 200:
                        # Извлечение ответа из JSON
                        response_json = await response.json()
                        answer = response_json["choices"][0]["message"]["content"]
                        
                        # Разделение длинного ответа на части
                        if len(answer) <= MAX_MESSAGE_LENGTH:
                            await safe_send_message(message.chat.id, answer, reply_markup=main_keyboard)
                        else:
                            # Разделение ответа на части по MAX_MESSAGE_LENGTH символов
                            for i in range(0, len(answer), MAX_MESSAGE_LENGTH):
                                part = answer[i:i + MAX_MESSAGE_LENGTH]
                                if i == 0:
                                    await safe_send_message(message.chat.id, part, reply_markup=main_keyboard)
                                else:
                                    await safe_send_message(message.chat.id, part)
                        
                        logger.info(f"Успешно отправлен ответ пользователю {message.from_user.id}")
                        return
                    elif response.status == 429:  # Rate limit
                        retry_delay = min(INITIAL_RETRY_DELAY * (2 ** retry_count) + random.uniform(0, 1), MAX_RETRY_DELAY)
                        logger.warning(f"Превышен лимит запросов API (429). Повторная попытка через {retry_delay:.2f} сек.")
                        await asyncio.sleep(retry_delay)
                    else:
                        error_text = await response.text()
                        logger.error(f"Ошибка API: {response.status} - {error_text}")
                        
                        # Более информативное сообщение об ошибке
                        error_message = "Извините, произошла ошибка при обработке вашего запроса."
                        if response.status == 404:
                            error_message += " Сервис временно недоступен или указан неверный URL."
                        elif response.status == 401:
                            error_message += " Проблема с аутентификацией API."
                        
                        # Для некоторых ошибок нет смысла повторять запрос
                        if response.status in [400, 401, 403]:
                            await safe_send_message(message.chat.id, error_message, reply_markup=main_keyboard)
                            return
                        
                        # Для других ошибок делаем паузу и повторяем
                        retry_delay = min(INITIAL_RETRY_DELAY * (2 ** retry_count) + random.uniform(0, 1), MAX_RETRY_DELAY)
                        logger.info(f"Повторная попытка через {retry_delay:.2f} сек.")
                        await asyncio.sleep(retry_delay)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"Ошибка сети: {str(e)}")
            retry_delay = min(INITIAL_RETRY_DELAY * (2 ** retry_count) + random.uniform(0, 1), MAX_RETRY_DELAY)
            logger.info(f"Повторная попытка через {retry_delay:.2f} сек.")
            await asyncio.sleep(retry_delay)
        except Exception as e:
            logger.error(f"Неожиданная ошибка: {str(e)}")
            await safe_send_message(
                message.chat.id,
                "Произошла неожиданная ошибка при обработке вашего запроса. Попробуйте позже.",
                reply_markup=main_keyboard
            )
            return
            
        retry_count += 1
    
    # Если все попытки исчерпаны
    await safe_send_message(
        message.chat.id,
        "К сожалению, не удалось получить ответ после нескольких попыток. Пожалуйста, попробуйте позже.",
        reply_markup=main_keyboard
    )

async def keep_alive():
    """Функция для поддержания бота активным на бесплатных хостингах"""
    while True:
        current_time = time.time()
        # Если прошло больше KEEP_ALIVE_INTERVAL с последней активности
        if current_time - last_activity_time > KEEP_ALIVE_INTERVAL:
            logger.info("Выполнение keep-alive запроса...")
            try:
                # Выполняем простой запрос к API Telegram
                await bot.get_me()
                logger.info("Keep-alive запрос выполнен успешно")
            except Exception as e:
                logger.error(f"Ошибка при выполнении keep-alive запроса: {e}")
        
        # Проверяем каждые 5 минут
        await asyncio.sleep(300)

async def check_api_availability():
    """Функция для проверки доступности API"""
    try:
        # Проверка API DeepInfra
        async with aiohttp.ClientSession() as session:
            async with session.post(
                DEEPINFRA_API_URL,
                headers=deepinfra_headers,
                json={
                    "model": "meta-llama/Meta-Llama-3-8B-Instruct",
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": "Hello"}
                    ],
                    "max_tokens": 10
                },
                timeout=10
            ) as response:
                if response.status == 200:
                    logger.info("API DeepInfra доступен")
                    return True
                else:
                    logger.warning(f"API DeepInfra недоступен, код ответа: {response.status}")
                    return False
    except Exception as e:
        logger.error(f"Ошибка при проверке доступности API: {e}")
        return False

async def main():
    """Основная функция запуска бота"""
    # Проверка наличия необходимых ключей API
    if not TELEGRAM_TOKEN:
        logger.error("Ошибка: TELEGRAM_TOKEN не найден в переменных окружения")
        return
    if not DEEPINFRA_API_KEY:
        logger.warning("Предупреждение: DEEPINFRA_API_KEY не найден в переменных окружения")
    if not STABILITY_API_KEY:
        logger.warning("Предупреждение: STABILITY_API_KEY не найден в переменных окружения")
    
    # Создание директории для временных файлов
    os.makedirs("temp", exist_ok=True)
    
    # Проверка доступности API перед запуском
    api_available = await check_api_availability()
    if not api_available:
        logger.warning("API недоступен при запуске. Бот будет запущен, но некоторые функции могут не работать.")
    
    try:
        # Запуск фоновой задачи для поддержания бота активным
        keep_alive_task = asyncio.create_task(keep_alive())
        
        # Запуск бота
        logger.info("Запуск бота...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске бота: {e}")
    finally:
        # Отмена фоновой задачи при завершении работы бота
        if 'keep_alive_task' in locals():
            keep_alive_task.cancel()
        logger.info("Бот остановлен")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.critical(f"Необработанное исключение: {e}")
        # Попытка перезапуска бота при критической ошибке
        logger.info("Попытка перезапуска бота через 10 секунд...")
        time.sleep(10)
        try:
            asyncio.run(main())
        except Exception as e2:
            logger.critical(f"Не удалось перезапустить бота: {e2}")
