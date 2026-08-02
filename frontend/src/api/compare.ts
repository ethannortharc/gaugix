import { useQuery } from '@tanstack/react-query'

import { apiFetch } from '@/api/client'
import type {
  AggregateMatrixRead,
  CompareOptions,
  DiffRead,
  LeaderboardRead,
  MatrixRead,
} from '@/api/types'

/**
 * Comparison queries (PRD F5.2–F5.4).
 *
 * Every view is derived from run items on the server, so nothing here caches
 * beyond React Query's own window — a comparison always reflects the runs as
 * they are now, including after a re-score.
 */

export type CompareFilters = {
  runIds: number[]
  setIds?: number[]
  executors?: string[]
}

/** The client's query serializer takes string arrays for repeated params. */
function compareQuery({ runIds, setIds, executors }: CompareFilters) {
  return {
    run_id: runIds.map(String),
    ...(setIds?.length ? { set_id: setIds.map(String) } : {}),
    ...(executors?.length ? { executor: executors } : {}),
  }
}

const key = (view: string, filters: CompareFilters) => ['compare', view, filters] as const

export function useCompareOptions() {
  return useQuery({
    queryKey: ['compare', 'options'],
    queryFn: () => apiFetch<CompareOptions>('/compare/options'),
  })
}

export function useLeaderboard(filters: CompareFilters) {
  return useQuery({
    queryKey: key('leaderboard', filters),
    queryFn: () =>
      apiFetch<LeaderboardRead>('/compare/leaderboard', { query: compareQuery(filters) }),
    enabled: filters.runIds.length > 0,
  })
}

export function useMatrix(filters: CompareFilters) {
  return useQuery({
    queryKey: key('matrix', filters),
    queryFn: () => apiFetch<MatrixRead>('/compare/matrix', { query: compareQuery(filters) }),
    enabled: filters.runIds.length > 0,
  })
}

export function useAggregate(filters: CompareFilters) {
  return useQuery({
    queryKey: key('aggregate', filters),
    queryFn: () =>
      apiFetch<AggregateMatrixRead>('/compare/aggregate', { query: compareQuery(filters) }),
    enabled: filters.runIds.length > 0,
  })
}

/**
 * The regression diff. With no `baselineRunId` the server finds the run marked
 * baseline for this run's sets — and 422s with an explanation when there is none,
 * which the UI shows as guidance rather than as an error.
 */
export function useDiff(runId: number | undefined, baselineRunId?: number, setIds?: number[]) {
  return useQuery({
    queryKey: ['compare', 'diff', runId, baselineRunId, setIds],
    queryFn: () =>
      apiFetch<DiffRead>('/compare/diff', {
        query: {
          run_id: runId,
          ...(baselineRunId ? { baseline_run_id: baselineRunId } : {}),
          ...(setIds?.length ? { set_id: setIds.map(String) } : {}),
        },
      }),
    enabled: runId !== undefined,
    retry: false,
  })
}

/** Report downloads are plain links, not fetches — the browser saves the file. */
export function runReportUrl(runId: number): string {
  return `/api/v1/runs/${runId}/report`
}

export function comparisonReportUrl(runIds: number[], baselineRunId?: number): string {
  const params = new URLSearchParams()
  for (const id of runIds) params.append('run_id', String(id))
  if (baselineRunId) params.set('baseline_run_id', String(baselineRunId))
  return `/api/v1/compare/report?${params.toString()}`
}
