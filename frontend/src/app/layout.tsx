import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AppProvider } from "@/lib/store";

export const metadata: Metadata = {
  title: "mini OpenClaw",
  description: "Transparent local-first AI Agent workspace",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f3f5f9" },
    { media: "(prefers-color-scheme: dark)", color: "#060b14" },
  ],
};

const activeTheme = process.env.NEXT_PUBLIC_UI_THEME === "legacy" ? "legacy" : "claude";
const pixelTexture = process.env.NEXT_PUBLIC_UI_PIXEL_TEXTURE === "off" ? "off" : "on";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body data-theme={activeTheme} data-pixel-texture={pixelTexture}>
        <a className="skip-link" href="#main-content">
          Skip to main content
        </a>
        <AppProvider>{children}</AppProvider>
      </body>
    </html>
  );
}
