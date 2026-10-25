"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { ThemeToggle } from "@/components/theme";

const NAV = [
  ["#story", "What it caught"],
  ["#how", "How it works"],
  ["#built", "Built with"],
] as const;

export function WelcomeHeader() {
  return (
    <header className="glass sticky top-0 z-30 border-b border-line">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between px-6">
        <Link href="/welcome" className="flex items-center gap-2.5">
          <span aria-hidden className="grid h-7 w-7 place-items-center rounded-sm bg-accent font-mono text-sm font-bold text-accent-ink">
            L
          </span>
          <span className="font-semibold tracking-tight">Lease Desk</span>
          <span className="ml-1 hidden font-mono text-2xs uppercase tracking-[0.1em] text-ink-faint sm:inline">Cal Hacks 13.0</span>
        </Link>
        <nav aria-label="On this page" className="flex items-center gap-1 sm:gap-2">
          {NAV.map(([href, label]) => (
            <a key={href} href={href} className="hidden rounded-sm px-3 py-1.5 text-sm text-ink-soft transition-colors hover:bg-raised hover:text-ink md:inline-block">
              {label}
            </a>
          ))}
          <ThemeToggle className="ml-1" />
          <Link
            href="/login"
            className="ml-1 inline-flex h-9 items-center gap-1.5 rounded-sm bg-accent px-3.5 text-sm font-medium text-accent-ink transition-colors hover:bg-accent-strong"
          >
            Open the desk <ArrowRight aria-hidden className="h-3.5 w-3.5" />
          </Link>
        </nav>
      </div>
    </header>
  );
}
