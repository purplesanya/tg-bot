"""
Telegram Control Bot - Notification and Monitoring Version
"""
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from database import SessionLocal, User, Task, UserChat
from dotenv import load_dotenv

# --- Setup ---
load_dotenv('.env')
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')


# --- Helpers ---
def get_user(update: Update):
    """Fetches the user from the database based on their Telegram ID."""
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=update.effective_user.id).first()
    db.close()
    return user


def format_time_ago(dt):
    """Format datetime to human readable time ago"""
    if not dt:
        return "Never"

    now = datetime.utcnow()
    diff = now - dt

    if diff.days > 0:
        return f"{diff.days}d ago"
    elif diff.seconds >= 3600:
        return f"{diff.seconds // 3600}h ago"
    elif diff.seconds >= 60:
        return f"{diff.seconds // 60}m ago"
    else:
        return "Just now"


def format_next_run(dt):
    """Format next run time"""
    if not dt:
        return "Not scheduled"

    now = datetime.utcnow()
    diff = dt - now

    if diff.days > 0:
        return f"in {diff.days}d"
    elif diff.seconds >= 3600:
        return f"in {diff.seconds // 3600}h"
    elif diff.seconds >= 60:
        return f"in {diff.seconds // 60}m"
    else:
        return "very soon"


async def is_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks if the user has authorized the bot by logging into the web app."""
    user = get_user(update)
    if user and user.is_bot_authorized:
        return True

    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "⚠️ *Not Authorized*\n\n"
            "To use this bot, you must first log in via the web interface. "
            "If you have recently logged out, please log back in to re-authorize the bot."
        ),
        parse_mode='Markdown'
    )
    return False


# --- Main Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greets the user and shows the main menu."""
    if not await is_authorized(update, context):
        return

    keyboard = [
        [InlineKeyboardButton("📋 My Tasks", callback_data="menu_tasks")],
        [InlineKeyboardButton("🗄️ Archived Tasks", callback_data="menu_archived")],
        [InlineKeyboardButton("📊 Statistics", callback_data="menu_stats")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")],
    ]
    await update.message.reply_text(
        f"👋 *Welcome, {update.effective_user.first_name}!*\n\n"
        "This bot helps you monitor your scheduled messages.\n\n"
        "Use the web application to create or manage your tasks.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provides help information about the bot's commands."""
    # --- FIX: Added authorization check ---
    if not await is_authorized(update, context):
        return
    # --- End of FIX ---
    help_text = """
🤖 *Bot Help & Commands*

This bot is for monitoring tasks created in the web app.

*Available Commands:*
/start - Shows the main menu.
/tasks - View your list of active and paused tasks.
/archived - View archived tasks.
/stats - See your overall task statistics.
/settings - Enable or disable task execution notifications.

*Please Note:*
Task creation and editing must be done through the web application.
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles callbacks from the main menu."""
    query = update.callback_query
    await query.answer()

    if not await is_authorized(update, context):
        return

    action = query.data.split('_')[1]

    if action == 'tasks':
        await view_tasks(update, context)
    elif action == 'archived':
        await view_archived_tasks(update, context)
    elif action == 'stats':
        await view_stats(update, context)
    elif action == 'settings':
        await settings_menu(update, context)
    elif action == 'main':
        await query.edit_message_text(
            f"👋 *Welcome, {update.effective_user.first_name}!*\n\n"
            "This bot helps you monitor your scheduled messages.\n\n"
            "Use the web application to create or manage your tasks.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 My Tasks", callback_data="menu_tasks")],
                [InlineKeyboardButton("🗄️ Archived Tasks", callback_data="menu_archived")],
                [InlineKeyboardButton("📊 Statistics", callback_data="menu_stats")],
                [InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")],
            ]),
            parse_mode='Markdown'
        )


# --- Bot Features ---
async def view_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays a list of the user's tasks."""
    # --- FIX: Added authorization check ---
    if not await is_authorized(update, context):
        return
    # --- End of FIX ---
    user = get_user(update)
    db = SessionLocal()
    tasks = db.query(Task).filter_by(user_id=user.id).filter(Task.status != 'archived').order_by(
        Task.created_at.desc()).all()
    db.close()

    message_sender = update.callback_query.edit_message_text if update.callback_query else update.message.reply_text

    if not tasks:
        await message_sender(
            text="🔭 *No Tasks Found*\n\nYou haven't created any active tasks yet. Please visit the web app to create your first task.",
            parse_mode='Markdown'
        )
        return

    text = f"📋 *Your Tasks* ({len(tasks)} total)\n\n"
    await message_sender(text=text, parse_mode='Markdown')

    chat_id = update.effective_chat.id

    for task in tasks[:10]:  # Show max 10 tasks
        status_emoji = {'active': '🟢', 'paused': '⏸️'}.get(task.status, '⚪')

        task_name_display = f"*{task.name}*\n" if task.name else ""
        schedule_info = f"Every {task.interval_value} {task.interval_unit}"
        files_info = f"\n📎 {len(task.file_paths)} files" if task.file_paths else ""

        last_run_info = f"Last: {format_time_ago(task.last_run)}" if task.last_run else "Not executed yet"
        next_run_info = f"Next: {format_next_run(task.next_run)}" if task.next_run else ""

        task_text = (
            f"{status_emoji} {task_name_display}"
            f"`{task.message[:50]}{'...' if len(task.message) > 50 else ''}`\n"
            f"⏱️ {schedule_info}\n"
            f"👥 {len(task.chat_ids)} chats{files_info}\n"
            f"🔄 Executed {task.execution_count} times\n"
            f"🕐 {last_run_info}"
        )

        if next_run_info and task.status == 'active':
            task_text += f" | {next_run_info}"

        await context.bot.send_message(
            chat_id=chat_id,
            text=task_text,
            parse_mode='Markdown'
        )


async def view_archived_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays a list of archived tasks."""
    # --- FIX: Added authorization check ---
    if not await is_authorized(update, context):
        return
    # --- End of FIX ---
    user = get_user(update)
    db = SessionLocal()
    tasks = db.query(Task).filter_by(user_id=user.id, status='archived').order_by(Task.updated_at.desc()).all()
    db.close()

    message_sender = update.callback_query.edit_message_text if update.callback_query else update.message.reply_text

    if not tasks:
        await message_sender(
            text="🗄️ *No Archived Tasks*\n\nYou don't have any archived tasks.",
            parse_mode='Markdown'
        )
        return

    text = f"🗄️ *Archived Tasks* ({len(tasks)} total)\n\n"
    await message_sender(text=text, parse_mode='Markdown')

    chat_id = update.effective_chat.id

    for task in tasks[:10]:  # Show max 10 tasks
        task_name_display = f"*{task.name}*\n" if task.name else ""
        schedule_info = f"Was: Every {task.interval_value} {task.interval_unit}"
        files_info = f"\n📎 {len(task.file_paths)} files" if task.file_paths else ""

        last_run_info = f"Last run: {format_time_ago(task.last_run)}" if task.last_run else "Never executed"

        task_text = (
            f"📦 {task_name_display}"
            f"`{task.message[:50]}{'...' if len(task.message) > 50 else ''}`\n"
            f"⏱️ {schedule_info}\n"
            f"👥 {len(task.chat_ids)} chats{files_info}\n"
            f"🔄 Executed {task.execution_count} times\n"
            f"🕐 {last_run_info}"
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=task_text,
            parse_mode='Markdown'
        )


async def view_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows user statistics."""
    # --- FIX: Added authorization check ---
    if not await is_authorized(update, context):
        return
    # --- End of FIX ---
    user = get_user(update)
    db = SessionLocal()
    tasks = db.query(Task).filter_by(user_id=user.id).all()
    db.close()

    total = len([t for t in tasks if t.status != 'archived'])
    active = sum(1 for t in tasks if t.status == 'active')
    paused = sum(1 for t in tasks if t.status == 'paused')
    archived = sum(1 for t in tasks if t.status == 'archived')
    executions = sum(t.execution_count for t in tasks)

    text = (
        "📊 *Your Statistics*\n\n"
        f"📋 Total Tasks: *{total}*\n"
        f"🟢 Active: *{active}*\n"
        f"⏸️ Paused: *{paused}*\n"
        f"🗄️ Archived: *{archived}*\n"
        f"🔄 Total Executions: *{executions}*"
    )

    message_sender = update.callback_query.edit_message_text if update.callback_query else update.message.reply_text
    await message_sender(text=text, parse_mode='Markdown')


async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the settings menu."""
    if not await is_authorized(update, context):
        return

    user = get_user(update)

    # Notification button
    notif_status = "🔔 Enabled" if user.notifications_enabled else "🔕 Disabled"
    notif_button_text = f"{'Disable' if user.notifications_enabled else 'Enable'} Notifications"

    # --- FIX: Add Simplified Login button ---
    login_status = "✅ Enabled" if user.simplified_login_enabled else "❌ Disabled"
    login_button_text = f"{'Disable' if user.simplified_login_enabled else 'Enable'} Simplified Login"

    keyboard = [
        [InlineKeyboardButton(f"Notifications: {notif_status}", callback_data="toggle_notif")],
        [InlineKeyboardButton(f"Simplified Login: {login_status}", callback_data="toggle_simplified_login")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_main")]
    ]

    text = "⚙️ *Settings*\n\nConfigure your bot preferences below."

    message_sender = update.callback_query.edit_message_text if update.callback_query else update.message.reply_text
    await message_sender(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def toggle_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggles the user's notification setting."""
    query = update.callback_query
    await query.answer()

    # --- FIX: Added authorization check ---
    if not await is_authorized(update, context):
        return
    # --- End of FIX ---

    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=update.effective_user.id).first()
    user.notifications_enabled = not user.notifications_enabled
    db.commit()
    db.close()

    # Refresh the settings menu to show the new state
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

    await settings_menu(update, context)  # Refresh the menu


def main():
    """Starts the bot."""
    app = Application.builder().token(BOT_TOKEN).build()

    # Command Handlers
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('tasks', view_tasks))
    app.add_handler(CommandHandler('archived', view_archived_tasks))
    app.add_handler(CommandHandler('stats', view_stats))
    app.add_handler(CommandHandler('settings', settings_menu))

    # Callback Query Handlers
    app.add_handler(CallbackQueryHandler(menu_handler, pattern='^menu_'))
    app.add_handler(CallbackQueryHandler(toggle_notifications, pattern='^toggle_notif$'))
    app.add_handler(CallbackQueryHandler(toggle_simplified_login, pattern='^toggle_simplified_login$'))

    print("🤖 Bot is running...")
    app.run_polling()


if __name__ == '__main__':
    main()
