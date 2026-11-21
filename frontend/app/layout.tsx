import type { Metadata, Viewport } from "next";
import { Header } from "@/components/Header";
import { MobileNav } from "@/components/Nav";
import { Ticker } from "@/components/Ticker";
import { themeScript } from "@/components/ThemeToggle";
import "./globals.css";

export const metadata: Metadata = {
  title: "WaxMatch",
  description: "Ta bibliothèque Spotify associée aux meilleures offres de vinyles d'occasion.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#EFEDE8" },
    { media: "(prefers-color-scheme: dark)", color: "#0B1017" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@700;800;900&family=Manrope:wght@500;600;700;800&family=Unbounded:wght@700;800&display=swap"
        />
      </head>
      <body>
        <Ticker />
        <div className="shell">
          <Header />
          <main>{children}</main>
        </div>
        <MobileNav />
      </body>
    </html>
  );
}
