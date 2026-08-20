import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PlaygroundPage from '@/pages/Playground'
import { renderWithProviders } from '@/test/utils'

function response(body: unknown, total?: number) {
  return new Response(JSON.stringify(body), {
    headers: {
      'Content-Type': 'application/json',
      ...(total === undefined ? {} : { 'X-Total-Count': String(total) }),
    },
  })
}

const EXECUTOR = {
  id: 1,
  name: 'subject @ fake',
  model_profile_id: 1,
  harness_profile_id: 1,
  model_name: 'subject',
  model_id: 'subject',
  provider: 'fake',
  harness_name: 'fake',
  harness_kind: 'fake',
  overrides: {},
  archived: false,
  run_count: 0,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
}

describe('PlaygroundPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.includes('/executors')) return response([EXECUTOR], 1)
        if (url.includes('/model-capabilities')) {
          return response({
            model_id: 'subject',
            known: true,
            supported: [],
            reasoning_effort: false,
            temperature: true,
            max_tokens: true,
            thinking: false,
            effort_levels: [],
          })
        }
        if (url.includes('/sets')) return response([], 0)
        if (url.includes('/playground/invoke')) {
          const request = JSON.parse(String(init?.body))
          return response({
            ok: true,
            executor_key: 'subject @ fake',
            output_text: '{"verdict":"blocked"}',
            parsed_output: { verdict: 'blocked' },
            messages: [...request.messages, { role: 'assistant', content: 'Blocked by policy' }],
            usage: {
              prompt_tokens: 4,
              completion_tokens: 3,
              cost_usd: 0,
              latency_ms: 8,
            },
            raw: { harness: 'fake' },
            artifacts: [],
            error: null,
            error_kind: null,
          })
        }
        if (url.includes('/cases') && init?.method === 'POST') {
          return response({ id: 12, title: 'manual check' })
        }
        return new Response('{}', { status: 404 })
      }),
    )
  })

  it('supports a manual chat, structured inspection and promotion to a case', async () => {
    const user = userEvent.setup()
    renderWithProviders(<PlaygroundPage />)

    const composer = await screen.findByLabelText('Playground message')
    await user.type(composer, 'Should this be blocked?')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Blocked by policy')).toBeInTheDocument()
    expect(screen.getByText('{"verdict":"blocked"}')).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'JSON' }))
    expect(screen.getByText(/"verdict": "blocked"/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Save as case' }))
    const title = screen.getByLabelText('Case title')
    await user.clear(title)
    await user.type(title, 'manual check')
    await user.click(screen.getByRole('button', { name: 'Save case' }))

    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining('/cases'),
        expect.objectContaining({ method: 'POST' }),
      ),
    )
  })
})
