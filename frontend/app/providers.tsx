"use client";

import { ApiError } from "@/lib/api";
import { useLiveStatus } from "@/lib/live";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            // never retry a 4xx; a real "no" should show immediately
            retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 1,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <LiveStatus />
      {children}
    </QueryClientProvider>
  );
}

/** Other windows' approvals refetch this one (lib/live.ts); nothing when unconfigured. */
function LiveStatus() {
  useLiveStatus();
  return null;
}
