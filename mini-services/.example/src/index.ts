// Example mini-service entry point
// This runs on port 3001 alongside the main Next.js app

const server = Bun.serve({
  port: 3001,
  fetch(req) {
    return new Response(JSON.stringify({
      service: "mini-service-example",
      status: "running",
      timestamp: new Date().toISOString(),
    }), {
      headers: { "Content-Type": "application/json" },
    });
  },
});

console.log(`Mini-service example running on http://localhost:${server.port}`);
