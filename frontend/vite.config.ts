import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// "@/..." means "src/..." in imports, so we never write ../../../
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: { port: 5173 },
});
