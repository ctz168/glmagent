# ============================================================
# GLM Agent Container - Replicated from Z.ai Runtime
# Base: Debian 13 (trixie) | Arch: x86_64
# ============================================================
FROM debian:trixie-slim

LABEL maintainer="ctz168"
LABEL description="GLM Agent Engine Container - Z.ai Runtime Replica"
LABEL version="1.0.0"

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV LC_CTYPE=C.UTF-8
ENV LANG=C.UTF-8
ENV TERM=dumb
ENV NO_COLOR=1
ENV CLICOLOR=0

# ===================== System Packages =======================
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Core utilities
    tini \
    bash \
    curl \
    wget \
    ca-certificates \
    gnupg \
    lsb-release \
    # Network & Process tools
    netcat-openbsd \
    iproute2 \
    iputils-ping \
    procps \
    # Archive & File tools
    unzip \
    tar \
    jq \
    rsync \
    tree \
    # Build essentials
    build-essential \
    cmake \
    # Git
    git \
    # Python build deps
    libffi-dev \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncurses5-dev \
    libncursesw5-dev \
    liblzma-dev \
    uuid-dev \
    tk-dev \
    # Image processing
    libjpeg-dev \
    libpng-dev \
    libwebp-dev \
    libtiff-dev \
    # GDAL (geospatial)
    gdal-bin \
    libgdal-dev \
    # PDF & OCR processing
    poppler-utils \
    tesseract-ocr \
    qpdf \
    # Archive support
    p7zip-full \
    # Browser automation (Chromium for Playwright)
    chromium \
    chromium-driver \
    # Misc
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# ===================== Node.js 24 ============================
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Verify Node.js
RUN node --version && npm --version

# ===================== Bun Runtime ===========================
RUN npm install -g bun@latest \
    && bun --version

# ===================== Python 3.12 via uv ====================
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN uv python install 3.12

# Create Python venv for the agent engine
RUN uv venv /app/.venv --python 3.12 \
    && /app/.venv/bin/pip install --no-cache-dir --upgrade pip

# Set venv prompt
RUN sed -i 's/PS1=.*/PS1="(z-agent) \\$ "/' /app/.venv/bin/activate 2>/dev/null || true

# ===================== Java 21 (OpenJDK) ====================
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-21-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

# ===================== Caddy Web Server ======================
RUN apt-get update && apt-get install -y --no-install-recommends \
    debian-keyring debian-archive-keyring apt-transport-https curl \
    && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg \
    && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list \
    && apt-get update && apt-get install -y caddy \
    && rm -rf /var/lib/apt/lists/*

# ===================== Docker CLI ============================
RUN curl -fsSL https://get.docker.com | sh

# ===================== User Setup ============================
# Create application user (matching Z.ai runtime: uid=1001)
RUN groupadd -g 1001 z \
    && useradd -u 1001 -g 1001 -m -s /bin/bash z

# Create project directories
RUN mkdir -p /home/z/my-project \
    && mkdir -p /home/z/my-project/download \
    && mkdir -p /home/z/my-project/skills \
    && mkdir -p /home/z/my-project/upload \
    && mkdir -p /home/z/my-project/db \
    && mkdir -p /home/z/.bun \
    && mkdir -p /home/z/.cache \
    && mkdir -p /home/sync \
    && mkdir -p /home/official_skills \
    && mkdir -p /home/user_skills \
    && mkdir -p /tmp/mini-services

# Set permissions
RUN chown -R z:z /home/z \
    && chmod 755 /home/z \
    && chmod 777 /home/sync \
    && chown -R z:z /home/z/.cache \
    && chmod 755 /tmp/mini-services

# ===================== App Directory =========================
# /app is the agent engine directory (restricted to root)
COPY app/ /app/
RUN chmod 700 /app \
    && chmod -R 755 /app/.venv \
    && chown -R root:root /app

# Install Python dependencies for agent engine
RUN cd /app && uv pip install --python /app/.venv/bin/python -r requirements.txt

# ===================== Playwright Setup ======================
# Install Chromium browser and system dependencies for Playwright
RUN /app/.venv/bin/playwright install chromium \
    && /app/.venv/bin/playwright install-deps chromium

# ===================== Caddy Configuration ===================
COPY config/Caddyfile /app/Caddyfile
COPY config/index.html /app/static/index.html
COPY config/logo.svg /app/static/logo.svg

# ===================== Start Script ==========================
COPY scripts/start.sh /start.sh
RUN chmod +x /start.sh

# ===================== Skills ================================
COPY skills/ /home/z/my-project/skills/
RUN chown -R z:z /home/z/my-project/skills \
    && chmod -R 755 /home/z/my-project/skills

# ===================== Environment ==========================
# These ENV variables match the real Z.ai production Kata Container runtime exactly.
ENV HOME=/home/z
ENV PATH="/home/z/.venv/bin:/app/.venv/bin:/usr/local/bin:/home/z/.bun/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/local/bun-node-fallback-bin"
ENV VIRTUAL_ENV=/app/.venv
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV UV=/usr/local/bin/uv
ENV UV_CACHE_DIR=/var/cache/uv
ENV UV_PYTHON=3.12
ENV BUN_INSTALL=/home/z/.bun
ENV BUN_INSTALL_BIN=/usr/local/bin
ENV BUN_RUNTIME_TRANSPILER_CACHE_PATH=0
ENV DATABASE_URL=file:/home/z/my-project/db/custom.db
ENV KATA_CONTAINER=true
ENV SHELL=/bin/bash
ENV CLICOLOR_FORCE=0

# Datadog tracing & observability
ENV DD_TRACE_ENABLED=true
ENV DD_SERVICE=glm-agent-engine
ENV DD_ENV=production

# Redis
ENV REDIS_URL=redis://localhost:6379/0

# Logging
ENV LOG_LEVEL=INFO

# Container metadata (defaults for local/dev, overridden by orchestrator in production)
ENV CLAWHUB_WORKDIR=/home/z/my-project
ENV CLAWHUB_DISABLE_TELEMETRY=1
ENV FC_REGION=cn-hongkong
ENV FC_FUNCTION_HANDLER=index.handler
ENV FC_FUNCTION_MEMORY_SIZE=8192
ENV FC_CUSTOM_LISTEN_PORT=81

# Runtime step timing (set by start.sh for uptime calculation)
ENV STEP_START_TIME=0

# Working directory for the user
WORKDIR /home/z/my-project

# Expose ports
# 81: Caddy (public facing, HTTP)
# 12600: ZAI Agent Engine (internal)
# 19001, 19005, 19006: Additional internal services
EXPOSE 81 12600 19001 19005 19006

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:12600/health || exit 1

# Use tini as PID 1 init system
ENTRYPOINT ["/usr/bin/tini", "--"]

# Start the container
CMD ["/start.sh"]
