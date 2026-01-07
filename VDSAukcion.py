import logging
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from io import BytesIO

# Включим логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Файлы для хранения данных
ADMINS_FILE = "admins.json"
PHOTOS_FILE = "photos_data.json"

# Константы
MAX_CONFIRMED_USERS = 4  # Максимальное количество подтвержденных участников

# Хранилища данных
admins = set()  # Множество ID администраторов
photos_data = {}  # {photo_id: {"photo": file_id, "users": {}, "confirmed_users": []}}

def save_admins():
    """Сохранить список администраторов в файл"""
    try:
        with open(ADMINS_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(admins), f, ensure_ascii=False, indent=2)
        logger.info(f"Сохранено {len(admins)} администраторов")
    except Exception as e:
        logger.error(f"Ошибка сохранения администраторов: {e}")

def load_admins():
    """Загрузить список администраторов из файл"""
    global admins
    try:
        if os.path.exists(ADMINS_FILE):
            with open(ADMINS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                admins = set(data)
                logger.info(f"Загружено {len(admins)} администраторов")
        else:
            logger.info("Файл администраторов не найден, будет создан при первом сохранении")
            admins = set()
    except Exception as e:
        logger.error(f"Ошибка загрузки администраторов: {e}")
        admins = set()

def save_photos_data():
    """Сохранить данные фото в файл (без данных пользователей)"""
    try:
        # Создаем копию без данных пользователей
        photos_to_save = {}
        for photo_id, data in photos_data.items():
            photos_to_save[photo_id] = {
                "photo": data.get("photo"),
                "photo_file_unique_id": data.get("photo_file_unique_id")
                # НЕ сохраняем users и confirmed_users
            }
        
        with open(PHOTOS_FILE, 'w', encoding='utf-8') as f:
            json.dump(photos_to_save, f, ensure_ascii=False, indent=2)
            logger.info(f"Сохранено {len(photos_to_save)} фото (без данных пользователей)")
            
    except Exception as e:
        logger.error(f"Ошибка сохранения данных фото: {e}")

def load_photos_data():
    """Загрузить данные фото из файл"""
    global photos_data
    try:
        if os.path.exists(PHOTOS_FILE):
            with open(PHOTOS_FILE, 'r', encoding='utf-8') as f:
                photos_data = json.load(f)
                logger.info(f"Загружено {len(photos_data)} фото")
                
                # ОЧИСТКА ДАННЫХ ПОЛЬЗОВАТЕЛЕЙ ПРИ ЗАГРУЗКЕ
                for photo_id, data in photos_data.items():
                    if "users" in data:
                        data["users"] = {}  # Очищаем список пользователей
                    if "confirmed_users" in data:
                        data["confirmed_users"] = []  # Очищаем подтвержденных пользователей
                
                # Проверяем целостность данных
                valid_photos = {}
                for photo_id, data in photos_data.items():
                    if "photo" in data:  # Проверяем, что есть file_id
                        valid_photos[photo_id] = data
                    else:
                        logger.warning(f"Фото {photo_id} не имеет file_id и будет пропущено")
                
                photos_data = valid_photos
                logger.info(f"Валидных фото после проверки: {len(photos_data)}")
        else:
            logger.info("Файл данных фото не найден, будет создан при первом сохранении")
            photos_data = {}
    except Exception as e:
        logger.error(f"Ошибка загрузки данных фото: {e}")
        photos_data = {}

def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    return user_id in admins

def get_user_icon(index: int) -> str:
    """Получить иконку для участника в зависимости от позиции"""
    if index == 0:
        return "☀️"  # Первый участник - солнце
    elif index == 1:
        return "🌤️"  # Второй участник - солнце с облачком
    elif index == 2:
        return "🌙"  # Третий участник - луна
    elif index == 3:
        return "⭐"  # Четвертый участник - звезда
    else:
        return "👤"  # Для остальных - обычный иконка

# Клавиатура для пользователей под фотографией
def get_photo_keyboard(photo_id, user_id=None):
    photo_data = photos_data.get(photo_id, {})
    confirmed_count = len(photo_data.get("confirmed_users", []))
    
    # Проверяем статус текущего пользователя
    user_has_registered = user_id in photo_data.get("users", {})
    user_has_confirmed = any(u["user_id"] == user_id for u in photo_data.get("confirmed_users", []))
    
    keyboard = []
    
    # Кнопка "Записать имя" - только если пользователь еще не записал имя
    if not user_has_registered:
        keyboard.append([InlineKeyboardButton("📝 Записать имя", callback_data=f"register_{photo_id}")])
    else:
        # Если пользователь уже записал имя, показываем кнопку удаления
        keyboard.append([InlineKeyboardButton("🗑️ Удалить мое имя", callback_data=f"delete_my_name_{photo_id}")])
    
    # Кнопка "Подтвердить" - только если пользователь записал имя, но еще не подтвердил
    # И если еще не достигнут лимит подтверждений
    if user_has_registered and not user_has_confirmed and confirmed_count < MAX_CONFIRMED_USERS:
        keyboard.append([InlineKeyboardButton("✅ Подтвердить участие", callback_data=f"confirm_{photo_id}")])
    
    # Информация о статусе пользователя
    status_text = ""
    if user_has_confirmed:
        # Находим позицию пользователя среди подтвержденных
        confirmed_users = photo_data.get("confirmed_users", [])
        user_position = next((i for i, u in enumerate(confirmed_users) if u["user_id"] == user_id), -1)
        if user_position >= 0:
            icon = get_user_icon(user_position)
            status_text = f"{icon} Вы подтвердили участие (позиция {user_position + 1})"
    elif user_has_registered and confirmed_count >= MAX_CONFIRMED_USERS:
        status_text = "❌ Места заняты"
    elif user_has_registered:
        status_text = "📝 Имя записано, можно подтвердить"
    
    if status_text:
        keyboard.append([InlineKeyboardButton(status_text, callback_data=f"status_{photo_id}")])
    
    # Кнопка показа участников
    keyboard.append([InlineKeyboardButton("👥 Показать участников", callback_data=f"show_{photo_id}")])
    
    # Кнопка управления для администраторов
    if user_id and is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👑 Управление участниками (Админ)", callback_data=f"admin_manage_{photo_id}")])
    
    return InlineKeyboardMarkup(keyboard)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    
    if not admins:  # Если нет админов, первый пользователь становится админом
        admins.add(user_id)
        save_admins()
        await update.message.reply_text(
            f"👑 Вы стали первым администратором бота! (ID: {user_id})\n\n"
            f"Доступные команды:\n"
            f"/start - показать это сообщение\n"
            f"/add_admin - добавить администратора по ID\n"
            f"/remove_admin - удалить администратора по ID\n"
            f"/list_admins - показать всех администраторов\n"
            f"/clear_names - очистить все имена участников (оставить фото)\n"
            f"/reset - полный сброс всех данных (удалить фото и имена)\n"
            f"/list - показать все фото (только для админов)\n"
            f"/view photo_X - просмотреть конкретное фото\n"
            f"/show - показать все фото и участников\n"
            f"/check_photos - проверить сохраненные фото\n"
            f"/restore - восстановить все фото из сохраненных данных\n"
            f"/id - получить свой ID\n\n"
            f"📸 Теперь можно подтвердить до {MAX_CONFIRMED_USERS} участников под каждой фото!\n"
            f"☀️ Первые 2 участника получают иконку солнца\n"
            f"🌙 Следующие 2 участника получают иконку луны\n"
            f"👑 Администраторы могут удалять участников через кнопку 'Управление участниками'\n\n"
            f"Отправьте мне фото 60x60, чтобы добавить его в систему."
        )
    elif is_admin(user_id):
        await update.message.reply_text(
            f"👑 Вы администратор! (ID: {user_id})\n\n"
            f"Доступные команды:\n"
            f"/start - показать это сообщение\n"
            f"/list_admins - показать всех администраторов\n"
            f"/clear_names - очистить все имена участников (оставить фото)\n"
            f"/view photo_X - просмотреть конкретное фото\n"
            f"/show - показать все фото и участников\n"
            f"/check_photos - проверить сохраненные фото\n"
            f"/restore - восстановить все фото из сохраненных данных\n"
            f"/id - получить свой ID\n\n"
            f"📸 Можно подтвердить до {MAX_CONFIRMED_USERS} участников под каждой фото!\n"
            f"☀️ Первые 2 участника получают иконку солнца\n"
            f"🌙 Следующие 2 участника получают иконку луны\n"
            f"👑 Вы можете удалять участников через кнопку 'Управление участниками' под каждой фотографией\n\n"
            f"Отправьте мне фото 60x60, чтобы добавить его в систему."
        )
    else:
        keyboard = [
            [InlineKeyboardButton("📸 Показать все фотографии", callback_data="show_all_photos")],
            [InlineKeyboardButton("👥 Показать всех участников", callback_data="show_all_participants")]
        ]
        
        await update.message.reply_text(
            f"👋 Привет, {username}!\n"
            f"📸 Этот бот позволяет записывать имена под фотографиями.\n\n"
            f"📋 Правила:\n"
            f"1. Каждый может записать имя под фото\n"
            f"2. Каждый может подтвердить участие ТОЛЬКО 1 раз под каждой фото\n"
            f"3. До {MAX_CONFIRMED_USERS} человек могут подтвердить участие под каждой фото!\n"
            f"4. Первые 2 участника получают иконку ☀️ Дневной Аукцион\n"
            f"5. Следующие 2 участника получают иконку 🌙 Ночной Аукцион\n"
            f"6. Вы можете удалить свое имя и записаться заново\n"
            f"7. Администраторы могут удалять участников при необходимости\n"
            f"Используйте кнопки ниже для навигации:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# Команда добавления администратора
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только администраторы могут добавлять других администраторов!")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "ℹ️ Использование: /add_admin <ID_пользователя>\n\n"
            "Чтобы получить ID пользователя:\n"
            "1. Попросите его переслать любое сообщение этому боту: @getidsbot\n"
            "2. Или используйте команду /id в этом боте\n"
            "3. ID - это число, например: 123456789"
        )
        return
    
    try:
        new_admin_id = int(args[0])
        
        if new_admin_id in admins:
            await update.message.reply_text(f"❌ Пользователь с ID {new_admin_id} уже является администратором!")
            return
        
        admins.add(new_admin_id)
        save_admins()
        
        await update.message.reply_text(
            f"✅ Пользователь с ID {new_admin_id} добавлен в список администраторов!\n\n"
            f"Теперь администраторов: {len(admins)}\n"
            f"ID всех администраторов: {', '.join(map(str, admins))}"
        )
        
        # Уведомляем нового администратора (если он уже общался с ботом)
        try:
            await context.bot.send_message(
                chat_id=new_admin_id,
                text=f"🎉 Поздравляем! Вас добавили в список администраторов бота!\n"
                     f"Теперь у вас есть доступ ко всем административным командам.\n"
                     f"Используйте /start чтобы увидеть список доступных команд."
            )
        except Exception as e:
            logger.info(f"Не удалось уведомить нового администратора: {e}")
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! ID должен быть числом.")

# Команда удаления администратора
async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только администраторы могут удалять других администраторов!")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text("ℹ️ Использование: /remove_admin <ID_пользователя>")
        return
    
    try:
        admin_to_remove = int(args[0])
        
        if admin_to_remove not in admins:
            await update.message.reply_text(f"❌ Пользователь с ID {admin_to_remove} не является администратором!")
            return
        
        if len(admins) <= 1:
            await update.message.reply_text("❌ Нельзя удалить последнего администратора!")
            return
        
        if admin_to_remove == user_id:
            await update.message.reply_text("❌ Вы не можете удалить себя! Попросите другого администратора.")
            return
        
        admins.remove(admin_to_remove)
        save_admins()
        
        await update.message.reply_text(
            f"✅ Пользователь с ID {admin_to_remove} удален из списка администраторов!\n\n"
            f"Теперь администраторов: {len(admins)}\n"
            f"ID оставшихся администраторов: {', '.join(map(str, admins))}"
        )
        
        # Уведомляем удаленного администратора
        try:
            await context.bot.send_message(
                chat_id=admin_to_remove,
                text="⚠️ Ваши права администратора были отозваны.\n"
                     "Теперь у вас нет доступа к административным командам."
            )
        except Exception as e:
            logger.info(f"Не удалось уведомить удаленного администратора: {e}")
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! ID должен быть числом.")

# Команда просмотра списка администраторов
async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только администраторы могут просматривать список администраторов!")
        return
    
    if not admins:
        await update.message.reply_text("📭 Список администраторов пуст!")
        return
    
    message = "👑 Список администраторов:\n\n"
    for idx, admin_id in enumerate(admins, 1):
        try:
            # Пытаемся получить информацию о пользователе
            chat = await context.bot.get_chat(admin_id)
            username = f"@{chat.username}" if chat.username else chat.full_name
            message += f"{idx}. {username} (ID: {admin_id})\n"
        except:
            message += f"{idx}. ID: {admin_id} (не удалось получить информацию)\n"
    
    message += f"\nВсего администраторов: {len(admins)}"
    
    await update.message.reply_text(message)

# Команда для получения своего ID
async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    
    message = (
        f"👤 Ваши данные:\n"
        f"• Имя: {username}\n"
        f"• ID: {user_id}\n\n"
        f"📝 ID нужен для добавления в администраторы\n"
        f"Покажите этот ID текущему администратору, чтобы он добавил вас"        
    )
    
    await update.message.reply_text(message)

    # Команда для просмотра списка администраторов (для всех пользователей)
async def show_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список администраторов всем пользователям (без ID)"""
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    
    if not admins:
        await update.message.reply_text("📭 Список администраторов пуст!")
        return
    
    message = "👑 Администраторы бота:\n\n"
    
    # Пытаемся получить информацию о каждом администраторе
    admin_list = []
    for admin_id in admins:
        try:
            chat = await context.bot.get_chat(admin_id)
            if chat.username:
                admin_list.append(f"@{chat.username}")
            else:
                admin_list.append(chat.full_name)
        except Exception as e:
            logger.warning(f"Не удалось получить информацию об администраторе {admin_id}: {e}")
            admin_list.append(f"Пользователь {admin_id}")  # Фолбэк, если не удалось получить данные
    
    # Добавляем администраторов в сообщение
    for idx, admin_name in enumerate(admin_list, 1):
        message += f"{idx}. {admin_name}\n"
    
    message += f"\nВсего администраторов: {len(admins)}"
    
    await update.message.reply_text(message)

# Обработка фотографий от администратора
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только администратор может добавлять фото!")
        return
    
    photo = update.message.photo[-1]  # Берем самое большое фото
    
    # Генерируем уникальный ID для фото
    photo_id = f"photo_{len(photos_data) + 1}"
    
    # Сохраняем данные о фото СРАЗУ
    photos_data[photo_id] = {
        "photo": photo.file_id,  # Сохраняем file_id
        "photo_file_unique_id": photo.file_unique_id,  # Сохраняем уникальный ID файла
        "users": {},  # {user_id: name}
        "confirmed_users": []  # Список подтвержденных имен
    }
    save_photos_data()  # Сразу сохраняем в файл
    
    # Проверяем размер (опционально)
    if photo.width != 60 or photo.height != 60:
        await update.message.reply_photo(
            photo=photo.file_id,
            caption=(
                f"📸 Фото добавлено администратором (ID: {photo_id})\n"
                f"⚠️ Размер: {photo.width}x{photo.height} (рекомендуется 60x60)\n"
                f"👇 Используйте кнопки ниже:"
            ),
            reply_markup=get_photo_keyboard(photo_id)
        )
    else:
        await update.message.reply_photo(
            photo=photo.file_id,
            caption=f"📸 Фото добавлено администратором (ID: {photo_id})\n👇 Используйте кнопки ниже:",
            reply_markup=get_photo_keyboard(photo_id)
        )

# Очистка только имен участников (фото остаются)
async def clear_names(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только для администратора!")
        return
    
    if not photos_data:
        await update.message.reply_text("📭 Нет фотографий для очистки")
        return
    
    # Счетчики
    total_users_cleared = 0
    total_confirmations_cleared = 0
    photos_affected = 0
    
    # Очищаем данные участников для каждой фотографии
    for photo_id, photo_data in photos_data.items():
        if photo_data.get("users") or photo_data.get("confirmed_users"):
            # Подсчитываем удаляемые данные
            total_users_cleared += len(photo_data.get("users", {}))
            total_confirmations_cleared += len(photo_data.get("confirmed_users", []))
            photos_affected += 1
            
            # Очищаем списки участников
            photo_data["users"] = {}
            photo_data["confirmed_users"] = []
    
    save_photos_data()
    
    if photos_affected > 0:
        await update.message.reply_text(
            f"✅ Имена участников очищены!\n\n"
            f"📊 Статистика:\n"
            f"• Фотографий обработано: {photos_affected}\n"
            f"• Удалено записей: {total_users_cleared}\n"
            f"• Удалено подтверждений: {total_confirmations_cleared}\n\n"
            f"📸 Фотографии сохранены и готовы для новых участников!"
        )
    else:
        await update.message.reply_text("ℹ️ Нет данных участников для очистки")

# Полный сброс всех данных
async def reset_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только для администратора!")
        return
    
    if not photos_data:
        await update.message.reply_text("📭 Нет данных для сброса")
        return
    
    # Подсчет статистики
    total_users = sum(len(p.get("users", {})) for p in photos_data.values())
    total_confirmed = sum(len(p.get("confirmed_users", [])) for p in photos_data.values())
    
    # Подтверждение сброса
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, сбросить ВСЕ", callback_data="confirm_reset_all"),
            InlineKeyboardButton("❌ Нет, отменить", callback_data="cancel_reset")
        ]
    ]
    
    await update.message.reply_text(
        "⚠️  ВНИМАНИЕ: Полный сброс данных!\n\n"
        f"Будет удалено:\n"
        f"• {len(photos_data)} фотографий\n"
        f"• {total_users} записей участников\n"
        f"• {total_confirmed} подтверждений\n\n"
        "Это действие НЕЛЬЗЯ отменить!\n"
        "Вы уверены?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Отправка альбома с фотографиями
async def send_photo_album(query, context):
    if not photos_data:
        await query.message.reply_text("📭 Нет добавленных фотографий")
        return
    
    # Создаем медиа-группу (альбом) с использованием InputMediaPhoto
    media_group = []
    
    photo_items = list(photos_data.items())
    for idx, (photo_id, photo_data) in enumerate(photo_items, 1):
        # Проверяем наличие file_id
        if "photo" not in photo_data:
            logger.warning(f"Фото {photo_id} не имеет file_id, пропускаем")
            continue
            
        confirmed_count = len(photo_data.get("confirmed_users", []))
        caption = (
            f"📸 {photo_id}\n"
            f"✅ Подтверждено: {confirmed_count}/{MAX_CONFIRMED_USERS}\n"
            f"📝 Записавшихся: {len(photo_data.get('users', {}))}"
        )
        
        # Создаем объект InputMediaPhoto
        media_group.append(
            InputMediaPhoto(
                media=photo_data['photo'],
                caption=caption
            )
        )
        
        # Максимум 10 фото в одном сообщении (ограничение Telegram)
        if len(media_group) >= 10:
            break
    
    if not media_group:
        await query.message.reply_text("❌ Нет доступных фотографий для отображения")
        return
    
    # Отправляем альбом
    try:
        await context.bot.send_media_group(
            chat_id=query.message.chat_id,
            media=media_group
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке альбома: {e}")
        # Если альбом не удалось отправить, отправляем фото по одному
        for media in media_group:
            try:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=media.media,
                    caption=media.caption
                )
            except Exception as e2:
                logger.error(f"Ошибка при отправке отдельного фото: {e2}")
    
    # После альбома отправляем кнопки для навигации
    keyboard = []
    for idx, photo_id in enumerate(list(photos_data.keys())[:10], 1):  # Берем первые 10
        if photo_id in photos_data and "photo" in photos_data[photo_id]:
            keyboard.append([
                InlineKeyboardButton(
                    f"📸 {photo_id} - Просмотреть подробно", 
                    callback_data=f"view_{photo_id}"
                )
            ])
    
    if keyboard:
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
        
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="👇 Выберите фотографию для детального просмотра:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# Команда для просмотра всех фото (только для админов)
async def list_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только для администратора!")
        return
    
    if not photos_data:
        await update.message.reply_text("📭 Нет добавленных фотографий")
        return
    
    message = "📚 Список всех фотографий:\n\n"
    for photo_id, data in photos_data.items():
        message += f"🆔 {photo_id}\n"
        has_file_id = "✅" if "photo" in data else "❌"
        message += f"Файл сохранен: {has_file_id}\n"
        message += f"👥 Подтверждено: {len(data.get('confirmed_users', []))}/{MAX_CONFIRMED_USERS}\n"
        if data.get('confirmed_users'):
            names_with_icons = []
            for i, user in enumerate(data['confirmed_users']):
                icon = get_user_icon(i)
                names_with_icons.append(f"{icon} {user['name']}")
            message += f"Участники: {', '.join(names_with_icons)}\n"
        message += f"📝 Всего записались: {len(data.get('users', {}))} чел.\n"
        message += "─" * 30 + "\n"
    
    await update.message.reply_text(message)

# Команда для просмотра конкретного фото
async def view_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("ℹ️ Использование: /view photo_1")
        return
    
    photo_id = args[0]
    if photo_id not in photos_data:
        await update.message.reply_text(f"❌ Фотография {photo_id} не найдена")
        return
    
    photo_data = photos_data[photo_id]
    
    # Проверяем наличие file_id
    if "photo" not in photo_data:
        await update.message.reply_text(f"❌ У фотографии {photo_id} отсутствует file_id")
        return
    
    # Формируем подпись с иконками
    caption = f"📸 Фото {photo_id}\n"
    if photo_data.get("confirmed_users"):
        caption += f"✅ Подтвержденные участники ({len(photo_data['confirmed_users'])}/{MAX_CONFIRMED_USERS}):\n"
        for i, user in enumerate(photo_data["confirmed_users"]):
            icon = get_user_icon(i)
            caption += f"{i+1}. {icon} {user['name']}\n"
    
    await update.message.reply_photo(
        photo=photo_data["photo"],
        caption=caption,
        reply_markup=get_photo_keyboard(photo_id, update.effective_user.id)
    )

# Команда для просмотра всех фото (для всех пользователей)
async def show_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📸 Показать все фотографии", callback_data="show_all_photos")],
        [InlineKeyboardButton("👥 Показать всех участников", callback_data="show_all_participants")]
    ]
    
    await update.message.reply_text(
        "Выберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Команда для проверки сохраненных фото
async def check_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только для администратора!")
        return
    
    if not photos_data:
        await update.message.reply_text("📭 Нет сохраненных фотографий")
        return
    
    message = "📚 Проверка сохраненных фотографий:\n\n"
    for idx, (photo_id, data) in enumerate(photos_data.items(), 1):
        has_file_id = "photo" in data
        has_users = len(data.get("users", {})) > 0
        has_confirmed = len(data.get("confirmed_users", [])) > 0
        
        status = "✅" if has_file_id else "❌"
        message += f"{idx}. {photo_id} {status}\n"
        message += f"   File ID: {'✅ Есть' if has_file_id else '❌ Нет'}\n"
        message += f"   Участники: {len(data.get('users', {}))}\n"
        message += f"   Подтверждено: {len(data.get('confirmed_users', []))}/{MAX_CONFIRMED_USERS}\n"
        message += "─" * 30 + "\n"
    
    await update.message.reply_text(message)
    
    # Пробуем отправить одну фотографию для проверки
    for photo_id, data in photos_data.items():
        if "photo" in data:
            try:
                await update.message.reply_photo(
                    photo=data["photo"],
                    caption=f"✅ Проверка: {photo_id} - файл сохранен",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🎯 Открыть", callback_data=f"view_{photo_id}")
                    ]])
                )
                break  # Отправляем только одну для проверки
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка отправки {photo_id}: {str(e)[:100]}")

# Команда для восстановления фото
async def restore_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только для администратора!")
        return
    
    if not photos_data:
        await update.message.reply_text("📭 Нет фотографий для восстановления")
        return
    
    # Создаем медиа-группу (альбом) с использованием InputMediaPhoto
    media_group = []
    valid_photos = []
    
    for photo_id, photo_data in photos_data.items():
        if "photo" not in photo_data:
            logger.warning(f"Фото {photo_id} не имеет file_id")
            continue
        
        confirmed_count = len(photo_data.get("confirmed_users", []))
        caption = (
            f"🔄 Восстановлено: {photo_id}\n"
            f"✅ Подтверждено: {confirmed_count}/{MAX_CONFIRMED_USERS}\n"
            f"📝 Записавшихся: {len(photo_data.get('users', {}))}"
        )
        
        media_group.append(
            InputMediaPhoto(
                media=photo_data['photo'],
                caption=caption
            )
        )
        valid_photos.append(photo_id)
        
        if len(media_group) >= 10:  # Ограничение Telegram
            break
    
    if not media_group:
        await update.message.reply_text("❌ Нет валидных фотографий для восстановления")
        return
    
    # Отправляем альбом
    try:
        await context.bot.send_media_group(
            chat_id=update.message.chat_id,
            media=media_group
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке альбома: {e}")
        # Если альбом не удался, отправляем по одному
        for media in media_group:
            try:
                await context.bot.send_photo(
                    chat_id=update.message.chat_id,
                    photo=media.media,
                    caption=media.caption
                )
            except Exception as e2:
                logger.error(f"Ошибка при отправке отдельного фото: {e2}")
    
    await update.message.reply_text(
        f"✅ Восстановлено {len(valid_photos)} фотографий\n"
        f"📸 ID фотографий: {', '.join(valid_photos[:5])}"
        f"{'...' if len(valid_photos) > 5 else ''}"
    )

# Вспомогательная функция для отображения меню управления участниками
async def admin_manage_participants(query, photo_id, context):
    """Отобразить меню управления участниками для администратора"""
    photo_data = photos_data.get(photo_id)
    if not photo_data:
        await query.answer("❌ Фотография не найдена!", show_alert=True)
        return
    
    user_id = query.from_user.id
    
    # Создаем клавиатуру с кнопками для удаления каждого участника
    keyboard = []
    
    # Показываем подтвержденных участников
    confirmed_users = photo_data.get("confirmed_users", [])
    if confirmed_users:
        keyboard.append([InlineKeyboardButton("✅ ПОДТВЕРЖДЕННЫЕ УЧАСТНИКИ", callback_data="admin_header")])
        for i, user in enumerate(confirmed_users):
            icon = get_user_icon(i)
            # Используем упрощенный формат callback_data
            keyboard.append([
                InlineKeyboardButton(
                    f"{icon} {user['name']} (ID: {user['user_id']})",
                    callback_data=f"adminshow_{photo_id.replace('photo_', '')}_{user['user_id']}"
                )
            ])
    
    # Показываем всех записавшихся (но не подтвержденных)
    all_users = list(photo_data.get("users", {}).items())
    if all_users:
        keyboard.append([InlineKeyboardButton("📝 ВСЕ ЗАПИСАВШИЕСЯ", callback_data="admin_header")])
        for uid, name in all_users:
            # Пропускаем тех, кто уже в подтвержденных
            if any(u["user_id"] == uid for u in confirmed_users):
                continue
            
            keyboard.append([
                InlineKeyboardButton(
                    f"⏳ {name} (ID: {uid})",
                    callback_data=f"adminshow_{photo_id.replace('photo_', '')}_{uid}"
                )
            ])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад к фото", callback_data=f"view_{photo_id}")])
    
    try:
        await query.edit_message_caption(
            caption=f"👑 Управление участниками для фото {photo_id}\n"
                   f"Выберите участника для действий:\n\n"
                   f"📊 Статистика:\n"
                   f"• Подтверждено: {len(confirmed_users)}/{MAX_CONFIRMED_USERS}\n"
                   f"• Всего записей: {len(photo_data.get('users', {}))}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        # Если не удалось изменить сообщение, отправляем новое
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"👑 Управление участниками для фото {photo_id}\n"
                 f"Выберите участника для действий:\n\n"
                 f"📊 Статистика:\n"
                 f"• Подтверждено: {len(confirmed_users)}/{MAX_CONFIRMED_USERS}\n"
                 f"• Всего записей: {len(photo_data.get('users', {}))}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# Обработка нажатий на кнопки
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    # 1. Обработка глобальных действий
    if data == "confirm_reset_all":
        if not is_admin(user_id):
            await query.answer("❌ Только для администратора!", show_alert=True)
            return
        
        count = len(photos_data)
        photos_data.clear()
        save_photos_data()
        await query.edit_message_text(f"✅ Все данные сброшены! Удалено {count} фотографий.")
        return
    
    elif data == "cancel_reset":
        await query.edit_message_text("❌ Сброс данных отменен")
        return
    
    elif data == "show_all_photos":
        if not photos_data:
            await query.edit_message_text("📭 Нет добавленных фотографий")
            return
        
        try:
            await query.delete_message()
        except Exception as e:
            logger.error(f"Не удалось удалить сообщение: {e}")
        
        await send_photo_album(query, context)
        return
    
    elif data == "show_all_participants":
        if not photos_data:
            await query.edit_message_text("📭 Нет добавленных фотографий")
            return
        
        message = "👥 Все участники:\n\n"
        for photo_id, photo_data in photos_data.items():
            message += f"📸 {photo_id}:\n"
            
            if photo_data.get("confirmed_users"):
                message += "✅ Подтвержденные:\n"
                for i, user in enumerate(photo_data["confirmed_users"]):
                    icon = get_user_icon(i)
                    message += f"   {i+1}. {icon} {user['name']}\n"
            
            if photo_data.get("users"):
                message += "📝 Все записавшиеся:\n"
                for idx, (uid, name) in enumerate(photo_data["users"].items(), 1):
                    is_confirmed = any(u["user_id"] == uid for u in photo_data.get("confirmed_users", []))
                    if is_confirmed:
                        position = next((i for i, u in enumerate(photo_data.get("confirmed_users", [])) if u["user_id"] == uid), -1)
                        icon = get_user_icon(position)
                        status = f"{icon} Подтвержден"
                    else:
                        status = "⏳ Ожидает"
                    message += f"   {idx}. {name} ({status})\n"
            
            message += "─" * 30 + "\n"
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    elif data == "back_to_main":
        keyboard = [
            [InlineKeyboardButton("📸 Показать все фотографии", callback_data="show_all_photos")],
            [InlineKeyboardButton("👥 Показать всех участников", callback_data="show_all_participants")]
        ]
        
        await query.edit_message_text(
            f"📸 Этот бот позволяет записывать имена под фотографиями.\n"
            f"📋 Новые правила:\n"
            f"1. Каждый может записать имя под фото\n"
            f"2. Каждый может подтвердить участие ТОЛЬКО 1 раз под каждой фото\n"
            f"3. Теперь до {MAX_CONFIRMED_USERS} человек могут подтвердить участие под каждой фото!\n"
            f"4. Первые 2 участника получают иконку ☀️\n"
            f"5. Следующие 2 участника получают иконку 🌙\n"
            f"6. Вы можете удалить свое имя и записаться заново\n"
            f"7. Администраторы могут удалять участников при необходимости\n"
            f"Используйте кнопки ниже для навигации:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    elif data.startswith("view_"):
        photo_id = data.replace("view_", "")
        if photo_id not in photos_data:
            await query.answer("❌ Фотография не найдена!", show_alert=True)
            return
        
        photo_data = photos_data[photo_id]
        
        if "photo" not in photo_data:
            await query.answer("❌ Фотография повреждена!", show_alert=True)
            return
        
        caption = f"📸 Фото {photo_id}\n"
        if photo_data.get("confirmed_users"):
            caption += f"✅ Подтвержденные участники ({len(photo_data['confirmed_users'])}/{MAX_CONFIRMED_USERS}):\n"
            for i, user in enumerate(photo_data["confirmed_users"]):
                icon = get_user_icon(i)
                caption += f"{i+1}. {icon} {user['name']}\n"
        
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=photo_data["photo"],
            caption=caption,
            reply_markup=get_photo_keyboard(photo_id, user_id)
        )
        return
    
    # 2. Обработка действий администратора
    elif data.startswith("admindeleteok_"):
        parts = data.replace("admindeleteok_", "").split("_")
        if len(parts) < 2:
            await query.answer("❌ Ошибка данных!", show_alert=True)
            return
        
        photo_id = f"photo_{parts[0]}"
        target_user_id = int(parts[1])
        
        if not is_admin(user_id):
            await query.answer("❌ Только для администратора!", show_alert=True)
            return
        
        if photo_id not in photos_data:
            await query.answer("❌ Фотография не найдена!", show_alert=True)
            return
        
        photo_data = photos_data[photo_id]
        user_name = photo_data.get("users", {}).get(target_user_id)
        
        if not user_name:
            await query.answer("❌ Участник не найден!", show_alert=True)
            return
        
        deleted_user_name = user_name
        
        # Удаляем из подтвержденных
        confirm_removed = False
        if "confirmed_users" in photo_data:
            before_confirm_count = len(photo_data["confirmed_users"])
            photo_data["confirmed_users"] = [
                user for user in photo_data["confirmed_users"] 
                if user["user_id"] != target_user_id
            ]
            after_confirm_count = len(photo_data["confirmed_users"])
            confirm_removed = before_confirm_count > after_confirm_count
        
        # Удаляем из списка пользователей
        user_removed = False
        if "users" in photo_data and target_user_id in photo_data["users"]:
            del photo_data["users"][target_user_id]
            user_removed = True
        
        save_photos_data()
        
        await query.answer(f"✅ Участник '{deleted_user_name}' удален администратором!", show_alert=True)
        
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"👑 Участник '{deleted_user_name}' удален администратором из фото {photo_id}.\n"
                 f"{'✅ Снято подтверждение' if confirm_removed else ''}\n"
                 f"{'✅ Удалено имя' if user_removed else ''}"
        )
        
        await admin_manage_participants(query, photo_id, context)
        return
    
    elif data.startswith("adminunconfirmok_"):
        parts = data.replace("adminunconfirmok_", "").split("_")
        if len(parts) < 2:
            await query.answer("❌ Ошибка данных!", show_alert=True)
            return
        
        photo_id = f"photo_{parts[0]}"
        target_user_id = int(parts[1])
        
        if not is_admin(user_id):
            await query.answer("❌ Только для администратора!", show_alert=True)
            return
        
        if photo_id not in photos_data:
            await query.answer("❌ Фотография не найдена!", show_alert=True)
            return
        
        photo_data = photos_data[photo_id]
        user_name = photo_data.get("users", {}).get(target_user_id)
        
        if not user_name:
            await query.answer("❌ Участник не найден!", show_alert=True)
            return
        
        # Удаляем из подтвержденных
        before_count = len(photo_data.get("confirmed_users", []))
        photo_data["confirmed_users"] = [
            user for user in photo_data["confirmed_users"] 
            if user["user_id"] != target_user_id
        ]
        after_count = len(photo_data["confirmed_users"])
        
        if before_count == after_count:
            await query.answer("❌ Участник не был подтвержден!", show_alert=True)
            return
        
        save_photos_data()
        
        await query.answer(f"✅ Подтверждение снято с участника '{user_name}'!", show_alert=True)
        
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"ℹ️ Администратор снял подтверждение с участника '{user_name}' под фото {photo_id}.\n"
                 f"✅ Теперь {after_count}/{MAX_CONFIRMED_USERS} подтвержденных участников.\n"
                 f"📝 Место освободилось для нового участника!"
        )
        
        await admin_manage_participants(query, photo_id, context)
        return
    
    elif data.startswith("admindelete_"):
        parts = data.replace("admindelete_", "").split("_")
        if len(parts) < 2:
            await query.answer("❌ Ошибка данных!", show_alert=True)
            return
        
        photo_id = f"photo_{parts[0]}"
        target_user_id = int(parts[1])
        
        if not is_admin(user_id):
            await query.answer("❌ Только для администратора!", show_alert=True)
            return
        
        if photo_id not in photos_data:
            await query.answer("❌ Фотография не найдена!", show_alert=True)
            return
        
        photo_data = photos_data[photo_id]
        user_name = photo_data.get("users", {}).get(target_user_id)
        
        if not user_name:
            await query.answer("❌ Участник не найден!", show_alert=True)
            return
        
        # Подтверждение удаления
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, удалить навсегда", 
                                   callback_data=f"admindeleteok_{photo_id.replace('photo_', '')}_{target_user_id}"),
                InlineKeyboardButton("❌ Отмена", 
                                   callback_data=f"adminshow_{photo_id.replace('photo_', '')}_{target_user_id}")
            ]
        ]
        
        await query.edit_message_caption(
            caption=f"⚠️ ВНИМАНИЕ: Удаление участника!\n\n"
                   f"📸 Фото: {photo_id}\n"
                   f"👤 Имя: {user_name}\n"
                   f"🆔 ID: {target_user_id}\n\n"
                   f"Это действие:\n"
                   f"• Удалит участника из списка\n"
                   f"• Удалит подтверждение (если есть)\n"
                   f"• Нельзя будет отменить\n\n"
                   f"Вы уверены?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    elif data.startswith("adminunconfirm_"):
        parts = data.replace("adminunconfirm_", "").split("_")
        if len(parts) < 2:
            await query.answer("❌ Ошибка данных!", show_alert=True)
            return
        
        photo_id = f"photo_{parts[0]}"
        target_user_id = int(parts[1])
        
        if not is_admin(user_id):
            await query.answer("❌ Только для администратора!", show_alert=True)
            return
        
        if photo_id not in photos_data:
            await query.answer("❌ Фотография не найдена!", show_alert=True)
            return
        
        photo_data = photos_data[photo_id]
        user_name = photo_data.get("users", {}).get(target_user_id)
        
        if not user_name:
            await query.answer("❌ Участник не найден!", show_alert=True)
            return
        
        # Проверяем, является ли пользователь подтвержденным
        is_confirmed = any(u["user_id"] == target_user_id for u in photo_data.get("confirmed_users", []))
        
        if not is_confirmed:
            await query.answer("❌ Этот участник не является подтвержденным!", show_alert=True)
            return
        
        # Подтверждение снятия
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, снять подтверждение", 
                                   callback_data=f"adminunconfirmok_{photo_id.replace('photo_', '')}_{target_user_id}"),
                InlineKeyboardButton("❌ Отмена", 
                                   callback_data=f"adminshow_{photo_id.replace('photo_', '')}_{target_user_id}")
            ]
        ]
        
        await query.edit_message_caption(
            caption=f"⚠️ Снятие подтверждения:\n\n"
                   f"📸 Фото: {photo_id}\n"
                   f"👤 Имя: {user_name}\n"
                   f"🆔 ID: {target_user_id}\n\n"
                   f"Это действие:\n"
                   f"• Удалит участника из подтвержденных\n"
                   f"• Оставит имя в списке\n"
                   f"• Освободит место для другого участника\n\n"
                   f"Вы уверены?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    elif data.startswith("adminshow_"):
        parts = data.replace("adminshow_", "").split("_")
        if len(parts) < 2:
            await query.answer("❌ Ошибка данных!", show_alert=True)
            return
        
        photo_id = f"photo_{parts[0]}"
        target_user_id = int(parts[1])
        
        if not is_admin(user_id):
            await query.answer("❌ Только для администратора!", show_alert=True)
            return
        
        if photo_id not in photos_data:
            await query.answer("❌ Фотография не найдена!", show_alert=True)
            return
        
        photo_data = photos_data[photo_id]
        user_name = photo_data.get("users", {}).get(target_user_id)
        
        if not user_name:
            await query.answer("❌ Участник не найден!", show_alert=True)
            return
        
        # Проверяем, является ли пользователь подтвержденным
        is_confirmed = any(u["user_id"] == target_user_id for u in photo_data.get("confirmed_users", []))
        
        # Если подтвержденный, находим его позицию
        position = -1
        if is_confirmed:
            position = next((i for i, u in enumerate(photo_data["confirmed_users"]) if u["user_id"] == target_user_id), -1)
        
        status = "✅ Подтвержден" if is_confirmed else "⏳ Ожидает подтверждения"
        icon = get_user_icon(position) if position >= 0 else "👤"
        
        # Клавиатура с действиями
        keyboard = []
        
        if is_confirmed:
            keyboard.append([
                InlineKeyboardButton(f"❌ Снять подтверждение", 
                                   callback_data=f"adminunconfirm_{photo_id.replace('photo_', '')}_{target_user_id}")
            ])
        
        keyboard.extend([
            [
                InlineKeyboardButton(f"🗑️ Удалить участника", 
                                   callback_data=f"admindelete_{photo_id.replace('photo_', '')}_{target_user_id}"),
                InlineKeyboardButton("🔙 Назад", 
                                   callback_data=f"admin_manage_{photo_id}")
            ]
        ])
        
        await query.edit_message_caption(
            caption=f"👑 Информация об участнике:\n\n"
                   f"📸 Фото: {photo_id}\n"
                   f"👤 Имя: {user_name}\n"
                   f"🆔 ID: {target_user_id}\n"
                   f"📊 Статус: {status}\n"
                   f"{f'{icon} Позиция: {position + 1}' if position >= 0 else ''}\n\n"
                   f"Выберите действие:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    elif data.startswith("admin_manage_"):
        photo_id = data.replace("admin_manage_", "")
        
        if not is_admin(user_id):
            await query.answer("❌ Только для администратора!", show_alert=True)
            return
        
        if photo_id not in photos_data:
            await query.answer("❌ Фотография не найдена!", show_alert=True)
            return
        
        await admin_manage_participants(query, photo_id, context)
        return
    
    # 3. Обработка действий пользователя
    elif data.startswith("status_"):
        await query.answer("Это информационная кнопка", show_alert=False)
        return
    
    elif data.startswith("delete_my_name_"):
        photo_id = data.replace("delete_my_name_", "")
        
        if photo_id not in photos_data:
            await query.answer("❌ Фотография не найдена!", show_alert=True)
            return
        
        photo_data = photos_data[photo_id]
        user_name = photo_data.get("users", {}).get(user_id)
        
        if not user_name:
            await query.answer("❌ У вас нет записанного имени!", show_alert=True)
            return
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_{photo_id}"),
                InlineKeyboardButton("❌ Нет, оставить", callback_data=f"cancel_delete_{photo_id}")
            ]
        ]
        
        await query.message.reply_text(
            f"⚠️ Вы уверены, что хотите удалить свое имя '{user_name}'?\n\n"
            f"После удаления:\n"
            f"• Вы сможете записаться заново под этой фотографией\n"
            f"• Освободится место для других участников\n"
            f"• Вы потеряете статус подтвержденного участника (если он был)",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    elif data.startswith("confirm_delete_"):
        photo_id = data.replace("confirm_delete_", "")
        
        if photo_id not in photos_data:
            await query.answer("❌ Фотография не найдена!", show_alert=True)
            return
        
        photo_data = photos_data[photo_id]
        user_name = photo_data.get("users", {}).get(user_id)
        
        if not user_name:
            await query.answer("❌ У вас нет записанного имени!", show_alert=True)
            return
        
        # Удаляем из подтвержденных
        if "confirmed_users" in photo_data:
            photo_data["confirmed_users"] = [
                user for user in photo_data["confirmed_users"] 
                if user["user_id"] != user_id
            ]
        
        # Удаляем из списка пользователей
        if "users" in photo_data and user_id in photo_data["users"]:
            del photo_data["users"][user_id]
        
        save_photos_data()
        
        # Обновляем сообщение с фото
        caption = f"📸 Фото {photo_id}\n"
        if photo_data.get("confirmed_users"):
            caption += f"✅ Подтвержденные участники ({len(photo_data['confirmed_users'])}/{MAX_CONFIRMED_USERS}):\n"
            for i, user in enumerate(photo_data["confirmed_users"]):
                icon = get_user_icon(i)
                caption += f"{i+1}. {icon} {user['name']}\n"
        
        try:
            await query.edit_message_caption(
                caption=caption,
                reply_markup=get_photo_keyboard(photo_id, user_id)
            )
        except:
            if "photo" in photo_data:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=photo_data["photo"],
                    caption=caption,
                    reply_markup=get_photo_keyboard(photo_id, user_id)
                )
        
        await query.answer(f"✅ Ваше имя '{user_name}' удалено!", show_alert=True)
        
        if len(photo_data.get("confirmed_users", [])) < MAX_CONFIRMED_USERS:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"ℹ️ Под фото {photo_id} освободилось место! Теперь {len(photo_data.get('confirmed_users', []))}/{MAX_CONFIRMED_USERS} подтвержденных."
            )
        return
    
    elif data.startswith("cancel_delete_"):
        photo_id = data.replace("cancel_delete_", "")
        await query.answer("❌ Удаление отменено", show_alert=True)
        return
    
    elif data == "admin_header":
        await query.answer("Раздел управления участниками", show_alert=False)
        return
    
    # 4. Обработка действий с конкретным фото (регистрация, подтверждение, показ)
    # Проверяем существование фото
    if "_" in data:
        parts = data.split("_", 1)
        action = parts[0]
        photo_id = parts[1]
    else:
        return
    
    if photo_id not in photos_data:
        await query.edit_message_caption(caption="❌ Эта фотография больше не доступна")
        return
    
    photo_data = photos_data[photo_id]
    
    # Регистрация имени
    if action == "register":
        if user_id in photo_data.get("users", {}):
            await query.answer("⚠️ Вы уже записали свое имя!", show_alert=True)
            return
        
        await query.message.reply_text(
            "📝 Введите ваше имя (одним сообщением):\n"
            "⚠️ Внимание: после ввода имени вы будете автоматически добавлены в список участников!"
        )
        context.user_data["awaiting_name"] = photo_id
        context.user_data["awaiting_user_id"] = user_id
        return
    
    # Подтверждение
    elif action == "confirm":
        if user_id not in photo_data.get("users", {}):
            await query.answer("❌ Сначала запишите свое имя!", show_alert=True)
            return
        
        if len(photo_data.get("confirmed_users", [])) >= MAX_CONFIRMED_USERS:
            await query.answer(f"❌ Уже есть {MAX_CONFIRMED_USERS} подтвержденных участника!", show_alert=True)
            await query.edit_message_reply_markup(reply_markup=get_photo_keyboard(photo_id, user_id))
            return
        
        if any(u["user_id"] == user_id for u in photo_data.get("confirmed_users", [])):
            await query.answer("❌ Вы уже подтвердили участие под этой фотографией!", show_alert=True)
            return
        
        user_name = photo_data["users"][user_id]
        
        if "confirmed_users" not in photo_data:
            photo_data["confirmed_users"] = []
        
        photo_data["confirmed_users"].append({
            "user_id": user_id,
            "name": user_name
        })
        
        save_photos_data()
        
        caption = f"📸 Фото {photo_id}\n"
        if photo_data.get("confirmed_users"):
            caption += f"✅ Подтвержденные участники ({len(photo_data['confirmed_users'])}/{MAX_CONFIRMED_USERS}):\n"
            for i, user in enumerate(photo_data["confirmed_users"]):
                icon = get_user_icon(i)
                caption += f"{i+1}. {icon} {user['name']}\n"
        
        await query.edit_message_caption(
            caption=caption,
            reply_markup=get_photo_keyboard(photo_id, user_id)
        )
        
        position = len(photo_data["confirmed_users"]) - 1
        icon = get_user_icon(position)
        
        await query.answer(f"{icon} Вы подтвердили участие как '{user_name}' (позиция {position + 1})!", show_alert=True)
        
        if len(photo_data["confirmed_users"]) == MAX_CONFIRMED_USERS:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"🎉 Под фото {photo_id} достигнут лимит в {MAX_CONFIRMED_USERS} подтвержденных участника!"
            )
        return
    
    # Показать участников
    elif action == "show":
        caption = f"📸 Фото {photo_id}\n"
        
        if not photo_data.get("confirmed_users"):
            caption += "❌ Нет подтвержденных участников\n"
        else:
            caption += f"✅ Подтвержденные участники ({len(photo_data['confirmed_users'])}/{MAX_CONFIRMED_USERS}):\n"
            for i, user in enumerate(photo_data["confirmed_users"]):
                icon = get_user_icon(i)
                caption += f"{i+1}. {icon} {user['name']}\n"
        
        total_registered = len(photo_data.get("users", {}))
        confirmed_count = len(photo_data.get("confirmed_users", []))
        
        caption += f"\n📊 Статистика:\n"
        caption += f"• Подтверждено: {confirmed_count}/{MAX_CONFIRMED_USERS}\n"
        caption += f"• Всего записались: {total_registered} чел."
        
        if photo_data.get("users"):
            caption += f"\n\n📝 Все записавшиеся:\n"
            for idx, (uid, name) in enumerate(photo_data["users"].items(), 1):
                is_confirmed = any(u["user_id"] == uid for u in photo_data.get("confirmed_users", []))
                if is_confirmed:
                    position = next((i for i, u in enumerate(photo_data.get("confirmed_users", [])) if u["user_id"] == uid), -1)
                    icon = get_user_icon(position)
                    status = f"{icon} Подтвержден"
                else:
                    status = "⏳ Ожидает"
                caption += f"{idx}. {name} ({status})\n"
        
        await query.edit_message_caption(
            caption=caption,
            reply_markup=get_photo_keyboard(photo_id, user_id)
        )
        await query.answer("👥 Список участников обновлен")
        return

# Обработка текстовых сообщений (для ввода имени)
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "awaiting_name" not in context.user_data:
        return
    
    photo_id = context.user_data.pop("awaiting_name")
    user_id = context.user_data.pop("awaiting_user_id", update.effective_user.id)
    
    if photo_id not in photos_data:
        await update.message.reply_text("❌ Фотография больше не доступна")
        return
    
    user_name = update.message.text.strip()
    if not user_name:
        await update.message.reply_text("❌ Имя не может быть пустым!")
        return
    
    # 1. Проверяем длину имени
    if len(user_name) > 20:
        await update.message.reply_text("❌ Имя слишком длинное! Максимум 20 символов.")
        return
    
    # 2. Проверяем минимальную длину
    if len(user_name) < 2:
        await update.message.reply_text("❌ Имя слишком короткое! Минимум 2 символа.")
        return
    
    # 3. Очищаем от HTML/XML тегов (базовая защита)
    import re
    # Удаляем все HTML/XML теги
    user_name_clean = re.sub(r'<[^>]+>', '', user_name)
    
    # 4. Удаляем опасные символы и ограничиваем набор допустимых символов
    # Разрешаем: буквы (включая русские), цифры, пробелы, дефисы, апострофы, точки
    user_name_clean = re.sub(r'[^\w\s\-\.\'\u0400-\u04FF]', '', user_name_clean, flags=re.UNICODE)
    
    # 5. Удаляем лишние пробелы
    user_name_clean = ' '.join(user_name_clean.split())
    
    # 6. Проверяем, что после очистки имя не стало пустым
    if not user_name_clean:
        await update.message.reply_text("❌ Имя содержит недопустимые символы! Используйте только буквы, цифры и пробелы.")
        return
    
    # 7. Проверяем длину после очистки
    if len(user_name_clean) > 20:
        user_name_clean = user_name_clean[:20]
    
    # 8. Экранируем специальные символы для безопасности
    # Заменяем потенциально опасные символы
    escape_map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }
    
    def escape_html(text):
        """Экранирует HTML символы в тексте"""
        return ''.join(escape_map.get(c, c) for c in text)
    
    user_name_safe = escape_html(user_name_clean)
    
    photo_data = photos_data[photo_id]
    
    # Инициализируем словари, если их нет
    if "users" not in photo_data:
        photo_data["users"] = {}
    if "confirmed_users" not in photo_data:
        photo_data["confirmed_users"] = []
    
    # Сохраняем очищенное и безопасное имя пользователя
    photo_data["users"][user_id] = user_name_safe
    
    # Пытаемся автоматически подтвердить пользователя (если есть свободные места)
    confirmed_count = len(photo_data["confirmed_users"])
    user_already_confirmed = any(u["user_id"] == user_id for u in photo_data["confirmed_users"])
    
    if not user_already_confirmed and confirmed_count < MAX_CONFIRMED_USERS:
        # Автоматически подтверждаем пользователя
        photo_data["confirmed_users"].append({
            "user_id": user_id,
            "name": user_name_safe
        })
        confirmed_count += 1
        
        # Определяем позицию и иконку
        position = confirmed_count - 1
        icon = get_user_icon(position)
        
        await update.message.reply_text(
            f"✅ Имя '{user_name_safe}' сохранено и вы автоматически подтверждены как участник!\n"
            f"{icon} Вы занимаете {confirmed_count}/{MAX_CONFIRMED_USERS} места под этой фотографией (позиция {position + 1})."
        )
        
        # Уведомляем, если достигнут лимит
        if confirmed_count == MAX_CONFIRMED_USERS:
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=f"🎉 Под фото {photo_id} достигнут лимит в {MAX_CONFIRMED_USERS} подтвержденных участника!"
            )
    else:
        # Мест нет или пользователь уже подтвержден
        if user_already_confirmed:
            # Находим позицию подтвержденного пользователя
            position = next((i for i, u in enumerate(photo_data["confirmed_users"]) if u["user_id"] == user_id), -1)
            icon = get_user_icon(position) if position >= 0 else "✅"
            
            await update.message.reply_text(
                f"✅ Имя '{user_name_safe}' сохранено!\n"
                f"{icon} Вы уже были подтверждены ранее (позиция {position + 1 if position >= 0 else '?'})."
            )
        else:
            await update.message.reply_text(
                f"✅ Имя '{user_name_safe}' сохранено!\n"
                f"❌ Все места уже заняты ({MAX_CONFIRMED_USERS}/{MAX_CONFIRMED_USERS}). Вы находитесь в списке ожидания."
            )
    
    save_photos_data()

# Основная функция
def main():
    # Токен вашего бота
    TOKEN = "7756097473:AAF4dRN3b9VZVk62Ua3eB6keFDFAnIuCPUY"
    
    # Загружаем данные при старте
    load_admins()
    load_photos_data()
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_admin", add_admin))
    application.add_handler(CommandHandler("remove_admin", remove_admin))
    application.add_handler(CommandHandler("list_admins", list_admins))
    application.add_handler(CommandHandler("id", get_id))
    application.add_handler(CommandHandler("admins", show_admins))
    application.add_handler(CommandHandler("clear_names", clear_names))
    application.add_handler(CommandHandler("reset", reset_data))
    application.add_handler(CommandHandler("list", list_photos))
    application.add_handler(CommandHandler("view", view_photo))
    application.add_handler(CommandHandler("show", show_all))
    application.add_handler(CommandHandler("check_photos", check_photos))
    application.add_handler(CommandHandler("restore", restore_photos))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Запускаем бота
    print("=" * 50)
    print("🤖 Бот запущен!")
    print(f"👑 Администраторов: {len(admins)}")
    print(f"📸 Фотографий в памяти: {len(photos_data)}")
    print(f"👥 Максимум подтвержденных участников: {MAX_CONFIRMED_USERS}")
    
    # Проверяем целостность загруженных фото
    valid_photos_count = sum(1 for data in photos_data.values() if "photo" in data)
    print(f"✅ Валидных фото (с file_id): {valid_photos_count}")
    
    print("=" * 50)
    print("🌟 НОВЫЕ ФИЧИ:")
    print(f"  • До {MAX_CONFIRMED_USERS} подтвержденных участников под каждой фото")
    print("  • Первые 2 участника получают иконку ☀️")
    print("  • Следующие 2 участника получают иконку 🌙")
    print("  • 👑 АДМИНЫ могут удалять участников через кнопку 'Управление участниками'")
    print("=" * 50)
    print("Доступные команды:")
    print("  /start - показать информацию")
    print("  /add_admin <ID> - добавить администратора")
    print("  /remove_admin <ID> - удалить администратора")
    print("  /list_admins - показать список администраторов")
    print("  /id - получить свой ID")
    print("  /check_photos - проверить сохраненные фото")
    print("  /restore - восстановить все фото")
    print("  /clear_names - очистить имена участников")
    print("  /reset - полный сброс всех данных")
    print("  /list - список всех фото (админы)")
    print("  /view photo_X - просмотреть конкретное фото")
    print("  /show - показать все фото и участников")
    print("=" * 50)
    print("📸 Фото сохраняются после перезапуска бота!")
    print("=" * 50)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
