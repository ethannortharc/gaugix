import {
  ArrowRight,
  Bot,
  Check,
  Eraser,
  FilePlus2,
  MessageSquareText,
  Play,
  Send,
  UserRound,
} from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { useCreateCase, useSetNodes, useSetOptions } from '@/api/cases'
import { usePlaygroundInvoke } from '@/api/playground'
import { useExecutors } from '@/api/runs'
import type { Message, PlaygroundResponse, Role } from '@/api/types'
import { GenerationParams } from '@/components/GenerationParams'
import { PageHeader } from '@/components/layout/AppShell'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatCost, formatDurationMs, formatTokens } from '@/lib/format'
import { cn } from '@/lib/utils'

export default function PlaygroundPage() {
  const executors = useExecutors()
  const invoke = usePlaygroundInvoke()
  const [executorId, setExecutorId] = React.useState<number | null>(null)
  const [system, setSystem] = React.useState('')
  const [turns, setTurns] = React.useState<Message[]>([])
  const [draft, setDraft] = React.useState('')
  const [params, setParams] = React.useState<Record<string, unknown>>({})
  const [result, setResult] = React.useState<PlaygroundResponse | null>(null)
  const [lastRequest, setLastRequest] = React.useState<Message[]>([])
  const [saving, setSaving] = React.useState(false)

  const rows = React.useMemo(() => executors.data?.items ?? [], [executors.data])
  const selected = rows.find((executor) => executor.id === executorId) ?? null

  React.useEffect(() => {
    if (executorId === null && rows.length > 0) setExecutorId(rows[0].id)
  }, [executorId, rows])

  if (executors.isLoading) return <LoadingState label="Loading Playground…" />
  if (executors.isError)
    return <ErrorState error={executors.error} onRetry={() => void executors.refetch()} />

  if (rows.length === 0) {
    return (
      <>
        <PageHeader
          title="Playground"
          description="Manually call the same executors used by formal evaluations."
        />
        <EmptyState
          icon={<MessageSquareText className="size-6" />}
          title="Configure an executor first"
          description="A Playground call uses a saved model + harness pair, so manual testing and formal runs exercise the same integration."
          action={
            <Button asChild size="sm">
              <Link to="/executors">
                Configure executors
                <ArrowRight />
              </Link>
            </Button>
          }
        />
      </>
    )
  }

  function requestMessages(userText: string): Message[] {
    return [
      ...(system.trim() ? [{ role: 'system' as Role, content: system.trim() }] : []),
      ...turns,
      { role: 'user' as Role, content: userText },
    ]
  }

  function send() {
    if (!selected || !draft.trim()) return
    const messages = requestMessages(draft.trim())
    setLastRequest(messages)
    setTurns((current) => [...current, { role: 'user', content: draft.trim() }])
    setDraft('')
    setResult(null)
    invoke.mutate(
      { executor_id: selected.id, messages, params },
      {
        onSuccess: (response) => {
          setResult(response)
          if (!response.ok) return
          const transcript = parseTranscript(response.messages)
          if (transcript.length > 0) {
            setSystem(transcript.find((message) => message.role === 'system')?.content ?? system)
            setTurns(transcript.filter((message) => message.role !== 'system'))
          } else {
            setTurns((current) => [
              ...current,
              { role: 'assistant', content: response.output_text },
            ])
          }
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  function clear() {
    setTurns([])
    setDraft('')
    setResult(null)
    setLastRequest([])
  }

  return (
    <>
      <PageHeader
        title="Playground"
        description="Probe an executor by hand, inspect the raw response, then promote a useful interaction into your eval library."
        actions={
          <Button variant="outline" size="sm" onClick={clear} disabled={turns.length === 0}>
            <Eraser />
            Clear chat
          </Button>
        }
      />

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_23rem]">
        <Card className="min-w-0 overflow-hidden">
          <CardHeader className="border-b border-[var(--border)] pb-3">
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Executor" htmlFor="playground-executor" className="min-w-64 flex-1">
                <Select
                  value={executorId === null ? '' : String(executorId)}
                  onValueChange={(value) => {
                    setExecutorId(Number(value))
                    setResult(null)
                    setParams({})
                  }}
                >
                  <SelectTrigger id="playground-executor">
                    <SelectValue placeholder="Choose an executor" />
                  </SelectTrigger>
                  <SelectContent>
                    {rows.map((executor) => (
                      <SelectItem key={executor.id} value={String(executor.id)}>
                        {executor.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              {selected ? (
                <div className="mb-0.5 flex flex-wrap gap-1.5">
                  <Badge variant="outline">{selected.provider}</Badge>
                  <Badge variant="outline">{selected.harness_kind}</Badge>
                </div>
              ) : null}
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="border-b border-[var(--border)] p-3">
              <details>
                <summary className="cursor-pointer text-xs font-medium text-[var(--muted-foreground)]">
                  System message {system ? '· configured' : '· optional'}
                </summary>
                <Textarea
                  value={system}
                  onChange={(event) => setSystem(event.target.value)}
                  rows={3}
                  className="mt-2 font-sans text-sm"
                  placeholder="Instructions applied to the conversation…"
                />
              </details>
            </div>

            <div className="flex min-h-[22rem] max-h-[55vh] flex-col gap-3 overflow-y-auto p-4">
              {turns.length === 0 ? (
                <div className="m-auto max-w-md text-center">
                  <MessageSquareText className="mx-auto mb-3 size-8 text-[var(--primary)]/70" />
                  <h2 className="text-sm font-semibold">
                    Test the behaviour before building a run
                  </h2>
                  <p className="mt-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
                    Try a prompt, inspect text and JSON, tune parameters, and save the useful input
                    as a reusable case.
                  </p>
                </div>
              ) : (
                turns.map((message, index) => <ChatTurn key={index} message={message} />)
              )}
              {invoke.isPending ? (
                <div className="flex max-w-[82%] items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs text-[var(--muted-foreground)]">
                  <Bot className="size-4 animate-pulse" />
                  Calling {selected?.name}…
                </div>
              ) : null}
              {result && !result.ok ? (
                <div className="max-w-[82%] rounded-lg border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 px-3 py-2 text-sm">
                  <p className="font-medium text-[var(--destructive)]">
                    {result.error_kind ?? 'Invocation failed'}
                  </p>
                  <p className="mt-1 text-xs">{result.error}</p>
                </div>
              ) : null}
            </div>

            <div className="border-t border-[var(--border)] p-3">
              <Textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') send()
                }}
                rows={4}
                className="font-sans text-sm"
                placeholder="Type a message…  ⌘/Ctrl + Enter to send"
                aria-label="Playground message"
              />
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <span className="text-[10px] text-[var(--muted-foreground)]">
                  This calls the provider and may incur cost. It does not create a formal run.
                </span>
                <Button onClick={send} disabled={!draft.trim() || invoke.isPending || !selected}>
                  {invoke.isPending ? <Play className="animate-pulse" /> : <Send />}
                  {invoke.isPending ? 'Running…' : 'Send'}
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="flex min-w-0 flex-col gap-4 xl:sticky xl:top-0">
          {selected ? (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle>Invocation controls</CardTitle>
                <CardDescription>
                  Overrides apply only to this manual call; the saved executor is unchanged.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <GenerationParams
                  provider={selected.provider}
                  modelId={selected.model_id}
                  value={params}
                  onChange={setParams}
                  idPrefix="playground"
                />
              </CardContent>
            </Card>
          ) : null}

          <ResultInspector
            result={result}
            canSave={lastRequest.length > 0 && Boolean(result?.ok)}
            onSave={() => setSaving(true)}
          />
        </div>
      </div>

      <SaveCaseDialog
        open={saving}
        onOpenChange={setSaving}
        input={lastRequest}
        output={result?.output_text ?? ''}
      />
    </>
  )
}

function ChatTurn({ message }: { message: Message }) {
  const assistant = message.role === 'assistant'
  return (
    <div
      className={cn(
        'flex max-w-[82%] gap-2 rounded-lg border px-3 py-2 text-sm',
        assistant
          ? 'self-start border-[var(--border)] bg-[var(--surface-2)]'
          : 'self-end border-[var(--primary)]/30 bg-[var(--primary)]/8',
      )}
    >
      {assistant ? (
        <Bot className="mt-0.5 size-4 shrink-0 text-[var(--primary)]" />
      ) : (
        <UserRound className="mt-0.5 size-4 shrink-0 text-[var(--primary)]" />
      )}
      <div className="min-w-0 whitespace-pre-wrap break-words leading-relaxed">
        <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
          {message.role}
        </p>
        {message.content}
      </div>
    </div>
  )
}

function ResultInspector({
  result,
  canSave,
  onSave,
}: {
  result: PlaygroundResponse | null
  canSave: boolean
  onSave: () => void
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-2 pb-2">
        <div>
          <CardTitle>Last response</CardTitle>
          <CardDescription>Rendered output, parsed JSON and transport metadata.</CardDescription>
        </div>
        {canSave ? (
          <Button variant="outline" size="sm" onClick={onSave}>
            <FilePlus2 />
            Save as case
          </Button>
        ) : null}
      </CardHeader>
      <CardContent>
        {!result ? (
          <p className="py-4 text-xs text-[var(--muted-foreground)]">
            Send a message to inspect the response here.
          </p>
        ) : result.ok ? (
          <Tabs defaultValue="output">
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="output">Output</TabsTrigger>
              <TabsTrigger value="json">JSON</TabsTrigger>
              <TabsTrigger value="raw">Raw</TabsTrigger>
            </TabsList>
            <TabsContent value="output">
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-[var(--surface-2)] p-3 font-sans text-xs leading-relaxed">
                {result.output_text}
              </pre>
            </TabsContent>
            <TabsContent value="json">
              <pre className="max-h-64 overflow-auto rounded-md bg-[var(--surface-2)] p-3 text-xs leading-relaxed">
                {result.parsed_output === null
                  ? 'Output is not valid JSON.'
                  : JSON.stringify(result.parsed_output, null, 2)}
              </pre>
            </TabsContent>
            <TabsContent value="raw">
              <pre className="max-h-64 overflow-auto rounded-md bg-[var(--surface-2)] p-3 text-xs leading-relaxed">
                {JSON.stringify(result.raw, null, 2)}
              </pre>
            </TabsContent>
            <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] text-[var(--muted-foreground)]">
              <span>{formatDurationMs(result.usage.latency_ms)} latency</span>
              <span>{formatCost(result.usage.cost_usd)} cost</span>
              <span>{formatTokens(result.usage.prompt_tokens)} input tokens</span>
              <span>{formatTokens(result.usage.completion_tokens)} output tokens</span>
            </div>
          </Tabs>
        ) : (
          <div className="rounded-md border border-[var(--destructive)]/40 p-3 text-xs">
            <p className="font-medium text-[var(--destructive)]">{result.error_kind}</p>
            <p className="mt-1">{result.error}</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function SaveCaseDialog({
  open,
  onOpenChange,
  input,
  output,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  input: Message[]
  output: string
}) {
  const create = useCreateCase()
  const sets = useSetOptions()
  const [title, setTitle] = React.useState('')
  const [setId, setSetId] = React.useState<number | null>(null)
  const [nodeId, setNodeId] = React.useState<number | null>(null)
  const [useReference, setUseReference] = React.useState(false)
  const nodes = useSetNodes(setId ?? undefined)

  React.useEffect(() => {
    if (!open) return
    const prompt = [...input].reverse().find((message) => message.role === 'user')?.content ?? ''
    setTitle(prompt.slice(0, 80) || 'Playground case')
    setUseReference(false)
  }, [open, input])

  function submit(event: React.FormEvent) {
    event.preventDefault()
    create.mutate(
      {
        title: title.trim(),
        input,
        reference: useReference ? output : null,
        set_id: setId ?? undefined,
        node_id: nodeId ?? undefined,
        tags: ['playground'],
        notes: 'Promoted from a manual Playground invocation.',
      },
      {
        onSuccess: () => {
          toast.success('Saved to the case library')
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
            <DialogTitle>Save Playground input as a case</DialogTitle>
            <DialogDescription>
              The request becomes reusable eval input. The model response is evidence, not an
              expected answer, unless you explicitly make it the reference.
            </DialogDescription>
          </DialogHeader>
          <Field label="Case title" htmlFor="playground-case-title">
            <Input
              id="playground-case-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              required
              autoFocus
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Eval set" htmlFor="playground-case-set">
              <Select
                value={setId === null ? '__library__' : String(setId)}
                onValueChange={(value) => {
                  setSetId(value === '__library__' ? null : Number(value))
                  setNodeId(null)
                }}
              >
                <SelectTrigger id="playground-case-set">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__library__">Case library only</SelectItem>
                  {(sets.data?.items ?? []).map((set) => (
                    <SelectItem key={set.id} value={String(set.id)}>
                      {set.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Branch" htmlFor="playground-case-node">
              <Select
                value={nodeId === null ? '__ungrouped__' : String(nodeId)}
                onValueChange={(value) =>
                  setNodeId(value === '__ungrouped__' ? null : Number(value))
                }
                disabled={setId === null}
              >
                <SelectTrigger id="playground-case-node">
                  <SelectValue placeholder="Ungrouped" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__ungrouped__">Ungrouped</SelectItem>
                  {(nodes.data ?? []).map((node) => (
                    <SelectItem key={node.id} value={String(node.id)}>
                      {node.path.join(' / ')}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </div>
          <label className="flex cursor-pointer items-start gap-2 rounded-md border border-[var(--border)] p-3 text-xs">
            <button
              type="button"
              role="checkbox"
              aria-checked={useReference}
              onClick={() => setUseReference((value) => !value)}
              className={cn(
                'mt-0.5 grid size-4 shrink-0 place-items-center rounded border',
                useReference
                  ? 'border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]'
                  : 'border-[var(--border)]',
              )}
            >
              {useReference ? <Check className="size-3" /> : null}
            </button>
            <span>
              <span className="block font-medium">Use this response as the reference answer</span>
              <span className="mt-0.5 block text-[var(--muted-foreground)]">
                Choose this only when you have manually verified the output is the expected result.
              </span>
            </span>
          </label>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!title.trim() || create.isPending}>
              <FilePlus2 />
              {create.isPending ? 'Saving…' : 'Save case'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function parseTranscript(rows: Array<Record<string, unknown>>): Message[] {
  const messages: Message[] = []
  for (const row of rows) {
    if (
      (row.role === 'system' || row.role === 'user' || row.role === 'assistant') &&
      typeof row.content === 'string'
    ) {
      messages.push({ role: row.role, content: row.content })
    }
  }
  return messages
}
