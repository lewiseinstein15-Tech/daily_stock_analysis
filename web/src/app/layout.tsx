import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

const display = localFont({
  src: "../../public/fonts/Fraunces-var.woff2",
  variable: "--font-display",
  weight: "100 900",
  display: "swap",
});

const ui = localFont({
  src: "../../public/fonts/Inter-var.woff2",
  variable: "--font-ui",
  weight: "100 900",
  display: "swap",
});

const data = localFont({
  src: "../../public/fonts/JetBrainsMono-var.woff2",
  variable: "--font-data",
  weight: "100 800",
  display: "swap",
});

export const metadata: Metadata = {
  title: "JEXI Market — the market, explained",
  description:
    "JEXI Market is a premium financial-intelligence terminal: live market command center, AI research pipeline, investment theses, and a trading engine that explains itself in plain English.",
};

export const viewport: Viewport = {
  themeColor: "#0C0B09",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${display.variable} ${ui.variable} ${data.variable}`}>
        {children}
      </body>
    </html>
  );
}
