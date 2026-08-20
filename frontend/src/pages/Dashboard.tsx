import {
  ArrowRight,
  BarChart3,
  Check,
  Layers,
  MessageSquareText,
  Play,
  PlayCircle,
} from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { useCases, useCollections, useSetOptions } from '@/api/cases'
import { useExecutors, useResumeRun, useRuns } from '@/api/runs'
import { PageHeader } from '@/components/layout/AppShell'
import { RunStatusBadge, Stat } from '@/components/RunBits'
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
  const suites = useCollections({ roots_only: true, visibility: ['primary'] })
  const resume = useResumeRun()

  const loading = runs.isLoading || sets.isLoading || suites.isLoading
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

  return (
    <>
      <PageHeader
        title="Home"
        description="Move from a manual probe to a repeatable evaluation, then review and compare."
        actions={
          runRows.length > 0 || executorRows.length > 0 ? (
            <Button asChild size="sm">
              <Link to="/runs/new">
                <Play />
                New evaluation
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
          <WorkflowActions />
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
                    <RunStatusBadge status={run.status} executionErrors={run.totals.error} />
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
                      <RunStatusBadge status={run.status} executionErrors={run.totals.error} />
                      <span className="tabular w-28 text-right text-xs">
                        <span className="block">
                          {rate === null ? '—' : `${Math.round(rate * 100)}% pass`}
                        </span>
                        <span className="block text-[11px] text-[var(--muted-foreground)]">
                          {run.totals.scored}/{run.totals.items} scored
                        </span>
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
              <CardTitle>Evaluation suites</CardTitle>
              <CardDescription>
                The primary library is organised into a few decision-oriented suites. Drill down
                only when you need a set, variant, branch, or individual case.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-1">
              {(suites.data?.items ?? []).length === 0 ? (
                <Button asChild size="sm" variant="outline" className="self-start">
                  <Link to="/sets">
                    <Layers />
                    Create your first set
                  </Link>
                </Button>
              ) : (
                (suites.data?.items ?? []).map((suite) => (
                  <Link
                    key={suite.id}
                    to={`/collections/${suite.id}`}
                    className="flex flex-wrap items-center gap-3 rounded-md border border-[var(--border)] px-2.5 py-2 transition-colors hover:border-[var(--primary)]/50"
                  >
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">
                      {suite.name}
                    </span>
                    <Badge variant="outline">{suite.descendant_set_count} sets</Badge>
                    <Badge variant="outline">{suite.descendant_case_count} cases</Badge>
                    <ArrowRight className="size-3.5 text-[var(--muted-foreground)]" />
                  </Link>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </>
  )
}

function WorkflowActions() {
  const actions = [
    {
      step: '01',
      title: 'Test manually',
      description: 'Try a conversation and inspect the raw model response.',
      to: '/playground',
      icon: MessageSquareText,
    },
    {
      step: '02',
      title: 'Build the eval',
      description: 'Organise durable cases, branches, sources and metric semantics.',
      to: '/sets',
      icon: Layers,
    },
    {
      step: '03',
      title: 'Run evaluation',
      description: 'Choose sets and executors; preflight before provider spend.',
      to: '/runs/new',
      icon: PlayCircle,
    },
    {
      step: '04',
      title: 'Review & compare',
      description: 'Resolve human items, inspect failures and measure regressions.',
      to: '/compare',
      icon: BarChart3,
    },
  ]
  return (
    <section aria-labelledby="workflow-heading">
      <div className="mb-2 flex items-center justify-between">
        <h2
          id="workflow-heading"
          className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]"
        >
          Evaluation workflow
        </h2>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {actions.map(({ step, title, description, to, icon: Icon }) => (
          <Link
            key={step}
            to={to}
            className="group flex min-h-28 flex-col rounded-lg border border-[var(--border)] bg-[var(--card)] p-3 transition-colors hover:border-[var(--primary)]/50"
          >
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-semibold tracking-widest text-[var(--primary)]">
                {step}
              </span>
              <Icon className="size-4 text-[var(--muted-foreground)] transition-colors group-hover:text-[var(--primary)]" />
            </div>
            <h3 className="mt-3 text-sm font-semibold">{title}</h3>
            <p className="mt-1 flex-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
              {description}
            </p>
            <ArrowRight className="mt-2 size-3.5 self-end text-[var(--muted-foreground)] transition-transform group-hover:translate-x-0.5" />
          </Link>
        ))}
      </div>
    </section>
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
