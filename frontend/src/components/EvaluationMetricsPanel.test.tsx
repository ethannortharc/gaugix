import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { EvaluationMetricsPanel } from '@/components/EvaluationMetricsPanel'
import { renderWithProviders } from '@/test/utils'

function response(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('EvaluationMetricsPanel', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        response({
          run_id: 1,
          slices: [
            {
              set_id: 4,
              set_name: 'Policy set',
              executor_key: 'subject @ direct',
              node_id: null,
              node_path: [],
              profile: {
                kind: 'binary_classification',
                name: 'Guardrail detection',
                description: null,
                truth: { source: 'tag', key: 'label' },
                prediction: { source: 'output_json', key: 'verdict' },
                score: null,
                score_scale: '0-1',
                category_truth: null,
                category_prediction: null,
                positive_values: ['unsafe'],
                negative_values: ['safe'],
                positive_label: 'blocked',
                negative_label: 'allowed',
                false_positive_label: 'Over-refusal rate',
              },
              coverage: {
                items: 4,
                valid: 4,
                execution_errors: 0,
                missing_truth: 0,
                missing_prediction: 0,
              },
              metrics: [
                {
                  key: 'recall',
                  label: 'Recall',
                  value: 0.75,
                  unit: 'ratio',
                  numerator: 3,
                  denominator: 4,
                  hint: null,
                  unavailable_reason: null,
                },
                {
                  key: 'false_positive_rate',
                  label: 'Over-refusal rate',
                  value: 0.25,
                  unit: 'ratio',
                  numerator: 1,
                  denominator: 4,
                  hint: null,
                  unavailable_reason: null,
                },
              ],
              confusion: {
                tp: 3,
                fp: 1,
                fn: 1,
                tn: 3,
                positive_label: 'blocked',
                negative_label: 'allowed',
              },
              categories: [],
              threshold_curve: [],
            },
          ],
        }),
      ),
    )
  })

  it('renders profile-specific metrics without a guard-only component contract', async () => {
    renderWithProviders(
      <EvaluationMetricsPanel
        runId={1}
        live={false}
        config={{
          executors: [],
          sets: [{ id: 4, name: 'Policy set' }],
          concurrency: 1,
          auto_score: true,
        }}
      />,
    )
    expect(await screen.findByText('Guardrail detection')).toBeInTheDocument()
    expect(screen.getByText('Recall')).toBeInTheDocument()
    expect(screen.getByText('75.0%')).toBeInTheDocument()
    expect(screen.getByText('Over-refusal rate')).toBeInTheDocument()
    expect(screen.getByText('Confusion matrix')).toBeInTheDocument()
  })
})
