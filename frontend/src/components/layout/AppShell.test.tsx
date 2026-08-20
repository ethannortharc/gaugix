import { screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { routes } from '@/app/router'
import { renderRoutes } from '@/test/utils'

function healthResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('AppShell', () => {
  beforeEach(() => {
    // Answer by shape, not one body for every URL: the index route renders the
    // dashboard, which asks for collections. Handing it the health object made
    // the stub, rather than the app, decide whether the page could render.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
        if (String(input).includes('/health')) {
          return healthResponse({ status: 'ok', version: '0.1.0', db: 'ok', data_dir: '/tmp/data' })
        }
        return healthResponse([])
      }),
    )
  })

  it('renders every top-level nav destination', () => {
    renderRoutes(routes)
    for (const label of [
      'Home',
      'Playground',
      'Eval sets',
      'New evaluation',
      'Executors',
      'Runs',
      'Compare',
      'Settings',
    ]) {
      expect(screen.getByRole('link', { name: label })).toBeInTheDocument()
    }
  })

  it('puts the Eval Guide entrance in the footer, not the main nav', () => {
    renderRoutes(routes)
    const guide = screen.getByRole('link', { name: /eval guide/i })
    expect(guide).toBeInTheDocument()
    expect(guide.closest('nav')).toBeNull()
  })

  it('shows the copyright line', () => {
    renderRoutes(routes)
    expect(screen.getByText('© 2026 Ethan H.B. Zhou')).toBeInTheDocument()
  })

  it('reports a healthy backend', async () => {
    renderRoutes(routes)
    await waitFor(() =>
      expect(screen.getByTestId('health-chip')).toHaveAttribute('data-state', 'ok'),
    )
    expect(screen.getByTestId('health-chip')).toHaveTextContent('connected')
  })

  it('reports an unreachable backend instead of failing silently', async () => {
    vi.mocked(fetch).mockImplementation(async () => {
      throw new TypeError('Failed to fetch')
    })
    renderRoutes(routes)
    // The chip retries once before giving up, so allow for the backoff delay.
    await waitFor(
      () => expect(screen.getByTestId('health-chip')).toHaveAttribute('data-state', 'down'),
      { timeout: 4000 },
    )
    expect(screen.getByTestId('health-chip')).toHaveTextContent('offline')
  })

  it('renders home at the index route', () => {
    renderRoutes(routes)
    expect(screen.getByRole('heading', { name: 'Home' })).toBeInTheDocument()
  })

  it('renders a not-found page for unknown routes', () => {
    renderRoutes(routes, { route: '/nope' })
    expect(screen.getByText('No such page')).toBeInTheDocument()
  })
})
