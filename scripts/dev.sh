#!/bin/bash
# ============================================================
# GLM Agent Engine - Local Development Setup
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo " GLM Agent Engine - Local Dev Setup"
echo "=========================================="
echo "Project Dir: $PROJECT_DIR"
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is required but not installed."
    echo "Install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check Docker Compose
if ! docker compose version &> /dev/null; then
    echo "ERROR: Docker Compose is required but not installed."
    exit 1
fi

# Create .env file if not exists
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cat > "$PROJECT_DIR/.env" << 'EOF'
# GLM Agent Engine Configuration
# Copy this file and customize for your environment

# Z.ai Backend API
ZAI_BASE_URL=http://host.docker.internal:8080/v1
ZAI_API_KEY=your-api-key

# Server
PORT=81

# Container metadata
FC_REGION=local
FC_INSTANCE_ID=glm-agent-dev-001
FC_FUNCTION_NAME=glm-agent-local
EOF
    echo "Created .env file. Please configure your ZAI API key."
fi

# Create data directories
mkdir -p "$PROJECT_DIR/data"/{project,upload,download,db,sync}

# Build and start
echo "Building Docker image..."
docker compose -f "$PROJECT_DIR/docker-compose.yml" build

echo "Starting services..."
docker compose -f "$PROJECT_DIR/docker-compose.yml" up -d

echo ""
echo "=========================================="
echo " GLM Agent Engine is running!"
echo "=========================================="
echo "  Public URL:   http://localhost:81"
echo "  API Docs:     http://localhost:12600/docs"
echo "  Health Check: http://localhost:81/health"
echo ""
echo "  Press Ctrl+C to stop."
echo "=========================================="

# Follow logs
docker compose -f "$PROJECT_DIR/docker-compose.yml" logs -f glm-agent
