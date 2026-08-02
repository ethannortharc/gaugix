import { Check, Layers, Play, PlayCircle } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { useCases, useSetOptions } from '@/api/cases'
import { useExecutors, useResumeRun, useRuns, useSetTrends } from '@/api/runs'
import { PageHeader } from '@/components/layout/AppShell'
import { RunStatusBadge, Sparkline, Stat } from '@/components/RunBits'
import { TruncatedNotice } from '@/components/LoadMore'
import { ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatCost, formatRelative, pluralize } from '@/lib/format'

export default function DashboardPage() {
  const runs = useRuns({ limit: 8 })
  const sets = useSetOptions()
  // One row, fetched only for its X-Total-Count header: the library's size.
  const allCases = useCases({ limit: 1 })
  const executors = useExecutors()
  const trends = useSetTrends()
  const resume = useResumeRun()

  const loading = runs.isLoading || sets.isLoading
  const runRows = React.useMemo(() => runs.data?.items ?? [], [runs.data])
  const setRows = sets.data?.items ?? []
  const executorRows = executors.data?.items ?? []
  /*
    The tiles count the library, not the page. `sets` is paginated, so
    `setRows.length` capped at 50 and `totalCases` summed only those fifty —
    a library of 300 sets reported 50, and always would have.
  */
  const setTotal = sets.data?.total ?? setRows.length
  const caseTotal = allCases.data?.total ?? null
  // `is_resumable` now means "a resume would schedule something", so the
  // status check that used to paper over completed runs is no longer needed.
  const resumable = runRows.filter((r) => r.is_resumable)

  // The checklist stays until the whole path is walked. It used to vanish the
  // moment a set existed, which is exactly one step in — leaving someone who
  // had created a set and nothing else on an empty dashboard with no next step.
  const setupIncomplete = setRows.length === 0 || executorRows.length === 0 || runRows.length === 0

  /**
   * Pass rate per set across recent runs, oldest first.
   *
   * The server splits this per set. It used to be derived here from each run's
   * *overall* rate, which meant a run covering three sets plotted one identical
   * number on all three lines — one set's regression showed up in its
   * neighbours' history, and a healthy set inherited a sick one's dip.
   */
  const setHistory = React.useMemo(() => {
    const history = new Map<number, number[]>()
    for (const trend of trends.data ?? []) {
      history.set(
        trend.set_id,
        trend.points.map((p) => p.pass_rate),
      )
    }
    return history
  }, [trends.data])

  /*
    The server leaves partial runs out of these lines: a rate over two of five
    cases has nothing to do with a rate over five, and plotting them together
    is how "Guardrail regression: 100%" came to mean two passing cases. The
    count comes back so the shorter line can be explained (D-053).
  */
  const excludedPartials = React.useMemo(() => {
    const excluded = new Map<number, number>()
    for (const trend of trends.data ?? []) {
      if (trend.partial_runs_excluded > 0) excluded.set(trend.set_id, trend.partial_runs_excluded)
    }
    return excluded
  }, [trends.data])

  const baselineSets = React.useMemo(
    () => new Set(runRows.flatMap((run) => run.is_baseline_for)),
    [runRows],
  )

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Where things stand, and what is waiting on you."
        actions={
          runRows.length > 0 || executorRows.length > 0 ? (
            <Button asChild size="sm">
              <Link to="/runs/new">
                <Play />
                New run
              </Link>
            </Button>
          ) : null
        }
      />

      {loading ? (
        <LoadingState label="Loading dashboard…" rows={4} />
      ) : runs.isError ? (
        <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
      ) : (
        <div className="flex flex-col gap-4">
          {setupIncomplete ? (
            <SetupChecklist
              hasSet={setRows.length > 0}
              hasExecutor={executorRows.length > 0}
              hasRun={runRows.length > 0}
            />
          ) : null}
          <Card>
            <CardContent className="flex flex-wrap items-center gap-x-10 gap-y-3 p-4">
              <Stat label="eval sets" value={setTotal} />
              <Stat label="cases" value={caseTotal ?? '—'} />
              <Stat label="executors" value={executorRows.length} />
              <Stat label="runs" value={runs.data?.total ?? runRows.length} />
            </CardContent>
          </Card>

          {resumable.length > 0 ? (
            <Card className="border-[var(--error)]/40">
              <CardHeader className="pb-2">
                <CardTitle>Unfinished runs</CardTitle>
                <CardDescription>
                  These stopped before completing. Resuming re-executes only what is unfinished —
                  passed and failed items are never redone.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {resumable.map((run) => (
                  <div
                    key={run.id}
                    className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--border)] px-2.5 py-2"
                  >
                    <Link
                      to={`/runs/${run.id}`}
                      className="min-w-0 flex-1 truncate text-sm font-medium hover:underline"
                    >
                      {run.name}
                    </Link>
                    <RunStatusBadge status={run.status} />
                    <span className="tabular text-xs text-[var(--muted-foreground)]">
                      {run.resumable_items} left
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        resume.mutate(
                          { id: run.id },
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
                      Resume
                    </Button>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Recent runs</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {runRows.length === 0 ? (
                <div className="flex flex-col items-start gap-2 py-2">
                  <p className="text-sm text-[var(--muted-foreground)]">
                    No runs yet — you have {setRows.length} {pluralize(setRows.length, 'set')} ready
                    to go.
                  </p>
                  <Button asChild size="sm">
                    <Link to="/runs/new">
                      <PlayCircle />
                      Start your first run
                    </Link>
                  </Button>
                </div>
              ) : (
                runRows.map((run) => {
                  const rate =
                    run.totals.scored > 0 ? run.totals.verdict_passed / run.totals.scored : null
                  return (
                    <Link
                      key={run.id}
                      to={`/runs/${run.id}`}
                      className="flex flex-wrap items-center gap-3 rounded-md border border-[var(--border)] px-2.5 py-2 transition-colors hover:border-[var(--primary)]/50"
                    >
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">
                        {run.name}
                      </span>
                      {run.is_baseline_for.length > 0 ? (
                        <Badge variant="primary">baseline</Badge>
                      ) : null}
                      <RunStatusBadge status={run.status} />
                      <span className="tabular w-24 text-right text-xs">
                        {rate === null ? '—' : `${Math.round(rate * 100)}% pass`}
                      </span>
                      {/*
                        A run with an unpriced model reported `$0.00` here and
                        `≥ $0.00` on its own page. One of those is a claim the
                        run was free; the two must not disagree.
                      */}
                      <span
                        className="tabular w-20 text-right text-xs text-[var(--muted-foreground)]"
                        title={
                          run.totals.cost_unknown
                            ? 'At least this much — a model in this run has no known price.'
                            : undefined
                        }
                      >
                        {run.totals.cost_unknown ? '≥ ' : ''}
                        {formatCost(run.totals.cost_usd)}
                      </span>
                      <span className="w-24 text-right text-xs text-[var(--muted-foreground)]">
                        {formatRelative(run.created_at)}
                      </span>
                    </Link>
                  )
                })
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Eval sets</CardTitle>
              <CardDescription>
                Pass rate over this set’s recent runs, oldest first. A set with no baseline has
                nothing to regress against.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-1">
              {setRows.length === 0 ? (
                <Button asChild size="sm" variant="outline" className="self-start">
                  <Link to="/sets">
                    <Layers />
                    Create your first set
                  </Link>
                </Button>
              ) : (
                setRows.map((set) => {
                  const history = setHistory.get(set.id) ?? []
                  const latest = history.at(-1) ?? null
                  const hasBaseline = baselineSets.has(set.id)
                  const skipped = excludedPartials.get(set.id) ?? 0
                  return (
                    <div
                      key={set.id}
                      className="flex flex-wrap items-center gap-3 rounded-md border border-[var(--border)] px-2.5 py-2"
                    >
                      <Link
                        to={`/sets/${set.id}`}
                        className="min-w-0 flex-1 truncate text-sm font-medium hover:underline"
                      >
                        {set.name}
                      </Link>
                      <span className="tabular text-xs text-[var(--muted-foreground)]">
                        {set.case_count} {pluralize(set.case_count, 'case')}
                      </span>
                      {hasBaseline ? (
                        <Badge variant="primary">baseline set</Badge>
                      ) : (
                        <Badge variant="outline" title="Mark a run as baseline to enable the diff">
                          no baseline
                        </Badge>
                      )}
                      {skipped > 0 ? (
                        <Badge
                          variant="outline"
                          title={`${skipped} run(s) covered only part of this set. Their pass rates describe those cases, not the set, so they are not on this line.`}
                        >
                          {skipped} partial {pluralize(skipped, 'run')} not shown
                        </Badge>
                      ) : null}
                      <Sparkline values={history} />
                      <span className="tabular w-16 text-right text-xs">
                        {latest === null ? '—' : `${Math.round(latest)}%`}
                      </span>
                    </div>
                  )
                })
              )}
              {/* This card lists sets, so past the ceiling it is listing some
                  of them. The tile above already counts the whole library, and
                  the two disagreeing without explanation is worse than either. */}
              <TruncatedNotice
                shown={setRows.length}
                total={setTotal}
                noun="set"
                hint="Open the library to see the rest."
              />
            </CardContent>
          </Card>
        </div>
      )}
    </>
  )
}

/**
 * What to do first, in order, on an empty install.
 *
 * Model profile, harness and executor is a three-layer idea that is right and
 * is not obvious in five seconds. A checklist that names the layers in the
 * order you meet them beats a paragraph explaining them, and installing a
 * benchmark sample is the fastest honest way to get a populated set — five real
 * cases, offline, with the scorer they were designed for.
 */
function SetupChecklist({
  hasSet,
  hasExecutor,
  hasRun,
}: {
  hasSet: boolean
  hasExecutor: boolean
  hasRun: boolean
}) {
  const steps = [
    {
      done: hasSet,
      title: 'Get some cases',
      body: 'Write a set by hand, import a file, or install a benchmark sample — five real cases, offline, each arriving with a scorer already configured.',
      to: '/benchmarks',
      cta: 'Browse benchmarks',
      alt: { to: '/sets', label: 'Create a set' },
    },
    {
      done: hasExecutor,
      title: 'Set up something to run them against',
      body: 'An executor is a model profile (which model, which key) paired with a harness (how to call it). The fake harness needs no key and costs nothing — use it to see the loop first.',
      to: '/executors',
      cta: 'Set up an executor',
    },
    {
      done: hasRun,
      title: 'Run it and read the result',
      body: 'A run sends every case to every executor once. Preflight checks the scorers and keys before anything is spent.',
      to: '/runs/new',
      cta: 'Start a run',
    },
  ]

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>Getting started</CardTitle>
        <CardDescription>
          Gaugix measures how models do on <em>your</em> tasks. Three steps, and the first two are
          free.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {steps.map((step, index) => (
          <div
            key={step.title}
            className="flex gap-3 rounded-md border border-[var(--border)] px-3 py-2.5"
          >
            <span
              className={`mt-0.5 grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-semibold ${
                step.done
                  ? 'bg-[var(--pass)]/20 text-[var(--pass)]'
                  : 'bg-[var(--muted)] text-[var(--muted-foreground)]'
              }`}
            >
              {step.done ? <Check className="size-3" /> : index + 1}
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <span className="text-sm font-medium">{step.title}</span>
              <p className="text-xs text-[var(--muted-foreground)]">{step.body}</p>
              {!step.done ? (
                <div className="flex flex-wrap gap-2 pt-0.5">
                  <Button asChild size="sm">
                    <Link to={step.to}>{step.cta}</Link>
                  </Button>
                  {step.alt ? (
                    <Button asChild variant="outline" size="sm">
                      <Link to={step.alt.to}>{step.alt.label}</Link>
                    </Button>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
