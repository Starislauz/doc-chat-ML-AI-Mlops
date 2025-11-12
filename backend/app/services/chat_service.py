"""Chat history management service"""

import sqlite3
import os
from typing import List, Dict, Optional
from datetime import datetime
from contextlib import contextmanager
import uuid

from ..config.settings import settings
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class ChatService:
    """Service for managing chat sessions and history"""
    
    def __init__(self):
        """Initialize chat service and create database"""
        self.db_path = settings.chat_db_path
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._create_database()
        logger.info("ChatService initialized")
    
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
        """Create chat tables if they don't exist"""
        with self.get_db_connection() as conn:
            # Sessions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Messages table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sources TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
                )
            """)
            
            # Create indexes
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_user 
                ON chat_sessions(user_id)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_session 
                ON chat_messages(session_id)
            """)
            
            logger.info("Chat database initialized")
    
    def create_session(self, user_id: int, title: str = "New Conversation") -> str:
        """
        Create a new chat session
        
        Args:
            user_id: User ID
            title: Session title
        
        Returns:
            Session ID
        """
        session_id = str(uuid.uuid4())
        
        with self.get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (session_id, user_id, title)
                VALUES (?, ?, ?)
                """,
                (session_id, user_id, title)
            )
        
        logger.info(f"Created chat session {session_id} for user {user_id}")
        return session_id
    
    def get_session(self, session_id: str, user_id: int) -> Optional[Dict]:
        """
        Get session information
        
        Args:
            session_id: Session ID
            user_id: User ID for validation
        
        Returns:
            Session data or None
        """
        with self.get_db_connection() as conn:
            cursor = conn.execute(
                """
                SELECT s.*, COUNT(m.message_id) as message_count
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON s.session_id = m.session_id
                WHERE s.session_id = ? AND s.user_id = ?
                GROUP BY s.session_id
                """,
                (session_id, user_id)
            )
            row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def list_user_sessions(self, user_id: int) -> List[Dict]:
        """
        List all sessions for a user
        
        Args:
            user_id: User ID
        
        Returns:
            List of session data
        """
        with self.get_db_connection() as conn:
            cursor = conn.execute(
                """
                SELECT s.*, COUNT(m.message_id) as message_count
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON s.session_id = m.session_id
                WHERE s.user_id = ?
                GROUP BY s.session_id
                ORDER BY s.updated_at DESC
                """,
                (user_id,)
            )
            rows = cursor.fetchall()
        
        return [dict(row) for row in rows]
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        sources: Optional[List[Dict]] = None
    ) -> int:
        """
        Add a message to a session
        
        Args:
            session_id: Session ID
            role: Message role ('user' or 'assistant')
            content: Message content
            sources: Optional source documents
        
        Returns:
            Message ID
        """
        import json
        
        sources_json = json.dumps(sources) if sources else None
        
        with self.get_db_connection() as conn:
            # Insert message
            cursor = conn.execute(
                """
                INSERT INTO chat_messages (session_id, role, content, sources)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, sources_json)
            )
            message_id = cursor.lastrowid
            
            # Update session timestamp
            conn.execute(
                """
                UPDATE chat_sessions 
                SET updated_at = CURRENT_TIMESTAMP 
                WHERE session_id = ?
                """,
                (session_id,)
            )
        
        logger.info(f"Added {role} message to session {session_id}")
        return message_id
    
    def get_session_history(
        self,
        session_id: str,
        user_id: int,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Get message history for a session
        
        Args:
            session_id: Session ID
            user_id: User ID for validation
            limit: Optional limit on number of messages
        
        Returns:
            List of messages
        """
        import json
        
        # Verify session belongs to user
        session = self.get_session(session_id, user_id)
        if not session:
            return []
        
        query = """
            SELECT * FROM chat_messages
            WHERE session_id = ?
            ORDER BY timestamp ASC
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        with self.get_db_connection() as conn:
            cursor = conn.execute(query, (session_id,))
            rows = cursor.fetchall()
        
        messages = []
        for row in rows:
            msg = dict(row)
            # Parse sources JSON
            if msg.get('sources'):
                try:
                    msg['sources'] = json.loads(msg['sources'])
                except:
                    msg['sources'] = None
            messages.append(msg)
        
        return messages
    
    def delete_session(self, session_id: str, user_id: int) -> bool:
        """
        Delete a chat session and all its messages
        
        Args:
            session_id: Session ID
            user_id: User ID for validation
        
        Returns:
            True if deleted, False if not found
        """
        # Verify ownership
        session = self.get_session(session_id, user_id)
        if not session:
            return False
        
        with self.get_db_connection() as conn:
            # Delete messages
            conn.execute(
                "DELETE FROM chat_messages WHERE session_id = ?",
                (session_id,)
            )
            
            # Delete session
            conn.execute(
                "DELETE FROM chat_sessions WHERE session_id = ?",
                (session_id,)
            )
        
        logger.info(f"Deleted chat session {session_id}")
        return True
    
    def update_session_title(self, session_id: str, user_id: int, title: str) -> bool:
        """
        Update session title
        
        Args:
            session_id: Session ID
            user_id: User ID for validation
            title: New title
        
        Returns:
            True if updated
        """
        # Verify ownership
        session = self.get_session(session_id, user_id)
        if not session:
            return False
        
        with self.get_db_connection() as conn:
            conn.execute(
                """
                UPDATE chat_sessions 
                SET title = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
                """,
                (title, session_id)
            )
        
        logger.info(f"Updated title for session {session_id}")
        return True


# Global chat service instance
chat_service = ChatService()
