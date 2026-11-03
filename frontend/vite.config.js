import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.VITE_BACKEND_PROXY || "http://127.0.0.1:8000";
  // When FastAPI isn't running, Vite would answer with a bare "500". Answer 502 with an explicit message instead.
  const explain = (proxy) => proxy.on("error", (err, _req, res) => {
    if (!res || res.headersSent || typeof res.writeHead !== "function") return;
    res.writeHead(502, { "Content-Type": "application/json" });
    res.end(JSON.stringify({
      detail: `PreVuCam API not reachable at ${backend} (${err.code || err.message}). Start the backend: cd backend && python run.py`,
      backend_unreachable: true,
    }));
  });
  const api = { target: backend, changeOrigin: true, configure: explain };
  return {
    plugins: [react()],
    server: {
      port: 5173,
      host: true,
      proxy: {
        "/api": api,
        "/media": api,
        "/docs": api,
        "/redoc": api,
        "/openapi.json": api,
        "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
      },
    },
  };
});
