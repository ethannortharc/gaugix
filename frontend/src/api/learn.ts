import { useQuery } from '@tanstack/react-query'

import { apiFetch } from '@/api/client'
import type { ChapterRead, ChapterSummary, SearchHit } from '@/api/types'

/**
 * The eval guide (PRD F7.1).
 *
 * Content ships with the app and cannot change while it is running, so
 * everything here is cached indefinitely.
 */

export function useChapters() {
  return useQuery({
    queryKey: ['learn'],
    queryFn: () => apiFetch<ChapterSummary[]>('/learn'),
    staleTime: Infinity,
  })
}

export function useChapter(slug: string | undefined) {
  return useQuery({
    queryKey: ['learn', slug],
    queryFn: () => apiFetch<ChapterRead>(`/learn/${slug}`),
    enabled: Boolean(slug),
    staleTime: Infinity,
  })
}

export function useLearnSearch(query: string) {
  return useQuery({
    queryKey: ['learn', 'search', query],
    queryFn: () => apiFetch<SearchHit[]>('/learn/search', { query: { q: query } }),
    enabled: query.trim().length > 1,
    staleTime: Infinity,
  })
}
