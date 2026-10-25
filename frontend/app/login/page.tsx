"use client";

import { ThemeToggle } from "@/components/theme";
import { Button } from "@/components/ui/Button";
import { demoSwitch, login } from "@/lib/api";
import { humanize } from "@/lib/format";
import { useDataSource, useDemoActors } from "@/lib/hooks";
import { isPerson, regionLabel } from "@/lib/labels";
import type { Actor } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

const ROLE_TONE: Record<string, string> = {
  controller: "bg-accent-soft text-accent border-accent/30",
  regional_manager: "bg-esc-soft text-esc border-esc-line",
  ap_clerk: "bg-ok-soft text-ok border-ok-line",
  auditor: "bg-warn-soft text-warn border-warn-line",
};

// the order the demo walks through them
const ROLE_ORDER: Record<string, number> = { controller: 0, regional_manager: 1, ap_clerk: 2, auditor: 3 };

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const source = useDataSource();
  const demo = useDemoActors();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // people only: the gateway and the agents act in the audit trail, nobody signs in as them
  const people = (demo.data ?? []).filter(isPerson).sort((a, b) => (ROLE_ORDER[a.role] ?? 9) - (ROLE_ORDER[b.role] ?? 9));
  const demoMode = people.length > 0;

  const next = params.get("next");
  const done = (actor: Actor) => {
    qc.setQueryData(["me"], actor);
    void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy("form");
    setError(null);
    try {
      done(await login(email, password));
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy(null);
    }
  };

  const become = async (a: Actor) => {
    setBusy(a.id);
    setError(null);
    try {
      done(await demoSwitch(a.id));
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1fr)_minmax(0,520px)]">
      {/* the story, in one breath, for whoever lands here first */}
      <aside className="relative hidden flex-col justify-between overflow-hidden border-r border-line bg-sunken/40 p-10 lg:flex">
        <div aria-hidden className="pointer-events-none absolute -left-40 top-1/3 h-[30rem] w-[40rem] rounded-full bg-accent/10 blur-[120px]" />
        <Link href="/welcome" className="relative flex items-center gap-2.5">
          <span aria-hidden className="grid h-8 w-8 place-items-center rounded-sm bg-accent font-mono font-bold text-accent-ink">
            L
          </span>
          <span className="text-lg font-semibold tracking-tight">Lease Desk</span>
        </Link>
        <div className="relative max-w-md">
          <p className="font-serif text-3xl leading-snug text-ink">
            Reads every lease. Checks every landlord bill. Holds only what is wrong, and waits for a person.
          </p>
          <ol className="mt-8 space-y-3 text-sm text-ink-soft">
            <li className="flex gap-3">
              <span className="font-mono text-2xs text-accent">01</span>
              The hidden amendment: an under-bill that led to a remeasured liability.
            </li>
            <li className="flex gap-3">
              <span className="font-mono text-2xs text-warn">02</span>
              January: a month of charges checked, the wrong ones held with the clause that proves it.
            </li>
            <li className="flex gap-3">
              <span className="font-mono text-2xs text-bad">03</span>
              Trust: the agent cannot post, a manager cannot approve their own answer, the chain verifies.
            </li>
          </ol>
          <Link href="/welcome" className="mt-8 inline-flex items-center gap-1.5 text-sm text-accent hover:text-accent-strong">
            <ArrowLeft aria-hidden className="h-3.5 w-3.5" /> Read the whole story
          </Link>
        </div>
        <p className="relative text-xs text-ink-faint">Cal Hacks 13.0 · Northbay Coffee, the demo company</p>
      </aside>

      <main className="relative flex items-center justify-center px-6 py-10">
        <ThemeToggle className="absolute right-6 top-6" />
        <div className="w-full max-w-[420px]">
          <div className="mb-6 flex items-center gap-2.5 lg:hidden">
            <span aria-hidden className="grid h-8 w-8 place-items-center rounded-sm bg-accent font-mono font-bold text-accent-ink">
              L
            </span>
            <div className="text-lg font-semibold leading-tight">Lease Desk</div>
          </div>

          <div className="flex items-end justify-between gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
            {demoMode ? (
              <span
                data-testid="demo-badge"
                className="inline-flex items-center gap-1.5 rounded-full border border-esc-line bg-esc-soft px-2.5 py-0.5 text-2xs font-semibold uppercase tracking-[0.08em] text-esc"
              >
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
                Demo mode
              </span>
            ) : null}
          </div>

          {demoMode ? (
            <section className="mt-5" aria-labelledby="personas">
              <h2 id="personas" className="eyebrow">
                Sign in as
              </h2>
              <ul className="mt-2 grid gap-2 sm:grid-cols-2" data-testid="personas">
                {people.map((a) => (
                  <li key={a.id}>
                    <button
                      type="button"
                      onClick={() => become(a)}
                      disabled={busy != null}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-md border border-line bg-surface p-3 text-left transition-colors duration-fast ease-out",
                        "hover:border-line-strong hover:bg-raised disabled:opacity-60",
                      )}
                    >
                      <span
                        aria-hidden
                        className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-full border text-xs font-semibold", ROLE_TONE[a.role] ?? "border-line bg-raised text-ink-soft")}
                      >
                        {initials(a.name)}
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">{busy === a.id ? "Signing in…" : a.name}</span>
                        <span className="block text-2xs leading-snug text-ink-muted">
                          {humanize(a.role)}
                          {a.region_id ? ` · ${regionLabel(a.region_id)}` : a.role === "auditor" ? " · external" : " · all regions"}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="my-6 flex items-center gap-3 text-2xs uppercase tracking-[0.1em] text-ink-faint">
                <span className="h-px flex-1 bg-line" />
                or with email
                <span className="h-px flex-1 bg-line" />
              </div>
            </section>
          ) : null}

          <form onSubmit={submit} className={cn("rounded-md border border-line bg-surface p-5 shadow-card", !demoMode && "mt-5")}>
            <label className="block text-sm font-medium" htmlFor="email">
              Work email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              required
              className="mt-1 h-10 w-full rounded-sm border border-line-strong bg-raised px-3 text-ink"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <label className="mt-4 block text-sm font-medium" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required={source === "api"}
              className="mt-1 h-10 w-full rounded-sm border border-line-strong bg-raised px-3 text-ink"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {error ? (
              <p role="alert" className="mt-3 text-sm text-bad">
                {error.startsWith("401") ? "Email or password is incorrect." : error}
              </p>
            ) : null}
            <Button type="submit" variant="primary" size="lg" className="mt-5 w-full" disabled={busy != null}>
              {busy === "form" ? "Signing in…" : "Sign in"}
            </Button>
            {source === "fixtures" ? (
              <p className="mt-3 text-xs text-ink-muted">Fixtures mode: any password works; unknown emails sign in as the controller.</p>
            ) : null}
          </form>
        </div>
      </main>
    </div>
  );
}
