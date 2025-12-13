from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
import json
import aiohttp
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

# Загружаем переменные окружения из .env файла
load_dotenv()

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GIST_ID = os.getenv("GIST_ID", "")
MENU_DATA_FILE = "menu_data.json"
ADMIN_PIN = os.getenv("ADMIN_PIN", "1234")  # Значение по умолчанию "1234", если не задано в .env

# --- Глобальные переменные для аутентификации ---
authenticated_users = set()  # Множество ID пользователей, прошедших аутентификацию

# --- Проверка конфигурации ---
def check_configuration():
    """Проверяет правильность конфигурации перед запуском"""
    errors = []
    
    if not BOT_TOKEN:
        errors.append("❌ Не указан BOT_TOKEN в .env файле")
    if not GITHUB_TOKEN:
        errors.append("❌ Не указан GITHUB_TOKEN в .env файле")
    
    if not os.path.exists(MENU_DATA_FILE):
        errors.append(f"❌ Не найден файл меню: {MENU_DATA_FILE}")
    
    return errors

# --- Функция для проверки аутентификации пользователя ---
async def is_authenticated(user_id: int) -> bool:
    return user_id in authenticated_users

# --- Обработчик ввода пин-кода ---
async def handle_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    entered_pin = update.message.text.strip()
    
    if entered_pin == ADMIN_PIN:
        authenticated_users.add(user_id)
        await update.message.reply_text(
            "✅ Успешная аутентификация!\n\nТеперь вы можете управлять меню и доставкой.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Открыть меню управления", callback_data="back_to_main")]
            ])
        )
    else:
        await update.message.reply_text(
            "❌ Неверный пин-код. Попробуйте еще раз или обратитесь к администратору.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Попробовать снова", callback_data="request_pin")]
            ])
        )

# --- Обработчик запроса пин-кода ---
async def request_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "🔑 Пожалуйста, введите пин-код для доступа к управлению:",
            reply_markup=None
        )
    else:
        await update.effective_message.reply_text(
            "🔑 Пожалуйста, введите пин-код для доступа к управлению:"
        )

# --- Загрузка данных из JSON-файлов ---
def load_menu_data():
    if os.path.exists(MENU_DATA_FILE):
        with open(MENU_DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

async def load_status_from_gist_or_local():
    """Загружает текущий статус из Gist или из локальных файлов при ошибке"""
    stop_list = []
    delivery_status = {"disabled_until": None}
    
    if GITHUB_TOKEN and GIST_ID:
        try:
            stop_list, delivery_status = await load_status_from_gist()
            print("✅ Статус успешно загружен из Gist")
            return stop_list, delivery_status
        except Exception as e:
            print(f"⚠️ Ошибка загрузки из Gist: {e}. Используем локальные файлы.")
    
    # Загрузка из локальных файлов как резервный вариант
    try:
        if os.path.exists("stop_list.json"):
            with open("stop_list.json", "r", encoding="utf-8") as f:
                stop_list = json.load(f)
                
        if os.path.exists("delivery_status.json"):
            with open("delivery_status.json", "r", encoding="utf-8") as f:
                delivery_status = json.load(f)
                
        print("✅ Статус загружен из локальных файлов")
    except Exception as e:
        print(f"⚠️ Ошибка загрузки из локальных файлов: {e}. Используем значения по умолчанию.")
    
    return stop_list, delivery_status

async def load_status_from_gist():
    """Загружает текущий статус из GitHub Gist"""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PythonBot"
    }
    url = f"https://api.github.com/gists/{GIST_ID}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                files = data.get('files', {})
                
                stop_list = json.loads(files.get('stop_list.json', {}).get('content', '[]'))
                delivery_status = json.loads(files.get('delivery_status.json', {}).get('content', '{"disabled_until": null}'))
                
                return stop_list, delivery_status
            else:
                error_text = await response.text()
                raise Exception(f"Ошибка загрузки Gist: {response.status}, {error_text}")

async def save_status_to_gist_or_local(stop_list, delivery_status):
    """Сохраняет статус в Gist или в локальные файлы при ошибке"""
    success = False
    
    if GITHUB_TOKEN and GIST_ID:
        try:
            success = await save_status_to_gist(stop_list, delivery_status)
            if success:
                print("✅ Статус успешно сохранен в Gist")
                return True
            else:
                print("⚠️ Не удалось сохранить статус в Gist. Попробуем локальные файлы.")
        except Exception as e:
            print(f"⚠️ Ошибка сохранения в Gist: {e}. Попробуем локальные файлы.")
    
    # Сохранение в локальные файлы как резервный вариант
    try:
        with open("stop_list.json", "w", encoding="utf-8") as f:
            json.dump(stop_list, f, ensure_ascii=False, indent=2)
        
        with open("delivery_status.json", "w", encoding="utf-8") as f:
            json.dump(delivery_status, f, ensure_ascii=False, indent=2)
        
        print("✅ Статус сохранен в локальные файлы")
        return True
    except Exception as e:
        print(f"❌ Критическая ошибка: не удалось сохранить статус ни в Gist, ни в локальные файлы: {e}")
        return False

async def save_status_to_gist(stop_list, delivery_status):
    """Сохраняет статус в GitHub Gist"""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PythonBot"
    }
    url = f"https://api.github.com/gists/{GIST_ID}"
    
    files = {
        "stop_list.json": {"content": json.dumps(stop_list, ensure_ascii=False, indent=2)},
        "delivery_status.json": {"content": json.dumps(delivery_status, ensure_ascii=False, indent=2)}
    }
    
    payload = {"files": files}
    
    async with aiohttp.ClientSession() as session:
        async with session.patch(url, json=payload, headers=headers, timeout=10) as response:
            if response.status == 200:
                return True
            else:
                error_text = await response.text()
                if response.status == 404:
                    print("⚠️ Gist не найден. Возможно, он был удален или ID неверный.")
                raise Exception(f"Ошибка сохранения Gist: {response.status}, {error_text}")

async def check_gist_access():
    """Проверяет доступ к Gist и права на редактирование"""
    if not GITHUB_TOKEN or not GIST_ID:
        return False, "Не указаны GITHUB_TOKEN или GIST_ID"
    
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PythonBot"
    }
    
    # Проверяем существование Gist
    gist_url = f"https://api.github.com/gists/{GIST_ID}"
    async with aiohttp.ClientSession() as session:
        async with session.get(gist_url, headers=headers, timeout=10) as response:
            if response.status != 200:
                error_text = await response.text()
                return False, f"Gist не найден или нет прав на чтение. Ошибка: {response.status}, {error_text}"
            
            gist_data = await response.json()
            owner = gist_data.get("owner", {}).get("login", "")
            
            # Проверяем права на редактирование
            async with session.get("https://api.github.com/user", headers=headers, timeout=10) as user_response:
                if user_response.status != 200:
                    return False, "Не удалось проверить права пользователя GitHub"
                
                user_data = await user_response.json()
                current_user = user_data.get("login", "")
                
                if owner != current_user:
                    return False, f"Gist принадлежит пользователю {owner}, а не вашему аккаунту {current_user}. У вас нет прав на редактирование."
    
    return True, "Доступ к Gist проверен успешно"

async def create_or_repair_gist():
    """Создает новый Gist или восстанавливает поврежденный"""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PythonBot"
    }
    
    # Проверяем, существует ли уже Gist
    if GIST_ID:
        gist_url = f"https://api.github.com/gists/{GIST_ID}"
        async with aiohttp.ClientSession() as session:
            async with session.get(gist_url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    print(f"✅ Gist с ID {GIST_ID} существует и доступен")
                    return GIST_ID
    
    # Создаем новый Gist
    url = "https://api.github.com/gists"
    files = {
        "stop_list.json": {"content": "[]"},
        "delivery_status.json": {"content": '{"disabled_until": null}'}
    }
    
    payload = {
        "description": "Стоп-лист и статус доставки для Kochevniki",
        "public": False,
        "files": files
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=10) as response:
            if response.status == 201:
                data = await response.json()
                new_gist_id = data["id"]
                print(f"✅ Создан новый Gist с ID: {new_gist_id}")
                
                # Обновляем GIST_ID в текущем сеансе
                os.environ["GIST_ID"] = new_gist_id
                with open(".env", "r+") as f:
                    content = f.read()
                    if "GIST_ID=" in content:
                        content = "\n".join([line if not line.startswith("GIST_ID=") else f"GIST_ID={new_gist_id}" for line in content.split("\n")])
                    else:
                        content += f"\nGIST_ID={new_gist_id}"
                    f.seek(0)
                    f.write(content)
                    f.truncate()
                
                print(f"✅ GIST_ID обновлен в .env файле")
                return new_gist_id
            else:
                error_text = await response.text()
                print(f"❌ Ошибка создания Gist: {response.status}, {error_text}")
                return None

# --- Вспомогательные функции ---
async def is_delivery_disabled():
    _, delivery_status = await load_status_from_gist_or_local()
    if delivery_status.get("disabled_until"):
        disabled_until = datetime.fromisoformat(delivery_status["disabled_until"])
        return datetime.now() < disabled_until
    return False

# --- Обработчики команд и кнопок ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Проверяем аутентификацию
    if not await is_authenticated(user_id):
        # Если пользователь не аутентифицирован, запрашиваем пин-код
        if update.callback_query:
            await update.callback_query.answer()
        await request_pin(update, context)
        return

    query = update.callback_query
    if query:
        await query.answer()

    # Определяем состояние доставки
    delivery_disabled = await is_delivery_disabled()
    delivery_button_text = "Включить доставку" if delivery_disabled else "Выключить доставку"

    keyboard = [
        [InlineKeyboardButton("Добавить в стоп-лист", callback_data="add_to_stop")],
        [InlineKeyboardButton(delivery_button_text, callback_data="toggle_delivery")],
        [InlineKeyboardButton("Убрать из стоп-листа", callback_data="remove_from_stop")],
       
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_text = "🛠️ Управление меню и доставкой:"
    if delivery_disabled:
        _, delivery_status = await load_status_from_gist_or_local()
        disabled_until = datetime.fromisoformat(delivery_status["disabled_until"])
        message_text += f"\n\n🔴 Доставка временно отключена до {disabled_until.strftime('%d.%m.%Y %H:%M')}."

    if query:
        await query.edit_message_text(text=message_text, reply_markup=reply_markup)
    else:
        await update.effective_message.reply_text(text=message_text, reply_markup=reply_markup)


async def get_category_from_dish_id(dish_id: int, menu_data: dict) -> str:
    """Находит категорию по ID блюда"""
    for category, dishes in menu_data.items():
        for dish in dishes:
            if dish['id'] == dish_id:
                return category
    return ""


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Проверяем аутентификацию
    if not await is_authenticated(user_id):
        await update.callback_query.answer("🔑 Требуется аутентификация", show_alert=True)
        await request_pin(update, context)
        return

    query = update.callback_query
    await query.answer()

    data = query.data
    menu_data = load_menu_data()
    stop_list, _ = await load_status_from_gist_or_local()

    # Обработка изменения пин-кода
    if data == "change_pin":
        await query.edit_message_text(
            "🔑 Введите новый пин-код (4-6 цифр):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("<< Назад", callback_data="back_to_main")]
            ])
        )
        context.user_data['awaiting_new_pin'] = True
        return

    # Если пользователь вводит новый пин-код
    if context.user_data.get('awaiting_new_pin') and data != "back_to_main":
        # Игнорируем, так как ожидаем текстовое сообщение
        return

    # Главное меню - добавление в стоп-лист
    if data == "add_to_stop":
        keyboard = []
        for key, label in category_map.items():
            if menu_data.get(key):
                keyboard.append([InlineKeyboardButton(label, callback_data=f"cat_stop_{key}")])
        keyboard.append([InlineKeyboardButton("<< Назад", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="📂 Выберите категорию блюда для добавления в стоп-лист:", reply_markup=reply_markup)

    # Выбор категории для добавления в стоп-лист
    elif data.startswith("cat_stop_"):
        category_key = data[9:]
        category_label = category_map.get(category_key, "Неизвестная категория")

        if not menu_data.get(category_key):
            await query.edit_message_text(text=f"❌ В категории '{category_label}' нет блюд.")
            return

        keyboard = []
        for dish in menu_data[category_key]:
            dish_id = dish['id']
            dish_name = dish['name']
            # Используем крестик (❌) для блюд в стоп-листе
            button_text = f"{dish_name} ❌" if dish_id in stop_list else dish_name
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"dish_add_{dish_id}_{category_key}")])

        # Кнопка отключения всей категории
        keyboard.append([InlineKeyboardButton(f"❌ Отключить все '{category_label}'", callback_data=f"disable_cat_{category_key}")])
        keyboard.append([InlineKeyboardButton("<< Назад к категориям", callback_data="add_to_stop")])
        keyboard.append([InlineKeyboardButton("<< Назад", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=f"🍱 Выберите блюдо из категории '{category_label}' для добавления в стоп-лист:", reply_markup=reply_markup)

    # Добавление конкретного блюда в стоп-лист
    elif data.startswith("dish_add_"):
        # Извлекаем ID блюда и категорию из callback_data
        parts = data.split('_')
        dish_id_str = parts[2]
        category_key = parts[3] if len(parts) > 3 else ""
        
        try:
            dish_id = int(dish_id_str)
        except ValueError:
            await query.edit_message_text(text="❌ Ошибка: некорректный ID блюда.")
            return

        if not category_key:
            # Если категория не указана, пытаемся найти ее
            category_key = await get_category_from_dish_id(dish_id, menu_data)
            if not category_key:
                await query.edit_message_text(text="❌ Ошибка: не удалось определить категорию блюда.")
                return

        stop_list, delivery_status = await load_status_from_gist_or_local()
        if dish_id not in stop_list:
            stop_list.append(dish_id)
            success = await save_status_to_gist_or_local(stop_list, delivery_status)
            
            dish_name = "Блюдо"
            dish_price = 0
            for dishes in menu_data.values():
                for dish in dishes:
                    if dish['id'] == dish_id:
                        dish_name = dish['name']
                        dish_price = dish['price']
                        break
                        
            if success:
                await query.edit_message_text(
                    text=f"✅ Блюдо '{dish_name}' (ID: {dish_id}, {dish_price}₽) добавлено в стоп-лист!\n\nВыберите следующее действие:", 
                    reply_markup=await get_category_keyboard(category_key, menu_data, stop_list)
                )
            else:
                await query.edit_message_text(
                    text=f"⚠️ Блюдо '{dish_name}' добавлено в стоп-лист, но не удалось сохранить изменения на сервере. Изменения сохранены локально.\n\nВыберите следующее действие:", 
                    reply_markup=await get_category_keyboard(category_key, menu_data, stop_list)
                )
        else:
            # Если блюдо уже в стоп-листе, просто обновляем клавиатуру
            await query.edit_message_reply_markup(reply_markup=await get_category_keyboard(category_key, menu_data, stop_list))

    # Отключение всех блюд в категории
    elif data.startswith("disable_cat_"):
        category_key = data[12:]
        category_label = category_map.get(category_key, "Неизвестная категория")
        dishes_in_cat = menu_data.get(category_key, [])
        stop_list, delivery_status = await load_status_from_gist_or_local()
        new_dish_ids = [dish['id'] for dish in dishes_in_cat if dish['id'] not in stop_list]
        if new_dish_ids:
            stop_list.extend(new_dish_ids)
            success = await save_status_to_gist_or_local(stop_list, delivery_status)
            
            if success:
                await query.edit_message_text(
                    text=f"✅ Все блюда из категории '{category_label}' ({len(new_dish_ids)} шт.) добавлены в стоп-лист!\n\nВыберите следующее действие:", 
                    reply_markup=await get_category_keyboard(category_key, menu_data, stop_list)
                )
            else:
                await query.edit_message_text(
                    text=f"⚠️ Все блюда из категории '{category_label}' добавлены в стоп-лист, но не удалось сохранить изменения на сервере. Изменения сохранены локально.\n\nВыберите следующее действие:", 
                    reply_markup=await get_category_keyboard(category_key, menu_data, stop_list)
                )
        else:
            await query.answer(f"ℹ️ Все блюда из категории '{category_label}' уже в стоп-листе.")
            # Обновляем клавиатуру
            await query.edit_message_reply_markup(reply_markup=await get_category_keyboard(category_key, menu_data, stop_list))


    # Меню удаления из стоп-листа
    elif data == "remove_from_stop":
        stop_list, _ = await load_status_from_gist_or_local()
        if not stop_list:
            await query.edit_message_text(text="ostringstream Стоп-лист пуст.")
            await start_command(update, context)
            return

        keyboard = []
        for dish_id in stop_list:
            dish_name = f"Блюдо ID {dish_id}"
            dish_price = 0
            for dishes in menu_data.values():
                for dish in dishes:
                    if dish['id'] == dish_id:
                        dish_name = dish['name']
                        dish_price = dish['price']
                        break
            # Отображаем имя блюда с крестиком в меню удаления
            keyboard.append([InlineKeyboardButton(f"{dish_name} ({dish_price}₽) ❌", callback_data=f"dish_remove_{dish_id}")])

        # Кнопка включения всех блюд
        keyboard.append([InlineKeyboardButton("✅ Включить все блюда (очистить стоп-лист)", callback_data="enable_all_dishes")])
        keyboard.append([InlineKeyboardButton("<< Назад", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="🗑️ Выберите блюдо для удаления из стоп-листа:", reply_markup=reply_markup)

    # Удаление конкретного блюда из стоп-листа
    elif data.startswith("dish_remove_"):
        dish_id_str = data[12:]
        try:
            dish_id = int(dish_id_str)
        except ValueError:
            await query.edit_message_text(text="❌ Ошибка: некорректный ID блюда.")
            return

        stop_list, delivery_status = await load_status_from_gist_or_local()
        if dish_id in stop_list:
            stop_list.remove(dish_id)
            success = await save_status_to_gist_or_local(stop_list, delivery_status)
            
            # После удаления обновляем список блюд в стоп-листе
            stop_list, _ = await load_status_from_gist_or_local()
            if not stop_list:
                await query.edit_message_text(text="ostringstream Стоп-лист пуст.")
                await start_command(update, context)
                return
                
            keyboard = []
            for id in stop_list:
                dish_name = f"Блюдо ID {id}"
                dish_price = 0
                for dishes in menu_data.values():
                    for dish in dishes:
                        if dish['id'] == id:
                            dish_name = dish['name']
                            dish_price = dish['price']
                            break
                keyboard.append([InlineKeyboardButton(f"{dish_name} ({dish_price}₽) ❌", callback_data=f"dish_remove_{id}")])

            keyboard.append([InlineKeyboardButton("✅ Включить все блюда (очистить стоп-лист)", callback_data="enable_all_dishes")])
            keyboard.append([InlineKeyboardButton("<< Назад", callback_data="back_to_main")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if success:
                await query.edit_message_text(text="🗑️ Выберите блюдо для удаления из стоп-листа:", reply_markup=reply_markup)
            else:
                await query.edit_message_text(text="⚠️ Блюдо удалено из стоп-листа, но не удалось сохранить изменения на сервере. Изменения сохранены локально.\n\n🗑️ Выберите блюдо для удаления из стоп-листа:", reply_markup=reply_markup)
        else:
            await query.answer(f"⚠️ Блюдо ID {dish_id} не найдено в стоп-листе.")
            await button_handler(update, context)  # Вернуть в меню стоп-листа


    # Включение всех блюд (очистка стоп-листа)
    elif data == "enable_all_dishes":
        # Очищаем стоп-лист
        _, delivery_status = await load_status_from_gist_or_local()
        success = await save_status_to_gist_or_local([], delivery_status)
        
        if success:
            message = "✅ Все блюда включены (стоп-лист очищен)!\n\nВыберите следующее действие:"
        else:
            message = "⚠️ Все блюда включены (стоп-лист очищен), но не удалось сохранить изменения на сервере. Изменения сохранены локально.\n\nВыберите следующее действие:"
            
        await query.edit_message_text(text=message)
        await start_command(update, context)  # Вернуть в главное меню


    # Управление доставкой
    elif data == "toggle_delivery":
        delivery_disabled = await is_delivery_disabled()
        if delivery_disabled:
            # Включаем доставку
            stop_list, _ = await load_status_from_gist_or_local()
            delivery_status = {"disabled_until": None}
            success = await save_status_to_gist_or_local(stop_list, delivery_status)
            
            if success:
                await query.edit_message_text(text="✅ Доставка успешно включена!\n\nВыберите следующее действие:")
            else:
                await query.edit_message_text(text="⚠️ Доставка включена, но не удалось сохранить изменения на сервере. Изменения сохранены локально.\n\nВыберите следующее действие:")
            await start_command(update, context)
        else:
            keyboard = [
                [InlineKeyboardButton("1 час", callback_data="delivery_off_1")],
                [InlineKeyboardButton("2 часа", callback_data="delivery_off_2")],
                [InlineKeyboardButton("4 часа", callback_data="delivery_off_4")],
                [InlineKeyboardButton("8 часов", callback_data="delivery_off_8")],
                [InlineKeyboardButton("24 часа", callback_data="delivery_off_24")],
                [InlineKeyboardButton("Другая дата", callback_data="delivery_date_picker")],
                [InlineKeyboardButton("<< Назад", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text="⏱️ Выберите, на сколько времени отключить доставку:", reply_markup=reply_markup)

    # Отключение доставки на определенное время
    elif data.startswith("delivery_off_"):
        hours_str = data[13:]
        try:
            hours = int(hours_str)
        except ValueError:
            await query.edit_message_text(text="❌ Ошибка: некорректное количество часов.")
            return

        disabled_until = datetime.now() + timedelta(hours=hours)
        stop_list, _ = await load_status_from_gist_or_local()
        delivery_status = {"disabled_until": disabled_until.isoformat()}
        success = await save_status_to_gist_or_local(stop_list, delivery_status)
        
        if success:
            message = f"🚫 Доставка отключена до {disabled_until.strftime('%d.%m.%Y %H:%M')}!\n\nВыберите следующее действие:"
        else:
            message = f"⚠️ Доставка отключена до {disabled_until.strftime('%d.%m.%Y %H:%M')}, но не удалось сохранить изменения на сервере. Изменения сохранены локально.\n\nВыберите следующее действие:"
            
        await query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Назад", callback_data="back_to_main")]])
        )
    
    # Выбор даты для отключения доставки
    elif data == "delivery_date_picker":
        keyboard = [
            [InlineKeyboardButton("1 день", callback_data="delivery_date_1")],
            [InlineKeyboardButton("3 дня", callback_data="delivery_date_3")],
            [InlineKeyboardButton("1 неделя", callback_data="delivery_date_7")],
            [InlineKeyboardButton("2 недели", callback_data="delivery_date_14")],
            [InlineKeyboardButton("1 месяц", callback_data="delivery_date_30")],
            [InlineKeyboardButton("Свой период", callback_data="delivery_custom_date")],
            [InlineKeyboardButton("<< Назад", callback_data="toggle_delivery")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="📅 Выберите срок отключения доставки:", reply_markup=reply_markup)
    
    # Отключение доставки на фиксированный срок
    elif data.startswith("delivery_date_"):
        days_str = data[14:]
        try:
            days = int(days_str)
        except ValueError:
            await query.edit_message_text(text="❌ Ошибка: некорректное количество дней.")
            return

        disabled_until = datetime.now() + timedelta(days=days)
        stop_list, _ = await load_status_from_gist_or_local()
        delivery_status = {"disabled_until": disabled_until.isoformat()}
        success = await save_status_to_gist_or_local(stop_list, delivery_status)
        
        if success:
            message = f"🚫 Доставка отключена до {disabled_until.strftime('%d.%m.%Y %H:%M')}!\n\nВыберите следующее действие:"
        else:
            message = f"⚠️ Доставка отключена до {disabled_until.strftime('%d.%m.%Y %H:%M')}, но не удалось сохранить изменения на сервере. Изменения сохранены локально.\n\nВыберите следующее действие:"
            
        await query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Назад", callback_data="back_to_main")]])
        )
    
    # Ввод собственной даты
    elif data == "delivery_custom_date":
        await query.edit_message_text(
            "📅 Введите дату и время отключения доставки в формате:\n\nДД.ММ.ГГГГ ЧЧ:ММ\n\nПример: 25.12.2025 18:00",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("<< Назад", callback_data="delivery_date_picker")]
            ])
        )
        context.user_data['awaiting_custom_date'] = True
    
    # Возврат в главное меню
    elif data == "back_to_main":
        context.user_data.pop('awaiting_new_pin', None)  # Сбрасываем состояние ожидания нового пин-кода
        context.user_data.pop('awaiting_custom_date', None)  # Сбрасываем состояние ожидания даты
        await start_command(update, context)


# --- Обработчик ввода собственной даты ---
async def handle_custom_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Проверяем аутентификацию
    if not await is_authenticated(user_id):
        await update.effective_message.reply_text("🔑 Требуется аутентификация")
        await request_pin(update, context)
        return

    # Проверяем, ожидаем ли мы ввод даты
    if not context.user_data.get('awaiting_custom_date'):
        # Если пользователь не ожидает ввода даты, проверяем, не ожидаем ли мы пин-код
        if not await is_authenticated(user_id):
            await handle_pin(update, context)
        return

    date_input = update.message.text.strip()
    
    try:
        # Парсим дату из строки
        parsed_datetime = datetime.strptime(date_input, "%d.%m.%Y %H:%M")
        
        # Проверяем, что дата не в прошлом
        if parsed_datetime < datetime.now():
            await update.message.reply_text(
                "❌ Ошибка: дата не может быть в прошлом.\n\nВведите дату и время отключения доставки в формате:\n\nДД.ММ.ГГГГ ЧЧ:ММ\n\nПример: 25.12.2025 18:00",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("<< Назад", callback_data="delivery_date_picker")]
                ])
            )
            return
        
        # Сохраняем статус
        stop_list, _ = await load_status_from_gist_or_local()
        delivery_status = {"disabled_until": parsed_datetime.isoformat()}
        success = await save_status_to_gist_or_local(stop_list, delivery_status)
        
        if success:
            message = f"🚫 Доставка отключена до {parsed_datetime.strftime('%d.%m.%Y %H:%M')}!"
        else:
            message = f"⚠️ Доставка отключена до {parsed_datetime.strftime('%d.%m.%Y %H:%M')}, но не удалось сохранить изменения на сервере. Изменения сохранены локально."
        
        await update.message.reply_text(
            text=message,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Назад", callback_data="back_to_main")]])
        )
        
        # Сбрасываем состояние ожидания даты
        context.user_data.pop('awaiting_custom_date', None)
        
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат даты.\n\nВведите дату и время отключения доставки в формате:\n\nДД.ММ.ГГГГ ЧЧ:ММ\n\nПример: 25.12.2025 18:00",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("<< Назад", callback_data="delivery_date_picker")]
            ])
        )


# --- category_map из React-кода ---
category_map = {
  "breakfast": "Завтраки",
  "appetizers": "На закуску",
  "salads": "Салаты",
  "main": "Рыба и морепродукты",
  "desserts": "Горячие закуски",
  "beef": "Мясо и птица",
  "steak": "Из печи",
  "fire": "Супы",
  "lepka": "Лепка",
  "garn": "Гарниры",
  "des": "Десерты",
}

# --- Вспомогательная функция для получения клавиатуры категории ---
async def get_category_keyboard(category_key, menu_data, stop_list):
    category_label = category_map.get(category_key, "Неизвестная категория")
    keyboard = []
    dishes_in_category = menu_data.get(category_key, [])
    
    # Сортировка блюд сначала доступные, потом в стоп-листе
    available_dishes = [dish for dish in dishes_in_category if dish['id'] not in stop_list]
    unavailable_dishes = [dish for dish in dishes_in_category if dish['id'] in stop_list]
    
    # Сначала добавляем доступные блюда
    for dish in available_dishes:
        dish_id = dish['id']
        dish_name = dish['name']
        dish_price = dish['price']
        button_text = f"{dish_name} ({dish_price}₽)"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"dish_add_{dish_id}_{category_key}")])
    
    # Затем добавляем недоступные блюда
    for dish in unavailable_dishes:
        dish_id = dish['id']
        dish_name = dish['name']
        dish_price = dish['price']
        button_text = f"{dish_name} ({dish_price}₽) ❌"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"dish_add_{dish_id}_{category_key}")])

    # Кнопка отключения всей категории
    keyboard.append([InlineKeyboardButton(f"❌ Отключить все '{category_label}' ({len(dishes_in_category)} шт.)", callback_data=f"disable_cat_{category_key}")])
    keyboard.append([InlineKeyboardButton("<< Назад к категориям", callback_data="add_to_stop")])
    keyboard.append([InlineKeyboardButton("<< Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)


# --- Запуск бота ---
async def initialize_bot():
    """Инициализация бота с проверкой и восстановлением конфигурации"""
    config_errors = check_configuration()
    if config_errors:
        for error in config_errors:
            print(error)
        return False, None
    
    # Проверяем доступ к Gist
    is_accessible, message = await check_gist_access()
    if not is_accessible:
        print(f"⚠️ {message}")
        print("🔧 Попытка восстановить Gist...")
        new_gist_id = await create_or_repair_gist()
        if new_gist_id:
            print(f"✅ Gist восстановлен с ID: {new_gist_id}")
        else:
            print("❌ Не удалось восстановить Gist. Используем локальные файлы для хранения данных.")
    
    print("✅ Проверка конфигурации пройдена успешно")
    return True, Application.builder().token(BOT_TOKEN).build()

def main():
    """Основная функция запуска бота"""
    print("🤖 Запуск бота...")
    print(f"📁 Файл данных: {MENU_DATA_FILE}")
    print(f"🔑 Пин-код аутентификации: {'[ЗАДАН]' if ADMIN_PIN != '1234' else '[ЗНАЧЕНИЕ ПО УМОЛЧАНИЮ]'}")
    
    # Инициализация бота
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    success, application = loop.run_until_complete(initialize_bot())
    
    if not success:
        print("❌ Запуск бота отменен из-за ошибок конфигурации")
        return
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pin))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_date))
    
    print("✅ Бот успешно запущен!")
    print("💬 Отправьте команду /start для начала работы")
    
    # Запуск бота
    application.run_polling()


if __name__ == '__main__':
    main()
