import { AlertTriangle, Loader2 } from 'lucide-react'
import * as React from 'react'

import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/misc'
import { ApiError } from '@/api/client'
import { cn } from '@/lib/utils'

/**
 * The three states every page owes the user.
 * Centralised so "loading" looks the same everywhere and no page forgets one.
 */

export function LoadingState({ label = 'Loading…', rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div className="flex flex-col gap-3" role="status" aria-live="polite" aria-busy="true">
      <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
        <Loader2 className="size-4 animate-spin" />
        {label}
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  )
}

export function ErrorState({
  error,
  onRetry,
  title = 'Something went wrong',
}: {
  error: unknown
  onRetry?: () => void
  title?: string
}) {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : 'Unknown error'
  const code = error instanceof ApiError ? error.code : undefined

  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-lg border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 p-4"
    >
      <div className="flex items-center gap-2 text-sm font-medium text-[var(--destructive)]">
        <AlertTriangle className="size-4" />
        {title}
      </div>
      <p className="text-sm text-[var(--muted-foreground)]">{message}</p>
      {code ? (
        <code className="rounded bg-[var(--muted)] px-1.5 py-0.5 font-mono text-[11px]">
          {code}
        </code>
      ) : null}
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode
  title: string
  description?: React.ReactNode
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'bg-grid flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-[var(--border)] px-6 py-14 text-center',
        className,
      )}
    >
      {icon ? <div className="text-[var(--muted-foreground)]">{icon}</div> : null}
      <div className="flex flex-col gap-1">
        <p className="text-sm font-medium">{title}</p>
        {description ? (
          <p className="max-w-md text-sm text-[var(--muted-foreground)]">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  )
}
