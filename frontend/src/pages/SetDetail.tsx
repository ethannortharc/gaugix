import {
  ArrowLeft,
  ChevronDown,
  ChevronUp,
  Download,
  FileUp,
  ListPlus,
  Pencil,
  Play,
  Search,
  Sparkles,
  Tag,
  Trash2,
  X,
} from 'lucide-react'
import * as React from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import {
  exportUrl,
  useBulkCaseOp,
  useDetachCases,
  useReorderCases,
  useSet,
  useSetCases,
  useSetOptions,
} from '@/api/cases'
import type { EvalCase, ExportFormat } from '@/api/types'
import { ProvenanceCard } from '@/components/BenchmarkBits'
import { GenerateDialog } from '@/components/GenerateDialog'
import { ImportDialog } from '@/components/ImportDialog'
import { PageHeader } from '@/components/layout/AppShell'
import { LoadMore, TruncatedNotice } from '@/components/LoadMore'
import { SetRunHistory } from '@/components/RunHistory'
import { SetDialog } from '@/pages/Sets'
import { usePagedLimit } from '@/lib/paging'
import { CaseEditorDialog } from '@/components/CaseEditorDialog'
import { ScoringSummary } from '@/components/ScoringBuilder'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox, Separator, Tooltip } from '@/components/ui/misc'
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
import { pluralize, truncate } from '@/lib/format'

export default function SetDetailPage() {
  const params = useParams()
  const setId = Number(params.id)

  const [q, setQ] = React.useState('')
  const [tagFilter, setTagFilter] = React.useState<string[]>([])
  const [selected, setSelected] = React.useState<Set<number>>(new Set())
  const [editing, setEditing] = React.useState<EvalCase | 'new' | null>(null)
  const [importing, setImporting] = React.useState(false)
  const [generating, setGenerating] = React.useState(false)
  const [editingSet, setEditingSet] = React.useState(false)

  const setQuery = useSet(setId)
  const { limit, more, reset } = usePagedLimit()
  const casesQuery = useSetCases(setId, {
    q: q || undefined,
    tags: tagFilter.length ? tagFilter : undefined,
    limit,
  })

  // A benchmark install can put thousands of cases in one set, so the window
  // starts small and grows. Narrowing the filter restarts it.
  React.useEffect(() => {
    reset()
  }, [q, tagFilter, reset])

  // Stable identity: a fresh [] on every render would re-run the hooks below.
  const cases = React.useMemo(() => casesQuery.data?.items ?? [], [casesQuery.data])
  const allTags = React.useMemo(() => [...new Set(cases.flatMap((c) => c.tags))].sort(), [cases])

  // Selecting a case then filtering it away would silently act on invisible rows.
  React.useEffect(() => {
    setSelected((prev) => {
      const visible = new Set(cases.map((c) => c.id))
      const next = new Set([...prev].filter((id) => visible.has(id)))
      return next.size === prev.size ? prev : next
    })
  }, [cases])

  if (setQuery.isLoading) return <LoadingState label="Loading set…" />
  if (setQuery.isError)
    return <ErrorState error={setQuery.error} onRetry={() => void setQuery.refetch()} />
  if (!setQuery.data) return null

  const set = setQuery.data

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <Button asChild variant="ghost" size="icon-sm" aria-label="Back to sets">
              <Link to="/sets">
                <ArrowLeft />
              </Link>
            </Button>
            {set.name}
          </span>
        }
        description={set.description}
        actions={
          <>
            <Button asChild size="sm">
              <Link to={`/runs/new?set_id=${setId}`}>
                <Play />
                Run this set
              </Link>
            </Button>
            <Button variant="outline" size="sm" onClick={() => setGenerating(true)}>
              <Sparkles />
              Generate with AI
            </Button>
            <Button variant="outline" size="sm" onClick={() => setImporting(true)}>
              <FileUp />
              Import
            </Button>
            <ExportMenu setId={setId} />
            <Button variant="outline" size="sm" onClick={() => setEditingSet(true)}>
              <Pencil />
              Edit set
            </Button>
            <Button variant="outline" size="sm" onClick={() => setEditing('new')}>
              <ListPlus />
              New case
            </Button>
          </>
        }
      >
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {set.tags.map((tag) => (
            <Badge key={tag}>{tag}</Badge>
          ))}
          {set.provenance.modified ? (
            <Badge variant="human" title={(set.provenance.modified_reasons ?? []).join(' ')}>
              modified since install
            </Badge>
          ) : null}
          {set.default_scoring.length > 0 ? (
            <Tooltip label="Cases with no scorers of their own inherit this config.">
              <span className="flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">
                default scoring:
                <ScoringSummary scoring={set.default_scoring} />
              </span>
            </Tooltip>
          ) : null}
        </div>
      </PageHeader>

      {/*
        Which dataset this actually is. Recorded at install and, until now,
        never shown — which made it useless for the one job it has: proving
        later which revision a number came from (D-056).
      */}
      <div className="mb-3">
        <ProvenanceCard provenance={set.provenance} />
      </div>

      <div className="mb-3">
        <SetRunHistory setId={setId} />
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 max-w-sm flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search cases…"
            className="pl-8"
            aria-label="Search cases in this set"
          />
        </div>
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
        <span className="ml-auto text-xs text-[var(--muted-foreground)]">
          {casesQuery.data?.total ?? 0} {pluralize(casesQuery.data?.total ?? 0, 'case')}
        </span>
      </div>

      {selected.size > 0 ? (
        <BulkBar setId={setId} selected={[...selected]} onDone={() => setSelected(new Set())} />
      ) : null}

      {casesQuery.isLoading ? (
        <LoadingState label="Loading cases…" rows={5} />
      ) : casesQuery.isError ? (
        <ErrorState error={casesQuery.error} onRetry={() => void casesQuery.refetch()} />
      ) : cases.length === 0 ? (
        q || tagFilter.length ? (
          <EmptyState
            icon={<Search className="size-6" />}
            title="No cases match these filters"
            action={
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setQ('')
                  setTagFilter([])
                }}
              >
                Clear filters
              </Button>
            }
          />
        ) : (
          <EmptyState
            icon={<ListPlus className="size-6" />}
            title="No cases in this set yet"
            description="Write one by hand, import a JSONL file, or have an assistant draft a batch — every route ends in the same preview-before-commit step."
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <Button size="sm" onClick={() => setEditing('new')}>
                  <ListPlus />
                  Write a case
                </Button>
                <Button variant="outline" size="sm" onClick={() => setGenerating(true)}>
                  <Sparkles />
                  Generate with AI
                </Button>
                <Button variant="outline" size="sm" onClick={() => setImporting(true)}>
                  <FileUp />
                  Import
                </Button>
              </div>
            }
          />
        )
      ) : (
        <>
          <CaseTable
            setId={setId}
            cases={cases}
            total={casesQuery.data?.total ?? cases.length}
            selected={selected}
            onSelected={setSelected}
            onEdit={setEditing}
            reorderable={
              !q && tagFilter.length === 0 && cases.length >= (casesQuery.data?.total ?? 0)
            }
          />
          <LoadMore
            shown={cases.length}
            total={casesQuery.data?.total ?? cases.length}
            noun="case"
            onMore={more}
            busy={casesQuery.isFetching}
          />
        </>
      )}

      <CaseEditorDialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        caseData={editing === 'new' ? null : editing}
        setId={setId}
        setDefaultScoring={set.default_scoring}
      />
      <SetDialog open={editingSet} onOpenChange={setEditingSet} editing={set} />
      <ImportDialog open={importing} onOpenChange={setImporting} setId={setId} setName={set.name} />
      <GenerateDialog
        open={generating}
        onOpenChange={setGenerating}
        setId={setId}
        setName={set.name}
      />
    </>
  )
}

function CaseTable({
  setId,
  cases,
  total,
  selected,
  onSelected,
  onEdit,
  reorderable,
}: {
  setId: number
  cases: EvalCase[]
  /** Cases in the set, so select-all can say when it covers only the page. */
  total: number
  selected: Set<number>
  onSelected: (next: Set<number>) => void
  onEdit: (c: EvalCase) => void
  reorderable: boolean
}) {
  const reorder = useReorderCases(setId)
  const allSelected = cases.length > 0 && cases.every((c) => selected.has(c.id))

  function toggle(id: number) {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onSelected(next)
  }

  function move(index: number, delta: number) {
    const target = index + delta
    if (target < 0 || target >= cases.length) return
    const ids = cases.map((c) => c.id)
    ;[ids[index], ids[target]] = [ids[target], ids[index]]
    reorder.mutate(ids, { onError: (error) => toast.error(error.message) })
  }

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-9">
              <Checkbox
                checked={allSelected}
                onCheckedChange={(checked) =>
                  onSelected(checked === true ? new Set(cases.map((c) => c.id)) : new Set())
                }
                aria-label={
                  cases.length < total
                    ? `Select all ${cases.length} loaded cases`
                    : 'Select all cases'
                }
                title="Selects the rows loaded below. Load more first to act on the rest."
              />
            </TableHead>
            <TableHead className="w-12">#</TableHead>
            <TableHead>Title</TableHead>
            <TableHead className="w-[28%]">Input</TableHead>
            <TableHead className="w-40">Scoring</TableHead>
            <TableHead className="w-44">Tags</TableHead>
            <TableHead className="w-24 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {cases.map((row, index) => (
            <TableRow key={row.id} data-state={selected.has(row.id) ? 'selected' : undefined}>
              <TableCell>
                <Checkbox
                  checked={selected.has(row.id)}
                  onCheckedChange={() => toggle(row.id)}
                  aria-label={`Select ${row.title}`}
                />
              </TableCell>
              <TableCell className="tabular text-xs text-[var(--muted-foreground)]">
                {row.position !== null ? row.position + 1 : '—'}
              </TableCell>
              <TableCell>
                <Link
                  to={`/cases/${row.id}`}
                  className="font-medium hover:text-[var(--primary)] hover:underline"
                >
                  {row.title}
                </Link>
              </TableCell>
              <TableCell className="text-xs text-[var(--muted-foreground)]">
                {truncate(row.input.map((m) => m.content).join(' ⏎ '), 110)}
              </TableCell>
              <TableCell>
                <ScoringSummary scoring={row.scoring} />
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {row.tags.map((tag) => (
                    <Badge key={tag}>{tag}</Badge>
                  ))}
                </div>
              </TableCell>
              <TableCell>
                <div className="flex items-center justify-end gap-0.5">
                  {reorderable ? (
                    <>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => move(index, -1)}
                        disabled={index === 0}
                        aria-label={`Move ${row.title} up`}
                      >
                        <ChevronUp />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => move(index, 1)}
                        disabled={index === cases.length - 1}
                        aria-label={`Move ${row.title} down`}
                      >
                        <ChevronDown />
                      </Button>
                    </>
                  ) : null}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => onEdit(row)}
                    aria-label={`Edit ${row.title}`}
                  >
                    <Pencil />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {!reorderable ? (
        <p className="border-t border-[var(--border)] px-3 py-1.5 text-[11px] text-[var(--muted-foreground)]">
          Reordering is available when no filters are active and every case is loaded — moving a row
          against a partial list would put it somewhere you cannot see.
        </p>
      ) : null}
    </div>
  )
}

function BulkBar({
  setId,
  selected,
  onDone,
}: {
  setId: number
  selected: number[]
  onDone: () => void
}) {
  const bulk = useBulkCaseOp()
  const detach = useDetachCases(setId)
  // Every set, so copy/move can reach every set (D-064).
  const sets = useSetOptions()
  const [tagDraft, setTagDraft] = React.useState('')

  const otherSets = (sets.data?.items ?? []).filter((s) => s.id !== setId)
  // Selecting cases and then running exactly those is the loop this page is
  // for: a failing case is fixed, re-run alone, and checked in seconds rather
  // than by re-running the four hundred around it.
  const runSelected = `/runs/new?set_id=${setId}&case_ids=${selected.join(',')}`

  function addTag() {
    const tags = tagDraft
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    if (tags.length === 0) return
    bulk.mutate(
      { op: 'tags', case_ids: selected, add_tags: tags },
      {
        onSuccess: (res) => {
          toast.success(`Tagged ${res.count} ${pluralize(res.count, 'case')}`)
          setTagDraft('')
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-[var(--primary)]/40 bg-[var(--primary)]/8 px-3 py-2">
      <span className="text-sm font-medium">
        {selected.length} {pluralize(selected.length, 'case')} selected
      </span>
      <Separator orientation="vertical" className="h-5" />

      <Button asChild size="sm">
        <Link to={runSelected}>
          <Play />
          Run {selected.length} {pluralize(selected.length, 'case')}
        </Link>
      </Button>

      <div className="flex items-center gap-1">
        <Tag className="size-3.5 text-[var(--muted-foreground)]" />
        <Input
          value={tagDraft}
          onChange={(e) => setTagDraft(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && addTag()}
          placeholder="add tags…"
          className="h-8 w-40"
          aria-label="Tags to add"
        />
        <Button variant="outline" size="sm" onClick={addTag} disabled={!tagDraft.trim()}>
          Add
        </Button>
      </div>

      {otherSets.length > 0 ? (
        <Select
          onValueChange={(value) => {
            const [mode, id] = value.split(':')
            bulk.mutate(
              {
                op: 'move',
                case_ids: selected,
                target_set_id: Number(id),
                source_set_id: mode === 'move' ? setId : undefined,
                mode: mode as 'copy' | 'move',
              },
              {
                onSuccess: (res) => {
                  toast.success(`${mode === 'move' ? 'Moved' : 'Copied'} ${res.count} cases`)
                  onDone()
                },
                onError: (error) => toast.error(error.message),
              },
            )
          }}
        >
          <SelectTrigger className="h-8 w-44" aria-label="Copy or move to another set">
            <SelectValue placeholder="Copy / move to…" />
          </SelectTrigger>
          <SelectContent>
            {otherSets.map((s) => (
              <SelectItem key={`copy-${s.id}`} value={`copy:${s.id}`}>
                Copy to {s.name}
              </SelectItem>
            ))}
            {otherSets.map((s) => (
              <SelectItem key={`move-${s.id}`} value={`move:${s.id}`}>
                Move to {s.name}
              </SelectItem>
            ))}
            {sets.truncated ? (
              <div className="px-2 py-1.5">
                <TruncatedNotice
                  shown={otherSets.length}
                  total={Math.max(sets.total - 1, otherSets.length)}
                  noun="set"
                  hint="The remaining destinations cannot be selected from this menu yet."
                />
              </div>
            ) : null}
          </SelectContent>
        </Select>
      ) : null}

      <Button
        variant="outline"
        size="sm"
        onClick={() =>
          detach.mutate(selected, {
            onSuccess: (res) => {
              toast.success(`Removed ${res.count} from this set (cases kept)`)
              onDone()
            },
            onError: (error) => toast.error(error.message),
          })
        }
      >
        Remove from set
      </Button>

      <Button
        variant="ghost"
        size="sm"
        className="text-[var(--destructive)]"
        onClick={() =>
          bulk.mutate(
            { op: 'delete', case_ids: selected },
            {
              onSuccess: (res) => {
                toast.success(`Moved ${res.count} to trash`)
                onDone()
              },
              onError: (error) => toast.error(error.message),
            },
          )
        }
      >
        <Trash2 />
        Delete
      </Button>

      <Button variant="ghost" size="sm" className="ml-auto" onClick={onDone}>
        <X />
        Clear
      </Button>
    </div>
  )
}

function ExportMenu({ setId }: { setId: number }) {
  const [format, setFormat] = React.useState<ExportFormat>('jsonl')
  return (
    <div className="flex items-center gap-1">
      <Select value={format} onValueChange={(f) => setFormat(f as ExportFormat)}>
        <SelectTrigger className="h-8 w-32" aria-label="Export format">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="jsonl">JSONL</SelectItem>
          <SelectItem value="yaml">YAML</SelectItem>
          <SelectItem value="json">JSON</SelectItem>
          {/*
            The two portable ones. Neither round-trips: CSV has nowhere to put a
            transcript or a scorer, and openai/evals has no scorer concept at
            all — so both drop that detail rather than encoding it into a field
            no other tool would read.
          */}
          <SelectItem value="csv">CSV</SelectItem>
          <SelectItem value="openai_evals">openai/evals</SelectItem>
        </SelectContent>
      </Select>
      <Button asChild variant="outline" size="sm">
        <a href={exportUrl({ format, setId })} download>
          <Download />
          Export
        </a>
      </Button>
      {LOSSY_FORMATS.includes(format) ? (
        <span className="text-[11px] text-[var(--muted-foreground)]">
          drops scorers &amp; multi-turn
        </span>
      ) : null}
    </div>
  )
}

/** Formats that cannot carry everything a case holds. */
const LOSSY_FORMATS: ExportFormat[] = ['csv', 'openai_evals']
