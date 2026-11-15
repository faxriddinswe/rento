import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = { title: "Rento — ijara va kommunal hisob-kitob", description: "Ijara, hisoblagich ko'rsatkichlari va to'lovlarni boshqarish" };
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="uz">
      <body><Providers>{children}</Providers></body>
    </html>
  );
}
