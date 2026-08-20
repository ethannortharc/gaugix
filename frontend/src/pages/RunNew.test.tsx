import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { STANDARD_EVALUATION_PROFILE, type EvalSet } from '@/api/types'
import RunNewPage from '@/pages/RunNew'
import { renderWithProviders } from '@/test/utils'

function makeSet(id: number): EvalSet {
  return {
    id,
    name: id === 501 ? 'Beyond the picker cap' : `Set ${id}`,
    description: null,
    tags: [],
    default_scoring: [],
    evaluation_profile: STANDARD_EVALUATION_PROFILE,
    collection_id: null,
    collection_key: null,
    collection_path: [],
    logical_key: null,
    variant: null,
    visibility: 'primary',
    case_count: 1,
    deleted_at: null,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    provenance: {},
  }
}

function response(body: unknown, total?: number, status = 200) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (total !== undefined) headers['X-Total-Count'] = String(total)
  return new Response(JSON.stringify(body), { status, headers })
}

const EXECUTOR = {
  id: 1,
  name: 'subject @ fake',
  provider: 'fake',
  model_profile_id: 1,
  harness_profile_id: 1,
  overrides: {},
  archived: false,
}

describe('RunNewPage', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))

  it('shows and checks a URL-preset set outside the 500-row picker response', async () => {
    const listed = Array.from({ length: 500 }, (_, index) => makeSet(index + 1))
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/sets/501')) return response(makeSet(501))
      if (url.includes('/sets?') && url.includes('limit=500')) return response(listed, 501)
      if (url.includes('/executors')) return response([EXECUTOR], 1)
      return new Response('{}', { status: 404 })
    })

    renderWithProviders(<RunNewPage />, { route: '/runs/new?set_id=501' })

    expect(await screen.findByText('Beyond the picker cap')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Select set Beyond the picker cap' })).toBeChecked()
    expect(screen.queryByText(/not listed here/i)).not.toBeInTheDocument()
  })

  it('keeps the builder usable when a bookmarked preset set was purged', async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/sets/999'))
        return response(
          { error: { code: 'not_found', message: 'Set 999 not found' } },
          undefined,
          404,
        )
      if (url.includes('/sets?')) return response([makeSet(1)], 1)
      if (url.includes('/executors')) return response([EXECUTOR], 1)
      return new Response('{}', { status: 404 })
    })

    renderWithProviders(<RunNewPage />, { route: '/runs/new?set_id=999' })

    expect(await screen.findByText('New run')).toBeInTheDocument()
    expect(screen.getByText('Set 1')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(
      /set from this link is no longer available/i,
    )
    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
  })

  it('does not merge a trashed preset set into the live picker', async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/sets/501'))
        return response({ ...makeSet(501), deleted_at: '2026-08-01T01:00:00Z' })
      if (url.includes('/sets?')) return response([makeSet(1)], 1)
      if (url.includes('/executors')) return response([EXECUTOR], 1)
      return new Response('{}', { status: 404 })
    })

    renderWithProviders(<RunNewPage />, { route: '/runs/new?set_id=501' })

    expect(await screen.findByText('Set 1')).toBeInTheDocument()
    expect(screen.queryByText('Beyond the picker cap')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(
      /set from this link is no longer available/i,
    )
  })
})
