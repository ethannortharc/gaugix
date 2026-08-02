import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { CaseRunHistoryRow, SetRunHistoryRow } from '@/api/types'
import { CaseRunHistory, SetRunHistory } from '@/components/RunHistory'
import { renderWithProviders } from '@/test/utils'

function response(body: unknown, total: number) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json', 'X-Total-Count': String(total) },
  })
}

describe('RunHistory', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))

  it('renders set-scoped metrics and keeps partial coverage explicit', async () => {
    const row: SetRunHistoryRow = {
      run_id: 41,
      run_name: 'Regression sweep',
      status: 'completed',
      created_at: '2026-08-01T00:00:00Z',
      finished_at: '2026-08-01T00:01:00Z',
      executor_keys: ['strict @ fake', 'helpful @ fake'],
      item_count: 4,
      case_count: 2,
      coverage: '2 of 5 cases',
      is_partial: true,
      is_baseline: true,
      scored: 4,
      passed: 2,
      failed: 2,
      unscored: 0,
      pass_rate: 50,
    }
    const rows = Array.from({ length: 10 }, (_, index) => ({
      ...row,
      run_id: row.run_id + index,
      run_name: index === 0 ? row.run_name : `Regression sweep ${index + 1}`,
    }))
    vi.mocked(fetch).mockResolvedValue(response(rows, 25))

    renderWithProviders(<SetRunHistory setId={7} />)

    expect(await screen.findByRole('link', { name: 'Regression sweep' })).toHaveAttribute(
      'href',
      '/runs/41',
    )
    expect(screen.getAllByText('partial')).toHaveLength(10)
    expect(screen.getAllByText('2 of 5 cases')).toHaveLength(10)
    expect(screen.getAllByText('baseline')).toHaveLength(10)
    expect(screen.getAllByText('50%')).toHaveLength(10)
    expect(screen.getAllByText('2/4 passed')).toHaveLength(10)
    expect(screen.getAllByText('2 executors')).toHaveLength(10)
    expect(screen.getByRole('button', { name: 'Load 10 more' })).toBeInTheDocument()
  })

  it('links a case history row to the exact run item and preserves set context', async () => {
    const row: CaseRunHistoryRow = {
      item_id: 91,
      run_id: 41,
      run_name: 'Regression sweep',
      run_status: 'completed',
      run_created_at: '2026-08-01T00:00:00Z',
      set_id: 7,
      set_name: 'Guardrails',
      executor_key: 'strict @ fake',
      item_status: 'failed',
      verdict: false,
      score_value: 25,
      needs_human: false,
      error: null,
      output_preview: 'The response allowed the unsafe request.',
      latency_ms: 420,
      cost_usd: 0.012,
      attempt_n: 1,
    }
    vi.mocked(fetch).mockResolvedValue(response([row], 1))

    renderWithProviders(<CaseRunHistory caseId={3} />)

    expect(await screen.findByRole('link', { name: 'Regression sweep' })).toHaveAttribute(
      'href',
      '/items/91',
    )
    expect(screen.getByRole('link', { name: 'Guardrails' })).toHaveAttribute('href', '/sets/7')
    expect(screen.getByText('strict @ fake')).toBeInTheDocument()
    expect(screen.getByText('The response allowed the unsafe request.')).toBeInTheDocument()
    expect(screen.getByText('420 ms · $0.012')).toBeInTheDocument()
  })

  it('states that an entity has no run history instead of leaving a blank card', async () => {
    vi.mocked(fetch).mockResolvedValue(response([], 0))
    renderWithProviders(<CaseRunHistory caseId={3} />)
    expect(await screen.findByText('This case has not been run yet.')).toBeInTheDocument()
  })
})
