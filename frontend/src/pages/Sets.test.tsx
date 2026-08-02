import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { EvalSet } from '@/api/types'
import SetsPage from '@/pages/Sets'
import { renderWithProviders } from '@/test/utils'

function makeSet(overrides: Partial<EvalSet> = {}): EvalSet {
  return {
    id: 1,
    name: 'Guardrail regression',
    description: 'Jailbreaks and benign lookalikes',
    tags: ['guardrail'],
    default_scoring: [],
    case_count: 5,
    deleted_at: null,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    // Empty is the shape a hand-made set has; benchmark installs fill it.
    provenance: {},
    ...overrides,
  }
}

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json', 'X-Total-Count': '1' },
    ...init,
  })
}

describe('SetsPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it('shows a loading state first', () => {
    vi.mocked(fetch).mockReturnValue(new Promise(() => {}))
    renderWithProviders(<SetsPage />)
    expect(screen.getByRole('status')).toHaveTextContent(/loading sets/i)
  })

  it('renders sets with their case counts and tags', async () => {
    vi.mocked(fetch).mockImplementation(async () => jsonResponse([makeSet()]))
    renderWithProviders(<SetsPage />)

    expect(await screen.findByText('Guardrail regression')).toBeInTheDocument()
    expect(screen.getByText('5 cases')).toBeInTheDocument()
    expect(screen.getByText('guardrail')).toBeInTheDocument()
  })

  it('uses the singular form for a set with one case', async () => {
    vi.mocked(fetch).mockImplementation(async () => jsonResponse([makeSet({ case_count: 1 })]))
    renderWithProviders(<SetsPage />)
    expect(await screen.findByText('1 case')).toBeInTheDocument()
  })

  it('teaches what a set is when there are none', async () => {
    vi.mocked(fetch).mockImplementation(async () => jsonResponse([]))
    renderWithProviders(<SetsPage />)

    expect(await screen.findByText('No eval sets yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create your first set/i })).toBeInTheDocument()
  })

  it('surfaces a backend error with a retry', async () => {
    vi.mocked(fetch).mockImplementation(async () =>
      jsonResponse(
        { error: { code: 'internal_error', message: 'database is locked' } },
        { status: 500 },
      ),
    )
    renderWithProviders(<SetsPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('database is locked')
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('searches by name', async () => {
    const user = userEvent.setup()
    vi.mocked(fetch).mockImplementation(async () => jsonResponse([makeSet()]))
    renderWithProviders(<SetsPage />)
    await screen.findByText('Guardrail regression')

    await user.type(screen.getByLabelText('Search sets'), 'jail')
    await waitFor(() => {
      const urls = vi.mocked(fetch).mock.calls.map((c) => String(c[0]))
      expect(urls.some((u) => u.includes('q=jail'))).toBe(true)
    })
  })

  it('switches to the trash view', async () => {
    const user = userEvent.setup()
    vi.mocked(fetch).mockImplementation(async () => jsonResponse([]))
    renderWithProviders(<SetsPage />)
    await screen.findByText('No eval sets yet')

    await user.click(screen.getByRole('tab', { name: 'Trash' }))
    expect(await screen.findByText('Trash is empty')).toBeInTheDocument()
    const urls = vi.mocked(fetch).mock.calls.map((c) => String(c[0]))
    expect(urls.some((u) => u.includes('trashed=true'))).toBe(true)
  })

  it('creates a set through the dialog', async () => {
    const user = userEvent.setup()
    vi.mocked(fetch).mockImplementation(async (_input, init) => {
      if (init?.method === 'POST')
        return jsonResponse(makeSet({ name: 'New set' }), { status: 201 })
      return jsonResponse([])
    })
    renderWithProviders(<SetsPage />)
    await screen.findByText('No eval sets yet')

    await user.click(screen.getByRole('button', { name: /^new set$/i }))
    await user.type(await screen.findByLabelText('Name'), 'New set')
    await user.click(screen.getByRole('button', { name: /create set/i }))

    await waitFor(() => {
      const post = vi.mocked(fetch).mock.calls.find((c) => (c[1] as RequestInit)?.method === 'POST')
      expect(post).toBeDefined()
      expect(JSON.parse(String((post![1] as RequestInit).body))).toMatchObject({ name: 'New set' })
    })
  })

  it('will not submit an empty set name', async () => {
    const user = userEvent.setup()
    vi.mocked(fetch).mockImplementation(async () => jsonResponse([]))
    renderWithProviders(<SetsPage />)
    await screen.findByText('No eval sets yet')

    await user.click(screen.getByRole('button', { name: /^new set$/i }))
    expect(await screen.findByRole('button', { name: /create set/i })).toBeDisabled()
  })
})
