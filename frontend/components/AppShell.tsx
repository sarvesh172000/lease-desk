"use client";

import { demoSwitch, logout } from "@/lib/api";
import { humanize, period } from "@/lib/format";
import { useApiHealth, useDataSource, useDemoActors, useExceptions, useMe, useSummary } from "@/lib/hooks";
import { useLiveConnection, type LiveState } from "@/lib/live";
import { isPerson } from "@/lib/labels";
import type { Actor } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { CommandPalette, openCommandPalette } from "@/components/ui/CommandPalette";
import { ConnectChatDialog } from "@/components/shell/ConnectChat";
import { DemoResetDialog } from "@/components/shell/DemoReset";
import { ThemeToggle } from "@/components/theme";
import { Tooltip } from "@/components/ui/Tooltip";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { motion, useReducedMotion } from "framer-motion";
import {
  BookMarked,
  Building2,
  CalendarClock,
  CalendarRange,
  Check,
  ChevronDown,
  Gauge,
  Link2,
  LogOut,
  MailWarning,
  MessageCircle,
  MessageSquareText,
  RefreshCw,
  RotateCcw,
  Search,
  TriangleAlert,
  WifiOff,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

const EASE = [0.2, 0.8, 0.2, 1] as const;

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  match: (p: string) => boolean;
  /** Shows the number of open exceptions next to the label. */
  count?: "exceptions";
}

/** Grouped the way the seat works: today's decisions, the portfolio, and the proof. */
const NAV: { title: string; items: NavItem[] }[] = [
  {
    title: "Work",
    items: [
      { href: "/", label: "Today", icon: Gauge, match: (p) => p === "/" },
      { href: "/month", label: "Month run", icon: CalendarRange, match: (p) => p.startsWith("/month") },
      { href: "/exceptions", label: "Exceptions", icon: TriangleAlert, match: (p) => p.startsWith("/exceptions"), count: "exceptions" },
      { href: "/questions", label: "Questions", icon: MessageSquareText, match: (p) => p.startsWith("/questions") },
    ],
  },
  {
    title: "Portfolio",
    items: [
      { href: "/leases", label: "Leases", icon: Building2, match: (p) => p.startsWith("/leases") },
      { href: "/obligations", label: "Obligations", icon: CalendarClock, match: (p) => p.startsWith("/obligations") },
      { href: "/disputes", label: "Disputes", icon: MailWarning, match: (p) => p.startsWith("/disputes") },
      { href: "/policies", label: "Policies", icon: BookMarked, match: (p) => p.startsWith("/policies") },
    ],
  },
  {
    title: "Trust",
    items: [{ href: "/audit", label: "Audit trail", icon: Link2, match: (p) => p.startsWith("/audit") }],
  },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const me = useMe();
  const reduce = useReducedMotion();
  // Public routes: no app chrome, and no redirect to sign in. The welcome page
  // is the first thing a stranger sees, so it must render without a session.
  const isPublic = pathname.startsWith("/login") || pathname.startsWith("/welcome");

  useEffect(() => {
    if (!isPublic && me.isSuccess && me.data === null) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [isPublic, me.isSuccess, me.data, pathname, router]);

  if (isPublic) return <>{children}</>;

  return (
    <div className="flex min-h-screen">
      <CommandPalette />
      <Rail pathname={pathname} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <UnreachableBanner />
        <main className="w-full max-w-[1400px] flex-1 px-6 pb-16 pt-6">
          {me.isLoading ? (
            <div className="py-24 text-center text-ink-muted">Checking your session…</div>
          ) : me.isError ? (
            <div role="alert" className="mx-auto mt-16 max-w-lg rounded-md border border-bad-line bg-bad-soft px-5 py-4">
              <p className="font-semibold text-bad">Could not check your session</p>
              <p className="mt-1 font-mono text-sm text-ink-soft">{(me.error as Error).message}</p>
            </div>
          ) : me.data ? (
            // A short rise on every route change; reduced motion gets none.
            <motion.div
              key={pathname}
              initial={reduce ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, ease: EASE }}
            >
              {children}
            </motion.div>
          ) : null}
        </main>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Left rail
// ---------------------------------------------------------------------------

/** The money screen needs the width for two documents side by side, so the rail folds to icons there. */
const isCompact = (p: string) => /^\/exceptions\/[^/]+/.test(p);

function Rail({ pathname }: { pathname: string }) {
  const exceptions = useExceptions();
  const open = exceptions.data?.filter((e) => e.status !== "balanced").length ?? 0;
  const compact = isCompact(pathname);
  return (
    <aside
      className={cn(
        "sticky top-0 flex h-screen shrink-0 flex-col gap-5 border-r border-line bg-rail py-4 transition-[width] duration-base ease-out",
        compact ? "w-16 px-2" : "w-56 px-3",
      )}
      data-compact={compact ? "true" : "false"}
    >
      <Link href="/" aria-label="Lease Desk, Today" className={cn("flex items-center gap-2.5 rounded-sm py-1", compact ? "justify-center px-0" : "px-2")}>
        <span aria-hidden className="flex h-7 w-7 items-center justify-center rounded-xs bg-accent font-mono text-sm font-bold text-accent-ink">
          L
        </span>
        <span className={cn("flex flex-col leading-tight", compact && "sr-only")}>
          <span className="text-[0.95rem] font-semibold tracking-tight text-ink">Lease Desk</span>
          <span className="text-2xs text-ink-muted">Northbay Physical Therapy</span>
        </span>
      </Link>

      <nav aria-label="Main" className="flex flex-col gap-5">
        {NAV.map((group) => (
          <div key={group.title} className="flex flex-col gap-0.5">
            <span className={cn("eyebrow px-2.5 pb-1.5", compact && "sr-only")}>{group.title}</span>
            {group.items.map((item) => {
              const active = item.match(pathname);
              const Icon = item.icon;
              const link = (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "group relative flex h-9 items-center gap-2.5 rounded-sm text-sm transition-colors duration-fast ease-out",
                    compact ? "justify-center px-0" : "px-2.5",
                    active ? "font-medium text-accent" : "text-ink-soft hover:bg-raised hover:text-ink",
                  )}
                >
                  {active ? (
                    <motion.span
                      layoutId="rail-active"
                      aria-hidden
                      className="absolute inset-0 rounded-sm bg-accent/10 shadow-[inset_2px_0_0_rgb(var(--accent))]"
                      transition={{ duration: 0.2, ease: EASE }}
                    />
                  ) : null}
                  <Icon aria-hidden className="relative h-4 w-4 shrink-0 transition-transform duration-fast ease-out group-hover:scale-110" strokeWidth={1.75} />
                  <span className={cn("relative flex-1", compact && "sr-only")}>{item.label}</span>
                  {item.count === "exceptions" && open > 0 ? (
                    <span
                      className={cn(
                        "num rounded-xs bg-warn-soft font-semibold text-warn",
                        compact ? "absolute -right-0.5 -top-0.5 px-1 text-2xs" : "relative px-1.5 text-xs",
                      )}
                      aria-label={`${open} open`}
                    >
                      {open}
                    </span>
                  ) : null}
                </Link>
              );
              return compact ? (
                <Tooltip key={item.href} label={item.label} side="right">
                  {link}
                </Tooltip>
              ) : (
                link
              );
            })}
          </div>
        ))}
      </nav>

      <div className={cn("mt-auto flex flex-col gap-2 rounded-sm border border-line", compact ? "items-center p-1.5" : "p-2.5")}>
        <LiveIndicator compact={compact} />
        <DataSourceBadge compact={compact} />
      </div>
    </aside>
  );
}

const LIVE: Record<LiveState, { label: string; title: string; dot: string; pulse?: boolean }> = {
  connected: { label: "Live", title: "Live updates on: changes appear as they are committed", dot: "bg-ok", pulse: true },
  connecting: { label: "Connecting", title: "Connecting to live updates", dot: "bg-warn", pulse: true },
  reconnecting: { label: "Reconnecting", title: "Live updates dropped; reconnecting. Screens refresh as usual meanwhile", dot: "bg-warn", pulse: true },
  lost: { label: "Live unavailable", title: "Could not reach live updates; screens refresh as usual", dot: "bg-ink-muted" },
  off: { label: "Live off", title: "Live updates are not configured here. Screens refresh as usual; nothing is wrong.", dot: "bg-ink-muted" },
};

/**
 * The SpacetimeDB mirror's connection. Off is the normal state when the
 * mirror is not configured: a neutral grey dot, explained on hover.
 */
function LiveIndicator({ compact }: { compact?: boolean }) {
  const state = useLiveConnection();
  const l = LIVE[state];
  return (
    <Tooltip label={l.title} side="right">
      <span
        tabIndex={0}
        className="flex w-fit items-center gap-2 rounded-xs text-xs text-ink-muted"
        data-testid="live-indicator"
        data-state={state}
      >
        <span aria-hidden className={cn("h-2 w-2 shrink-0 rounded-full", l.dot, l.pulse && "animate-pulse-dot")} />
        <span className={cn(compact && "sr-only")}>{l.label}</span>
        <span className="sr-only">: {l.title}</span>
      </span>
    </Tooltip>
  );
}

/** Where the figures come from. Fixtures only ever by choice (NEXT_PUBLIC_USE_FIXTURES=1). */
function DataSourceBadge({ compact }: { compact?: boolean }) {
  const source = useDataSource();
  const health = useApiHealth();
  if (compact) {
    const s = source === "fixtures" ? "fixtures" : health.reachable ? "api" : "api-unreachable";
    const text = s === "fixtures" ? "Offline demo: fixtures, not a live API" : s === "api" ? "Live API" : "API unreachable";
    return (
      <Tooltip label={text} side="right">
        <span
          tabIndex={0}
          data-testid="data-source"
          data-source={s}
          aria-label={text}
          className={cn(
            "rounded-xs border px-1 py-0.5 font-mono text-2xs font-semibold uppercase",
            s === "fixtures" ? "border-warn-line bg-warn-soft text-warn" : s === "api" ? "border-ok-line bg-ok-soft text-ok" : "border-bad-line bg-bad-soft text-bad",
          )}
        >
          {s === "fixtures" ? "FX" : "API"}
        </span>
      </Tooltip>
    );
  }
  if (source === "api" && !health.reachable)
    return (
      <span
        className="rounded-xs border border-bad-line bg-bad-soft px-2 py-1 font-mono text-2xs font-medium uppercase tracking-wide text-bad"
        title={health.error}
        data-testid="data-source"
        data-source="api-unreachable"
      >
        API unreachable
      </span>
    );
  return source === "fixtures" ? (
    <span
      className="rounded-xs border border-warn-line bg-warn-soft px-2 py-1 font-mono text-2xs font-medium uppercase tracking-wide text-warn"
      title="Offline demo: figures come from the frozen fixtures, not a live API"
      data-testid="data-source"
      data-source="fixtures"
    >
      Offline · fixtures
    </span>
  ) : (
    <span
      className="rounded-xs border border-ok-line bg-ok-soft px-2 py-1 font-mono text-2xs font-medium uppercase tracking-wide text-ok"
      title="Figures come from the live API"
      data-testid="data-source"
      data-source="api"
    >
      Live API
    </span>
  );
}

// ---------------------------------------------------------------------------
// Top bar
// ---------------------------------------------------------------------------

function TopBar() {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/90 backdrop-blur">
      <div className="flex h-14 max-w-[1400px] items-center gap-3 px-6">
        <ContextPicker />
        <button
          type="button"
          onClick={openCommandPalette}
          className="flex h-9 w-full max-w-sm items-center gap-2 rounded-sm border border-line bg-surface px-3 text-left text-sm text-ink-muted transition-colors duration-fast ease-out hover:border-line-strong hover:text-ink-soft"
        >
          <Search aria-hidden className="h-4 w-4" />
          <span className="flex-1">Jump to a lease, exception, screen…</span>
          <kbd className="rounded-xs border border-line px-1.5 font-mono text-2xs">⌘K</kbd>
        </button>
        <div className="ml-auto flex items-center gap-2.5">
          <ThemeToggle />
          <RoleSwitcher />
        </div>
      </div>
    </header>
  );
}

const MENU =
  "z-50 min-w-64 rounded-md border border-line bg-surface p-1 shadow-float motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-95";
const MENU_LABEL = "eyebrow px-2.5 pb-1 pt-2";
const MENU_ITEM =
  "flex cursor-pointer items-center gap-2.5 rounded-xs px-2.5 py-2 text-sm text-ink outline-none data-[disabled]:cursor-default data-[highlighted]:bg-raised";

/**
 * The entity and the period every figure is for. The period is the API's own
 * business clock (summary.as_of), not today's date.
 */
function ContextPicker() {
  const summary = useSummary();
  const asOf = summary.data?.as_of;
  const label = asOf ? period(asOf) : summary.isLoading ? "…" : "—";
  return (
    <Menu.Root>
      <Menu.Trigger asChild>
        <button
          type="button"
          aria-label={`Entity Northbay Physical Therapy, period ${label}`}
          className="flex h-9 shrink-0 items-center gap-2 rounded-sm border border-line bg-surface px-3 text-sm text-ink transition-colors duration-fast ease-out hover:border-line-strong data-[state=open]:border-line-strong"
        >
          <span>Northbay PT</span>
          <span aria-hidden className="text-ink-faint">/</span>
          <span className="num font-semibold">{label}</span>
          <ChevronDown aria-hidden className="h-3.5 w-3.5 text-ink-muted" />
        </button>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content align="start" sideOffset={6} className={MENU}>
          <Menu.Label className={MENU_LABEL}>Entity</Menu.Label>
          <Menu.Item className={MENU_ITEM} disabled>
            <Check aria-hidden className="h-4 w-4 text-accent" />
            Northbay Physical Therapy
          </Menu.Item>
          <Menu.Separator className="my-1 h-px bg-line" />
          <Menu.Label className={MENU_LABEL}>Period</Menu.Label>
          <Menu.Item className={MENU_ITEM} disabled>
            <Check aria-hidden className="h-4 w-4 text-accent" />
            <span className="num">{asOf ? period(asOf) : "None run yet"}</span>
          </Menu.Item>
          <p className="max-w-64 px-2.5 pb-2 pt-1 text-xs text-ink-muted">
            The period follows the business clock. Other months appear here once they are run.
          </p>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");

const ROLE_TONE: Record<string, string> = {
  controller: "bg-accent-soft text-accent",
  regional_manager: "bg-esc-soft text-esc",
  ap_clerk: "bg-warn-soft text-warn",
  auditor: "bg-ok-soft text-ok",
};

function Avatar({ actor, className }: { actor: Actor; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ring-2 ring-surface",
        ROLE_TONE[actor.role] ?? "bg-sunken text-ink-soft",
        className,
      )}
    >
      {initials(actor.name)}
    </span>
  );
}

const roleLine = (a: Actor) => `${humanize(a.role)}${a.region_id ? ` · ${a.region_id}` : ""}`;

/** Who you are, and in demo mode who you can become. Agents never appear here. */
function RoleSwitcher() {
  const actors = useDemoActors();
  const me = useMe();
  const qc = useQueryClient();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  if (!me.data) return null;
  const current = me.data;
  const people = (actors.data ?? []).filter(isPerson);
  const demo = people.length > 0;
  const canReset = demo && current.role === "controller";

  const become = async (id: string) => {
    if (id === current.id) return;
    setBusy(true);
    setErr(null);
    try {
      const actor = await demoSwitch(id);
      qc.setQueryData(["me"], actor);
      await qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" && q.queryKey[0] !== "demo-actors" });
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    await logout().catch(() => undefined);
    qc.setQueryData(["me"], null);
    router.replace("/login");
  };

  return (
    <Menu.Root>
      <Menu.Trigger asChild>
        <button
          type="button"
          aria-label={`Signed in as ${current.name}, ${roleLine(current)}${demo ? ". Switch person (demo)" : ""}`}
          className={cn(
            "flex h-10 items-center gap-2.5 rounded-full border border-line bg-surface py-1 pl-1 pr-3 transition-colors duration-fast ease-out hover:border-line-strong data-[state=open]:border-line-strong",
            busy && "opacity-60",
          )}
        >
          <Avatar actor={current} />
          <span className="flex flex-col items-start leading-tight">
            <span className="text-sm font-semibold text-ink">{current.name}</span>
            <span className="text-2xs text-ink-muted">
              {roleLine(current)}
              {demo ? " · demo" : ""}
            </span>
          </span>
          <ChevronDown aria-hidden className="h-3.5 w-3.5 text-ink-muted" />
        </button>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content align="end" sideOffset={6} className={MENU}>
          {demo ? (
            <>
              <Menu.Label className={MENU_LABEL}>Act as (demo)</Menu.Label>
              {people.map((a) => (
                <Menu.Item key={a.id} className={MENU_ITEM} disabled={busy} onSelect={() => void become(a.id)}>
                  <Avatar actor={a} className="ring-0" />
                  <span className="flex flex-1 flex-col leading-tight">
                    <span className="font-medium">{a.name}</span>
                    <span className="text-xs text-ink-muted">{roleLine(a)}</span>
                  </span>
                  {a.id === current.id ? <Check aria-label="Current" className="h-4 w-4 text-accent" /> : null}
                </Menu.Item>
              ))}
              {err ? (
                <p role="alert" className="max-w-64 px-2.5 py-1.5 text-xs text-bad">
                  {err}
                </p>
              ) : null}
              <Menu.Separator className="my-1 h-px bg-line" />
            </>
          ) : null}
          <Menu.Item className={MENU_ITEM} onSelect={() => setChatOpen(true)} data-testid="menu-connect-chat">
            <MessageCircle aria-hidden className="h-4 w-4 text-ink-muted" />
            Connect chat
          </Menu.Item>
          {canReset ? (
            <Menu.Item className={MENU_ITEM} onSelect={() => setResetOpen(true)} data-testid="menu-demo-reset">
              <RotateCcw aria-hidden className="h-4 w-4 text-esc" />
              Reset demo
            </Menu.Item>
          ) : null}
          <Menu.Separator className="my-1 h-px bg-line" />
          <Menu.Item className={MENU_ITEM} onSelect={() => void signOut()}>
            <LogOut aria-hidden className="h-4 w-4 text-ink-muted" />
            Sign out
          </Menu.Item>
        </Menu.Content>
      </Menu.Portal>
      <ConnectChatDialog open={chatOpen} onOpenChange={setChatOpen} />
      {canReset ? <DemoResetDialog open={resetOpen} onOpenChange={setResetOpen} /> : null}
    </Menu.Root>
  );
}

/**
 * The live API could not be reached. Full width and impossible to miss: the
 * screens below show errors, never fixture numbers in place of real ones.
 */
function UnreachableBanner() {
  const health = useApiHealth();
  const qc = useQueryClient();
  const fetching = useIsFetching() > 0;
  if (health.reachable) return null;
  return (
    <div role="alert" className="border-b border-bad-line bg-bad-soft">
      <div className="flex max-w-[1400px] items-center gap-4 px-6 py-3">
        <WifiOff aria-hidden className="h-5 w-5 shrink-0 text-bad" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-bad">API unreachable. No figures on this page are current.</p>
          <p className="truncate font-mono text-xs text-ink-soft" title={health.error}>
            {health.error}
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          loading={fetching}
          icon={<RefreshCw aria-hidden className="h-3.5 w-3.5" />}
          onClick={() => void qc.invalidateQueries()}
        >
          Retry
        </Button>
      </div>
    </div>
  );
}
