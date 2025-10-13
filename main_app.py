"""
Flask Telegram Message Scheduler - Complete Fixed Version
"""

from flask import Flask, render_template, request, jsonify, session, send_from_directory
from flask_session import Session
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from database import init_db, User, Task, UserChat, SessionLocal, DATABASE_URL
from encryption import encrypt_data, decrypt_data
import os
import asyncio
from datetime import datetime
import pytz
from functools import wraps
import secrets
from threading import Thread
from telegram import Bot
from werkzeug.utils import secure_filename

# --- App Initialization ---
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

app.config.from_mapping(
    SESSION_TYPE='filesystem',
    SESSION_PERMANENT=True,
    SESSION_KEY_PREFIX='telegram_scheduler:',
)
Session(app)

# --- Configuration & Setup ---
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

init_db()

jobstores = {'default': SQLAlchemyJobStore(url=DATABASE_URL)}
scheduler = BackgroundScheduler(jobstores=jobstores, timezone="UTC")
if not scheduler.running:
    scheduler.start()

main_loop = asyncio.new_event_loop()


def run_loop_in_thread():
    asyncio.set_event_loop(main_loop)
    main_loop.run_forever()


loop_thread = Thread(target=run_loop_in_thread, daemon=True)
loop_thread.start()

pending_auth = {}
active_tasks = set()


# --- Helper Functions ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Not authenticated'}), 401
        return f(*args, **kwargs)

    return decorated_function


def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, main_loop).result()


# --- Main Route ---
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# --- Authentication API ---
@app.route('/api/auth/start', methods=['POST'])
def start_auth():
    data = request.json
    phone, api_id, api_hash = data.get('phone'), data.get('api_id'), data.get('api_hash')
    if not all([phone, api_id, api_hash]):
        return jsonify({'error': 'All fields are required'}), 400
    temp_id = secrets.token_hex(16)

    async def send_code():
        global pending_auth
        client = TelegramClient(StringSession(), int(api_id), api_hash, loop=main_loop)
        await client.connect()
        result = await client.send_code_request(phone)
        pending_auth[temp_id] = {
            'client': client,
            'phone': phone,
            'phone_code_hash': result.phone_code_hash,
            'api_id': api_id,
            'api_hash': api_hash
        }

    try:
        run_async(send_code())
        session['temp_auth_id'] = temp_id
        return jsonify({'success': True, 'message': 'Code sent'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/auth/verify_code', methods=['POST'])
def verify_code():
    temp_id = session.get('temp_auth_id')
    if not temp_id or temp_id not in pending_auth:
        return jsonify({'error': 'Invalid session'}), 400
    auth_data = pending_auth[temp_id]

    async def sign_in():
        try:
            await auth_data['client'].sign_in(
                auth_data['phone'],
                request.json.get('code'),
                phone_code_hash=auth_data['phone_code_hash']
            )
            return await complete_login(auth_data['client'], auth_data, temp_id)
        except SessionPasswordNeededError:
            return {'needs_2fa': True}, None

    try:
        result, _ = run_async(sign_in())
        if isinstance(result, dict) and result.get('needs_2fa'):
            return jsonify({'needs_2fa': True})
        session['user_id'] = result.id
        session.permanent = True
        return jsonify({
            'success': True,
            'user': {
                'id': result.id,
                'first_name': result.first_name,
                'username': result.username
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/auth/verify_2fa', methods=['POST'])
def verify_2fa():
    temp_id = session.get('temp_auth_id')
    if not temp_id or temp_id not in pending_auth:
        return jsonify({'error': 'Invalid session'}), 400
    auth_data = pending_auth[temp_id]

    async def sign_in_2fa():
        await auth_data['client'].sign_in(password=request.json.get('password'))
        return await complete_login(auth_data['client'], auth_data, temp_id)

    try:
        result, _ = run_async(sign_in_2fa())
        session['user_id'] = result.id
        session.permanent = True
        return jsonify({
            'success': True,
            'user': {
                'id': result.id,
                'first_name': result.first_name,
                'username': result.username
            }
        })
    except Exception:
        return jsonify({'error': "Invalid password or session."}), 400


async def complete_login(client: TelegramClient, auth_data: dict, temp_id: str):
    global pending_auth
    me = await client.get_me()
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=me.id).first()
        creds = {
            'session_string_encrypted': encrypt_data(client.session.save()),
            'api_id_encrypted': encrypt_data(str(auth_data['api_id'])),
            'api_hash_encrypted': encrypt_data(auth_data['api_hash']),
            'last_login': datetime.utcnow(),
            'is_bot_authorized': True
        }
        if user:
            for key, value in creds.items():
                setattr(user, key, value)
        else:
            user = User(
                telegram_id=me.id,
                phone=auth_data['phone'],
                first_name=me.first_name,
                username=me.username,
                **creds
            )
            db.add(user)
        db.commit()
        user_id = user.id
    finally:
        db.close()

    asyncio.run_coroutine_threadsafe(monitor_user_chats(user_id), main_loop)
    if temp_id in pending_auth:
        del pending_auth[temp_id]
    await client.disconnect()
    return me, user_id


# --- Task & Chat API ---
@app.route('/api/chats', methods=['GET'])
@login_required
def get_chats():
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    chats = db.query(UserChat).filter_by(user_id=user.id, is_active=True).all()
    db.close()
    return jsonify({'chats': [{'id': c.chat_id, 'name': c.chat_name, 'type': c.chat_type} for c in chats]})


async def refresh_chats_async(user_id: int):
    db = SessionLocal()
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        db.close()
        return 0
    api_id = int(decrypt_data(user.api_id_encrypted))
    api_hash = decrypt_data(user.api_hash_encrypted)
    session_string = decrypt_data(user.session_string_encrypted)
    client = TelegramClient(StringSession(session_string), api_id, api_hash, loop=main_loop)
    try:
        await client.connect()
        await update_user_chats(user.id, client, db)
        count = db.query(UserChat).filter_by(user_id=user.id, is_active=True).count()
        return count
    finally:
        if client.is_connected():
            await client.disconnect()
        db.close()


@app.route('/api/chats/refresh', methods=['POST'])
@login_required
def refresh_chats():
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=session['user_id']).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        count = run_async(refresh_chats_async(user.id))
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@app.route('/api/schedule', methods=['POST'])
@login_required
def schedule_message():
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=session['user_id']).first()
        user_timezone = request.form.get('timezone', 'UTC')
        auto_delete = request.form.get('auto_delete', 'false') == 'true'
        task = create_or_update_task_from_request(request, user.id, db, user_timezone, auto_delete=auto_delete)
        db.add(task)
        db.commit()
        return jsonify({'success': True, 'message': 'Task scheduled successfully', 'task_id': task.id})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 400
    finally:
        db.close()


@app.route('/api/tasks/<task_id>/update', methods=['POST'])
@login_required
def update_task_route(task_id):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=session['user_id']).first()
        task = db.query(Task).filter_by(id=task_id, user_id=user.id).first()
        if not task:
            return jsonify({'error': 'Task not found'}), 404
        user_timezone = request.form.get('timezone', 'UTC')
        auto_delete = request.form.get('auto_delete', 'false') == 'true'
        create_or_update_task_from_request(request, user.id, db, user_timezone, task_id_to_update=task_id,
                                           auto_delete=auto_delete)
        db.commit()
        return jsonify({'success': True, 'message': 'Task updated successfully'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 400
    finally:
        db.close()


def create_or_update_task_from_request(req, user_db_id, db, user_timezone, task_id_to_update=None, auto_delete=False):
    if task_id_to_update:
        task = db.query(Task).filter_by(id=task_id_to_update, user_id=user_db_id).first()
        try:
            scheduler.remove_job(task.id)
        except Exception:
            pass
    else:
        task = Task(id=secrets.token_hex(16), user_id=user_db_id)

    task.chat_ids = [int(id.strip()) for id in req.form.get('chat_ids').split(',')]
    task.message = req.form.get('message')
    task.schedule_type = req.form.get('schedule_type')

    # Handle file order from request
    file_order = req.form.get('file_order', '')
    ordered_files = []

    if 'files' in req.files:
        files = []
        # Delete old files if updating
        if task.file_paths:
            for fp in task.file_paths:
                if os.path.exists(fp):
                    os.remove(fp)

        # Save new files
        for file in req.files.getlist('files')[:10]:
            if file.filename:
                safe_filename = secure_filename(file.filename)
                filepath = os.path.join(UPLOAD_FOLDER, f"{secrets.token_hex(8)}_{safe_filename}")
                file.save(filepath)
                files.append(filepath)

        # Apply ordering if provided
        if file_order and files:
            order_indices = [int(i) for i in file_order.split(',') if i.strip().isdigit()]
            ordered_files = [files[i] for i in order_indices if i < len(files)]
        else:
            ordered_files = files

        task.file_paths = ordered_files

    # Parse timezone
    try:
        tz = pytz.timezone(user_timezone)
    except:
        tz = pytz.UTC

    if task.schedule_type == 'once':
        schedule_str = req.form.get('schedule_time')
        local_dt = datetime.strptime(schedule_str, '%Y-%m-%dT%H:%M')
        local_aware = tz.localize(local_dt)
        utc_dt = local_aware.astimezone(pytz.UTC).replace(tzinfo=None)

        task.schedule_time = utc_dt
        task.status = 'scheduled'
        task.interval_value, task.interval_unit = None, None

        # Store auto_delete preference in task (add this to database model if needed)
        # For now, we'll pass it as a job argument
        scheduler.add_job(
            send_scheduled_message,
            DateTrigger(run_date=utc_dt, timezone='UTC'),
            args=[user_db_id, task.id, auto_delete],
            id=task.id,
            replace_existing=True
        )
    else:
        task.interval_value = int(req.form.get('interval_value'))
        task.interval_unit = req.form.get('interval_unit')
        task.status = 'active'
        task.schedule_time = None

        scheduler.add_job(
            send_scheduled_message,
            IntervalTrigger(**{task.interval_unit: task.interval_value}, timezone='UTC'),
            args=[user_db_id, task.id, False],  # Never auto-delete repeating tasks
            id=task.id,
            replace_existing=True
        )

    if not task_id_to_update:
        return task
    return None


def task_to_dict(t: Task, user_timezone='UTC'):
    schedule_time_str = None
    if t.schedule_time:
        try:
            tz = pytz.timezone(user_timezone)
        except:
            tz = pytz.UTC
        utc_time = pytz.UTC.localize(t.schedule_time)
        local_time = utc_time.astimezone(tz)
        schedule_time_str = local_time.isoformat()

    # Generate file URLs for preview
    file_urls = []
    if t.file_paths:
        for fp in t.file_paths:
            filename = os.path.basename(fp)
            file_urls.append(f'/uploads/{filename}')

    return {
        'id': t.id,
        'message': t.message,
        'schedule_type': t.schedule_type,
        'schedule_time': schedule_time_str,
        'interval_value': t.interval_value,
        'interval_unit': t.interval_unit,
        'status': t.status,
        'chat_ids': t.chat_ids,
        'files': len(t.file_paths) if t.file_paths else 0,
        'file_urls': file_urls,
        'execution_count': t.execution_count
    }


@app.route('/api/tasks', methods=['GET'])
@login_required
def get_tasks():
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    tasks = db.query(Task).filter_by(user_id=user.id).order_by(Task.created_at.desc()).all()
    user_timezone = request.args.get('timezone', 'UTC')
    db.close()
    return jsonify({'tasks': [task_to_dict(t, user_timezone) for t in tasks]})


@app.route('/api/tasks/<task_id>', methods=['GET'])
@login_required
def get_single_task(task_id):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=session['user_id']).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
        if not task:
            return jsonify({'error': 'Task not found'}), 404

        user_timezone = request.args.get('timezone', 'UTC')
        return jsonify({'task': task_to_dict(task, user_timezone)})
    finally:
        db.close()


@app.route('/api/tasks/<task_id>', methods=['DELETE'])
@login_required
def delete_task(task_id):
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    task = db.query(Task).filter_by(id=task_id, user_id=user.id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    if task.file_paths:
        for file_path in task.file_paths:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"Error deleting file {file_path}: {e}")
    try:
        scheduler.remove_job(task.id)
    except Exception:
        pass
    db.delete(task)
    db.commit()
    db.close()
    return jsonify({'success': True})


@app.route('/api/tasks/<task_id>/pause', methods=['POST'])
@login_required
def pause_task(task_id):
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    task = db.query(Task).filter_by(id=task_id, user_id=user.id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    try:
        scheduler.pause_job(task_id)
    except Exception as e:
        print(f"Error pausing job: {e}")
    task.status = 'paused'
    db.commit()
    db.close()
    return jsonify({'success': True})


@app.route('/api/tasks/<task_id>/resume', methods=['POST'])
@login_required
def resume_task(task_id):
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    task = db.query(Task).filter_by(id=task_id, user_id=user.id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    try:
        scheduler.resume_job(task_id)
    except Exception as e:
        print(f"Error resuming job: {e}")
    task.status = 'active'
    db.commit()
    db.close()
    return jsonify({'success': True})


# --- User, Settings, Stats API ---
@app.route('/api/user/info', methods=['GET'])
def get_user_info():
    if 'user_id' not in session:
        return jsonify({'logged_in': False})
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    db.close()
    return jsonify({
        'logged_in': True,
        'user': {
            'id': user.telegram_id,
            'first_name': user.first_name,
            'username': user.username
        }
    }) if user else jsonify({'logged_in': False})


@app.route('/api/logout', methods=['POST'])
def logout():
    user_id = session.get('user_id')
    if user_id:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(telegram_id=user_id).first()
            if user:
                user.is_bot_authorized = False
                db.commit()
        except Exception as e:
            print(f"DB Error on logout: {e}")
            db.rollback()
        finally:
            db.close()
    session.clear()
    return jsonify({'success': True})


@app.route('/api/settings/notifications', methods=['GET'])
@login_required
def get_notification_settings():
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    db.close()
    return jsonify({'enabled': user.notifications_enabled if user else True})


@app.route('/api/settings/notifications', methods=['POST'])
@login_required
def toggle_notifications():
    enabled = request.json.get('enabled', False)
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    if user:
        user.notifications_enabled = enabled
        db.commit()
    db.close()
    return jsonify({'success': True})


@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    tasks = db.query(Task).filter_by(user_id=user.id).all()
    db.close()
    return jsonify({
        'total_tasks': len(tasks),
        'active_tasks': sum(1 for t in tasks if t.status in ['scheduled', 'active']),
        'completed_tasks': sum(1 for t in tasks if t.status == 'sent'),
        'total_executions': sum(t.execution_count for t in tasks)
    })


# --- Background Processes ---
def send_scheduled_message(user_db_id: int, task_id: str, auto_delete: bool = False):
    if task_id in active_tasks:
        print(f"Task {task_id} is already running, skipping...")
        return

    active_tasks.add(task_id)

    try:
        db = SessionLocal()
        task = db.query(Task).filter_by(id=task_id).first()
        user = db.query(User).filter_by(id=user_db_id).first()

        if not task or not user:
            db.close()
            return

        success, s_count, f_count = run_async(send_message_async(user, task))
        task.execution_count += 1
        task.last_run = datetime.utcnow()

        if task.schedule_type == 'once':
            task.status = 'sent' if success else 'failed'

            # Auto-delete if enabled
            if auto_delete and success:
                # Delete files
                if task.file_paths:
                    for file_path in task.file_paths:
                        try:
                            if os.path.exists(file_path):
                                os.remove(file_path)
                        except Exception as e:
                            print(f"Error deleting file {file_path}: {e}")

                # Delete task from database
                db.delete(task)
                db.commit()
                db.close()

                if user.notifications_enabled:
                    send_task_notification(user.telegram_id, task, success, s_count, f_count, auto_deleted=True)
                return

        db.commit()

        if user.notifications_enabled:
            send_task_notification(user.telegram_id, task, success, s_count, f_count)

        db.close()
    finally:
        active_tasks.discard(task_id)


async def send_message_async(user: User, task: Task):
    api_id = int(decrypt_data(user.api_id_encrypted))
    api_hash = decrypt_data(user.api_hash_encrypted)
    session_string = decrypt_data(user.session_string_encrypted)
    client = TelegramClient(StringSession(session_string), api_id, api_hash, loop=main_loop)
    s_count, f_count = 0, 0

    try:
        await client.connect()
        for chat_id in task.chat_ids:
            try:
                if task.file_paths:
                    await client.send_file(chat_id, task.file_paths, caption=task.message)
                else:
                    await client.send_message(chat_id, task.message)
                s_count += 1
            except Exception as e:
                print(f"Send Error (Task {task.id}): {e}")
                f_count += 1
            await asyncio.sleep(2)
    finally:
        if client.is_connected():
            await client.disconnect()

    return s_count > 0, s_count, f_count


def send_task_notification(telegram_id, task, success, s_count, f_count, auto_deleted=False):
    if not BOT_TOKEN:
        return
    emoji = '✅' if success else '❌'
    type_str = "Completed" if task.schedule_type == 'once' else f"Executed (#{task.execution_count})"
    msg = f"{emoji} *Task {type_str}*\n`{task.message[:50]}...`\nSent to: {s_count}/{len(task.chat_ids)} chats."

    if auto_deleted:
        msg += "\n🗑️ Task auto-deleted after execution"

    async def send_notif():
        await Bot(token=BOT_TOKEN).send_message(
            chat_id=telegram_id,
            text=msg,
            parse_mode='Markdown'
        )

    asyncio.run_coroutine_threadsafe(send_notif(), main_loop)


async def monitor_user_chats(user_db_id: int):
    db_outer = SessionLocal()
    user = db_outer.query(User).filter_by(id=user_db_id).first()
    db_outer.close()
    if not user:
        return
    api_id = int(decrypt_data(user.api_id_encrypted))
    api_hash = decrypt_data(user.api_hash_encrypted)
    session_string = decrypt_data(user.session_string_encrypted)
    client = TelegramClient(StringSession(session_string), api_id, api_hash, loop=main_loop)

    while True:
        db = SessionLocal()
        try:
            if not client.is_connected():
                await client.connect()
            await update_user_chats(user.id, client, db)
        except Exception as e:
            print(f"Chat Monitor Error: {e}")
        finally:
            db.close()
        await asyncio.sleep(300)


async def update_user_chats(user_db_id, client, db):
    dialogs = await client.get_dialogs()
    current_chats = {}  # Use dict to track unique chats by ID

    for d in dialogs:
        if d.is_group:
            # Skip if user can't send messages
            if hasattr(d.entity, 'banned_rights') and d.entity.banned_rights and d.entity.banned_rights.send_messages:
                continue

            # Determine chat type
            chat_type = 'supergroup' if hasattr(d.entity, 'megagroup') and d.entity.megagroup else 'group'

            # Use chat ID as unique identifier - this prevents duplicates
            chat_id = d.id

            # Only add if not already tracked (prevents group/supergroup duplicates)
            if chat_id not in current_chats:
                current_chats[chat_id] = {
                    'name': d.name,
                    'type': chat_type
                }

    # Update database
    for chat_id, chat_info in current_chats.items():
        chat = db.query(UserChat).filter_by(user_id=user_db_id, chat_id=chat_id).first()
        if chat:
            chat.chat_name = chat_info['name']
            chat.chat_type = chat_info['type']
            chat.is_active = True
        else:
            db.add(UserChat(
                user_id=user_db_id,
                chat_id=chat_id,
                chat_name=chat_info['name'],
                chat_type=chat_info['type']
            ))

    # Mark chats not in current list as inactive
    db.query(UserChat).filter(
        UserChat.user_id == user_db_id,
        UserChat.chat_id.notin_(list(current_chats.keys()))
    ).update({'is_active': False}, synchronize_session=False)

    db.commit()


if __name__ == '__main__':
    app.run(host= '0.0.0.0', debug=True, port=5000)
