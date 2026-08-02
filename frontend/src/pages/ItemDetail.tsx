import {
  ArrowLeft,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  History,
  Paperclip,
  RefreshCw,
  RotateCw,
  SkipForward,
} from 'lucide-react'
import * as React from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { useItemArtifacts } from '@/api/artifacts'
import { useItemScoreHistory, useRerunFrom, useRescore, useRetryItem, useRunItem } from '@/api/runs'
import type { AttemptRead, RunItemDetail, ScorerSpec } from '@/api/types'
import { ArtifactList, ArtifactViewer, RunArtifact } from '@/components/ArtifactViewer'
import { HumanScorePanel } from '@/components/HumanScorePanel'
import { PageHeader } from '@/components/layout/AppShell'
import { ItemStatusBadge, ScoreBadge, Stat } from '@/components/RunBits'
import { ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/misc'
import {
  formatCost,
  formatDateTime,
  formatDurationMs,
  formatScore,
  formatTokens,
} from '@/lib/format'

export default function ItemDetailPage() {
  const params = useParams()
  const itemId = Number(params.id)
  const query = useRunItem(itemId)
  const [showSuperseded, setShowSuperseded] = React.useState(false)
  const [showHistory, setShowHistory] = React.useState(false)

  if (query.isLoading) return <LoadingState label="Loading item…" />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  if (!query.data) return null

  const item = query.data
  const attempts = item.attempts.filter((a) => showSuperseded || !a.superseded)
  const current = item.attempts.filter((a) => !a.superseded).at(-1) ?? item.attempts.at(-1)
  const supersededCount = item.attempts.filter((a) => a.superseded).length

  return (
    <>
      <PageHeader
        title={
          <span className="flex min-w-0 items-center gap-2">
            <Button asChild variant="ghost" size="icon-sm" aria-label="Back to run">
              <Link to={`/runs/${item.run_id}`}>
                <ArrowLeft />
              </Link>
            </Button>
            <span className="truncate">{item.title}</span>
          </span>
        }
        description={
          <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
            <Link
              to={`/runs/${item.run_id}`}
              className="hover:text-[var(--primary)] hover:underline"
            >
              {item.run_name || `Run ${item.run_id}`}
            </Link>
            <span aria-hidden>›</span>
            {item.set_id ? (
              <Link
                to={`/sets/${item.set_id}`}
                className="hover:text-[var(--primary)] hover:underline"
              >
                {item.set_name}
              </Link>
            ) : (
              <span>{item.set_name}</span>
            )}
            <Badge variant="outline">{item.executor_key}</Badge>
          </span>
        }
        actions={<LaneNav item={item} />}
      />

      {/*
        Verdict, cost and the things you can do about them, on one line. They
        were spread across the header and the foot of every attempt row, so the
        two questions this page exists to answer — did it pass, what did it
        cost — were never in view together.
      */}
      <ItemToolbar item={item} current={current} />

      {item.error ? (
        <div className="mb-4 rounded-md border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 p-3 text-sm">
          <span className="font-medium text-[var(--destructive)]">Error:</span> {item.error}
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <div className="flex min-w-0 flex-col gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Input</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {item.input.map((message, index) => (
                <div key={index} className="rounded-md border border-[var(--border)]">
                  <div className="border-b border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)]">
                    {message.role}
                  </div>
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words px-2.5 py-2 font-mono text-xs leading-relaxed">
                    {message.content}
                  </pre>
                </div>
              ))}
            </CardContent>
          </Card>

          {/*
            Output and reference in one card, side by side where there is room.
            The question is nearly always "how does this differ from what was
            expected", and answering it meant scrolling past two other cards.
          */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle>{item.reference ? 'Output vs reference' : 'Output'}</CardTitle>
            </CardHeader>
            <CardContent
              className={item.reference ? 'grid gap-3 lg:grid-cols-2' : 'flex flex-col gap-3'}
            >
              <TextPane
                label="model output"
                text={current?.output_text ?? ''}
                fallback={current?.error ? `No output — ${current.error}` : 'No output yet.'}
              />
              {item.reference ? <TextPane label="reference" text={item.reference} /> : null}
            </CardContent>
          </Card>

          <ArtifactsCard itemId={item.id} />
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          {item.needs_human ? (
            <HumanScorePanel
              itemId={item.id}
              scorerIndex={humanScorerIndex(item.case_snapshot.scoring ?? [])}
              spec={
                (item.case_snapshot.scoring ?? [])[
                  humanScorerIndex(item.case_snapshot.scoring ?? [])
                ]
              }
            />
          ) : null}

          <Card>
            <CardHeader className="flex-row items-center justify-between pb-2">
              <CardTitle>Scores</CardTitle>
              {/*
                A re-score or a human override supersedes the previous version
                rather than erasing it. Showing only the latest hid exactly the
                thing a calibration argument turns on: what changed, and why.
              */}
              <Button
                variant="ghost"
                size="sm"
                className="text-xs"
                onClick={() => setShowHistory((v) => !v)}
              >
                <History className="size-3.5" />
                {showHistory ? 'Latest only' : 'Version history'}
              </Button>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {showHistory ? (
                <ScoreHistory itemId={item.id} />
              ) : item.scores.length === 0 ? (
                <p className="text-sm text-[var(--muted-foreground)]">
                  No scores recorded. This item ran but nothing was configured to judge it — which
                  is why the status reads “done (unscored)” rather than “passed”.
                </p>
              ) : (
                item.scores.map((score) => (
                  <div key={score.id} className="rounded-md border border-[var(--border)] p-2.5">
                    <div className="mb-1 flex flex-wrap items-center gap-1.5">
                      <Badge variant="outline">{score.scorer_type}</Badge>
                      <Badge
                        variant={
                          score.passed === true ? 'pass' : score.passed === false ? 'fail' : 'error'
                        }
                      >
                        {score.passed === true
                          ? 'pass'
                          : score.passed === false
                            ? 'fail'
                            : 'scorer error'}
                      </Badge>
                      {score.value !== null ? (
                        <span className="tabular text-xs">{formatScore(score.value)}</span>
                      ) : null}
                      <Badge variant={score.source === 'human' ? 'human' : 'default'}>
                        {score.source}
                      </Badge>
                      {score.version > 1 ? <Badge variant="outline">v{score.version}</Badge> : null}
                    </div>
                    {score.rationale ? (
                      <p className="whitespace-pre-wrap text-xs text-[var(--muted-foreground)]">
                        {score.rationale}
                      </p>
                    ) : null}
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center justify-between pb-2">
              <CardTitle>Attempts</CardTitle>
              {supersededCount > 0 ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowSuperseded((v) => !v)}
                  className="text-xs"
                >
                  <History />
                  {showSuperseded ? 'Hide' : `Show ${supersededCount} superseded`}
                </Button>
              ) : null}
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {attempts.map((attempt) => (
                <AttemptRow key={attempt.id} attempt={attempt} />
              ))}
            </CardContent>
          </Card>

          <FrozenScoring scoring={item.case_snapshot.scoring ?? []} />
        </div>
      </div>
    </>
  )
}

/** Index of the first human scorer — the one the review panel resolves. */
function humanScorerIndex(scoring: ScorerSpec[]): number {
  const index = scoring.findIndex((s) => s.type === 'human')
  return index === -1 ? 0 : index
}

/**
 * Move between items in this executor lane without going back to the board.
 *
 * Reading a run means reading its failures one after another, and the round
 * trip through the item list to reach the next one was the whole of that loop.
 * The neighbours come from the server, so this costs the same on a 5,000-item
 * run as on a five-item one.
 */
function LaneNav({ item }: { item: RunItemDetail }) {
  if (item.lane_total <= 1) return null
  return (
    <span className="flex items-center gap-1">
      <Button
        asChild={item.prev_item_id !== null}
        variant="outline"
        size="icon-sm"
        disabled={item.prev_item_id === null}
        aria-label="Previous item in this lane"
      >
        {item.prev_item_id !== null ? (
          <Link to={`/items/${item.prev_item_id}`}>
            <ChevronLeft />
          </Link>
        ) : (
          <ChevronLeft />
        )}
      </Button>
      <span className="tabular whitespace-nowrap px-1 text-xs text-[var(--muted-foreground)]">
        {item.lane_position} / {item.lane_total}
      </span>
      <Button
        asChild={item.next_item_id !== null}
        variant="outline"
        size="icon-sm"
        disabled={item.next_item_id === null}
        aria-label="Next item in this lane"
      >
        {item.next_item_id !== null ? (
          <Link to={`/items/${item.next_item_id}`}>
            <ChevronRight />
          </Link>
        ) : (
          <ChevronRight />
        )}
      </Button>
    </span>
  )
}

/** Verdict and cost on the left, the three things you can do on the right. */
function ItemToolbar({ item, current }: { item: RunItemDetail; current?: AttemptRead }) {
  const rescore = useRescore()
  const rerunFrom = useRerunFrom()
  const retry = useRetryItem()

  const tokens = item.attempts.reduce((n, a) => n + a.prompt_tokens + a.completion_tokens, 0)
  // A null cost is unknown, not zero — summing it as zero would report an
  // unpriced model as free. Unknown anywhere makes the total unknown.
  const cost = item.attempts.some((a) => a.cost_usd === null)
    ? null
    : item.attempts.reduce((n, a) => n + (a.cost_usd ?? 0), 0)

  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-5 gap-y-3 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2.5">
      <ItemStatusBadge status={item.status} verdict={item.verdict} needsHuman={item.needs_human} />
      <ScoreBadge verdict={item.verdict} score={item.score_value} />
      <Separator orientation="vertical" className="hidden h-6 sm:block" />
      <Stat label="tokens" value={formatTokens(tokens)} />
      <Stat label="cost" value={cost === null ? 'unknown' : formatCost(cost)} />
      <Stat label="latency" value={formatDurationMs(current?.latency_ms ?? 0)} />
      <Stat label="attempts" value={item.attempts.length} />

      <span className="ml-auto flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={rescore.isPending}
          title="Re-run the scorers against the stored output — no model call, no cost."
          onClick={() =>
            rescore.mutate(
              { item_ids: [item.id] },
              {
                onSuccess: (r) =>
                  toast.success(
                    r.verdict_changes > 0
                      ? 'Re-scored — the verdict changed'
                      : 'Re-scored — the verdict is unchanged',
                  ),
                onError: (e) => toast.error(e.message),
              },
            )
          }
        >
          <RefreshCw />
          Re-score
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={retry.isPending}
          title="Re-execute only this item. Nothing else in the run is touched — the cheap fix for one rate-limited or timed-out call."
          onClick={() =>
            retry.mutate(
              { runId: item.run_id, itemId: item.id },
              {
                onSuccess: () => toast.success('Retrying this item'),
                onError: (e) => toast.error(e.message),
              },
            )
          }
        >
          <RotateCw />
          Retry
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={rerunFrom.isPending}
          title="Re-execute this item and every later one in the same executor lane. Earlier items and other lanes are left alone."
          onClick={() =>
            rerunFrom.mutate(
              { runId: item.run_id, itemId: item.id },
              {
                onSuccess: (r) =>
                  r.ok
                    ? toast.success(`Rerunning ${r.affected} items from here`)
                    : toast.info(r.message ?? 'Nothing to rerun'),
                onError: (e) => toast.error(e.message),
              },
            )
          }
        >
          <SkipForward />
          Rerun from here
        </Button>
      </span>
    </div>
  )
}

/** One labelled block of monospace text, scrollable rather than endless. */
function TextPane({ label, text, fallback }: { label: string; text: string; fallback?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        {label}
      </span>
      {text ? (
        <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap break-words rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-2 font-mono text-xs leading-relaxed">
          {text}
        </pre>
      ) : (
        <p className="text-sm text-[var(--muted-foreground)]">{fallback ?? '—'}</p>
      )}
    </div>
  )
}

/**
 * The scoring config as it was frozen at plan time.
 *
 * Summarised, not dumped. A HumanEval case's frozen config carries the whole
 * unit-test file, and printing it expanded pushed the scores and attempts a
 * screen and a half down the page — so each scorer opens on its own.
 */
function FrozenScoring({ scoring }: { scoring: ScorerSpec[] }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>Scoring config (frozen)</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-1.5">
        {scoring.length === 0 ? (
          <p className="text-xs text-[var(--muted-foreground)]">
            No scorers were configured when this run was planned.
          </p>
        ) : (
          scoring.map((spec, index) => <FrozenScorer key={index} spec={spec} index={index} />)
        )}
      </CardContent>
    </Card>
  )
}

function FrozenScorer({ spec, index }: { spec: ScorerSpec; index: number }) {
  const [open, setOpen] = React.useState(false)
  const params = JSON.stringify(spec.params ?? {}, null, 2)
  const empty = params === '{}'

  return (
    <div className="rounded-md border border-[var(--border)]">
      <button
        type="button"
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left hover:bg-[var(--muted)] disabled:cursor-default disabled:hover:bg-transparent"
        onClick={() => setOpen((v) => !v)}
        disabled={empty}
        aria-expanded={open}
      >
        <Badge variant="outline">{index + 1}</Badge>
        <Badge variant={spec.required ? 'primary' : 'outline'}>{spec.type}</Badge>
        {spec.weight !== 1 ? (
          <span className="tabular text-[11px] text-[var(--muted-foreground)]">×{spec.weight}</span>
        ) : null}
        {empty ? null : (
          <ChevronDown
            className={`ml-auto size-3.5 text-[var(--muted-foreground)] transition-transform ${open ? 'rotate-180' : ''}`}
          />
        )}
      </button>
      {open ? (
        <pre className="max-h-72 overflow-auto border-t border-[var(--border)] bg-[var(--muted)] p-2 font-mono text-[11px]">
          {params}
        </pre>
      ) : null}
    </div>
  )
}

function AttemptRow({ attempt }: { attempt: AttemptRead }) {
  return (
    <div
      className={`rounded-md border border-[var(--border)] p-2.5 ${attempt.superseded ? 'opacity-60' : ''}`}
    >
      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
        <Badge variant="outline">#{attempt.n}</Badge>
        <Badge variant={attempt.status === 'ok' ? 'pass' : 'error'}>{attempt.status}</Badge>
        {attempt.retries > 0 ? (
          <Badge variant="default">
            {attempt.retries} {attempt.retries === 1 ? 'retry' : 'retries'}
          </Badge>
        ) : null}
        {attempt.superseded ? <Badge variant="default">superseded</Badge> : null}
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <Stat
          label="tokens"
          value={formatTokens(attempt.prompt_tokens + attempt.completion_tokens)}
        />
        {/* "unknown", not "n/a" — the same word the summary bar uses for the
            same fact, so the two do not read as different states. */}
        <Stat
          label="cost"
          value={attempt.cost_usd === null ? 'unknown' : formatCost(attempt.cost_usd)}
        />
        <Stat label="latency" value={formatDurationMs(attempt.latency_ms)} />
      </div>
      {attempt.error ? (
        <>
          <Separator className="my-2" />
          <p className="text-xs text-[var(--destructive)]">
            {attempt.error_kind ? `[${attempt.error_kind}] ` : ''}
            {attempt.error}
          </p>
        </>
      ) : null}
    </div>
  )
}

/**
 * The files this item produced (PRD F6.1–F6.2).
 *
 * Only rendered when there is something beyond the transcript: on a plain
 * chat answer the raw output is already shown above, and a card repeating it
 * as "output.md" would be furniture.
 */
/** Extensions the backend is willing to run — see artifacts/execute.py. */
const RUNNABLE = /\.(py|js|mjs|sh|rb|go)$/i

function ArtifactsCard({ itemId }: { itemId: number }) {
  const query = useItemArtifacts(itemId)
  const artifacts = query.data ?? []
  const [selectedId, setSelectedId] = React.useState<number | null>(null)

  const selected = artifacts.find((a) => a.id === selectedId) ?? artifacts[0]
  const worthShowing = artifacts.some((a) => a.kind !== 'raw_output')

  if (!worthShowing) return null

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-1.5">
          <Paperclip className="size-4" />
          Artifacts
          <span className="text-xs font-normal text-[var(--muted-foreground)]">
            {artifacts.length}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 lg:grid-cols-[220px_1fr]">
        <ArtifactList
          artifacts={artifacts}
          selectedId={selected?.id ?? null}
          onSelect={(artifact) => setSelectedId(artifact.id)}
        />
        {selected ? (
          <div className="flex min-w-0 flex-col gap-2">
            <ArtifactViewer artifact={selected} />
            {RUNNABLE.test(selected.filename) ? <RunArtifact artifact={selected} /> : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

/**
 * Every version of every score for this item, oldest first.
 *
 * A re-score or a human override writes a new version rather than replacing
 * the old one, and the run page only ever showed the latest. This is where a
 * "the judge changed its mind" argument gets settled.
 */
function ScoreHistory({ itemId }: { itemId: number }) {
  const history = useItemScoreHistory(itemId)

  if (history.isLoading) return <LoadingState label="Loading history…" rows={2} />
  if (history.isError) return <ErrorState error={history.error} />

  const rows = history.data ?? []
  if (rows.length === 0) {
    return <p className="text-sm text-[var(--muted-foreground)]">Nothing has scored this item.</p>
  }

  return (
    <div className="flex flex-col gap-2">
      {rows.map((score) => (
        <div key={score.id} className="rounded-md border border-[var(--border)] p-2.5">
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            <Badge variant="outline">scorer {score.scorer_index + 1}</Badge>
            <Badge variant="default">v{score.version}</Badge>
            <Badge variant="outline">{score.scorer_type}</Badge>
            <Badge
              variant={score.passed === true ? 'pass' : score.passed === false ? 'fail' : 'error'}
            >
              {score.passed === true ? 'pass' : score.passed === false ? 'fail' : 'scorer error'}
            </Badge>
            {score.value !== null ? (
              <span className="tabular text-xs">{formatScore(score.value)}</span>
            ) : null}
            <Badge variant={score.source === 'human' ? 'human' : 'default'}>{score.source}</Badge>
            <span className="ml-auto text-[11px] text-[var(--muted-foreground)]">
              {formatDateTime(score.created_at)}
            </span>
          </div>
          {score.rationale ? (
            <p className="whitespace-pre-wrap text-xs text-[var(--muted-foreground)]">
              {score.rationale}
            </p>
          ) : null}
        </div>
      ))}
    </div>
  )
}
