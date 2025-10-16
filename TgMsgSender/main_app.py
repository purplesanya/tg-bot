from flask import Flask, render_template, request, jsonify, session, send_from_directory
from flask_session import Session
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, rpcerrorlist
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from database import init_db, User, Task, UserChat, SessionLocal, DATABASE_URL
from encryption import encrypt_data, decrypt_data
import os
import asyncio
from datetime import datetime, timedelta
import pytz
from functools import wraps
import secrets
from threading import Thread
from werkzeug.utils import secure_filename
import base64
import json
from dotenv import load_dotenv

try:
    from telegram import Bot
    from telegram.helpers import escape_markdown

    TELEGRAM_BOT_AVAILABLE = True
except ImportError:
    TELEGRAM_BOT_AVAILABLE = False

load_dotenv()

app = Flask(__name__,
            static_folder='static',
            static_url_path='/static')
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(32))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)

app.config.from_mapping(
    SESSION_TYPE='filesystem',
    SESSION_PERMANENT=True,
    SESSION_KEY_PREFIX='telegram_scheduler:',
    SESSION_FILE_DIR=os.path.join(os.path.dirname(__file__), 'flask_session'),
)

os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
Session(app)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
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


def is_auth_error(e):
    """Checks if a Telethon exception is due to an invalid session."""
    return isinstance(e, rpcerrorlist.AuthKeyUnregisteredError) or "key is not registered" in str(e)


def invalidate_user_session(user_id: int):
    """Performs a 'hard logout' by deleting session data and pausing tasks."""
    print(f"Auth key invalid. Forcing logout for user ID: {user_id}")
    db = SessionLocal()
    user = db.query(User).filter_by(id=user_id).first()
    if user and user.session_string_encrypted is not None:
        user.session_string_encrypted = None
        user.is_bot_authorized = False

        tasks = db.query(Task).filter_by(user_id=user.id, status='active').all()
        for task in tasks:
            try:
                scheduler.pause_job(task.id)
                task.status = 'paused'
                print(f"Paused task {task.id} for user {user_id} due to invalid session.")
            except Exception as e:
                print(f"Could not pause job {task.id}: {e}")

        db.commit()
    db.close()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Not authenticated'}), 401
        return f(*args, **kwargs)

    return decorated_function


def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, main_loop).result()


def calculate_next_run(interval_value, interval_unit):
    now = datetime.utcnow()
    if interval_unit == 'minutes':
        return now + timedelta(minutes=interval_value)
    elif interval_unit == 'hours':
        return now + timedelta(hours=interval_value)
    elif interval_unit == 'days':
        return now + timedelta(days=interval_value)
    return now


def escape_markdown_v2(text: str) -> str:
    """Escapes all reserved characters for Telegram's MarkdownV2 parser."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return "".join(f'\\{char}' if char in escape_chars else char for char in str(text))


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/api/auth/start', methods=['POST'])
def start_auth():
    data = request.json
    phone = data.get('phone')
    api_id = data.get('api_id')
    api_hash = data.get('api_hash')

    if not phone:
        return jsonify({'error': 'Phone number is required.'}), 400

    if not api_id or not api_hash:
        db = SessionLocal()
        user = db.query(User).filter_by(phone=phone).first()
        db.close()
        if user and user.simplified_login_enabled and user.api_id_encrypted:
            try:
                api_id = decrypt_data(user.api_id_encrypted)
                api_hash = decrypt_data(user.api_hash_encrypted)
            except Exception:
                return jsonify({'error': 'Could not use stored credentials. Please perform a full login.'}), 400
        else:
            return jsonify({'error': 'API details are required for the first login.'}), 400

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
        result, user_info = run_async(sign_in())
        if isinstance(result, dict) and result.get('needs_2fa'):
            return jsonify({'needs_2fa': True})
        session['user_id'] = user_info['id']
        session.permanent = True
        return jsonify({'success': True, 'user': user_info})
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
        result, user_info = run_async(sign_in_2fa())
        session['user_id'] = user_info['id']
        session.permanent = True
        return jsonify({'success': True, 'user': user_info})
    except Exception:
        return jsonify({'error': "Invalid password or session."}), 400


async def complete_login(client, auth_data, temp_id):
    me = await client.get_me()
    photo_base64 = None
    if me.photo:
        try:
            photo_bytes = await client.download_profile_photo(me, bytes)
            if photo_bytes: photo_base64 = base64.b64encode(photo_bytes).decode('utf-8')
        except Exception as e:
            print(f"Error downloading photo: {e}")

    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=me.id).first()
    creds = {
        'session_string_encrypted': encrypt_data(client.session.save()),
        'api_id_encrypted': encrypt_data(str(auth_data['api_id'])),
        'api_hash_encrypted': encrypt_data(auth_data['api_hash']),
        'last_login': datetime.utcnow(),
        'is_bot_authorized': True
    }
    if user:
        user.phone = auth_data['phone']
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
    user_db_id = user.id
    db.close()

    if user_db_id:
        asyncio.run_coroutine_threadsafe(monitor_user_chats(user_db_id), main_loop)
    if temp_id in pending_auth:
        del pending_auth[temp_id]
    await client.disconnect()

    user_info = {
        'id': me.id,
        'first_name': me.first_name,
        'username': me.username,
        'photo': photo_base64,
        'phone': auth_data['phone']
    }
    session['user_photo'] = photo_base64
    return me, user_info


@app.route('/api/auth/status')
@login_required
def auth_status():
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    if not user or not user.session_string_encrypted:
        db.close()
        # If there's no session in DB, they are effectively logged out
        session.clear()
        return jsonify({'error': 'Not authenticated'}), 401

    async def check_connection():
        api_id = int(decrypt_data(user.api_id_encrypted))
        api_hash = decrypt_data(user.api_hash_encrypted)
        session_string = decrypt_data(user.session_string_encrypted)
        client = TelegramClient(StringSession(session_string), api_id, api_hash, loop=main_loop)
        try:
            await client.connect()
            is_auth = await client.is_user_authorized()
            await client.disconnect()
            return is_auth
        except Exception as e:
            if is_auth_error(e):
                return False
            raise e

    try:
        is_authorized = run_async(check_connection())
        if not is_authorized:
            invalidate_user_session(user.id)
            session.clear()  # Clear Flask session as well
            return jsonify({'error': 'Telegram session is invalid.'}), 401

        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500
    finally:
        db.close()


@app.route('/api/chats', methods=['GET'])
@login_required
def get_chats():
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    if not user: return jsonify({'error': 'User not found'}), 404
    chats = db.query(UserChat).filter_by(user_id=user.id, is_active=True).all()
    db.close()
    return jsonify({'chats': [{'id': c.chat_id, 'name': c.chat_name, 'type': c.chat_type} for c in chats]})


async def refresh_chats_async(user_id: int):
    db = SessionLocal()
    user = db.query(User).filter_by(id=user_id).first()
    if not user or not user.session_string_encrypted:
        db.close()
        invalidate_user_session(user_id)
        raise rpcerrorlist.AuthKeyUnregisteredError

    api_id = int(decrypt_data(user.api_id_encrypted))
    api_hash = decrypt_data(user.api_hash_encrypted)
    session_string = decrypt_data(user.session_string_encrypted)
    client = TelegramClient(StringSession(session_string), api_id, api_hash, loop=main_loop)
    try:
        await client.connect()
        await update_user_chats(user.id, client, db)
        count = db.query(UserChat).filter_by(user_id=user.id, is_active=True).count()
        return count
    except Exception as e:
        if is_auth_error(e):
            invalidate_user_session(user.id)
        raise e
    finally:
        if client.is_connected(): await client.disconnect()
        db.close()


@app.route('/api/chats/refresh', methods=['POST'])
@login_required
def refresh_chats():
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=session['user_id']).first()
        if not user:
            db.close()
            return jsonify({'error': 'User not found'}), 404
        count = run_async(refresh_chats_async(user.id))
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        if is_auth_error(e):
            return jsonify({'error': 'Your Telegram session has expired. Please log out and log back in.'}), 401
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@app.route('/api/schedule', methods=['POST'])
@login_required
def schedule_message():
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=session['user_id']).first()
        if not user: return jsonify({'error': 'User not found'}), 404
        task = create_or_update_task_from_request(request, user.id, db)
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
        if not task: return jsonify({'error': 'Task not found'}), 404
        keep_existing_urls = json.loads(request.form.get('keep_existing', '[]'))
        if task.file_paths:
            for file_path in task.file_paths:
                if f'/uploads/{os.path.basename(file_path)}' not in keep_existing_urls and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        print(f"Error deleting old file: {e}")
        kept_file_paths = [fp for fp in (task.file_paths or []) if
                           f'/uploads/{os.path.basename(fp)}' in keep_existing_urls]
        create_or_update_task_from_request(request, user.id, db, task_id_to_update=task_id,
                                           existing_files=kept_file_paths)
        db.commit()
        return jsonify({'success': True, 'message': 'Task updated successfully'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 400
    finally:
        db.close()


def create_or_update_task_from_request(req, user_db_id, db, task_id_to_update=None, existing_files=None):
    if task_id_to_update:
        task = db.query(Task).filter_by(id=task_id_to_update, user_id=user_db_id).first()
        try:
            scheduler.remove_job(task.id)
        except Exception:
            pass
    else:
        task = Task(id=secrets.token_hex(16), user_id=user_db_id)
        existing_files = []

    task.chat_ids = [int(id.strip()) for id in req.form.get('chat_ids').split(',')]
    task.name = req.form.get('task_name', '').strip()
    task.message = req.form.get('message')
    existing_files_map = {f'/uploads/{os.path.basename(p)}': p for p in (existing_files or [])}
    uploaded_file_paths = {}
    if 'files' in req.files:
        for file in req.files.getlist('files')[:10]:
            if file.filename:
                safe_filename = secure_filename(file.filename)
                unique_name = f"{secrets.token_hex(8)}_{safe_filename}"
                filepath = os.path.join(UPLOAD_FOLDER, unique_name)
                file.save(filepath)
                if file.filename not in uploaded_file_paths: uploaded_file_paths[file.filename] = []
                uploaded_file_paths[file.filename].append(filepath)
    final_order = json.loads(req.form.get('final_order', '[]'))
    final_file_paths = []
    for identifier in final_order:
        if identifier.startswith('/uploads/'):
            if identifier in existing_files_map: final_file_paths.append(existing_files_map[identifier])
        else:
            if identifier in uploaded_file_paths and uploaded_file_paths[identifier]:
                final_file_paths.append(uploaded_file_paths[identifier].pop(0))
    task.file_paths = final_file_paths if final_file_paths else None
    task.schedule_type = 'repeat'
    task.interval_value = int(req.form.get('interval_value'))
    task.interval_unit = req.form.get('interval_unit')
    task.status = 'active'
    task.next_run = calculate_next_run(task.interval_value, task.interval_unit)
    scheduler.add_job(send_scheduled_message,
                      IntervalTrigger(**{task.interval_unit: task.interval_value}, timezone='UTC'),
                      args=[user_db_id, task.id], id=task.id, replace_existing=True, next_run_time=task.next_run)
    if not task_id_to_update: return task
    return None


def task_to_dict(t: Task, user_timezone_str: str):
    try:
        user_tz = pytz.timezone(user_timezone_str)
    except pytz.UnknownTimeZoneError:
        user_tz = pytz.utc

    def convert_time(dt):
        if dt: return dt.replace(tzinfo=pytz.utc).astimezone(user_tz).isoformat()
        return None

    file_urls = [f'/uploads/{os.path.basename(fp)}' for fp in t.file_paths] if t.file_paths else []
    return {'id': t.id, 'name': t.name or '', 'message': t.message, 'schedule_type': t.schedule_type,
            'interval_value': t.interval_value, 'interval_unit': t.interval_unit, 'status': t.status,
            'chat_ids': t.chat_ids, 'files': len(t.file_paths) if t.file_paths else 0, 'file_urls': file_urls,
            'execution_count': t.execution_count, 'last_run': convert_time(t.last_run),
            'next_run': convert_time(t.next_run)}


@app.route('/api/tasks', methods=['GET'])
@login_required
def get_tasks():
    user_timezone = request.args.get('timezone', 'UTC')
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    if not user: return jsonify({'error': 'User not found'}), 404
    tasks = db.query(Task).filter_by(user_id=user.id).filter(Task.status != 'archived').order_by(
        Task.created_at.desc()).all()
    db.close()
    return jsonify({'tasks': [task_to_dict(t, user_timezone) for t in tasks]})


@app.route('/api/tasks/archived', methods=['GET'])
@login_required
def get_archived_tasks():
    user_timezone = request.args.get('timezone', 'UTC')
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    if not user: return jsonify({'error': 'User not found'}), 404
    tasks = db.query(Task).filter_by(user_id=user.id, status='archived').order_by(Task.updated_at.desc()).all()
    db.close()
    return jsonify({'tasks': [task_to_dict(t, user_timezone) for t in tasks]})


@app.route('/api/tasks/<task_id>', methods=['GET'])
@login_required
def get_single_task(task_id):
    user_timezone = request.args.get('timezone', 'UTC')
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=session['user_id']).first()
        if not user: return jsonify({'error': 'User not found'}), 404
        task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
        if not task: return jsonify({'error': 'Task not found'}), 404
        return jsonify({'task': task_to_dict(task, user_timezone)})
    finally:
        db.close()


@app.route('/api/tasks/<task_id>', methods=['DELETE'])
@login_required
def delete_task(task_id):
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    task = db.query(Task).filter_by(id=task_id, user_id=user.id).first()
    if not task: return jsonify({'error': 'Task not found'}), 404
    if task.file_paths:
        for file_path in task.file_paths:
            if os.path.exists(file_path): os.remove(file_path)
    try:
        scheduler.remove_job(task.id)
    except Exception:
        pass
    db.delete(task);
    db.commit();
    db.close()
    return jsonify({'success': True})


@app.route('/api/tasks/<task_id>/pause', methods=['POST'])
@login_required
def pause_task(task_id):
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    task = db.query(Task).filter_by(id=task_id, user_id=user.id).first()
    if not task: return jsonify({'error': 'Task not found'}), 404
    scheduler.pause_job(task_id);
    task.status = 'paused'
    db.commit();
    db.close()
    return jsonify({'success': True})


@app.route('/api/tasks/<task_id>/resume', methods=['POST'])
@login_required
def resume_task(task_id):
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    task = db.query(Task).filter_by(id=task_id, user_id=user.id).first()
    if not task: return jsonify({'error': 'Task not found'}), 404
    task.next_run = datetime.utcnow();
    scheduler.resume_job(task_id);
    task.status = 'active'
    db.commit();
    db.close()
    return jsonify({'success': True})


@app.route('/api/tasks/<task_id>/archive', methods=['POST'])
@login_required
def archive_task(task_id):
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    task = db.query(Task).filter_by(id=task_id, user_id=user.id).first()
    if not task: return jsonify({'error': 'Task not found'}), 404
    try:
        scheduler.remove_job(task.id)
    except Exception:
        pass
    task.status = 'archived';
    db.commit();
    db.close()
    return jsonify({'success': True})


@app.route('/api/tasks/<task_id>/unarchive', methods=['POST'])
@login_required
def unarchive_task(task_id):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=session['user_id']).first()
        task = db.query(Task).filter_by(id=task_id, user_id=user.id).first()
        if not task: return jsonify({'error': 'Task not found'}), 404
        task.status = 'active';
        task.next_run = calculate_next_run(task.interval_value, task.interval_unit)
        scheduler.add_job(send_scheduled_message,
                          IntervalTrigger(**{task.interval_unit: task.interval_value}, timezone='UTC'),
                          args=[user.id, task.id], id=task.id, replace_existing=True, next_run_time=task.next_run)
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 400
    finally:
        db.close()


@app.route('/api/user/info', methods=['GET'])
def get_user_info():
    if 'user_id' not in session: return jsonify({'logged_in': False})
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    db.close()
    if not user: return jsonify({'logged_in': False})
    return jsonify({'logged_in': True,
                    'user': {'id': user.telegram_id, 'first_name': user.first_name, 'username': user.username,
                             'photo': session.get('user_photo'), 'phone': user.phone}})


@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    if user:
        invalidate_user_session(user.id)
    db.close()
    session.clear()
    return jsonify({'success': True})


@app.route('/api/settings/notifications', methods=['GET', 'POST'])
@login_required
def notification_settings():
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    if request.method == 'POST':
        user.notifications_enabled = request.json.get('enabled', False)
        db.commit()
        db.close()
        return jsonify({'success': True})
    enabled = user.notifications_enabled if user else True
    db.close()
    return jsonify({'enabled': enabled})


@app.route('/api/settings/simplified_login', methods=['GET', 'POST'])
@login_required
def simplified_login_settings():
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    if request.method == 'POST':
        user.simplified_login_enabled = request.json.get('enabled', False)
        db.commit()
        db.close()
        return jsonify({'success': True})
    enabled = user.simplified_login_enabled if user else False
    db.close()
    return jsonify({'enabled': enabled})


@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    db = SessionLocal()
    user = db.query(User).filter_by(telegram_id=session['user_id']).first()
    if not user: return jsonify({'error': 'User not found'}), 404
    tasks = db.query(Task).filter_by(user_id=user.id).all()
    db.close()
    return jsonify({'total_tasks': len([t for t in tasks if t.status != 'archived']),
                    'active_tasks': sum(1 for t in tasks if t.status == 'active'),
                    'archived_tasks': sum(1 for t in tasks if t.status == 'archived'),
                    'total_executions': sum(t.execution_count for t in tasks)})


def send_scheduled_message(user_db_id: int, task_id: str):
    db = SessionLocal()
    try:
        updated_rows = db.query(Task).filter_by(id=task_id, is_running=False, status='active').update(
            {"is_running": True})
        db.commit()
        if updated_rows == 0: return
        task = db.query(Task).filter_by(id=task_id).first()
        user = db.query(User).filter_by(id=user_db_id).first()
        if not user or not user.session_string_encrypted:
            print(f"User {user_db_id} has no session. Invalidating.")
            invalidate_user_session(user_db_id)
            return

        success, s_count, f_count = run_async(send_message_async(user, task))
        job = scheduler.get_job(task.id)
        next_run_time = job.next_run_time.replace(tzinfo=None) if job else None

        # Re-fetch task to avoid detached instance error after async call
        db.refresh(task)
        db.refresh(user)

        task.execution_count += 1
        task.last_run = datetime.utcnow()
        task.next_run = next_run_time
        task.is_running = False
        db.commit()

        if user.notifications_enabled:
            send_task_notification(user.telegram_id, task, success, s_count, f_count)

    except Exception as e:
        print(f"Error executing task {task_id}: {e}")
        db.rollback()
        db.query(Task).filter_by(id=task_id).update({"is_running": False});
        db.commit()
    finally:
        db.close()


async def send_message_async(user: User, task: Task):
    if not user.session_string_encrypted:
        invalidate_user_session(user.id)
        return False, 0, len(task.chat_ids)
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
                    await client.send_file(chat_id, task.file_paths, caption=task.message, parse_mode=None)
                else:
                    await client.send_message(chat_id, task.message, parse_mode=None)
                s_count += 1
            except Exception as e:
                print(f"Send Error (Task {task.id} to {chat_id}): {e}")
                f_count += 1
                if is_auth_error(e):
                    invalidate_user_session(user.id)
                    print(f"Stopping task {task.id} due to invalid session.")
                    break
            await asyncio.sleep(2)
    except Exception as e:
        if is_auth_error(e):
            invalidate_user_session(user.id)
        return False, s_count, len(task.chat_ids) - s_count
    finally:
        if client.is_connected(): await client.disconnect()
    return s_count > 0, s_count, f_count


def send_task_notification(telegram_id, task, success, s_count, f_count):
    if not BOT_TOKEN or not TELEGRAM_BOT_AVAILABLE: return
    emoji = '✅' if success else '❌'

    if task.name:
        task_identifier = f"'{escape_markdown_v2(task.name)}'"
    else:
        safe_message = escape_markdown_v2(task.message[:50])
        task_identifier = f"`{safe_message}\\.\\.\\.`" if len(task.message) > 50 else f"`{safe_message}`"

    text = (f"{emoji} *Task Executed \\(#{escape_markdown_v2(str(task.execution_count))}\\)*\n"
            f"{task_identifier}\n"
            f"Sent to: {s_count}/{len(task.chat_ids)} chats\\.")

    async def send_notif():
        try:
            await Bot(token=BOT_TOKEN).send_message(chat_id=telegram_id, text=text, parse_mode='MarkdownV2')
        except Exception as e:
            print(f"Failed to send bot notification: {e}")

    asyncio.run_coroutine_threadsafe(send_notif(), main_loop)


async def monitor_user_chats(user_db_id: int):
    db = SessionLocal()
    user = db.query(User).filter_by(id=user_db_id).first()
    db.close()
    if not user or not user.session_string_encrypted: return
    api_id = int(decrypt_data(user.api_id_encrypted))
    api_hash = decrypt_data(user.api_hash_encrypted)
    session_string = decrypt_data(user.session_string_encrypted)
    client = TelegramClient(StringSession(session_string), api_id, api_hash, loop=main_loop)
    while True:
        db = SessionLocal()
        try:
            user_check = db.query(User).filter_by(id=user_db_id).first()
            if not user_check or not user_check.session_string_encrypted: break
            if not client.is_connected(): await client.connect()
            await update_user_chats(user_db_id, client, db)
        except Exception as e:
            if is_auth_error(e):
                invalidate_user_session(user_db_id)
            print(f"Chat Monitor Error: {e}");
            break
        finally:
            db.close()
        await asyncio.sleep(300)


async def update_user_chats(user_db_id, client, db):
    dialogs = await client.get_dialogs()
    all_potential_groups = []
    for d in dialogs:
        if d.is_group:
            if hasattr(d.entity,
                       'banned_rights') and d.entity.banned_rights and d.entity.banned_rights.send_messages: continue
            chat_type = 'supergroup' if hasattr(d.entity, 'megagroup') and d.entity.megagroup else 'group'
            all_potential_groups.append({'original_id': d.id, 'abs_id': abs(d.id), 'name': d.name, 'type': chat_type})
    final_chats = {}
    for group in all_potential_groups:
        abs_id = group['abs_id']
        if abs_id not in final_chats:
            final_chats[abs_id] = group
        elif final_chats[abs_id]['type'] == 'group' and group['type'] == 'supergroup':
            final_chats[abs_id] = group
    db_chat_ids = {c.chat_id for c in db.query(UserChat).filter_by(user_id=user_db_id)}
    for chat_info in final_chats.values():
        if chat_info['original_id'] not in db_chat_ids:
            db.add(UserChat(user_id=user_db_id, chat_id=chat_info['original_id'], chat_name=chat_info['name'],
                            chat_type=chat_info['type']))
        else:
            db.query(UserChat).filter_by(user_id=user_db_id, chat_id=chat_info['original_id']).update(
                {'chat_name': chat_info['name'], 'chat_type': chat_info['type'], 'is_active': True})
    active_original_ids = [info['original_id'] for info in final_chats.values()]
    db.query(UserChat).filter(UserChat.user_id == user_db_id, UserChat.chat_id.notin_(active_original_ids)).update(
        {'is_active': False}, synchronize_session=False)
    db.commit()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
else:
    application = app
