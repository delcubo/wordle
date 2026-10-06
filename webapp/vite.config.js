import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      // Две точки входа: страницы игроков (index.html) и админка (a.html) —
      // админский код не попадает в бандл игроков (см. src/adminBase.js).
      input: {
        main: resolve(__dirname, "index.html"),
        a: resolve(__dirname, "a.html"),
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
