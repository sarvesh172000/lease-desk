"use client";

import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

/** A section that fades up once, the first time it is reached. */
export function Reveal({
  children, delay = 0, className,
}: { children: ReactNode; delay?: number; className?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
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
    <section id={id} className={cn("mx-auto w-full max-w-6xl px-6 py-24 md:py-32", className)}>
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
