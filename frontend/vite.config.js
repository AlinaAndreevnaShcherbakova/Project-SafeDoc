import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: ["localhost", "127.0.0.1", "safedoc.tech", "www.safedoc.tech"],
  },
  preview: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: ["localhost", "127.0.0.1", "safedoc.tech", "www.safedoc.tech"],
  },
});
