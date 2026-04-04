#!/bin/bash
# ============================================================
# GLM Agent Engine - Container Start Script
# Replicated from Z.ai Container Runtime (/start.sh)
#
# This is the PID 1 entrypoint (via tini). It performs:
# 1. Project initialization (clean start or restore from /home/sync)
# 2. Official skills extraction from /home/official_skills
# 3. Permission setup
# 4. Git repository initialization
# 5. Z.ai backend config writing (with IM gateway metadata)
# 6. Playwright browser installation check
# 7. Redis connection check (optional)
# 8. ZAI Agent Engine startup (background)
# 9. Bun/Next.js project initialization (background)
# 10. Mini-services startup (background)
# 11. Caddy reverse proxy (foreground, PID 1)
# ============================================================

set -e

# ===================== Signal Handling =======================
# Cleanup on shutdown: kill background processes, flush logs

cleanup() {
    echo "=========================================="
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Shutting down..."
    echo "=========================================="

    # Kill the ZAI engine if running
    if [ -n "$ZAI_PID" ] && kill -0 "$ZAI_PID" 2>/dev/null; then
        echo "Stopping ZAI engine (PID: $ZAI_PID)..."
        kill -TERM "$ZAI_PID" 2>/dev/null || true
    fi

    # Kill the bun/dev process if running
    if [ -n "$BUN_PID" ] && kill -0 "$BUN_PID" 2>/dev/null; then
        echo "Stopping project process (PID: $BUN_PID)..."
        kill -TERM "$BUN_PID" 2>/dev/null || true
    fi

    # Kill any mini-service processes we spawned
    if [ -n "$MINI_SERVICE_PIDS" ]; then
        echo "Stopping mini-services..."
        for pid in $MINI_SERVICE_PIDS; do
            if kill -0 "$pid" 2>/dev/null; then
                kill -TERM "$pid" 2>/dev/null || true
            fi
        done
    fi

    # Wait briefly for graceful shutdown
    sleep 2

    echo "Shutdown complete."
}

trap cleanup EXIT SIGTERM SIGINT SIGQUIT

# ===================== Logging Helpers ======================

log_step_start() {
    local step_name="$1"
    echo "=========================================="
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting: $step_name"
    echo "=========================================="
    export STEP_START_TIME=$(date +%s)
}

log_step_end() {
    local step_name="$1"
    if [ -z "$step_name" ]; then
        step_name="Unknown step"
    fi
    local end_time=$(date +%s)
    local duration=$((end_time - STEP_START_TIME))
    echo "=========================================="
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Completed: $step_name"
    echo "[LOG] Step: $step_name | Duration: ${duration}s"
    echo "=========================================="
    echo ""
}

# Export functions so subshells can use them
export -f log_step_start
export -f log_step_end

# Track mini-service PIDs for cleanup
MINI_SERVICE_PIDS=""

# ===================== Step 1: Project Init =================
# FIXME: Project initialization check should use a marker file, not directory emptiness

log_step_start "Project initialization check"
SYNC_DIR=/home/sync
if [ -z "$(ls -A $SYNC_DIR 2>/dev/null | grep -v "^\.")" ]; then
  echo "Whoa, wat a nice clean project"
  echo "DATABASE_URL=file:/home/z/my-project/db/custom.db" > /home/z/my-project/.env
  mkdir -p /home/z/my-project/download && echo "Here are all the generated files." > /home/z/my-project/download/README.md
  chown -R z:z /home/z/my-project/download
  chmod -R 755 /home/z/my-project/download
  # Ensure skills directory exists and set permissions (only chown skills, avoid recursive entire project)
  mkdir -p /home/z/my-project/skills
  chown -R z:z /home/z/my-project/skills
  chmod -R 755 /home/z/my-project/skills
  # Ensure db directory exists
  mkdir -p /home/z/my-project/db
  chown -R z:z /home/z/my-project/db
else
  echo "restoring $SYNC_DIR to /home/z/my-project"
  # Handle potential mount points (e.g. upload directory)
  if [ -d "/home/z/my-project" ]; then
    echo "Cleaning project directory (preserving mount points)..."
    # Delete all files and directories, but skip mount points
    find /home/z/my-project -mindepth 1 -maxdepth 1 ! -path "/home/z/my-project/upload" -exec rm -rf {} + 2>/dev/null || true
    # If upload is not a mount point, delete it too
    if ! mountpoint -q /home/z/my-project/upload 2>/dev/null; then
      rm -rf /home/z/my-project/upload
    else
      echo "Skipping /home/z/my-project/upload (mount point detected)"
    fi
  fi
  mkdir -p /home/z/my-project
  tar xf $SYNC_DIR/repo.tar -C /home/z/my-project
  echo "DATABASE_URL=file:/home/z/my-project/db/custom.db" > /home/z/my-project/.env

  # Fix ownership and permissions, excluding mount points
  if mountpoint -q /home/z/my-project/upload 2>/dev/null; then
    echo "Setting ownership (handling upload mount point specially)..."
    find /home/z/my-project -mindepth 1 -maxdepth 1 ! -path "/home/z/my-project/upload" -exec chown -R z:z {} + 2>/dev/null || true
    find /home/z/my-project -mindepth 1 -maxdepth 1 ! -path "/home/z/my-project/upload" -exec chmod -R 755 {} + 2>/dev/null || true
    # OSS mount point is read-only, skip permission changes
    echo "Skipping permission changes on OSS mount point: /home/z/my-project/upload"
  else
    echo "Setting ownership (no mount points detected)..."
    chown -R z:z /home/z/my-project
    chmod -R 755 /home/z/my-project
  fi
fi
chown -R z:z /home/z/my-project/.env
log_step_end "Project initialization check"

# ===================== Step 2: Skills Setup =================
# Extract official skills from /home/official_skills to project

log_step_start "Extracting official skills to project"
if [ -d "/home/official_skills" ]; then
  echo "Extracting skills from /home/official_skills to /home/z/my-project/skills..."
  mkdir -p /home/z/my-project/skills

  # Collect allowed skill names from stages.yaml (all stage forward references), no config means no restriction
  allowed_skills=""
  if [ -f "/home/official_skills/stages.yaml" ]; then
    allowed_skills=$(grep -E '^\s+-\s+\S' /home/official_skills/stages.yaml | sed 's/^\s*-\s*//' | tr -d '"'"'")
    echo "Stages config found, allowed skills: $(echo "$allowed_skills" | tr '\n' ' ')"
  fi

  # Iterate all .zip files and extract (root execution, since z user cannot read /home/official_skills/)
  zip_count=0
  for zip_file in /home/official_skills/*.zip; do
    if [ -f "$zip_file" ]; then
      skill_name=$(basename "$zip_file" .zip)
      if [ -n "$allowed_skills" ] && ! echo "$allowed_skills" | grep -qx "$skill_name"; then
        echo "Skipping $skill_name: not in stages config"
        continue
      fi
      echo "Extracting $(basename "$zip_file")..."
      unzip -q -o "$zip_file" -x '__MACOSX/*' -x '*.DS_Store' -x '._*' -d /home/z/my-project/skills/
      zip_count=$((zip_count + 1))
    fi
  done

  # Remove official skills not in stages config (only clean when stages.yaml exists)
  if [ -n "$allowed_skills" ]; then
    for skill_dir in /home/z/my-project/skills/*/; do
      if [ -d "$skill_dir" ]; then
        skill_name=$(basename "$skill_dir")
        if [ -f "/home/official_skills/${skill_name}.zip" ] && ! echo "$allowed_skills" | grep -qx "$skill_name"; then
          echo "Removing disallowed official skill: $skill_name"
          rm -rf "$skill_dir"
        fi
      fi
    done
  fi

  # Fix ownership and permissions after extraction
  # (root extraction causes owner to be root, zip may store restricted permissions)
  chown -R z:z /home/z/my-project/skills/ 2>/dev/null || true
  chmod -R 755 /home/z/my-project/skills/ 2>/dev/null || true

  if [ $zip_count -eq 0 ]; then
    echo "No zip files found in /home/official_skills"
  else
    echo "Successfully extracted $zip_count skill(s)"
  fi
else
  echo "Warning: /home/official_skills directory not found"
fi
log_step_end "Extracting official skills to project"


# Set permissions first to prevent user config issues
log_step_start "Setting permissions"
chown z:z /home/z
chmod 755 /home/z
# Ensure /home/sync directory exists and give z user read/write permissions
mkdir -p /home/sync
# Check if /home/sync is a mount point, if so skip permission changes
if mountpoint -q /home/sync 2>/dev/null; then
  echo "Skipping permission changes on mount point: /home/sync"
else
  chmod 777 /home/sync
fi
log_step_end "Setting permissions"

# Initialize git (first time only)
log_step_start "Git setup"
cd /home/z/my-project

su z -c "
git config --global --add safe.directory /home/z/my-project
git config --global user.email 'z@container'
git config --global user.name 'Z User'
"

if [ ! -d ".git" ]; then
  echo "Initializing git repository for the first time..."
  su z -c "
  cd /home/z/my-project
  git config --global init.defaultBranch main
  git init
  git add .
  git commit -m 'Initial commit'
  "
else
  echo "Existing git repository detected, preserving current git state."
fi
log_step_end "Git setup"

# ===================== Step 5: Z.ai Config ==================
# Write Z.ai backend config (always overwritten, matching production behavior)
# Config now includes chatId, token, userId from IM gateway metadata

log_step_start "Z.ai config setup"
ZAI_CONFIG_FILE="/etc/.z-ai-config"
ZAI_BASE_URL="${ZAI_BASE_URL:-http://172.25.136.193:8080/v1}"
ZAI_API_KEY="${ZAI_API_KEY:-Z.ai}"

# IM gateway metadata (set by orchestrator, empty in local dev)
ZAI_CHAT_ID="${ZAI_CHAT_ID:-}"
ZAI_TOKEN="${ZAI_TOKEN:-}"
ZAI_USER_ID="${ZAI_USER_ID:-}"

# Build config JSON (always overwrite)
if [ -n "$ZAI_CHAT_ID" ] || [ -n "$ZAI_TOKEN" ] || [ -n "$ZAI_USER_ID" ]; then
  # Full config with IM gateway metadata
  cat > "$ZAI_CONFIG_FILE" <<ZAI_EOF
{
  "baseUrl": "$ZAI_BASE_URL",
  "apiKey": "$ZAI_API_KEY",
  "chatId": "$ZAI_CHAT_ID",
  "token": "$ZAI_TOKEN",
  "userId": "$ZAI_USER_ID"
}
ZAI_EOF
  echo "Z.ai config written with IM gateway metadata (chatId=$ZAI_CHAT_ID, userId=$ZAI_USER_ID)"
else
  # Minimal config without IM metadata
  echo "{\"baseUrl\": \"$ZAI_BASE_URL\", \"apiKey\": \"$ZAI_API_KEY\"}" > "$ZAI_CONFIG_FILE"
  echo "Z.ai config written (minimal, no IM metadata)"
fi
chmod 444 "$ZAI_CONFIG_FILE"
log_step_end "Z.ai config setup"

# ===================== Step 6: Playwright Check ==============
# Ensure Playwright browser is installed and cache dir exists

log_step_start "Playwright browser check"
mkdir -p /home/z/.cache
chown -R z:z /home/z/.cache
chmod 755 /home/z/.cache

# Check if Chromium is available (installed via Dockerfile)
if command -v chromium &>/dev/null; then
  echo "Chromium browser found: $(chromium --version 2>/dev/null || echo 'version unknown')"
else
  echo "Warning: Chromium browser not found. Browser automation features may not work."
  echo "Install it with: /app/.venv/bin/playwright install chromium"
fi

# Verify Playwright itself is available
if [ -x "/app/.venv/bin/playwright" ]; then
  echo "Playwright CLI available: $(/app/.venv/bin/playwright --version 2>/dev/null || echo 'version unknown')"
else
  echo "Warning: Playwright CLI not found at /app/.venv/bin/playwright"
fi
log_step_end "Playwright browser check"

# ===================== Step 7: Redis Check (Optional) ========
# Check Redis connectivity if REDIS_URL is set

log_step_start "Redis connection check"
REDIS_URL="${REDIS_URL:-}"
if [ -n "$REDIS_URL" ]; then
  echo "REDIS_URL is configured: ${REDIS_URL%%@*}@***"
  # Basic connectivity check via the engine health endpoint later
  echo "Redis will be verified when engine starts."
else
  echo "REDIS_URL is not configured. Redis features disabled."
  echo "Set REDIS_URL=redis://host:6379/0 to enable Redis caching and sessions."
fi
log_step_end "Redis connection check"

# ===================== Service Helpers =======================

wait_for_service() {
    local host="$1"
    local port="$2"
    local service_name="$3"
    local max_attempts="${4:-60}"
    local attempt=1

    echo "Waiting for $service_name to be ready on $host:$port..."

    while [ $attempt -le $max_attempts ]; do
        if curl -s --connect-timeout 2 --max-time 5 "http://$host:$port" > /dev/null 2>&1; then
            echo "$service_name is ready!"
            return 0
        fi

        echo "Attempt $attempt/$max_attempts: $service_name not ready yet, waiting..."
        sleep 1
        attempt=$((attempt + 1))
    done

    echo "ERROR: $service_name failed to start within $((max_attempts * 2)) seconds"
    return 1
}

# ===================== Step 8: Start ZAI Service =============
# Start ZAI Agent Engine in background (root runs /app/, z user cannot access /app/ with 700 perms)

log_step_start "Starting ZAI service"
echo "Starting ZAI service in background as root..."
echo "CLAWHUB_WORKDIR=$CLAWHUB_WORKDIR"
echo "DATABASE_URL=${DATABASE_URL:-not set}"
echo "LOG_LEVEL=${LOG_LEVEL:-INFO}"

(cd /app && uv run main.py) &
ZAI_PID=$!
echo "ZAI engine started with PID: $ZAI_PID"
log_step_end "Starting ZAI service"

# ===================== Step 9: Project Services ==============
# Start bun project initialization in background

echo "Starting project initialization in background..."
# New version: use fullstack skill logic
if [ -f "/home/z/my-project/.zscripts/dev.sh" ]; then
  echo "[INIT] Found custom dev script, running custom flow..."
  (
    log_step_start "custom dev script"
    echo "[DEV] Found /home/z/my-project/.zscripts/dev.sh, executing..."
    sudo -u z bash /home/z/my-project/.zscripts/dev.sh
    log_step_end "custom dev script"
  ) &
  BUN_PID=$!
# Backward compatible: if no custom dev.sh but package.json exists, use bun + mini-services flow
elif [ -f "/home/z/my-project/package.json" ]; then
  echo "[INIT] No custom dev script found, running bun + mini-services flow..."
  (
    log_step_start "bun install"
    echo "[BUN] Installing dependencies..."
    sudo -u z bun install
    log_step_end "bun install"

    log_step_start "bun run db:push"
    echo "[BUN] Setting up database..."
    sudo -u z bun run db:push 2>/dev/null || echo "[BUN] db:push not found, skipping..."
    log_step_end "bun run db:push"

    echo "[BUN] Starting development server..."
    sudo -u z bun run dev &

    # Wait for dev server to be ready
    wait_for_service "localhost" "3000" "Next.js dev server"

    # Health check after service is ready
    echo "[BUN] Performing health check..."
    curl localhost:3000 || echo "[BUN] Health check failed, but continuing..."
  ) &
  BUN_PID=$!

  # Start mini-services sub-services in background (non-blocking)
  log_step_start "Starting mini-services"
  MINI_SERVICES_DIR="/home/z/my-project/mini-services"
  if [ -d "$MINI_SERVICES_DIR" ]; then
    echo "Found mini-services directory, scanning for sub-services..."

    # Iterate all sub-directories in mini-services
    for service_dir in "$MINI_SERVICES_DIR"/*; do
      if [ -d "$service_dir" ]; then
        service_name=$(basename "$service_dir")
        echo "Checking service: $service_name"

        # Check if package.json exists
        if [ -f "$service_dir/package.json" ]; then
          echo "Starting $service_name (has package.json) in background..."
          (
            cd "$service_dir"
            # Install dependencies first
            echo "[$service_name] Installing dependencies in background..."
            sudo -u z bun install
            # Only run dev script
            if grep -q '"dev"' package.json; then
              echo "[$service_name] Running bun run dev..."
              sudo -u z bun run dev
            else
              echo "[$service_name] No dev script found, skipping..."
            fi
          ) > /tmp/mini-service-${service_name}.log 2>&1 &
          SERVICE_PID=$!
          MINI_SERVICE_PIDS="$MINI_SERVICE_PIDS $SERVICE_PID"
          echo "[$service_name] Started in background (PID: $SERVICE_PID)"
        else
          echo "[$service_name] No package.json found, skipping..."
        fi
      fi
    done

    echo "Mini-services startup initiated (all running in background)"
  else
    echo "Mini-services directory not found, skipping..."
  fi
  log_step_end "Starting mini-services"
else
  echo "[INIT] Neither custom dev script nor package.json found, skipping project initialization."
fi

# ===================== Step 10: Wait for ZAI ================

log_step_start "Waiting for ZAI service"
wait_for_service "localhost" "${ENGINE_PORT:-12600}" "ZAI Control Service"
if [ $? -ne 0 ]; then
    echo "ERROR: ZAI service failed to start"
    exit 1
fi

# Verify engine is actually responding (not just accepting connections)
echo "Performing engine health check..."
ENGINE_HEALTH=$(curl -sf --max-time 5 "http://localhost:${ENGINE_PORT:-12600}/health" 2>/dev/null || echo "FAILED")
if [ "$ENGINE_HEALTH" = "FAILED" ]; then
    echo "Warning: Engine health check returned non-200, but port is open. Continuing anyway."
else
    echo "Engine health check passed: $ENGINE_HEALTH"
fi
log_step_end "Waiting for ZAI service"

# ===================== Step 11: Start Caddy =================

log_step_start "Starting Caddy server"
echo "All services are ready. Starting Caddy with configuration from /app/Caddyfile..."
echo "Caddy will run in foreground mode as the main process (PID 1)"
echo "Listening on port: ${FC_CUSTOM_LISTEN_PORT:-81}"
exec caddy run --config /app/Caddyfile --adapter caddyfile
