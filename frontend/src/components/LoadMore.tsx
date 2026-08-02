import { Button } from '@/components/ui/button'
import { pluralize } from '@/lib/format'
import { PAGE_SIZE } from '@/lib/paging'

/**
 * The same honesty for a control that *cannot* load more.
 *
 * A picker fetches to the API's ceiling in one go, so past it there is no
 * "load more" to offer — only the choice between saying so and not saying so.
 * `useSetOptions()` has returned `truncated` since the 50-set limit was raised
 * to 500, and no caller read it, so the 501st set would have disappeared
 * exactly as silently as the 51st did (D-066). It is not the paginated picker
 * this eventually wants; it is the part that must not wait for one.
 */
export function TruncatedNotice({
  shown,
  total,
  noun = 'item',
  hint = 'Use search to reach the rest.',
}: {
  shown: number
  total: number
  noun?: string
  hint?: string
}) {
  if (total <= shown) return null
  return (
    <p role="status" className="text-xs text-[var(--warning-foreground,var(--muted-foreground))]">
      Showing {shown.toLocaleString()} of {total.toLocaleString()} {pluralize(total, noun)} —{' '}
      {(total - shown).toLocaleString()} not listed here. {hint}
    </p>
  )
}

/**
 * The footer of a possibly-truncated list.
 *
 * Always renders the count, even when everything fits — a list that says
 * nothing about its size is how "showing the first 500 of 4,326" reads as
 * "there are 500". That silence is the bug this exists to fix.
 */
export function LoadMore({
  shown,
  total,
  noun = 'item',
  onMore,
  busy,
  step = PAGE_SIZE,
}: {
  shown: number
  total: number
  noun?: string
  onMore: () => void
  busy?: boolean
  step?: number
}) {
  const remaining = Math.max(0, total - shown)

  return (
    <div className="flex items-center justify-center gap-3 py-2 text-xs text-[var(--muted-foreground)]">
      <span className="tabular">
        {remaining > 0
          ? `Showing ${shown.toLocaleString()} of ${total.toLocaleString()}`
          : `${total.toLocaleString()} ${pluralize(total, noun)}`}
      </span>
      {remaining > 0 ? (
        <Button variant="outline" size="sm" onClick={onMore} disabled={busy}>
          Load {Math.min(remaining, step).toLocaleString()} more
        </Button>
      ) : null}
    </div>
  )
}
