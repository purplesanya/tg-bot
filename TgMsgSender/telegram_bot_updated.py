"""
Telegram Control Bot - Notification and Monitoring Version
"""

import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters
)
from database import SessionLocal, User, Task, UserChat
from dotenv import load_dotenv

# --- Setup ---
load_dotenv('.env')
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')  # For granting admin rights

# --- States for ConversationHandler ---
ADMIN_PASSWORD_STATE = range(1)

# --- FIX: Internationalization (i18n) ---
translations = {
    'en': {
        "not_authorized": "⚠️ Not Authorized\n\nTo use this bot, you must first log in via the web interface. If you have recently logged out, please log back in to re-authorize the bot.",
        "welcome": "👋 Welcome, {first_name}!\n\nThis bot helps you monitor your scheduled messages.\n\nUse the web application to create or manage your tasks.",
        "my_tasks": "📋 My Tasks",
        "archived_tasks": "🗄️ Archived Tasks",
        "statistics": "📊 Statistics",
        "settings": "⚙️ Settings",
        "admin_panel": "👑 Admin Panel",
        "help_text": "🤖 Bot Help & Commands\n\nThis bot is for monitoring tasks created in the web app.\n\nAvailable Commands:\n/start - Shows the main menu.\n/tasks - View your list of active and paused tasks.\n/archived - View archived tasks.\n/stats - See your overall task statistics.\n/settings - Configure your preferences.\n\nPlease Note:\nTask creation and editing must be done through the web application.",
        "admin_web_feature": "👑 Admin Panel\n\nThis feature is available in the web application. Please log in to access the admin dashboard.",
        "no_tasks": "🔭 No Tasks Found\n\nYou haven't created any active tasks yet. Please visit the web app to create your first task.",
        "your_tasks_header": "📋 Your Tasks ({count} total)\n\n",
        "last_run": "Last: {time}",
        "not_executed_yet": "Not executed yet",
        "next_run": "Next: {time}",
        "schedule_info": "Every {value} {unit}",
        "files_info": "\n📎 {count} files",
        "chats_info": "👥 {count} chats",
        "execution_info": "🔄 Executed {count} times",
        "no_archived_tasks": "🗄️ No Archived Tasks\n\nYou don't have any archived tasks.",
        "archived_header": "🗄️ Archived Tasks ({count} total)\n\n",
        "was_schedule": "Was: Every {value} {unit}",
        "last_run_archived": "Last run: {time}",
        "never_executed": "Never executed",
        "stats_header": "📊 Your Statistics\n\n",
        "total_tasks_stat": "📋 Total Tasks: {count}",
        "active_stat": "🟢 Active: {count}",
        "paused_stat": "⏸️ Paused: {count}",
        "archived_stat": "🗄️ Archived: {count}",
        "total_executions_stat": "🔄 Total Executions: {count}",
        "settings_header": "⚙️ Settings\n\nConfigure your bot preferences below.",
        "notifications": "Notifications",
        "simplified_login": "Simplified Login",
        "language": "Language",
        "back_to_menu": "🔙 Back to Menu",
        "enabled": "🔔 Enabled",
        "disabled": "🔕 Disabled",
        "simplified_enabled": "✅ Enabled",
        "simplified_disabled": "❌ Disabled",
        "select_language": "Please select your language:",
        "lang_changed": "✅ Language has been set to {lang_name}.",
    },
    'ru': {
        "not_authorized": "⚠️ Нет авторизации\n\nЧтобы использовать этого бота, вы должны сначала войти через веб-интерфейс. Если вы недавно вышли, пожалуйста, войдите снова, чтобы повторно авторизовать бота.",
        "welcome": "👋 Добро пожаловать, {first_name}!\n\nЭтот бот поможет вам отслеживать ваши запланированные сообщения.\n\nИспользуйте веб-приложение для создания и управления вашими задачами.",
        "my_tasks": "📋 Мои задачи",
        "archived_tasks": "🗄️ Архивные задачи",
        "statistics": "📊 Статистика",
        "settings": "⚙️ Настройки",
        "admin_panel": "👑 Панель администратора",
        "help_text": "🤖 Помощь по боту и команды\n\nЭтот бот предназначен для мониторинга задач, созданных в веб-приложении.\n\nДоступные команды:\n/start - Показать главное меню.\n/tasks - Просмотр списка активных и приостановленных задач.\n/archived - Просмотр архивных задач.\n/stats - Просмотр вашей общей статистики по задачам.\n/settings - Настроить ваши предпочтения.\n\nОбратите внимание:\nСоздание и редактирование задач должно производиться через веб-приложение.",
        "admin_web_feature": "👑 Панель администратора\n\nЭта функция доступна в веб-приложении. Пожалуйста, войдите, чтобы получить доступ к панели администратора.",
        "no_tasks": "🔭 Задачи не найдены\n\nВы еще не создали ни одной активной задачи. Пожалуйста, посетите веб-приложение, чтобы создать свою первую задачу.",
        "your_tasks_header": "📋 Ваши задачи (всего: {count})\n\n",
        "last_run": "Последний запуск: {time}",
        "not_executed_yet": "Еще не выполнялась",
        "next_run": "Следующий запуск: {time}",
        "schedule_info": "Каждые {value} {unit}",
        "files_info": "\n📎 Файлов: {count}",
        "chats_info": "👥 Чатов: {count}",
        "execution_info": "🔄 Выполнено раз: {count}",
        "no_archived_tasks": "🗄️ Нет архивных задач\n\nУ вас нет архивных задач.",
        "archived_header": "🗄️ Архивные задачи (всего: {count})\n\n",
        "was_schedule": "Было: Каждые {value} {unit}",
        "last_run_archived": "Последний запуск: {time}",
        "never_executed": "Никогда не выполнялась",
        "stats_header": "📊 Ваша статистика\n\n",
        "total_tasks_stat": "📋 Всего задач: {count}",
        "active_stat": "🟢 Активные: {count}",
        "paused_stat": "⏸️ На паузе: {count}",
        "archived_stat": "🗄️ В архиве: {count}",
        "total_executions_stat": "🔄 Всего выполнений: {count}",
        "settings_header": "⚙️ Настройки\n\nНастройте ваши предпочтения для бота ниже.",
        "notifications": "Уведомления",
        "simplified_login": "Упрощенный вход",
        "language": "Язык",
        "back_to_menu": "🔙 Назад в меню",
        "enabled": "🔔 Включены",
        "disabled": "🔕 Отключены",
        "simplified_enabled": "✅ Включен",
        "simplified_disabled": "❌ Отключен",
        "select_language": "Пожалуйста, выберите ваш язык:",
        "lang_changed": "✅ Язык изменен на {lang_name}.",
    }
}
LANGUAGES = {'en': 'English', 'ru': 'Русский'}


def get_text(key, lang_code='en'):
    """Fetches a translation string."""
    return translations.get(lang_code, translations['en']).get(key, key)


# --- End of FIX ---

# --- Helpers ---
def get_user(update: Update, db_session=None):
    """Fetches the user from the database based on their Telegram ID."""
    db = db_session or SessionLocal()
    user = db.query(User).filter_by(telegram_id=update.effective_user.id).first()
    if not db_session:
        db.close()
    return user


def format_time_ago(dt, lang):
    """Format datetime to human readable time ago"""
    # This part is complex to translate well with pluralization, keeping it simple for now.
    if not dt:
        return "Never" if lang == 'en' else "Никогда"

    now = datetime.utcnow()
    diff = now - dt

    if diff.days > 0:
        return f"{diff.days}d ago" if lang == 'en' else f"{diff.days} д. назад"
    elif diff.seconds >= 3600:
        return f"{diff.seconds // 3600}h ago" if lang == 'en' else f"{diff.seconds // 3600} ч. назад"
    elif diff.seconds >= 60:
        return f"{diff.seconds // 60}m ago" if lang == 'en' else f"{diff.seconds // 60} м. назад"
    else:
        return "Just now" if lang == 'en' else "Только что"


def format_next_run(dt, lang):
    """Format next run time"""
    if not dt:
        return "Not scheduled" if lang == 'en' else "Не запланировано"

    now = datetime.utcnow()
    diff = dt - now

    if diff.days > 0:
        return f"in {diff.days}d" if lang == 'en' else f"через {diff.days} д."
    elif diff.seconds >= 3600:
        return f"in {diff.seconds // 3600}h" if lang == 'en' else f"через {diff.seconds // 3600} ч."
    elif diff.seconds >= 60:
        return f"in {diff.seconds // 60}m" if lang == 'en' else f"через {diff.seconds // 60} м."
    else:
        return "very soon" if lang == 'en' else "очень скоро"


async def is_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks if the user has authorized the bot by logging into the web app."""
    user = get_user(update)
    if user and user.is_bot_authorized:
        return True

    lang = user.language if user else 'en'
    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text=get_text("not_authorized", lang)
    )
    return False


# --- Main Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greets the user and shows the main menu."""
    if not await is_authorized(update, context):
        return

    user = get_user(update)
    lang = user.language

    keyboard = [
        [InlineKeyboardButton(get_text("my_tasks", lang), callback_data="menu_tasks")],
        [InlineKeyboardButton(get_text("archived_tasks", lang), callback_data="menu_archived")],
        [InlineKeyboardButton(get_text("statistics", lang), callback_data="menu_stats")],
        [InlineKeyboardButton(get_text("settings", lang), callback_data="menu_settings")],
    ]
    if user and user.is_admin:
        keyboard.append([InlineKeyboardButton(get_text("admin_panel", lang), callback_data="menu_admin")])

    await update.message.reply_text(
        get_text("welcome", lang).format(first_name=update.effective_user.first_name),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provides help information about the bot's commands."""
    if not await is_authorized(update, context):
        return
    user = get_user(update)
    await update.message.reply_text(get_text("help_text", user.language))


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles callbacks from the main menu."""
    query = update.callback_query
    await query.answer()

    if not await is_authorized(update, context):
        return

    user = get_user(update)
    lang = user.language
    action = query.data.split('_')[1]

    if action == 'tasks':
        await view_tasks(update, context)
    elif action == 'archived':
        await view_archived_tasks(update, context)
    elif action == 'stats':
        await view_stats(update, context)
    elif action == 'settings':
        await settings_menu(update, context)
    elif action == 'admin':
        await query.edit_message_text(
            text=get_text("admin_web_feature", lang)
        )
    elif action == 'main':
        keyboard = [
            [InlineKeyboardButton(get_text("my_tasks", lang), callback_data="menu_tasks")],
            [InlineKeyboardButton(get_text("archived_tasks", lang), callback_data="menu_archived")],
            [InlineKeyboardButton(get_text("statistics", lang), callback_data="menu_stats")],
            [InlineKeyboardButton(get_text("settings", lang), callback_data="menu_settings")],
        ]
        if user and user.is_admin:
            keyboard.append([InlineKeyboardButton(get_text("admin_panel", lang), callback_data="menu_admin")])

        await query.edit_message_text(
            get_text("welcome", lang).format(first_name=update.effective_user.first_name),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# --- Admin Commands (unchanged) ---
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to grant admin privileges to another user."""
    if not await is_authorized(update, context):
        return ConversationHandler.END

    db = SessionLocal()
    admin_user = db.query(User).filter_by(telegram_id=update.effective_user.id).first()

    if not admin_user or not admin_user.is_admin:
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        db.close()
        return ConversationHandler.END

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /admin @username")
        db.close()
        return ConversationHandler.END

    target_username = context.args[0].lstrip('@')
    target_user = db.query(User).filter_by(username=target_username).first()

    if not target_user:
        await update.message.reply_text(f"Could not find a user with the username @{target_username}.")
        db.close()
        return ConversationHandler.END

    if not ADMIN_PASSWORD:
        await update.message.reply_text("⚠️ Admin password is not set on the server. Cannot proceed.")
        db.close()
        return ConversationHandler.END

    context.user_data['target_user_id'] = target_user.id
    await update.message.reply_text("Please enter the admin password to confirm.")
    db.close()
    return ADMIN_PASSWORD_STATE


async def receive_admin_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Checks the admin password and grants privileges if correct."""
    password_attempt = update.message.text
    target_user_id = context.user_data.get('target_user_id')

    if not target_user_id:
        await update.message.reply_text("Session expired. Please start over with /admin.")
        return ConversationHandler.END

    if password_attempt == ADMIN_PASSWORD:
        db = SessionLocal()
        target_user = db.query(User).filter_by(id=target_user_id).first()
        if target_user:
            target_user.is_admin = True
            db.commit()
            await update.message.reply_text(f"✅ Success! @{target_user.username} has been granted admin privileges.")
        else:
            await update.message.reply_text("An error occurred. Could not find the target user.")
        db.close()
    else:
        await update.message.reply_text("⛔ Incorrect password. Action cancelled.")

    del context.user_data['target_user_id']
    return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current conversation."""
    if 'target_user_id' in context.user_data:
        del context.user_data['target_user_id']
    await update.message.reply_text("Action cancelled.")
    return ConversationHandler.END


# --- Bot Features ---
async def view_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays a list of the user's tasks."""
    if not await is_authorized(update, context):
        return
    user = get_user(update)
    lang = user.language
    db = SessionLocal()
    tasks = db.query(Task).filter_by(user_id=user.id).filter(Task.status != 'archived').order_by(
        Task.created_at.desc()).all()
    db.close()

    message_sender = update.callback_query.edit_message_text if update.callback_query else update.message.reply_text

    if not tasks:
        await message_sender(
            text=get_text("no_tasks", lang)
        )
        return

    text = get_text("your_tasks_header", lang).format(count=len(tasks))
    await message_sender(text=text)

    chat_id = update.effective_chat.id

    for task in tasks[:10]:
        status_emoji = {'active': '🟢', 'paused': '⏸️'}.get(task.status, '⚪')

        task_name_display = f"{task.name}\n" if task.name else ""
        schedule_info = get_text("schedule_info", lang).format(value=task.interval_value, unit=task.interval_unit)
        files_info = get_text("files_info", lang).format(count=len(task.file_paths)) if task.file_paths else ""
        last_run_info = get_text("last_run", lang).format(
            time=format_time_ago(task.last_run, lang)) if task.last_run else get_text("not_executed_yet", lang)
        next_run_info = get_text("next_run", lang).format(
            time=format_next_run(task.next_run, lang)) if task.next_run else ""

        task_text = (
            f"{status_emoji} {task_name_display}"
            f"\"{task.message[:50]}{'...' if len(task.message) > 50 else ''}\"\n"
            f"⏱️ {schedule_info}\n"
            f"👥 {get_text('chats_info', lang).format(count=len(task.chat_ids))}{files_info}\n"
            f"🔄 {get_text('execution_info', lang).format(count=task.execution_count)}\n"
            f"🕐 {last_run_info}"
        )

        if next_run_info and task.status == 'active':
            task_text += f" | {next_run_info}"

        await context.bot.send_message(
            chat_id=chat_id,
            text=task_text
        )


async def view_archived_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays a list of archived tasks."""
    if not await is_authorized(update, context):
        return
    user = get_user(update)
    lang = user.language
    db = SessionLocal()
    tasks = db.query(Task).filter_by(user_id=user.id, status='archived').order_by(Task.updated_at.desc()).all()
    db.close()

    message_sender = update.callback_query.edit_message_text if update.callback_query else update.message.reply_text

    if not tasks:
        await message_sender(text=get_text("no_archived_tasks", lang))
        return

    text = get_text("archived_header", lang).format(count=len(tasks))
    await message_sender(text=text)

    chat_id = update.effective_chat.id

    for task in tasks[:10]:
        task_name_display = f"{task.name}\n" if task.name else ""
        schedule_info = get_text("was_schedule", lang).format(value=task.interval_value, unit=task.interval_unit)
        files_info = get_text("files_info", lang).format(count=len(task.file_paths)) if task.file_paths else ""
        last_run_info = get_text("last_run_archived", lang).format(
            time=format_time_ago(task.last_run, lang)) if task.last_run else get_text("never_executed", lang)

        task_text = (
            f"📦 {task_name_display}"
            f"\"{task.message[:50]}{'...' if len(task.message) > 50 else ''}\"\n"
            f"⏱️ {schedule_info}\n"
            f"👥 {get_text('chats_info', lang).format(count=len(task.chat_ids))}{files_info}\n"
            f"🔄 {get_text('execution_info', lang).format(count=task.execution_count)}\n"
            f"🕐 {last_run_info}"
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=task_text
        )


async def view_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows user statistics."""
    if not await is_authorized(update, context):
        return
    user = get_user(update)
    lang = user.language
    db = SessionLocal()
    tasks = db.query(Task).filter_by(user_id=user.id).all()
    db.close()

    total = len([t for t in tasks if t.status != 'archived'])
    active = sum(1 for t in tasks if t.status == 'active')
    paused = sum(1 for t in tasks if t.status == 'paused')
    archived = sum(1 for t in tasks if t.status == 'archived')
    executions = sum(t.execution_count for t in tasks)

    text = (
        f'{get_text("stats_header", lang)}\n'
        f'{get_text("total_tasks_stat", lang).format(count=total)}\n'
        f'{get_text("active_stat", lang).format(count=active)}\n'
        f'{get_text("paused_stat", lang).format(count=paused)}\n'
        f'{get_text("archived_stat", lang).format(count=archived)}\n'
        f'{get_text("total_executions_stat", lang).format(count=executions)}'
    )

    message_sender = update.callback_query.edit_message_text if update.callback_query else update.message.reply_text
    await message_sender(text=text)


async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=True):
    """Displays the settings menu."""
    if not await is_authorized(update, context):
        return

    user = get_user(update)
    lang = user.language

    notif_status = get_text("enabled", lang) if user.notifications_enabled else get_text("disabled", lang)
    login_status = get_text("simplified_enabled", lang) if user.simplified_login_enabled else get_text(
        "simplified_disabled", lang)

    keyboard = [
        [InlineKeyboardButton(f'{get_text("notifications", lang)}: {notif_status}', callback_data="toggle_notif")],
        [InlineKeyboardButton(f'{get_text("simplified_login", lang)}: {login_status}',
                              callback_data="toggle_simplified_login")],
        [InlineKeyboardButton(f'{get_text("language", lang)}: {LANGUAGES[lang]}', callback_data="set_lang_menu")],
        [InlineKeyboardButton(get_text("back_to_menu", lang), callback_data="menu_main")]
    ]

    text = get_text("settings_header", lang)

    message_sender = update.callback_query.edit_message_text if is_callback and update.callback_query else update.message.reply_text
    await message_sender(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# --- FIX: New handlers for language settings ---
async def language_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the language selection menu."""
    query = update.callback_query
    await query.answer()
    user = get_user(update)
    lang = user.language

    keyboard = [
        [InlineKeyboardButton("English 🇬🇧", callback_data="set_lang_en")],
        [InlineKeyboardButton("Русский 🇷🇺", callback_data="set_lang_ru")],
        [InlineKeyboardButton(get_text("back_to_menu", lang), callback_data="menu_settings_back")]
    ]
    await query.edit_message_text(
        text=get_text("select_language", lang),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets the user's language."""
    query = update.callback_query
    await query.answer()

    new_lang = query.data.split('_')[-1]  # 'en' or 'ru'

    db = SessionLocal()
    user = get_user(update, db_session=db)
    user.language = new_lang
    db.commit()
    db.close()

    await query.answer(get_text("lang_changed", new_lang).format(lang_name=LANGUAGES[new_lang]))
    await settings_menu(update, context)  # Go back to settings menu


# --- End of FIX ---

async def toggle_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggles the user's notification setting."""
    query = update.callback_query
    await query.answer()

    if not await is_authorized(update, context):
        return

    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=update.effective_user.id).first()
    user.notifications_enabled = not user.notifications_enabled
    db.commit()
    db.close()

    await settings_menu(update, context)


async def toggle_simplified_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggles the user's simplified login setting."""
    query = update.callback_query
    await query.answer()

    if not await is_authorized(update, context):
        return

    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=update.effective_user.id).first()
    if user:
        user.simplified_login_enabled = not user.simplified_login_enabled
        db.commit()
    db.close()

    await settings_menu(update, context)


def main():
    """Starts the bot."""
    app = Application.builder().token(BOT_TOKEN).build()

    admin_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('admin', admin_command)],
        states={
            ADMIN_PASSWORD_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_password)],
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)],
    )
    app.add_handler(admin_conv_handler)

    # Command Handlers
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('tasks', view_tasks))
    app.add_handler(CommandHandler('archived', view_archived_tasks))
    app.add_handler(CommandHandler('stats', view_stats))
    app.add_handler(CommandHandler('settings', lambda u, c: settings_menu(u, c, is_callback=False)))

    # Callback Query Handlers
    app.add_handler(CallbackQueryHandler(menu_handler, pattern='^menu_main$'))
    app.add_handler(CallbackQueryHandler(view_tasks, pattern='^menu_tasks$'))
    app.add_handler(CallbackQueryHandler(view_archived_tasks, pattern='^menu_archived$'))
    app.add_handler(CallbackQueryHandler(view_stats, pattern='^menu_stats$'))
    app.add_handler(CallbackQueryHandler(lambda u, c: settings_menu(u, c), pattern='^menu_settings$'))
    app.add_handler(CallbackQueryHandler(lambda u, c: settings_menu(u, c), pattern='^menu_settings_back$'))

    app.add_handler(CallbackQueryHandler(toggle_notifications, pattern='^toggle_notif$'))
    app.add_handler(CallbackQueryHandler(toggle_simplified_login, pattern='^toggle_simplified_login$'))

    # --- FIX: Add language handlers ---
    app.add_handler(CallbackQueryHandler(language_menu, pattern='^set_lang_menu$'))
    app.add_handler(CallbackQueryHandler(set_language, pattern='^set_lang_'))
    # --- End of FIX ---

    print("🤖 Bot is running...")
    app.run_polling()


if __name__ == '__main__':
    main()
