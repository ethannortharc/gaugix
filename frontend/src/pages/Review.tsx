import { CheckCircle2, UserRound } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'

import { useReviewQueue, useRunItem } from '@/api/runs'
import { HumanScorePanel } from '@/components/HumanScorePanel'
import { PageHeader } from '@/components/layout/AppShell'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { formatRelative, pluralize } from '@/lib/format'

/**
 * The "needs human score" queue (PRD F4.4).
 *
 * Deliberately one item at a time with the output in view: scoring a list of
 * titles without reading the outputs would produce noise, not a calibration
 * signal.
 */
export default function ReviewPage() {
  const [runFilter, setRunFilter] = React.useState<number | null>(null)
  const queue = useReviewQueue(runFilter ?? undefined)
  const [index, setIndex] = React.useState(0)

  // Stable identity: a fresh [] each render would re-run the memo below.
  const items = React.useMemo(() => queue.data?.items ?? [], [queue.data])
  const current = items[Math.min(index, Math.max(0, items.length - 1))]

  React.useEffect(() => {
    if (index >= items.length && items.length > 0) setIndex(items.length - 1)
  }, [items.length, index])

  // Reviewing an item removes it from the queue, so the index would silently
  // land on a different item; snapping back to the top keeps position honest.
  React.useEffect(() => setIndex(0), [runFilter])

  /** Runs represented in the queue, so the filter only offers real choices. */
  const runs = React.useMemo(() => {
    const seen = new Map<number, string>()
    for (const entry of items) seen.set(entry.run_id, entry.run_name)
    return [...seen.entries()].map(([id, name]) => ({ id, name }))
  }, [items])

  return (
    <>
      <PageHeader
        title="Review queue"
        description="Items whose scoring config asks for your judgement. Your call overrides the machine, and disagreements are counted as a judge-calibration signal."
      />

      {queue.isLoading ? (
        <LoadingState label="Loading queue…" />
      ) : queue.isError ? (
        <ErrorState error={queue.error} onRetry={() => void queue.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<CheckCircle2 className="size-6" />}
          title="Nothing waiting on you"
          description="Items appear here when their scoring config includes a `human` scorer that has not been resolved yet."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <Card className="h-fit">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-1.5">
                <UserRound className="size-4 text-[var(--human)]" />
                {items.length} {pluralize(items.length, 'item')} waiting
              </CardTitle>
            </CardHeader>
            {runs.length > 1 ? (
              <CardContent className="pb-2">
                <Select
                  value={runFilter === null ? 'all' : String(runFilter)}
                  onValueChange={(value) => setRunFilter(value === 'all' ? null : Number(value))}
                >
                  <SelectTrigger className="h-8" aria-label="Filter by run">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Every run</SelectItem>
                    {runs.map((run) => (
                      <SelectItem key={run.id} value={String(run.id)}>
                        {run.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </CardContent>
            ) : null}
            {/*
              Title and executor alone were not enough to tell two entries
              apart — a benchmark install guarantees repeated titles, and one
              executor produces most of a run. Run, set, the machine's own
              verdict and the age make each row identifiable.
            */}
            <CardContent className="flex max-h-[60vh] flex-col gap-1 overflow-y-auto">
              {items.map((entry, i) => (
                <button
                  key={entry.item_id}
                  type="button"
                  onClick={() => setIndex(i)}
                  className={`flex flex-col gap-0.5 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
                    i === index
                      ? 'bg-[var(--human)]/15 text-[var(--human)]'
                      : 'hover:bg-[var(--muted)]'
                  }`}
                >
                  <span className="line-clamp-1 font-medium">{entry.title}</span>
                  <span className="line-clamp-1 text-[11px] text-[var(--muted-foreground)]">
                    {entry.set_name} · {entry.executor_key}
                  </span>
                  <span className="flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">
                    <span className="line-clamp-1 flex-1">{entry.run_name}</span>
                    {entry.auto_verdict !== null ? (
                      <Badge variant={entry.auto_verdict ? 'pass' : 'fail'}>
                        auto {entry.auto_verdict ? 'pass' : 'fail'}
                      </Badge>
                    ) : (
                      <Badge variant="default">unscored</Badge>
                    )}
                  </span>
                  <span className="text-[11px] text-[var(--muted-foreground)]">
                    {formatRelative(entry.updated_at)}
                  </span>
                </button>
              ))}
            </CardContent>
          </Card>

          {current ? <ReviewPane key={current.item_id} entry={current} /> : null}
        </div>
      )}
    </>
  )
}

function ReviewPane({
  entry,
}: {
  entry: { item_id: number; scorer_index: number; title: string; run_id: number; run_name: string }
}) {
  const detail = useRunItem(entry.item_id)

  if (detail.isLoading) return <LoadingState label="Loading item…" />
  if (detail.isError) return <ErrorState error={detail.error} />
  if (!detail.data) return null

  const item = detail.data
  const output = item.attempts.filter((a) => !a.superseded).at(-1)?.output_text ?? ''
  const spec = (item.case_snapshot.scoring ?? [])[entry.scorer_index]

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold">{item.title}</h2>
        <Badge variant="outline">{item.executor_key}</Badge>
        <Button asChild variant="ghost" size="sm" className="ml-auto">
          <Link to={`/items/${item.id}`}>Open full item</Link>
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle>Input</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {item.input.map((message, i) => (
            <pre
              key={i}
              className="overflow-x-auto whitespace-pre-wrap break-words rounded-md border border-[var(--border)] px-2.5 py-2 font-mono text-xs"
            >
              {message.content}
            </pre>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle>Output</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-2 font-mono text-xs">
            {output || '(no output)'}
          </pre>
        </CardContent>
      </Card>

      {item.reference ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Reference</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="whitespace-pre-wrap text-sm">{item.reference}</p>
          </CardContent>
        </Card>
      ) : null}

      <HumanScorePanel itemId={item.id} scorerIndex={entry.scorer_index} spec={spec} />
    </div>
  )
}
