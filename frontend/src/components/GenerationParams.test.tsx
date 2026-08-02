import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AppProviders } from '@/app/providers'
import { GenerationParams, ParamsSummary } from '@/components/GenerationParams'
import { mockFetch, testQueryClient } from '@/test/utils'

function stubCapabilities(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    'fetch',
    mockFetch({
      '/api/v1/model-capabilities': {
        model_id: 'o3-mini',
        known: true,
        supported: ['reasoning_effort', 'max_tokens'],
        reasoning_effort: true,
        temperature: false,
        max_tokens: true,
        thinking: false,
        effort_levels: ['low', 'medium', 'high'],
        ...overrides,
      },
    }),
  )
}

beforeEach(() => stubCapabilities())

function Harness({ initial = {} as Record<string, unknown> }) {
  const [value, setValue] = React.useState(initial)
  return (
    <AppProviders client={testQueryClient()}>
      <GenerationParams
        provider="openai"
        modelId="o3-mini"
        value={value}
        onChange={setValue}
        idPrefix="t"
      />
      <output data-testid="state">{JSON.stringify(value)}</output>
    </AppProviders>
  )
}

function state() {
  return JSON.parse(screen.getByTestId('state').textContent || '{}')
}

describe('GenerationParams', () => {
  it('offers reasoning effort for a reasoning model', async () => {
    render(<Harness />)
    expect(await screen.findByLabelText('Reasoning effort')).toBeInTheDocument()
  })

  it('hides a control the model would reject', async () => {
    render(<Harness />)
    // Controls are permissive until the capabilities land, so wait for the
    // unsupported one to disappear rather than checking the first paint.
    await waitFor(() => expect(screen.queryByLabelText('Temperature')).not.toBeInTheDocument())
    expect(screen.getByLabelText('Reasoning effort')).toBeInTheDocument()
    expect(screen.getByLabelText('Max tokens')).toBeInTheDocument()
  })

  it('explains why reasoning effort is missing on a non-reasoning model', async () => {
    stubCapabilities({ reasoning_effort: false, temperature: true })
    render(<Harness />)
    expect(await screen.findByText(/not a reasoning model/i)).toBeInTheDocument()
  })

  it('offers every control when litellm does not know the model', async () => {
    stubCapabilities({ known: false, reasoning_effort: true, temperature: true })
    render(<Harness />)
    // Wait for the "unknown model" note, which only appears once data lands.
    expect(await screen.findByText(/does not recognise/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Reasoning effort')).toBeInTheDocument()
    expect(screen.getByLabelText('Temperature')).toBeInTheDocument()
  })

  it('writes a number param as a number, not a string', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.type(await screen.findByLabelText('Max tokens'), '512')
    expect(state().max_tokens).toBe(512)
  })

  it('clearing a field removes the key rather than sending an empty value', async () => {
    const user = userEvent.setup()
    render(<Harness initial={{ max_tokens: 512 }} />)
    await user.clear(await screen.findByLabelText('Max tokens'))
    expect('max_tokens' in state()).toBe(false)
  })

  it('the JSON escape hatch edits the same object', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const json = await screen.findByLabelText('Generation params JSON')
    await user.clear(json)
    await user.type(json, '{{"top_p": 0.9}')
    expect(state().top_p).toBe(0.9)
  })

  it('invalid JSON is flagged and never reaches the parent', async () => {
    const user = userEvent.setup()
    render(<Harness initial={{ max_tokens: 512 }} />)
    const json = await screen.findByLabelText('Generation params JSON')
    // Append garbage rather than clearing: an empty box legitimately means
    // "no params", so clearing first would test the wrong thing.
    await user.type(json, ' broken')
    expect(await screen.findByTestId('params-error')).toBeInTheDocument()
    expect(state()).toEqual({ max_tokens: 512 })
  })

  it('emptying the box means no params, which is valid', async () => {
    const user = userEvent.setup()
    render(<Harness initial={{ max_tokens: 512 }} />)
    await user.clear(await screen.findByLabelText('Generation params JSON'))
    expect(state()).toEqual({})
    expect(screen.queryByTestId('params-error')).not.toBeInTheDocument()
  })

  it('a JSON array is refused — params must be an object', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const json = await screen.findByLabelText('Generation params JSON')
    await user.clear(json)
    // `[[` is userEvent's escape for a literal bracket.
    await user.type(json, '[[1, 2]')
    expect(await screen.findByTestId('params-error')).toHaveTextContent('object')
  })
})

describe('ParamsSummary', () => {
  it('renders nothing when there is nothing to say', () => {
    const { container } = render(<ParamsSummary params={{}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('lists each override so two executors on one model are distinguishable', () => {
    render(<ParamsSummary params={{ reasoning_effort: 'high', max_tokens: 512 }} />)
    expect(screen.getByText(/reasoning_effort=high/)).toBeInTheDocument()
    expect(screen.getByText(/max_tokens=512/)).toBeInTheDocument()
  })
})
