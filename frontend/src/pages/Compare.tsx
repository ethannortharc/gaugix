import { AlertTriangle, Check, Download, GitCompare, Scale, Table2 } from 'lucide-react'
import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import {
  comparisonReportUrl,
  useAggregate,
  useCompareOptions,
  useDiff,
  useLeaderboard,
  useMatrix,
} from '@/api/compare'
import type {
  CaseUniverse,
  CompareRunOption,
  DiffKind,
  DiffRead,
  LeaderboardRead,
  MatrixRead,
  SetCoverage,
} from '@/api/types'
import {
  CostCell,
  DiffCountButton,
  DiffKindBadge,
  MatrixCellChip,
  PassRate,
  PassRateBar,
  ScoreDelta,
} from '@/components/CompareBits'
import { PageHeader } from '@/components/layout/AppShell'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatRelative, formatScore, formatTokens, pluralize } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * Comparison (PRD F5.2–F5.4).
 *
 * Four questions, four tabs, one picker. **Diff** answers "did this regress
 * against the run I blessed?" and leads because it is the question with a
 * deadline; **Leaderboard** answers "which executor should I use?"; the two
 * matrices are for reading the detail once you know where to look.
 *
 * Selection lives in the URL so a comparison is a link you can send.
 */

const DIFF_ORDER: DiffKind[] = [
  'regressed',
  'improved',
  'unresolved',
  'new',
  'removed',
  'unchanged',
]

function useSelection() {
  const [params, setParams] = useSearchParams()

  const runIds = React.useMemo(
    () =>
      (params.get('runs') ?? '')
        .split(',')
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value) && value > 0),
    [params],
  )
  const executors = React.useMemo(
    () => (params.get('executors') ?? '').split(',').filter(Boolean),
    [params],
  )
  const tab = params.get('view') ?? 'diff'

  const update = React.useCallback(
    (next: { runs?: number[]; executors?: string[]; view?: string }) => {
      setParams(
        (previous) => {
          const merged = new URLSearchParams(previous)
          if (next.runs) {
            if (next.runs.length) merged.set('runs', next.runs.join(','))
            else merged.delete('runs')
          }
          if (next.executors) {
            if (next.executors.length) merged.set('executors', next.executors.join(','))
            else merged.delete('executors')
          }
          if (next.view) merged.set('view', next.view)
          return merged
        },
        { replace: true },
      )
    },
    [setParams],
  )

  return { runIds, executors, tab, update }
}

export default function ComparePage() {
  const options = useCompareOptions()
  const { runIds, executors, tab, update } = useSelection()
  const runs = React.useMemo(() => options.data?.runs ?? [], [options.data])

  // Default to the newest run, so the page opens on something rather than a form.
  React.useEffect(() => {
    if (runIds.length === 0 && runs.length > 0) {
      update({ runs: [runs[0].id] })
    }
  }, [runIds.length, runs, update])

  const filters = React.useMemo(() => ({ runIds, executors }), [runIds, executors])

  if (options.isError) {
    return (
      <>
        <PageHeader title="Compare" />
        <ErrorState error={options.error} onRetry={() => void options.refetch()} />
      </>
    )
  }
  if (options.isLoading) {
    return (
      <>
        <PageHeader title="Compare" />
        <LoadingState label="Looking for runs to compare…" rows={4} />
      </>
    )
  }
  if (runs.length === 0) {
    return (
      <>
        <PageHeader title="Compare" description="Matrix, leaderboard and regression diff." />
        <EmptyState
          icon={<Scale className="size-6" />}
          title="Nothing to compare yet"
          description="A comparison reads finished run items. Start a run — the fake executors cost nothing — and this page fills in."
          action={
            <Button asChild size="sm">
              <Link to="/runs/new">Start a run</Link>
            </Button>
          }
        />
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Compare"
        description="Regression against a baseline, and which executor earns its cost."
        actions={
          runIds.length > 0 ? (
            <Button asChild size="sm" variant="outline">
              <a href={comparisonReportUrl(runIds)} download>
                <Download />
                Export report
              </a>
            </Button>
          ) : undefined
        }
      />

      <div className="flex flex-col gap-4">
        <Picker
          runs={runs}
          executors={options.data?.executors ?? []}
          selectedRuns={runIds}
          selectedExecutors={executors}
          onChange={update}
        />

        {runIds.length === 0 ? (
          <EmptyState
            icon={<Scale className="size-6" />}
            title="Pick at least one run"
            description="Every view below is computed from the runs you select."
          />
        ) : (
          <Tabs value={tab} onValueChange={(view) => update({ view })}>
            <TabsList>
              <TabsTrigger value="diff">
                <GitCompare className="size-3.5" />
                Diff
              </TabsTrigger>
              <TabsTrigger value="leaderboard">
                <Scale className="size-3.5" />
                Leaderboard
              </TabsTrigger>
              <TabsTrigger value="matrix">
                <Table2 className="size-3.5" />
                Matrix
              </TabsTrigger>
              <TabsTrigger value="aggregate">By set</TabsTrigger>
            </TabsList>

            <TabsContent value="diff">
              <DiffView runIds={runIds} runs={runs} />
            </TabsContent>
            <TabsContent value="leaderboard">
              <LeaderboardView filters={filters} />
            </TabsContent>
            <TabsContent value="matrix">
              <MatrixView filters={filters} />
            </TabsContent>
            <TabsContent value="aggregate">
              <AggregateView filters={filters} />
            </TabsContent>
          </Tabs>
        )}
      </div>
    </>
  )
}

// -- picker --------------------------------------------------------------------

function Picker({
  runs,
  executors,
  selectedRuns,
  selectedExecutors,
  onChange,
}: {
  runs: CompareRunOption[]
  executors: string[]
  selectedRuns: number[]
  selectedExecutors: string[]
  onChange: (next: { runs?: number[]; executors?: string[] }) => void
}) {
  function toggleRun(id: number) {
    onChange({
      runs: selectedRuns.includes(id)
        ? selectedRuns.filter((value) => value !== id)
        : [...selectedRuns, id],
    })
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          Runs{' '}
          <span className="font-normal text-[var(--muted-foreground)]">
            — {selectedRuns.length} of {runs.length} selected
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-2">
          {runs.map((run) => {
            const active = selectedRuns.includes(run.id)
            return (
              <button
                key={run.id}
                type="button"
                onClick={() => toggleRun(run.id)}
                aria-pressed={active}
                className={cn(
                  'flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-left text-xs transition-colors',
                  active
                    ? 'border-[var(--primary)] bg-[var(--accent)] text-[var(--accent-foreground)]'
                    : 'border-[var(--border)] hover:bg-[var(--muted)]',
                )}
              >
                {/* Decorative only: the button itself carries aria-pressed, and a
                    real checkbox here would nest a <button> inside a <button>. */}
                <span
                  aria-hidden
                  className={cn(
                    'flex size-4 shrink-0 items-center justify-center rounded-[4px] border',
                    active
                      ? 'border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]'
                      : 'border-[var(--input)]',
                  )}
                >
                  {active ? <Check className="size-3" /> : null}
                </span>
                <span className="flex flex-col">
                  <span className="font-medium">{run.name || `Run ${run.id}`}</span>
                  <span className="text-[11px] text-[var(--muted-foreground)]">
                    {formatRelative(run.finished_at ?? run.created_at)} · {run.totals.items ?? 0}{' '}
                    {pluralize(run.totals.items ?? 0, 'item')}
                  </span>
                </span>
                {run.is_baseline_for.length > 0 ? <Badge variant="primary">baseline</Badge> : null}
              </button>
            )
          })}
        </div>

        {executors.length > 1 ? (
          <div className="flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-3">
            <span className="text-xs text-[var(--muted-foreground)]">Executors:</span>
            {executors.map((executor) => {
              const active = selectedExecutors.includes(executor)
              return (
                <button
                  key={executor}
                  type="button"
                  aria-pressed={active}
                  onClick={() =>
                    onChange({
                      executors: active
                        ? selectedExecutors.filter((value) => value !== executor)
                        : [...selectedExecutors, executor],
                    })
                  }
                  className={cn(
                    'rounded-full border px-2.5 py-0.5 font-mono text-[11px] transition-colors',
                    active
                      ? 'border-[var(--primary)] bg-[var(--accent)] text-[var(--accent-foreground)]'
                      : 'border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]',
                  )}
                >
                  {executor}
                </button>
              )
            })}
            {selectedExecutors.length > 0 ? (
              <Button variant="ghost" size="sm" onClick={() => onChange({ executors: [] })}>
                Clear
              </Button>
            ) : (
              <span className="text-[11px] text-[var(--muted-foreground)]">all</span>
            )}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

// -- diff (PRD F5.3) -----------------------------------------------------------

function DiffView({ runIds, runs }: { runIds: number[]; runs: CompareRunOption[] }) {
  // The diff is inherently two-sided: the first selected run is "current".
  const currentId = runIds[0]
  const [baselineId, setBaselineId] = React.useState<number | undefined>(undefined)
  const explicitBaseline = baselineId ?? (runIds.length > 1 ? runIds[1] : undefined)
  const diff = useDiff(currentId, explicitBaseline)
  const [kinds, setKinds] = React.useState<DiffKind[]>([])

  const current = runs.find((run) => run.id === currentId)

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-4 text-sm">
          <span className="font-medium">{current?.name || `Run ${currentId}`}</span>
          <span className="text-[var(--muted-foreground)]">compared against</span>
          <Select
            value={explicitBaseline ? String(explicitBaseline) : 'auto'}
            onValueChange={(value) => setBaselineId(value === 'auto' ? undefined : Number(value))}
          >
            <SelectTrigger className="h-8 w-64" aria-label="Baseline run">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">the run marked baseline</SelectItem>
              {runs
                .filter((run) => run.id !== currentId)
                .map((run) => (
                  <SelectItem key={run.id} value={String(run.id)}>
                    {run.name || `Run ${run.id}`}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
          {diff.data ? (
            <Button asChild size="sm" variant="outline" className="ml-auto">
              <a
                href={comparisonReportUrl(
                  [diff.data.current_run_id, diff.data.baseline_run_id],
                  diff.data.baseline_run_id,
                )}
                download
              >
                <Download />
                Export diff
              </a>
            </Button>
          ) : null}
        </CardContent>
      </Card>

      {diff.isLoading ? (
        <LoadingState label="Diffing…" rows={4} />
      ) : diff.isError ? (
        <ErrorState error={diff.error} onRetry={() => void diff.refetch()} />
      ) : diff.data && !diff.data.available ? (
        // Not an error: there is simply nothing blessed yet to compare against.
        <EmptyState
          icon={<GitCompare className="size-6" />}
          title="No baseline to compare against"
          description={diff.data.reason ?? 'Mark a run as baseline for this set.'}
        />
      ) : diff.data ? (
        <DiffBody diff={diff.data} kinds={kinds} onKinds={setKinds} />
      ) : null}
    </div>
  )
}

/**
 * Which sets this diff actually covers.
 *
 * Sets bless their own baselines, so a run spanning two sets can face two
 * different baseline runs. The diff scopes itself to one of them; this names
 * the ones it left out instead of quietly folding them into the numbers.
 */
function CoverageNotice({ coverage }: { coverage: SetCoverage[] }) {
  const excluded = coverage.filter((entry) => !entry.included)
  if (excluded.length === 0 || coverage.length < 2) return null

  return (
    <div className="flex flex-col gap-1 rounded-md border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-2 text-xs">
      <span className="font-medium">
        This diff covers {coverage.length - excluded.length} of {coverage.length} sets in the run.
      </span>
      {excluded.map((entry) => (
        <span key={entry.set_id} className="text-[var(--muted-foreground)]">
          <strong>{entry.set_name}</strong> is not included — {entry.reason}
          {entry.baseline_run_id ? (
            <>
              {' '}
              <Link
                to={`/compare?run=${entry.baseline_run_id}`}
                className="underline hover:text-[var(--foreground)]"
              >
                open that baseline
              </Link>
            </>
          ) : null}
        </span>
      ))}
    </div>
  )
}

function DiffBody({
  diff,
  kinds,
  onKinds,
}: {
  diff: DiffRead
  kinds: DiffKind[]
  onKinds: (next: DiffKind[]) => void
}) {
  const shown = kinds.length
    ? diff.entries.filter((entry) => kinds.includes(entry.kind))
    : // Unchanged is the bulk and the least interesting; hide it by default but
      // keep it one click away rather than pretending it does not exist.
      diff.entries.filter((entry) => entry.kind !== 'unchanged')

  const mismatched =
    diff.executors.only_current.length > 0 || diff.executors.only_baseline.length > 0

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        {DIFF_ORDER.map((kind) => {
          const active = kinds.includes(kind)
          return (
            <DiffCountButton
              key={kind}
              kind={kind}
              count={diff.counts[kind] ?? 0}
              active={active}
              onClick={() => onKinds(active ? kinds.filter((k) => k !== kind) : [...kinds, kind])}
            />
          )
        })}
      </div>

      {/*
        The headline is the *paired* delta: both runs restricted to the cases
        and executors they share. Subtracting the two unpaired rates produced a
        confident number out of two different bodies of work — a run that
        merely swapped executors read as a six-point regression.
      */}
      {diff.comparable ? (
        <div className="flex flex-col gap-1.5 rounded-md border border-[var(--border)] px-4 py-3">
          <div className="flex flex-wrap gap-6 text-sm">
            <span className="flex items-center gap-2">
              <span className="text-[var(--muted-foreground)]">Pass rate</span>
              <PassRate value={diff.paired.pass_rate.baseline} />
              <span className="text-[var(--muted-foreground)]">→</span>
              <PassRate value={diff.paired.pass_rate.current} />
            </span>
            <span className="flex items-center gap-2">
              <span className="text-[var(--muted-foreground)]">Mean score</span>
              <span className="tabular">{formatScore(diff.paired.mean_score.baseline)}</span>
              <span className="text-[var(--muted-foreground)]">→</span>
              <span className="tabular">{formatScore(diff.paired.mean_score.current)}</span>
            </span>
          </div>
          <p className="text-xs text-[var(--muted-foreground)]">
            Over the {diff.paired.items} {pluralize(diff.paired.items, 'item')} both runs share.
            {diff.entries.length > diff.paired.items
              ? ` ${diff.entries.length - diff.paired.items} more appear on only one side and are excluded — a delta needs both.`
              : ''}
          </p>
        </div>
      ) : (
        <p className="rounded-md border border-[var(--error)]/40 bg-[var(--error)]/10 px-3 py-2 text-xs">
          <strong>No overall delta to show.</strong> These two runs have no case-and-executor pair
          in common, so every entry below is new or removed and there is nothing to subtract. Run
          the same executors over the same sets to get a comparison.
        </p>
      )}

      {mismatched ? (
        <p className="rounded-md border border-[var(--error)]/40 bg-[var(--error)]/10 px-3 py-2 text-xs">
          These runs did not use the same executors
          {diff.executors.only_current.length
            ? ` (only here: ${diff.executors.only_current.join(', ')})`
            : ''}
          {diff.executors.only_baseline.length
            ? ` (only in the baseline: ${diff.executors.only_baseline.join(', ')})`
            : ''}
          , so those cases are counted as new or removed rather than as changes.
        </p>
      ) : null}

      <CoverageNotice coverage={diff.coverage} />
      <UniverseNotice universes={diff.case_universes} />

      {shown.length === 0 ? (
        <EmptyState
          icon={<GitCompare className="size-6" />}
          title="Nothing changed"
          description="Every case holds the verdict it had on the baseline."
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-32">Change</TableHead>
                <TableHead>Case</TableHead>
                <TableHead className="w-40">Executor</TableHead>
                <TableHead className="w-40">Verdict</TableHead>
                <TableHead className="w-24 text-right">Score</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((entry, index) => (
                <TableRow key={`${entry.case_id}-${entry.executor_key}-${index}`}>
                  <TableCell>
                    <DiffKindBadge kind={entry.kind} />
                  </TableCell>
                  <TableCell>
                    {(entry.current_item_id ?? entry.baseline_item_id) ? (
                      <Link
                        to={`/items/${entry.current_item_id ?? entry.baseline_item_id}`}
                        className="font-medium hover:underline"
                      >
                        {entry.title}
                      </Link>
                    ) : (
                      <span className="font-medium">{entry.title}</span>
                    )}
                    <div className="text-[11px] text-[var(--muted-foreground)]">
                      {entry.set_name}
                      {entry.note ? ` · ${entry.note}` : ''}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{entry.executor_key}</TableCell>
                  <TableCell className="text-xs">
                    <VerdictArrow from={entry.baseline_verdict} to={entry.current_verdict} />
                  </TableCell>
                  <TableCell className="text-right">
                    <ScoreDelta delta={entry.score_delta} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

function VerdictLabel({ verdict }: { verdict: boolean | null }) {
  if (verdict === null) return <span className="text-[var(--muted-foreground)]">—</span>
  return (
    <span className={verdict ? 'text-[var(--pass)]' : 'text-[var(--fail)]'}>
      {verdict ? 'pass' : 'fail'}
    </span>
  )
}

function VerdictArrow({ from, to }: { from: boolean | null; to: boolean | null }) {
  return (
    <span className="flex items-center gap-1.5">
      <VerdictLabel verdict={from} />
      <span className="text-[var(--muted-foreground)]">→</span>
      <VerdictLabel verdict={to} />
    </span>
  )
}

// -- leaderboard (PRD F5.4) ----------------------------------------------------

function LeaderboardView({ filters }: { filters: { runIds: number[]; executors: string[] } }) {
  const query = useLeaderboard(filters)
  if (query.isLoading) return <LoadingState label="Ranking…" rows={4} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  const board: LeaderboardRead | undefined = query.data
  if (!board || board.rows.length === 0) {
    return <EmptyState title="No items in these runs" description="Pick a different run." />
  }

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-12">#</TableHead>
            <TableHead>Executor</TableHead>
            <TableHead className="w-44">Pass rate</TableHead>
            <TableHead className="w-24 text-right">Passed</TableHead>
            <TableHead className="w-24 text-right">Failed</TableHead>
            <TableHead className="w-24 text-right">Unscored</TableHead>
            <TableHead className="w-24 text-right">Mean score</TableHead>
            <TableHead className="w-24 text-right">Cost</TableHead>
            <TableHead className="w-28 text-right">Mean latency</TableHead>
            <TableHead className="w-24 text-right">Tokens</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {board.rows.map((row) => (
            <TableRow key={row.executor_key}>
              <TableCell className="tabular text-xs text-[var(--muted-foreground)]">
                {row.rank ?? '—'}
              </TableCell>
              <TableCell className="font-medium">{row.executor_key}</TableCell>
              <TableCell>
                <PassRateBar value={row.pass_rate} />
              </TableCell>
              <TableCell className="tabular text-right text-xs">{row.passed}</TableCell>
              <TableCell className="tabular text-right text-xs">{row.failed}</TableCell>
              <TableCell className="tabular text-right text-xs">{row.unscored}</TableCell>
              <TableCell className="tabular text-right text-xs">
                {formatScore(row.mean_score)}
              </TableCell>
              <TableCell className="text-right">
                <CostCell stats={row} />
              </TableCell>
              <TableCell className="tabular text-right text-xs">
                {row.mean_latency_ms === null ? '—' : `${row.mean_latency_ms} ms`}
              </TableCell>
              <TableCell className="tabular text-right text-xs">
                {formatTokens(row.prompt_tokens + row.completion_tokens)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

// -- matrices (PRD F5.2) -------------------------------------------------------

function MatrixView({ filters }: { filters: { runIds: number[]; executors: string[] } }) {
  const query = useMatrix(filters)
  if (query.isLoading) return <LoadingState label="Building the matrix…" rows={6} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  const matrix: MatrixRead | undefined = query.data
  if (!matrix || matrix.rows.length === 0) {
    return <EmptyState title="No cases in these runs" description="Pick a different run." />
  }

  let lastSet: string | null = null
  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Case</TableHead>
            {matrix.executors.map((executor) => (
              <TableHead key={executor} className="w-36 font-mono text-[11px]">
                {executor}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {matrix.rows.map((row) => {
            const newSet = row.set_name !== lastSet
            lastSet = row.set_name
            return (
              <React.Fragment key={`${row.set_id}-${row.case_id}`}>
                {newSet ? (
                  <TableRow className="bg-[var(--surface-2)]">
                    <TableCell
                      colSpan={matrix.executors.length + 1}
                      className="py-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]"
                    >
                      {row.set_name}
                    </TableCell>
                  </TableRow>
                ) : null}
                <TableRow>
                  <TableCell className="text-sm">
                    <span className="flex items-center gap-2">
                      {row.title}
                      {/* Two or more cells means there is something to compare. */}
                      {Object.keys(row.cells).length >= 2 ? (
                        <Link
                          to={`/compare/side-by-side?items=${Object.values(row.cells)
                            .slice(0, 4)
                            .map((cell) => cell.item_id)
                            .join(',')}`}
                          className="text-[11px] text-[var(--muted-foreground)] hover:text-[var(--primary)] hover:underline"
                          title="Open this case across executors, side by side"
                        >
                          side by side
                        </Link>
                      ) : null}
                    </span>
                  </TableCell>
                  {matrix.executors.map((executor) => {
                    const cell = row.cells[executor]
                    return (
                      <TableCell key={executor}>
                        {cell ? (
                          <Link to={`/items/${cell.item_id}`}>
                            <MatrixCellChip cell={cell} />
                          </Link>
                        ) : (
                          <MatrixCellChip cell={undefined} />
                        )}
                      </TableCell>
                    )
                  })}
                </TableRow>
              </React.Fragment>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

function AggregateView({ filters }: { filters: { runIds: number[]; executors: string[] } }) {
  const query = useAggregate(filters)
  if (query.isLoading) return <LoadingState label="Aggregating…" rows={4} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  const data = query.data
  if (!data || data.rows.length === 0) {
    return <EmptyState title="No sets in these runs" description="Pick a different run." />
  }

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Set</TableHead>
            {data.executors.map((executor) => (
              <TableHead key={executor} className="font-mono text-[11px]">
                {executor}
              </TableHead>
            ))}
            <TableHead className="w-28">All</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.rows.map((row) => (
            <TableRow key={row.set_id}>
              <TableCell className="font-medium">{row.set_name}</TableCell>
              {data.executors.map((executor) => {
                const cell = row.cells[executor]
                return (
                  <TableCell key={executor}>
                    {cell ? (
                      <div className="flex flex-col gap-0.5">
                        <PassRateBar value={cell.pass_rate} />
                        <span className="text-[11px] text-[var(--muted-foreground)]">
                          {cell.passed}/{cell.scored} scored · <CostCell stats={cell} />
                        </span>
                      </div>
                    ) : (
                      <span className="text-xs text-[var(--muted-foreground)]">—</span>
                    )}
                  </TableCell>
                )
              })}
              <TableCell>
                <PassRate value={row.totals.pass_rate} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

/**
 * Whether the two runs were about the same cases.
 *
 * The paired delta already restricts the arithmetic to shared identities, so
 * nothing here changes a number. It supplies the sentence that stops one being
 * misread: "40% → 100%" reads as a fixed model until you know the second run
 * covered two of those five cases (D-053).
 */
function UniverseNotice({ universes }: { universes: CaseUniverse[] }) {
  const mismatched = universes.filter(
    (u) => u.same_universe === false || u.current_partial || u.baseline_partial,
  )
  if (mismatched.length === 0) return null

  return (
    <div className="flex flex-col gap-1 rounded-md border border-[var(--human)]/40 bg-[var(--human)]/10 px-3 py-2 text-xs">
      <span className="flex items-center gap-1.5 font-medium">
        <AlertTriangle className="size-3.5 shrink-0" />
        These runs did not cover the same cases
      </span>
      {mismatched.map((entry) => (
        <span key={entry.set_id} className="text-[var(--muted-foreground)]">
          <strong>{entry.set_name}</strong> — this run: {entry.current}; baseline: {entry.baseline}.
        </span>
      ))}
      <span className="text-[var(--muted-foreground)]">
        The delta above is computed over the cases both runs share, so it is sound — but the two
        pass rates describe different populations and should not be quoted side by side.
      </span>
    </div>
  )
}
