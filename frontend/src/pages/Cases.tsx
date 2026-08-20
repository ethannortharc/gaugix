import { FolderInput, Layers, ListPlus, RotateCcw, Search, Trash2, X } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { useBulkCaseOp, useCases, useSetOptions } from '@/api/cases'
import type { EvalCase } from '@/api/types'
import { AddCasesDialog, type AddCasesMethod } from '@/components/AddCasesDialog'
import { CaseEditorDialog } from '@/components/CaseEditorDialog'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { GenerateDialog } from '@/components/GenerateDialog'
import { ImportDialog } from '@/components/ImportDialog'
import { PageHeader } from '@/components/layout/AppShell'
import { LoadMore, TruncatedNotice } from '@/components/LoadMore'
import { ScoringSummary } from '@/components/ScoringBuilder'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/misc'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { pluralize, truncate } from '@/lib/format'
import { usePagedLimit } from '@/lib/paging'

type Scope = 'all' | 'unfiled' | 'trash'

/**
 * The case library — every case, whether or not a set claims it.
 *
 * Cases are independent entities that sets merely *reference*, but every
 * listing was scoped to a set. So a case removed from a set, or soft-deleted,
 * or created without one, still existed and could not be found again. This is
 * the page where those live (D-043).
 */
export default function CasesPage() {
  const [scope, setScope] = React.useState<Scope>('all')
  const [q, setQ] = React.useState('')
  const [setFilter, setSetFilter] = React.useState<number | null>(null)
  const [tagFilter, setTagFilter] = React.useState<string[]>([])
  const [selected, setSelected] = React.useState<Set<number>>(new Set())
  const [editing, setEditing] = React.useState<EvalCase | 'new' | null>(null)
  const [adding, setAdding] = React.useState(false)
  const [importing, setImporting] = React.useState(false)
  const [generating, setGenerating] = React.useState(false)

  const { limit, more, reset } = usePagedLimit()
  // Every set, so the filter can name every set (D-064).
  const sets = useSetOptions()
  const query = useCases({
    q: q || undefined,
    tags: tagFilter.length ? tagFilter : undefined,
    trashed: scope === 'trash',
    unfiled: scope === 'unfiled' || undefined,
    set_id: scope === 'all' && setFilter !== null ? setFilter : undefined,
    limit,
  })

  React.useEffect(() => {
    reset()
    setSelected(new Set())
  }, [scope, q, setFilter, tagFilter, reset])

  const cases = React.useMemo(() => query.data?.items ?? [], [query.data])
  // Drawn from the loaded page, like the set page's. A tag on a case you have
  // not scrolled to cannot be offered, but every tag you can see can be used.
  const allTags = React.useMemo(() => [...new Set(cases.flatMap((c) => c.tags))].sort(), [cases])

  // Acting on a row that has been filtered away would be invisible surgery.
  React.useEffect(() => {
    setSelected((prev) => {
      const visible = new Set(cases.map((c) => c.id))
      const next = new Set([...prev].filter((id) => visible.has(id)))
      return next.size === prev.size ? prev : next
    })
  }, [cases])

  const allSelected = cases.length > 0 && selected.size === cases.length

  function chooseAddMethod(method: AddCasesMethod) {
    setAdding(false)
    if (method === 'manual') setEditing('new')
    if (method === 'import') setImporting(true)
    if (method === 'ai') setGenerating(true)
  }

  return (
    <>
      <PageHeader
        title="Case library"
        description="Every case you have written or imported. Cases belong here, not to a set — a set is one ordered view over them."
        actions={
          <Button size="sm" onClick={() => setAdding(true)}>
            <ListPlus />
            Add cases
          </Button>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Tabs value={scope} onValueChange={(value) => setScope(value as Scope)}>
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="unfiled">In no set</TabsTrigger>
            <TabsTrigger value="trash">
              <Trash2 className="size-3.5" />
              Trash
            </TabsTrigger>
          </TabsList>
        </Tabs>

        <div className="relative min-w-56 max-w-sm flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
          <Input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="Search every case…"
            className="pl-8"
            aria-label="Search cases"
          />
        </div>

        {scope === 'all' ? (
          <Select
            value={setFilter === null ? 'any' : String(setFilter)}
            onValueChange={(value) => setSetFilter(value === 'any' ? null : Number(value))}
          >
            <SelectTrigger className="w-52" aria-label="Filter by set">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="any">Any set</SelectItem>
              {(sets.data?.items ?? []).map((set) => (
                <SelectItem key={set.id} value={String(set.id)}>
                  {set.name}
                </SelectItem>
              ))}
              {sets.truncated ? (
                <div className="px-2 py-1.5">
                  <TruncatedNotice
                    shown={sets.data?.items.length ?? 0}
                    total={sets.total}
                    noun="set"
                    hint="Filter from the set's own page instead."
                  />
                </div>
              ) : null}
            </SelectContent>
          </Select>
        ) : null}

        {allTags.map((tag) => {
          const active = tagFilter.includes(tag)
          return (
            <button
              key={tag}
              type="button"
              onClick={() =>
                setTagFilter((prev) => (active ? prev.filter((t) => t !== tag) : [...prev, tag]))
              }
              aria-pressed={active}
            >
              <Badge variant={active ? 'primary' : 'outline'} className="cursor-pointer">
                {tag}
              </Badge>
            </button>
          )
        })}
        {tagFilter.length > 0 ? (
          <Button variant="ghost" size="sm" onClick={() => setTagFilter([])}>
            <X />
            Clear tags
          </Button>
        ) : null}
      </div>

      {selected.size > 0 ? (
        <BulkBar
          selected={[...selected]}
          scope={scope}
          onDone={() => setSelected(new Set())}
          sets={sets.data?.items ?? []}
          setsTotal={sets.total}
        />
      ) : null}

      {query.isLoading ? (
        <LoadingState label="Loading cases…" rows={6} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : cases.length === 0 ? (
        <EmptyState
          icon={<Layers className="size-6" />}
          title={
            scope === 'trash'
              ? 'The trash is empty'
              : scope === 'unfiled'
                ? 'Every case belongs to a set'
                : 'No cases match'
          }
          description={
            scope === 'unfiled'
              ? 'Cases show up here when they are created without a set, or removed from every set they were in. Nothing is stranded right now.'
              : 'Write one, import a file, or install a benchmark from the library.'
          }
          action={
            scope === 'all' && !q ? (
              <div className="flex flex-wrap justify-center gap-2">
                <Button size="sm" onClick={() => setAdding(true)}>
                  <ListPlus />
                  Add cases
                </Button>
                <Button asChild variant="outline" size="sm">
                  <Link to="/benchmarks">Browse benchmarks</Link>
                </Button>
              </div>
            ) : undefined
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <Checkbox
                    checked={allSelected}
                    onCheckedChange={(checked) =>
                      setSelected(checked === true ? new Set(cases.map((c) => c.id)) : new Set())
                    }
                    aria-label={
                      cases.length < (query.data?.total ?? 0)
                        ? `Select all ${cases.length} loaded cases`
                        : 'Select all cases'
                    }
                    title="Selects the rows loaded below. Load more first to act on the rest."
                  />
                </TableHead>
                <TableHead>Title</TableHead>
                <TableHead className="w-56">Sets</TableHead>
                <TableHead className="w-40">Scoring</TableHead>
                <TableHead className="w-48">Tags</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {cases.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>
                    <Checkbox
                      checked={selected.has(row.id)}
                      onCheckedChange={(checked) =>
                        setSelected((prev) => {
                          const next = new Set(prev)
                          if (checked === true) next.add(row.id)
                          else next.delete(row.id)
                          return next
                        })
                      }
                      aria-label={`Select ${row.title}`}
                    />
                  </TableCell>
                  <TableCell>
                    <Link
                      to={`/cases/${row.id}`}
                      className="font-medium hover:text-[var(--primary)] hover:underline"
                    >
                      {row.title}
                    </Link>
                    <p className="text-[11px] text-[var(--muted-foreground)]">
                      {truncate(row.input.at(-1)?.content ?? '', 90)}
                    </p>
                  </TableCell>
                  <TableCell>
                    {row.sets.length === 0 ? (
                      <Badge
                        variant="outline"
                        title="This case is in no set, so no run will reach it."
                      >
                        in no set
                      </Badge>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {row.sets.map((set) => (
                          <Link key={set.id} to={`/sets/${set.id}`}>
                            <Badge variant="default" className="cursor-pointer hover:underline">
                              {set.name}
                            </Badge>
                          </Link>
                        ))}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    {row.scoring.length === 0 ? (
                      <span className="text-[11px] text-[var(--muted-foreground)]">
                        inherits the set’s
                      </span>
                    ) : (
                      <ScoringSummary scoring={row.scoring} inherits={row.sets.length > 0} />
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {row.tags.map((tag) => (
                        <Badge key={tag}>{tag}</Badge>
                      ))}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <LoadMore
            shown={cases.length}
            total={query.data?.total ?? cases.length}
            noun="case"
            onMore={more}
            busy={query.isFetching}
          />
        </div>
      )}

      <CaseEditorDialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        caseData={editing === 'new' ? null : editing}
      />
      <AddCasesDialog open={adding} onOpenChange={setAdding} onChoose={chooseAddMethod} />
      {/* No `setId`: cases imported here are unfiled until a set claims them. */}
      <ImportDialog open={importing} onOpenChange={setImporting} />
      <GenerateDialog open={generating} onOpenChange={setGenerating} />
    </>
  )
}

function BulkBar({
  selected,
  scope,
  sets,
  setsTotal,
  onDone,
}: {
  selected: number[]
  scope: Scope
  sets: { id: number; name: string }[]
  /** The library's size, not the page's — so "add to a set" can admit it is
   *  offering a prefix of it rather than dropping the rest in silence. */
  setsTotal: number
  onDone: () => void
}) {
  const bulk = useBulkCaseOp()
  const [target, setTarget] = React.useState<string>('')
  const [purging, setPurging] = React.useState(false)

  function run(body: Parameters<typeof bulk.mutate>[0], message: string) {
    bulk.mutate(body, {
      onSuccess: (result) => {
        toast.success(`${message} ${result.count} ${pluralize(result.count, 'case')}`)
        onDone()
      },
      onError: (error) => toast.error(error.message),
    })
  }

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-[var(--primary)]/40 bg-[var(--primary)]/5 px-3 py-2">
      <span className="text-sm font-medium">
        {selected.length} {pluralize(selected.length, 'case')} selected
      </span>

      {scope === 'trash' ? (
        <>
          <Button
            variant="outline"
            size="sm"
            disabled={bulk.isPending}
            onClick={() => run({ op: 'restore', case_ids: selected }, 'Restored')}
          >
            <RotateCcw />
            Restore
          </Button>
          {/*
            The trash could only be filled, never emptied. Purge has existed on
            the server since the trash did; it just had no button.
          */}
          <Button
            variant="ghost"
            size="sm"
            className="text-[var(--destructive)]"
            disabled={bulk.isPending}
            onClick={() => setPurging(true)}
          >
            <Trash2 />
            Delete permanently
          </Button>
        </>
      ) : (
        <>
          {/* The fix for the orphan problem: put stranded cases back to work. */}
          <Select value={target} onValueChange={setTarget}>
            <SelectTrigger className="h-8 w-48" aria-label="Add to set">
              <SelectValue placeholder="Add to a set…" />
            </SelectTrigger>
            <SelectContent>
              {sets.map((set) => (
                <SelectItem key={set.id} value={String(set.id)}>
                  {set.name}
                </SelectItem>
              ))}
              {setsTotal > sets.length ? (
                <div className="px-2 py-1.5">
                  <TruncatedNotice
                    shown={sets.length}
                    total={setsTotal}
                    noun="set"
                    hint="The remaining destinations cannot be selected from this menu yet."
                  />
                </div>
              ) : null}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            disabled={!target || bulk.isPending}
            onClick={() =>
              run(
                {
                  op: 'move',
                  case_ids: selected,
                  target_set_id: Number(target),
                  mode: 'copy',
                },
                'Added',
              )
            }
          >
            <FolderInput />
            Add
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-[var(--destructive)]"
            disabled={bulk.isPending}
            onClick={() => run({ op: 'delete', case_ids: selected }, 'Moved to trash:')}
          >
            <Trash2 />
            Move to trash
          </Button>
        </>
      )}

      <Button variant="ghost" size="sm" className="ml-auto" onClick={onDone}>
        <X />
        Clear
      </Button>

      <ConfirmDialog
        open={purging}
        onOpenChange={setPurging}
        title={`Permanently delete ${selected.length} ${pluralize(selected.length, 'case')}?`}
        description="They leave the trash for good. Runs that already used them keep their frozen snapshots, so past results are unaffected."
        impact={[
          `${selected.length} ${pluralize(selected.length, 'case')} destroyed`,
          'their membership of every set removed',
        ]}
        confirmText="delete"
        busy={bulk.isPending}
        onConfirm={() => {
          run({ op: 'purge', case_ids: selected }, 'Permanently deleted')
          setPurging(false)
        }}
      />
    </div>
  )
}
