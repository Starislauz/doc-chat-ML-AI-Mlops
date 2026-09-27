"""Ingestion job tracking service using SQLite"""

import os
import sqlite3
import uuid
from contextlib import contextmanager
from typing import Dict, Optional

from ..config.settings import settings
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class IngestionService:
    """Service for tracking document ingestion jobs"""

    def __init__(self) -> None:
        self.db_path = settings.ingestion_db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._create_database()
        logger.info("IngestionService initialized")

    @contextmanager
    def get_db_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise exc
        finally:
            conn.close()

    def _create_database(self) -> None:
        """Create ingestion jobs table if it doesn't exist"""
        with self.get_db_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    job_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_user
                ON ingestion_jobs(user_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status
                ON ingestion_jobs(status)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_updated
                ON ingestion_jobs(updated_at)
                """
            )

    def create_job(self, user_id: int, filename: str) -> Dict:
        """Create a new ingestion job"""
        job_id = str(uuid.uuid4())

        with self.get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO ingestion_jobs (job_id, user_id, filename, status, progress, message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (job_id, user_id, filename, "queued", 0, "Queued")
            )

        logger.info(f"Created ingestion job {job_id} for user {user_id}")
        return self.get_job(job_id, user_id)

    def get_job(self, job_id: str, user_id: int) -> Optional[Dict]:
        """Get a job by ID for a user"""
        with self.get_db_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM ingestion_jobs
                WHERE job_id = ? AND user_id = ?
                """,
                (job_id, user_id)
            ).fetchone()

        return dict(row) if row else None

    def update_job(
        self,
        job_id: str,
        user_id: int,
        *,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
        completed_at: Optional[str] = None
    ) -> Optional[Dict]:
        """Update job status and metadata"""
        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)

        if progress is not None:
            progress = max(0, min(100, int(progress)))
            updates.append("progress = ?")
            params.append(progress)

        if message is not None:
            updates.append("message = ?")
            params.append(message)

        if error is not None:
            updates.append("error = ?")
            params.append(error)

        if completed_at is not None:
            updates.append("completed_at = ?")
            params.append(completed_at)
        elif status in {"completed", "failed"}:
            updates.append("completed_at = CURRENT_TIMESTAMP")

        updates.append("updated_at = CURRENT_TIMESTAMP")

        if not updates:
            return self.get_job(job_id, user_id)

        query = f"UPDATE ingestion_jobs SET {', '.join(updates)} WHERE job_id = ? AND user_id = ?"
        params.extend([job_id, user_id])

        with self.get_db_connection() as conn:
            conn.execute(query, params)

        return self.get_job(job_id, user_id)


# Global ingestion service instance
ingestion_service = IngestionService()
