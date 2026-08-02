import { useAppSettings } from '@/api/runs'
import type { Executor } from '@/api/types'

/**
 * Judge-resolution helpers (PRD F4.1).
 *
 * Separate from `components/JudgeSelect` so that file exports only components —
 * mixing the two breaks Fast Refresh, and the lint rule enforces it.
 *
 * The backend resolves in three steps (`scoring/judge_config.py`): the scorer's
 * own `judge_executor`, then the Settings default, then the executor being
 * evaluated. That last step keeps a fresh install working, but it means a model
 * grades its own output — so the UI has to be able to detect it and say so.
 */

/** Radix cannot hold an empty value, so "no explicit choice" needs a sentinel. */
export const INHERIT = '__inherit__'

/** The scorer param accepts an id or a name; the UI only ever writes an id. */
export function judgeExecutorId(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function describeExecutor(executor: Executor): string {
  return `${executor.name} · ${executor.model_id}`
}

/**
 * Would this judge end up grading the model it is evaluating?
 *
 * True only when nothing above it resolves — no scorer-level judge and no
 * configured default.
 */
export function useSelfJudging(scorerJudge: unknown): boolean {
  const settings = useAppSettings()
  if (judgeExecutorId(scorerJudge) !== null) return false
  // While settings are loading, stay quiet rather than flash a warning.
  if (!settings.data) return false
  return settings.data.default_judge_executor_id === null
}
