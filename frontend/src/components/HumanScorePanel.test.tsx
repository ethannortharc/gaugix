import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { HumanScorePanel } from '@/components/HumanScorePanel'
import { renderWithProviders } from '@/test/utils'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const OK = {
  ok: true,
  verdict: false,
  score_value: 20,
  needs_human: false,
  status: 'failed',
  disagreed_with_machine: false,
}

function lastBody() {
  const call = vi.mocked(fetch).mock.calls.at(-1)
  return JSON.parse(String((call?.[1] as RequestInit).body))
}

describe('HumanScorePanel', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async () => jsonResponse(OK)),
    )
  })

  it('shows the scorer instructions when the case supplies them', () => {
    renderWithProviders(
      <HumanScorePanel
        itemId={1}
        scorerIndex={0}
        spec={{
          type: 'human',
          params: { instructions: 'Does this read like a native speaker?' },
          required: true,
          weight: 1,
        }}
      />,
    )
    expect(screen.getByText('Does this read like a native speaker?')).toBeInTheDocument()
  })

  it('falls back to explaining what the panel is for', () => {
    renderWithProviders(<HumanScorePanel itemId={1} scorerIndex={0} />)
    expect(screen.getByText(/overrides the machine/i)).toBeInTheDocument()
  })

  it('submits a pass', async () => {
    const user = userEvent.setup()
    renderWithProviders(<HumanScorePanel itemId={7} scorerIndex={2} />)

    await user.click(screen.getByRole('button', { name: /pass/i }))
    await waitFor(() => expect(fetch).toHaveBeenCalled())

    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).toContain('/items/7/human-score')
    expect(lastBody()).toMatchObject({ scorer_index: 2, passed: true })
  })

  it('submits a fail with a note', async () => {
    const user = userEvent.setup()
    renderWithProviders(<HumanScorePanel itemId={7} scorerIndex={0} />)

    await user.type(screen.getByLabelText('Note'), 'stilted phrasing')
    await user.click(screen.getByRole('button', { name: /fail/i }))

    await waitFor(() =>
      expect(lastBody()).toMatchObject({ passed: false, note: 'stilted phrasing' }),
    )
  })

  it('sends a numeric score alongside the verdict', async () => {
    const user = userEvent.setup()
    renderWithProviders(<HumanScorePanel itemId={7} scorerIndex={0} />)

    await user.type(screen.getByLabelText(/score/i), '42')
    await user.click(screen.getByRole('button', { name: /pass/i }))

    await waitFor(() => expect(lastBody()).toMatchObject({ passed: true, value: 42 }))
  })

  it('supports the p and f keyboard shortcuts', async () => {
    const user = userEvent.setup()
    renderWithProviders(<HumanScorePanel itemId={7} scorerIndex={0} />)

    await user.keyboard('p')
    await waitFor(() => expect(lastBody()).toMatchObject({ passed: true }))

    await user.keyboard('f')
    await waitFor(() => expect(lastBody()).toMatchObject({ passed: false }))
  })

  it('does not fire the shortcut while typing a note', async () => {
    const user = userEvent.setup()
    renderWithProviders(<HumanScorePanel itemId={7} scorerIndex={0} />)

    await user.type(screen.getByLabelText('Note'), 'pff')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('offers a score-only submit once a number is entered', async () => {
    const user = userEvent.setup()
    renderWithProviders(<HumanScorePanel itemId={7} scorerIndex={0} />)

    expect(screen.queryByRole('button', { name: /submit score only/i })).not.toBeInTheDocument()
    await user.type(screen.getByLabelText(/score/i), '55')

    await user.click(screen.getByRole('button', { name: /submit score only/i }))
    await waitFor(() => expect(lastBody()).toMatchObject({ passed: null, value: 55 }))
  })

  it('calls back when a score lands, so a queue can advance', async () => {
    const user = userEvent.setup()
    const onDone = vi.fn()
    renderWithProviders(<HumanScorePanel itemId={7} scorerIndex={0} onDone={onDone} />)

    await user.click(screen.getByRole('button', { name: /pass/i }))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
  })
})
