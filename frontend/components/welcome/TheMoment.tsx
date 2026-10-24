"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, FileSearch, Quote, Scale } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";

/**
 * The four beats of the demo, as real figures from the system.
 *
 * Driven by clicking or hovering a step rather than by scroll position. A
 * scroll-pinned sequence looks impressive and takes the page away from the
 * reader — on a projector, in two minutes, a judge needs to be able to go
 * straight to the beat being talked about.
 */
type Figure = { label: string; value: string; tone?: "bad" | "ok" };
type Step = {
  key: string;
  icon: typeof AlertTriangle;
  tone: "bad" | "warn" | "accent" | "ok";
  label: string;
  headline: string;
  body: string;
  figures: Figure[];
};

const STEPS: Step[] = [
  {
    key: "break",
    icon: AlertTriangle,
    tone: "bad",
    label: "The break",
    headline: "July rent came in $2,226.65 short",
    body:
      "Three months running. The payment is not wrong — the landlord invoiced it " +
      "and AP paid it. The schedule in the books is wrong.",
    figures: [
      { label: "Schedule says", value: "$19,626.65" },
      { label: "Actually paid", value: "$17,400.00" },
      { label: "Variance", value: "−$2,226.65", tone: "bad" },
    ],
  },
  {
    key: "search",
    icon: FileSearch,
    tone: "warn",
    label: "The search",
    headline: "Ten documents read, one of them governs",
    body:
      "An executed amendment from the landlord's authorized representative. A " +
      "property manager claiming something different, a forged sender, and an " +
      "injection attempt are all set aside — none can modify a lease.",
    figures: [
      { label: "Documents searched", value: "10" },
      { label: "Source trusted", value: "Rank 1 — executed amendment" },
      { label: "Refused", value: "3 lower-ranked sources" },
    ],
  },
  {
    key: "proof",
    icon: Quote,
    tone: "accent",
    label: "The proof",
    headline: "The sentence it relied on, boxed on the page",
    body:
      "Every claim carries the quote it came from and a box on the page image. " +
      "A term the model cannot cite does not reach a schedule.",
    figures: [
      { label: "Quoted", value: "“Base rent reduced to $17,400 per month effective July 1, 2026.”" },
      { label: "From", value: "dana.reyes@serramonteretail.example, 18 June 2026" },
      { label: "Confidence", value: "100%" },
    ],
  },
  {
    key: "entries",
    icon: Scale,
    tone: "ok",
    label: "The entries",
    headline: "Remeasured under ASC 842, awaiting the controller",
    body:
      "The term extends three years and the rent falls, so the liability rises. " +
      "Debits equal credits. Nothing posts until a human signs off.",
    figures: [
      { label: "Lease liability", value: "$559,665.35 → $1,002,921.05" },
      { label: "ROU asset", value: "$538,771.19 → $982,026.89" },
      { label: "Balanced", value: "447,880.44 = 447,880.44", tone: "ok" },
    ],
  },
];

export function TheMoment() {
  const [active, setActive] = useState(0);
  const step = STEPS[active];

  return (
    <div className="grid gap-8 lg:grid-cols-[260px_1fr]">
      {/* The four steps, as a vertical rail with a connecting line. */}
      <ol className="relative flex gap-2 overflow-x-auto pb-2 lg:flex-col lg:overflow-visible lg:pb-0">
        <span
          aria-hidden
          className="absolute left-[19px] top-6 hidden h-[calc(100%-3rem)] w-px bg-line lg:block"
        />
        {STEPS.map((s, i) => {
          const Icon = s.icon;
          const on = i === active;
          return (
            <li key={s.key} className="relative shrink-0">
              <button
                type="button"
                onClick={() => setActive(i)}
                onMouseEnter={() => setActive(i)}
                aria-current={on || undefined}
                className={cn(
                  "group flex w-full items-center gap-3 rounded-sm px-2 py-3 text-left",
                  "transition-colors duration-fast ease-out",
                  on ? "text-ink" : "text-ink-muted hover:text-ink-soft",
                )}
              >
                <span
                  className={cn(
                    "relative z-10 grid h-10 w-10 shrink-0 place-items-center rounded-full border",
                    "transition-all duration-base ease-out",
                    on
                      ? "border-accent bg-accent-soft text-accent shadow-glow"
                      : "border-line bg-surface text-ink-faint group-hover:border-line-strong",
                  )}
                >
                  <Icon className="h-4 w-4" aria-hidden />
                </span>
                <span className="min-w-0">
                  <span className="block text-2xs font-semibold uppercase tracking-[0.1em] text-ink-faint">
                    Step {i + 1}
                  </span>
                  <span className="block truncate text-sm font-medium">{s.label}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      {/* The panel. Height is not animated, so nothing below it jumps. */}
      <div className="min-h-[22rem] rounded-md border border-line bg-surface p-6 md:p-8">
        <AnimatePresence mode="wait">
          <motion.div
            key={step.key}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}
          >
            <Badge tone={step.tone} dot>{step.label}</Badge>
            <h3 className="mt-4 text-2xl font-semibold tracking-tight md:text-3xl">
              {step.headline}
            </h3>
            <p className="mt-3 max-w-2xl leading-relaxed text-ink-soft">{step.body}</p>

            <dl className="mt-7 space-y-3 border-t border-line pt-6">
              {step.figures.map((f) => (
                <div key={f.label} className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-6">
                  <dt className="w-44 shrink-0 text-2xs font-semibold uppercase tracking-[0.1em] text-ink-faint">
                    {f.label}
                  </dt>
                  <dd
                    className={cn(
                      "num text-sm leading-relaxed",
                      f.tone === "bad" && "text-bad",
                      f.tone === "ok" && "text-ok",
                      !f.tone && "text-ink",
                    )}
                  >
                    {f.value}
                  </dd>
                </div>
              ))}
            </dl>
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
