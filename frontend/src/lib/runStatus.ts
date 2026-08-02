import type { ItemStatus } from '@/api/types'

/** Zeroed per-status tally — the shape every lane progress bar counts into. */
export function emptyCounts(): Record<ItemStatus, number> {
  return {
    pending: 0,
    invoking: 0,
    scoring: 0,
    passed: 0,
    failed: 0,
    error: 0,
    skipped: 0,
  }
}
