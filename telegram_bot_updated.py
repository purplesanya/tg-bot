"""
Telegram Control Bot - Full Featured Final Version with All Fixes
"""
import os
from datetime import datetime, timezone
import secrets
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)
from database import SessionLocal, User, Task, UserChat, DATABASE_URL
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

# --- Setup ---
load_dotenv('.env')
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

jobstores = {'default': SQLAlchemyJobStore(url=DATABASE_URL)}
scheduler = BackgroundScheduler(jobstores=jobstores, timezone="UTC")
if not scheduler.running:
    scheduler.start()

# --- Conversation States ---
(SELECT_TYPE, GET_MESSAGE, GET_MEDIA, GET_SCHEDULE, SELECT_CHATS,
 EDIT_TASK_MENU, GET_NEW_VALUE) = range(7)


# --- Helpers ---
def get_user(update: Update):
    db = SessionLocal();
    user = db.query(User).filter_by(telegram_id=update.effective_user.id).first();
    db.close()
    return user


async def is_authorized(update: Update):
    user = get_user(update)
    if user and user.is_bot_authorized: return True
    await update.message.reply_text("❌ Please log in via the web interface first.")
    return False


# --- Main Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_authorized(update):
        await update.message.reply_text(f"👋 Welcome {update.effective_user.first_name}!\nUse /newtask or /tasks.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Commands*\n/newtask - Create a message.\n/tasks - Manage tasks.\n/stats - View stats.\n/notifications - Toggle alerts.\n/cancel - Cancel operation.",
        parse_mode='Markdown')


# --- Task Viewing ---
async def view_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    user = get_user(update);
    db = SessionLocal();
    tasks = db.query(Task).filter_by(user_id=user.id).order_by(Task.created_at.desc()).all();
    db.close()
    if not tasks: await update.message.reply_text("📭 You have no tasks. Use /newtask."); return
    await update.message.reply_text("📋 *Your Tasks:*", parse_mode='Markdown')
    for task in tasks:
        emoji = {'scheduled': '⏰', 'active': '🔄', 'paused': '⏸️', 'sent': '✅', 'failed': '❌'}.get(task.status, '❓')
        schedule = f"Every {task.interval_value} {task.interval_unit}" if task.schedule_type == 'repeat' else f"At {task.schedule_time.strftime('%Y-%m-%d %H:%M')} UTC"
        files = f"\n📎 {len(task.file_paths)} file(s)" if task.file_paths else ""
        text = (f"{emoji} *{task.status.title()}*\n`{task.message[:40]}...`\n"
                f"🗓️ {schedule}\n👥 To {len(task.chat_ids)} chat(s){files}")
        buttons = []
        if task.status not in ['sent', 'failed']: buttons.append(
            InlineKeyboardButton("📝 Edit", callback_data=f"edit_{task.id}"))
        if task.status == 'active': buttons.append(InlineKeyboardButton("⏸️ Pause", callback_data=f"pause_{task.id}"))
        if task.status == 'paused': buttons.append(InlineKeyboardButton("▶️ Resume", callback_data=f"resume_{task.id}"))
        if task.status != 'sent': buttons.append(InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_{task.id}"))
        await update.message.reply_text(text, parse_mode='Markdown',
                                        reply_markup=InlineKeyboardMarkup([buttons]) if buttons else None)


async def handle_task_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query;
    await query.answer();
    action, task_id = query.data.split('_', 1)
    db = SessionLocal();
    task = db.query(Task).filter_by(id=task_id).first()
    if not task: await query.edit_message_text("❌ Task not found."); db.close(); return
    if action == 'pause':
        scheduler.pause_job(task_id); task.status = 'paused'; await query.edit_message_text("⏸️ Task paused.")
    elif action == 'resume':
        scheduler.resume_job(task_id); task.status = 'active'; await query.edit_message_text("▶️ Task resumed.")
    elif action == 'delete':
        if task.file_paths:
            for file_path in task.file_paths:
                try:
                    if os.path.exists(file_path): os.remove(file_path)
                except Exception as e:
                    print(f"Bot error deleting file {file_path}: {e}")
        try:
            scheduler.remove_job(task_id)
        except Exception:
            pass
        db.delete(task);
        await query.edit_message_text("🗑️ Task deleted.")
    db.commit();
    db.close()


# --- New Task/Edit Task Universal Functions ---
async def prompt_for_chats(update, context):
    user = get_user(update);
    db = SessionLocal();
    chats = db.query(UserChat).filter_by(user_id=user.id, is_active=True).all();
    db.close()
    if not chats: await update.effective_message.reply_text("❌ No chats found."); return ConversationHandler.END
    context.user_data['available_chats'] = {f"c_{c.chat_id}": {'id': c.chat_id, 'name': c.chat_name} for c in chats}
    context.user_data.setdefault('selected_chats', [])
    keyboard = []
    for key, info in context.user_data['available_chats'].items():
        keyboard.append([InlineKeyboardButton(
            f"{'☑️' if info['id'] in context.user_data['selected_chats'] else '◻️'} {info['name']}",
            callback_data=f"sel_{key}")])
    keyboard.append([InlineKeyboardButton("✅ Done", callback_data="chats_done"),
                     InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await update.effective_message.reply_text("👇 Select chats:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_CHATS


async def toggle_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query;
    await query.answer();
    key = query.data.split('_', 1)[1]
    chat_id = context.user_data['available_chats'][key]['id']
    selected = context.user_data['selected_chats']
    if chat_id in selected:
        selected.remove(chat_id)
    else:
        selected.append(chat_id)
    keyboard = []
    for k, info in context.user_data['available_chats'].items():
        keyboard.append([InlineKeyboardButton(f"{'☑️' if info['id'] in selected else '◻️'} {info['name']}",
                                              callback_data=f"sel_{k}")])
    keyboard.append([InlineKeyboardButton("✅ Done", callback_data="chats_done"),
                     InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_CHATS


# --- New Task Conversation ---
async def new_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return ConversationHandler.END
    context.user_data.clear()
    keyboard = [[InlineKeyboardButton("One-time", callback_data="type_once"),
                 InlineKeyboardButton("Repeating", callback_data="type_repeat")],
                [InlineKeyboardButton("Cancel", callback_data="cancel")]]
    await update.message.reply_text("📝 *New Task:* Select type", reply_markup=InlineKeyboardMarkup(keyboard),
                                    parse_mode='Markdown')
    return SELECT_TYPE


async def get_task_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query;
    await query.answer();
    context.user_data['task_type'] = query.data.split('_')[1]
    await query.edit_message_text("✍️ Send the message text:")
    return GET_MESSAGE


async def get_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['message'] = update.message.text;
    context.user_data['media'] = []
    keyboard = [[InlineKeyboardButton("📎 Add Media", callback_data="add_media"),
                 InlineKeyboardButton("✅ No Media", callback_data="skip_media")]]
    await update.message.reply_text("Attach media?", reply_markup=InlineKeyboardMarkup(keyboard))
    return GET_MEDIA


async def prompt_for_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query;
    await query.answer()
    await query.edit_message_text("Send a photo/video (up to 10). Send /done when finished.")
    return GET_MEDIA


async def get_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.user_data.get('media', [])) >= 10: await update.message.reply_text(
        "Max 10 files. /done to continue."); return GET_MEDIA
    try:
        file = await (update.message.photo[-1] if update.message.photo else update.message.video).get_file()
        file_path = os.path.join(UPLOAD_FOLDER, f"{secrets.token_hex(8)}_{os.path.basename(file.file_path)}")
        await file.download_to_drive(file_path);
        context.user_data['media'].append(file_path)
        await update.message.reply_text(f"✅ Media added ({len(context.user_data['media'])}/10). Send more or /done.")
    except Exception:
        await update.message.reply_text("Not a photo/video. Send media or /done.")
    return GET_MEDIA


async def done_adding_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = f"✅ {len(context.user_data.get('media', []))} file(s) attached." if context.user_data.get(
        'media') else "Okay, no media."
    if update.callback_query:
        await update.callback_query.answer(); await update.callback_query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

    if context.user_data.get('is_editing'):
        await save_edited_task(update, context)
        await update.effective_message.reply_text("✅ Media updated.")
        return await show_edit_menu(update, context)
    else:
        prompt = "⏰ Send schedule time in UTC (`YYYY-MM-DD HH:MM`)" if context.user_data[
                                                                           'task_type'] == 'once' else "🔁 Send repeat interval (e.g., `2 hours`)"
        await update.effective_message.reply_text(prompt, parse_mode='Markdown')
        return GET_SCHEDULE


async def get_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if context.user_data['task_type'] == 'once':
            naive_dt = datetime.strptime(update.message.text.strip(), '%Y-%m-%d %H:%M')
            context.user_data['schedule_time'] = naive_dt.replace(tzinfo=timezone.utc)
        else:
            val, unit = update.message.text.strip().split(); context.user_data.update(
                {'interval_value': int(val), 'interval_unit': unit.lower().rstrip('s') + 's'})
    except:
        await update.message.reply_text(
            "❌ Invalid format. Please enter as `YYYY-MM-DD HH:MM` in UTC."); return GET_SCHEDULE
    return await prompt_for_chats(update, context)


async def save_new_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query;
    await query.answer()
    if not context.user_data.get('selected_chats'): await query.answer("❌ Select at least one chat!",
                                                                       show_alert=True); return SELECT_CHATS
    user = get_user(update);
    task_id = secrets.token_hex(16)
    db = SessionLocal();
    task = Task(id=task_id, user_id=user.id, message=context.user_data['message'],
                schedule_type=context.user_data['task_type'], chat_ids=context.user_data['selected_chats'],
                file_paths=context.user_data.get('media'))
    if task.schedule_type == 'once':
        task.schedule_time = context.user_data['schedule_time']; task.status = 'scheduled'; scheduler.add_job(
            send_scheduled_message, DateTrigger(run_date=task.schedule_time, timezone='UTC'), args=[user.id, task.id],
            id=task.id)
    else:
        task.interval_value = context.user_data['interval_value']; task.interval_unit = context.user_data[
            'interval_unit']; task.status = 'active'; scheduler.add_job(send_scheduled_message, IntervalTrigger(
            **{task.interval_unit: task.interval_value}, timezone='UTC'), args=[user.id, task.id], id=task.id)
    db.add(task);
    db.commit();
    db.close()
    await query.edit_message_text("✅ Task saved successfully!");
    context.user_data.clear()
    return ConversationHandler.END


# --- Edit Task Conversation ---
async def edit_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query;
    await query.answer()
    context.user_data.clear();
    context.user_data['task_id'] = query.data.split('_')[1]
    return await show_edit_menu(update, context, is_first_time=True)


async def show_edit_menu(update, context, is_first_time=False):
    keyboard = [[InlineKeyboardButton("✍️ Message", callback_data="edit_field_message"),
                 InlineKeyboardButton("📎 Media", callback_data="edit_field_media")],
                [InlineKeyboardButton("⏰ Schedule", callback_data="edit_field_schedule"),
                 InlineKeyboardButton("👥 Chats", callback_data="edit_field_chats")],
                [InlineKeyboardButton("✅ Done Editing", callback_data="cancel")]]
    msg = "🔧 What would you like to edit?"
    if is_first_time:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.effective_message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_TASK_MENU


async def select_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query;
    await query.answer();
    field = query.data.split('_')[-1]
    context.user_data['edit_field'] = field;
    context.user_data['is_editing'] = True
    db = SessionLocal();
    task = db.query(Task).filter_by(id=context.user_data['task_id']).first();
    db.close()
    context.user_data.update({'message': task.message, 'task_type': task.schedule_type, 'selected_chats': task.chat_ids,
                              'media': task.file_paths or [], 'schedule_time': task.schedule_time,
                              'interval_value': task.interval_value, 'interval_unit': task.interval_unit})
    if field == 'message':
        await query.edit_message_text("Send the new message."); return GET_NEW_VALUE
    elif field == 'schedule':
        await query.edit_message_text(
            "Send new schedule in UTC (e.g., `2025-12-31 23:59` or `6 hours`)."); return GET_NEW_VALUE
    elif field == 'chats':
        await query.message.delete(); return await prompt_for_chats(query, context)
    elif field == 'media':
        context.user_data['media'] = []; await query.edit_message_text(
            "Current media cleared. Send a new photo/video, or /done to remove all media."); return GET_MEDIA


async def get_new_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data['edit_field']
    if field == 'message':
        context.user_data['message'] = update.message.text
    elif field == 'schedule':
        try:
            naive_dt = datetime.strptime(update.message.text.strip(), '%Y-%m-%d %H:%M')
            context.user_data['schedule_time'] = naive_dt.replace(tzinfo=timezone.utc)
            context.user_data['task_type'] = 'once'
        except:
            try:
                val, unit = update.message.text.strip().split(); context.user_data.update(
                    {'interval_value': int(val), 'interval_unit': unit.lower().rstrip('s') + 's',
                     'task_type': 'repeat'})
            except:
                await update.message.reply_text("❌ Invalid format."); return GET_NEW_VALUE
    await save_edited_task(update, context)
    await update.message.reply_text("✅ Field updated.")
    return await show_edit_menu(update, context)


async def save_edited_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update);
    task_id = context.user_data['task_id']
    db = SessionLocal();
    task = db.query(Task).filter_by(id=task_id).first()
    task.message = context.user_data['message'];
    task.schedule_type = context.user_data['task_type']
    task.chat_ids = context.user_data['selected_chats'];
    task.file_paths = context.user_data.get('media')
    if task.schedule_type == 'once':
        task.schedule_time = context.user_data['schedule_time'];
        task.status = 'scheduled';
        task.interval_value = None;
        task.interval_unit = None
        scheduler.add_job(send_scheduled_message, DateTrigger(run_date=task.schedule_time, timezone='UTC'),
                          args=[user.id, task.id], id=task.id, replace_existing=True)
    else:
        task.interval_value = context.user_data['interval_value'];
        task.interval_unit = context.user_data['interval_unit'];
        task.status = 'active';
        task.schedule_time = None
        scheduler.add_job(send_scheduled_message,
                          IntervalTrigger(**{task.interval_unit: task.interval_value}, timezone='UTC'),
                          args=[user.id, task.id], id=task.id, replace_existing=True)
    db.commit();
    db.close()


async def save_edited_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query;
    await query.answer()
    if not context.user_data.get('selected_chats'): await query.answer("❌ Select at least one chat!",
                                                                       show_alert=True); return SELECT_CHATS
    await save_edited_task(update, context)
    await query.edit_message_text("✅ Chats updated.")
    return await show_edit_menu(update, context)


# --- Fallback & Main ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "Operation finished."
    if update.callback_query:
        await update.callback_query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)
    context.user_data.clear();
    return ConversationHandler.END


# --- Stats & Settings ---
async def view_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    user = get_user(update);
    db = SessionLocal();
    tasks = db.query(Task).filter_by(user_id=user.id).all();
    db.close()
    await update.message.reply_text(
        f"📊 *Stats*\nTotal: {len(tasks)}\nActive: {sum(1 for t in tasks if t.status in ['active', 'scheduled'])}\nCompleted: {sum(1 for t in tasks if t.status == 'sent')}\nExecutions: {sum(t.execution_count for t in tasks)}",
        parse_mode='Markdown')


async def notifications_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    user = get_user(update)
    keyboard = [[InlineKeyboardButton("🔔 Enable", callback_data="notif_on"),
                 InlineKeyboardButton("🔕 Disable", callback_data="notif_off")]]
    await update.message.reply_text(f"Notifications are *{'enabled' if user.notifications_enabled else 'disabled'}*.",
                                    reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def toggle_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query;
    await query.answer();
    enabled = query.data == 'notif_on'
    db = SessionLocal();
    user = db.query(User).filter_by(telegram_id=update.effective_user.id).first()
    user.notifications_enabled = enabled;
    db.commit();
    db.close()
    await query.edit_message_text(f"✅ Notifications {'enabled' if enabled else 'disabled'}.")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    new_task_conv = ConversationHandler(
        entry_points=[CommandHandler('newtask', new_task_start)],
        states={
            SELECT_TYPE: [CallbackQueryHandler(get_task_type, pattern='^type_')],
            GET_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_message)],
            GET_MEDIA: [CallbackQueryHandler(prompt_for_media, pattern='^add_media$'),
                        CallbackQueryHandler(done_adding_media, pattern='^skip_media$'),
                        MessageHandler(filters.PHOTO | filters.VIDEO, get_media),
                        CommandHandler('done', done_adding_media)],
            GET_SCHEDULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_schedule)],
            SELECT_CHATS: [CallbackQueryHandler(toggle_chat, pattern='^sel_'),
                           CallbackQueryHandler(save_new_task, pattern='^chats_done$')],
        }, fallbacks=[CallbackQueryHandler(cancel, pattern='^cancel$'), CommandHandler('cancel', cancel)])
    edit_task_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_task_start, pattern='^edit_')],
        states={
            EDIT_TASK_MENU: [CallbackQueryHandler(select_edit_field, pattern='^edit_field_')],
            GET_NEW_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_value)],
            SELECT_CHATS: [CallbackQueryHandler(toggle_chat, pattern='^sel_'),
                           CallbackQueryHandler(save_edited_chats, pattern='^chats_done$')],
            GET_MEDIA: [MessageHandler(filters.PHOTO | filters.VIDEO, get_media),
                        CommandHandler('done', done_adding_media)],
        }, fallbacks=[CallbackQueryHandler(cancel, pattern='^cancel$'), CommandHandler('cancel', cancel)])
    app.add_handler(CommandHandler('start', start_command));
    app.add_handler(CommandHandler('help', help_command));
    app.add_handler(CommandHandler('tasks', view_tasks));
    app.add_handler(CommandHandler('stats', view_stats));
    app.add_handler(CommandHandler('notifications', notifications_command))
    app.add_handler(new_task_conv);
    app.add_handler(edit_task_conv)
    app.add_handler(CallbackQueryHandler(handle_task_action, pattern='^(pause|resume|delete)_'));
    app.add_handler(CallbackQueryHandler(toggle_notifications, pattern='^notif_'))
    print("🤖 Bot is running...");
    app.run_polling()


def send_scheduled_message(user_db_id, task_id): pass


if __name__ == '__main__': main()
