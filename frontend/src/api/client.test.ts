import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiFetch, apiFetchList, buildQuery, fetchHealth } from '@/api/client'

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

describe('buildQuery', () => {
  it('skips empty values and expands arrays', () => {
    expect(buildQuery({ a: 1, b: undefined, c: null, d: '', e: ['x', 'y'] })).toBe('?a=1&e=x&e=y')
  })

  it('returns an empty string when there is nothing to send', () => {
    expect(buildQuery(undefined)).toBe('')
    expect(buildQuery({})).toBe('')
  })
})

describe('apiFetch', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it('parses a JSON body', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ id: 7 }))
    await expect(apiFetch<{ id: number }>('/cases/7')).resolves.toEqual({ id: 7 })
    expect(fetch).toHaveBeenCalledWith('/api/v1/cases/7', expect.anything())
  })

  it('unwraps the error envelope into an ApiError', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(
        { error: { code: 'not_found', message: 'Case 7 does not exist', details: { id: 7 } } },
        { status: 404 },
      ),
    )
    const error = (await apiFetch('/cases/7').catch((e) => e)) as ApiError
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(404)
    expect(error.code).toBe('not_found')
    expect(error.message).toBe('Case 7 does not exist')
    expect(error.details).toEqual({ id: 7 })
  })

  it('falls back to the status text when the body is not our envelope', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response('<html>proxy error</html>', { status: 502 }))
    const error = (await apiFetch('/runs').catch((e) => e)) as ApiError
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(502)
    expect(error.code).toBe('http_error')
  })

  it('serialises a JSON body and sets the content type', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ok: true }))
    await apiFetch('/cases', { method: 'POST', body: { title: 'x' } })
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit
    expect(init.body).toBe('{"title":"x"}')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
  })

  it('leaves FormData alone so the browser can set the boundary', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ok: true }))
    const form = new FormData()
    form.append('file', new Blob(['x']), 'cases.jsonl')
    await apiFetch('/cases/import', { method: 'POST', body: form })
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit
    expect(init.body).toBe(form)
    expect((init.headers as Record<string, string>)['Content-Type']).toBeUndefined()
  })

  it('handles 204 responses', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }))
    await expect(apiFetch('/cases/1')).resolves.toBeUndefined()
  })
})

describe('apiFetchList', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it('reads the total from X-Total-Count', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse([{ id: 1 }], { headers: { 'X-Total-Count': '42' } }),
    )
    await expect(apiFetchList('/cases')).resolves.toEqual({ items: [{ id: 1 }], total: 42 })
  })

  it('falls back to the page length when the header is absent', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse([{ id: 1 }, { id: 2 }]))
    await expect(apiFetchList('/cases')).resolves.toEqual({
      items: [{ id: 1 }, { id: 2 }],
      total: 2,
    })
  })
})

describe('fetchHealth', () => {
  it('calls the unversioned health path', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'ok' })))
    await fetchHealth()
    expect(fetch).toHaveBeenCalledWith('/api/health')
  })
})
