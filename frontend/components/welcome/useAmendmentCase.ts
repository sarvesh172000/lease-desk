"use client";

import { useQuery } from "@tanstack/react-query";
import { getException } from "@/lib/api";
import { FIXTURE_DOCUMENTS, SECTION_16_EXCEPTION_DETAIL, fixturePageUrl } from "@/lib/fixtures";
import { useApiHealth, useDataSource, useExceptions } from "@/lib/hooks";
import type { DocumentPages, ExceptionDetail, JournalLine } from "@/lib/types";
import { amendmentCaseId, figureSource, type FigureSource } from "@/lib/welcome";

/**
 * The case the story opens on: the July base-rent under-bill whose cause was an
 * executed amendment. Live, it is whichever exception the running system gave
 * that charge; offline, the §16 fixture. Either way the figures are the API's.
 */
export interface AmendmentCase {
  id: string | null;
  detail: ExceptionDetail | undefined;
  isLoading: boolean;
  source: FigureSource;
  /** Where the page images and sizes come from: the API, or the fixture copies when the API would not answer. */
  pages: { src: (docId: string, page: number) => string; sizes: Record<string, DocumentPages> } | null;
}

const FIXTURE_PAGES = { src: fixturePageUrl, sizes: FIXTURE_DOCUMENTS };

/**
 * A stranger on /welcome has no session, so the API answers 401; and a freshly
 * seeded desk has not investigated July yet. Either way the page shows the
 * fixture copy of the case and says so. Never a blank, never a live label on a
 * fixture.
 */
export function useAmendmentCase(): AmendmentCase {
  const dataSource = useDataSource();
  const health = useApiHealth();
  const list = useExceptions();
  const id = dataSource === "api" ? amendmentCaseId(list.data) : SECTION_16_EXCEPTION_DETAIL.exception_id;
  const detail = useQuery({
    queryKey: ["exception", id],
    queryFn: () => getException(id!),
    enabled: !!id,
    retry: false,
  });
  // no session, no such exception, or not yet investigated on this desk: the fixture copy, labelled as such
  const refused =
    dataSource === "api" &&
    (list.isError || detail.isError || (list.isSuccess && !id) || (detail.isSuccess && !detail.data.investigation));
  if (refused) {
    return {
      id: SECTION_16_EXCEPTION_DETAIL.exception_id,
      detail: SECTION_16_EXCEPTION_DETAIL,
      isLoading: false,
      source: { kind: "fixtures" },
      pages: FIXTURE_PAGES,
    };
  }
  return {
    id,
    detail: detail.data,
    isLoading: list.isLoading || detail.isLoading,
    source: figureSource({ source: dataSource, reachable: health.reachable, liveOk: detail.isSuccess, asOf: detail.data?.period ?? null }),
    pages: dataSource === "fixtures" ? FIXTURE_PAGES : null,
  };
}

/** The lease-liability line of the proposed entries: the amount the story is about, as the engine wrote it. */
export function liabilityLine(entries: JournalLine[] | undefined): number | null {
  const line = entries?.find((e) => /lease liability/i.test(e.account));
  if (!line) return null;
  return line.credit || line.debit;
}
