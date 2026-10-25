"use client";

import type { ReactNode } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";

/** A block that fades up once, the first time it is reached; a static frame for anyone who asked for less motion. */
export function Reveal({
  children, delay = 0, className,
}: { children: ReactNode; delay?: number; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.55, delay, ease: [0.2, 0.8, 0.2, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

export function Section({
  id, eyebrow, title, lead, children, className,
}: {
  id?: string;
  eyebrow?: string;
  title?: ReactNode;
  lead?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={cn("mx-auto w-full max-w-6xl scroll-mt-16 px-6 py-24 md:py-32", className)}>
      {eyebrow || title || lead ? (
        <Reveal className="mb-12 max-w-3xl">
          {eyebrow ? <div className="eyebrow mb-3 text-accent">{eyebrow}</div> : null}
          {title ? <h2 className="text-headline font-semibold">{title}</h2> : null}
          {lead ? <p className="mt-4 text-lg leading-relaxed text-ink-soft">{lead}</p> : null}
        </Reveal>
      ) : null}
      {children}
    </section>
  );
}

/** "live · as of …" or "measured … by make eval": where the figures beside it came from. */
export function SourceTag({ children, live, className }: { children: ReactNode; live?: boolean; className?: string }) {
  return (
    <span
      data-testid="source-tag"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-2xs",
        live ? "border-ok-line bg-ok-soft text-ok" : "border-line bg-raised text-ink-muted",
        className,
      )}
    >
      {live ? <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" /> : null}
      {children}
    </span>
  );
}

/** A link into the real screen a beat was describing. */
export function IntoTheDesk({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      className="group mt-8 inline-flex items-center gap-2 text-sm font-medium text-accent transition-colors hover:text-accent-strong"
    >
      {children}
      <span aria-hidden className="transition-transform duration-fast ease-out group-hover:translate-x-0.5">→</span>
    </a>
  );
}
