"""
Database Models using SQLAlchemy
"""

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import os

# Updated way to declare the base for modern SQLAlchemy
Base = declarative_base()

# Database setup
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///telegram_scheduler.db')
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    phone = Column(String(50), unique=True, index=True)  # Phone should be unique for simplified login
    first_name = Column(String(255))
    username = Column(String(255))
    api_id_encrypted = Column(Text, nullable=False)
    api_hash_encrypted = Column(Text, nullable=False)
    session_string_encrypted = Column(Text)
    is_bot_authorized = Column(Boolean, default=False)
    notifications_enabled = Column(Boolean, default=True)
    # --- FIX: Added setting for Simplified Login ---
    simplified_login_enabled = Column(Boolean, default=False)
    # --- End of FIX ---
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime)

    tasks = relationship("Task", back_populates="user", cascade="all, delete-orphan")
    chats = relationship("UserChat", back_populates="user", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = 'tasks'

    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    name = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    schedule_type = Column(String(20), default='repeat')

    schedule_time = Column(DateTime)
    interval_value = Column(Integer)
    interval_unit = Column(String(20))

    status = Column(String(20), default='scheduled')
    is_running = Column(Boolean, default=False, nullable=False)
    execution_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    last_run = Column(DateTime)
    last_status = Column(String(20))
    next_run = Column(DateTime)
    sent_at = Column(DateTime)

    file_paths = Column(JSON)
    chat_ids = Column(JSON, nullable=False)
    failed_chat_ids = Column(JSON)

    send_delay_seconds = Column(Integer, default=2)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="tasks")


class UserChat(Base):
    __tablename__ = 'user_chats'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    chat_id = Column(Integer, nullable=False)
    chat_name = Column(String(255))
    chat_type = Column(String(50))
    can_send = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    last_checked = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="chats")


class TaskExecution(Base):
    __tablename__ = 'task_executions'

    id = Column(Integer, primary_key=True)
    task_id = Column(String(32), ForeignKey('tasks.id'), nullable=False)
    execution_time = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20))
    total_chats = Column(Integer)
    successful_chats = Column(Integer)
    failed_chats = Column(Integer)
    error_message = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)
    print("✅ Database initialized successfully")


if __name__ == "__main__":
    init_db()
