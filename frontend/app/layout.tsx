import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { Toaster } from "sonner";
import { AppShell } from "@/components/AppShell";
import { TooltipProvider } from "@/components/ui/Tooltip";
import { sans, mono } from "./fonts";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lease Desk — the lease accountant's seat",
  description:
    "Reads every lease, checks every landlord bill against it, and holds only the money that is wrong.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0a0b0d" },
    { media: "(prefers-color-scheme: light)", color: "#f6f5f1" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" data-theme="dark" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <Providers>
          <TooltipProvider>
            <AppShell>{children}</AppShell>
            <Toaster
              theme="dark"
              position="bottom-right"
              toastOptions={{
                className:
                  "!bg-raised !border !border-line !text-ink !rounded-sm !shadow-float",
              }}
            />
          </TooltipProvider>
        </Providers>
      </body>
    </html>
  );
}
