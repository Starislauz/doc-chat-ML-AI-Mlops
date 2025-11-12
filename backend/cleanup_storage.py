"""
🧹 Storage Cleanup Utility
Helps manage and clean up storage space in the Doc-Chat application
"""

import os
import sys
import shutil
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.config.settings import settings
from app.services.cleanup_service import cleanup_service
from app.services.vector_store import vector_store
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


def print_header(text):
    """Print formatted header"""
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80 + "\n")


def get_directory_size(path):
    """Calculate total size of a directory"""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file():
                total += entry.stat().st_size
            elif entry.is_dir():
                total += get_directory_size(entry.path)
    except Exception as e:
        logger.error(f"Error calculating size of {path}: {e}")
    return total


def format_size(bytes):
    """Format bytes to human-readable size"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes < 1024.0:
            return f"{bytes:.2f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.2f} TB"


def show_storage_stats():
    """Display storage statistics"""
    print_header("📊 STORAGE STATISTICS")
    
    # Check uploads directory
    uploads_dir = settings.upload_dir
    if os.path.exists(uploads_dir):
        uploads_size = get_directory_size(uploads_dir)
        print(f"📁 Uploads Directory: {format_size(uploads_size)}")
        print(f"   Location: {uploads_dir}")
        
        # Count files per user
        user_count = 0
        total_files = 0
        for user_dir in os.listdir(uploads_dir):
            user_path = os.path.join(uploads_dir, user_dir)
            if os.path.isdir(user_path):
                user_count += 1
                file_count = len([f for f in os.listdir(user_path) if os.path.isfile(os.path.join(user_path, f))])
                total_files += file_count
                user_size = get_directory_size(user_path)
                print(f"   User {user_dir}: {file_count} files, {format_size(user_size)}")
        
        print(f"\n   Total Users: {user_count}")
        print(f"   Total Files: {total_files}")
    else:
        print(f"📁 Uploads Directory: Not found")
    
    # Check images directory
    images_dir = settings.image_dir
    if os.path.exists(images_dir):
        images_size = get_directory_size(images_dir)
        print(f"\n🖼️  Images Directory: {format_size(images_size)}")
        print(f"   Location: {images_dir}")
    else:
        print(f"\n🖼️  Images Directory: Not found")
    
    # Check ChromaDB
    chroma_dir = os.path.join(backend_path, "backend", "chroma_db")
    if os.path.exists(chroma_dir):
        chroma_size = get_directory_size(chroma_dir)
        print(f"\n🗄️  Vector Database: {format_size(chroma_size)}")
        print(f"   Location: {chroma_dir}")
    else:
        print(f"\n🗄️  Vector Database: Not found")
    
    # Total
    total_size = 0
    if os.path.exists(uploads_dir):
        total_size += uploads_size
    if os.path.exists(images_dir):
        total_size += images_size
    if os.path.exists(chroma_dir):
        total_size += chroma_size
    
    print(f"\n💾 TOTAL STORAGE USED: {format_size(total_size)}")
    print()


def cleanup_all_users():
    """Clean up documents for all users"""
    print_header("🧹 CLEANUP ALL USERS")
    
    confirm = input("⚠️  This will DELETE ALL uploaded documents and data. Are you sure? (yes/no): ")
    if confirm.lower() != 'yes':
        print("❌ Cleanup cancelled")
        return
    
    # Get all user directories
    uploads_dir = settings.upload_dir
    if not os.path.exists(uploads_dir):
        print("✅ No uploads directory found - nothing to clean")
        return
    
    user_dirs = [d for d in os.listdir(uploads_dir) if os.path.isdir(os.path.join(uploads_dir, d))]
    
    if not user_dirs:
        print("✅ No user data found - nothing to clean")
        return
    
    print(f"\nFound {len(user_dirs)} users with data")
    
    total_deleted = 0
    for user_dir in user_dirs:
        try:
            user_id = int(user_dir)
            print(f"\n🧹 Cleaning user {user_id}...")
            
            result = cleanup_service.cleanup_user_documents(user_id)
            print(f"   ✅ Deleted {result.get('documents_deleted', 0)} documents, "
                  f"freed {result.get('space_freed_mb', 0)}MB")
            
            total_deleted += result.get('documents_deleted', 0)
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    print(f"\n✅ Cleanup complete! Deleted {total_deleted} documents total")


def cleanup_specific_user():
    """Clean up documents for a specific user"""
    print_header("🧹 CLEANUP SPECIFIC USER")
    
    try:
        user_id = int(input("Enter user ID to clean up: "))
    except ValueError:
        print("❌ Invalid user ID")
        return
    
    confirm = input(f"⚠️  This will DELETE all documents for user {user_id}. Are you sure? (yes/no): ")
    if confirm.lower() != 'yes':
        print("❌ Cleanup cancelled")
        return
    
    print(f"\n🧹 Cleaning user {user_id}...")
    
    try:
        result = cleanup_service.cleanup_user_documents(user_id)
        
        print(f"\n✅ Cleanup complete!")
        print(f"   Documents deleted: {result.get('documents_deleted', 0)}")
        print(f"   Chunks deleted: {result.get('chunks_deleted', 0)}")
        print(f"   Files deleted: {result.get('files_deleted', 0)}")
        print(f"   Space freed: {result.get('space_freed_mb', 0)}MB")
    
    except Exception as e:
        print(f"❌ Error during cleanup: {e}")


def show_venv_info():
    """Show information about the venv directory"""
    print_header("📦 VIRTUAL ENVIRONMENT INFO")
    
    venv_dir = Path(__file__).parent.parent.parent / "venv"
    
    if venv_dir.exists():
        venv_size = get_directory_size(str(venv_dir))
        print(f"📦 Virtual Environment Size: {format_size(venv_size)}")
        print(f"   Location: {venv_dir}")
        print(f"\n💡 This is NORMAL for AI/ML projects!")
        print(f"   The venv contains large libraries like:")
        print(f"   - PyTorch (~500 MB)")
        print(f"   - ChromaDB (~100 MB)")
        print(f"   - ONNX Runtime (~100 MB)")
        print(f"   - scipy/numpy (~200 MB)")
        print(f"   - And other AI dependencies")
        print(f"\n⚠️  DO NOT DELETE venv manually!")
        print(f"   Use: deactivate && rmdir /s venv (Windows)")
        print(f"   Then: python -m venv venv && pip install -r requirements.txt")
    else:
        print(f"📦 Virtual Environment: Not found at {venv_dir}")
    
    print()


def main():
    """Main menu"""
    while True:
        print_header("🧹 DOC-CHAT STORAGE CLEANUP UTILITY")
        
        print("1. 📊 Show Storage Statistics")
        print("2. 🧹 Cleanup All Users")
        print("3. 🧹 Cleanup Specific User")
        print("4. 📦 Show Virtual Environment Info")
        print("5. ❌ Exit")
        
        choice = input("\nSelect option (1-5): ").strip()
        
        if choice == '1':
            show_storage_stats()
            input("\nPress Enter to continue...")
        elif choice == '2':
            cleanup_all_users()
            input("\nPress Enter to continue...")
        elif choice == '3':
            cleanup_specific_user()
            input("\nPress Enter to continue...")
        elif choice == '4':
            show_venv_info()
            input("\nPress Enter to continue...")
        elif choice == '5':
            print("\n👋 Goodbye!")
            break
        else:
            print("\n❌ Invalid option. Please try again.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Cleanup cancelled by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
