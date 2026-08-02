import { AlertTriangle, BookMarked, Check, Coins, Search, Terminal } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'

import { useBenchmarks } from '@/api/benchmarks'
import type { BenchmarkSummary } from '@/api/types'
import { MethodBadge } from '@/components/BenchmarkBits'
import { PageHeader } from '@/components/layout/AppShell'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { pluralize } from '@/lib/format'

/**
 * The benchmark library.
 *
 * Cards, not a table: choosing a benchmark is a reading task, and the thing
 * that should be visible before anyone clicks Install is what it costs you —
 * a judge model on every run, or model-written code executing on this machine.
 * Those two badges are the reason this page is not a dropdown.
 */
export default function BenchmarksPage() {
  const benchmarks = useBenchmarks()
  const [q, setQ] = React.useState('')
  const [tag, setTag] = React.useState<string | null>(null)

  const all = React.useMemo(() => benchmarks.data ?? [], [benchmarks.data])
  const tags = React.useMemo(() => [...new Set(all.flatMap((e) => e.tags))].sort(), [all])
  const needle = q.trim().toLowerCase()
  const shown = all.filter(
    (entry) =>
      (tag === null || entry.tags.includes(tag)) &&
      (needle === '' ||
        [entry.name, entry.publisher, entry.task, entry.summary, ...entry.tags]
          .join(' ')
          .toLowerCase()
          .includes(needle)),
  )

  return (
    <>
      <PageHeader
        title="Benchmark library"
        description="Public evals you can install as sets. Each one ships a small sample that works offline; the full download is one explicit click and one named URL."
      />

      {benchmarks.isLoading ? (
        <LoadingState label="Reading the catalogue…" rows={3} />
      ) : benchmarks.isError ? (
        <ErrorState error={benchmarks.error} onRetry={() => void benchmarks.refetch()} />
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div className="relative min-w-56 max-w-sm flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search benchmarks…"
                className="pl-8"
                aria-label="Search benchmarks"
              />
            </div>
            {tags.map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => setTag(tag === name ? null : name)}
                aria-pressed={tag === name}
              >
                <Badge variant={tag === name ? 'primary' : 'outline'} className="cursor-pointer">
                  {name}
                </Badge>
              </button>
            ))}
            <span className="ml-auto text-xs text-[var(--muted-foreground)]">
              {shown.length} of {all.length}
            </span>
          </div>

          {shown.length === 0 ? (
            <EmptyState
              icon={<Search className="size-6" />}
              title="No benchmark matches"
              description="Clear the search or the tag filter to see the whole catalogue."
            />
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {shown.map((entry) => (
                <BenchmarkCard key={entry.slug} entry={entry} />
              ))}
            </div>
          )}
        </>
      )}
    </>
  )
}

function BenchmarkCard({ entry }: { entry: BenchmarkSummary }) {
  const installed = entry.installed.length > 0

  return (
    <Card className="transition-colors hover:border-[var(--primary)]/50">
      <CardContent className="flex h-full flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <Link to={`/benchmarks/${entry.slug}`} className="min-w-0">
            <h2 className="truncate text-sm font-semibold hover:underline">{entry.name}</h2>
            <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
              {entry.publisher} · {entry.year} · {entry.licence}
            </p>
          </Link>
          {installed ? (
            <Badge variant="pass" className="shrink-0 gap-1">
              <Check className="size-3" />
              installed
            </Badge>
          ) : null}
        </div>

        <p className="flex-1 text-sm text-[var(--muted-foreground)]">{entry.summary}</p>

        <div className="flex flex-wrap items-center gap-1.5">
          {/*
            First, before the size and the cost: whether the number this
            produces is the benchmark's number or one of Gaugix's own.
          */}
          <MethodBadge method={entry.method} />
          <Badge variant="outline">
            {entry.full_size.toLocaleString()} {pluralize(entry.full_size, 'case')}
          </Badge>
          <Badge variant="default">{entry.sample_size} bundled</Badge>
          {/*
            The two badges that change what pressing Install means. A judge
            costs money on every run; code execution runs the model's output
            on this machine. Both belong on the card, not behind a click.
          */}
          {entry.requires_judge ? (
            <Badge
              variant="human"
              className="gap-1"
              title="Scoring calls a judge model, which costs money on every run."
            >
              <Coins className="size-3" />
              needs a judge
            </Badge>
          ) : null}
          {entry.requires_code_execution ? (
            <Badge
              variant="error"
              className="gap-1"
              title="Scoring executes model-written code on this machine, outside any sandbox."
            >
              <AlertTriangle className="size-3" />
              runs model code
            </Badge>
          ) : entry.requires_judge ? null : (
            <Badge
              variant="pass"
              className="gap-1"
              title="Scored deterministically in code — no judge, no API cost."
            >
              <Terminal className="size-3" />
              free to score
            </Badge>
          )}
        </div>

        {installed ? (
          <div className="flex flex-wrap gap-2 border-t border-[var(--border)] pt-2 text-xs">
            {entry.installed.map((set) => (
              <Link
                key={set.id}
                to={`/sets/${set.id}`}
                className="text-[var(--primary)] hover:underline"
              >
                {set.name} ({set.case_count})
              </Link>
            ))}
          </div>
        ) : (
          <Link
            to={`/benchmarks/${entry.slug}`}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--primary)] hover:underline"
          >
            <BookMarked className="size-3.5" />
            Read what it measures
          </Link>
        )}
      </CardContent>
    </Card>
  )
}
