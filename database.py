"""
Database Models using SQLAlchemy
"""

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

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
    phone = Column(String(50))
    first_name = Column(String(255))
    username = Column(String(255))
    api_id_encrypted = Column(Text, nullable=False)  # RSA encrypted
    api_hash_encrypted = Column(Text, nullable=False)  # RSA encrypted
    session_string_encrypted = Column(Text)  # RSA encrypted
    is_bot_authorized = Column(Boolean, default=False)
    notifications_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime)

    # Relationships
    tasks = relationship("Task", back_populates="user", cascade="all, delete-orphan")
    chats = relationship("UserChat", back_populates="user", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = 'tasks'

    id = Column(String(32), primary_key=True)  # UUID hex
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    message = Column(Text, nullable=False)
    schedule_type = Column(String(20), default='once')  # 'once' or 'repeat'

    # For one-time tasks
    schedule_time = Column(DateTime)

    # For repeating tasks
    interval_value = Column(Integer)
    interval_unit = Column(String(20))  # 'minutes', 'hours', 'days'

    # Status and tracking
    status = Column(String(20), default='scheduled')  # scheduled, paused, sent, failed, active
    execution_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    last_run = Column(DateTime)
    last_status = Column(String(20))
    next_run = Column(DateTime)
    sent_at = Column(DateTime)

    # Files and chats
    file_paths = Column(JSON)  # List of file paths
    chat_ids = Column(JSON, nullable=False)  # List of chat IDs
    failed_chat_ids = Column(JSON)  # List of failed chat IDs

    # Delay settings
    send_delay_seconds = Column(Integer, default=2)  # Delay between groups

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="tasks")


class UserChat(Base):
    __tablename__ = 'user_chats'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    chat_id = Column(Integer, nullable=False)
    chat_name = Column(String(255))
    chat_type = Column(String(50))  # 'group', 'supergroup'
    can_send = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    last_checked = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="chats")


class TaskExecution(Base):
    __tablename__ = 'task_executions'

    id = Column(Integer, primary_key=True)
    task_id = Column(String(32), ForeignKey('tasks.id'), nullable=False)
    execution_time = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20))  # 'success', 'partial', 'failed'
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