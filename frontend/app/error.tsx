"use client";

import { ErrorState } from "@/components/ui/States";

export default function GlobalError({ error, reset }: { error: Error; reset: () => void }) {
  return <ErrorState className="mt-10" title="Something broke on this screen" error={error} onRetry={reset} />;
}
