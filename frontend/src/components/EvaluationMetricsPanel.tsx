import { Activity, SlidersHorizontal } from 'lucide-react'
import * as React from 'react'

import { useRunMetrics } from '@/api/evaluation'
import type { EvaluationSlice, MetricValue, RunConfig, ThresholdPoint } from '@/api/types'
import { ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface FrozenNodeOption {
  setId: number
  id: number
  name: string
  path: string[]
}

export function EvaluationMetricsPanel({
  runId,
  config,
  live,
}: {
  runId: number
  config: RunConfig
  live: boolean
}) {
  const [branch, setBranch] = React.useState('all')
  const nodes = React.useMemo(() => frozenNodeOptions(config), [config])
  const selected = nodes.find((node) => `${node.setId}:${node.id}` === branch)
  const query = useRunMetrics(
    runId,
    selected ? { set_id: selected.setId, node_id: selected.id } : {},
    { live },
  )

  return (
    <Card className="mb-4">
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 pb-3">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Activity className="size-4 text-[var(--primary)]" />
            Evaluation metrics
          </CardTitle>
          <CardDescription className="mt-1">
            Computed from the metric profile frozen with this run—not the set’s current settings.
          </CardDescription>
        </div>
        {nodes.length > 0 ? (
          <Select value={branch} onValueChange={setBranch}>
            <SelectTrigger className="h-8 w-60" aria-label="Metric branch">
              <SlidersHorizontal className="size-3.5" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All set branches</SelectItem>
              {nodes.map((node) => (
                <SelectItem key={`${node.setId}:${node.id}`} value={`${node.setId}:${node.id}`}>
                  {node.path.join(' / ')}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
      </CardHeader>
      <CardContent>
        {query.isLoading ? (
          <LoadingState label="Computing metrics…" rows={3} />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : query.data?.slices.length ? (
          <div className="flex flex-col gap-4">
            {query.data.slices.map((slice) => (
              <MetricSlice key={`${slice.set_id}:${slice.executor_key}`} slice={slice} />
            ))}
          </div>
        ) : (
          <p className="py-4 text-sm text-[var(--muted-foreground)]">
            No run items are available for this slice yet.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function MetricSlice({ slice }: { slice: EvaluationSlice }) {
  return (
    <section className="overflow-hidden rounded-lg border border-[var(--border)]">
      <div className="flex flex-wrap items-start gap-2 border-b border-[var(--border)] bg-[var(--surface-2)] px-3 py-2.5">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold">
            {slice.set_name} <span className="text-[var(--muted-foreground)]">×</span>{' '}
            {slice.executor_key}
          </h3>
          <p className="text-xs text-[var(--muted-foreground)]">
            {slice.node_path.length > 0 ? `${slice.node_path.join(' / ')} · ` : ''}
            {slice.profile.name}
          </p>
        </div>
        <Badge variant="outline">
          {slice.coverage.valid}/{slice.coverage.items} metric-ready
        </Badge>
        {slice.coverage.execution_errors > 0 ? (
          <Badge variant="error">{slice.coverage.execution_errors} errors</Badge>
        ) : null}
      </div>

      <div className="grid gap-px bg-[var(--border)] sm:grid-cols-2 lg:grid-cols-4">
        {slice.metrics.map((metric) => (
          <MetricCell key={metric.key} metric={metric} />
        ))}
      </div>

      {slice.confusion ? (
        <div className="grid gap-4 border-t border-[var(--border)] p-3 xl:grid-cols-[18rem_minmax(0,1fr)]">
          <ConfusionMatrix slice={slice} />
          <div className="min-w-0">
            {slice.categories.length > 0 ? <CategoryTable slice={slice} /> : null}
            {slice.threshold_curve.length > 1 ? (
              <ThresholdChart points={slice.threshold_curve} />
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  )
}

function MetricCell({ metric }: { metric: MetricValue }) {
  return (
    <div className="min-h-20 bg-[var(--card)] p-3" title={metric.hint ?? undefined}>
      <p className="text-[11px] text-[var(--muted-foreground)]">{metric.label}</p>
      <p className="mt-1 tabular text-lg font-semibold tracking-tight">{formatMetric(metric)}</p>
      {metric.numerator !== null && metric.denominator !== null ? (
        <p className="tabular text-[10px] text-[var(--muted-foreground)]">
          {metric.numerator}/{metric.denominator}
        </p>
      ) : metric.unavailable_reason ? (
        <p className="line-clamp-2 text-[10px] text-[var(--muted-foreground)]">
          {metric.unavailable_reason}
        </p>
      ) : null}
    </div>
  )
}

function formatMetric(metric: MetricValue): string {
  if (metric.value === null) return '—'
  if (metric.unit === 'milliseconds') return `${Math.round(metric.value)} ms`
  if (metric.unit === 'ratio') return `${(metric.value * 100).toFixed(1)}%`
  return metric.value.toFixed(3)
}

function ConfusionMatrix({ slice }: { slice: EvaluationSlice }) {
  const matrix = slice.confusion
  if (!matrix) return null
  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold">Confusion matrix</h4>
      <div className="grid grid-cols-[5.5rem_1fr_1fr] gap-px overflow-hidden rounded-md bg-[var(--border)] text-center text-xs">
        <div className="bg-[var(--surface-2)] p-2" />
        <div className="bg-[var(--surface-2)] p-2">Pred. {matrix.positive_label}</div>
        <div className="bg-[var(--surface-2)] p-2">Pred. {matrix.negative_label}</div>
        <div className="bg-[var(--surface-2)] p-2">Actual {matrix.positive_label}</div>
        <div className="bg-[var(--card)] p-2 font-semibold">{matrix.tp}</div>
        <div className="bg-[var(--card)] p-2 font-semibold">{matrix.fn}</div>
        <div className="bg-[var(--surface-2)] p-2">Actual {matrix.negative_label}</div>
        <div className="bg-[var(--card)] p-2 font-semibold">{matrix.fp}</div>
        <div className="bg-[var(--card)] p-2 font-semibold">{matrix.tn}</div>
      </div>
      {(slice.coverage.missing_truth > 0 || slice.coverage.missing_prediction > 0) && (
        <p className="mt-2 text-[10px] text-[var(--muted-foreground)]">
          Excluded: {slice.coverage.missing_truth} missing truth ·{' '}
          {slice.coverage.missing_prediction} missing prediction
        </p>
      )}
    </div>
  )
}

function CategoryTable({ slice }: { slice: EvaluationSlice }) {
  return (
    <div className="mb-4">
      <h4 className="mb-2 text-xs font-semibold">Category attribution</h4>
      <div className="max-h-52 overflow-auto rounded-md border border-[var(--border)]">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Category</TableHead>
              <TableHead className="text-right">Support</TableHead>
              <TableHead className="text-right">Precision</TableHead>
              <TableHead className="text-right">Recall</TableHead>
              <TableHead className="text-right">F1</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {slice.categories.map((row) => (
              <TableRow key={row.category}>
                <TableCell className="font-medium">{row.category}</TableCell>
                <TableCell className="tabular text-right">{row.support}</TableCell>
                <TableCell className="tabular text-right">{formatRatio(row.precision)}</TableCell>
                <TableCell className="tabular text-right">{formatRatio(row.recall)}</TableCell>
                <TableCell className="tabular text-right">{formatRatio(row.f1)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function ThresholdChart({ points }: { points: ThresholdPoint[] }) {
  const line = (key: 'precision' | 'recall' | 'false_positive_rate') =>
    points
      .filter((point) => point[key] !== null)
      .map((point) => `${(1 - point.threshold) * 100},${(1 - (point[key] ?? 0)) * 100}`)
      .join(' ')
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-3 text-[10px] text-[var(--muted-foreground)]">
        <h4 className="mr-auto text-xs font-semibold text-[var(--foreground)]">Threshold curve</h4>
        <span className="text-[var(--primary)]">— Precision</span>
        <span className="text-[var(--pass)]">— Recall</span>
        <span className="text-[var(--destructive)]">— False positive</span>
      </div>
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="h-28 w-full rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-2"
        role="img"
        aria-label="Precision, recall and false-positive rate across score thresholds"
      >
        <polyline
          fill="none"
          stroke="var(--primary)"
          strokeWidth="1.5"
          points={line('precision')}
        />
        <polyline fill="none" stroke="var(--pass)" strokeWidth="1.5" points={line('recall')} />
        <polyline
          fill="none"
          stroke="var(--destructive)"
          strokeWidth="1.5"
          points={line('false_positive_rate')}
        />
      </svg>
      <p className="mt-1 text-[10px] text-[var(--muted-foreground)]">
        Threshold decreases left → right. Curves appear only when the profile maps a probability
        score.
      </p>
    </div>
  )
}

function formatRatio(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`
}

function frozenNodeOptions(config: RunConfig): FrozenNodeOption[] {
  const options: FrozenNodeOption[] = []
  for (const set of config.sets ?? []) {
    for (const raw of set.nodes ?? []) {
      if (typeof raw.id !== 'number' || typeof raw.name !== 'string') continue
      const path = Array.isArray(raw.path) ? raw.path.map(String) : [raw.name]
      options.push({ setId: set.id, id: raw.id, name: raw.name, path })
    }
  }
  return options
}
