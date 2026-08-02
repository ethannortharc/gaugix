import { AlertTriangle, Ban, Check, CircleDashed, Loader2, UserRound, X } from 'lucide-react'
import * as React from 'react'

import type { ItemStatus, RunStatus, RunTotals } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Tooltip } from '@/components/ui/misc'
import { formatCost, formatScore, formatTokens } from '@/lib/format'
import { cn } from '@/lib/utils'

/** Shared run/item vocabulary, so a status looks the same on every page. */

const ITEM_META: Record<
  ItemStatus,
  { label: string; variant: React.ComponentProps<typeof Badge>['variant']; icon: React.ReactNode }
> = {
  pending: { label: 'pending', variant: 'pending', icon: <CircleDashed className="size-3" /> },
  invoking: {
    label: 'invoking',
    variant: 'running',
    icon: <Loader2 className="size-3 animate-spin" />,
  },
  scoring: {
    label: 'scoring',
    variant: 'running',
    icon: <Loader2 className="size-3 animate-spin" />,
  },
  passed: { label: 'passed', variant: 'pass', icon: <Check className="size-3" /> },
  failed: { label: 'failed', variant: 'fail', icon: <X className="size-3" /> },
  error: { label: 'error', variant: 'error', icon: <AlertTriangle className="size-3" /> },
  skipped: { label: 'skipped', variant: 'default', icon: <Ban className="size-3" /> },
}

export function ItemStatusBadge({
  status,
  verdict,
  needsHuman,
}: {
  status: ItemStatus
  verdict?: boolean | null
  needsHuman?: boolean
}) {
  const meta = ITEM_META[status]
  // A `passed` item with no verdict ran fine but nothing scored it — saying
  // "passed" would overclaim (ARCHITECTURE §5).
  const unscored = status === 'passed' && (verdict === null || verdict === undefined)

  return (
    <span className="inline-flex items-center gap-1">
      <Badge variant={unscored ? 'default' : meta.variant} className="gap-1">
        {meta.icon}
        {unscored ? 'done (unscored)' : meta.label}
      </Badge>
      {needsHuman ? (
        <Tooltip label="Waiting on your review — open the item to score it.">
          <Badge variant="human" className="gap-1">
            <UserRound className="size-3" />
            needs you
          </Badge>
        </Tooltip>
      ) : null}
    </span>
  )
}

const RUN_META: Record<RunStatus, { variant: React.ComponentProps<typeof Badge>['variant'] }> = {
  pending: { variant: 'pending' },
  running: { variant: 'running' },
  completed: { variant: 'pass' },
  failed: { variant: 'fail' },
  canceled: { variant: 'default' },
  interrupted: { variant: 'error' },
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return (
    <Badge variant={RUN_META[status].variant} className="gap-1">
      {status === 'running' ? <Loader2 className="size-3 animate-spin" /> : null}
      {status}
    </Badge>
  )
}

export function ScoreBadge({ verdict, score }: { verdict: boolean | null; score: number | null }) {
  if (verdict === null && score === null) {
    return <span className="text-xs text-[var(--muted-foreground)]">—</span>
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      {verdict !== null ? (
        <Badge variant={verdict ? 'pass' : 'fail'}>{verdict ? 'pass' : 'fail'}</Badge>
      ) : null}
      {score !== null ? <span className="tabular text-xs">{formatScore(score)}</span> : null}
    </span>
  )
}

/** One number with a label — the unit of the run summary header. */
export function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string
  value: React.ReactNode
  hint?: string
  tone?: 'pass' | 'fail' | 'error' | 'muted'
}) {
  const colour =
    tone === 'pass'
      ? 'text-[var(--pass)]'
      : tone === 'fail'
        ? 'text-[var(--fail)]'
        : tone === 'error'
          ? 'text-[var(--error)]'
          : ''

  const body = (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] uppercase tracking-wide text-[var(--muted-foreground)]">
        {label}
      </span>
      <span className={cn('tabular text-lg font-semibold leading-none', colour)}>{value}</span>
    </div>
  )
  return hint ? <Tooltip label={hint}>{body}</Tooltip> : body
}

/**
 * Run summary numbers, in two groups — and the split is the point.
 *
 * `totals.passed` counts items whose *invocation* finished, which includes
 * items nothing scored. Showing it beside a verdict-derived pass rate produced
 * lines like "items 9 · passed 5 · failed 4 · unscored 1 · pass rate 50%",
 * where the unscored item was hiding inside the 5 and the numbers did not add
 * up in any reading. So: Execution answers "did the call go through", and
 * Evaluation answers "was the answer any good". Nothing appears in both.
 */
export function RunTotalsRow({ totals }: { totals: RunTotals }) {
  // Pass rate is verdicts over verdicts. An item that ran fine with no scorers
  // has no verdict, so it must not inflate the numerator or the denominator.
  const passRate = totals.scored > 0 ? totals.verdict_passed / totals.scored : null
  const completed = totals.passed + totals.failed
  const verdictFailed = totals.scored - totals.verdict_passed
  const running = totals.invoking + totals.scoring

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
        <GroupLabel>Execution</GroupLabel>
        <Stat label="items" value={totals.items} />
        <Stat
          label="completed"
          value={completed}
          hint="The model answered. Whether the answer was any good is the next row."
        />
        {running > 0 ? <Stat label="in flight" value={running} /> : null}
        {totals.pending > 0 ? <Stat label="pending" value={totals.pending} /> : null}
        {totals.error > 0 ? <Stat label="errors" value={totals.error} tone="error" /> : null}
        {totals.skipped > 0 ? <Stat label="skipped" value={totals.skipped} /> : null}
        <Stat
          label="tokens"
          value={formatTokens(totals.prompt_tokens + totals.completion_tokens)}
          hint={`${formatTokens(totals.prompt_tokens)} in · ${formatTokens(totals.completion_tokens)} out`}
        />
        <Stat
          label="cost"
          value={
            totals.cost_unknown ? `≥ ${formatCost(totals.cost_usd)}` : formatCost(totals.cost_usd)
          }
          hint={
            totals.cost_unknown
              ? 'At least one attempt could not be priced, so this is a lower bound.'
              : undefined
          }
        />
      </div>

      <div className="flex flex-wrap items-center gap-x-8 gap-y-3 border-t border-[var(--border)] pt-3">
        <GroupLabel>Evaluation</GroupLabel>
        <Stat
          label="passed"
          value={totals.verdict_passed}
          tone="pass"
          hint="Every required scorer said yes."
        />
        <Stat
          label="failed"
          value={verdictFailed}
          tone="fail"
          hint="At least one scorer said no."
        />
        {totals.unscored > 0 ? (
          <Stat
            label="unscored"
            value={totals.unscored}
            hint="Ran cleanly, but nothing judged them — no scorer configured, or the scorer declined."
          />
        ) : null}
        <Stat
          label="pass rate"
          value={passRate === null ? '—' : `${Math.round(passRate * 100)}%`}
          hint={
            totals.scored === 0
              ? 'Nothing has a verdict yet, so there is no pass rate to report.'
              : `${totals.verdict_passed} of ${totals.scored} scored items passed. Unscored items are in neither number.`
          }
        />
        {totals.needs_human > 0 ? <Stat label="needs review" value={totals.needs_human} /> : null}
      </div>
    </div>
  )
}

function GroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="w-20 shrink-0 text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
      {children}
    </span>
  )
}

/** A compact per-lane progress bar — the run page's "at a glance" view. */
export function LaneProgress({
  counts,
  total,
}: {
  counts: Record<ItemStatus, number>
  total: number
}) {
  const segments: { status: ItemStatus; colour: string }[] = [
    { status: 'passed', colour: 'var(--pass)' },
    { status: 'failed', colour: 'var(--fail)' },
    { status: 'error', colour: 'var(--error)' },
    { status: 'invoking', colour: 'var(--running)' },
    { status: 'scoring', colour: 'var(--running)' },
    { status: 'skipped', colour: 'var(--pending)' },
  ]

  return (
    <div
      className="flex h-2 w-full overflow-hidden rounded-full bg-[var(--muted)]"
      role="img"
      aria-label={`${counts.passed} passed, ${counts.failed} failed, ${counts.error} errored of ${total}`}
    >
      {segments.map(({ status, colour }) =>
        counts[status] > 0 ? (
          <div
            key={status}
            style={{ width: `${(counts[status] / Math.max(1, total)) * 100}%`, background: colour }}
            className={status === 'invoking' || status === 'scoring' ? 'animate-pulse-soft' : ''}
          />
        ) : null,
      )}
    </div>
  )
}

/**
 * A pass-rate trend, drawn as inline SVG.
 *
 * Deliberately tiny and unlabelled: it answers "is this getting better or
 * worse?" at a glance, and the number beside it answers "by how much". Fewer
 * than two points is not a trend, so it renders nothing rather than a dot
 * that would imply one.
 */
export function Sparkline({
  values,
  width = 96,
  height = 24,
}: {
  values: number[]
  width?: number
  height?: number
}) {
  if (values.length < 2) return null

  const low = Math.min(...values)
  const high = Math.max(...values)
  const span = high - low || 1
  const step = width / (values.length - 1)
  const points = values
    .map((value, index) => {
      const x = index * step
      const y = height - ((value - low) / span) * (height - 4) - 2
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  const rising = values[values.length - 1] >= values[0]
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={`Pass rate trend: ${values[0]}% to ${values[values.length - 1]}%`}
      className="shrink-0"
    >
      <polyline
        points={points}
        fill="none"
        stroke={rising ? 'var(--pass)' : 'var(--fail)'}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}
