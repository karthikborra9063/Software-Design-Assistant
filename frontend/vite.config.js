import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, proxy /api to the Flask backend so there are no CORS issues and no need to set
// VITE_API_URL locally. In production (Vercel), set VITE_API_URL to the Render backend URL.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:5000",
    },
  },
});
