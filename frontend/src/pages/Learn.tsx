import { BookOpen, Search } from 'lucide-react'
import * as React from 'react'
import { Link, useParams } from 'react-router-dom'

import { useChapter, useChapters, useLearnSearch } from '@/api/learn'
import { PageHeader } from '@/components/layout/AppShell'
import { Markdown } from '@/components/Markdown'
import { ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

/**
 * The eval guide (PRD F7.1–F7.2).
 *
 * Reachable from a quiet footer link rather than the sidebar: findable when you
 * want it, invisible while you work, which is what the draft asked for. Deep
 * links from the app (rubric editor → "Writing rubrics", judge config → "Judge
 * calibration") land on a specific chapter.
 */

export default function LearnPage() {
  const params = useParams()
  const slug = params.slug
  const toc = useChapters()
  const [query, setQuery] = React.useState('')
  const results = useLearnSearch(query)

  if (toc.isLoading) return <LoadingState label="Loading the guide…" rows={5} />
  if (toc.isError) return <ErrorState error={toc.error} onRetry={() => void toc.refetch()} />

  const chapters = toc.data ?? []

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <BookOpen className="size-5 text-[var(--primary)]" />
            Eval Guide
          </span>
        }
        description="How to measure a language model on your own work, and how to avoid fooling yourself."
      />

      <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
        <nav className="flex flex-col gap-3" aria-label="Guide contents">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search the guide"
              aria-label="Search the guide"
              className="h-8 pl-8"
            />
          </div>

          {query.trim() ? (
            <SearchResults hits={results.data ?? []} loading={results.isLoading} />
          ) : (
            <ol className="flex flex-col gap-0.5">
              {chapters.map((chapter) => (
                <li key={chapter.slug}>
                  <Link
                    to={`/learn/${chapter.slug}`}
                    className={cn(
                      'flex gap-2 rounded-md px-2 py-1.5 text-sm transition-colors',
                      chapter.slug === slug
                        ? 'bg-[var(--accent)] font-medium text-[var(--accent-foreground)]'
                        : 'hover:bg-[var(--muted)]',
                    )}
                  >
                    <span className="tabular w-4 shrink-0 text-[var(--muted-foreground)]">
                      {chapter.order}
                    </span>
                    <span className="min-w-0">{chapter.title}</span>
                  </Link>
                </li>
              ))}
            </ol>
          )}
        </nav>

        {slug ? <Chapter slug={slug} /> : <Overview chapters={chapters} />}
      </div>
    </>
  )
}

function SearchResults({
  hits,
  loading,
}: {
  hits: { slug: string; title: string; excerpt: string }[]
  loading: boolean
}) {
  if (loading) return <LoadingState label="Searching…" rows={2} />
  if (hits.length === 0) {
    return <p className="px-2 text-xs text-[var(--muted-foreground)]">Nothing matched.</p>
  }
  return (
    <ul className="flex flex-col gap-1">
      {hits.map((hit) => (
        <li key={hit.slug}>
          <Link
            to={`/learn/${hit.slug}`}
            className="flex flex-col gap-0.5 rounded-md px-2 py-1.5 transition-colors hover:bg-[var(--muted)]"
          >
            <span className="text-sm font-medium">{hit.title}</span>
            <span className="line-clamp-2 text-[11px] text-[var(--muted-foreground)]">
              {hit.excerpt}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

function Overview({
  chapters,
}: {
  chapters: { slug: string; order: number; title: string; summary: string; tags: string[] }[]
}) {
  return (
    <div className="flex flex-col gap-3">
      <p className="max-w-2xl text-[15px] leading-relaxed text-[var(--muted-foreground)]">
        Ten short chapters, written to be read in order the first time and dipped into afterwards.
        The through-line: an eval is only worth what its honesty is worth.
      </p>
      {chapters.map((chapter) => (
        <Link
          key={chapter.slug}
          to={`/learn/${chapter.slug}`}
          className="flex flex-col gap-1 rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-3 transition-colors hover:border-[var(--primary)]/50"
        >
          <span className="flex items-center gap-2 font-medium">
            <span className="tabular text-[var(--muted-foreground)]">{chapter.order}</span>
            {chapter.title}
          </span>
          <span className="text-sm text-[var(--muted-foreground)]">{chapter.summary}</span>
          <span className="flex flex-wrap gap-1 pt-0.5">
            {chapter.tags.map((tag) => (
              <Badge key={tag} variant="outline" className="text-[10px]">
                {tag}
              </Badge>
            ))}
          </span>
        </Link>
      ))}
    </div>
  )
}

function Chapter({ slug }: { slug: string }) {
  const query = useChapter(slug)

  React.useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [slug])

  if (query.isLoading) return <LoadingState label="Loading chapter…" rows={6} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  if (!query.data) return null

  const chapter = query.data

  return (
    <article className="flex min-w-0 max-w-3xl flex-col gap-4">
      <header className="flex flex-col gap-1 border-b border-[var(--border)] pb-3">
        <span className="text-[11px] uppercase tracking-wide text-[var(--muted-foreground)]">
          Chapter {chapter.order}
        </span>
        <h1 className="text-2xl font-semibold tracking-tight">{chapter.title}</h1>
        <p className="text-sm text-[var(--muted-foreground)]">{chapter.summary}</p>
      </header>

      <Markdown source={chapter.body} />

      <nav className="mt-4 flex items-center justify-between gap-2 border-t border-[var(--border)] pt-4">
        {chapter.previous ? (
          <Button asChild variant="outline" size="sm">
            <Link to={`/learn/${chapter.previous.slug}`}>← {chapter.previous.title}</Link>
          </Button>
        ) : (
          <span />
        )}
        {chapter.next ? (
          <Button asChild variant="outline" size="sm">
            <Link to={`/learn/${chapter.next.slug}`}>{chapter.next.title} →</Link>
          </Button>
        ) : (
          <span />
        )}
      </nav>
    </article>
  )
}
