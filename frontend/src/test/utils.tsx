import { QueryClient } from '@tanstack/react-query'
import { render, type RenderOptions } from '@testing-library/react'
import * as React from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'

import { AppProviders } from '@/app/providers'

/** Query client with retries and caching off — tests should be deterministic. */
export function testQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  })
}

/** Render inside the app's providers, with a memory router at `route`. */
export function renderWithProviders(
  ui: React.ReactElement,
  { route = '/', ...options }: RenderOptions & { route?: string } = {},
) {
  const router = createMemoryRouter([{ path: '*', element: ui }], { initialEntries: [route] })
  return render(
    <AppProviders client={testQueryClient()}>
      <RouterProvider router={router} />
    </AppProviders>,
    options,
  )
}

/** Render a full route tree (used to exercise the shell + navigation). */
export function renderRoutes(
  routes: Parameters<typeof createMemoryRouter>[0],
  { route = '/' }: { route?: string } = {},
) {
  const router = createMemoryRouter(routes, { initialEntries: [route] })
  return render(
    <AppProviders client={testQueryClient()}>
      <RouterProvider router={router} />
    </AppProviders>,
  )
}

/** Stub `fetch` with a map of path → JSON response. */
export function mockFetch(routes: Record<string, unknown>, status = 200) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    const key = Object.keys(routes).find((k) => url.startsWith(k))
    if (key === undefined) {
      return new Response(JSON.stringify({ error: { code: 'not_found', message: url } }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    return new Response(JSON.stringify(routes[key]), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
}
