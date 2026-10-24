"use client";

import { demoSwitch, logout } from "@/lib/api";
import { humanize } from "@/lib/format";
import { useApiHealth, useDataSource, useDemoActors, useMe } from "@/lib/hooks";
import { useLiveConnection, type LiveState } from "@/lib/live";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { CommandPalette } from "@/components/ui/CommandPalette";
import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, WifiOff } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

const NAV = [
  { href: "/", label: "Dashboard", match: (p: string) => p === "/" || p.startsWith("/exceptions") },
  { href: "/leases", label: "Leases", match: (p: string) => p.startsWith("/leases") },
  { href: "/audit", label: "Audit trail", match: (p: string) => p.startsWith("/audit") },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const me = useMe();
  // Public routes: no app chrome, and no redirect to sign in. The welcome page
  // is the first thing a stranger sees, so it must render without a session.
  const isPublic = pathname.startsWith("/login") || pathname.startsWith("/welcome");

  useEffect(() => {
    if (!isPublic && me.isSuccess && me.data === null) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [isPublic, me.isSuccess, me.data, pathname, router]);

  if (isPublic) return <>{children}</>;

  return (
    <div className="min-h-screen">
      <CommandPalette />
      <Header pathname={pathname} />
      <UnreachableBanner />
      <main className="mx-auto w-full max-w-[1400px] px-6 pb-16 pt-6">
        {me.isLoading ? (
          <div className="py-24 text-center text-ink-muted">Checking your session…</div>
        ) : me.isError ? (
          <div role="alert" className="mx-auto mt-16 max-w-lg rounded-md border border-bad-line bg-bad-soft px-5 py-4">
            <p className="font-semibold text-bad">Could not check your session</p>
            <p className="mt-1 font-mono text-sm text-ink-soft">{(me.error as Error).message}</p>
          </div>
        ) : me.data ? (
          children
        ) : null}
      </main>
    </div>
  );
}

function Header({ pathname }: { pathname: string }) {
  const me = useMe();
  const source = useDataSource();
  const router = useRouter();
  const qc = useQueryClient();

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-[1400px] items-center gap-8 px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <span aria-hidden className="flex h-7 w-7 items-center justify-center rounded bg-accent font-mono text-sm font-bold text-white">
            L
          </span>
          <span className="text-[1.05rem] font-semibold tracking-tight">Lease Desk</span>
          <span className="hidden text-sm text-ink-muted xl:inline">Northbay Physical Therapy</span>
        </Link>
        <nav className="flex items-center gap-1" aria-label="Main">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={cn(
                "rounded px-3 py-1.5 text-sm font-medium transition-colors",
                n.match(pathname) ? "bg-accent-soft text-accent" : "text-ink-soft hover:bg-sunken hover:text-ink",
              )}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {source === "fixtures" ? (
            <span
              className="rounded border border-warn-line bg-warn-soft px-2 py-0.5 text-2xs font-semibold uppercase tracking-wide text-warn"
              title="Data comes from the frozen DESIGN.md §16 fixtures, not a live API"
            >
              Fixtures
            </span>
          ) : null}
          <LiveIndicator />
          <RoleSwitcher />
          {me.data ? (
            <div className="flex items-center gap-3 border-l border-line pl-3">
              <div className="text-right leading-tight">
                <div className="text-sm font-medium">{me.data.name}</div>
                <div className="text-2xs text-ink-muted">
                  {humanize(me.data.role)}
                  {me.data.region_id ? ` · ${me.data.region_id}` : ""}
                </div>
              </div>
              <button
                type="button"
                className="rounded px-2 py-1 text-xs text-ink-muted hover:bg-sunken hover:text-ink"
                onClick={async () => {
                  await logout().catch(() => undefined);
                  qc.setQueryData(["me"], null);
                  router.replace("/login");
                }}
              >
                Sign out
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}

/** Demo-only: renders nothing unless /api/auth/demo-actors returns actors. */
function RoleSwitcher() {
  const actors = useDemoActors();
  const me = useMe();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!actors.data?.length || !me.data) return null;

  return (
    <label className="flex items-center gap-2 text-xs text-ink-muted">
      <span className="rounded bg-esc-soft px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide text-esc">Demo</span>
      <span className="sr-only">Act as</span>
      <select
        aria-label="Act as (demo)"
        className="h-8 rounded border border-line-strong bg-surface px-2 text-sm text-ink"
        value={me.data.id}
        disabled={busy}
        onChange={async (e) => {
          setBusy(true);
          setErr(null);
          try {
            const actor = await demoSwitch(e.target.value);
            qc.setQueryData(["me"], actor);
            await qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" && q.queryKey[0] !== "demo-actors" });
          } catch (ex) {
            setErr(ex instanceof Error ? ex.message : String(ex));
          } finally {
            setBusy(false);
          }
        }}
      >
        {actors.data.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name} — {humanize(a.role)}
          </option>
        ))}
      </select>
      {err ? <span className="text-bad" role="alert">{err}</span> : null}
    </label>
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
      <div className="mx-auto flex w-full max-w-[1400px] items-center gap-4 px-6 py-3">
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

const LIVE: Record<LiveState, { label: string; title: string; dot: string; pulse?: boolean }> = {
  connected: { label: "Live", title: "Live updates on: changes appear as they are committed", dot: "bg-ok", pulse: true },
  connecting: { label: "Connecting", title: "Connecting to live updates", dot: "bg-warn", pulse: true },
  reconnecting: { label: "Reconnecting", title: "Live updates dropped; reconnecting. Screens refresh as usual meanwhile", dot: "bg-warn", pulse: true },
  lost: { label: "Live unavailable", title: "Could not reach live updates; screens refresh as usual", dot: "bg-ink-faint" },
  off: { label: "Live off", title: "Live updates are not configured for this deployment; screens refresh as usual", dot: "bg-ink-faint" },
};

/** The SpacetimeDB mirror's connection. Off is a normal state, shown quietly. */
function LiveIndicator() {
  const state = useLiveConnection();
  const l = LIVE[state];
  return (
    <span
      className="flex items-center gap-1.5 text-xs text-ink-muted"
      title={l.title}
      data-testid="live-indicator"
      data-state={state}
    >
      <span aria-hidden className={cn("h-2 w-2 rounded-full", l.dot, l.pulse && "animate-pulse-dot")} />
      <span>{l.label}</span>
      <span className="sr-only">: {l.title}</span>
    </span>
  );
}
