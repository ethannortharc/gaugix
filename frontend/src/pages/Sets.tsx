import { Layers, Plus, RotateCcw, Search, Trash2 } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { useCreateSet, useDeleteSet, useRestoreSet, useSets, useUpdateSet } from '@/api/cases'
import type { EvalSet, ScorerSpec } from '@/api/types'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { PageHeader } from '@/components/layout/AppShell'
import { ScoringBuilder } from '@/components/ScoringBuilder'
import { LoadMore } from '@/components/LoadMore'
import { usePagedLimit } from '@/lib/paging'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { TagInput } from '@/components/TagInput'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatRelative, pluralize } from '@/lib/format'

export default function SetsPage() {
  const [q, setQ] = React.useState('')
  const [view, setView] = React.useState<'live' | 'trash'>('live')
  const [creating, setCreating] = React.useState(false)

  // A library can outgrow one page, and a grid that silently stopped at 50
  // made every set past that unreachable from here.
  const { limit, more, reset } = usePagedLimit()
  const query = useSets({ q: q || undefined, trashed: view === 'trash', limit })

  React.useEffect(() => {
    reset()
  }, [q, view, reset])

  return (
    <>
      <PageHeader
        title="Eval sets"
        description="Your library of eval sets — the asset that compounds every time you add to it."
        actions={
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus />
            New set
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative min-w-56 max-w-sm flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search sets…"
            className="pl-8"
            aria-label="Search sets"
          />
        </div>
        <Tabs value={view} onValueChange={(v) => setView(v as 'live' | 'trash')}>
          <TabsList>
            <TabsTrigger value="live">Sets</TabsTrigger>
            <TabsTrigger value="trash">Trash</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {query.isLoading ? (
        <LoadingState label="Loading sets…" />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data && query.data.items.length > 0 ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {query.data.items.map((set) => (
              <SetCard key={set.id} set={set} trashed={view === 'trash'} />
            ))}
          </div>
          <LoadMore
            shown={query.data.items.length}
            total={query.data.total ?? query.data.items.length}
            noun="set"
            onMore={more}
            busy={query.isFetching}
          />
        </>
      ) : view === 'trash' ? (
        <EmptyState
          icon={<Trash2 className="size-6" />}
          title="Trash is empty"
          description="Deleted sets land here and can be restored."
        />
      ) : q ? (
        <EmptyState
          icon={<Search className="size-6" />}
          title="No sets match"
          description={`Nothing matches “${q}”.`}
          action={
            <Button variant="outline" size="sm" onClick={() => setQ('')}>
              Clear search
            </Button>
          }
        />
      ) : (
        <EmptyState
          icon={<Layers className="size-6" />}
          title="No eval sets yet"
          description="A set is a named collection of cases you re-run over time. Start with one narrow question you actually care about — “does my guardrail block this?” beats “is this model good?”."
          action={
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus />
              Create your first set
            </Button>
          }
        />
      )}

      <SetDialog open={creating} onOpenChange={setCreating} />
    </>
  )
}

function SetCard({ set, trashed }: { set: EvalSet; trashed: boolean }) {
  const remove = useDeleteSet()
  const restore = useRestoreSet()
  const [confirmPurge, setConfirmPurge] = React.useState(false)

  const body = (
    <>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="truncate">{set.name}</CardTitle>
          <Badge variant="outline" className="tabular shrink-0">
            {set.case_count} {pluralize(set.case_count, 'case')}
          </Badge>
        </div>
        {set.description ? (
          <CardDescription className="line-clamp-2">{set.description}</CardDescription>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-1.5">
        {set.tags.map((tag) => (
          <Badge key={tag} variant="default">
            {tag}
          </Badge>
        ))}
        <span className="ml-auto text-[11px] text-[var(--muted-foreground)]">
          {formatRelative(set.updated_at)}
        </span>
      </CardContent>
    </>
  )

  if (trashed) {
    return (
      <Card className="opacity-70">
        {body}
        <CardContent className="flex gap-2 pt-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              restore.mutate(set.id, { onSuccess: () => toast.success(`Restored “${set.name}”`) })
            }
          >
            <RotateCcw />
            Restore
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-[var(--destructive)]"
            onClick={() => setConfirmPurge(true)}
          >
            Delete permanently
          </Button>
        </CardContent>
        {/*
          Cases outlive their sets — they are shared entities, so purging a set
          removes the grouping and leaves the cases in the library. Saying that
          is the difference between a confident click and a panicked one.
        */}
        <ConfirmDialog
          open={confirmPurge}
          onOpenChange={setConfirmPurge}
          title={`Delete “${set.name}” permanently?`}
          impact={[
            'The set and its ordering are gone for good.',
            set.case_count > 0
              ? `Its ${set.case_count} ${pluralize(set.case_count, 'case')} are kept — cases belong to the library, not to one set.`
              : null,
            'Runs that used this set keep their frozen copies and stay readable.',
          ]}
          busy={remove.isPending}
          onConfirm={() =>
            remove.mutate(
              { id: set.id, purge: true },
              {
                onSuccess: () => {
                  toast.success(`Purged “${set.name}”`)
                  setConfirmPurge(false)
                },
                onError: (error) => toast.error(error.message),
              },
            )
          }
        />
      </Card>
    )
  }

  return (
    <Link to={`/sets/${set.id}`} className="group">
      <Card className="h-full transition-colors group-hover:border-[var(--primary)]/50">
        {body}
      </Card>
    </Link>
  )
}

/**
 * Create or edit a set, including its **default scoring**.
 *
 * The default config is what a case with no scorers of its own inherits, and
 * it was readable on the set page and settable only through the API. So a set
 * whose default was wrong could be diagnosed and not fixed.
 */
export function SetDialog({
  open,
  onOpenChange,
  editing,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  editing?: EvalSet | null
}) {
  const create = useCreateSet()
  const update = useUpdateSet()
  const [name, setName] = React.useState('')
  const [description, setDescription] = React.useState('')
  const [tags, setTags] = React.useState<string[]>([])
  const [scoring, setScoring] = React.useState<ScorerSpec[]>([])

  React.useEffect(() => {
    if (open) {
      setName(editing?.name ?? '')
      setDescription(editing?.description ?? '')
      setTags(editing?.tags ?? [])
      setScoring(editing?.default_scoring ?? [])
    }
  }, [open, editing])

  const pending = create.isPending || update.isPending

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const body = {
      name: name.trim(),
      description: description.trim() || null,
      tags,
      default_scoring: scoring,
    }
    const done = {
      onSuccess: (set: EvalSet) => {
        toast.success(`${editing ? 'Updated' : 'Created'} “${set.name}”`)
        onOpenChange(false)
      },
      onError: (error: Error) => toast.error(error.message),
    }
    if (editing) update.mutate({ id: editing.id, ...body }, done)
    else create.mutate(body, done)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{editing ? `Edit “${editing.name}”` : 'New eval set'}</DialogTitle>
            <DialogDescription>
              Name it after the question it answers, not the model it tests.
            </DialogDescription>
          </DialogHeader>

          <Field label="Name" htmlFor="set-name">
            <Input
              id="set-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Guardrail regression"
              autoFocus
              required
            />
          </Field>

          <Field label="Description" htmlFor="set-description">
            <Textarea
              id="set-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this set is for and what a regression here means."
              rows={3}
              className="font-sans text-sm"
            />
          </Field>

          <Field label="Tags">
            <TagInput value={tags} onChange={setTags} />
          </Field>

          <Field
            label="Default scoring"
            hint="Cases with no scorers of their own inherit this. Changing it affects future runs; runs already recorded keep the config they froze."
          >
            <ScoringBuilder
              value={scoring}
              onChange={setScoring}
              emptyHint="No default — a case with no scorers of its own comes back unscored."
            />
          </Field>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || pending}>
              {pending ? 'Saving…' : editing ? 'Save changes' : 'Create set'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
