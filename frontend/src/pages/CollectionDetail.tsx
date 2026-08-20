import {
  ArrowLeft,
  ChevronRight,
  ExternalLink,
  Folder,
  FolderOpen,
  ListPlus,
  Play,
  Search,
} from 'lucide-react'
import * as React from 'react'
import { Link, useParams } from 'react-router-dom'

import { useCollection, useCollections, useSets } from '@/api/cases'
import type { EvalCollection, EvalSet } from '@/api/types'
import { PageHeader } from '@/components/layout/AppShell'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { pluralize } from '@/lib/format'

function descendants(rows: EvalCollection[], rootId: number): EvalCollection[] {
  const byParent = new Map<number | null, EvalCollection[]>()
  for (const row of rows) {
    byParent.set(row.parent_id, [...(byParent.get(row.parent_id) ?? []), row])
  }
  const result: EvalCollection[] = []
  const pending = [rootId]
  while (pending.length) {
    const current = pending.shift()
    if (current === undefined) break
    const row = rows.find((item) => item.id === current)
    if (row) result.push(row)
    pending.push(...(byParent.get(current) ?? []).map((item) => item.id))
  }
  return result.sort(
    (a, b) =>
      a.path.length - b.path.length || a.position - b.position || a.name.localeCompare(b.name),
  )
}

function getSource(collection: EvalCollection): string | null {
  const value = collection.provenance.source_url ?? collection.provenance.url
  return typeof value === 'string' ? value : null
}

export default function CollectionDetailPage() {
  const params = useParams()
  const collectionId = Number(params.id)
  const collectionQuery = useCollection(collectionId)
  const collectionsQuery = useCollections()
  const setsQuery = useSets({
    collection_id: collectionId,
    include_descendants: true,
    visibility: ['primary', 'fixture', 'hidden'],
    limit: 500,
  })
  const [q, setQ] = React.useState('')

  if (collectionQuery.isLoading || collectionsQuery.isLoading || setsQuery.isLoading) {
    return <LoadingState label="Loading suite…" rows={5} />
  }
  if (collectionQuery.isError) {
    return (
      <ErrorState error={collectionQuery.error} onRetry={() => void collectionQuery.refetch()} />
    )
  }
  if (collectionsQuery.isError) {
    return (
      <ErrorState error={collectionsQuery.error} onRetry={() => void collectionsQuery.refetch()} />
    )
  }
  if (setsQuery.isError) {
    return <ErrorState error={setsQuery.error} onRetry={() => void setsQuery.refetch()} />
  }
  if (!collectionQuery.data) return null

  const collection = collectionQuery.data
  const branch = descendants(collectionsQuery.data?.items ?? [], collectionId)
  const needle = q.trim().toLocaleLowerCase()
  const allSets = setsQuery.data?.items ?? []
  const visibleSets = allSets.filter(
    (set) =>
      !needle ||
      set.name.toLocaleLowerCase().includes(needle) ||
      set.description?.toLocaleLowerCase().includes(needle) ||
      set.logical_key?.toLocaleLowerCase().includes(needle),
  )
  const source = getSource(collection)

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <Button asChild variant="ghost" size="icon-sm" aria-label="Back to suites">
              <Link to="/sets">
                <ArrowLeft />
              </Link>
            </Button>
            {collection.name}
          </span>
        }
        description={collection.description}
        actions={
          allSets.length > 0 ? (
            <Button asChild size="sm">
              <Link to="/runs/new">
                <Play />
                Choose sets to run
              </Link>
            </Button>
          ) : null
        }
      >
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <Badge variant="outline">{collection.descendant_set_count} sets</Badge>
          <Badge variant="outline">{collection.descendant_case_count} cases</Badge>
          {source ? (
            <a
              href={source}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-[var(--primary)] hover:underline"
            >
              Official source <ExternalLink className="size-3" />
            </a>
          ) : null}
        </div>
      </PageHeader>

      <div className="mb-4 max-w-md">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
          <Input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="Find a logical set or variant…"
            className="pl-8"
            aria-label="Search this suite"
          />
        </div>
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
        <Card className="lg:sticky lg:top-0">
          <CardHeader className="pb-2">
            <CardTitle>Suite structure</CardTitle>
            <CardDescription>Folders and their direct set counts</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-0.5">
            {branch.map((folder) => (
              <a
                key={folder.id}
                href={`#collection-${folder.id}`}
                className="flex items-center gap-2 rounded-md py-1.5 pr-2 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                style={{ paddingLeft: `${8 + (folder.depth - collection.depth) * 14}px` }}
              >
                {folder.id === collectionId ? (
                  <FolderOpen className="size-3.5 shrink-0" />
                ) : (
                  <Folder className="size-3.5 shrink-0" />
                )}
                <span className="min-w-0 flex-1 truncate">{folder.name}</span>
                <span className="tabular text-[10px]">{folder.direct_set_count}</span>
              </a>
            ))}
          </CardContent>
        </Card>

        <div className="min-w-0 space-y-3">
          {visibleSets.length === 0 ? (
            <EmptyState
              icon={<Search className="size-6" />}
              title={q ? 'No sets match' : 'This suite has no sets yet'}
              description={q ? `Nothing in this suite matches “${q}”.` : undefined}
              action={
                q ? (
                  <Button variant="outline" size="sm" onClick={() => setQ('')}>
                    Clear search
                  </Button>
                ) : undefined
              }
            />
          ) : (
            branch.map((folder) => {
              const rows = visibleSets.filter((set) => set.collection_id === folder.id)
              if (rows.length === 0) return null
              return (
                <CollectionSection
                  key={folder.id}
                  folder={folder}
                  sets={rows}
                  forceOpen={Boolean(q) || folder.id === collectionId}
                />
              )
            })
          )}
        </div>
      </div>
    </>
  )
}

function CollectionSection({
  folder,
  sets,
  forceOpen,
}: {
  folder: EvalCollection
  sets: EvalSet[]
  forceOpen: boolean
}) {
  const logical = new Map<string, EvalSet[]>()
  for (const set of sets) {
    const key = set.logical_key || set.name
    logical.set(key, [...(logical.get(key) ?? []), set])
  }
  const caseCount = sets.reduce((total, set) => total + set.case_count, 0)
  return (
    <details
      id={`collection-${folder.id}`}
      open={forceOpen}
      className="scroll-mt-3 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]"
    >
      <summary className="flex cursor-pointer list-none items-start gap-3 px-4 py-3 hover:bg-[var(--muted)]/50">
        <Folder className="mt-0.5 size-4 shrink-0 text-[var(--primary)]" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1 text-[10px] text-[var(--muted-foreground)]">
            {folder.path.map((part, index) => (
              <React.Fragment key={`${part}-${index}`}>
                {index > 0 ? <ChevronRight className="size-3" /> : null}
                <span>{part}</span>
              </React.Fragment>
            ))}
          </div>
          <h2 className="text-sm font-semibold">{folder.name}</h2>
          {folder.description ? (
            <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">{folder.description}</p>
          ) : null}
        </div>
        <Badge variant="outline">{logical.size} logical sets</Badge>
        <Badge variant="outline">{caseCount} cases</Badge>
      </summary>
      <div className="divide-y divide-[var(--border)] border-t border-[var(--border)]">
        {[...logical.entries()].map(([key, variants]) => (
          <LogicalSet key={key} name={key} variants={variants} />
        ))}
      </div>
    </details>
  )
}

const VARIANT_ORDER = ['input', 'output', 'both']

function LogicalSet({ name, variants }: { name: string; variants: EvalSet[] }) {
  const ordered = [...variants].sort((a, b) => {
    const ai = a.variant ? VARIANT_ORDER.indexOf(a.variant) : -1
    const bi = b.variant ? VARIANT_ORDER.indexOf(b.variant) : -1
    return ai - bi || a.name.localeCompare(b.name)
  })
  const cases = ordered.reduce((total, set) => total + set.case_count, 0)
  if (ordered.length === 1) {
    const set = ordered[0]
    return (
      <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 hover:bg-[var(--muted)]/40">
        <Link
          to={`/sets/${set.id}`}
          className="min-w-0 flex-1 truncate text-sm font-medium hover:text-[var(--primary)] hover:underline"
        >
          {name}
        </Link>
        {set.variant ? <Badge variant="outline">{set.variant}</Badge> : null}
        <span className="tabular text-xs text-[var(--muted-foreground)]">
          {set.case_count} {pluralize(set.case_count, 'case')}
        </span>
        <Button asChild variant="ghost" size="sm">
          <Link to={`/sets/${set.id}?add=1`}>
            <ListPlus /> Add cases
          </Link>
        </Button>
        <Button asChild variant="ghost" size="sm">
          <Link to={`/runs/new?set_id=${set.id}`}>
            <Play /> Run
          </Link>
        </Button>
      </div>
    )
  }
  return (
    <details className="group/logical">
      <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-2.5 hover:bg-[var(--muted)]/40">
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{name}</span>
        <Badge variant="primary">{ordered.length} variants</Badge>
        <span className="tabular text-xs text-[var(--muted-foreground)]">
          {cases} {pluralize(cases, 'case')}
        </span>
      </summary>
      <div className="bg-[var(--muted)]/20 px-4 py-2">
        {ordered.map((set) => (
          <div
            key={set.id}
            className="flex flex-wrap items-center gap-2 border-b border-[var(--border)]/70 py-2 last:border-0"
          >
            <Link
              to={`/sets/${set.id}`}
              className="min-w-0 flex-1 text-sm hover:text-[var(--primary)] hover:underline"
            >
              {set.name}
            </Link>
            {set.variant ? <Badge variant="outline">{set.variant}</Badge> : null}
            <span className="tabular text-xs text-[var(--muted-foreground)]">
              {set.case_count} cases
            </span>
            <Button asChild variant="ghost" size="sm">
              <Link to={`/sets/${set.id}?add=1`}>
                <ListPlus /> Add
              </Link>
            </Button>
            <Button asChild variant="ghost" size="sm">
              <Link to={`/runs/new?set_id=${set.id}`}>
                <Play /> Run
              </Link>
            </Button>
          </div>
        ))}
      </div>
    </details>
  )
}
