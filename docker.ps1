# ================================================
# RAG Document Chat - PowerShell Setup Script
# Modern alternative to batch files
# ================================================

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet('start', 'stop', 'restart', 'status', 'logs', 'clean', 'backup', 'dev', 'help')]
    [string]$Command = 'help'
)

# Colors
$GREEN = 'Green'
$YELLOW = 'Yellow'
$RED = 'Red'
$CYAN = 'Cyan'

function Write-Header {
    param([string]$Text)
    Write-Host "`n================================================" -ForegroundColor $CYAN
    Write-Host " $Text" -ForegroundColor $CYAN
    Write-Host "================================================`n" -ForegroundColor $CYAN
}

function Write-Success {
    param([string]$Text)
    Write-Host "[OK] $Text" -ForegroundColor $GREEN
}

function Write-Warning {
    param([string]$Text)
    Write-Host "[WARNING] $Text" -ForegroundColor $YELLOW
}

function Write-Error-Custom {
    param([string]$Text)
    Write-Host "[ERROR] $Text" -ForegroundColor $RED
}

function Test-DockerRunning {
    try {
        docker version | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Start-Services {
    Write-Header "Starting RAG Document Chat"
    
    # Check .env file
    if (-not (Test-Path ".env")) {
        Write-Warning ".env file not found. Creating from template..."
        Copy-Item ".env.example" ".env"
        Write-Success ".env file created"
        Write-Host "`n[IMPORTANT] Please edit .env file and add your GEMINI_API_KEY" -ForegroundColor $YELLOW
        Write-Host "            Get API key from: https://makersuite.google.com/app/apikey`n" -ForegroundColor $YELLOW
        Write-Host "After adding API key, run this script again.`n"
        Read-Host "Press Enter to open .env file"
        notepad .env
        return
    }
    
    # Check Docker
    if (-not (Test-DockerRunning)) {
        Write-Error-Custom "Docker is not running!"
        Write-Host "Please start Docker Desktop and try again.`n"
        return
    }
    
    Write-Success "Docker is running"
    
    # Build and start
    Write-Host "`nBuilding Docker images...`n"
    docker-compose build
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error-Custom "Failed to build Docker images"
        return
    }
    
    Write-Host "`nStarting services...`n"
    docker-compose up -d
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error-Custom "Failed to start services"
        return
    }
    
    Write-Header "SUCCESS! Services Started"
    Write-Host "  Frontend:  http://localhost" -ForegroundColor $GREEN
    Write-Host "  Backend:   http://localhost:8000" -ForegroundColor $GREEN
    Write-Host "  API Docs:  http://localhost:8000/docs" -ForegroundColor $GREEN
    Write-Host "  Health:    http://localhost:8000/health`n" -ForegroundColor $GREEN
}

function Stop-Services {
    Write-Header "Stopping Services"
    docker-compose stop
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Services stopped successfully"
    }
}

function Restart-Services {
    Write-Header "Restarting Services"
    docker-compose restart
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Services restarted successfully"
    }
}

function Show-Status {
    Write-Header "Service Status"
    docker-compose ps
    
    Write-Host "`n================================================" -ForegroundColor $CYAN
    Write-Host " Health Check" -ForegroundColor $CYAN
    Write-Host "================================================`n" -ForegroundColor $CYAN
    
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            Write-Success "Backend is healthy"
            Write-Host $response.Content
        }
    } catch {
        Write-Error-Custom "Backend not responding"
        Write-Host "`nTroubleshooting tips:"
        Write-Host "  - Check logs: .\docker.ps1 logs"
        Write-Host "  - Restart: .\docker.ps1 restart"
    }
}

function Show-Logs {
    Write-Header "Service Logs"
    Write-Host "Press Ctrl+C to stop viewing logs`n"
    docker-compose logs -f --tail=100
}

function Clean-Services {
    Write-Header "Clean Containers"
    Write-Warning "This will remove containers but preserve your data"
    $confirm = Read-Host "Continue? (Y/N)"
    
    if ($confirm -eq 'Y' -or $confirm -eq 'y') {
        docker-compose down
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Containers removed (data preserved in volumes)"
        }
    } else {
        Write-Host "Operation cancelled"
    }
}

function Backup-Data {
    Write-Header "Backup Data Volumes"
    
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $backupDir = "backups\$timestamp"
    
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    
    Write-Host "Creating backup in $backupDir...`n"
    
    Write-Host "[1/4] Backing up uploads..."
    docker run --rm -v doc-chat-uploads:/data -v ${PWD}/${backupDir}:/backup alpine tar czf /backup/uploads.tar.gz -C /data .
    
    Write-Host "[2/4] Backing up images..."
    docker run --rm -v doc-chat-images:/data -v ${PWD}/${backupDir}:/backup alpine tar czf /backup/images.tar.gz -C /data .
    
    Write-Host "[3/4] Backing up vector database..."
    docker run --rm -v doc-chat-chroma:/data -v ${PWD}/${backupDir}:/backup alpine tar czf /backup/chroma.tar.gz -C /data .
    
    Write-Host "[4/4] Backing up users database..."
    docker run --rm -v doc-chat-users:/data -v ${PWD}/${backupDir}:/backup alpine tar czf /backup/users.tar.gz -C /data .
    
    Write-Success "Backup completed successfully!"
    Write-Host "Location: $backupDir`n"
    Get-ChildItem $backupDir
}

function Start-DevMode {
    Write-Header "Starting Development Mode"
    docker-compose -f docker-compose.dev.yml up -d
    
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Development mode started!"
        Write-Host "`n  Frontend: http://localhost:8080" -ForegroundColor $GREEN
        Write-Host "  Backend:  http://localhost:8000" -ForegroundColor $GREEN
        Write-Host "`n  Code changes will auto-reload!`n" -ForegroundColor $YELLOW
    }
}

function Show-Help {
    Write-Header "RAG Document Chat - Docker Commands"
    
    Write-Host "Usage: .\docker.ps1 <command>`n"
    
    Write-Host "Commands:" -ForegroundColor $CYAN
    Write-Host "  start      Start all services (default setup)" -ForegroundColor $GREEN
    Write-Host "  stop       Stop all services" -ForegroundColor $YELLOW
    Write-Host "  restart    Restart all services" -ForegroundColor $YELLOW
    Write-Host "  status     Check service status and health" -ForegroundColor $CYAN
    Write-Host "  logs       View service logs (Ctrl+C to exit)" -ForegroundColor $CYAN
    Write-Host "  clean      Remove containers (keeps data)" -ForegroundColor $RED
    Write-Host "  backup     Backup all data volumes" -ForegroundColor $GREEN
    Write-Host "  dev        Start in development mode" -ForegroundColor $YELLOW
    Write-Host "  help       Show this help message`n" -ForegroundColor $CYAN
    
    Write-Host "Examples:" -ForegroundColor $CYAN
    Write-Host "  .\docker.ps1 start" -ForegroundColor $GREEN
    Write-Host "  .\docker.ps1 logs" -ForegroundColor $GREEN
    Write-Host "  .\docker.ps1 status`n" -ForegroundColor $GREEN
    
    Write-Host "Quick Access:" -ForegroundColor $CYAN
    Write-Host "  Frontend:  http://localhost" -ForegroundColor $GREEN
    Write-Host "  Backend:   http://localhost:8000" -ForegroundColor $GREEN
    Write-Host "  API Docs:  http://localhost:8000/docs`n" -ForegroundColor $GREEN
}

# Main script logic
switch ($Command) {
    'start'   { Start-Services }
    'stop'    { Stop-Services }
    'restart' { Restart-Services }
    'status'  { Show-Status }
    'logs'    { Show-Logs }
    'clean'   { Clean-Services }
    'backup'  { Backup-Data }
    'dev'     { Start-DevMode }
    'help'    { Show-Help }
    default   { Show-Help }
}
