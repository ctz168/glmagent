# Mini-Services

This directory contains sub-services that run alongside the main Next.js application.
Each sub-service is a standalone Node.js/Bun project with its own `package.json`.

## Structure

```
mini-services/
├── .example/          # Example template (not a real service)
└── your-service/      # Your custom service
    ├── package.json   # Must have a "dev" script
    └── ...            # Your service code
```

## How It Works

During container startup, `start.sh` scans this directory and:
1. Finds all sub-directories with `package.json`
2. Runs `bun install` for each service
3. Starts `bun run dev` for services that define a "dev" script
4. Each service runs in the background and logs to `/tmp/mini-service-{name}.log`

## Creating a New Mini-Service

```bash
mkdir mini-services/my-service
cd mini-services/my-service
bun init
# Edit package.json to add a "dev" script
```

Example `package.json`:

```json
{
  "name": "my-service",
  "scripts": {
    "dev": "bun run src/index.ts"
  }
}
```

## Port Allocation

Mini-services are typically proxied through Caddy:
- Port 3000 → Main Next.js app (proxied via `:19005`)
- Port 3001 → Additional service (proxied via `:19006`)
- Other ports → Configure additional Caddy listeners as needed
