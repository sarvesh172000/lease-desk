"use client";

import { Button } from "@/components/ui/Button";
import { demoSwitch, login } from "@/lib/api";
import { humanize } from "@/lib/format";
import { useDataSource, useDemoActors } from "@/lib/hooks";
import type { Actor } from "@/lib/types";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const source = useDataSource();
  const demo = useDemoActors();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const next = params.get("next");
  const done = (actor: Actor) => {
    qc.setQueryData(["me"], actor);
    void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      done(await login(email, password));
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-[420px]">
        <div className="mb-6 flex items-center gap-2.5">
          <span aria-hidden className="flex h-8 w-8 items-center justify-center rounded bg-accent font-mono font-bold text-white">
            L
          </span>
          <div>
            <div className="text-lg font-semibold leading-tight">Lease Desk</div>
            <div className="text-sm text-ink-muted">Northbay Physical Therapy</div>
          </div>
        </div>
        <form onSubmit={submit} className="rounded-md border border-line bg-surface p-6 shadow-card">
          <h1 className="text-xl font-semibold">Sign in</h1>
          <label className="mt-5 block text-sm font-medium" htmlFor="email">
            Work email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            required
            className="mt-1 h-10 w-full rounded-md border border-line-strong px-3"
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
            className="mt-1 h-10 w-full rounded-md border border-line-strong px-3"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error ? (
            <p role="alert" className="mt-3 text-sm text-bad">
              {error.startsWith("401") ? "Email or password is incorrect." : error}
            </p>
          ) : null}
          <Button type="submit" variant="primary" size="lg" className="mt-5 w-full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
          {source === "fixtures" ? (
            <p className="mt-3 text-xs text-ink-muted">Fixtures mode: any password works; unknown emails sign in as the controller.</p>
          ) : null}
        </form>

        {demo.data?.length ? (
          <div className="mt-5 rounded-md border border-esc-line bg-esc-soft/50 p-4">
            <div className="eyebrow mb-2 text-esc">Demo mode · sign in as</div>
            <div className="grid grid-cols-2 gap-2">
              {demo.data.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  className="rounded-md border border-line bg-surface px-3 py-2 text-left hover:border-line-strong"
                  onClick={async () => {
                    try {
                      done(await demoSwitch(a.id));
                    } catch (ex) {
                      setError(ex instanceof Error ? ex.message : String(ex));
                    }
                  }}
                >
                  <div className="text-sm font-medium">{a.name}</div>
                  <div className="text-2xs text-ink-muted">{humanize(a.role)}</div>
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
