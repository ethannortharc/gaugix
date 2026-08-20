import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from '@tanstack/react-query'

import { apiFetch, apiFetchList, buildQuery } from '@/api/client'
import type {
  CountResponse,
  EvalCase,
  EvalCollection,
  EvalSet,
  EvalSetNode,
  EvaluationProfile,
  ExportFormat,
  FieldMapping,
  GenPromptResponse,
  ImportFormat,
  ImportResult,
  Message,
  ScorerSpec,
} from '@/api/types'

/** Query keys in one place so invalidation stays honest. */
export const qk = {
  cases: (filters?: Record<string, unknown>) => ['cases', filters ?? {}] as const,
  case: (id: number) => ['case', id] as const,
  sets: (filters?: Record<string, unknown>) => ['sets', filters ?? {}] as const,
  set: (id: number) => ['set', id] as const,
  setCases: (id: number, filters?: Record<string, unknown>) =>
    ['set', id, 'cases', filters ?? {}] as const,
  setNodes: (id: number) => ['set', id, 'nodes'] as const,
  collections: (filters?: Record<string, unknown>) => ['collections', filters ?? {}] as const,
  collection: (id: number) => ['collection', id] as const,
}

export interface CaseFilters extends Record<
  string,
  string | number | boolean | string[] | undefined
> {
  q?: string
  tags?: string[]
  set_id?: number
  exclude_set_id?: number
  /** Only cases that belong to no set — otherwise invisible in a set-scoped UI. */
  unfiled?: boolean
  trashed?: boolean
  limit?: number
  offset?: number
}

export function useCases(filters: CaseFilters = {}) {
  return useQuery({
    queryKey: qk.cases(filters),
    queryFn: () => apiFetchList<EvalCase>('/cases', { query: filters }),
  })
}

export function useCase(id: number | undefined) {
  return useQuery({
    queryKey: qk.case(id ?? 0),
    queryFn: () => apiFetch<EvalCase>(`/cases/${id}`),
    enabled: id !== undefined && Number.isFinite(id),
  })
}

export function useSets(
  filters: {
    q?: string
    tags?: string[]
    collection_id?: number
    include_descendants?: boolean
    visibility?: string[]
    unfiled?: boolean
    trashed?: boolean
    limit?: number
    offset?: number
  } = {},
) {
  return useQuery({
    queryKey: qk.sets(filters),
    queryFn: () => apiFetchList<EvalSet>('/sets', { query: filters }),
  })
}

export function useCollections(filters: { visibility?: string[]; roots_only?: boolean } = {}) {
  return useQuery({
    queryKey: qk.collections(filters),
    queryFn: () => apiFetchList<EvalCollection>('/collections', { query: filters }),
  })
}

export function useCollection(id: number | undefined) {
  return useQuery({
    queryKey: qk.collection(id ?? 0),
    queryFn: () => apiFetch<EvalCollection>(`/collections/${id}`),
    enabled: id !== undefined && Number.isFinite(id),
  })
}

/** The API's own ceiling. Asking for more is rejected, not truncated. */
const MAX_PAGE = 500

/**
 * Every set, for a picker that must be able to offer every set.
 *
 * `useSets()` takes the API default of 50. That is right for a browsable page
 * with a Load more button and wrong for a chooser: the run builder, the
 * library's set filter and the copy/move menu all used it, so the 51st set
 * existed, was findable on the Sets page, and could not be run, filtered by or
 * copied into (D-064).
 *
 * `truncated` is true past the API's own ceiling — at which point a picker is
 * the wrong control and the caller should say so rather than pretend.
 */
export function useSetOptions() {
  const query = useSets({ limit: MAX_PAGE })
  const total = query.data?.total ?? 0
  return { ...query, truncated: total > MAX_PAGE, total }
}

export function useSet(id: number | undefined) {
  return useQuery({
    queryKey: qk.set(id ?? 0),
    queryFn: () => apiFetch<EvalSet>(`/sets/${id}`),
    enabled: id !== undefined && Number.isFinite(id),
  })
}

export function useSetCases(
  id: number | undefined,
  filters: {
    q?: string
    tags?: string[]
    node_id?: number
    include_descendants?: boolean
    ungrouped?: boolean
    limit?: number
    offset?: number
  } = {},
  options?: Partial<UseQueryOptions<{ items: EvalCase[]; total: number }>>,
) {
  return useQuery({
    queryKey: qk.setCases(id ?? 0, filters),
    queryFn: () => apiFetchList<EvalCase>(`/sets/${id}/cases`, { query: filters }),
    enabled: id !== undefined && Number.isFinite(id),
    ...options,
  })
}

/** Invalidate everything a case/set write could have changed. */
function useInvalidateAll() {
  const client = useQueryClient()
  return () => {
    void client.invalidateQueries({ queryKey: ['cases'] })
    void client.invalidateQueries({ queryKey: ['case'] })
    void client.invalidateQueries({ queryKey: ['sets'] })
    void client.invalidateQueries({ queryKey: ['set'] })
    void client.invalidateQueries({ queryKey: ['collections'] })
  }
}

// -- mutations -----------------------------------------------------------------

export interface CaseInput {
  title: string
  input: Message[]
  reference?: string | null
  scoring?: ScorerSpec[]
  tags?: string[]
  notes?: string | null
  set_id?: number
  node_id?: number
}

export function useCreateCase() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: CaseInput) => apiFetch<EvalCase>('/cases', { method: 'POST', body }),
    onSuccess: invalidate,
  })
}

export function useUpdateCase() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, ...body }: Partial<CaseInput> & { id: number }) =>
      apiFetch<EvalCase>(`/cases/${id}`, { method: 'PATCH', body }),
    onSuccess: invalidate,
  })
}

export function useDeleteCase() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, purge = false }: { id: number; purge?: boolean }) =>
      apiFetch<CountResponse>(`/cases/${id}${buildQuery({ purge })}`, { method: 'DELETE' }),
    onSuccess: invalidate,
  })
}

export function useRestoreCase() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (id: number) => apiFetch<EvalCase>(`/cases/${id}/restore`, { method: 'POST' }),
    onSuccess: invalidate,
  })
}

export function useDuplicateCase() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, setId }: { id: number; setId?: number }) =>
      apiFetch<EvalCase>(`/cases/${id}/duplicate${buildQuery({ set_id: setId })}`, {
        method: 'POST',
      }),
    onSuccess: invalidate,
  })
}

export type BulkOp =
  | { op: 'tags'; case_ids: number[]; add_tags?: string[]; remove_tags?: string[] }
  | {
      op: 'move'
      case_ids: number[]
      target_set_id: number
      source_set_id?: number
      target_node_id?: number
      mode: 'copy' | 'move'
    }
  | { op: 'delete' | 'restore' | 'purge'; case_ids: number[] }

export function useBulkCaseOp() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ op, ...body }: BulkOp) =>
      apiFetch<CountResponse>(`/cases/bulk/${op}`, { method: 'POST', body }),
    onSuccess: invalidate,
  })
}

// -- sets ----------------------------------------------------------------------

export interface SetInput {
  name: string
  description?: string | null
  tags?: string[]
  default_scoring?: ScorerSpec[]
  evaluation_profile?: EvaluationProfile
  collection_id?: number | null
  logical_key?: string | null
  variant?: string | null
  visibility?: 'primary' | 'fixture' | 'hidden'
}

export interface CollectionInput {
  key: string
  name: string
  description?: string | null
  parent_id?: number | null
  position?: number
  visibility?: 'primary' | 'fixture' | 'hidden'
  tags?: string[]
  provenance?: Record<string, unknown>
}

export function useCreateCollection() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: CollectionInput) =>
      apiFetch<EvalCollection>('/collections', { method: 'POST', body }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['collections'] })
    },
  })
}

export function useUpdateCollection() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: Partial<CollectionInput> & { id: number }) =>
      apiFetch<EvalCollection>(`/collections/${id}`, { method: 'PATCH', body }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['collections'] })
      void client.invalidateQueries({ queryKey: ['collection'] })
      void client.invalidateQueries({ queryKey: ['sets'] })
    },
  })
}

export function useCreateSet() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: SetInput) => apiFetch<EvalSet>('/sets', { method: 'POST', body }),
    onSuccess: invalidate,
  })
}

export function useUpdateSet() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, ...body }: Partial<SetInput> & { id: number }) =>
      apiFetch<EvalSet>(`/sets/${id}`, { method: 'PATCH', body }),
    onSuccess: invalidate,
  })
}

export function useDeleteSet() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, purge = false }: { id: number; purge?: boolean }) =>
      apiFetch<CountResponse>(`/sets/${id}${buildQuery({ purge })}`, { method: 'DELETE' }),
    onSuccess: invalidate,
  })
}

export function useRestoreSet() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (id: number) => apiFetch<EvalSet>(`/sets/${id}/restore`, { method: 'POST' }),
    onSuccess: invalidate,
  })
}

export function useAttachCases(setId: number) {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ case_ids, node_id }: { case_ids: number[]; node_id?: number }) =>
      apiFetch<CountResponse>(`/sets/${setId}/cases`, {
        method: 'POST',
        body: { case_ids, node_id },
      }),
    onSuccess: invalidate,
  })
}

// -- set hierarchy ------------------------------------------------------------

export function useSetNodes(setId: number | undefined) {
  return useQuery({
    queryKey: qk.setNodes(setId ?? 0),
    queryFn: () => apiFetch<EvalSetNode[]>(`/sets/${setId}/nodes`),
    enabled: setId !== undefined && Number.isFinite(setId),
  })
}

export interface SetNodeInput {
  name: string
  parent_id?: number | null
  description?: string | null
  position?: number
  tags?: string[]
  provenance?: Record<string, unknown>
}

export function useCreateSetNode(setId: number) {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: SetNodeInput) =>
      apiFetch<EvalSetNode>(`/sets/${setId}/nodes`, { method: 'POST', body }),
    onSuccess: invalidate,
  })
}

export function useUpdateSetNode(setId: number) {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, ...body }: Partial<SetNodeInput> & { id: number }) =>
      apiFetch<EvalSetNode>(`/sets/${setId}/nodes/${id}`, { method: 'PATCH', body }),
    onSuccess: invalidate,
  })
}

export function useDeleteSetNode(setId: number) {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<CountResponse>(`/sets/${setId}/nodes/${id}`, { method: 'DELETE' }),
    onSuccess: invalidate,
  })
}

export function useAssignCasesNode(setId: number) {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ case_ids, node_id }: { case_ids: number[]; node_id: number | null }) =>
      apiFetch<CountResponse>(`/sets/${setId}/nodes/assign`, {
        method: 'POST',
        body: { case_ids, node_id },
      }),
    onSuccess: invalidate,
  })
}

export function useDetachCases(setId: number) {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (case_ids: number[]) =>
      apiFetch<CountResponse>(`/sets/${setId}/cases/detach`, {
        method: 'POST',
        body: { case_ids },
      }),
    onSuccess: invalidate,
  })
}

export function useReorderCases(setId: number) {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (case_ids: number[]) =>
      apiFetch<CountResponse>(`/sets/${setId}/cases/reorder`, {
        method: 'POST',
        body: { case_ids },
      }),
    onSuccess: invalidate,
  })
}

// -- import / export / generate ------------------------------------------------

export function useImportCases() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: {
      content: string
      format: ImportFormat
      set_id?: number
      /** Destination branch. Native group_path values are nested below it. */
      node_id?: number
      dry_run?: boolean
      /** Only meaningful for tabular formats; the server guesses without it. */
      mapping?: FieldMapping
    }) => apiFetch<ImportResult>('/cases/import', { method: 'POST', body }),
    onSuccess: (result) => {
      if (result.ok && !result.dry_run) invalidate()
    },
  })
}

/*
  There was a `useImportCasesFile` here, posting the file straight to
  `/cases/import/file`. It ignored the chosen format and the column mapping and
  skipped Check, so uploading a file behaved differently from pasting its
  contents. The dialog now reads the file and uses the one path (D-052); the
  endpoint stays for scripts and the CLI.
*/

/** Direct link to the export endpoint — the browser handles the download. */
export function exportUrl(params: {
  format: ExportFormat
  setId?: number
  caseIds?: number[]
  download?: boolean
}) {
  return `/api/v1/cases/export${buildQuery({
    format: params.format,
    set_id: params.setId,
    case_ids: params.caseIds?.map(String),
    download: params.download ?? true,
  })}`
}

export function useGenerationPrompt() {
  return useMutation({
    mutationFn: (body: {
      topic: string
      count?: number
      set_id?: number
      example_count?: number
      instructions?: string
    }) => apiFetch<GenPromptResponse>('/gen/prompt', { method: 'POST', body }),
  })
}
