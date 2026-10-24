"use client";

import { useQuery } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import { getDataSource, getDemoActors, getMe, subscribeDataSource, type DataSource } from "./api";

export function useDataSource(): DataSource {
  return useSyncExternalStore(subscribeDataSource, getDataSource, () => getDataSource());
}

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: getMe, staleTime: 60_000 });
}

export function useDemoActors() {
  return useQuery({ queryKey: ["demo-actors"], queryFn: getDemoActors, staleTime: 5 * 60_000, retry: false });
}
