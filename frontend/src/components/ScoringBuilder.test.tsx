import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Executor, ScorerSpec } from '@/api/types'
import { AppProviders } from '@/app/providers'
import { ScoringBuilder, ScoringSummary } from '@/components/ScoringBuilder'
import { TooltipProvider } from '@/components/ui/misc'
import { DEFAULT_PARAMS, newScorer } from '@/lib/scorers'
import { mockFetch, testQueryClient } from '@/test/utils'

/** The judge form reads the executor list and the default judge from the API. */
function stubApi({ defaultJudge = null as number | null } = {}) {
  const executor = { id: 7, name: 'gpt-4o-mini', model_id: 'gpt-4o-mini' } as Executor
  vi.stubGlobal(
    'fetch',
    mockFetch({
      '/api/v1/executors': { items: [executor], total: 1 },
      '/api/v1/settings': { pricing: [], default_judge_executor_id: defaultJudge },
    }),
  )
}

beforeEach(() => stubApi())

function Harness({ initial = [] as ScorerSpec[] }) {
  const [value, setValue] = React.useState<ScorerSpec[]>(initial)
  return (
    <AppProviders client={testQueryClient()}>
      <MemoryRouter>
        <ScoringBuilder value={value} onChange={setValue} />
        <output data-testid="state">{JSON.stringify(value)}</output>
      </MemoryRouter>
    </AppProviders>
  )
}

function state() {
  return JSON.parse(screen.getByTestId('state').textContent || '[]') as ScorerSpec[]
}

describe('newScorer', () => {
  it('starts required with weight 1', () => {
    const scorer = newScorer()
    expect(scorer).toMatchObject({ type: 'contains', required: true, weight: 1 })
  })

  it('has sensible defaults for every scorer type', () => {
    for (const type of Object.keys(DEFAULT_PARAMS) as (keyof typeof DEFAULT_PARAMS)[]) {
      expect(DEFAULT_PARAMS[type]).toBeDefined()
    }
    expect(DEFAULT_PARAMS.regex).toEqual({ pattern: '', should_match: true })
    expect(DEFAULT_PARAMS.llm_judge).toMatchObject({ scale: '1-5', pass_threshold: 4 })
  })

  it('does not share param objects between scorers', () => {
    const a = newScorer('regex')
    const b = newScorer('regex')
    a.params.pattern = 'changed'
    expect(b.params.pattern).toBe('')
  })
})

describe('ScoringBuilder', () => {
  it('explains inheritance when there are no scorers', () => {
    render(<Harness />)
    expect(screen.getByText(/inherits its set/i)).toBeInTheDocument()
  })

  it('adds a scorer', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: /add scorer/i }))
    expect(state()).toHaveLength(1)
    expect(state()[0].type).toBe('contains')
  })

  it('edits the text of a contains scorer', async () => {
    const user = userEvent.setup()
    render(<Harness initial={[newScorer('contains')]} />)
    await user.type(screen.getByLabelText('Text'), 'block')
    expect(state()[0].params.text).toBe('block')
  })

  it('toggles required off', async () => {
    const user = userEvent.setup()
    render(<Harness initial={[newScorer()]} />)
    await user.click(screen.getByLabelText('Scorer 1 required'))
    expect(state()[0].required).toBe(false)
  })

  it('removes a scorer', async () => {
    const user = userEvent.setup()
    render(<Harness initial={[newScorer('contains'), newScorer('regex')]} />)
    await user.click(screen.getByLabelText('Remove scorer 1'))
    expect(state()).toHaveLength(1)
    expect(state()[0].type).toBe('regex')
  })

  it('shows the regex fields for a regex scorer', () => {
    render(<Harness initial={[newScorer('regex')]} />)
    expect(screen.getByLabelText(/pattern/i)).toBeInTheDocument()
    expect(screen.getByText(/must match/i)).toBeInTheDocument()
  })

  it('shows rubric and threshold fields for a judge scorer', () => {
    render(<Harness initial={[newScorer('llm_judge')]} />)
    expect(screen.getByLabelText('Rubric')).toBeInTheDocument()
    expect(screen.getByLabelText('Pass threshold')).toHaveValue(4)
  })

  it('offers a judge model for a judge scorer', () => {
    render(<Harness initial={[newScorer('llm_judge')]} />)
    expect(screen.getByLabelText('Scorer 1 judge model')).toBeInTheDocument()
  })

  it('warns when nothing resolves and the model would grade itself', async () => {
    render(<Harness initial={[newScorer('llm_judge')]} />)
    expect(await screen.findByTestId('self-judge-warning')).toBeInTheDocument()
  })

  it('drops the warning once a judge is named on the scorer', async () => {
    const judge = newScorer('llm_judge')
    judge.params.judge_executor = 7
    render(<Harness initial={[judge]} />)
    await screen.findByLabelText('Scorer 1 judge model')
    // A real judge is configured, so there is nothing to warn about.
    expect(screen.queryByTestId('self-judge-warning')).not.toBeInTheDocument()
  })

  it('drops the warning when a default judge is configured', async () => {
    stubApi({ defaultJudge: 7 })
    render(<Harness initial={[newScorer('llm_judge')]} />)
    await screen.findByLabelText('Scorer 1 judge model')
    expect(screen.queryByTestId('self-judge-warning')).not.toBeInTheDocument()
  })

  it('surfaces invalid JSON in the schema editor instead of corrupting state', async () => {
    const user = userEvent.setup()
    render(<Harness initial={[newScorer('json_schema')]} />)
    const editor = screen.getByLabelText('JSON Schema')
    await user.clear(editor)
    await user.type(editor, '{{ broken')
    expect(await screen.findByTestId('field-error')).toBeInTheDocument()
  })

  it('warns that python scorers execute locally without a sandbox', () => {
    render(<Harness initial={[newScorer('python')]} />)
    // The claim that matters is the negative one: a subprocess with a timeout
    // is not containment, and a user pasting a scorer must be told so.
    expect(screen.getByText(/this is not a sandbox/i)).toBeInTheDocument()
    expect(screen.getAllByText(/separate process/i).length).toBeGreaterThan(0)
    expect(screen.queryByText(/sandboxed subprocess/i)).not.toBeInTheDocument()
  })

  it('states the verdict rule once a scorer exists', () => {
    render(<Harness initial={[newScorer()]} />)
    expect(screen.getByText(/every/i)).toHaveTextContent('required')
  })
})

describe('ScoringSummary', () => {
  it('says "set default" when a case has no scorers of its own', () => {
    render(<ScoringSummary scoring={[]} />)
    expect(screen.getByText('set default')).toBeInTheDocument()
  })

  it('lists each scorer type', () => {
    render(<ScoringSummary scoring={[newScorer('contains'), newScorer('llm_judge')]} />)
    expect(screen.getByText('contains')).toBeInTheDocument()
    expect(screen.getByText('llm_judge')).toBeInTheDocument()
  })
})

describe('onChange contract', () => {
  it('never mutates the array it was given', async () => {
    const user = userEvent.setup()
    const initial = [newScorer()]
    const frozen = JSON.stringify(initial)
    const onChange = vi.fn()
    render(
      <TooltipProvider>
        <MemoryRouter>
          <ScoringBuilder value={initial} onChange={onChange} />
        </MemoryRouter>
      </TooltipProvider>,
    )
    await user.click(screen.getByLabelText('Scorer 1 required'))
    expect(JSON.stringify(initial)).toBe(frozen)
    expect(onChange).toHaveBeenCalled()
  })
})
