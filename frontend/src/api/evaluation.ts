import { useQuery } from '@tanstack/react-query'

import { apiFetch } from '@/api/client'
import type { RunEvaluation } from '@/api/types'

export function useRunMetrics(
  runId: number | undefined,
  filters: { set_id?: number; executor_key?: string; node_id?: number } = {},
  options: { live?: boolean } = {},
) {
  return useQuery({
    queryKey: ['run', runId, 'metrics', filters],
    queryFn: () => apiFetch<RunEvaluation>(`/runs/${runId}/metrics`, { query: filters }),
    enabled: runId !== undefined && Number.isFinite(runId),
    refetchInterval: options.live ? 4000 : false,
  })
}
