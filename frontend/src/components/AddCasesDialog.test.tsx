import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { EvalSetNode } from '@/api/types'
import { AddCasesDialog } from '@/components/AddCasesDialog'

const NODE: EvalSetNode = {
  id: 7,
  set_id: 3,
  parent_id: null,
  name: 'Chinese',
  description: 'Chinese-language cases',
  position: 0,
  tags: [],
  provenance: {},
  effective_provenance: {},
  path: ['Language', 'Chinese'],
  depth: 1,
  direct_case_count: 4,
  descendant_case_count: 4,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
}

describe('AddCasesDialog', () => {
  it('keeps the selected set branch when choosing a batch method', async () => {
    const onChoose = vi.fn()
    const user = userEvent.setup()
    render(
      <AddCasesDialog
        open
        onOpenChange={() => {}}
        setName="Guardrail regression"
        nodes={[NODE]}
        defaultNodeId={NODE.id}
        onChoose={onChoose}
      />,
    )

    expect(screen.getByText('Guardrail regression')).toBeInTheDocument()
    expect(screen.getByText('Language / Chinese')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /import a batch/i }))

    expect(onChoose).toHaveBeenCalledWith('import', NODE.id)
  })

  it('explains that library-level additions remain unfiled', () => {
    render(<AddCasesDialog open onOpenChange={() => {}} onChoose={() => {}} />)

    expect(screen.getByText(/remain in the case library/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /write one case/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /generate with ai/i })).toBeInTheDocument()
  })
})
