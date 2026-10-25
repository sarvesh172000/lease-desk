import { PlaceholderPage } from "@/components/PlaceholderPage";

export default function ObligationsPage() {
  return (
    <PlaceholderPage
      icon="obligations"
      eyebrow="Portfolio"
      title="Obligations"
      lead="Deadlines the leases set: renewal notices, CAM audit windows, deposit returns and expirations."
      shows={[
        { label: "Timeline", detail: "Upcoming deadlines along a river of weeks, coloured by urgency." },
        { label: "Days left", detail: "How long remains for each, and what action it needs." },
        { label: "Citation", detail: "The lease clause that creates the obligation, one click from the PDF." },
        { label: "Filters", detail: "By kind, lease and window (30, 90 or 365 days)." },
      ]}
    />
  );
}
