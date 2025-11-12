@echo off
REM ================================================
REM RAG Document Chat - Backup Data
REM ================================================

echo.
echo ================================================
echo  Backup Data Volumes
echo ================================================
echo.

REM Create backup directory with timestamp
set TIMESTAMP=%date:~-4%%date:~3,2%%date:~0,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set TIMESTAMP=%TIMESTAMP: =0%
set BACKUP_DIR=backups\%TIMESTAMP%

mkdir "%BACKUP_DIR%" 2>nul

echo [BACKUP] Creating backup in %BACKUP_DIR%...
echo.

REM Backup uploads
echo [1/4] Backing up uploads...
docker run --rm -v doc-chat-uploads:/data -v %cd%/%BACKUP_DIR%:/backup alpine tar czf /backup/uploads.tar.gz -C /data .

REM Backup images
echo [2/4] Backing up images...
docker run --rm -v doc-chat-images:/data -v %cd%/%BACKUP_DIR%:/backup alpine tar czf /backup/images.tar.gz -C /data .

REM Backup chroma
echo [3/4] Backing up vector database...
docker run --rm -v doc-chat-chroma:/data -v %cd%/%BACKUP_DIR%:/backup alpine tar czf /backup/chroma.tar.gz -C /data .

REM Backup users
echo [4/4] Backing up users database...
docker run --rm -v doc-chat-users:/data -v %cd%/%BACKUP_DIR%:/backup alpine tar czf /backup/users.tar.gz -C /data .

echo.
echo [OK] Backup completed successfully!
echo      Location: %BACKUP_DIR%
echo.
echo Files created:
dir /B "%BACKUP_DIR%"
echo.

pause
