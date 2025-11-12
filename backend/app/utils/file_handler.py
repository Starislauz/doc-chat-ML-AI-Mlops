"""File upload and validation utilities"""

import os
from typing import Tuple
from fastapi import UploadFile, HTTPException, status

from ..config.settings import settings
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


def validate_file_type(filename: str, allowed_extensions: list) -> None:
    """
    Validate file extension
    
    Args:
        filename: Name of the file
        allowed_extensions: List of allowed extensions
    
    Raises:
        HTTPException: If file type is not allowed
    """
    file_ext = os.path.splitext(filename)[1].lower()
    
    if file_ext not in allowed_extensions:
        logger.warning(f"Invalid file type: {file_ext}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {file_ext} not allowed. Allowed types: {', '.join(allowed_extensions)}"
        )


def validate_file_size(file_size: int, max_size: int, file_type: str = "file") -> None:
    """
    Validate file size
    
    Args:
        file_size: Size of the file in bytes
        max_size: Maximum allowed size in bytes
        file_type: Type of file for error message
    
    Raises:
        HTTPException: If file is too large
    """
    if file_size > max_size:
        max_mb = max_size / (1024 * 1024)
        logger.warning(f"File too large: {file_size} bytes")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{file_type.capitalize()} size exceeds maximum allowed size of {max_mb:.1f} MB"
        )


async def save_upload_file(upload_file: UploadFile, save_path: str) -> int:
    """
    Save uploaded file to disk
    
    Args:
        upload_file: FastAPI UploadFile object
        save_path: Path where file should be saved
    
    Returns:
        File size in bytes
    """
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    
    # Read and save file
    content = await upload_file.read()
    file_size = len(content)
    
    with open(save_path, "wb") as f:
        f.write(content)
    
    logger.info(f"Saved file to {save_path} ({file_size} bytes)")
    
    return file_size


async def validate_and_save_document(
    file: UploadFile,
    user_id: int
) -> Tuple[str, str, int]:
    """
    Validate and save a document file
    
    Args:
        file: Uploaded file
        user_id: ID of the user uploading the file
    
    Returns:
        Tuple of (file_path, file_type, file_size)
    
    Raises:
        HTTPException: If validation fails
    """
    # Validate file type
    validate_file_type(file.filename, settings.allowed_extensions)
    
    # Read file content to get size
    content = await file.read()
    file_size = len(content)
    
    # Validate file size
    validate_file_size(file_size, settings.max_file_size, "document")
    
    # Reset file pointer
    await file.seek(0)
    
    # Create upload directory
    upload_dir = os.path.join(settings.upload_dir, str(user_id))
    os.makedirs(upload_dir, exist_ok=True)
    
    # Generate unique filename
    import time as time_module
    file_ext = os.path.splitext(file.filename)[1]
    timestamp = int(time_module.time() * 1000)
    safe_filename = f"{timestamp}_{file.filename}"
    file_path = os.path.join(upload_dir, safe_filename)
    
    # Save file
    with open(file_path, "wb") as f:
        f.write(content)
    
    logger.info(f"Saved document for user {user_id}: {file_path}")
    
    return file_path, file_ext, file_size


async def validate_and_save_image(
    file: UploadFile,
    user_id: int,
    document_id: str
) -> Tuple[str, int]:
    """
    Validate and save an image file
    
    Args:
        file: Uploaded image file
        user_id: ID of the user
        document_id: Associated document ID
    
    Returns:
        Tuple of (file_path, file_size)
    
    Raises:
        HTTPException: If validation fails
    """
    # Validate image type
    validate_file_type(file.filename, settings.allowed_image_extensions)
    
    # Read file content
    content = await file.read()
    file_size = len(content)
    
    # Validate image size
    validate_file_size(file_size, settings.max_image_size, "image")
    
    # Create image directory
    image_dir = os.path.join(settings.image_dir, str(user_id), document_id)
    os.makedirs(image_dir, exist_ok=True)
    
    # Save image
    file_path = os.path.join(image_dir, file.filename)
    with open(file_path, "wb") as f:
        f.write(content)
    
    logger.info(f"Saved image for user {user_id}, document {document_id}: {file_path}")
    
    return file_path, file_size


def delete_file(file_path: str) -> None:
    """
    Delete a file from disk
    
    Args:
        file_path: Path to the file
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Deleted file: {file_path}")
    except Exception as e:
        logger.error(f"Error deleting file {file_path}: {str(e)}")


def delete_directory(dir_path: str) -> None:
    """
    Delete a directory and all its contents
    
    Args:
        dir_path: Path to the directory
    """
    try:
        if os.path.exists(dir_path):
            import shutil
            shutil.rmtree(dir_path)
            logger.info(f"Deleted directory: {dir_path}")
    except Exception as e:
        logger.error(f"Error deleting directory {dir_path}: {str(e)}")
