import {
  ArrowLeft,
  Ban,
  Download,
  Flag,
  GitCompare,
  PieChart,
  Play,
  Radio,
  RefreshCw,
  RotateCw,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import * as React from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { runReportUrl } from '@/api/compare'
import {
  useCancelRun,
  useDeleteRun,
  useResumeRun,
  useRun,
  useJudgeClasses,
  useRunEvents,
  useRescore,
  useErrorKinds,
  useRunItems,
  useRunLanes,
  useSetBaseline,
} from '@/api/runs'
import type { ItemStatus, RunItem } from '@/api/types'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { EvaluationMetricsPanel } from '@/components/EvaluationMetricsPanel'
import { PageHeader } from '@/components/layout/AppShell'
import { LoadMore } from '@/components/LoadMore'
import { usePagedLimit } from '@/lib/paging'
import {
  ItemStatusBadge,
  LaneProgress,
  RunStatusBadge,
  RunTotalsRow,
  Stat,
  ScoreBadge,
} from '@/components/RunBits'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Tooltip } from '@/components/ui/misc'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDateTime, formatRelative, pluralize } from '@/lib/format'
import { emptyCounts } from '@/lib/runStatus'
import { cn } from '@/lib/utils'

const STATUS_FILTERS: ItemStatus[] = ['passed', 'failed', 'error', 'skipped', 'pending']

export default function RunDetailPage() {
  const params = useParams()
  const navigate = useNavigate()
  const runId = Number(params.id)

  const [statusFilter, setStatusFilter] = React.useState<ItemStatus[]>([])
  const [laneFilter, setLaneFilter] = React.useState<string[]>([])
  const [errorKindFilter, setErrorKindFilter] = React.useState<string[]>([])
  const [q, setQ] = React.useState('')

  const runQuery = useRun(runId)
  const live = runQuery.data?.is_active ?? false
  // Re-enterable: full state comes from the API first, then SSE streams deltas.
  const { connected } = useRunEvents(runId, live)

  const { limit, more, reset } = usePagedLimit()
  const itemsQuery = useRunItems(
    runId,
    {
      status: statusFilter.length ? statusFilter : undefined,
      executor_key: laneFilter.length ? laneFilter : undefined,
      error_kind: errorKindFilter.length ? errorKindFilter : undefined,
      q: q || undefined,
      limit,
    },
    { live },
  )
  const lanesQuery = useRunLanes(runId, { live })

  // A narrowed filter should start at the top of its own result set, not
  // 300 rows into the previous one.
  React.useEffect(() => {
    reset()
  }, [statusFilter, laneFilter, errorKindFilter, q, reset])

  const cancel = useCancelRun()
  const resume = useResumeRun()
  const remove = useDeleteRun()
  const [confirmDelete, setConfirmDelete] = React.useState(false)
  const [confirmBaseline, setConfirmBaseline] = React.useState(false)
  const baseline = useSetBaseline()
  const rescore = useRescore()
  const errorKinds = useErrorKinds(runId)

  if (runQuery.isLoading) return <LoadingState label="Loading run…" />
  if (runQuery.isError)
    return <ErrorState error={runQuery.error} onRetry={() => void runQuery.refetch()} />
  if (!runQuery.data) return null

  const run = runQuery.data
  const items = itemsQuery.data?.items ?? []
  const lanes = run.config.executors?.map((e) => e.key) ?? []
  const setIds = run.config.sets?.map((s) => s.id) ?? []

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <Button asChild variant="ghost" size="icon-sm" aria-label="Back to runs">
              <Link to="/runs">
                <ArrowLeft />
              </Link>
            </Button>
            {run.name}
            <RunStatusBadge status={run.status} executionErrors={run.totals.error} />
            {run.is_baseline_for.length > 0 ? (
              <Tooltip label="Regression diffs compare against this run.">
                <Badge variant="primary" className="gap-1">
                  <Flag className="size-3" />
                  baseline
                </Badge>
              </Tooltip>
            ) : null}
            {/*
              Every number on this page is about the cases listed here, not
              about the sets. Said next to the run's name, because that is what
              gets copied into a message about it.
            */}
            {run.is_partial ? (
              <Tooltip label={run.partial_coverage.join(' · ')}>
                <Badge variant="human" className="gap-1">
                  <PieChart className="size-3" />
                  partial run
                </Badge>
              </Tooltip>
            ) : null}
            {live ? (
              <Tooltip
                label={connected ? 'Live updates streaming' : 'Stream reconnecting — polling'}
              >
                <span className="inline-flex items-center gap-1 text-[11px] text-[var(--muted-foreground)]">
                  <Radio
                    className={cn('size-3', connected ? 'text-[var(--running)]' : 'opacity-50')}
                  />
                  {connected ? 'live' : 'polling'}
                </span>
              </Tooltip>
            ) : null}
          </span>
        }
        description={
          run.started_at
            ? `Started ${formatDateTime(run.started_at)}${
                run.finished_at ? ` · finished ${formatRelative(run.finished_at)}` : ''
              }`
            : 'Not started yet'
        }
        actions={
          <>
            {run.is_active ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  cancel.mutate(runId, {
                    onSuccess: () => toast.success('Cancel requested'),
                    onError: (e) => toast.error(e.message),
                  })
                }
              >
                <Ban />
                Cancel
              </Button>
            ) : run.is_resumable ? (
              <Button
                size="sm"
                onClick={() =>
                  resume.mutate(
                    { id: runId },
                    {
                      onSuccess: (r) =>
                        r.ok
                          ? toast.success(
                              `Resuming ${r.scheduled} ${pluralize(r.scheduled, 'item')}`,
                            )
                          : toast.info(r.message ?? 'Nothing to resume'),
                      onError: (e) => toast.error(e.message),
                    },
                  )
                }
              >
                <Play />
                Resume {run.resumable_items} {pluralize(run.resumable_items, 'item')}
              </Button>
            ) : null}

            {!run.is_active && run.totals.items > 0 ? (
              <Button
                variant="outline"
                size="sm"
                disabled={rescore.isPending}
                title="Re-run the scorers against stored outputs. No model calls, no cost."
                onClick={() =>
                  rescore.mutate(
                    { run_id: runId },
                    {
                      onSuccess: (r) =>
                        toast.success(
                          r.verdict_changes > 0
                            ? `Re-scored ${r.items_rescored} items — ${r.verdict_changes} verdicts changed`
                            : `Re-scored ${r.items_rescored} items — no verdicts changed`,
                        ),
                      onError: (e) => toast.error(e.message),
                    },
                  )
                }
              >
                <RefreshCw />
                Re-score
              </Button>
            ) : null}

            {!run.is_active ? (
              <>
                <Button asChild variant="outline" size="sm">
                  <a
                    href={runReportUrl(runId)}
                    download
                    title="One self-contained HTML file — opens offline, with the methodology attached."
                  >
                    <Download />
                    Export report
                  </a>
                </Button>
                <Button asChild variant="outline" size="sm">
                  <Link to={`/compare?runs=${runId}&view=diff`}>
                    <GitCompare />
                    Compare
                  </Link>
                </Button>
              </>
            ) : null}

            {setIds.length > 0 && !run.is_active ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  const unset = run.is_baseline_for.length > 0
                  // A partial run can still be a baseline, deliberately — but
                  // the API refuses until asked twice, because everything
                  // downstream reads a baseline as describing the whole set.
                  if (!unset && run.is_partial) {
                    setConfirmBaseline(true)
                    return
                  }
                  baseline.mutate(
                    { id: runId, setIds, unset },
                    { onSuccess: () => toast.success('Baseline updated') },
                  )
                }}
              >
                <Flag />
                {run.is_baseline_for.length > 0 ? 'Unset baseline' : 'Mark baseline'}
              </Button>
            ) : null}

            {!run.is_active ? (
              <Button
                variant="ghost"
                size="sm"
                className="text-[var(--destructive)]"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 />
                Delete
              </Button>
            ) : null}
          </>
        }
      />

      {/*
        Deleting a run is a hard delete: items, attempts, scores and saved
        artifacts all go, and there is no trash to fish them back out of. So it
        lists what it will destroy and asks for the run's name.
      */}
      {/*
        A baseline is read everywhere as "what this set normally scores". One
        drawn from part of the set silently redefines regression for every
        later diff, so it takes a deliberate second click rather than being
        refused outright — a baseline over a chosen slice is a real thing to
        want, just never by accident (D-053).
      */}
      <ConfirmDialog
        open={confirmBaseline}
        onOpenChange={setConfirmBaseline}
        title="Make a partial run the baseline?"
        description="This run did not cover the whole of every set it touched. Everything that compares against a baseline treats it as describing the set."
        impact={run.partial_coverage}
        confirmLabel="Use it as the baseline"
        busy={baseline.isPending}
        onConfirm={() => {
          baseline.mutate(
            { id: runId, setIds, unset: false, allowPartial: true },
            { onSuccess: () => toast.success('Baseline updated') },
          )
          setConfirmBaseline(false)
        }}
      />

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Delete this run?"
        description="Runs are not moved to a trash — this removes them and everything they produced."
        impact={[
          `${run.totals.items} run ${pluralize(run.totals.items, 'item')} with their attempts and outputs`,
          run.totals.scored > 0
            ? `${run.totals.scored} scores, including any you reviewed by hand`
            : null,
          'Any artifacts extracted from the model’s answers',
          run.is_baseline_for.length > 0
            ? `This run is the baseline for ${run.is_baseline_for.length} ${pluralize(run.is_baseline_for.length, 'set')} — those sets will have none.`
            : null,
        ]}
        confirmText={run.name}
        busy={remove.isPending}
        onConfirm={() =>
          remove.mutate(runId, {
            onSuccess: () => {
              toast.success('Run deleted')
              navigate('/runs')
            },
            onError: (e) => toast.error(e.message),
          })
        }
      />

      <Card className="mb-4">
        <CardContent className="flex flex-col gap-3 p-4">
          <RunTotalsRow totals={run.totals} />
          <JudgeClassRow runId={runId} />
        </CardContent>
      </Card>

      <EvaluationMetricsPanel runId={runId} config={run.config} live={live} />

      {run.error ? (
        <div className="mb-4 rounded-md border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 p-3 text-sm">
          <span className="font-medium text-[var(--destructive)]">Run failed:</span> {run.error}
        </div>
      ) : null}

      {/*
        Lane progress comes from the server, not from the loaded items: the
        item list is paginated, so counting its rows described the page. A
        2,000-item run read "500/500 done" while a quarter through.
      */}
      <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {lanes.map((lane) => {
          const laneCounts = lanesQuery.data?.find((l) => l.executor_key === lane)
          const counts = { ...emptyCounts(), ...(laneCounts?.counts ?? {}) }
          const total = laneCounts?.total ?? 0
          return (
            <Card key={lane}>
              <CardHeader className="gap-2 pb-3">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="truncate">{lane}</CardTitle>
                  <span className="tabular text-xs text-[var(--muted-foreground)]">
                    {counts.passed + counts.failed + counts.error}/{total}
                  </span>
                </div>
                <LaneProgress counts={counts} total={total} />
              </CardHeader>
            </Card>
          )
        })}
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 max-w-sm flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search items…"
            className="pl-8"
            aria-label="Search run items"
          />
        </div>
        {STATUS_FILTERS.map((status) => {
          const active = statusFilter.includes(status)
          return (
            <button
              key={status}
              type="button"
              aria-pressed={active}
              onClick={() =>
                setStatusFilter((prev) =>
                  active ? prev.filter((s) => s !== status) : [...prev, status],
                )
              }
            >
              <Badge variant={active ? 'primary' : 'outline'} className="cursor-pointer">
                {status}
              </Badge>
            </button>
          )
        })}
        {lanes.length > 1
          ? lanes.map((lane) => {
              const active = laneFilter.includes(lane)
              return (
                <button
                  key={lane}
                  type="button"
                  aria-pressed={active}
                  onClick={() =>
                    setLaneFilter((prev) =>
                      active ? prev.filter((l) => l !== lane) : [...prev, lane],
                    )
                  }
                >
                  <Badge variant={active ? 'primary' : 'outline'} className="cursor-pointer">
                    {lane}
                  </Badge>
                </button>
              )
            })
          : null}
        {/* Built from the run, so a taxonomy chip only appears if it happened. */}
        {(errorKinds.data ?? []).map((entry) => {
          const active = errorKindFilter.includes(entry.kind)
          return (
            <button
              key={entry.kind}
              type="button"
              aria-pressed={active}
              aria-label={`Filter by ${entry.kind}`}
              onClick={() =>
                setErrorKindFilter((prev) =>
                  active ? prev.filter((k) => k !== entry.kind) : [...prev, entry.kind],
                )
              }
            >
              <Badge variant={active ? 'error' : 'outline'} className="cursor-pointer gap-1">
                {entry.kind}
                <span className="tabular opacity-70">{entry.count}</span>
              </Badge>
            </button>
          )
        })}
        {statusFilter.length || laneFilter.length || errorKindFilter.length || q ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setStatusFilter([])
              setLaneFilter([])
              setErrorKindFilter([])
              setQ('')
            }}
          >
            <X />
            Clear
          </Button>
        ) : null}
        <span className="ml-auto text-xs text-[var(--muted-foreground)]">
          {itemsQuery.data?.total ?? 0} {pluralize(itemsQuery.data?.total ?? 0, 'item')}
        </span>
      </div>

      {itemsQuery.isLoading ? (
        <LoadingState label="Loading items…" rows={6} />
      ) : itemsQuery.isError ? (
        <ErrorState error={itemsQuery.error} onRetry={() => void itemsQuery.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<RotateCw className="size-6" />}
          title="No items match"
          description="Clear the filters to see the whole run."
        />
      ) : (
        <>
          <ItemTable items={items} showLane={lanes.length > 1} />
          <LoadMore
            shown={items.length}
            total={itemsQuery.data?.total ?? items.length}
            noun="item"
            onMore={more}
            busy={itemsQuery.isFetching}
          />
        </>
      )}
    </>
  )
}

function ItemTable({ items, showLane }: { items: RunItem[]; showLane: boolean }) {
  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-12">#</TableHead>
            <TableHead>Case</TableHead>
            {showLane ? <TableHead className="w-48">Executor</TableHead> : null}
            <TableHead className="w-44">Status</TableHead>
            <TableHead className="w-28">Score</TableHead>
            <TableHead>Detail</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.id}>
              <TableCell className="tabular text-xs text-[var(--muted-foreground)]">
                {item.position + 1}
              </TableCell>
              <TableCell>
                <Link
                  to={`/items/${item.id}`}
                  className="font-medium hover:text-[var(--primary)] hover:underline"
                >
                  {item.title}
                </Link>
                <div className="text-[11px] text-[var(--muted-foreground)]">{item.set_name}</div>
              </TableCell>
              {showLane ? (
                <TableCell className="text-xs text-[var(--muted-foreground)]">
                  {item.executor_key}
                </TableCell>
              ) : null}
              <TableCell>
                <ItemStatusBadge
                  status={item.status}
                  verdict={item.verdict}
                  needsHuman={item.needs_human}
                />
              </TableCell>
              <TableCell>
                <ScoreBadge verdict={item.verdict} score={item.score_value} />
              </TableCell>
              <TableCell
                className={cn(
                  'max-w-xl text-xs',
                  item.error || item.verdict === false
                    ? 'text-[var(--destructive)]'
                    : 'text-[var(--muted-foreground)]',
                )}
              >
                <Link to={`/items/${item.id}`} className="line-clamp-3 hover:underline">
                  {item.error ?? item.score_summary ?? ''}
                </Link>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

/**
 * How a class-graded judge split this run.
 *
 * Renders nothing for the scale-graded rubrics that are most of them.
 * SimpleQA is the case it exists for: its accuracy figure cannot tell a model
 * that answered wrongly from one that declined, and the catalogue told people
 * to read the not-attempted share back when the class lived only in the
 * judge's prose (D-057).
 */
function JudgeClassRow({ runId }: { runId: number }) {
  const classes = useJudgeClasses(runId)
  const rows = classes.data ?? []
  if (rows.length === 0) return null

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-[var(--border)] pt-3">
      <span className="text-[11px] uppercase tracking-wide text-[var(--muted-foreground)]">
        judge classes
      </span>
      {rows.map((row) => (
        <Stat
          key={row.name}
          label={row.name.toLowerCase()}
          value={`${row.count} · ${row.share}%`}
        />
      ))}
    </div>
  )
}
