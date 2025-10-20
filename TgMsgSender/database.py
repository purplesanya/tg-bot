import os
from datetime import datetime

from sqlalchemy import (create_engine, Column, Integer, String, Boolean,
                        DateTime, Text, ForeignKey, JSON)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# Use declarative_base for modern SQLAlchemy
Base = declarative_base()

# Database setup
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///telegram_scheduler.db')
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency for getting a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    phone = Column(String(50), unique=True, index=True)
    first_name = Column(String(255))
    username = Column(String(255), nullable=True)
    api_id_encrypted = Column(Text, nullable=False)
    api_hash_encrypted = Column(Text, nullable=False)
    session_string_encrypted = Column(Text, nullable=True)
    is_bot_authorized = Column(Boolean, default=False)
    notifications_enabled = Column(Boolean, default=True)
    simplified_login_enabled = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    language = Column(String(5), default='en', nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    tasks = relationship("Task", back_populates="user", cascade="all, delete-orphan")
    chats = relationship("UserChat", back_populates="user", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = 'tasks'

    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    name = Column(String(255), nullable=True)
    message = Column(Text, nullable=True)
    schedule_type = Column(String(20), default='repeat', nullable=False)

    schedule_time = Column(DateTime, nullable=True)
    interval_value = Column(Integer, nullable=True)
    interval_unit = Column(String(20), nullable=True)

    status = Column(String(20), default='scheduled', nullable=False, index=True)
    is_running = Column(Boolean, default=False, nullable=False)
    execution_count = Column(Integer, default=0)
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True, index=True)

    file_paths = Column(JSON, nullable=True)
    chat_ids = Column(JSON, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="tasks")


class UserChat(Base):
    __tablename__ = 'user_chats'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    chat_id = Column(Integer, nullable=False, index=True)
    chat_name = Column(String(255))
    chat_type = Column(String(50))
    is_active = Column(Boolean, default=True)
    last_checked = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="chats")


class TaskExecution(Base):
    __tablename__ = 'task_executions'

    id = Column(Integer, primary_key=True)
    task_id = Column(String(32), ForeignKey('tasks.id'), nullable=False, index=True)
    execution_time = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20))  # e.g., 'success', 'partial_failure', 'total_failure'
    total_chats = Column(Integer)
    successful_chats = Column(Integer)
    failed_chats = Column(Integer)
    error_message = Column(Text, nullable=True)


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)
    print("✅ Database initialized successfully")


if __name__ == "__main__":
    init_db()
