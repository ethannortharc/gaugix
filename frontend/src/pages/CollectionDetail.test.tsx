import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { STANDARD_EVALUATION_PROFILE, type EvalCollection, type EvalSet } from '@/api/types'
import CollectionDetailPage from '@/pages/CollectionDetail'
import { renderRoutes } from '@/test/utils'

const ROOT: EvalCollection = {
  id: 1,
  key: 'standards',
  name: 'Standards',
  description: 'International frameworks',
  parent_id: null,
  position: 0,
  visibility: 'primary',
  tags: [],
  provenance: { source_url: 'https://example.com/standards' },
  path: ['Standards'],
  depth: 0,
  direct_set_count: 0,
  descendant_set_count: 2,
  direct_case_count: 0,
  descendant_case_count: 9,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
}

const CHILD: EvalCollection = {
  ...ROOT,
  id: 2,
  key: 'standards.owasp',
  name: 'OWASP',
  description: 'OWASP mappings',
  parent_id: 1,
  path: ['Standards', 'OWASP'],
  depth: 1,
  direct_set_count: 2,
  direct_case_count: 9,
}

function evalSet(id: number, variant: 'input' | 'output'): EvalSet {
  return {
    id,
    name: `owasp-runtime-${variant}`,
    description: `${variant} checks`,
    tags: [],
    default_scoring: [],
    evaluation_profile: STANDARD_EVALUATION_PROFILE,
    collection_id: 2,
    collection_key: 'standards.owasp',
    collection_path: ['Standards', 'OWASP'],
    logical_key: 'owasp-runtime',
    variant,
    visibility: 'primary',
    case_count: id === 10 ? 4 : 5,
    deleted_at: null,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    provenance: {},
  }
}

describe('CollectionDetailPage', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))

  it('groups physical set variants under one logical set and keeps source context', async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input)
      const body = url.includes('/collections/1')
        ? ROOT
        : url.includes('/collections')
          ? [ROOT, CHILD]
          : url.includes('/sets?')
            ? [evalSet(10, 'input'), evalSet(11, 'output')]
            : {}
      return new Response(JSON.stringify(body), {
        headers: { 'Content-Type': 'application/json', 'X-Total-Count': '2' },
      })
    })

    renderRoutes([{ path: '/collections/:id', element: <CollectionDetailPage /> }], {
      route: '/collections/1',
    })

    expect(await screen.findByText('owasp-runtime')).toBeInTheDocument()
    expect(screen.getByText('2 variants')).toBeInTheDocument()
    expect(screen.getAllByText('9 cases').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByRole('link', { name: /official source/i })).toHaveAttribute(
      'href',
      'https://example.com/standards',
    )
  })

  it('renders a single physical set once without a redundant logical wrapper', async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input)
      const body = url.includes('/collections/1')
        ? ROOT
        : url.includes('/collections')
          ? [ROOT, CHILD]
          : url.includes('/sets?')
            ? [evalSet(10, 'input')]
            : {}
      return new Response(JSON.stringify(body), {
        headers: { 'Content-Type': 'application/json', 'X-Total-Count': '1' },
      })
    })

    renderRoutes([{ path: '/collections/:id', element: <CollectionDetailPage /> }], {
      route: '/collections/1',
    })

    expect(await screen.findByText('owasp-runtime')).toBeInTheDocument()
    expect(screen.getAllByText('owasp-runtime')).toHaveLength(1)
    expect(screen.queryByText(/variants$/)).not.toBeInTheDocument()
  })
})
