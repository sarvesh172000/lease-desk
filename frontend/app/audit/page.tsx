"use client";

import { AuditView } from "@/components/audit/AuditView";
import { LoadingBlock } from "@/components/ui/States";
import { BROKEN_CHAIN_FIXTURE } from "@/lib/chain";
import { useAudit, useDataSource } from "@/lib/hooks";
import type { AuditResponse } from "@/lib/types";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

export default function AuditPage() {
  return (
    <Suspense fallback={<LoadingBlock rows={6} label="Loading audit trail" />}>
      <AuditTrail />
    </Suspense>
  );
}

function AuditTrail() {
  const params = useSearchParams();
  const router = useRouter();
  const leaseId = params.get("lease_id") || undefined;
  const source = useDataSource();
  // Offline demo only: ?fixture=broken shows the broken-chain state from a fixture, and says so.
  const brokenFixture = source === "fixtures" && params.get("fixture") === "broken";
  const q = useAudit(leaseId);
  const data: AuditResponse | undefined = brokenFixture ? BROKEN_CHAIN_FIXTURE : q.data;
  return <AuditView data={data} loading={q.isLoading && !brokenFixture} error={q.isError && !brokenFixture ? q.error : null} refetch={() => q.refetch()} fetching={q.isFetching} updatedAt={q.dataUpdatedAt} leaseId={leaseId} onClearLease={() => router.push("/audit")} fixture={brokenFixture} />;
}

