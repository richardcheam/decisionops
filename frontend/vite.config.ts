import { defineConfig } from "vite";
export default defineConfig({
  server: {
    proxy: {
      "/pilot-api": "http://127.0.0.1:8000",
      "/api": "http://127.0.0.1:8000",
      "/customer-api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
