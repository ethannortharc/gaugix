import {
  ArrowLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Download,
  ExternalLink,
  FileText,
  Folder,
  FolderOpen,
  Layers,
  ListPlus,
  Pencil,
  Play,
  Search,
  Tag,
  Trash2,
  X,
} from 'lucide-react'
import * as React from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import {
  exportUrl,
  useBulkCaseOp,
  useAssignCasesNode,
  useCreateSetNode,
  useDeleteSetNode,
  useDetachCases,
  useReorderCases,
  useSet,
  useSetCases,
  useSetNodes,
  useSetOptions,
  useUpdateSetNode,
} from '@/api/cases'
import type { EvalCase, EvalSetNode, ExportFormat } from '@/api/types'
import { AddCasesDialog, type AddCasesMethod } from '@/components/AddCasesDialog'
import { ProvenanceCard } from '@/components/BenchmarkBits'
import { ConfirmDialog } from '@/components/ConfirmDialog'
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
import { Field, Input, Textarea } from '@/components/ui/input'
import { Checkbox, Separator, Tooltip } from '@/components/ui/misc'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
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
import { cn } from '@/lib/utils'

export default function SetDetailPage() {
  const params = useParams()
  const setId = Number(params.id)
  const [searchParams, setSearchParams] = useSearchParams()

  const [q, setQ] = React.useState('')
  const [tagFilter, setTagFilter] = React.useState<string[]>([])
  const [selected, setSelected] = React.useState<Set<number>>(new Set())
  const [editing, setEditing] = React.useState<EvalCase | 'new' | null>(null)
  const [importing, setImporting] = React.useState(false)
  const [generating, setGenerating] = React.useState(false)
  const [adding, setAdding] = React.useState(false)
  const [addTargetNodeId, setAddTargetNodeId] = React.useState<number | undefined>()
  const [editingSet, setEditingSet] = React.useState(false)
  const [selectedBranch, setSelectedBranch] = React.useState<number | 'ungrouped' | null>(null)

  const setQuery = useSet(setId)
  const nodesQuery = useSetNodes(setId)
  const { limit, more, reset } = usePagedLimit()
  const casesQuery = useSetCases(setId, {
    q: q || undefined,
    tags: tagFilter.length ? tagFilter : undefined,
    node_id: typeof selectedBranch === 'number' ? selectedBranch : undefined,
    ungrouped: selectedBranch === 'ungrouped' || undefined,
    limit,
  })

  // A benchmark install can put thousands of cases in one set, so the window
  // starts small and grows. Narrowing the filter restarts it.
  React.useEffect(() => {
    reset()
  }, [q, tagFilter, selectedBranch, reset])

  React.useEffect(() => {
    if (searchParams.get('add') !== '1') return
    setAdding(true)
    const next = new URLSearchParams(searchParams)
    next.delete('add')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

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
  const nodes = nodesQuery.data ?? []
  const activeNode =
    typeof selectedBranch === 'number'
      ? (nodes.find((node) => node.id === selectedBranch) ?? null)
      : null
  const addTargetNode = nodes.find((node) => node.id === addTargetNodeId)

  function chooseAddMethod(method: AddCasesMethod, nodeId?: number) {
    setAdding(false)
    setAddTargetNodeId(nodeId)
    if (method === 'manual') setEditing('new')
    if (method === 'import') setImporting(true)
    if (method === 'ai') setGenerating(true)
  }

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <Button asChild variant="ghost" size="icon-sm" aria-label="Back to sets">
              <Link
                to={
                  setQuery.data?.collection_id
                    ? `/collections/${setQuery.data.collection_id}`
                    : '/sets'
                }
              >
                <ArrowLeft />
              </Link>
            </Button>
            {set.name}
          </span>
        }
        description={set.description}
        actions={
          <>
            <Button
              size="sm"
              onClick={() => {
                setAddTargetNodeId(typeof selectedBranch === 'number' ? selectedBranch : undefined)
                setAdding(true)
              }}
            >
              <ListPlus />
              Add cases
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link to={`/runs/new?set_id=${setId}`}>
                <Play />
                Run this set
              </Link>
            </Button>
            <ExportMenu setId={setId} />
            <Button variant="outline" size="sm" onClick={() => setEditingSet(true)}>
              <Pencil />
              Edit set
            </Button>
          </>
        }
      >
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {set.collection_id && set.collection_path.length > 0 ? (
            <Link
              to={`/collections/${set.collection_id}`}
              className="mr-1 inline-flex items-center gap-1 text-[11px] text-[var(--primary)] hover:underline"
            >
              {set.collection_path.join(' / ')}
              <ChevronRight className="size-3" />
            </Link>
          ) : null}
          {set.variant ? <Badge variant="primary">variant: {set.variant}</Badge> : null}
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

      <div className="grid items-start gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
        <SetTreePanel
          setId={setId}
          caseCount={set.case_count}
          nodes={nodes}
          loading={nodesQuery.isLoading}
          selected={selectedBranch}
          onSelected={setSelectedBranch}
          onAdd={(nodeId) => {
            setAddTargetNodeId(nodeId)
            setAdding(true)
          }}
        />

        <section className="min-w-0" aria-label="Cases in selected branch">
          {activeNode ? (
            <BranchSummary
              node={activeNode}
              onAdd={() => {
                setAddTargetNodeId(activeNode.id)
                setAdding(true)
              }}
            />
          ) : null}
          {selectedBranch === 'ungrouped' ? (
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold">Ungrouped cases</h2>
                <p className="text-xs text-[var(--muted-foreground)]">
                  Cases in this set that have not been assigned to a branch.
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setAddTargetNodeId(undefined)
                  setAdding(true)
                }}
              >
                <ListPlus /> Add cases here
              </Button>
            </div>
          ) : null}

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
                    setTagFilter((prev) =>
                      active ? prev.filter((t) => t !== tag) : [...prev, tag],
                    )
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
            <BulkBar
              setId={setId}
              nodes={nodes}
              selected={[...selected]}
              onDone={() => setSelected(new Set())}
            />
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
                title={
                  selectedBranch === null ? 'No cases in this set yet' : 'No cases in this branch'
                }
                description={
                  selectedBranch === null
                    ? 'Write one, import a batch, or have AI draft candidates — the destination set and branch stay explicit throughout.'
                    : 'Create a case here or select cases from another branch and move them here.'
                }
                action={
                  <div className="flex flex-wrap justify-center gap-2">
                    <Button
                      size="sm"
                      onClick={() => {
                        setAddTargetNodeId(
                          typeof selectedBranch === 'number' ? selectedBranch : undefined,
                        )
                        setAdding(true)
                      }}
                    >
                      <ListPlus />
                      Add cases
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
                  selectedBranch === null &&
                  !q &&
                  tagFilter.length === 0 &&
                  cases.length >= (casesQuery.data?.total ?? 0)
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
        </section>
      </div>

      <CaseEditorDialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        caseData={editing === 'new' ? null : editing}
        setId={setId}
        nodeId={editing === 'new' ? addTargetNodeId : undefined}
        setDefaultScoring={set.default_scoring}
      />
      <AddCasesDialog
        open={adding}
        onOpenChange={setAdding}
        setName={set.name}
        nodes={nodes}
        defaultNodeId={addTargetNodeId}
        onChoose={chooseAddMethod}
      />
      <SetDialog open={editingSet} onOpenChange={setEditingSet} editing={set} />
      <ImportDialog
        open={importing}
        onOpenChange={setImporting}
        setId={setId}
        setName={set.name}
        nodeId={addTargetNodeId}
        nodePath={addTargetNode?.path}
      />
      <GenerateDialog
        open={generating}
        onOpenChange={setGenerating}
        setId={setId}
        setName={set.name}
        nodeId={addTargetNodeId}
        nodePath={addTargetNode?.path}
      />
    </>
  )
}

type BranchSelection = number | 'ungrouped' | null

function SetTreePanel({
  setId,
  caseCount,
  nodes,
  loading,
  selected,
  onSelected,
  onAdd,
}: {
  setId: number
  caseCount: number
  nodes: EvalSetNode[]
  loading: boolean
  selected: BranchSelection
  onSelected: (value: BranchSelection) => void
  onAdd: (nodeId?: number) => void
}) {
  const [editing, setEditing] = React.useState<EvalSetNode | 'new' | null>(null)
  const grouped = nodes.reduce((total, node) => total + node.direct_case_count, 0)
  const ungrouped = Math.max(0, caseCount - grouped)
  const selectedNode =
    typeof selected === 'number' ? (nodes.find((node) => node.id === selected) ?? null) : null
  const children = React.useMemo(() => {
    const map = new Map<number | null, EvalSetNode[]>()
    for (const node of nodes) {
      const siblings = map.get(node.parent_id) ?? []
      siblings.push(node)
      map.set(node.parent_id, siblings)
    }
    for (const siblings of map.values()) siblings.sort((a, b) => a.position - b.position)
    return map
  }, [nodes])

  function renderNodes(parentId: number | null): React.ReactNode {
    return (children.get(parentId) ?? []).map((node) => (
      <React.Fragment key={node.id}>
        <button
          type="button"
          onClick={() => onSelected(node.id)}
          className={cn(
            'flex w-full items-center gap-1.5 rounded-md py-1.5 pr-2 text-left text-xs transition-colors',
            selected === node.id
              ? 'bg-[var(--primary)]/12 font-medium text-[var(--primary)]'
              : 'text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]',
          )}
          style={{ paddingLeft: `${8 + node.depth * 14}px` }}
        >
          <span className="w-3" />
          {selected === node.id ? (
            <FolderOpen className="size-3.5 shrink-0" />
          ) : (
            <Folder className="size-3.5 shrink-0" />
          )}
          <span className="min-w-0 flex-1 truncate">{node.name}</span>
          <span className="tabular text-[10px] opacity-70">{node.descendant_case_count}</span>
        </button>
        {renderNodes(node.id)}
      </React.Fragment>
    ))
  }

  return (
    <aside className="sticky top-0 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-2.5">
        <div>
          <h2 className="text-xs font-semibold">Set structure</h2>
          <p className="text-[10px] text-[var(--muted-foreground)]">
            Browse without loading all rows
          </p>
        </div>
        <div className="flex items-center gap-0.5">
          {selectedNode ? (
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => setEditing(selectedNode)}
              aria-label={`Edit ${selectedNode.name}`}
            >
              <Pencil />
            </Button>
          ) : null}
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setEditing('new')}
            aria-label="Add branch"
          >
            <ListPlus />
          </Button>
        </div>
      </div>
      <div className="max-h-[62vh] overflow-y-auto p-2">
        <button
          type="button"
          onClick={() => onSelected(null)}
          className={cn(
            'mb-0.5 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors',
            selected === null
              ? 'bg-[var(--primary)]/12 font-medium text-[var(--primary)]'
              : 'text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]',
          )}
        >
          <Layers className="size-3.5" />
          <span className="flex-1">All cases</span>
          <span className="tabular text-[10px] opacity-70">{caseCount}</span>
        </button>
        {loading ? (
          <p className="px-2 py-3 text-xs text-[var(--muted-foreground)]">Loading branches…</p>
        ) : (
          renderNodes(null)
        )}
        {ungrouped > 0 ? (
          <button
            type="button"
            onClick={() => onSelected('ungrouped')}
            className={cn(
              'mt-0.5 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors',
              selected === 'ungrouped'
                ? 'bg-[var(--primary)]/12 font-medium text-[var(--primary)]'
                : 'text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]',
            )}
          >
            <FileText className="size-3.5" />
            <span className="flex-1">Ungrouped</span>
            <span className="tabular text-[10px] opacity-70">{ungrouped}</span>
          </button>
        ) : null}
      </div>
      <div className="flex flex-col gap-2 border-t border-[var(--border)] p-2">
        <Button
          variant="secondary"
          size="sm"
          className="w-full justify-start"
          onClick={() => onAdd(typeof selected === 'number' ? selected : undefined)}
        >
          <ListPlus />
          {selectedNode ? `Add to ${selectedNode.name}` : 'Add cases'}
        </Button>
        <p className="px-1 text-[10px] leading-relaxed text-[var(--muted-foreground)]">
          Imports with <code className="font-mono">group_path</code> build nested branches below the
          selected destination.
        </p>
      </div>
      <NodeDialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        setId={setId}
        nodes={nodes}
        editing={editing === 'new' ? null : editing}
        defaultParentId={editing === 'new' && selectedNode ? selectedNode.id : null}
        onDeleted={(id) => {
          if (selected === id) onSelected(null)
          setEditing(null)
        }}
      />
    </aside>
  )
}

function BranchSummary({ node, onAdd }: { node: EvalSetNode; onAdd: () => void }) {
  const source =
    node.effective_provenance.source_url ??
    node.effective_provenance.url ??
    node.effective_provenance.huggingface_url
  const sourceUrl = typeof source === 'string' ? source : null
  return (
    <div className="mb-3 flex flex-wrap items-start gap-3 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="mb-0.5 flex items-center gap-1 text-[10px] text-[var(--muted-foreground)]">
          {node.path.map((part, index) => (
            <React.Fragment key={`${part}-${index}`}>
              {index > 0 ? <ChevronRight className="size-3" /> : null}
              <span>{part}</span>
            </React.Fragment>
          ))}
        </div>
        <h2 className="text-sm font-semibold">{node.name}</h2>
        <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
          {node.description || 'No branch description yet.'}
        </p>
      </div>
      <div className="flex items-center gap-2 text-xs">
        <Badge variant="outline">{node.descendant_case_count} cases</Badge>
        {sourceUrl ? (
          <a
            href={sourceUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[var(--primary)] hover:underline"
          >
            Source
            <ExternalLink className="size-3" />
          </a>
        ) : null}
        <Button variant="outline" size="sm" onClick={onAdd}>
          <ListPlus /> Add cases here
        </Button>
      </div>
    </div>
  )
}

function NodeDialog({
  open,
  onOpenChange,
  setId,
  nodes,
  editing,
  defaultParentId,
  onDeleted,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  setId: number
  nodes: EvalSetNode[]
  editing: EvalSetNode | null
  defaultParentId: number | null
  onDeleted: (id: number) => void
}) {
  const create = useCreateSetNode(setId)
  const update = useUpdateSetNode(setId)
  const remove = useDeleteSetNode(setId)
  const [confirmDelete, setConfirmDelete] = React.useState(false)
  const [name, setName] = React.useState('')
  const [description, setDescription] = React.useState('')
  const [parentId, setParentId] = React.useState<number | null>(null)
  const [sourceUrl, setSourceUrl] = React.useState('')
  const [revision, setRevision] = React.useState('')
  const [licence, setLicence] = React.useState('')

  React.useEffect(() => {
    if (!open) return
    setName(editing?.name ?? '')
    setDescription(editing?.description ?? '')
    setParentId(editing?.parent_id ?? defaultParentId)
    setSourceUrl(String(editing?.provenance.source_url ?? editing?.provenance.url ?? ''))
    setRevision(String(editing?.provenance.revision ?? ''))
    setLicence(String(editing?.provenance.licence ?? ''))
  }, [open, editing, defaultParentId])

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const provenance: Record<string, unknown> = { ...(editing?.provenance ?? {}) }
    delete provenance.url
    delete provenance.source_url
    delete provenance.revision
    delete provenance.licence
    if (sourceUrl.trim()) provenance.source_url = sourceUrl.trim()
    if (revision.trim()) provenance.revision = revision.trim()
    if (licence.trim()) provenance.licence = licence.trim()
    const body = {
      name: name.trim(),
      description: description.trim() || null,
      parent_id: parentId,
      provenance,
    }
    const callbacks = {
      onSuccess: () => {
        toast.success(editing ? 'Branch updated' : 'Branch created')
        onOpenChange(false)
      },
      onError: (error: Error) => toast.error(error.message),
    }
    if (editing) update.mutate({ id: editing.id, ...body }, callbacks)
    else create.mutate(body, callbacks)
  }

  const busy = create.isPending || update.isPending || remove.isPending
  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent widthClass="max-w-xl">
          <form onSubmit={submit} className="flex flex-col gap-4">
            <DialogHeader>
              <DialogTitle>{editing ? `Edit “${editing.name}”` : 'New branch'}</DialogTitle>
              <DialogDescription>
                Branches organise one EvalSet; they do not create separate metric contracts.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name" htmlFor="node-name">
                <Input
                  id="node-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  autoFocus
                  required
                />
              </Field>
              <Field label="Parent branch" htmlFor="node-parent">
                <Select
                  value={parentId === null ? '__root__' : String(parentId)}
                  onValueChange={(value) =>
                    setParentId(value === '__root__' ? null : Number(value))
                  }
                >
                  <SelectTrigger id="node-parent">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__root__">Top level</SelectItem>
                    {nodes
                      .filter((node) => node.id !== editing?.id)
                      .map((node) => (
                        <SelectItem key={node.id} value={String(node.id)}>
                          {'· '.repeat(node.depth)}
                          {node.name}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </Field>
            </div>
            <Field label="Description" htmlFor="node-description">
              <Textarea
                id="node-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={3}
                className="font-sans text-sm"
                placeholder="What this branch covers and why it exists."
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Official / source URL" htmlFor="node-source">
                <Input
                  id="node-source"
                  type="url"
                  value={sourceUrl}
                  onChange={(event) => setSourceUrl(event.target.value)}
                  placeholder="https://huggingface.co/…"
                />
              </Field>
              <Field label="Revision" htmlFor="node-revision">
                <Input
                  id="node-revision"
                  value={revision}
                  onChange={(event) => setRevision(event.target.value)}
                  placeholder="main / commit"
                />
              </Field>
              <Field label="Licence" htmlFor="node-licence">
                <Input
                  id="node-licence"
                  value={licence}
                  onChange={(event) => setLicence(event.target.value)}
                />
              </Field>
            </div>
            <DialogFooter className="justify-between">
              {editing ? (
                <Button
                  type="button"
                  variant="ghost"
                  className="mr-auto text-[var(--destructive)]"
                  onClick={() => setConfirmDelete(true)}
                >
                  <Trash2 />
                  Delete branch
                </Button>
              ) : (
                <span />
              )}
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={!name.trim() || busy}>
                {busy ? 'Saving…' : 'Save branch'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={`Delete “${editing?.name ?? ''}”?`}
        description="Only empty leaf branches can be deleted. Cases and child branches must be moved first."
        busy={remove.isPending}
        onConfirm={() => {
          if (!editing) return
          remove.mutate(editing.id, {
            onSuccess: () => {
              toast.success('Branch deleted')
              setConfirmDelete(false)
              onDeleted(editing.id)
            },
            onError: (error) => toast.error(error.message),
          })
        }}
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
  nodes,
  selected,
  onDone,
}: {
  setId: number
  nodes: EvalSetNode[]
  selected: number[]
  onDone: () => void
}) {
  const bulk = useBulkCaseOp()
  const detach = useDetachCases(setId)
  const assign = useAssignCasesNode(setId)
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

      {nodes.length > 0 ? (
        <Select
          onValueChange={(value) => {
            const nodeId = value === '__ungrouped__' ? null : Number(value)
            assign.mutate(
              { case_ids: selected, node_id: nodeId },
              {
                onSuccess: (result) => {
                  toast.success(`Moved ${result.count} ${pluralize(result.count, 'case')}`)
                  onDone()
                },
                onError: (error) => toast.error(error.message),
              },
            )
          }}
        >
          <SelectTrigger className="h-8 w-44" aria-label="Move to branch">
            <SelectValue placeholder="Move to branch…" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__ungrouped__">Ungrouped</SelectItem>
            {nodes.map((node) => (
              <SelectItem key={node.id} value={String(node.id)}>
                {'· '.repeat(node.depth)}
                {node.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}

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
