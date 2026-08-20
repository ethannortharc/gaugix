import {
  ExternalLink,
  FolderTree,
  Layers,
  Library,
  Plus,
  RotateCcw,
  Search,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import {
  useCollections,
  useCreateCollection,
  useCreateSet,
  useDeleteSet,
  useRestoreSet,
  useSets,
  useUpdateSet,
} from '@/api/cases'
import {
  STANDARD_EVALUATION_PROFILE,
  type EvalCollection,
  type EvalSet,
  type EvaluationProfile,
  type ScorerSpec,
} from '@/api/types'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatRelative, pluralize } from '@/lib/format'

export default function SetsPage() {
  const [q, setQ] = React.useState('')
  const [view, setView] = React.useState<'suites' | 'sets' | 'fixtures' | 'trash'>('suites')
  const [creating, setCreating] = React.useState(false)
  const [creatingSuite, setCreatingSuite] = React.useState(false)

  const { limit, more, reset } = usePagedLimit()
  const collections = useCollections()
  const query = useSets({
    q: q || undefined,
    trashed: view === 'trash',
    visibility:
      view === 'fixtures' ? ['fixture'] : view === 'sets' ? ['primary', 'hidden'] : undefined,
    limit,
  })

  React.useEffect(() => {
    reset()
  }, [q, view, reset])

  const roots = (collections.data?.items ?? []).filter(
    (collection) => collection.parent_id === null && collection.visibility === 'primary',
  )
  const visibleRoots = roots.filter((collection) => {
    const needle = q.trim().toLocaleLowerCase()
    return (
      !needle ||
      collection.name.toLocaleLowerCase().includes(needle) ||
      collection.description?.toLocaleLowerCase().includes(needle)
    )
  })

  return (
    <>
      <PageHeader
        title="Eval sets"
        description="Start with a suite, drill into logical eval sets and variants, then inspect branches and cases."
        actions={
          <div className="flex items-center gap-2">
            {view === 'suites' ? (
              <Button variant="outline" size="sm" onClick={() => setCreatingSuite(true)}>
                <FolderTree />
                New suite
              </Button>
            ) : null}
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus />
              New set
            </Button>
          </div>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative min-w-56 max-w-sm flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={view === 'suites' ? 'Search suites…' : 'Search sets…'}
            className="pl-8"
            aria-label="Search sets"
          />
        </div>
        <Tabs
          value={view}
          onValueChange={(value) => setView(value as 'suites' | 'sets' | 'fixtures' | 'trash')}
        >
          <TabsList>
            <TabsTrigger value="suites">Suites</TabsTrigger>
            <TabsTrigger value="sets">All sets</TabsTrigger>
            <TabsTrigger value="fixtures">Fixtures</TabsTrigger>
            <TabsTrigger value="trash">Trash</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {view === 'suites' ? (
        collections.isLoading ? (
          <LoadingState label="Loading suites…" />
        ) : collections.isError ? (
          <ErrorState error={collections.error} onRetry={() => void collections.refetch()} />
        ) : visibleRoots.length > 0 ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {visibleRoots.map((collection) => (
              <SuiteCard key={collection.id} collection={collection} />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<FolderTree className="size-6" />}
            title={q ? 'No suites match' : 'No evaluation suites yet'}
            description="Suites group related eval sets without changing how those sets are executed or scored."
            action={
              <Button size="sm" onClick={() => setCreatingSuite(true)}>
                <Plus />
                Create a suite
              </Button>
            }
          />
        )
      ) : query.isLoading ? (
        <LoadingState label="Loading sets…" />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data && query.data.items.length > 0 ? (
        <>
          <SetDirectory sets={query.data.items} trashed={view === 'trash'} expanded={Boolean(q)} />
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
      ) : view === 'fixtures' ? (
        <EmptyState
          icon={<Library className="size-6" />}
          title="No compatibility fixtures"
          description="Stub-dependent and legacy sets appear here when installed."
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
      <SuiteDialog open={creatingSuite} onOpenChange={setCreatingSuite} />
    </>
  )
}

function sourceUrl(collection: EvalCollection): string | null {
  const source = collection.provenance.source_url ?? collection.provenance.url
  return typeof source === 'string' ? source : null
}

function SuiteCard({ collection }: { collection: EvalCollection }) {
  const source = sourceUrl(collection)
  return (
    <Link to={`/collections/${collection.id}`} className="group">
      <Card className="h-full transition-colors group-hover:border-[var(--primary)]/50">
        <CardHeader className="pb-2">
          <div className="flex items-start gap-3">
            <span className="rounded-md bg-[var(--primary)]/10 p-2 text-[var(--primary)]">
              <FolderTree className="size-4" />
            </span>
            <div className="min-w-0 flex-1">
              <CardTitle className="text-base">{collection.name}</CardTitle>
              <CardDescription className="mt-1 line-clamp-3 leading-relaxed">
                {collection.description || 'No suite description yet.'}
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{collection.descendant_set_count} sets</Badge>
          <Badge variant="outline">{collection.descendant_case_count} cases</Badge>
          {source ? (
            <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-[var(--primary)]">
              Source <ExternalLink className="size-3" />
            </span>
          ) : null}
        </CardContent>
      </Card>
    </Link>
  )
}

function SetDirectory({
  sets,
  trashed,
  expanded,
}: {
  sets: EvalSet[]
  trashed: boolean
  expanded: boolean
}) {
  const groups = new Map<string, EvalSet[]>()
  for (const set of sets) {
    const key = set.collection_path.join(' / ') || 'Unfiled sets'
    groups.set(key, [...(groups.get(key) ?? []), set])
  }
  return (
    <div className="flex flex-col gap-2">
      {[...groups.entries()].map(([path, rows]) => (
        <details
          key={path}
          open={expanded || groups.size === 1}
          className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]"
        >
          <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-sm font-medium hover:bg-[var(--muted)]/60">
            <FolderTree className="size-4 text-[var(--muted-foreground)]" />
            <span className="min-w-0 flex-1 truncate">{path}</span>
            <Badge variant="outline">{rows.length} sets</Badge>
            <Badge variant="outline">
              {rows.reduce((total, set) => total + set.case_count, 0)} cases
            </Badge>
          </summary>
          <div className="grid gap-3 border-t border-[var(--border)] p-3 sm:grid-cols-2 xl:grid-cols-3">
            {rows.map((set) => (
              <SetCard key={set.id} set={set} trashed={trashed} />
            ))}
          </div>
        </details>
      ))}
    </div>
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
        {set.variant ? <Badge variant="primary">{set.variant}</Badge> : null}
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

function SuiteDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const create = useCreateCollection()
  const [name, setName] = React.useState('')
  const [key, setKey] = React.useState('')
  const [description, setDescription] = React.useState('')
  const [source, setSource] = React.useState('')

  React.useEffect(() => {
    if (!open) return
    setName('')
    setKey('')
    setDescription('')
    setSource('')
  }, [open])

  function submit(event: React.FormEvent) {
    event.preventDefault()
    create.mutate(
      {
        key: key.trim(),
        name: name.trim(),
        description: description.trim() || null,
        visibility: 'primary',
        provenance: source.trim() ? { source_url: source.trim() } : {},
      },
      {
        onSuccess: (suite) => {
          toast.success(`Created “${suite.name}”`)
          onOpenChange(false)
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent widthClass="max-w-xl">
        <form onSubmit={submit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>New evaluation suite</DialogTitle>
            <DialogDescription>
              A suite organises related sets. Each set keeps its own scoring and metric contract.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name" htmlFor="suite-name">
              <Input
                id="suite-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Retrieval quality"
                required
                autoFocus
              />
            </Field>
            <Field
              label="Stable key"
              htmlFor="suite-key"
              hint="Letters, numbers, dots, colons, underscores, or dashes. Importers reconcile by this key."
            >
              <Input
                id="suite-key"
                value={key}
                onChange={(event) => setKey(event.target.value)}
                placeholder="retrieval-quality"
                pattern="[A-Za-z0-9][A-Za-z0-9._:-]*"
                required
              />
            </Field>
          </div>
          <Field label="Description" htmlFor="suite-description">
            <Textarea
              id="suite-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="What belongs here, and what decisions this suite supports."
              rows={3}
              className="font-sans text-sm"
            />
          </Field>
          <Field label="Official or source URL" htmlFor="suite-source">
            <Input
              id="suite-source"
              type="url"
              value={source}
              onChange={(event) => setSource(event.target.value)}
              placeholder="https://…"
            />
          </Field>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || !key.trim() || create.isPending}>
              {create.isPending ? 'Creating…' : 'Create suite'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
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
  const collections = useCollections()
  const [name, setName] = React.useState('')
  const [description, setDescription] = React.useState('')
  const [collectionId, setCollectionId] = React.useState<number | null>(null)
  const [logicalKey, setLogicalKey] = React.useState('')
  const [variant, setVariant] = React.useState('')
  const [visibility, setVisibility] = React.useState<'primary' | 'fixture' | 'hidden'>('primary')
  const [tags, setTags] = React.useState<string[]>([])
  const [scoring, setScoring] = React.useState<ScorerSpec[]>([])
  const [profile, setProfile] = React.useState<EvaluationProfile>(standardProfile())

  React.useEffect(() => {
    if (open) {
      setName(editing?.name ?? '')
      setDescription(editing?.description ?? '')
      setCollectionId(editing?.collection_id ?? null)
      setLogicalKey(editing?.logical_key ?? '')
      setVariant(editing?.variant ?? '')
      setVisibility(editing?.visibility ?? 'primary')
      setTags(editing?.tags ?? [])
      setScoring(editing?.default_scoring ?? [])
      setProfile(editing?.evaluation_profile ?? standardProfile())
    }
  }, [open, editing])

  const pending = create.isPending || update.isPending

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const body = {
      name: name.trim(),
      description: description.trim() || null,
      collection_id: collectionId,
      logical_key: logicalKey.trim() || null,
      variant: variant.trim() || null,
      visibility,
      tags,
      default_scoring: scoring,
      evaluation_profile: profile,
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
      <DialogContent widthClass="max-w-2xl">
        <form
          onSubmit={submit}
          className="scroll-gutter flex min-h-0 flex-col gap-4 overflow-y-auto pr-1"
        >
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

          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label="Suite / folder"
              htmlFor="set-collection"
              hint="Organisation only; it does not change scoring or execution."
            >
              <Select
                value={collectionId === null ? '__none__' : String(collectionId)}
                onValueChange={(value) =>
                  setCollectionId(value === '__none__' ? null : Number(value))
                }
              >
                <SelectTrigger id="set-collection">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">Unfiled</SelectItem>
                  {(collections.data?.items ?? []).map((collection) => (
                    <SelectItem key={collection.id} value={String(collection.id)}>
                      {'· '.repeat(collection.depth)}
                      {collection.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Library visibility" htmlFor="set-visibility">
              <Select
                value={visibility}
                onValueChange={(value) => setVisibility(value as 'primary' | 'fixture' | 'hidden')}
              >
                <SelectTrigger id="set-visibility">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="primary">Primary</SelectItem>
                  <SelectItem value="fixture">Fixture / compatibility</SelectItem>
                  <SelectItem value="hidden">Hidden</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label="Logical set key"
              htmlFor="set-logical-key"
              hint="Variants with the same key are grouped together in a suite."
            >
              <Input
                id="set-logical-key"
                value={logicalKey}
                onChange={(event) => setLogicalKey(event.target.value)}
                placeholder="translation-quality"
              />
            </Field>
            <Field
              label="Variant"
              htmlFor="set-variant"
              hint="For example: input, output, zh, or v2."
            >
              <Input
                id="set-variant"
                value={variant}
                onChange={(event) => setVariant(event.target.value)}
                placeholder="input"
              />
            </Field>
          </div>

          <Field label="Tags">
            <TagInput value={tags} onChange={setTags} />
          </Field>

          <Field
            label="Evaluation metrics"
            hint="This describes how labels and predictions become aggregate metrics. It is optional and independent of the executor or harness."
          >
            <EvaluationProfileEditor value={profile} onChange={setProfile} />
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

function standardProfile(): EvaluationProfile {
  return {
    ...STANDARD_EVALUATION_PROFILE,
    positive_values: [...STANDARD_EVALUATION_PROFILE.positive_values],
    negative_values: [...STANDARD_EVALUATION_PROFILE.negative_values],
  }
}

function binaryProfile(): EvaluationProfile {
  return {
    ...standardProfile(),
    kind: 'binary_classification',
    name: 'Binary classification',
    description: 'Precision, recall, F1, false-positive rate and optional calibration.',
    truth: { source: 'tag', key: 'label' },
    prediction: { source: 'output_json', key: 'label' },
    score: { source: 'output_json', key: 'score' },
  }
}

function guardrailProfile(): EvaluationProfile {
  return {
    ...binaryProfile(),
    name: 'Guardrail detection',
    description: 'Detect unsafe inputs while measuring over-refusal on benign inputs.',
    truth: { source: 'tag', key: 'label' },
    prediction: { source: 'output_json', key: 'verdict' },
    score: { source: 'output_json', key: 'unsafe_score' },
    category_truth: { source: 'tag', key: 'category' },
    category_prediction: { source: 'output_json', key: 'category' },
    positive_values: ['unsafe', 'blocked'],
    negative_values: ['safe', 'allowed'],
    positive_label: 'blocked',
    negative_label: 'allowed',
    false_positive_label: 'Over-refusal rate',
  }
}

function csv(value: string[]): string {
  return value.join(', ')
}

function fromCsv(value: string): string[] {
  return value
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
}

function EvaluationProfileEditor({
  value,
  onChange,
}: {
  value: EvaluationProfile
  onChange: (value: EvaluationProfile) => void
}) {
  const binary = value.kind === 'binary_classification'
  return (
    <div className="flex flex-col gap-3 rounded-md border border-[var(--border)] p-3">
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Metric profile" htmlFor="set-profile-kind">
          <Select
            value={value.kind}
            onValueChange={(kind) =>
              onChange(kind === 'binary_classification' ? binaryProfile() : standardProfile())
            }
          >
            <SelectTrigger id="set-profile-kind" className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="standard">Standard scoring</SelectItem>
              <SelectItem value="binary_classification">Binary classification</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onChange(guardrailProfile())}
        >
          <ShieldCheck />
          Guardrail preset
        </Button>
      </div>
      <p className="text-xs text-[var(--muted-foreground)]">
        {binary
          ? 'Generic classification contract. The Guardrail button only fills these same fields.'
          : 'Uses scorer verdicts, pass rate, execution errors and latency. Best for open-ended generation and rubric-based evals.'}
      </p>
      {binary ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Profile name" htmlFor="profile-name">
            <Input
              id="profile-name"
              value={value.name}
              onChange={(event) => onChange({ ...value, name: event.target.value })}
            />
          </Field>
          <Field label="Truth source" htmlFor="profile-truth-key">
            <div className="flex gap-2">
              <Select
                value={value.truth?.source === 'reference' ? 'reference' : 'tag'}
                onValueChange={(source) =>
                  onChange({
                    ...value,
                    truth:
                      source === 'reference'
                        ? { source: 'reference', key: null }
                        : { source: 'tag', key: value.truth?.key || 'label' },
                  })
                }
              >
                <SelectTrigger className="w-28" aria-label="Truth source">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="tag">Case tag</SelectItem>
                  <SelectItem value="reference">Reference</SelectItem>
                </SelectContent>
              </Select>
              <Input
                id="profile-truth-key"
                value={value.truth?.source === 'tag' ? (value.truth.key ?? '') : ''}
                placeholder={value.truth?.source === 'reference' ? 'uses reference' : 'label'}
                disabled={value.truth?.source === 'reference'}
                onChange={(event) =>
                  onChange({
                    ...value,
                    truth: { source: 'tag', key: event.target.value || null },
                  })
                }
              />
            </div>
          </Field>
          <Field label="Prediction JSON path" htmlFor="profile-prediction-key">
            <Input
              id="profile-prediction-key"
              value={value.prediction?.key ?? ''}
              placeholder="label"
              onChange={(event) =>
                onChange({
                  ...value,
                  prediction: { source: 'output_json', key: event.target.value || null },
                })
              }
            />
          </Field>
          <Field label="Score JSON path (optional)" htmlFor="profile-score-key">
            <div className="flex gap-2">
              <Input
                id="profile-score-key"
                value={value.score?.key ?? ''}
                placeholder="score"
                onChange={(event) =>
                  onChange({
                    ...value,
                    score: event.target.value
                      ? { source: 'output_json', key: event.target.value }
                      : null,
                  })
                }
              />
              <Select
                value={value.score_scale}
                onValueChange={(score_scale) =>
                  onChange({ ...value, score_scale: score_scale as '0-1' | '0-100' })
                }
              >
                <SelectTrigger className="w-24" aria-label="Score scale">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="0-1">0–1</SelectItem>
                  <SelectItem value="0-100">0–100</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </Field>
          <Field label="Positive values" htmlFor="profile-positive-values">
            <Input
              id="profile-positive-values"
              value={csv(value.positive_values)}
              onChange={(event) =>
                onChange({ ...value, positive_values: fromCsv(event.target.value) })
              }
            />
          </Field>
          <Field label="Negative values" htmlFor="profile-negative-values">
            <Input
              id="profile-negative-values"
              value={csv(value.negative_values)}
              onChange={(event) =>
                onChange({ ...value, negative_values: fromCsv(event.target.value) })
              }
            />
          </Field>
          <Field label="Positive label" htmlFor="profile-positive-label">
            <Input
              id="profile-positive-label"
              value={value.positive_label}
              onChange={(event) => onChange({ ...value, positive_label: event.target.value })}
            />
          </Field>
          <Field label="Negative label" htmlFor="profile-negative-label">
            <Input
              id="profile-negative-label"
              value={value.negative_label}
              onChange={(event) => onChange({ ...value, negative_label: event.target.value })}
            />
          </Field>
          <Field label="False-positive metric label" htmlFor="profile-fp-label">
            <Input
              id="profile-fp-label"
              value={value.false_positive_label}
              onChange={(event) => onChange({ ...value, false_positive_label: event.target.value })}
            />
          </Field>
          <Field label="Category truth tag (optional)" htmlFor="profile-category-truth">
            <Input
              id="profile-category-truth"
              value={value.category_truth?.key ?? ''}
              placeholder="category"
              onChange={(event) =>
                onChange({
                  ...value,
                  category_truth: event.target.value
                    ? { source: 'tag', key: event.target.value }
                    : null,
                })
              }
            />
          </Field>
          <Field
            label="Category prediction JSON path (optional)"
            htmlFor="profile-category-prediction"
          >
            <Input
              id="profile-category-prediction"
              value={value.category_prediction?.key ?? ''}
              placeholder="category"
              onChange={(event) =>
                onChange({
                  ...value,
                  category_prediction: event.target.value
                    ? { source: 'output_json', key: event.target.value }
                    : null,
                })
              }
            />
          </Field>
        </div>
      ) : null}
    </div>
  )
}
