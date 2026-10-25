import { PlaceholderPage } from "@/components/PlaceholderPage";

export default function ExceptionsPage() {
  return (
    <PlaceholderPage
      icon="exceptions"
      eyebrow="Work"
      title="Exceptions"
      lead="Every charge that did not match its lease, across the portfolio, with keyboard review (J/K to move, A approve, H hold)."
      shows={[
        { label: "The full queue", detail: "Status, charge, clinic, period, expected, billed and variance for every open item." },
        { label: "Filters", detail: "By status, clinic, region and period, with counts." },
        { label: "Keyboard review", detail: "Move through items and act without leaving the list." },
        { label: "Resolved history", detail: "What was approved, held or paid as billed, and by whom." },
      ]}
      meanwhile={{ href: "/", label: "Open today's queue" }}
    />
  );
}
