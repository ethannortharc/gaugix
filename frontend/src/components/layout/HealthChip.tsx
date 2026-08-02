import { useQuery } from '@tanstack/react-query'

import { fetchHealth } from '@/api/client'
import { Tooltip } from '@/components/ui/misc'
import { cn } from '@/lib/utils'

/** Backend liveness at a glance — the first thing to check when the UI looks stuck. */
export function HealthChip() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 15_000,
    retry: 1,
  })

  const state = isLoading ? 'loading' : isError ? 'down' : (data?.status ?? 'down')
  const dot =
    state === 'ok'
      ? 'bg-[var(--pass)]'
      : state === 'loading'
        ? 'bg-[var(--pending)] animate-pulse-soft'
        : state === 'degraded'
          ? 'bg-[var(--error)]'
          : 'bg-[var(--fail)]'

  const label =
    state === 'ok'
      ? `API v${data?.version} · db ${data?.db} · ${data?.data_dir}`
      : state === 'loading'
        ? 'Checking the backend…'
        : state === 'degraded'
          ? `Backend degraded: ${data?.db}`
          : 'Backend unreachable — is `make dev` running on :8317?'

  const text =
    state === 'ok'
      ? 'connected'
      : state === 'loading'
        ? 'checking'
        : state === 'degraded'
          ? 'degraded'
          : 'offline'

  return (
    <Tooltip label={label} side="bottom">
      <span
        className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-2 py-1 text-[11px] text-[var(--muted-foreground)]"
        data-testid="health-chip"
        data-state={state}
      >
        <span className={cn('size-1.5 rounded-full', dot)} aria-hidden />
        {text}
      </span>
    </Tooltip>
  )
}
