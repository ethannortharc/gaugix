import { AlertTriangle, ArrowLeft, CheckCircle2, Info, ListChecks, Play } from 'lucide-react'
import * as React from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { useSet, useSetOptions } from '@/api/cases'
import { ApiError } from '@/api/client'
import { useCreateRun, useExecutors, usePreflight, useRunPreview } from '@/api/runs'
import type { PreflightFinding } from '@/api/types'
import { PageHeader } from '@/components/layout/AppShell'
import { TruncatedNotice } from '@/components/LoadMore'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, Input } from '@/components/ui/input'
import { Checkbox, Switch, Tooltip } from '@/components/ui/misc'
import { formatCost, pluralize } from '@/lib/format'
import { cn } from '@/lib/utils'

export default function RunNewPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const presetSetId = React.useMemo(() => {
    const raw = searchParams.get('set_id')
    if (!raw) return undefined
    const parsed = Number(raw)
    return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined
  }, [searchParams])

  // A picker must be able to offer every set, not the first fifty (D-064).
  const sets = useSetOptions()
  // A deep link from set 501+ is still a real selection. Fetch that one row
  // separately and merge it into the capped picker so the checked choice is
  // visible and reversible instead of existing only in hidden component state.
  const presetSet = useSet(presetSetId)
  const executors = useExecutors()
  const create = useCreateRun()

  const [setIds, setSetIds] = React.useState<number[]>(() =>
    presetSetId === undefined ? [] : [presetSetId],
  )
  // A subset arrives from "Run these cases" on a set page. Null means the whole of
  // every chosen set, which is the ordinary case and stays the default.
  const [caseIds, setCaseIds] = React.useState<number[] | null>(() => {
    const preset = searchParams.get('case_ids')
    if (!preset) return null
    const parsed = preset
      .split(',')
      .map(Number)
      .filter((n) => Number.isFinite(n))
    return parsed.length > 0 ? parsed : null
  })
  const [executorIds, setExecutorIds] = React.useState<number[]>([])
  const [name, setName] = React.useState('')
  const [concurrency, setConcurrency] = React.useState(4)
  const [autoScore, setAutoScore] = React.useState(true)
  const [acceptedCode, setAcceptedCode] = React.useState(false)

  const missingPreset =
    presetSetId !== undefined &&
    presetSet.isError &&
    presetSet.error instanceof ApiError &&
    presetSet.error.status === 404
  const trashedPreset = presetSet.data?.deleted_at != null
  const unavailablePreset = missingPreset || trashedPreset
  const activeSetIds = unavailablePreset ? setIds.filter((id) => id !== presetSetId) : setIds

  React.useEffect(() => {
    if (!unavailablePreset || presetSetId === undefined) return
    setSetIds((current) => current.filter((id) => id !== presetSetId))
    setCaseIds(null)
  }, [presetSetId, unavailablePreset])

  const preview = useRunPreview(activeSetIds, executorIds, caseIds)
  // Free and read-only, so it runs alongside the preview on every change.
  const preflight = usePreflight(activeSetIds, executorIds, caseIds, autoScore)
  const blocked = preflight.data ? !preflight.data.ok : false
  const needsCodeAck = preflight.data?.requires_code_execution === true
  const codeBlocked = needsCodeAck && !acceptedCode

  function toggleSet(id: number) {
    // Changing which sets are in play invalidates a case subset picked against
    // the old selection — a set added underneath it would contribute nothing.
    setCaseIds(null)
    setSetIds(setIds.includes(id) ? setIds.filter((x) => x !== id) : [...setIds, id])
  }

  function launch() {
    create.mutate(
      {
        set_ids: activeSetIds,
        executor_ids: executorIds,
        case_ids: caseIds,
        name: name.trim() || undefined,
        concurrency,
        auto_score: autoScore,
        start: true,
        accept_code_execution: acceptedCode,
      },
      {
        onSuccess: (run) => {
          toast.success(`Launched “${run.name}”`)
          navigate(`/runs/${run.id}`)
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  if (sets.isLoading || executors.isLoading || presetSet.isLoading)
    return <LoadingState label="Loading…" />
  if (sets.isError) return <ErrorState error={sets.error} onRetry={() => void sets.refetch()} />
  if (presetSet.isError && !missingPreset)
    return <ErrorState error={presetSet.error} onRetry={() => void presetSet.refetch()} />
  if (executors.isError)
    return <ErrorState error={executors.error} onRetry={() => void executors.refetch()} />

  const listedSets = sets.data?.items ?? []
  const setRows =
    presetSet.data && !trashedPreset
      ? [...listedSets.filter((set) => set.id !== presetSet.data.id), presetSet.data]
      : listedSets
  const executorRows = executors.data?.items ?? []
  const ready = activeSetIds.length > 0 && executorIds.length > 0

  if (setRows.length === 0 || executorRows.length === 0) {
    return (
      <>
        <PageHeader title="New run" />
        <EmptyState
          icon={<AlertTriangle className="size-6" />}
          title={setRows.length === 0 ? 'No eval sets yet' : 'No executors yet'}
          description={
            setRows.length === 0
              ? 'A run needs at least one set of cases.'
              : 'A run needs at least one executor — a model profile paired with a harness.'
          }
          action={
            <Button asChild size="sm">
              <Link to={setRows.length === 0 ? '/sets' : '/executors'}>
                {setRows.length === 0 ? 'Go to eval sets' : 'Go to executors'}
              </Link>
            </Button>
          }
        />
      </>
    )
  }

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
            New run
          </span>
        }
        description="Pick sets and executors. Each case is sent to each executor once, so items = cases × executors."
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr_320px]">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Eval sets</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-1.5">
            {unavailablePreset ? (
              <p
                role="alert"
                className="mb-1 rounded-md border border-[var(--warning)]/40 bg-[var(--warning)]/8 px-2.5 py-2 text-xs"
              >
                The set from this link is no longer available. Choose another set.
              </p>
            ) : null}
            {/*
              A subset is a promise about what the run will mean, so it is stated
              at the point of choosing rather than only in the preview — and it
              is one click to undo, because "run the whole thing after all" is
              the commonest correction.
            */}
            {caseIds ? (
              <div className="mb-1 flex flex-wrap items-center gap-2 rounded-md border border-[var(--primary)]/40 bg-[var(--primary)]/8 px-2.5 py-2 text-xs">
                <ListChecks className="size-3.5 shrink-0" />
                <span className="min-w-0 flex-1">
                  Running <strong>{caseIds.length}</strong> chosen{' '}
                  {pluralize(caseIds.length, 'case')}, not the whole set.
                </span>
                <Button variant="outline" size="sm" onClick={() => setCaseIds(null)}>
                  Use the whole set
                </Button>
              </div>
            ) : null}
            {setRows.map((set) => (
              <label
                key={set.id}
                className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-[var(--muted)]"
              >
                <Checkbox
                  checked={setIds.includes(set.id)}
                  onCheckedChange={() => toggleSet(set.id)}
                  aria-label={`Select set ${set.name}`}
                />
                <span className="min-w-0 flex-1 truncate text-sm">{set.name}</span>
                <Badge variant="outline" className="tabular">
                  {set.case_count}
                </Badge>
              </label>
            ))}
            {/*
              Past the API's ceiling this list is not the library. A run built
              from it would silently be a run over the sets that happened to
              fit, which is the failure the 50-set fix was supposed to end.
            */}
            <TruncatedNotice
              shown={setRows.length}
              total={Math.max(sets.total, setRows.length)}
              noun="set"
              hint="Open an omitted set and choose “Run this set” to start from it."
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Executors</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-1.5">
            {executorRows.map((executor) => (
              <label
                key={executor.id}
                className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-[var(--muted)]"
              >
                <Checkbox
                  checked={executorIds.includes(executor.id)}
                  onCheckedChange={() =>
                    setExecutorIds(
                      executorIds.includes(executor.id)
                        ? executorIds.filter((x) => x !== executor.id)
                        : [...executorIds, executor.id],
                    )
                  }
                  aria-label={`Select executor ${executor.name}`}
                />
                <span className="min-w-0 flex-1 truncate text-sm">{executor.name}</span>
                <Badge variant={executor.provider === 'fake' ? 'default' : 'outline'}>
                  {executor.provider}
                </Badge>
              </label>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Matrix preview</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {!ready ? (
              <p className="text-sm text-[var(--muted-foreground)]">
                Choose at least one set and one executor.
              </p>
            ) : preview.isLoading ? (
              <LoadingState label="Computing…" rows={1} />
            ) : preview.isError ? (
              <ErrorState error={preview.error} />
            ) : preview.data ? (
              <>
                <div className="flex items-baseline gap-2">
                  <span className="tabular text-3xl font-semibold">{preview.data.item_count}</span>
                  <span className="text-sm text-[var(--muted-foreground)]">
                    {pluralize(preview.data.item_count, 'item')}
                  </span>
                </div>
                <p className="text-xs text-[var(--muted-foreground)]">
                  {caseIds
                    ? `${preview.data.case_count} of ${preview.data.available_case_count} `
                    : `${preview.data.case_count} `}
                  {pluralize(preview.data.case_count, 'case')} × {preview.data.executor_count}{' '}
                  {pluralize(preview.data.executor_count, 'executor')} — every case is sent to every
                  executor once.
                </p>

                <div className="flex flex-col gap-1 border-t border-[var(--border)] pt-3">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-[var(--muted-foreground)]">Estimated cost</span>
                    {preview.data.estimated_cost_usd === null ? (
                      <Tooltip label="At least one model has no known pricing. Add rates in Settings for an estimate.">
                        <span className="text-[var(--muted-foreground)]">unknown</span>
                      </Tooltip>
                    ) : (
                      <span className="tabular font-medium">
                        ≥ {formatCost(preview.data.estimated_cost_usd)}
                      </span>
                    )}
                  </div>
                  {/*
                    The assumptions travel with the number. "~$0.42" with no
                    stated basis gets repeated as a quote; a lower bound with
                    its token assumption printed underneath does not.
                  */}
                  {/*
                    Judge calls are a second call per item, and a run that hides
                    them under one number understates a judged benchmark by more
                    than half. Shown as its own line, not folded into the total.
                  */}
                  {preflight.data && preflight.data.judge_call_count > 0 ? (
                    <div className="flex items-center justify-between text-xs text-[var(--muted-foreground)]">
                      <span>
                        of which {preflight.data.judge_call_count} judge{' '}
                        {pluralize(preflight.data.judge_call_count, 'call')}
                      </span>
                      <span className="tabular">
                        {preflight.data.estimated_judge_cost_usd === null
                          ? 'unknown'
                          : formatCost(preflight.data.estimated_judge_cost_usd)}
                      </span>
                    </div>
                  ) : null}
                  {preflight.data?.cost_assumptions ? (
                    <p className="text-[11px] leading-snug text-[var(--muted-foreground)]">
                      {preflight.data.cost_assumptions}
                    </p>
                  ) : null}
                </div>

                <PreflightPanel findings={preflight.data?.findings ?? []} />

                {/*
                  The install-time acknowledgement covered installing the data.
                  This one covers running it: a benchmark installed weeks ago
                  still executes model output on this machine today, and the
                  moment that happens is here (D-049).
                */}
                {needsCodeAck ? (
                  <label className="flex cursor-pointer items-start gap-2 rounded-md border border-[var(--destructive)]/50 bg-[var(--destructive)]/10 px-3 py-2 text-xs">
                    <Checkbox
                      checked={acceptedCode}
                      onCheckedChange={(checked) => setAcceptedCode(checked === true)}
                      aria-label="Accept running model-written code on this machine"
                      className="mt-0.5"
                    />
                    <span>
                      I accept that scoring this run <strong>executes model-written code</strong> on
                      this machine — with my user's permissions and no sandbox —
                      {preflight.data && preflight.data.code_execution_sets.length > 0
                        ? ` from ${preflight.data.code_execution_sets.join(', ')}.`
                        : '.'}
                    </span>
                  </label>
                ) : null}

                <Field label="Run name" htmlFor="run-name">
                  <Input
                    id="run-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={preview.data.suggested_name}
                  />
                </Field>

                <Field
                  label="Concurrency"
                  hint="1 runs serially — useful when a provider rate-limits."
                  htmlFor="run-concurrency"
                >
                  <Input
                    id="run-concurrency"
                    type="number"
                    min={1}
                    max={64}
                    value={concurrency}
                    onChange={(e) => setConcurrency(Math.max(1, Number(e.target.value)))}
                  />
                </Field>

                <label className="flex items-center justify-between gap-2 text-sm">
                  <span>Score automatically</span>
                  <Switch
                    checked={autoScore}
                    onCheckedChange={setAutoScore}
                    aria-label="Score automatically"
                  />
                </label>

                <Button onClick={launch} disabled={create.isPending || blocked || codeBlocked}>
                  <Play />
                  {create.isPending
                    ? 'Launching…'
                    : blocked
                      ? 'Fix the blockers first'
                      : codeBlocked
                        ? 'Accept code execution first'
                        : 'Launch run'}
                </Button>
              </>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </>
  )
}

/**
 * What preflight found, worst first.
 *
 * Blockers disable the launch button; warnings and notes do not. That
 * distinction is the whole design — a page that treats "this model has no
 * price" the same as "this regex will not compile" trains people to click
 * through both.
 */
function PreflightPanel({ findings }: { findings: PreflightFinding[] }) {
  const order: PreflightFinding['severity'][] = ['blocker', 'warning', 'note']
  const sorted = [...findings].sort((a, b) => order.indexOf(a.severity) - order.indexOf(b.severity))

  if (sorted.length === 0) {
    return (
      <p className="flex items-center gap-2 rounded-md border border-[var(--pass)]/40 bg-[var(--pass)]/10 px-3 py-2 text-xs text-[var(--pass)]">
        <CheckCircle2 className="size-3.5 shrink-0" />
        Nothing to flag: every scorer is valid, every key is present, and every case will be scored.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-1.5">
      {sorted.map((finding, index) => (
        <div
          key={index}
          className={cn(
            'flex gap-2 rounded-md border px-3 py-2 text-xs',
            finding.severity === 'blocker'
              ? 'border-[var(--destructive)]/50 bg-[var(--destructive)]/10'
              : finding.severity === 'warning'
                ? 'border-[var(--human)]/40 bg-[var(--human)]/10'
                : 'border-[var(--border)] bg-[var(--muted)]/40',
          )}
        >
          {finding.severity === 'blocker' ? (
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-[var(--destructive)]" />
          ) : finding.severity === 'warning' ? (
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          ) : (
            <Info className="mt-0.5 size-3.5 shrink-0" />
          )}
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="font-medium">{finding.message}</span>
            {finding.detail ? (
              <span className="text-[var(--muted-foreground)]">{finding.detail}</span>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  )
}
