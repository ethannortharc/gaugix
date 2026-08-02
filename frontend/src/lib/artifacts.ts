import type { ArtifactRead } from '@/api/types'

/**
 * Renderer selection for artifacts (PRD F6.2).
 *
 * Separate from `components/ArtifactViewer` so that file exports only
 * components — mixing the two breaks Fast Refresh, and the lint rule enforces it.
 */

export type Renderer = 'text' | 'markdown' | 'html' | 'image'

export const RENDERERS: Renderer[] = ['text', 'markdown', 'html', 'image']

/** What this file most likely wants to be shown as. */
export function defaultRenderer(artifact: ArtifactRead): Renderer {
  if (artifact.mime.startsWith('image/')) return 'image'
  if (artifact.mime === 'text/html') return 'html'
  if (artifact.mime === 'text/markdown') return 'markdown'
  return 'text'
}
