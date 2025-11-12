# ==========================================
# RAG Document Chat - Makefile
# Simple commands for Docker management
# ==========================================

.PHONY: help build start stop restart logs clean dev prod backup

# Default target
help:
	@echo "🐳 RAG Document Chat - Docker Commands"
	@echo ""
	@echo "Setup Commands:"
	@echo "  make setup     - First time setup (copy .env and guide)"
	@echo "  make build     - Build Docker images"
	@echo "  make start     - Start all services"
	@echo ""
	@echo "Management Commands:"
	@echo "  make stop      - Stop all services"
	@echo "  make restart   - Restart all services"
	@echo "  make logs      - View all logs"
	@echo "  make status    - Check service status"
	@echo ""
	@echo "Development Commands:"
	@echo "  make dev       - Start in development mode"
	@echo "  make prod      - Start in production mode"
	@echo ""
	@echo "Maintenance Commands:"
	@echo "  make clean     - Remove containers (keep data)"
	@echo "  make clean-all - Remove everything (INCLUDING DATA!)"
	@echo "  make backup    - Backup all data volumes"
	@echo ""
	@echo "Specific Service Commands:"
	@echo "  make logs-backend  - View backend logs"
	@echo "  make logs-frontend - View frontend logs"
	@echo "  make shell-backend - Open backend shell"
	@echo ""

# First time setup
setup:
	@echo "🚀 First Time Setup"
	@echo ""
	@if [ ! -f .env ]; then \
		echo "Creating .env file..."; \
		cp .env.example .env; \
		echo "✅ .env file created"; \
		echo ""; \
		echo "⚠️  IMPORTANT: Edit .env file and add your GEMINI_API_KEY"; \
		echo "   Get API key from: https://makersuite.google.com/app/apikey"; \
		echo ""; \
		echo "After adding API key, run: make start"; \
	else \
		echo "✅ .env file already exists"; \
		echo ""; \
		echo "Next step: make start"; \
	fi

# Build images
build:
	@echo "🔨 Building Docker images..."
	docker-compose build

# Start services
start:
	@echo "🚀 Starting services..."
	docker-compose up -d
	@echo ""
	@echo "✅ Services started!"
	@echo ""
	@echo "Access your application:"
	@echo "  Frontend: http://localhost"
	@echo "  Backend:  http://localhost:8000"
	@echo "  API Docs: http://localhost:8000/docs"
	@echo ""
	@echo "View logs: make logs"

# Stop services
stop:
	@echo "🛑 Stopping services..."
	docker-compose stop
	@echo "✅ Services stopped"

# Restart services
restart:
	@echo "🔄 Restarting services..."
	docker-compose restart
	@echo "✅ Services restarted"

# View logs
logs:
	docker-compose logs -f

# View backend logs only
logs-backend:
	docker-compose logs -f backend

# View frontend logs only
logs-frontend:
	docker-compose logs -f frontend

# Check status
status:
	@echo "📊 Service Status:"
	@docker-compose ps
	@echo ""
	@echo "🔍 Health Check:"
	@curl -s http://localhost:8000/health | grep -o '"status":"[^"]*"' || echo "Backend not responding"

# Development mode
dev:
	@echo "🔧 Starting in development mode..."
	docker-compose -f docker-compose.dev.yml up -d
	@echo ""
	@echo "✅ Development mode started!"
	@echo ""
	@echo "Access your application:"
	@echo "  Frontend: http://localhost:8080"
	@echo "  Backend:  http://localhost:8000"
	@echo ""
	@echo "Code changes will auto-reload!"

# Production mode
prod:
	@echo "🚀 Starting in production mode..."
	docker-compose up -d
	@echo "✅ Production mode started!"

# Clean containers (keep data)
clean:
	@echo "🧹 Removing containers..."
	docker-compose down
	@echo "✅ Containers removed (data preserved)"

# Clean everything (including data)
clean-all:
	@echo "⚠️  WARNING: This will delete ALL data!"
	@echo "Press Ctrl+C to cancel, or wait 5 seconds..."
	@sleep 5
	docker-compose down -v
	@echo "✅ Everything removed"

# Backup data
backup:
	@echo "💾 Creating backup..."
	@mkdir -p backups/$$(date +%Y%m%d_%H%M%S)
	@docker run --rm -v doc-chat-uploads:/data -v $$(pwd)/backups/$$(date +%Y%m%d_%H%M%S):/backup alpine tar czf /backup/uploads.tar.gz -C /data .
	@docker run --rm -v doc-chat-chroma:/data -v $$(pwd)/backups/$$(date +%Y%m%d_%H%M%S):/backup alpine tar czf /backup/chroma.tar.gz -C /data .
	@docker run --rm -v doc-chat-users:/data -v $$(pwd)/backups/$$(date +%Y%m%d_%H%M%S):/backup alpine tar czf /backup/users.tar.gz -C /data .
	@echo "✅ Backup completed: backups/$$(date +%Y%m%d_%H%M%S)"

# Shell into backend container
shell-backend:
	docker-compose exec backend /bin/bash

# Shell into frontend container  
shell-frontend:
	docker-compose exec frontend /bin/sh

# Update and rebuild
update:
	@echo "🔄 Updating application..."
	git pull
	docker-compose build --no-cache
	docker-compose up -d
	@echo "✅ Update completed"

# Health check
health:
	@echo "🏥 Health Check:"
	@curl -s http://localhost:8000/health | python -m json.tool || echo "❌ Backend not responding"
