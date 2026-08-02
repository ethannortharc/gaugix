import { ArrowDownRight, ArrowUpRight, Minus, Plus, TriangleAlert, X } from 'lucide-react'
import * as React from 'react'

import type { BucketStats, DiffKind, MatrixCell } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Tooltip } from '@/components/ui/misc'
import { formatCost, formatScore, NOT_AVAILABLE } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * Shared presentation for the comparison views.
 *
 * One rule runs through all of it: **an absent number is drawn as absent.**
 * A pass rate of `null` means nothing was scored, and rendering that as 0%
 * would turn "not measured" into "failed everything" — which is the single
 * easiest way for an eval tool to lie to you.
 */

/** Pass rate with the colour it earns, or a plain dash when unscored. */
export function PassRate({ value, className }: { value: number | null; className?: string }) {
  if (value === null) {
    return (
      <Tooltip label="Nothing scored — not the same as 0%">
        <span className={cn('text-xs text-[var(--muted-foreground)]', className)}>
          {NOT_AVAILABLE}
        </span>
      </Tooltip>
    )
  }
  const tone =
    value >= 80
      ? 'text-[var(--pass)]'
      : value >= 50
        ? 'text-[var(--foreground)]'
        : 'text-[var(--fail)]'
  return <span className={cn('tabular font-medium', tone, className)}>{value}%</span>
}

/** A horizontal meter behind a pass rate — comparison at a glance. */
export function PassRateBar({ value }: { value: number | null }) {
  return (
    <span className="flex items-center gap-2">
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-[var(--muted)]">
        {value === null ? null : (
          <span
            className={cn(
              'block h-full rounded-full',
              value >= 50 ? 'bg-[var(--pass)]' : 'bg-[var(--fail)]',
            )}
            // A measured 0% keeps a hairline: drawing nothing reads as unmeasured.
            style={{ width: `${Math.max(value, 1.5)}%` }}
          />
        )}
      </span>
      <PassRate value={value} />
    </span>
  )
}

export function CostCell({ stats }: { stats: Pick<BucketStats, 'cost_usd' | 'cost_unknown'> }) {
  const text = formatCost(stats.cost_usd)
  if (!stats.cost_unknown) return <span className="tabular text-xs">{text}</span>
  return (
    <Tooltip label="At least one call could not be priced, so this is a floor.">
      <span className="tabular text-xs">
        {text}
        <span className="text-[var(--muted-foreground)]">+</span>
      </span>
    </Tooltip>
  )
}

const DIFF_META: Record<
  DiffKind,
  { label: string; icon: React.ReactNode; badge: string; blurb: string }
> = {
  regressed: {
    label: 'Regressions',
    icon: <ArrowDownRight className="size-3.5" />,
    badge: 'fail',
    blurb: 'Passed on the baseline, fails now.',
  },
  improved: {
    label: 'Improvements',
    icon: <ArrowUpRight className="size-3.5" />,
    badge: 'pass',
    blurb: 'Failed on the baseline, passes now.',
  },
  unchanged: {
    label: 'Unchanged',
    icon: <Minus className="size-3.5" />,
    badge: 'default',
    blurb: 'Same verdict on both sides.',
  },
  new: {
    label: 'New',
    icon: <Plus className="size-3.5" />,
    badge: 'outline',
    blurb: 'Present now, absent from the baseline.',
  },
  removed: {
    label: 'Removed',
    icon: <X className="size-3.5" />,
    badge: 'outline',
    blurb: 'Present on the baseline, absent now.',
  },
  unresolved: {
    label: 'Unresolved',
    icon: <TriangleAlert className="size-3.5" />,
    badge: 'error',
    blurb: 'One side has no verdict, so nothing can be concluded.',
  },
}

/**
 * One bucket of the diff, as a count you can filter by.
 *
 * The labels live in here rather than being exported, so this file stays
 * components-only — mixing component and value exports breaks Fast Refresh.
 */
export function DiffCountButton({
  kind,
  count,
  active,
  onClick,
}: {
  kind: DiffKind
  count: number
  active: boolean
  onClick: () => void
}) {
  const meta = DIFF_META[kind]
  return (
    <Tooltip label={meta.blurb}>
      <button
        type="button"
        aria-pressed={active}
        aria-label={`${meta.label}: ${count}`}
        disabled={count === 0}
        onClick={onClick}
        className={cn(
          'flex items-center gap-2 rounded-md border px-3 py-2 text-left transition-colors disabled:opacity-40',
          active
            ? 'border-[var(--primary)] bg-[var(--accent)]'
            : 'border-[var(--border)] hover:bg-[var(--muted)]',
        )}
      >
        <span className="tabular text-lg font-semibold leading-none">{count}</span>
        <span className="text-xs text-[var(--muted-foreground)]">{meta.label}</span>
      </button>
    </Tooltip>
  )
}

export function DiffKindBadge({ kind }: { kind: DiffKind }) {
  const meta = DIFF_META[kind]
  return (
    <Tooltip label={meta.blurb}>
      <Badge variant={meta.badge as never} className="gap-1">
        {meta.icon}
        {kind}
      </Badge>
    </Tooltip>
  )
}

/** A signed score change. Zero is shown as zero, never as blank. */
export function ScoreDelta({ delta }: { delta: number | null }) {
  if (delta === null) {
    return <span className="text-xs text-[var(--muted-foreground)]">—</span>
  }
  const tone =
    delta > 0
      ? 'text-[var(--pass)]'
      : delta < 0
        ? 'text-[var(--fail)]'
        : 'text-[var(--muted-foreground)]'
  return (
    <span className={cn('tabular text-xs font-medium', tone)}>
      {delta > 0 ? '+' : ''}
      {formatScore(delta)}
    </span>
  )
}

/** One matrix cell: verdict colour, score on hover, click-through to the item. */
export function MatrixCellChip({ cell }: { cell: MatrixCell | undefined }) {
  if (!cell) {
    return <span className="text-xs text-[var(--muted-foreground)]">—</span>
  }
  const tone =
    cell.status === 'error'
      ? 'bg-[var(--error)]/15 text-[var(--error)] border-[var(--error)]/40'
      : cell.verdict === true
        ? 'bg-[var(--pass)]/15 text-[var(--pass)] border-[var(--pass)]/40'
        : cell.verdict === false
          ? 'bg-[var(--fail)]/15 text-[var(--fail)] border-[var(--fail)]/40'
          : 'bg-[var(--muted)] text-[var(--muted-foreground)] border-[var(--border)]'
  const label =
    cell.status === 'error'
      ? 'err'
      : cell.verdict === true
        ? 'pass'
        : cell.verdict === false
          ? 'fail'
          : '—'
  const hint =
    cell.status === 'error'
      ? (cell.error ?? 'errored')
      : cell.verdict === null
        ? cell.needs_human
          ? 'waiting on human review'
          : 'finished, nothing scored it'
        : `score ${formatScore(cell.score_value)}`

  return (
    <Tooltip label={hint}>
      <span
        className={cn(
          'inline-flex min-w-[54px] items-center justify-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-medium',
          tone,
        )}
      >
        {label}
        {cell.score_value !== null ? (
          <span className="tabular opacity-70">{formatScore(cell.score_value)}</span>
        ) : null}
      </span>
    </Tooltip>
  )
}
