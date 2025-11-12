# 🚀 Quick Start Guide - Docker Edition

## ⚡ Super Easy Setup (Windows)

### For Windows Users (2 Steps!)

1. **Setup Environment**
   ```cmd
   # Double-click this file or run in PowerShell:
   docker-start.bat
   ```
   - First time: It will create `.env` file
   - Add your `GEMINI_API_KEY` in `.env`
   - Run `docker-start.bat` again

2. **Access Your App**
   - Frontend: http://localhost
   - Backend API: http://localhost:8000/docs

### Simple Batch Commands

| Command | What it does |
|---------|-------------|
| `docker-start.bat` | Start everything |
| `docker-stop.bat` | Stop services |
| `docker-status.bat` | Check if running |
| `docker-logs.bat` | View logs |
| `docker-restart.bat` | Restart services |
| `docker-clean.bat` | Remove containers (keeps data) |
| `docker-backup.bat` | Backup your data |

---

## 🐧 For Linux/Mac Users

### Using Make Commands (Easy!)

```bash
# First time setup
make setup

# Edit .env and add your GEMINI_API_KEY
nano .env

# Start services
make start

# Other commands
make stop      # Stop services
make logs      # View logs
make status    # Check status
make restart   # Restart
make backup    # Backup data
make clean     # Remove containers (keep data)
```

### Or Use Docker Compose Directly

```bash
# Setup
cp .env.example .env
# Edit .env and add GEMINI_API_KEY

# Start
docker-compose up -d

# Stop
docker-compose stop

# Logs
docker-compose logs -f

# Status
docker-compose ps
```

---

## 📋 What You Need

1. **Docker Desktop** - [Download Here](https://www.docker.com/products/docker-desktop/)
2. **Gemini API Key** - [Get Free Key](https://makersuite.google.com/app/apikey)

---

## 🎯 Access Points

Once started, access these URLs:

- **Frontend (Main App)**: http://localhost
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

---

## 🔧 Troubleshooting

### Services won't start?

```bash
# Windows
docker-status.bat
docker-logs.bat

# Linux/Mac
make status
make logs
```

### Port already in use?

Edit `docker-compose.yml` and change:
```yaml
ports:
  - "8080:8000"  # Change 8000 to 8080 for backend
  - "8080:80"    # Change 80 to 8080 for frontend
```

### Backend API key error?

Check your `.env` file has:
```env
GEMINI_API_KEY=your-actual-key-here
```

### Need to reset everything?

```bash
# Windows
docker-clean.bat
docker-start.bat

# Linux/Mac
make clean
make start
```

---

## 💾 Your Data is Safe

Your data is stored in Docker volumes and persists even when you stop/restart containers:

- User uploads
- Vector database
- User accounts
- Chat history

To backup: `docker-backup.bat` (Windows) or `make backup` (Linux/Mac)

---

## 🌐 Deploy to Production

Full deployment guide available in `README.Docker.md`

Quick options:
- AWS ECS
- Google Cloud Run
- DigitalOcean
- Azure Container Instances
- Any VPS with Docker

---

## ✨ Features

✅ **Multi-format Support**: PDF, DOCX, TXT, Images  
✅ **AI-Powered**: Google Gemini for intelligent responses  
✅ **Vector Search**: ChromaDB for fast retrieval  
✅ **OCR Support**: Extract text from scanned documents  
✅ **Image Analysis**: Understand images and diagrams  
✅ **Persistent Storage**: Your data never gets lost  
✅ **Production Ready**: Health checks, logging, security  
✅ **Easy Deployment**: Works anywhere Docker runs  

---

## 📞 Need Help?

1. Check logs: `docker-logs.bat` or `make logs`
2. View status: `docker-status.bat` or `make status`
3. Read full guide: `README.Docker.md`
4. Check health: http://localhost:8000/health

---

## 👨‍💻 Created By

**Anthony Njoku**  
AI/ML Engineer & MLops Specialist

🔗 [LinkedIn](https://www.linkedin.com/in/anthony-emeka-6227782a1/)  
🐙 [GitHub](https://github.com/starislauz)  
🌐 [Portfolio](https://starislauz.github.io/myportfolio.com/)

---

**🎉 That's it! Your app is now containerized and super easy to deploy!**
