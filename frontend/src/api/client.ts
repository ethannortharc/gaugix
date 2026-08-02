/**
 * Thin fetch wrapper over the Gaugix API.
 *
 * Every backend failure arrives as `{"error": {code, message, details?}}`
 * (ARCHITECTURE §7), so unwrapping it once here means every caller — and every
 * error boundary — gets a real message instead of "Failed to fetch".
 */

export const API_BASE = '/api/v1'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details?: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  /** Serialized as JSON unless it is already a FormData/string body. */
  body?: unknown
  /** Appended as a query string, skipping null/undefined values. */
  query?: Record<string, string | number | boolean | undefined | null | string[]>
}

export function buildQuery(query: RequestOptions['query']): string {
  if (!query) return ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      for (const v of value) params.append(key, String(v))
    } else {
      params.append(key, String(value))
    }
  }
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = 'http_error'
  let message = `${response.status} ${response.statusText}`
  let details: unknown
  try {
    const payload = await response.json()
    if (payload?.error) {
      code = payload.error.code ?? code
      message = payload.error.message ?? message
      details = payload.error.details
    }
  } catch {
    // non-JSON body (proxy error page, empty response) — keep the status text
  }
  return new ApiError(response.status, code, message, details)
}

/** Perform a request and parse the JSON body, or throw {@link ApiError}. */
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, query, headers, ...rest } = options
  const isForm = body instanceof FormData
  const init: RequestInit = {
    ...rest,
    headers: {
      ...(isForm ? {} : { 'Content-Type': 'application/json' }),
      ...(headers as Record<string, string> | undefined),
    },
  }
  if (body !== undefined) {
    init.body = isForm || typeof body === 'string' ? (body as BodyInit) : JSON.stringify(body)
  }

  const response = await fetch(`${API_BASE}${path}${buildQuery(query)}`, init)
  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

/** Like {@link apiFetch} but also surfaces the `X-Total-Count` pagination header. */
export async function apiFetchList<T>(
  path: string,
  options: RequestOptions = {},
): Promise<{ items: T[]; total: number }> {
  const { body, query, headers, ...rest } = options
  const response = await fetch(`${API_BASE}${path}${buildQuery(query)}`, {
    ...rest,
    headers: { 'Content-Type': 'application/json', ...(headers as Record<string, string>) },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
  if (!response.ok) throw await toApiError(response)
  const payload = await response.json()
  // Defensive: a proxy error page or a mis-shaped response should surface as an
  // empty list, not a crash inside whichever component called .map on it.
  const items: T[] = Array.isArray(payload) ? (payload as T[]) : []
  const header = response.headers.get('X-Total-Count')
  return { items, total: header ? Number(header) : items.length }
}

/** Health lives outside /api/v1. */
export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch('/api/health')
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as HealthResponse
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  version: string
  db: string
  data_dir: string
}
