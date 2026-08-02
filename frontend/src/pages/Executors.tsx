import { Copy, Cpu, KeyRound, Pencil, Plug, Plus, Trash2, Zap } from 'lucide-react'
import * as React from 'react'
import { toast } from 'sonner'

import {
  useDeleteExecutor,
  useDeleteHarnessProfile,
  useDeleteModelProfile,
  useExecutors,
  useHarnessProfiles,
  useModelProfiles,
  useSaveExecutor,
  useSaveHarnessProfile,
  useSaveModelProfile,
  useTestModelProfile,
} from '@/api/runs'
import type {
  Executor,
  HarnessKind,
  HarnessProfile,
  ModelProfile,
  Provider,
  TestConnectionResult,
} from '@/api/types'
import { GenerationParams, ParamsSummary } from '@/components/GenerationParams'
import { PageHeader } from '@/components/layout/AppShell'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Tooltip } from '@/components/ui/misc'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatCost, formatDurationMs } from '@/lib/format'

const PROVIDERS: Provider[] = ['fake', 'anthropic', 'openai', 'gemini', 'openai_compatible']
const HARNESS_KINDS: HarnessKind[] = ['fake', 'direct', 'cli']

export default function ExecutorsPage() {
  const [tab, setTab] = React.useState('executors')
  return (
    <>
      <PageHeader
        title="Executors"
        description="An executor is a model profile paired with a harness. Every run, result and comparison binds to one."
      />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="executors">Executors</TabsTrigger>
          <TabsTrigger value="models">Model profiles</TabsTrigger>
          <TabsTrigger value="harnesses">Harnesses</TabsTrigger>
        </TabsList>
        <TabsContent value="executors">
          <ExecutorTab />
        </TabsContent>
        <TabsContent value="models">
          <ModelTab />
        </TabsContent>
        <TabsContent value="harnesses">
          <HarnessTab />
        </TabsContent>
      </Tabs>
    </>
  )
}

// -- executors -----------------------------------------------------------------

function ExecutorTab() {
  const query = useExecutors(true)
  const models = useModelProfiles()
  const harnesses = useHarnessProfiles()
  const remove = useDeleteExecutor()
  const [editing, setEditing] = React.useState<Executor | 'new' | null>(null)

  if (query.isLoading) return <LoadingState label="Loading executors…" />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />

  const rows = query.data?.items ?? []
  const canCreate = (models.data?.items.length ?? 0) > 0 && (harnesses.data?.items.length ?? 0) > 0

  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        <Button size="sm" onClick={() => setEditing('new')} disabled={!canCreate}>
          <Plus />
          New executor
        </Button>
      </div>

      {rows.length === 0 ? (
        <EmptyState
          icon={<Cpu className="size-6" />}
          title="No executors yet"
          description={
            canCreate
              ? 'Pair a model profile with a harness to get something you can run.'
              : 'Create a model profile and a harness first — an executor is the pairing of the two.'
          }
          action={
            canCreate ? (
              <Button size="sm" onClick={() => setEditing('new')}>
                <Plus />
                New executor
              </Button>
            ) : null
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Display key</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Harness</TableHead>
                <TableHead className="w-24">Runs</TableHead>
                <TableHead className="w-24 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((executor) => (
                <TableRow key={executor.id} className={executor.archived ? 'opacity-50' : ''}>
                  <TableCell className="font-medium">
                    <span className="flex items-center gap-2">
                      {executor.name}
                      {executor.archived ? <Badge>archived</Badge> : null}
                    </span>
                  </TableCell>
                  <TableCell className="text-xs text-[var(--muted-foreground)]">
                    <div>
                      {executor.model_name}
                      <span className="ml-1.5 font-mono">{executor.model_id}</span>
                    </div>
                    {/* Two executors can share a model and differ only here. */}
                    <ParamsSummary params={executor.overrides} />
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{executor.harness_kind}</Badge>
                  </TableCell>
                  <TableCell className="tabular text-xs">{executor.run_count}</TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => setEditing(executor)}
                        aria-label={`Edit ${executor.name}`}
                      >
                        <Pencil />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        title="Start a copy — the usual way to make “same model, different effort”."
                        onClick={() =>
                          setEditing({ ...executor, id: 0, name: `${executor.name} (copy)` })
                        }
                        aria-label={`Duplicate ${executor.name}`}
                      >
                        <Copy />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() =>
                          remove.mutate(executor.id, {
                            onSuccess: (r) => toast.success(r.message ?? 'Removed'),
                            onError: (e) => toast.error(e.message),
                          })
                        }
                        aria-label={`Remove ${executor.name}`}
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <ExecutorDialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        models={models.data?.items ?? []}
        harnesses={harnesses.data?.items ?? []}
        editing={editing}
      />
    </div>
  )
}

function ExecutorDialog({
  open,
  onOpenChange,
  models,
  harnesses,
  editing,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  models: ModelProfile[]
  harnesses: HarnessProfile[]
  editing: Executor | 'new' | null
}) {
  const save = useSaveExecutor()
  // Prefill and identity are separate: "duplicate" hands over a full executor
  // with `id: 0`, which must create rather than PATCH /executors/0.
  const prefill = editing !== 'new' && editing !== null ? editing : null
  const existing = prefill && prefill.id > 0 ? prefill : null
  const [modelId, setModelId] = React.useState('')
  const [harnessId, setHarnessId] = React.useState('')
  const [name, setName] = React.useState('')
  const [overrides, setOverrides] = React.useState<Record<string, unknown>>({})

  React.useEffect(() => {
    if (!open) return
    setModelId(String(prefill?.model_profile_id ?? models[0]?.id ?? ''))
    setHarnessId(String(prefill?.harness_profile_id ?? harnesses[0]?.id ?? ''))
    setName(prefill?.name ?? '')
    setOverrides(prefill?.overrides ?? {})
  }, [open, models, harnesses, prefill])

  const model = models.find((m) => String(m.id) === modelId)
  const harness = harnesses.find((h) => String(h.id) === harnessId)
  const suggested = model && harness ? `${model.name} @ ${harness.name}` : ''

  function submit(event: React.FormEvent) {
    event.preventDefault()
    save.mutate(
      {
        ...(existing ? { id: existing.id } : {}),
        model_profile_id: Number(modelId),
        harness_profile_id: Number(harnessId),
        overrides,
        ...(name.trim() ? { name: name.trim() } : {}),
      },
      {
        onSuccess: (executor) => {
          toast.success(`${existing ? 'Updated' : 'Created'} ${executor.name}`)
          onOpenChange(false)
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>
              {existing ? `Edit ${existing.name}` : prefill ? 'Duplicate executor' : 'New executor'}
            </DialogTitle>
            <DialogDescription>
              Model × harness. The display key is what shows up in every result table.
            </DialogDescription>
          </DialogHeader>

          <Field label="Model profile">
            <Select value={modelId} onValueChange={setModelId}>
              <SelectTrigger aria-label="Model profile">
                <SelectValue placeholder="Choose a model" />
              </SelectTrigger>
              <SelectContent>
                {models.map((m) => (
                  <SelectItem key={m.id} value={String(m.id)}>
                    {m.name} ({m.provider})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field label="Harness">
            <Select value={harnessId} onValueChange={setHarnessId}>
              <SelectTrigger aria-label="Harness">
                <SelectValue placeholder="Choose a harness" />
              </SelectTrigger>
              <SelectContent>
                {harnesses.map((h) => (
                  <SelectItem key={h.id} value={String(h.id)}>
                    {h.name} ({h.kind})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field label="Display key" hint={suggested ? `Defaults to “${suggested}”` : undefined}>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={suggested} />
          </Field>

          {model ? (
            <GenerationParams
              provider={model.provider}
              modelId={model.model_id}
              value={overrides}
              onChange={setOverrides}
              idPrefix="ex"
              label="Overrides"
              hint={
                <>
                  Applied on top of {model.name}’s own params. Two executors on the same model with
                  different effort is a comparison worth running — give them distinct display keys.
                </>
              }
            />
          ) : null}

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!modelId || !harnessId || save.isPending}>
              {save.isPending ? 'Saving…' : existing ? 'Save changes' : 'Create executor'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// -- model profiles ------------------------------------------------------------

function ModelTab() {
  const query = useModelProfiles(true)
  const remove = useDeleteModelProfile()
  const test = useTestModelProfile()
  const [editing, setEditing] = React.useState<ModelProfile | 'new' | null>(null)
  const [results, setResults] = React.useState<Record<number, TestConnectionResult>>({})

  if (query.isLoading) return <LoadingState label="Loading model profiles…" />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />

  const rows = query.data?.items ?? []

  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        <Button size="sm" onClick={() => setEditing('new')}>
          <Plus />
          New model profile
        </Button>
      </div>

      {rows.length === 0 ? (
        <EmptyState
          icon={<Zap className="size-6" />}
          title="No model profiles"
          description="Start with a `fake` profile — it runs the built-in deterministic simulator, costs nothing, and needs no API key."
          action={
            <Button size="sm" onClick={() => setEditing('new')}>
              <Plus />
              New model profile
            </Button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead className="w-36">Provider</TableHead>
                <TableHead>Model id</TableHead>
                <TableHead className="w-24">Key</TableHead>
                <TableHead>Connection</TableHead>
                <TableHead className="w-32 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((profile) => {
                const result = results[profile.id]
                return (
                  <TableRow key={profile.id} className={profile.archived ? 'opacity-50' : ''}>
                    <TableCell className="font-medium">{profile.name}</TableCell>
                    <TableCell>
                      <Badge variant={profile.provider === 'fake' ? 'default' : 'outline'}>
                        {profile.provider}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{profile.model_id || '—'}</TableCell>
                    <TableCell>
                      {profile.provider === 'fake' ? (
                        <span className="text-xs text-[var(--muted-foreground)]">n/a</span>
                      ) : profile.key_present ? (
                        <Tooltip
                          label={`Read from ${profile.api_key_env ?? 'the default env var'}`}
                        >
                          <Badge variant="pass" className="gap-1">
                            <KeyRound className="size-3" />
                            set
                          </Badge>
                        </Tooltip>
                      ) : (
                        <Badge variant="error">missing</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-xs">
                      {result ? (
                        result.ok ? (
                          <span className="text-[var(--pass)]">
                            ok · {formatDurationMs(result.latency_ms)} ·{' '}
                            {formatCost(result.cost_usd)}
                          </span>
                        ) : (
                          <span className="text-[var(--destructive)]">{result.message}</span>
                        )
                      ) : (
                        <span className="text-[var(--muted-foreground)]">not tested</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        <Tooltip
                          label={
                            profile.provider === 'fake'
                              ? 'Simulated — free.'
                              : 'Sends one tiny real request. This costs money.'
                          }
                        >
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={test.isPending}
                            onClick={() =>
                              test.mutate(profile.id, {
                                onSuccess: (r) => setResults((p) => ({ ...p, [profile.id]: r })),
                                onError: (e) => toast.error(e.message),
                              })
                            }
                          >
                            <Plug />
                            Test
                          </Button>
                        </Tooltip>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => setEditing(profile)}
                          aria-label={`Edit ${profile.name}`}
                        >
                          <Pencil />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() =>
                            remove.mutate(profile.id, {
                              onSuccess: (r) => toast.success(r.message ?? 'Removed'),
                              onError: (e) => toast.error(e.message),
                            })
                          }
                          aria-label={`Remove ${profile.name}`}
                        >
                          <Trash2 />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <ModelDialog
        open={editing !== null}
        onOpenChange={(o) => !o && setEditing(null)}
        editing={editing}
      />
    </div>
  )
}

/**
 * Create *or* edit a model profile.
 *
 * The PATCH endpoint always existed; nothing in the UI reached it, so a typo in
 * a base URL or an API key variable could only be fixed by deleting the profile
 * and rebuilding every executor that referenced it. Editing never rewrites
 * history: runs carry a frozen snapshot of the config they used.
 */
function ModelDialog({
  open,
  onOpenChange,
  editing,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  editing: ModelProfile | 'new' | null
}) {
  const save = useSaveModelProfile()
  const existing = editing !== 'new' && editing !== null ? editing : null
  const [name, setName] = React.useState('')
  const [provider, setProvider] = React.useState<Provider>('fake')
  const [modelId, setModelId] = React.useState('')
  const [baseUrl, setBaseUrl] = React.useState('')
  const [apiKeyEnv, setApiKeyEnv] = React.useState('')
  const [params, setParams] = React.useState<Record<string, unknown>>({})

  React.useEffect(() => {
    if (!open) return
    setName(existing?.name ?? '')
    setProvider(existing?.provider ?? 'fake')
    setModelId(existing?.model_id ?? '')
    setBaseUrl(existing?.base_url ?? '')
    setApiKeyEnv(existing?.api_key_env ?? '')
    setParams(existing?.params ?? {})
  }, [open, existing])

  function submit(event: React.FormEvent) {
    event.preventDefault()
    save.mutate(
      {
        ...(existing ? { id: existing.id } : {}),
        name: name.trim(),
        provider,
        model_id: modelId.trim(),
        base_url: baseUrl.trim() || null,
        api_key_env: apiKeyEnv.trim() || null,
        params,
      },
      {
        onSuccess: () => {
          toast.success(existing ? 'Model profile updated' : 'Model profile created')
          onOpenChange(false)
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form
          onSubmit={submit}
          className="scroll-gutter flex max-h-[75vh] flex-col gap-4 overflow-y-auto"
        >
          <DialogHeader>
            <DialogTitle>{existing ? `Edit ${existing.name}` : 'New model profile'}</DialogTitle>
            <DialogDescription>
              Keys come from the environment only — Gaugix stores the variable name, never the
              value.
            </DialogDescription>
          </DialogHeader>

          <Field label="Name" htmlFor="mp-name">
            <Input
              id="mp-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="haiku"
              autoFocus
              required
            />
          </Field>

          <Field label="Provider">
            <Select value={provider} onValueChange={(v) => setProvider(v as Provider)}>
              <SelectTrigger aria-label="Provider">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PROVIDERS.map((p) => (
                  <SelectItem key={p} value={p}>
                    {p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field
            label="Model id"
            hint={provider === 'fake' ? 'Optional for the fake provider.' : undefined}
            htmlFor="mp-model-id"
          >
            <Input
              id="mp-model-id"
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
              placeholder="provider/model-id"
              className="font-mono text-xs"
            />
          </Field>

          {provider === 'openai_compatible' ? (
            <Field label="Base URL" htmlFor="mp-base-url">
              <Input
                id="mp-base-url"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://openrouter.ai/api/v1"
                className="font-mono text-xs"
              />
            </Field>
          ) : null}

          {provider !== 'fake' ? (
            <Field
              label="API key env var"
              hint="Leave blank to use the provider default (e.g. ANTHROPIC_API_KEY)."
              htmlFor="mp-key-env"
            >
              <Input
                id="mp-key-env"
                value={apiKeyEnv}
                onChange={(e) => setApiKeyEnv(e.target.value)}
                placeholder="OPENROUTER_API_KEY"
                className="font-mono text-xs"
              />
            </Field>
          ) : null}

          <GenerationParams
            provider={provider}
            modelId={modelId.trim()}
            value={params}
            onChange={setParams}
            idPrefix="mp"
            hint="Defaults for every executor built on this profile. An executor can override them."
          />

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || save.isPending}>
              {save.isPending ? 'Saving…' : existing ? 'Save changes' : 'Create'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// -- harnesses -----------------------------------------------------------------

const FAKE_PRESET = JSON.stringify(
  {
    mode: 'script',
    script: [{ match: 'napalm', response: '{"action": "block"}' }],
    default_response: '{"action": "allow"}',
  },
  null,
  2,
)

function HarnessTab() {
  const query = useHarnessProfiles(true)
  const remove = useDeleteHarnessProfile()
  const [editing, setEditing] = React.useState<HarnessProfile | 'new' | null>(null)

  if (query.isLoading) return <LoadingState label="Loading harnesses…" />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />

  const rows = query.data?.items ?? []

  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        <Button size="sm" onClick={() => setEditing('new')}>
          <Plus />
          New harness
        </Button>
      </div>

      {rows.length === 0 ? (
        <EmptyState
          icon={<Plug className="size-6" />}
          title="No harnesses"
          description="A harness is how a model gets called: `direct` for a plain API call, `fake` for the deterministic simulator, `cli` for a command-line agent."
          action={
            <Button size="sm" onClick={() => setEditing('new')}>
              <Plus />
              New harness
            </Button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead className="w-24">Kind</TableHead>
                <TableHead>Config</TableHead>
                <TableHead className="w-16 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((harness) => (
                <TableRow key={harness.id} className={harness.archived ? 'opacity-50' : ''}>
                  <TableCell className="font-medium">{harness.name}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{harness.kind}</Badge>
                  </TableCell>
                  <TableCell>
                    <code className="line-clamp-1 font-mono text-[11px] text-[var(--muted-foreground)]">
                      {JSON.stringify(harness.config)}
                    </code>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => setEditing(harness)}
                        aria-label={`Edit ${harness.name}`}
                      >
                        <Pencil />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() =>
                          remove.mutate(harness.id, {
                            onSuccess: (r) => toast.success(r.message ?? 'Removed'),
                            onError: (e) => toast.error(e.message),
                          })
                        }
                        aria-label={`Remove ${harness.name}`}
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <HarnessDialog
        open={editing !== null}
        onOpenChange={(o) => !o && setEditing(null)}
        editing={editing}
      />
    </div>
  )
}

function HarnessDialog({
  open,
  onOpenChange,
  editing,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  editing: HarnessProfile | 'new' | null
}) {
  const save = useSaveHarnessProfile()
  const existing = editing !== 'new' && editing !== null ? editing : null
  const [name, setName] = React.useState('')
  const [kind, setKind] = React.useState<HarnessKind>('fake')
  const [config, setConfig] = React.useState('{}')
  const [configError, setConfigError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!open) return
    setName(existing?.name ?? '')
    setKind(existing?.kind ?? 'fake')
    setConfig(JSON.stringify(existing?.config ?? {}, null, 2))
    setConfigError(null)
  }, [open, existing])

  function submit(event: React.FormEvent) {
    event.preventDefault()
    let parsed: Record<string, unknown> = {}
    try {
      parsed = JSON.parse(config || '{}')
    } catch {
      setConfigError('invalid JSON')
      return
    }
    save.mutate(
      { ...(existing ? { id: existing.id } : {}), name: name.trim(), kind, config: parsed },
      {
        onSuccess: () => {
          toast.success(existing ? 'Harness updated' : 'Harness created')
          onOpenChange(false)
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{existing ? `Edit ${existing.name}` : 'New harness'}</DialogTitle>
            <DialogDescription>
              `fake` simulates responses deterministically — ideal for building a set before
              spending anything.
            </DialogDescription>
          </DialogHeader>

          <Field label="Name" htmlFor="h-name">
            <Input
              id="h-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="direct"
              autoFocus
              required
            />
          </Field>

          <Field label="Kind">
            <Select
              value={kind}
              onValueChange={(v) => {
                setKind(v as HarnessKind)
                setConfig(
                  v === 'cli'
                    ? JSON.stringify(
                        { command_template: 'my-agent --file {prompt_file}', timeout_s: 300 },
                        null,
                        2,
                      )
                    : '{}',
                )
              }}
            >
              <SelectTrigger aria-label="Harness kind">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {HARNESS_KINDS.map((k) => (
                  <SelectItem key={k} value={k}>
                    {k}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field
            label="Config (JSON)"
            error={configError}
            hint={
              kind === 'fake' ? 'echo mode by default; script mode for canned answers.' : undefined
            }
            htmlFor="h-config"
          >
            <Textarea
              id="h-config"
              value={config}
              onChange={(e) => {
                setConfig(e.target.value)
                try {
                  JSON.parse(e.target.value || '{}')
                  setConfigError(null)
                } catch {
                  setConfigError('invalid JSON')
                }
              }}
              rows={8}
              spellCheck={false}
            />
          </Field>

          {kind === 'fake' ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="self-start"
              onClick={() => setConfig(FAKE_PRESET)}
            >
              Use a scripted example
            </Button>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || save.isPending || !!configError}>
              {save.isPending ? 'Saving…' : existing ? 'Save changes' : 'Create'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
