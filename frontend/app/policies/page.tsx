import { PlaceholderPage } from "@/components/PlaceholderPage";

export default function PoliciesPage() {
  return (
    <PlaceholderPage
      icon="policies"
      eyebrow="Portfolio"
      title="Policies"
      lead="The house rules the agents follow, learned from precedent and approved by the controller."
      shows={[
        { label: "The rule in plain words", detail: "Scope, action and the charge types it covers." },
        { label: "Backtest", detail: "What would have changed historically, and any conflicts." },
        { label: "Cited by", detail: "The decisions that relied on each rule." },
        { label: "Approve or reject", detail: "Controller only, with versions kept." },
      ]}
    />
  );
}
