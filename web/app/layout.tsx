import type { Metadata, Viewport } from "next";
import "./globals.css";
import NavBar from "@/components/NavBar";

export const metadata: Metadata = {
  title: "AniNova AR — Stream Anime",
  description:
    "AniNova web experience: browse, discover and stream anime in the signature Sunrise theme.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0D0D11",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen flex flex-col">
        <NavBar />
        <main className="flex-1">{children}</main>
        <footer className="border-t border-line/60 py-6 text-center text-xs text-ink-mute">
          AniNova AR · Sunrise Theme · Streams resolve via public provider
          instances — for personal use only.
        </footer>
      </body>
    </html>
  );
}
