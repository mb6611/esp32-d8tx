import { defineConfig } from "vite";

// `npm run dev` serves the UI on :5173 and proxies /ws to the d8live backend
// (`esp32sdr d8live`, default 127.0.0.1:8765). `npm run build` writes dist/,
// which the backend serves itself at http://127.0.0.1:8765/.
export default defineConfig({
  server: {
    proxy: { "/ws": { target: "ws://127.0.0.1:8765", ws: true } },
  },
});
