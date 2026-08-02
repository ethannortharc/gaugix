import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiFetch } from '@/api/client'
import type {
  BenchmarkDetail,
  BenchmarkSummary,
  InstallPreview,
  InstallRequest,
  InstallResult,
} from '@/api/types'

/**
 * The benchmark catalogue (PRD F1.3, extended).
 *
 * Browsing is free and offline — the server reads sample rows shipped inside
 * Gaugix. Only `install` with `scope: 'full'` can reach the network, and
 * `preview` exists so the UI can show the exact host and URL first.
 */

export const bk = {
  all: () => ['benchmarks'] as const,
  one: (slug: string) => ['benchmarks', slug] as const,
}

export function useBenchmarks() {
  return useQuery({
    queryKey: bk.all(),
    queryFn: () => apiFetch<BenchmarkSummary[]>('/benchmarks'),
  })
}

export function useBenchmark(slug: string | undefined) {
  return useQuery({
    queryKey: bk.one(slug ?? ''),
    queryFn: () => apiFetch<BenchmarkDetail>(`/benchmarks/${slug}`),
    enabled: Boolean(slug),
  })
}

/** What an install would do — name clashes, caveats, and the URL involved. */
export function usePreviewInstall() {
  return useMutation({
    mutationFn: ({ slug, ...body }: InstallRequest & { slug: string }) =>
      apiFetch<InstallPreview>(`/benchmarks/${slug}/preview`, { method: 'POST', body }),
  })
}

export function useInstallBenchmark() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ slug, ...body }: InstallRequest & { slug: string }) =>
      apiFetch<InstallResult>(`/benchmarks/${slug}/install`, { method: 'POST', body }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: bk.all() })
      // An install creates a set, so the sets list and the dashboard are stale.
      void client.invalidateQueries({ queryKey: ['sets'] })
    },
  })
}
