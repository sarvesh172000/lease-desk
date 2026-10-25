"use client";

import { Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";
import { Toaster } from "sonner";
import { cn } from "@/lib/utils";
import { THEME_KEY as KEY } from "./themeScript";

/**
 * Dark by default; light on request, remembered per browser. The theme is one
 * attribute on <html>, so every token in globals.css follows it.
 */
export type Theme = "dark" | "light";

function read(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function subscribe(fn: () => void): () => void {
  const obs = new MutationObserver(fn);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => obs.disconnect();
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const theme = useSyncExternalStore(subscribe, read, () => "light" as Theme);
  const set = (t: Theme) => {
    document.documentElement.dataset.theme = t;
    try {
      localStorage.setItem(KEY, t);
    } catch {
      /* private window: the choice lasts this page only */
    }
  };
  return [theme, set];
}

export function ThemeToggle({ className }: { className?: string }) {
  const [theme, setTheme] = useTheme();
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      onClick={() => setTheme(next)}
      className={cn(
        "flex h-9 w-9 items-center justify-center rounded-sm border border-line text-ink-soft transition-colors duration-fast ease-out hover:border-line-strong hover:bg-raised hover:text-ink active:scale-95",
        className,
      )}
    >
      {theme === "dark" ? <Moon aria-hidden className="h-4 w-4" /> : <Sun aria-hidden className="h-4 w-4" />}
    </button>
  );
}

/** Toasts in the current theme. */
export function ThemedToaster() {
  const [theme] = useTheme();
  return (
    <Toaster
      theme={theme}
      position="bottom-right"
      toastOptions={{ className: "!bg-raised !border !border-line !text-ink !rounded-sm !shadow-float" }}
    />
  );
}
