"""User management service with SQLite database"""

import sqlite3
import os
from typing import Optional, Dict
from datetime import datetime
from contextlib import contextmanager

from ..config.settings import settings
from ..utils.auth import hash_password, verify_password
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class UserService:
    """Service for user CRUD operations"""
    
    def __init__(self):
        """Initialize user service and create database"""
        self.db_path = settings.users_db_path
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._create_database()
        logger.info("UserService initialized")
    
    @contextmanager
    def get_db_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _create_database(self) -> None:
        """Create users table if it doesn't exist"""
        with self.get_db_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    hashed_password TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("Users database initialized")
    
    def create_user(self, username: str, email: str, password: str) -> Dict:
        """
        Create a new user
        
        Args:
            username: User's username
            email: User's email
            password: Plain text password
        
        Returns:
            User data dictionary
        
        Raises:
            ValueError: If user already exists
        """
        # Check if user exists
        if self.get_user_by_username(username):
            logger.warning(f"User registration failed: username '{username}' already exists")
            raise ValueError("Username already exists")
        
        if self.get_user_by_email(email):
            logger.warning(f"User registration failed: email '{email}' already exists")
            raise ValueError("Email already exists")
        
        # Hash password
        hashed_password = hash_password(password)
        
        # Insert user
        with self.get_db_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (username, email, hashed_password)
                VALUES (?, ?, ?)
                """,
                (username, email, hashed_password)
            )
            user_id = cursor.lastrowid
        
        logger.info(f"Created new user: {username} (ID: {user_id})")
        
        # Return user data
        return self.get_user_by_id(user_id)
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """
        Get user by ID
        
        Args:
            user_id: User's ID
        
        Returns:
            User data dictionary or None
        """
        with self.get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """
        Get user by username
        
        Args:
            username: User's username
        
        Returns:
            User data dictionary or None
        """
        with self.get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,)
            )
            row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """
        Get user by email
        
        Args:
            email: User's email
        
        Returns:
            User data dictionary or None
        """
        with self.get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM users WHERE email = ?",
                (email,)
            )
            row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """
        Authenticate user with username and password
        
        Args:
            username: User's username
            password: Plain text password
        
        Returns:
            User data dictionary if authentication successful, None otherwise
        """
        user = self.get_user_by_username(username)
        
        if not user:
            logger.warning(f"Authentication failed: user '{username}' not found")
            return None
        
        if not verify_password(password, user['hashed_password']):
            logger.warning(f"Authentication failed: invalid password for user '{username}'")
            return None
        
        if not user['is_active']:
            logger.warning(f"Authentication failed: user '{username}' is inactive")
            return None
        
        logger.info(f"User authenticated successfully: {username}")
        return user
    
    def update_user(self, user_id: int, **kwargs) -> Optional[Dict]:
        """
        Update user information
        
        Args:
            user_id: User's ID
            **kwargs: Fields to update
        
        Returns:
            Updated user data or None
        """
        allowed_fields = ['email', 'is_active']
        update_fields = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not update_fields:
            return self.get_user_by_id(user_id)
        
        set_clause = ", ".join([f"{field} = ?" for field in update_fields.keys()])
        values = list(update_fields.values()) + [user_id]
        
        with self.get_db_connection() as conn:
            conn.execute(
                f"UPDATE users SET {set_clause} WHERE id = ?",
                values
            )
        
        logger.info(f"Updated user {user_id}: {update_fields}")
        return self.get_user_by_id(user_id)
    
    def change_password(self, user_id: int, new_password: str) -> bool:
        """
        Change user password
        
        Args:
            user_id: User's ID
            new_password: New plain text password
        
        Returns:
            True if successful
        """
        hashed_password = hash_password(new_password)
        
        with self.get_db_connection() as conn:
            conn.execute(
                "UPDATE users SET hashed_password = ? WHERE id = ?",
                (hashed_password, user_id)
            )
        
        logger.info(f"Password changed for user {user_id}")
        return True


# Global user service instance
user_service = UserService()
