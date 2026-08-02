import { useMutation, useQuery } from '@tanstack/react-query'

import { API_BASE, apiFetch } from '@/api/client'
import type { ArtifactCompare, ArtifactRead, ExecPlanRead, ExecResultRead } from '@/api/types'

/** Artifacts: files an attempt produced (PRD F6). */

export function useItemArtifacts(itemId: number | undefined) {
  return useQuery({
    queryKey: ['items', itemId, 'artifacts'],
    queryFn: () => apiFetch<ArtifactRead[]>(`/items/${itemId}/artifacts`),
    enabled: itemId !== undefined && Number.isFinite(itemId),
  })
}

export function artifactContentUrl(artifactId: number, download = false): string {
  return `${API_BASE}/artifacts/${artifactId}/content${download ? '?download=true' : ''}`
}

/**
 * An artifact's text.
 *
 * Fetched raw rather than through `apiFetch`, which parses JSON — an artifact is
 * a file, and its bytes are the answer. The server pins the response to inert
 * text/plain whatever the file really is (D-028).
 */
export function useArtifactContent(artifactId: number | undefined) {
  return useQuery({
    queryKey: ['artifacts', artifactId, 'content'],
    queryFn: async () => {
      const response = await fetch(artifactContentUrl(artifactId as number))
      if (!response.ok) throw new Error(`could not read artifact (${response.status})`)
      return response.text()
    },
    enabled: artifactId !== undefined && Number.isFinite(artifactId),
    // File content is immutable once written — an attempt never rewrites one.
    staleTime: Infinity,
  })
}

/** Two to four items' artifacts, side by side (PRD F6.5). */
export function useArtifactCompare(itemIds: number[]) {
  return useQuery({
    queryKey: ['artifacts', 'compare', itemIds],
    queryFn: () =>
      apiFetch<ArtifactCompare>('/artifacts/compare', {
        query: { item_id: itemIds.map(String) },
      }),
    enabled: itemIds.length >= 2 && itemIds.length <= 4,
  })
}

/**
 * The two-step run handshake (PRD F6.4).
 *
 * The plan is fetched first so the user sees the exact command; its token
 * authorises that command and nothing else. Never call `exec` without having
 * shown the plan — the handshake *is* the safety property.
 */
export function useExecPlan(artifactId: number | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ['artifacts', artifactId, 'exec-plan'],
    queryFn: () => apiFetch<ExecPlanRead>(`/artifacts/${artifactId}/exec-plan`),
    enabled: enabled && artifactId !== undefined,
    retry: false,
  })
}

export function useExecArtifact() {
  return useMutation({
    mutationFn: ({ artifactId, token }: { artifactId: number; token: string }) =>
      apiFetch<ExecResultRead>(`/artifacts/${artifactId}/exec`, {
        method: 'POST',
        body: { confirm_token: token },
      }),
  })
}
