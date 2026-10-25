import { PlaceholderPage } from "@/components/PlaceholderPage";

export default function DisputesPage() {
  return (
    <PlaceholderPage
      icon="disputes"
      eyebrow="Portfolio"
      title="Disputes"
      lead="Letters to landlords about held money, from draft to credit, with every reply on the record."
      shows={[
        { label: "Pipeline", detail: "Drafted, sent, acknowledged, credited, partially credited, refused, with counts." },
        { label: "The letter", detail: "Rendered like real correspondence: to, facts and amount." },
        { label: "History", detail: "Every step and reply in order, with credits received." },
        { label: "Actions", detail: "Approve the letter (regional manager), the receivable (controller), record a reply." },
      ]}
    />
  );
}
