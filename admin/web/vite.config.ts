import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// En développement (npm run dev), l'API est servie par la console sur le port 8788.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "dist", sourcemap: false },
  server: { proxy: { "/api": "http://127.0.0.1:8788" } },
});
