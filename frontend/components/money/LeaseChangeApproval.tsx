import type { ModificationLink } from "@/lib/types";
import Link from "next/link";

const POSTED = "POSTED";

/** Where the remeasurement's approval lives: the lease change (LEASE_MODIFICATION), which only a controller approves. */
export function leaseChangeHref(leaseId: string): string {
  return `/leases/${encodeURIComponent(leaseId)}`;
}

/** The "On approval" card's words once an investigation has proposed a lease change. */
export function LeaseChangeApproval({
  leaseId,
  modification,
  entries,
  balanced,
}: Readonly<{ leaseId: string; modification: ModificationLink; entries: number; balanced: boolean }>) {
  const version = modification.version == null ? "the new version" : `v${modification.version}`;
  const link = (
    <Link href={leaseChangeHref(leaseId)} className="font-medium text-accent hover:underline">
      {leaseId} {version}
    </Link>
  );
  if (modification.state === POSTED) {
    return (
      <>
        Approved: {link} is confirmed, and the gateway posted the {entries} {balanced ? "balanced " : ""}entries. This charge is rechecked against{" "}
        {version}; the approval is in the audit trail.
      </>
    );
  }
  return (
    <>
      {entries} proposed entries, {balanced ? "balanced" : "not balanced"}. They post when a controller approves the lease change on {link} (item #
      {modification.item_id}, {modification.state.toLowerCase()}); the decision is recorded in the audit trail.
    </>
  );
}
