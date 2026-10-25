import { PlaceholderPage } from "@/components/PlaceholderPage";

export default function MonthPage() {
  return (
    <PlaceholderPage
      icon="month"
      eyebrow="Work"
      title="Month run"
      lead="The month's run as a pipeline: ingest, read leases, check, hold, dispute, batch, with the rows behind every number."
      shows={[
        { label: "The pipeline", detail: "Each stage with its count; the stage waiting on a person stands out." },
        { label: "Drill-down", detail: "Click any number to see the charges, holds or questions behind it." },
        { label: "Batch panel", detail: "What is ready, released and awaiting a decision, with the releasable total." },
        { label: "Release batch", detail: "The AP clerk's action, shown only to people the server allows." },
      ]}
      meanwhile={{ href: "/", label: "See today's queue" }}
    />
  );
}
