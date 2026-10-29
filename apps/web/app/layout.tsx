import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Golden Goose — Audit Assistant",
  description:
    "Agentic retrieval over the quality management system for live regulatory audits",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
