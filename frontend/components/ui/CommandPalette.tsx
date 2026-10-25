"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import {
  BookMarked,
  Building2,
  CalendarClock,
  CalendarRange,
  Gauge,
  Link2,
  MailWarning,
  MessageSquareText,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { getExceptions, getLeases } from "@/lib/api";
import type { ExceptionSummary, LeaseSummary } from "@/lib/types";

const OPEN_EVENT = "leasedesk:command-palette";

/** Open the palette from a button (the top bar's search field). */
export function openCommandPalette() {
  window.dispatchEvent(new Event(OPEN_EVENT));
}

/**
 * ⌘K. It is cheap and it makes a demo feel like a tool rather than a slide —
 * jumping straight to Store 14 beats scrolling a queue while someone watches.
 */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  // Only fetched once the palette has been opened, so it costs nothing on load.
  const leases = useQuery({ queryKey: ["leases"], queryFn: getLeases, enabled: open });
  const exceptions = useQuery({ queryKey: ["exceptions"], queryFn: getExceptions, enabled: open });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    const onOpen = () => setOpen(true);
    document.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => {
      document.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_EVENT, onOpen);
    };
  }, []);

  const go = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command palette"
      // One panel: the input on top, the list directly under it. The content
      // (not the cmdk root) is what is positioned, so nothing stretches.
      className="flex flex-col"
      overlayClassName="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
      contentClassName="fixed left-1/2 top-[12vh] z-50 w-[min(36rem,92vw)] -translate-x-1/2 overflow-hidden rounded-md border border-line bg-surface shadow-float"
    >
      <Command.Input
        placeholder="Jump to a lease, an exception, or a screen…"
        className="w-full border-b border-line bg-transparent px-4 py-3.5 text-sm text-ink outline-none placeholder:text-ink-faint"
      />
      <Command.List className="max-h-80 overflow-y-auto p-2">
        <Command.Empty className="px-3 py-6 text-center text-sm text-ink-muted">
          Nothing matches that.
        </Command.Empty>

        <Group heading="Go to">
          <Item onSelect={() => go("/")} icon={<Gauge className="h-4 w-4" />}>Today</Item>
          <Item onSelect={() => go("/month")} icon={<CalendarRange className="h-4 w-4" />}>Month run</Item>
          <Item onSelect={() => go("/exceptions")} icon={<TriangleAlert className="h-4 w-4" />}>Exceptions</Item>
          <Item onSelect={() => go("/questions")} icon={<MessageSquareText className="h-4 w-4" />}>Questions</Item>
          <Item onSelect={() => go("/leases")} icon={<Building2 className="h-4 w-4" />}>Leases</Item>
          <Item onSelect={() => go("/obligations")} icon={<CalendarClock className="h-4 w-4" />}>Obligations</Item>
          <Item onSelect={() => go("/disputes")} icon={<MailWarning className="h-4 w-4" />}>Disputes</Item>
          <Item onSelect={() => go("/policies")} icon={<BookMarked className="h-4 w-4" />}>Policies</Item>
          <Item onSelect={() => go("/audit")} icon={<Link2 className="h-4 w-4" />}>Audit trail</Item>
          <Item onSelect={() => go("/welcome")} icon={<Sparkles className="h-4 w-4" />}>Welcome page</Item>
        </Group>

        {exceptions.data?.length ? (
          <Group heading="Open exceptions">
            {exceptions.data.slice(0, 8).map((e: ExceptionSummary) => (
              <Item key={e.exception_id} onSelect={() => go(`/exceptions/${e.exception_id}`)}>
                {e.clinic_id} · {e.charge_type?.replace(/_/g, " ")} · {e.period}
              </Item>
            ))}
          </Group>
        ) : null}

        {leases.data?.length ? (
          <Group heading="Leases">
            {leases.data.slice(0, 8).map((l: LeaseSummary) => (
              <Item key={l.lease_id} onSelect={() => go(`/leases/${l.lease_id}`)}>
                {l.lease_id} · {l.location ?? l.clinic_id}
              </Item>
            ))}
          </Group>
        ) : null}
      </Command.List>
    </Command.Dialog>
  );
}

function Group({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <Command.Group
      heading={heading}
      className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.1em] [&_[cmdk-group-heading]]:text-ink-faint"
    >
      {children}
    </Command.Group>
  );
}

function Item({
  children, onSelect, icon,
}: { children: React.ReactNode; onSelect: () => void; icon?: React.ReactNode }) {
  return (
    <Command.Item
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-2.5 rounded-xs px-3 py-2.5 text-sm text-ink-soft aria-selected:bg-raised aria-selected:text-ink"
    >
      {icon ? <span className="text-ink-faint">{icon}</span> : null}
      {children}
    </Command.Item>
  );
}
