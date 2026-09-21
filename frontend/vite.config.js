import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    headers: {
      "Content-Security-Policy": [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "connect-src 'self' http://127.0.0.1:8000 http://localhost:8000 ws://127.0.0.1:5173 ws://localhost:5173",
        "img-src 'self' data:",
        "font-src 'self'",
      ].join("; "),
    },
  },
});
