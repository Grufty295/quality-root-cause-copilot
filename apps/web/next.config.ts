import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // Tailwind v4 con Turbopack: sin este loader el CSS sale sin las clases de utilidad.
  turbopack: {
    rules: {
      "*.css": { loaders: ["@tailwindcss/turbopack"], as: "*.css" },
    },
  },
  experimental: {
    // /ncrs/{id}/analyze tarda minutos. La UI no espera esa respuesta (sigue la corrida por
    // /runs), pero el proxy no debe cortarla a los 30 s por defecto.
    proxyTimeout: 10 * 60 * 1000,
  },
  // El navegador solo habla con Next.js; /api/* se reenvia a FastAPI.
  // Evita CORS y mantiene la logica del agente fuera del frontend.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
};

export default nextConfig;
