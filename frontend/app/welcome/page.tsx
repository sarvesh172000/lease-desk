import type { Metadata } from "next";
import { BeatAmendment } from "@/components/welcome/BeatAmendment";
import { BeatJanuary } from "@/components/welcome/BeatJanuary";
import { BeatTrust } from "@/components/welcome/BeatTrust";
import { Closing } from "@/components/welcome/Closing";
import { Hero } from "@/components/welcome/Hero";
import { HowItWorks } from "@/components/welcome/HowItWorks";
import { TechStrip } from "@/components/welcome/TechStrip";
import { WelcomeHeader } from "@/components/welcome/WelcomeHeader";

export const metadata: Metadata = {
  title: "Lease Desk — the lease accountant's seat",
  description:
    "Reads every lease, checks every landlord bill against it, and holds only the money that is wrong. A person approves; the chain keeps the record.",
};

/**
 * The first thirty seconds. What seat it fills, what it caught, why to trust it.
 *
 * No figure on this page is typed in: live ones come from the API when it is
 * reachable, the rest from public/proof.json, which scripts/proof.mjs copies
 * from the last real `make eval` and `make prove-limits` runs, with the date.
 */
export default function WelcomePage() {
  return (
    <>
      <WelcomeHeader />
      <main className="relative">
        <Hero />
        <div className="rule-soft" />
        <BeatAmendment />
        <div className="rule-soft" />
        <BeatJanuary />
        <div className="rule-soft" />
        <BeatTrust />
        <div className="rule-soft" />
        <HowItWorks />
        <TechStrip />
        <Closing />
      </main>
    </>
  );
}
