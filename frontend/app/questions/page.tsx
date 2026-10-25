import { PlaceholderPage } from "@/components/PlaceholderPage";

export default function QuestionsPage() {
  return (
    <PlaceholderPage
      icon="questions"
      eyebrow="Work"
      title="Questions"
      lead="The questions the agents asked people when the documents could not settle a charge on their own."
      shows={[
        { label: "Your inbox", detail: "Open questions waiting on you, with the item they are about." },
        { label: "Who was asked", detail: "The person, their role and when the payment is due." },
        { label: "Answer inline", detail: "Reply without leaving the inbox; the answer goes on the record." },
        { label: "Everything in scope", detail: "Switch from mine to every open question in your region." },
      ]}
    />
  );
}
