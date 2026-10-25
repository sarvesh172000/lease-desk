"use client";

import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { ApiError } from "@/lib/api";
import { timestamp } from "@/lib/format";
import { usePairingCode, usePairings, useRevokePairing } from "@/lib/hooks";
import * as Dialog from "@radix-ui/react-dialog";
import { Copy, Check, MessageCircle, X } from "lucide-react";
import { useEffect, useState } from "react";

/** mm:ss until the code expires, from the API's expires_at. */
function remaining(expiresAt: string, now: number): number {
  return Math.max(0, Math.floor((Date.parse(expiresAt) - now) / 1000));
}

/**
 * Pair an ASI:One chat with this desk: mint a one-time code, show it with
 * its countdown and the line to type, and list live pairings with revoke.
 */
export function ConnectChatDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const code = usePairingCode();
  const pairings = usePairings();
  const revoke = useRevokePairing();
  const [now, setNow] = useState(() => Date.now());
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!open || !code.data) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [open, code.data]);
  const left = code.data ? remaining(code.data.expires_at, now) : 0;
  const notLive = (e: unknown) => e instanceof ApiError && e.status === 501;
  const line = code.data ? `pair ${code.data.code}` : "";

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50 motion-safe:animate-in motion-safe:fade-in" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-md border border-line bg-surface shadow-float motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-95" data-testid="connect-chat">
          <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
            <div>
              <Dialog.Title className="flex items-center gap-2 text-lg font-semibold">
                <MessageCircle aria-hidden className="h-5 w-5 text-accent" /> Connect chat
              </Dialog.Title>
              <Dialog.Description className="text-sm text-ink-muted">Pair your ASI:One chat with Northbay Lease Desk. The code works once and for ten minutes.</Dialog.Description>
            </div>
            <Dialog.Close className="rounded-xs p-1 text-ink-muted hover:bg-raised hover:text-ink" aria-label="Close">
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>
          <div className="space-y-5 px-5 py-4">
            {code.data ? (
              <div className="rounded-md border border-accent/40 bg-accent-soft/60 p-4" data-testid="pairing-code">
                <div className="flex items-center justify-between gap-3">
                  <span className="num font-mono text-3xl font-semibold tracking-[0.2em] text-ink">{code.data.code}</span>
                  <span className={left > 0 ? "num text-sm font-semibold text-accent" : "text-sm font-semibold text-bad"} aria-live="polite" data-testid="pairing-countdown">
                    {left > 0 ? `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}` : "Expired"}
                  </span>
                </div>
                <p className="mt-3 text-sm text-ink-soft">
                  In ASI:One, open <strong className="text-ink">Northbay Lease Desk</strong> and type
                </p>
                <div className="mt-1 flex items-center gap-2">
                  <code className="flex-1 rounded-xs border border-line bg-surface px-2.5 py-1.5 font-mono text-sm text-ink">{line}</code>
                  <button
                    type="button"
                    aria-label={copied ? "Copied" : "Copy the pairing line"}
                    onClick={() => navigator.clipboard?.writeText(line).then(() => setCopied(true))}
                    className="flex h-8 w-8 items-center justify-center rounded-xs border border-line text-ink-muted hover:text-ink"
                  >
                    {copied ? <Check aria-hidden className="h-4 w-4 text-ok" /> : <Copy aria-hidden className="h-4 w-4" />}
                  </button>
                </div>
                {code.data.instructions ? <p className="mt-2 text-xs text-ink-muted">{code.data.instructions}</p> : null}
                {left === 0 ? (
                  <Button className="mt-3" variant="secondary" size="sm" loading={code.isPending} onClick={() => code.mutate()}>
                    New code
                  </Button>
                ) : null}
              </div>
            ) : (
              <div className="flex items-center justify-between gap-3 rounded-md border border-dashed border-line-strong p-4">
                <p className="text-sm text-ink-soft">Mint a one-time code, then type it to the desk in ASI:One.</p>
                <Button variant="primary" size="sm" loading={code.isPending} onClick={() => code.mutate()} data-testid="mint-code">
                  Get a code
                </Button>
              </div>
            )}
            {code.isError ? (
              <p role="alert" className="text-sm text-bad">
                {notLive(code.error) ? "Pairing needs the live API." : code.error.message}
              </p>
            ) : null}

            <div>
              <div className="eyebrow mb-2">Paired chats</div>
              {pairings.isLoading ? (
                <LoadingBlock rows={1} label="Loading pairings" />
              ) : pairings.isError ? (
                <ErrorState title="Pairings unavailable" error={pairings.error} onRetry={() => pairings.refetch()} />
              ) : !pairings.data?.pairings.length ? (
                <EmptyState title="No chat is paired yet.">A paired chat can ask the desk about its items and get answers from the audit trail.</EmptyState>
              ) : (
                <ul className="divide-y divide-line rounded-sm border border-line">
                  {pairings.data.pairings.map((p) => (
                    <li key={p.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                      <span className="min-w-0">
                        <span className="block truncate font-mono text-xs">{p.chat_user}</span>
                        <span className="text-xs text-ink-muted">
                          since {timestamp(p.claimed_at)} · until {timestamp(p.expires_at)}
                        </span>
                      </span>
                      <Button variant="danger" size="sm" loading={revoke.isPending && revoke.variables === p.id} onClick={() => revoke.mutate(p.id)}>
                        Revoke
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              {revoke.isError ? (
                <p role="alert" className="mt-2 text-xs text-bad">
                  {notLive(revoke.error) ? "Revoking needs the live API." : revoke.error.message}
                </p>
              ) : null}
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
