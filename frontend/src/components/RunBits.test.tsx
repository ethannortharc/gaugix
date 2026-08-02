import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { RunTotals } from '@/api/types'
import {
  ItemStatusBadge,
  LaneProgress,
  RunStatusBadge,
  RunTotalsRow,
  ScoreBadge,
} from '@/components/RunBits'
import { TooltipProvider } from '@/components/ui/misc'
import { emptyCounts } from '@/lib/runStatus'

function withProviders(ui: React.ReactElement) {
  return render(<TooltipProvider>{ui}</TooltipProvider>)
}

function totals(overrides: Partial<RunTotals> = {}): RunTotals {
  return {
    items: 10,
    pending: 0,
    invoking: 0,
    scoring: 0,
    passed: 7,
    failed: 3,
    error: 0,
    skipped: 0,
    needs_human: 0,
    scored: 10,
    verdict_passed: 7,
    unscored: 0,
    prompt_tokens: 1200,
    completion_tokens: 800,
    cost_usd: 0.0123,
    judge_cost_usd: 0,
    cost_unknown: false,
    ...overrides,
  }
}

describe('ItemStatusBadge', () => {
  it('says "done (unscored)" when nothing judged the item', () => {
    // Calling this "passed" would overclaim — nothing actually checked it.
    withProviders(<ItemStatusBadge status="passed" verdict={null} />)
    expect(screen.getByText('done (unscored)')).toBeInTheDocument()
    expect(screen.queryByText('passed')).not.toBeInTheDocument()
  })

  it('says "passed" when a verdict backs it up', () => {
    withProviders(<ItemStatusBadge status="passed" verdict={true} />)
    expect(screen.getByText('passed')).toBeInTheDocument()
  })

  it('renders failed, error and skipped distinctly', () => {
    const { unmount } = withProviders(<ItemStatusBadge status="failed" verdict={false} />)
    expect(screen.getByText('failed')).toBeInTheDocument()
    unmount()

    const second = withProviders(<ItemStatusBadge status="error" />)
    expect(screen.getByText('error')).toBeInTheDocument()
    second.unmount()

    withProviders(<ItemStatusBadge status="skipped" />)
    expect(screen.getByText('skipped')).toBeInTheDocument()
  })

  it('flags an item that is waiting on a human', () => {
    withProviders(<ItemStatusBadge status="passed" verdict={true} needsHuman />)
    expect(screen.getByText('needs you')).toBeInTheDocument()
  })
})

describe('RunStatusBadge', () => {
  it('renders each run status', () => {
    for (const status of [
      'pending',
      'running',
      'completed',
      'failed',
      'canceled',
      'interrupted',
    ] as const) {
      const { unmount } = withProviders(<RunStatusBadge status={status} />)
      expect(screen.getByText(status)).toBeInTheDocument()
      unmount()
    }
  })
})

describe('ScoreBadge', () => {
  it('shows a dash when there is nothing to show', () => {
    withProviders(<ScoreBadge verdict={null} score={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('shows the verdict and the numeric score together', () => {
    withProviders(<ScoreBadge verdict={true} score={87.5} />)
    expect(screen.getByText('pass')).toBeInTheDocument()
    expect(screen.getByText('87.5')).toBeInTheDocument()
  })
})

describe('RunTotalsRow', () => {
  it('computes pass rate over scored items only', () => {
    // 7 passed + 3 failed = 10 scored → 70%. Errors must not dilute it.
    withProviders(<RunTotalsRow totals={totals({ error: 5, items: 15 })} />)
    expect(screen.getByText('70%')).toBeInTheDocument()
  })

  it('shows a dash rather than 0% when nothing has been scored', () => {
    withProviders(
      <RunTotalsRow
        totals={totals({
          passed: 0,
          failed: 0,
          items: 4,
          pending: 4,
          scored: 0,
          verdict_passed: 0,
        })}
      />,
    )
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('marks an unknown cost as a lower bound', () => {
    withProviders(<RunTotalsRow totals={totals({ cost_unknown: true })} />)
    expect(screen.getByText(/^≥ \$/)).toBeInTheDocument()
  })

  it('reports an exact cost without the bound marker', () => {
    withProviders(<RunTotalsRow totals={totals()} />)
    expect(screen.getByText('$0.012')).toBeInTheDocument()
  })

  it('only surfaces errors and review counts when they exist', () => {
    const { unmount } = withProviders(<RunTotalsRow totals={totals()} />)
    expect(screen.queryByText('errors')).not.toBeInTheDocument()
    expect(screen.queryByText('needs review')).not.toBeInTheDocument()
    unmount()

    withProviders(<RunTotalsRow totals={totals({ error: 2, needs_human: 1 })} />)
    expect(screen.getByText('errors')).toBeInTheDocument()
    expect(screen.getByText('needs review')).toBeInTheDocument()
  })
})

describe('LaneProgress', () => {
  it('describes the lane for screen readers', () => {
    const counts = { ...emptyCounts(), passed: 3, failed: 1, error: 1 }
    withProviders(<LaneProgress counts={counts} total={5} />)
    expect(screen.getByRole('img')).toHaveAccessibleName('3 passed, 1 failed, 1 errored of 5')
  })

  it('handles a zero-item lane without dividing by zero', () => {
    withProviders(<LaneProgress counts={emptyCounts()} total={0} />)
    expect(screen.getByRole('img')).toBeInTheDocument()
  })
})

describe('RunTotalsRow — execution versus evaluation', () => {
  /**
   * The shape from the review: nine items, one of which ran fine and was never
   * scored. `totals.passed` counts it (the call succeeded); the pass rate must
   * not. Showing both under one heading made the numbers refuse to add up.
   */
  const mixed = totals({
    items: 9,
    passed: 5,
    failed: 4,
    scored: 8,
    verdict_passed: 4,
    unscored: 1,
  })

  it('separates the two groups so nothing is counted in both', () => {
    withProviders(<RunTotalsRow totals={mixed} />)

    expect(screen.getByText('Execution')).toBeInTheDocument()
    expect(screen.getByText('Evaluation')).toBeInTheDocument()
  })

  it('reports completed executions, not verdicts, under Execution', () => {
    withProviders(<RunTotalsRow totals={mixed} />)

    // 5 status-passed + 4 status-failed = 9 items whose call went through.
    const completed = screen.getByText('completed').parentElement
    expect(completed).toHaveTextContent('9')
  })

  it('reports verdicts, not statuses, under Evaluation', () => {
    withProviders(<RunTotalsRow totals={mixed} />)

    // 4 passed by verdict — not the 5 whose invocation succeeded.
    expect(screen.getByText('passed').parentElement).toHaveTextContent('4')
    expect(screen.getByText('failed').parentElement).toHaveTextContent('4')
    expect(screen.getByText('unscored').parentElement).toHaveTextContent('1')
    // 4 of 8 scored, so 50% — and the unscored item is in neither term.
    expect(screen.getByText('pass rate').parentElement).toHaveTextContent('50%')
  })
})
