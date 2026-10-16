import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // El navegador solo habla con Next.js; /api/* se reenvia a FastAPI.
  // Evita CORS y mantiene la logica del agente fuera del frontend.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
};

export default nextConfig;
