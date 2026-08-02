import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ConfirmDialog } from '@/components/ConfirmDialog'

describe('ConfirmDialog', () => {
  it('lists what will be destroyed, skipping the entries that do not apply', () => {
    render(
      <ConfirmDialog
        open
        onOpenChange={() => {}}
        title="Delete this run?"
        impact={['412 run items', null, false, '9 saved artifacts']}
        onConfirm={() => {}}
      />,
    )

    expect(screen.getByText('412 run items')).toBeInTheDocument()
    expect(screen.getByText('9 saved artifacts')).toBeInTheDocument()
  })

  it('confirms on one click when no name is required', async () => {
    const onConfirm = vi.fn()
    const user = userEvent.setup()
    render(<ConfirmDialog open onOpenChange={() => {}} title="Purge?" onConfirm={onConfirm} />)

    await user.click(screen.getByRole('button', { name: /delete permanently/i }))

    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('stays locked until the exact name is typed', async () => {
    const onConfirm = vi.fn()
    const user = userEvent.setup()
    render(
      <ConfirmDialog
        open
        onOpenChange={() => {}}
        title="Delete this run?"
        confirmText="Nightly regression"
        onConfirm={onConfirm}
      />,
    )

    const button = screen.getByRole('button', { name: /delete permanently/i })
    expect(button).toBeDisabled()

    // A near-miss must not unlock it — that is the whole point of typing it.
    await user.type(screen.getByLabelText(/type/i), 'Nightly regressio')
    expect(button).toBeDisabled()

    await user.type(screen.getByLabelText(/type/i), 'n')
    expect(button).toBeEnabled()

    await user.click(button)
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('forgets what was typed when reopened', async () => {
    const user = userEvent.setup()
    const { rerender } = render(
      <ConfirmDialog
        open
        onOpenChange={() => {}}
        title="Delete?"
        confirmText="thing"
        onConfirm={() => {}}
      />,
    )
    await user.type(screen.getByLabelText(/type/i), 'thing')
    expect(screen.getByRole('button', { name: /delete permanently/i })).toBeEnabled()

    rerender(
      <ConfirmDialog
        open={false}
        onOpenChange={() => {}}
        title="Delete?"
        confirmText="thing"
        onConfirm={() => {}}
      />,
    )
    rerender(
      <ConfirmDialog
        open
        onOpenChange={() => {}}
        title="Delete?"
        confirmText="thing"
        onConfirm={() => {}}
      />,
    )

    expect(screen.getByRole('button', { name: /delete permanently/i })).toBeDisabled()
  })
})
