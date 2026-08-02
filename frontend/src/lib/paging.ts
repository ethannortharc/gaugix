import * as React from 'react'

/** How many rows a list asks for at a time. */
export const PAGE_SIZE = 100

/**
 * Client-side paging state for a list backed by a server `limit`.
 *
 * Deliberately "load more" rather than numbered pages: every list here is
 * something you scan or filter, not something you navigate by page number, and
 * a growing window keeps what you already looked at on screen.
 */
export function usePagedLimit(pageSize = PAGE_SIZE, maxLimit = Number.POSITIVE_INFINITY) {
  const initialLimit = Math.min(pageSize, maxLimit)
  const [limit, setLimit] = React.useState(initialLimit)
  const more = React.useCallback(
    () => setLimit((n) => Math.min(n + pageSize, maxLimit)),
    [maxLimit, pageSize],
  )
  const reset = React.useCallback(() => setLimit(initialLimit), [initialLimit])
  return { limit, more, reset }
}
