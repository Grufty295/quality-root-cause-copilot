import type { Metadata } from "next";
import "./globals.css";

// Fuente del sistema: el build no depende de descargar fuentes de Google (falla sin red).
export const metadata: Metadata = {
  title: "Agente 8D · Causa raíz",
  description: "Borradores D2/D4 con evidencia citada y router de confidencialidad",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
