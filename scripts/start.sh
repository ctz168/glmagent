#!/bin/bash
# ============================================================
# GLM Agent Engine - Container Start Script
# Replicated from Z.ai Container Runtime (/start.sh)
# ============================================================

set -e

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

export -f log_step_start
export -f log_step_end

# ===================== Step 1: Project Init =================

log_step_start "Project initialization check"
SYNC_DIR=/home/sync
if [ -z "$(ls -A $SYNC_DIR 2>/dev/null | grep -v "^\.")" ]; then
  echo "Clean project environment detected"
  echo "DATABASE_URL=file:/home/z/my-project/db/custom.db" > /home/z/my-project/.env
  mkdir -p /home/z/my-project/download && echo "Here are all the generated files." > /home/z/my-project/download/README.md
  chown -R z:z /home/z/my-project/download
  chmod -R 755 /home/z/my-project/download
  mkdir -p /home/z/my-project/skills
  chown -R z:z /home/z/my-project/skills
  chmod -R 755 /home/z/my-project/skills
  mkdir -p /home/z/my-project/db
  chown -R z:z /home/z/my-project/db
else
  echo "restoring $SYNC_DIR to /home/z/my-project"
  if [ -d "/home/z/my-project" ]; then
    echo "Cleaning project directory (preserving mount points)..."
    find /home/z/my-project -mindepth 1 -maxdepth 1 ! -path "/home/z/my-project/upload" -exec rm -rf {} + 2>/dev/null || true
    if ! mountpoint -q /home/z/my-project/upload 2>/dev/null; then
      rm -rf /home/z/my-project/upload
    fi
  fi
  mkdir -p /home/z/my-project
  tar xf $SYNC_DIR/repo.tar -C /home/z/my-project
  echo "DATABASE_URL=file:/home/z/my-project/db/custom.db" > /home/z/my-project/.env

  if mountpoint -q /home/z/my-project/upload 2>/dev/null; then
    find /home/z/my-project -mindepth 1 -maxdepth 1 ! -path "/home/z/my-project/upload" -exec chown -R z:z {} + 2>/dev/null || true
    find /home/z/my-project -mindepth 1 -maxdepth 1 ! -path "/home/z/my-project/upload" -exec chmod -R 755 {} + 2>/dev/null || true
  else
    chown -R z:z /home/z/my-project
    chmod -R 755 /home/z/my-project
  fi
fi
chown -R z:z /home/z/my-project/.env
log_step_end "Project initialization check"

# ===================== Step 2: Skills Setup =================

log_step_start "Extracting official skills to project"
if [ -d "/home/official_skills" ]; then
  echo "Extracting skills from /home/official_skills to /home/z/my-project/skills..."
  mkdir -p /home/z/my-project/skills

  allowed_skills=""
  if [ -f "/home/official_skills/stages.yaml" ]; then
    allowed_skills=$(grep -E '^\s+-\s+\S' /home/official_skills/stages.yaml | sed 's/^\s*-\s*//' | tr -d '"'"'")
    echo "Stages config found, allowed skills: $(echo "$allowed_skills" | tr '\n' ' ')"
  fi

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

# ===================== Step 3: Permissions ==================

log_step_start "Setting permissions"
chown z:z /home/z
chmod 755 /home/z
mkdir -p /home/sync
if mountpoint -q /home/sync 2>/dev/null; then
  echo "Skipping permission changes on mount point: /home/sync"
else
  chmod 777 /home/sync
fi
log_step_end "Setting permissions"

# ===================== Step 4: Git Setup ====================

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

log_step_start "Z.ai config setup"
ZAI_CONFIG_FILE="/etc/.z-ai-config"
if [ ! -f "$ZAI_CONFIG_FILE" ]; then
  ZAI_BASE_URL="${ZAI_BASE_URL:-http://172.25.136.193:8080/v1}"
  ZAI_API_KEY="${ZAI_API_KEY:-Z.ai}"
  echo "{\"baseUrl\": \"$ZAI_BASE_URL\", \"apiKey\": \"$ZAI_API_KEY\"}" > "$ZAI_CONFIG_FILE"
fi
chmod 444 "$ZAI_CONFIG_FILE"
log_step_end "Z.ai config setup"

# ===================== Service Helpers =======================

wait_for_service() {
    local host="$1"
    local port="$2"
    local service_name="$3"
    local max_attempts=60
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

# ===================== Step 6: Start Agent Engine ============

log_step_start "Starting GLM Agent Engine"
echo "Starting Agent Engine in background..."
(cd /app && uv run main.py) &
AGENT_PID=$!
log_step_end "Starting GLM Agent Engine"

# ===================== Step 7: Project Services ==============

echo "Starting project initialization in background..."
if [ -f "/home/z/my-project/.zscripts/dev.sh" ]; then
  echo "[INIT] Found custom dev script, running custom flow..."
  (
    log_step_start "custom dev script"
    sudo -u z bash /home/z/my-project/.zscripts/dev.sh
    log_step_end "custom dev script"
  ) &
elif [ -f "/home/z/my-project/package.json" ]; then
  echo "[INIT] Found package.json, running bun + mini-services flow..."
  (
    log_step_start "bun install"
    sudo -u z bun install
    log_step_end "bun install"

    log_step_start "bun run db:push"
    sudo -u z bun run db:push 2>/dev/null || echo "[BUN] db:push script not found, skipping..."
    log_step_end "bun run db:push"

    echo "[BUN] Starting development server..."
    sudo -u z bun run dev &

    wait_for_service "localhost" "3000" "Next.js dev server" || true
    echo "[BUN] Dev server started."
  ) &

  # Mini-services
  MINI_SERVICES_DIR="/home/z/my-project/mini-services"
  if [ -d "$MINI_SERVICES_DIR" ]; then
    log_step_start "Starting mini-services"
    for service_dir in "$MINI_SERVICES_DIR"/*; do
      if [ -d "$service_dir" ] && [ -f "$service_dir/package.json" ]; then
        service_name=$(basename "$service_dir")
        echo "Starting $service_name in background..."
        (
          cd "$service_dir"
          sudo -u z bun install
          if grep -q '"dev"' package.json; then
            sudo -u z bun run dev
          fi
        ) > /tmp/mini-service-${service_name}.log 2>&1 &
        echo "[$service_name] Started (PID: $!)"
      fi
    done
    log_step_end "Starting mini-services"
  fi
else
  echo "[INIT] No project initialization needed."
fi

# ===================== Step 8: Wait for Agent ===============

log_step_start "Waiting for Agent Engine"
wait_for_service "localhost" "12600" "GLM Agent Engine"
if [ $? -ne 0 ]; then
    echo "ERROR: Agent Engine failed to start"
    exit 1
fi
log_step_end "Waiting for Agent Engine"

# ===================== Step 9: Start Caddy ==================

log_step_start "Starting Caddy server"
echo "Agent Engine is ready. Starting Caddy..."
echo "Caddy will run in foreground mode as the main process"
exec caddy run --config /app/Caddyfile --adapter caddyfile
