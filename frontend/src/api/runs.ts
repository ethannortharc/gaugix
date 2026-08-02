import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as React from 'react'

import { apiFetch, apiFetchList } from '@/api/client'
import type {
  CaseIO,
  CaseRunHistoryRow,
  CountResponse,
  ErrorKindCount,
  Executor,
  HarnessProfile,
  ItemStatus,
  JudgeClassCount,
  ModelProfile,
  Run,
  RunItem,
  RunItemDetail,
  RunPreview,
  ScoreRead,
  ModelCapabilities,
  PreflightRead,
  PricingPullResult,
  SetTrend,
  SetRunHistoryRow,
  SettingsRead,
  TestConnectionResult,
} from '@/api/types'

export const rk = {
  runs: (filters?: Record<string, unknown>) => ['runs', filters ?? {}] as const,
  run: (id: number) => ['run', id] as const,
  runItems: (id: number, filters?: Record<string, unknown>) =>
    ['run', id, 'items', filters ?? {}] as const,
  item: (id: number) => ['item', id] as const,
  executors: () => ['executors'] as const,
  models: () => ['model-profiles'] as const,
  harnesses: () => ['harness-profiles'] as const,
  settings: () => ['settings'] as const,
}

// -- executors -----------------------------------------------------------------

export function useExecutors(includeArchived = false) {
  return useQuery({
    queryKey: [...rk.executors(), includeArchived],
    queryFn: () =>
      apiFetchList<Executor>('/executors', { query: { include_archived: includeArchived } }),
  })
}

/** Which generation params a model accepts, so a form cannot offer a rejected one. */
export function useModelCapabilities(provider: string, modelId: string) {
  return useQuery({
    queryKey: ['model-capabilities', provider, modelId],
    queryFn: () =>
      apiFetch<ModelCapabilities>('/model-capabilities', {
        query: { provider, model_id: modelId },
      }),
    // The answer comes from a table bundled with litellm — it cannot change
    // while the app is open.
    staleTime: Infinity,
  })
}

export function useModelProfiles(includeArchived = false) {
  return useQuery({
    queryKey: [...rk.models(), includeArchived],
    queryFn: () =>
      apiFetchList<ModelProfile>('/model-profiles', {
        query: { include_archived: includeArchived },
      }),
  })
}

export function useHarnessProfiles(includeArchived = false) {
  return useQuery({
    queryKey: [...rk.harnesses(), includeArchived],
    queryFn: () =>
      apiFetchList<HarnessProfile>('/harness-profiles', {
        query: { include_archived: includeArchived },
      }),
  })
}

function useInvalidateExecutorStack() {
  const client = useQueryClient()
  return () => {
    void client.invalidateQueries({ queryKey: rk.executors() })
    void client.invalidateQueries({ queryKey: rk.models() })
    void client.invalidateQueries({ queryKey: rk.harnesses() })
  }
}

export function useSaveModelProfile() {
  const invalidate = useInvalidateExecutorStack()
  return useMutation({
    mutationFn: ({ id, ...body }: Record<string, unknown> & { id?: number }) =>
      id
        ? apiFetch<ModelProfile>(`/model-profiles/${id}`, { method: 'PATCH', body })
        : apiFetch<ModelProfile>('/model-profiles', { method: 'POST', body }),
    onSuccess: invalidate,
  })
}

export function useDeleteModelProfile() {
  const invalidate = useInvalidateExecutorStack()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<CountResponse>(`/model-profiles/${id}`, { method: 'DELETE' }),
    onSuccess: invalidate,
  })
}

export function useTestModelProfile() {
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<TestConnectionResult>(`/model-profiles/${id}/test`, { method: 'POST' }),
  })
}

export function useSaveHarnessProfile() {
  const invalidate = useInvalidateExecutorStack()
  return useMutation({
    mutationFn: ({ id, ...body }: Record<string, unknown> & { id?: number }) =>
      id
        ? apiFetch<HarnessProfile>(`/harness-profiles/${id}`, { method: 'PATCH', body })
        : apiFetch<HarnessProfile>('/harness-profiles', { method: 'POST', body }),
    onSuccess: invalidate,
  })
}

export function useDeleteHarnessProfile() {
  const invalidate = useInvalidateExecutorStack()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<CountResponse>(`/harness-profiles/${id}`, { method: 'DELETE' }),
    onSuccess: invalidate,
  })
}

export function useSaveExecutor() {
  const invalidate = useInvalidateExecutorStack()
  return useMutation({
    mutationFn: ({ id, ...body }: Record<string, unknown> & { id?: number }) =>
      id
        ? apiFetch<Executor>(`/executors/${id}`, { method: 'PATCH', body })
        : apiFetch<Executor>('/executors', { method: 'POST', body }),
    onSuccess: invalidate,
  })
}

export function useDeleteExecutor() {
  const invalidate = useInvalidateExecutorStack()
  return useMutation({
    mutationFn: (id: number) => apiFetch<CountResponse>(`/executors/${id}`, { method: 'DELETE' }),
    onSuccess: invalidate,
  })
}

// -- runs ----------------------------------------------------------------------

export function useRuns(filters: { status?: string[]; set_id?: number; limit?: number } = {}) {
  return useQuery({
    queryKey: rk.runs(filters),
    queryFn: () => apiFetchList<Run>('/runs', { query: filters }),
  })
}

export const RUN_HISTORY_MAX_LIMIT = 1000

export function useSetRunHistory(setId: number | undefined, limit = 10) {
  const requestLimit = Math.min(Math.max(limit, 1), RUN_HISTORY_MAX_LIMIT)
  return useQuery({
    queryKey: ['set', setId, 'run-history', requestLimit],
    queryFn: () =>
      apiFetchList<SetRunHistoryRow>(`/sets/${setId}/runs`, { query: { limit: requestLimit } }),
    enabled: setId !== undefined && Number.isFinite(setId),
  })
}

export function useCaseRunHistory(caseId: number | undefined, limit = 10) {
  const requestLimit = Math.min(Math.max(limit, 1), RUN_HISTORY_MAX_LIMIT)
  return useQuery({
    queryKey: ['case', caseId, 'run-history', requestLimit],
    queryFn: () =>
      apiFetchList<CaseRunHistoryRow>(`/cases/${caseId}/run-items`, {
        query: { limit: requestLimit },
      }),
    enabled: caseId !== undefined && Number.isFinite(caseId),
  })
}

/**
 * Pass rate per set over recent runs.
 *
 * Deliberately its own call rather than something derived from the run list:
 * a run's totals are run-wide, and a run covering several sets has a different
 * rate in each of them. The server splits per set; the dashboard must not try.
 */
export function useSetTrends(limit = 10) {
  return useQuery({
    queryKey: ['set-trends', limit],
    queryFn: () => apiFetch<SetTrend[]>('/runs/trends', { query: { limit } }),
  })
}

export function useRun(id: number | undefined, options: { live?: boolean } = {}) {
  return useQuery({
    queryKey: rk.run(id ?? 0),
    queryFn: () => apiFetch<Run>(`/runs/${id}`),
    enabled: id !== undefined && Number.isFinite(id),
    // A safety net behind SSE: if the stream drops, the page still converges.
    refetchInterval: options.live ? 4000 : false,
  })
}

export type RunItemFilters = Record<string, string | number | boolean | string[] | null | undefined>

export function useRunItems(
  id: number | undefined,
  filters: RunItemFilters = {},
  options: { live?: boolean } = {},
) {
  return useQuery({
    queryKey: rk.runItems(id ?? 0, filters),
    queryFn: () => apiFetchList<RunItem>(`/runs/${id}/items`, { query: filters }),
    enabled: id !== undefined && Number.isFinite(id),
    refetchInterval: options.live ? 4000 : false,
  })
}

export interface LaneCounts {
  executor_key: string
  counts: Partial<Record<ItemStatus, number>>
  total: number
}

/**
 * Per-executor progress over the *whole* run.
 *
 * Separate from the item list on purpose: that list is paginated, and counting
 * its rows described the page rather than the run.
 */
export function useRunLanes(runId: number | undefined, options: { live?: boolean } = {}) {
  return useQuery({
    queryKey: ['run', runId, 'lanes'],
    queryFn: () => apiFetch<LaneCounts[]>(`/runs/${runId}/lanes`),
    enabled: runId !== undefined && Number.isFinite(runId),
    refetchInterval: options.live ? 4000 : false,
  })
}

/** The error taxonomy present in one run — the source for the filter chips. */
export function useErrorKinds(runId: number | undefined) {
  return useQuery({
    queryKey: ['runs', runId, 'error-kinds'],
    queryFn: () => apiFetch<ErrorKindCount[]>(`/runs/${runId}/error-kinds`),
    enabled: runId !== undefined && Number.isFinite(runId),
  })
}

/**
 * How a class-graded judge split this run.
 *
 * Empty for the scale-graded rubrics that are most of them. SimpleQA is the
 * case it exists for: accuracy alone cannot tell a model that answered wrongly
 * from one that declined, and that difference is the benchmark's point.
 */
export function useJudgeClasses(runId: number | undefined) {
  return useQuery({
    queryKey: ['runs', runId, 'judge-classes'],
    queryFn: () => apiFetch<JudgeClassCount[]>(`/runs/${runId}/judge-classes`),
    enabled: runId !== undefined && Number.isFinite(runId),
  })
}

/**
 * Re-execute one item without touching the rest of its lane (PRD F3.6).
 *
 * `runId` travels with the call rather than the hook so the button can live on
 * a page that does not know the run until its query resolves.
 */
export function useRetryItem() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ runId, itemId }: { runId: number; itemId: number }) =>
      apiFetch<{ ok: boolean; affected: number; status: string; message: string | null }>(
        `/runs/${runId}/items/${itemId}/retry`,
        { method: 'POST' },
      ),
    onSuccess: (_data, { runId }) => {
      void client.invalidateQueries({ queryKey: rk.run(runId) })
      void client.invalidateQueries({ queryKey: rk.runItems(runId) })
      void client.invalidateQueries({ queryKey: ['runs', runId, 'error-kinds'] })
    },
  })
}

export function useRunItem(id: number | undefined) {
  return useQuery({
    queryKey: rk.item(id ?? 0),
    queryFn: () => apiFetch<RunItemDetail>(`/items/${id}`),
    enabled: id !== undefined && Number.isFinite(id),
  })
}

export function useRunPreview(
  setIds: number[],
  executorIds: number[],
  caseIds: number[] | null = null,
) {
  return useQuery({
    queryKey: ['run-preview', setIds, executorIds, caseIds],
    queryFn: () =>
      apiFetch<RunPreview>('/runs/preview', {
        method: 'POST',
        body: { set_ids: setIds, executor_ids: executorIds, case_ids: caseIds },
      }),
    enabled: setIds.length > 0 && executorIds.length > 0,
  })
}

/**
 * Everything wrong with a planned run that is knowable for free.
 *
 * Runs on every selection change: it reads, validates and estimates, and never
 * calls a model — so the first time you learn a regex will not compile is
 * before the tokens are spent rather than after.
 */
export function usePreflight(
  setIds: number[],
  executorIds: number[],
  caseIds: number[] | null = null,
  autoScore = true,
) {
  return useQuery({
    queryKey: ['run-preflight', setIds, executorIds, caseIds, autoScore],
    queryFn: () =>
      apiFetch<PreflightRead>('/runs/preflight', {
        method: 'POST',
        body: {
          set_ids: setIds,
          executor_ids: executorIds,
          case_ids: caseIds,
          auto_score: autoScore,
        },
      }),
    enabled: setIds.length > 0 && executorIds.length > 0,
  })
}

export function useCreateRun() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      set_ids: number[]
      executor_ids: number[]
      case_ids?: number[] | null
      name?: string
      concurrency?: number
      auto_score?: boolean
      start?: boolean
      accept_code_execution?: boolean
    }) => apiFetch<Run>('/runs', { method: 'POST', body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['runs'] }),
  })
}

function useInvalidateRun() {
  const client = useQueryClient()
  return (id: number) => {
    void client.invalidateQueries({ queryKey: rk.run(id) })
    void client.invalidateQueries({ queryKey: ['run', id, 'items'] })
    void client.invalidateQueries({ queryKey: ['runs'] })
  }
}

export function useCancelRun() {
  const invalidate = useInvalidateRun()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<{ ok: boolean; status: string; message: string | null }>(`/runs/${id}/cancel`, {
        method: 'POST',
      }),
    onSuccess: (_data, id) => invalidate(id),
  })
}

export function useResumeRun() {
  const invalidate = useInvalidateRun()
  return useMutation({
    mutationFn: ({ id, includeErrors = true }: { id: number; includeErrors?: boolean }) =>
      apiFetch<{ ok: boolean; scheduled: number; status: string; message: string | null }>(
        `/runs/${id}/resume`,
        { method: 'POST', body: { include_errors: includeErrors } },
      ),
    onSuccess: (_data, { id }) => invalidate(id),
  })
}

export function useDeleteRun() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<{ ok: boolean; status: string }>(`/runs/${id}`, { method: 'DELETE' }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['runs'] }),
  })
}

export function useSetBaseline() {
  const invalidate = useInvalidateRun()
  return useMutation({
    mutationFn: ({
      id,
      setIds,
      unset,
      allowPartial,
    }: {
      id: number
      setIds: number[]
      unset?: boolean
      /** Required to bless a run that covered only part of the set. */
      allowPartial?: boolean
    }) =>
      apiFetch<Run>(`/runs/${id}/baseline`, {
        method: 'POST',
        body: {
          set_ids: setIds,
          unset: unset ?? false,
          allow_partial: allowPartial ?? false,
        },
      }),
    onSuccess: (_data, { id }) => invalidate(id),
  })
}

// -- settings ------------------------------------------------------------------

export function useAppSettings() {
  return useQuery({
    queryKey: rk.settings(),
    queryFn: () => apiFetch<SettingsRead>('/settings'),
  })
}

export function useUpdateAppSettings() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiFetch<SettingsRead>('/settings', { method: 'PATCH', body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: rk.settings() }),
  })
}

/** Seed the pricing table from litellm's bundled cost map. Manual rows survive. */
export function usePullPricing() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { model_ids?: string[]; refresh?: boolean } = {}) =>
      apiFetch<PricingPullResult>('/settings/pricing/pull', { method: 'POST', body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: rk.settings() }),
  })
}

// -- live events ---------------------------------------------------------------

export interface RunEvent {
  type: 'run_status' | 'item_status' | 'usage_delta' | 'log' | 'ping' | 'end'
  seq: number
  [key: string]: unknown
}

/**
 * Subscribe to a run's SSE stream and merge deltas into the query cache.
 *
 * The page always fetches full state first and *then* subscribes, so nothing is
 * replayed. Events carry a monotonic `seq`; anything older than what we have
 * already applied is dropped, which makes a reconnect safe.
 */
export function useRunEvents(runId: number | undefined, enabled: boolean) {
  const client = useQueryClient()
  const [connected, setConnected] = React.useState(false)
  const lastSeq = React.useRef(0)

  React.useEffect(() => {
    if (!runId || !enabled) return
    const source = new EventSource(`/api/v1/runs/${runId}/events`)
    let closed = false

    const invalidate = () => {
      void client.invalidateQueries({ queryKey: rk.run(runId) })
      void client.invalidateQueries({ queryKey: ['run', runId, 'items'] })
    }

    const handle = (raw: MessageEvent, type: RunEvent['type']) => {
      try {
        const data = JSON.parse(raw.data) as { seq?: number }
        const seq = data.seq ?? 0
        if (seq && seq <= lastSeq.current) return
        lastSeq.current = seq
      } catch {
        return
      }
      if (type === 'end') {
        invalidate()
        source.close()
        setConnected(false)
        closed = true
        return
      }
      invalidate()
    }

    source.addEventListener('open', () => setConnected(true))
    for (const type of ['run_status', 'item_status', 'usage_delta', 'log', 'end'] as const) {
      source.addEventListener(type, (event) => handle(event as MessageEvent, type))
    }
    source.onerror = () => setConnected(false)

    return () => {
      if (!closed) source.close()
      setConnected(false)
    }
  }, [runId, enabled, client])

  return { connected }
}

// -- scoring (PRD F4) ----------------------------------------------------------

export interface QueueItem {
  item_id: number
  run_id: number
  run_name: string
  title: string
  executor_key: string
  set_id: number | null
  set_name: string
  instructions: string | null
  scorer_index: number
  /** What the automatic scorers concluded, so disagreement is visible up front. */
  auto_verdict: boolean | null
  auto_score: number | null
  updated_at: string
}

export interface HumanScoreResponse {
  ok: boolean
  verdict: boolean | null
  score_value: number | null
  needs_human: boolean
  status: string
  disagreed_with_machine: boolean
}

export interface RescoreResponse {
  ok: boolean
  items_rescored: number
  items_skipped: number
  verdict_changes: number
  details: { item_id: number; title: string; before: boolean | null; after: boolean | null }[]
}

export interface Rubric {
  key: string
  name: string
  text: string
  builtin: boolean
}

export function useReviewQueue(runId?: number) {
  return useQuery({
    queryKey: ['review-queue', runId ?? null],
    queryFn: () => apiFetchList<QueueItem>('/review-queue', { query: { run_id: runId } }),
  })
}

export function useSubmitHumanScore() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      itemId,
      ...body
    }: {
      itemId: number
      scorer_index: number
      passed?: boolean | null
      value?: number | null
      note?: string
    }) => apiFetch<HumanScoreResponse>(`/items/${itemId}/human-score`, { method: 'POST', body }),
    onSuccess: (_data, { itemId }) => {
      void client.invalidateQueries({ queryKey: rk.item(itemId) })
      void client.invalidateQueries({ queryKey: ['review-queue'] })
      void client.invalidateQueries({ queryKey: ['run'] })
      void client.invalidateQueries({ queryKey: ['runs'] })
    },
  })
}

export function useRescore() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      run_id?: number
      item_ids?: number[]
      only_failing?: boolean
      scorer_indices?: number[]
    }) => apiFetch<RescoreResponse>('/rescore', { method: 'POST', body }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['run'] })
      void client.invalidateQueries({ queryKey: ['runs'] })
      void client.invalidateQueries({ queryKey: ['item'] })
      void client.invalidateQueries({ queryKey: ['review-queue'] })
    },
  })
}

/**
 * Every version of every score for an item, oldest first.
 *
 * Separate from the item payload, which carries only the latest per scorer —
 * history is a deliberate click rather than something every page pays for.
 */
export function useItemScoreHistory(itemId: number | undefined) {
  return useQuery({
    queryKey: ['item', itemId, 'score-history'],
    queryFn: () => apiFetch<ScoreRead[]>(`/items/${itemId}/scores`, { query: { history: true } }),
    enabled: itemId !== undefined && Number.isFinite(itemId),
  })
}

export interface GenDirectResponse {
  cases: CaseIO[]
  errors: { line: number; message: string; raw: string | null }[]
  raw_output: string
  usage: {
    prompt_tokens?: number
    completion_tokens?: number
    cost_usd?: number | null
    latency_ms?: number
    executor?: string
  }
}

/**
 * Path B of AI generation (PRD F1.5): a configured executor drafts the cases.
 *
 * Writes nothing — candidates come back for review and are committed through
 * the ordinary importer, so a model's draft faces the same gate as a file.
 */
export function useGenerateDirect() {
  return useMutation({
    mutationFn: (body: {
      topic: string
      count: number
      set_id?: number
      example_count?: number
      instructions?: string
      executor_id: number
    }) => apiFetch<GenDirectResponse>('/gen/direct', { method: 'POST', body }),
  })
}

export function useRubrics() {
  return useQuery({ queryKey: ['rubrics'], queryFn: () => apiFetch<Rubric[]>('/rubrics') })
}

export function useSaveRubric() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { key: string; text: string }) =>
      apiFetch<Rubric[]>('/rubrics', { method: 'PUT', body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['rubrics'] }),
  })
}

export function useDeleteRubric() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (key: string) =>
      apiFetch<Rubric[]>(`/rubrics/${encodeURIComponent(key)}`, { method: 'DELETE' }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['rubrics'] }),
  })
}

export function useRerunFrom() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ runId, itemId }: { runId: number; itemId: number }) =>
      apiFetch<{ ok: boolean; affected: number; status: string; message: string | null }>(
        `/runs/${runId}/items/${itemId}/rerun-from`,
        { method: 'POST' },
      ),
    onSuccess: (_data, { runId }) => {
      void client.invalidateQueries({ queryKey: rk.run(runId) })
      void client.invalidateQueries({ queryKey: ['run', runId, 'items'] })
      void client.invalidateQueries({ queryKey: ['item'] })
    },
  })
}

export function useRerunWholeRun() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (runId: number) => apiFetch<Run>(`/runs/${runId}/rerun`, { method: 'POST' }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['runs'] }),
  })
}
