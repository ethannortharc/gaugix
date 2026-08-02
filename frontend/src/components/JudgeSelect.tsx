import { TriangleAlert } from 'lucide-react'
import * as React from 'react'

import { useAppSettings, useExecutors } from '@/api/runs'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { describeExecutor, INHERIT, judgeExecutorId } from '@/lib/judge'
import { cn } from '@/lib/utils'

/**
 * Choosing who grades (PRD F4.1).
 *
 * A judge is an **executor**, not a bare model: the judge call goes through the
 * harness layer so its tokens and cost land in the same ledger as the eval call.
 * Resolution order and the self-judging fallback live in `lib/judge.ts`.
 */

export function JudgeExecutorSelect({
  value,
  onChange,
  inheritLabel,
  className,
  ariaLabel,
}: {
  /** Executor id, or null for "inherit". */
  value: number | null
  onChange: (next: number | null) => void
  /** What "no explicit choice" means at this level. */
  inheritLabel: string
  className?: string
  ariaLabel?: string
}) {
  const executors = useExecutors()
  const options = executors.data?.items ?? []

  return (
    <Select
      value={value === null ? INHERIT : String(value)}
      onValueChange={(next) => onChange(next === INHERIT ? null : Number(next))}
    >
      <SelectTrigger className={cn('h-8', className)} aria-label={ariaLabel ?? 'Judge model'}>
        <SelectValue placeholder={inheritLabel} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={INHERIT}>{inheritLabel}</SelectItem>
        {options.map((executor) => (
          <SelectItem key={executor.id} value={String(executor.id)}>
            {describeExecutor(executor)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export function SelfJudgeWarning({ className }: { className?: string }) {
  return (
    <p
      role="status"
      data-testid="self-judge-warning"
      className={cn(
        'flex items-start gap-1.5 rounded-md border border-[var(--error)]/40 bg-[var(--error)]/10 px-2.5 py-2 text-xs text-[var(--foreground)]',
        className,
      )}
    >
      <TriangleAlert className="mt-px size-3.5 shrink-0 text-[var(--error)]" />
      <span>
        No judge chosen, so <strong>each executor will grade its own output</strong>. Models rate
        their own work generously — pick a different model here, or set a default judge in Settings.
      </span>
    </p>
  )
}

/** Read-only line describing who graded / will grade, for detail views. */
export function JudgeSummary({ scorerJudge }: { scorerJudge: unknown }) {
  const executors = useExecutors()
  const settings = useAppSettings()
  const explicit = judgeExecutorId(scorerJudge)
  const fallback = settings.data?.default_judge_executor_id ?? null
  const chosen = explicit ?? fallback
  const executor = React.useMemo(
    () => (executors.data?.items ?? []).find((e) => e.id === chosen),
    [executors.data, chosen],
  )

  if (chosen === null) {
    return <span className="text-[var(--error)]">the executor under test (self-judging)</span>
  }
  return (
    <span>
      {executor ? describeExecutor(executor) : `executor #${chosen}`}
      {explicit === null ? ' (default)' : null}
    </span>
  )
}
