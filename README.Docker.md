# 🐳 Docker Deployment Guide

## Quick Start (2 Commands!)

### 1️⃣ First Time Setup
```bash
# Copy and configure environment file
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# Start the application
docker-compose up -d
```

### 2️⃣ Access Your Application
- **Frontend (UI)**: http://localhost
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

---

## 📋 Prerequisites

1. **Docker** (20.10+) - [Install Docker](https://docs.docker.com/get-docker/)
2. **Docker Compose** (2.0+) - [Install Docker Compose](https://docs.docker.com/compose/install/)
3. **Google Gemini API Key** - [Get API Key](https://makersuite.google.com/app/apikey)

---

## 🚀 Complete Setup Instructions

### Step 1: Clone & Configure

```bash
# Navigate to your project directory
cd Doc-chat

# Create environment file from example
cp .env.example .env

# Edit .env file and add your API key
# Windows: notepad .env
# Linux/Mac: nano .env or vim .env
```

**Required: Add your API key in `.env`:**
```env
GEMINI_API_KEY=your-actual-api-key-here
```

### Step 2: Build & Start

```bash
# Build and start all services
docker-compose up -d

# Or build from scratch (no cache)
docker-compose build --no-cache
docker-compose up -d
```

### Step 3: Verify Deployment

```bash
# Check container status
docker-compose ps

# View logs
docker-compose logs -f

# Check specific service logs
docker-compose logs -f backend
docker-compose logs -f frontend
```

---

## 🛠️ Common Commands

### Container Management
```bash
# Start services
docker-compose up -d

# Stop services (keeps data)
docker-compose stop

# Restart services
docker-compose restart

# Stop and remove containers (keeps data)
docker-compose down

# Stop and remove containers + volumes (DELETES ALL DATA!)
docker-compose down -v
```

### View Logs
```bash
# All services
docker-compose logs -f

# Backend only
docker-compose logs -f backend

# Last 100 lines
docker-compose logs --tail=100 backend

# Follow new logs
docker-compose logs -f --tail=0
```

### Health Checks
```bash
# Check service health
docker-compose ps

# Test backend health
curl http://localhost:8000/health

# Test frontend
curl http://localhost
```

### Rebuild Services
```bash
# Rebuild after code changes
docker-compose build

# Rebuild specific service
docker-compose build backend

# Rebuild without cache
docker-compose build --no-cache

# Rebuild and restart
docker-compose up -d --build
```

---

## 🔧 Development Mode

For development with hot-reload:

```bash
# Start in development mode
docker-compose -f docker-compose.dev.yml up -d

# Access at:
# - Frontend: http://localhost:8080
# - Backend: http://localhost:8000

# View development logs
docker-compose -f docker-compose.dev.yml logs -f
```

**Development Features:**
- ✅ Hot reload for code changes
- ✅ Debug mode enabled
- ✅ Detailed error messages
- ✅ Mounted volumes for live editing

---

## 📊 Data Persistence

Your data is automatically persisted in Docker volumes:

```bash
# List volumes
docker volume ls | grep doc-chat

# Backup volumes
docker run --rm -v doc-chat-uploads:/data -v $(pwd):/backup alpine tar czf /backup/uploads-backup.tar.gz -C /data .

# Restore volumes
docker run --rm -v doc-chat-uploads:/data -v $(pwd):/backup alpine tar xzf /backup/uploads-backup.tar.gz -C /data

# Remove all volumes (CAUTION: Deletes all data!)
docker-compose down -v
```

**Volumes Created:**
- `doc-chat-uploads` - User uploaded documents
- `doc-chat-images` - Extracted images
- `doc-chat-chroma` - Vector database
- `doc-chat-users` - User database

---

## 🐛 Troubleshooting

### Problem: Backend won't start

```bash
# Check logs
docker-compose logs backend

# Common issues:
# 1. Missing API key in .env
# 2. Port 8000 already in use

# Fix port conflict
docker-compose down
# Edit docker-compose.yml and change "8000:8000" to "8001:8000"
docker-compose up -d
```

### Problem: Frontend can't connect to backend

```bash
# Check if backend is healthy
docker-compose ps

# Check nginx configuration
docker-compose exec frontend cat /etc/nginx/conf.d/default.conf

# Restart services
docker-compose restart
```

### Problem: Permission errors

```bash
# On Linux/Mac, fix permissions
sudo chown -R $USER:$USER backend/

# Rebuild with no cache
docker-compose build --no-cache
docker-compose up -d
```

### Problem: Out of disk space

```bash
# Clean up unused Docker resources
docker system prune -a

# Remove unused volumes (CAUTION!)
docker volume prune

# Check disk usage
docker system df
```

---

## 🔒 Production Deployment

### Security Checklist

1. **Change Secret Key**
   ```bash
   # Generate new secret key
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   # Add to .env file
   ```

2. **Use Strong Passwords**
   - Don't use default passwords
   - Use password manager

3. **Enable HTTPS**
   - Use reverse proxy (Nginx, Caddy, Traefik)
   - Get SSL certificate (Let's Encrypt)

4. **Restrict CORS**
   ```env
   # In .env
   CORS_ORIGINS=https://yourdomain.com
   ```

5. **Secure API Keys**
   - Never commit .env file
   - Use environment-specific configs

### Production Deployment Options

#### Option 1: VPS/Cloud Server

```bash
# SSH to your server
ssh user@your-server-ip

# Clone repo
git clone <your-repo>
cd Doc-chat

# Configure
cp .env.example .env
nano .env  # Add API keys

# Deploy
docker-compose up -d

# Setup reverse proxy (Nginx example)
sudo apt install nginx certbot python3-certbot-nginx
sudo nano /etc/nginx/sites-available/doc-chat
# Configure proxy_pass to http://localhost:8000
sudo certbot --nginx -d yourdomain.com
```

#### Option 2: Docker Hub

```bash
# Build and tag images
docker build -f Dockerfile.backend -t yourusername/doc-chat-backend:latest .
docker build -f Dockerfile.frontend -t yourusername/doc-chat-frontend:latest .

# Push to Docker Hub
docker push yourusername/doc-chat-backend:latest
docker push yourusername/doc-chat-frontend:latest

# Deploy on any server
docker pull yourusername/doc-chat-backend:latest
docker-compose up -d
```

#### Option 3: Cloud Platforms

**AWS ECS, Google Cloud Run, Azure Container Instances:**
- Use provided `docker-compose.yml`
- Configure environment variables in cloud console
- Set up load balancer and SSL

---

## 📈 Monitoring & Maintenance

### View Resource Usage

```bash
# Container stats
docker stats

# Disk usage
docker system df

# Network info
docker network inspect doc-chat-network
```

### Update Application

```bash
# Pull latest changes
git pull

# Rebuild and restart
docker-compose build --no-cache
docker-compose up -d

# Or rolling update
docker-compose up -d --build --force-recreate
```

### Backup Strategy

```bash
# Create backup script
cat > backup.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p backups/$DATE
docker run --rm -v doc-chat-uploads:/data -v $(pwd)/backups/$DATE:/backup alpine tar czf /backup/uploads.tar.gz -C /data .
docker run --rm -v doc-chat-chroma:/data -v $(pwd)/backups/$DATE:/backup alpine tar czf /backup/chroma.tar.gz -C /data .
docker run --rm -v doc-chat-users:/data -v $(pwd)/backups/$DATE:/backup alpine tar czf /backup/users.tar.gz -C /data .
echo "Backup completed: backups/$DATE"
EOF

chmod +x backup.sh
./backup.sh
```

---

## 🎯 Architecture Overview

```
┌─────────────────────────────────────────┐
│         Docker Compose                   │
│                                          │
│  ┌──────────────┐    ┌──────────────┐  │
│  │   Frontend   │    │   Backend    │  │
│  │   (Nginx)    │───▶│  (FastAPI)   │  │
│  │   Port 80    │    │  Port 8000   │  │
│  └──────────────┘    └──────────────┘  │
│                           │              │
│                           ▼              │
│                    ┌──────────────┐     │
│                    │   Volumes    │     │
│                    │ (Persistence)│     │
│                    └──────────────┘     │
└─────────────────────────────────────────┘
```

**Components:**
- **Frontend Container**: Nginx serving static files
- **Backend Container**: FastAPI + AI/ML models
- **Network**: Bridge network for container communication
- **Volumes**: Persistent storage for user data

---

## 💡 Tips & Best Practices

1. **Always use `.env` file** - Never hardcode secrets
2. **Monitor logs regularly** - `docker-compose logs -f`
3. **Regular backups** - Automate volume backups
4. **Update dependencies** - Keep Docker images updated
5. **Use development mode** - For local testing
6. **Production checklist** - Security, HTTPS, monitoring
7. **Resource limits** - Set memory/CPU limits if needed

---

## 📞 Support & Troubleshooting

### Get Help

- **Health Check**: http://localhost:8000/health
- **API Docs**: http://localhost:8000/docs
- **Container Logs**: `docker-compose logs -f`

### Common Issues

| Issue | Solution |
|-------|----------|
| Port already in use | Change port in docker-compose.yml |
| API key error | Check .env file has correct key |
| Out of memory | Restart containers or increase Docker memory |
| Can't access frontend | Check if backend is healthy first |
| Data lost | Volumes might be removed, restore from backup |

---

## ✨ Created By

**Anthony Njoku**  
AI/ML Engineer & MLops Specialist

- 🔗 [LinkedIn](https://www.linkedin.com/in/anthony-emeka-6227782a1/)
- 🐙 [GitHub](https://github.com/starislauz)
- 🌐 [Portfolio](https://starislauz.github.io/myportfolio.com/)

---

**🎉 You're all set! Your RAG Document Chat is now containerized and ready to deploy anywhere!**
