"""Document cleanup service - Auto-delete documents on logout and enforce limits"""

import os
import shutil
from datetime import datetime, timedelta
from typing import List, Dict
from pathlib import Path

from ..config.settings import settings
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class CleanupService:
    """Service for cleaning up user documents and enforcing storage limits"""
    
    def __init__(self):
        """Initialize cleanup service"""
        self.max_documents_per_user = 3  # Maximum active documents per user
        logger.info("CleanupService initialized")
    
    def cleanup_user_documents(self, user_id: int, document_ids: List[str] = None) -> Dict:
        """
        Clean up all documents for a user (called on logout or page close)
        
        Args:
            user_id: User's ID
            document_ids: Optional list of specific document IDs to delete
                         If None, deletes ALL user documents
        
        Returns:
            Dictionary with cleanup results
        """
        logger.info(f"🧹 Starting cleanup for user {user_id}")
        
        try:
            # Import here to avoid circular imports
            from .vector_store import vector_store
            
            # Get all user documents if no specific IDs provided
            if document_ids is None:
                user_docs = vector_store.list_user_documents(user_id)
                document_ids = [doc['id'] for doc in user_docs]
            
            if not document_ids:
                logger.info(f"No documents to clean for user {user_id}")
                return {
                    "user_id": user_id,
                    "documents_deleted": 0,
                    "files_deleted": 0,
                    "space_freed_mb": 0
                }
            
            # Delete from vector store and file system
            total_chunks = 0
            files_deleted = 0
            space_freed = 0
            
            for doc_id in document_ids:
                # Delete from vector store
                deleted_chunks = vector_store.delete_document(doc_id, user_id)
                total_chunks += deleted_chunks
                
                # Calculate space freed
                doc_space = self._get_document_space(user_id, doc_id)
                space_freed += doc_space
                
                # Delete files
                files = self._delete_document_files(user_id, doc_id)
                files_deleted += files
            
            space_freed_mb = round(space_freed / (1024 * 1024), 2)
            
            logger.info(f"✅ Cleanup complete for user {user_id}: "
                       f"{len(document_ids)} docs, {total_chunks} chunks, "
                       f"{files_deleted} files, {space_freed_mb}MB freed")
            
            return {
                "user_id": user_id,
                "documents_deleted": len(document_ids),
                "chunks_deleted": total_chunks,
                "files_deleted": files_deleted,
                "space_freed_mb": space_freed_mb
            }
        
        except Exception as e:
            logger.error(f"Error during cleanup for user {user_id}: {str(e)}")
            return {
                "user_id": user_id,
                "error": str(e)
            }
    
    def _delete_document_files(self, user_id: int, document_id: str) -> int:
        """
        Delete all files associated with a document
        
        Args:
            user_id: User's ID
            document_id: Document's ID
        
        Returns:
            Number of files deleted
        """
        files_deleted = 0
        
        try:
            # Delete from uploads directory
            upload_dir = os.path.join(settings.upload_dir, str(user_id))
            if os.path.exists(upload_dir):
                for filename in os.listdir(upload_dir):
                    file_path = os.path.join(upload_dir, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                            files_deleted += 1
                            logger.debug(f"Deleted file: {file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to delete file {file_path}: {e}")
            
            # Delete from images directory
            image_dir = os.path.join(settings.image_dir, str(user_id), document_id)
            if os.path.exists(image_dir):
                shutil.rmtree(image_dir)
                logger.debug(f"Deleted image directory: {image_dir}")
                files_deleted += 1
        
        except Exception as e:
            logger.error(f"Error deleting files for document {document_id}: {e}")
        
        return files_deleted
    
    def _get_document_space(self, user_id: int, document_id: str) -> int:
        """
        Calculate space used by a document
        
        Args:
            user_id: User's ID
            document_id: Document's ID
        
        Returns:
            Space in bytes
        """
        total_size = 0
        
        try:
            # Check uploads directory
            upload_dir = os.path.join(settings.upload_dir, str(user_id))
            if os.path.exists(upload_dir):
                for filename in os.listdir(upload_dir):
                    file_path = os.path.join(upload_dir, filename)
                    if os.path.isfile(file_path):
                        total_size += os.path.getsize(file_path)
            
            # Check images directory
            image_dir = os.path.join(settings.image_dir, str(user_id), document_id)
            if os.path.exists(image_dir):
                for root, dirs, files in os.walk(image_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        total_size += os.path.getsize(file_path)
        
        except Exception as e:
            logger.warning(f"Error calculating document space: {e}")
        
        return total_size
    
    def check_user_document_limit(self, user_id: int) -> Dict:
        """
        Check if user has reached document limit
        
        Args:
            user_id: User's ID
        
        Returns:
            Dictionary with limit status
        """
        try:
            from .vector_store import vector_store
            
            user_docs = vector_store.list_user_documents(user_id)
            current_count = len(user_docs)
            
            return {
                "user_id": user_id,
                "current_documents": current_count,
                "max_documents": self.max_documents_per_user,
                "can_upload": current_count < self.max_documents_per_user,
                "must_delete": max(0, current_count - self.max_documents_per_user + 1)
            }
        
        except Exception as e:
            logger.error(f"Error checking document limit: {e}")
            return {
                "user_id": user_id,
                "error": str(e)
            }
    
    def enforce_document_limit(self, user_id: int) -> bool:
        """
        Enforce document limit before upload
        
        Args:
            user_id: User's ID
        
        Returns:
            True if user can upload, False if limit reached
        """
        limit_status = self.check_user_document_limit(user_id)
        return limit_status.get('can_upload', False)
    
    def cleanup_old_documents(self, days_old: int = 7) -> Dict:
        """
        Clean up documents older than specified days (admin function)
        
        Args:
            days_old: Delete documents older than this many days
        
        Returns:
            Dictionary with cleanup results
        """
        logger.info(f"🧹 Cleaning up documents older than {days_old} days")
        
        # This would require document timestamps in the database
        # For now, just log the intent
        logger.warning("Old document cleanup not yet implemented - requires timestamp tracking")
        
        return {
            "status": "not_implemented",
            "message": "Timestamp tracking needed for age-based cleanup"
        }
    
    def get_storage_stats(self, user_id: int = None) -> Dict:
        """
        Get storage statistics for a user or all users
        
        Args:
            user_id: Optional user ID, if None returns stats for all users
        
        Returns:
            Dictionary with storage statistics
        """
        try:
            stats = {
                "total_size_mb": 0,
                "total_files": 0,
                "users": {}
            }
            
            # Scan uploads directory
            if os.path.exists(settings.upload_dir):
                for user_dir in os.listdir(settings.upload_dir):
                    try:
                        uid = int(user_dir)
                        
                        # Skip if specific user requested and this isn't them
                        if user_id is not None and uid != user_id:
                            continue
                        
                        user_path = os.path.join(settings.upload_dir, user_dir)
                        if os.path.isdir(user_path):
                            user_size = 0
                            user_files = 0
                            
                            for root, dirs, files in os.walk(user_path):
                                for file in files:
                                    file_path = os.path.join(root, file)
                                    user_size += os.path.getsize(file_path)
                                    user_files += 1
                            
                            stats["users"][uid] = {
                                "size_mb": round(user_size / (1024 * 1024), 2),
                                "files": user_files
                            }
                            stats["total_size_mb"] += stats["users"][uid]["size_mb"]
                            stats["total_files"] += user_files
                    
                    except (ValueError, OSError):
                        continue
            
            stats["total_size_mb"] = round(stats["total_size_mb"], 2)
            
            return stats
        
        except Exception as e:
            logger.error(f"Error getting storage stats: {e}")
            return {"error": str(e)}


# Global cleanup service instance
cleanup_service = CleanupService()
