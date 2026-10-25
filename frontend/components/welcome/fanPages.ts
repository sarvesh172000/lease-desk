import { money } from "@/lib/format";
import type { ExceptionDetail } from "@/lib/types";
import type { FanPage } from "./DocumentFan";

/**
 * The three pages the amendment case cites, in the order the fan stacks them:
 * the lease clause at the back, the billed line in the middle, the amendment
 * in front. Only what the exception carries; a page it lacks is left out.
 */
export function fanPages(detail: ExceptionDetail | undefined): FanPage[] {
  if (!detail) return [];
  const out: FanPage[] = [];
  const lease = detail.lease_citation;
  if (lease) {
    out.push({
      key: "lease",
      docId: lease.doc_id,
      page: lease.page,
      box: lease.box,
      tone: "lease",
      tag: `LEASE · ${lease.label.replace(/^LEASE-\d+ · /, "")} · p.${lease.page}`,
      alt: `Lease page ${lease.page}: ${lease.quote}`,
      quote: lease.quote,
    });
  }
  const line = detail.invoice_line;
  if (line) {
    out.push({
      key: "invoice",
      docId: line.doc_id,
      page: line.page,
      box: line.box,
      tone: "billed",
      tag: `INVOICE · ${money(line.amount)} BILLED`,
      alt: `Invoice page ${line.page}: ${line.description}, ${money(line.amount)}`,
      quote: `${line.description} · ${money(line.amount)}`,
    });
  }
  const ev = detail.investigation?.evidence[0];
  if (ev) {
    out.push({
      key: "email",
      docId: ev.doc_id,
      page: ev.page,
      box: ev.box,
      tone: "found",
      tag: `AMENDMENT · TRUST RANK ${ev.trust_rank}`,
      alt: ev.page ? `Email page ${ev.page}: ${ev.quote}` : `Email from ${ev.source}: ${ev.quote}`,
      quote: ev.quote,
      from: ev.source,
    });
  }
  return out;
}
