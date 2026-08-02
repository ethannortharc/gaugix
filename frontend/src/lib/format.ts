/**
 * Display formatting for the numbers Gaugix shows constantly.
 *
 * The rule that matters: **unknown is not zero**. When cost or a score could not
 * be computed we render "n/a", never 0 — a fabricated zero would quietly lie in
 * a leaderboard (PRD NFR-V, ARCHITECTURE §4).
 */

export const NOT_AVAILABLE = 'n/a'

export function formatInt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NOT_AVAILABLE
  return new Intl.NumberFormat('en-US').format(value)
}

/** Compact token counts: 1_234 → "1.2k". */
export function formatTokens(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NOT_AVAILABLE
  if (value < 1000) return String(value)
  if (value < 1_000_000) return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)}k`
  return `${(value / 1_000_000).toFixed(2)}M`
}

/** USD with enough precision that sub-cent eval runs stay legible. */
export function formatCost(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NOT_AVAILABLE
  if (value === 0) return '$0.00'
  if (value < 0.01) return `$${value.toFixed(4)}`
  if (value < 1) return `$${value.toFixed(3)}`
  return `$${value.toFixed(2)}`
}

export function formatDurationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return NOT_AVAILABLE
  if (ms < 1000) return `${Math.round(ms)}ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  if (minutes < 60) return `${minutes}m ${rest}s`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m`
}

/** Scores are normalised 0–100 everywhere in the domain model. */
export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NOT_AVAILABLE
  return value % 1 === 0 ? value.toFixed(0) : value.toFixed(1)
}

export function formatPercent(fraction: number | null | undefined, digits = 0): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return NOT_AVAILABLE
  return `${(fraction * 100).toFixed(digits)}%`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return NOT_AVAILABLE
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return NOT_AVAILABLE
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

/** "3 minutes ago" for run lists; falls back to absolute beyond a week. */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return NOT_AVAILABLE
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return NOT_AVAILABLE
  const diffMs = Date.now() - date.getTime()
  const seconds = Math.round(diffMs / 1000)
  if (seconds < 45) return 'just now'
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  const table: [Intl.RelativeTimeFormatUnit, number][] = [
    ['minute', 60],
    ['hour', 3600],
    ['day', 86400],
  ]
  for (const [unit, size] of table) {
    if (Math.abs(seconds) < size * (unit === 'day' ? 7 : 60)) {
      if (Math.abs(seconds) >= size) return rtf.format(-Math.round(seconds / size), unit)
    }
  }
  return formatDateTime(iso)
}

export function truncate(text: string, max = 120): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`
}

export function pluralize(count: number, singular: string, plural?: string): string {
  return count === 1 ? singular : (plural ?? `${singular}s`)
}

/** Byte sizes for artifact lists — 1 kB is friendlier than 1024 B. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return NOT_AVAILABLE
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
