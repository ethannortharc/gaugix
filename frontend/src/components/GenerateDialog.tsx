import { Check, Copy, Sparkles, Wand2 } from 'lucide-react'
import * as React from 'react'
import { toast } from 'sonner'

import { useGenerationPrompt, useImportCases } from '@/api/cases'
import { useExecutors, useGenerateDirect, type GenDirectResponse } from '@/api/runs'
import type { ImportResult } from '@/api/types'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatCost, formatTokens, pluralize } from '@/lib/format'

/**
 * Generate-with-AI, path A (PRD F1.4): Gaugix writes the prompt, you run it in
 * whatever assistant you already pay for, and paste the JSONL back. The paste-back
 * step goes through the ordinary importer, so generated cases face the same
 * validation as hand-written ones — and you preview before anything is committed.
 */
export function GenerateDialog({
  open,
  onOpenChange,
  setId,
  setName,
  nodeId,
  nodePath,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  setId?: number
  setName?: string
  nodeId?: number
  nodePath?: string[]
}) {
  const [tab, setTab] = React.useState('prompt')
  const [topic, setTopic] = React.useState('')
  const [count, setCount] = React.useState(10)
  const [instructions, setInstructions] = React.useState('')
  const [prompt, setPrompt] = React.useState('')
  const [pasted, setPasted] = React.useState('')
  const [preview, setPreview] = React.useState<ImportResult | null>(null)
  const [copied, setCopied] = React.useState(false)
  const [directExecutor, setDirectExecutor] = React.useState('')
  // What the last direct generation actually produced: the lines that failed to
  // parse, and what the call cost. Both were being thrown away — a run could
  // drop half its output and report only the half that survived.
  const [draft, setDraft] = React.useState<GenDirectResponse | null>(null)
  const [showRaw, setShowRaw] = React.useState(false)
  const executors = useExecutors()
  const direct = useGenerateDirect()

  function runDirect() {
    direct.mutate(
      {
        topic: topic.trim(),
        count,
        set_id: setId,
        instructions: instructions.trim() || undefined,
        executor_id: Number(directExecutor),
      },
      {
        onSuccess: (result) => {
          // Straight into the paste tab: the review-then-commit step is the
          // same one a hand-pasted batch goes through.
          setPasted(result.cases.map((c) => JSON.stringify(c)).join('\n'))
          setDraft(result)
          setTab('paste')
          if (result.errors.length > 0) {
            toast.warning(`${result.errors.length} line(s) came back malformed — check them`)
          } else {
            toast.success(`Drafted ${result.cases.length} cases — review before importing`)
          }
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  const build = useGenerationPrompt()
  const importCases = useImportCases()

  React.useEffect(() => {
    if (open) {
      setTab('prompt')
      setPrompt('')
      setPasted('')
      setPreview(null)
      setCopied(false)
      setDraft(null)
      setShowRaw(false)
    }
  }, [open])

  function generate() {
    build.mutate(
      {
        topic: topic.trim(),
        count,
        set_id: setId,
        example_count: 3,
        instructions: instructions.trim() || undefined,
      },
      {
        onSuccess: (res) => {
          setPrompt(res.prompt)
          toast.success(
            res.example_case_ids.length
              ? `Prompt built with ${res.example_case_ids.length} example ${pluralize(res.example_case_ids.length, 'case')}`
              : 'Prompt built',
          )
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  async function copyPrompt() {
    try {
      await navigator.clipboard.writeText(prompt)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      toast.error('Could not reach the clipboard — select the text and copy manually.')
    }
  }

  function check() {
    importCases.mutate(
      { content: pasted, format: 'jsonl', set_id: setId, node_id: nodeId, dry_run: true },
      { onSuccess: setPreview, onError: (error) => toast.error(error.message) },
    )
  }

  function commit() {
    importCases.mutate(
      { content: pasted, format: 'jsonl', set_id: setId, node_id: nodeId },
      {
        onSuccess: (res) => {
          setPreview(res)
          if (res.ok) {
            toast.success(`Added ${res.imported} generated ${pluralize(res.imported, 'case')}`)
            onOpenChange(false)
          }
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent widthClass="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="size-4 text-[var(--primary)]" />
            Generate cases with AI
          </DialogTitle>
          <DialogDescription>
            Gaugix builds the prompt (with the schema and real examples from
            {setName ? ` “${setName}”` : ' your library'}). Run it in any assistant, then paste the
            JSONL back — it goes through the same validation as a manual import.
            {setName ? (
              <>
                {' '}
                New cases go to <strong>{setName}</strong>
                {nodePath?.length ? ` / ${nodePath.join(' / ')}` : ' / Ungrouped'}.
              </>
            ) : null}
          </DialogDescription>
        </DialogHeader>

        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="prompt">1 · Build prompt</TabsTrigger>
            <TabsTrigger value="paste">2 · Paste result</TabsTrigger>
          </TabsList>

          <TabsContent value="prompt" className="flex flex-col gap-3">
            <div className="flex flex-wrap gap-3">
              <Field label="Topic" htmlFor="gen-topic" className="min-w-64 flex-1">
                <Input
                  id="gen-topic"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="obfuscated jailbreak attempts (base64, leetspeak, translation)"
                  autoFocus
                />
              </Field>
              <Field label="How many" htmlFor="gen-count" className="w-28">
                <Input
                  id="gen-count"
                  type="number"
                  min={1}
                  max={100}
                  value={count}
                  onChange={(e) => setCount(Number(e.target.value))}
                />
              </Field>
            </div>

            <Field
              label="Extra instructions (optional)"
              htmlFor="gen-instructions"
              hint="Anything the assistant should know — language, format quirks, what to avoid."
            >
              <Textarea
                id="gen-instructions"
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                rows={2}
                className="font-sans text-sm"
              />
            </Field>

            <div className="flex flex-wrap items-end gap-2">
              <Button type="button" onClick={generate} disabled={!topic.trim() || build.isPending}>
                <Wand2 />
                {build.isPending ? 'Building…' : 'Build prompt'}
              </Button>

              {/*
                Path B: hand the same prompt to a configured executor instead of
                the clipboard. The candidates still land in the paste tab and
                still go through the importer — a model's draft earns no more
                trust than a stranger's file.
              */}
              <Select value={directExecutor} onValueChange={setDirectExecutor}>
                <SelectTrigger className="w-56" aria-label="Generate with an executor">
                  <SelectValue placeholder="…or generate with" />
                </SelectTrigger>
                <SelectContent>
                  {(executors.data?.items ?? []).map((executor) => (
                    <SelectItem key={executor.id} value={String(executor.id)}>
                      {executor.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                type="button"
                variant="secondary"
                disabled={!topic.trim() || !directExecutor || direct.isPending}
                onClick={runDirect}
              >
                <Sparkles />
                {direct.isPending ? 'Generating…' : 'Generate now'}
              </Button>
            </div>
            {directExecutor ? (
              <p className="text-[11px] text-[var(--muted-foreground)]">
                This spends money on that executor, and its draft still has to pass the importer
                before anything is written.
              </p>
            ) : null}

            {prompt ? (
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-[var(--muted-foreground)]">
                    Copy this into your assistant
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => void copyPrompt()}
                  >
                    {copied ? <Check /> : <Copy />}
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                </div>
                <Textarea
                  value={prompt}
                  readOnly
                  rows={12}
                  spellCheck={false}
                  aria-label="Generated prompt"
                />
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setTab('paste')}
                  className="self-start"
                >
                  Next: paste the result
                </Button>
              </div>
            ) : null}
          </TabsContent>

          <TabsContent value="paste" className="flex flex-col gap-3">
            {draft ? <DraftReport draft={draft} showRaw={showRaw} onShowRaw={setShowRaw} /> : null}
            <Field
              label="Paste the assistant's JSONL"
              htmlFor="gen-paste"
              hint="One JSON object per line. Check first to see what would be created."
            >
              <Textarea
                id="gen-paste"
                value={pasted}
                onChange={(e) => setPasted(e.target.value)}
                rows={12}
                spellCheck={false}
              />
            </Field>

            {preview ? (
              preview.ok ? (
                <div className="rounded-md border border-[var(--pass)]/40 bg-[var(--pass)]/10 px-3 py-2 text-sm text-[var(--pass)]">
                  {preview.dry_run
                    ? `${preview.imported} ${pluralize(preview.imported, 'case')} ready to add.`
                    : `Added ${preview.imported} ${pluralize(preview.imported, 'case')}.`}
                </div>
              ) : (
                <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto rounded-md border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 p-3 text-xs">
                  <li className="font-medium text-[var(--destructive)]">
                    {preview.errors.length} {pluralize(preview.errors.length, 'row')} rejected —
                    nothing written
                  </li>
                  {preview.errors.map((error, i) => (
                    <li key={i}>
                      <span className="tabular font-mono text-[var(--muted-foreground)]">
                        line {error.line}
                      </span>{' '}
                      {error.message}
                    </li>
                  ))}
                </ul>
              )
            ) : null}
          </TabsContent>
        </Tabs>

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          {tab === 'paste' ? (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={check}
                disabled={!pasted.trim() || importCases.isPending}
              >
                Check
              </Button>
              <Button
                type="button"
                onClick={commit}
                disabled={!pasted.trim() || importCases.isPending}
              >
                Add cases
              </Button>
            </>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * What a direct generation actually produced.
 *
 * Two things were being discarded. The lines the model returned that would not
 * parse — so a run that dropped half its output reported only the surviving
 * half, and the malformed text was gone. And the token count and cost, which
 * are the reason path B is not free.
 */
function DraftReport({
  draft,
  showRaw,
  onShowRaw,
}: {
  draft: GenDirectResponse
  showRaw: boolean
  onShowRaw: (next: boolean) => void
}) {
  const { usage, errors } = draft
  const tokens = (usage.prompt_tokens ?? 0) + (usage.completion_tokens ?? 0)

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs">
        <span>
          <strong>{draft.cases.length}</strong> {pluralize(draft.cases.length, 'case')} drafted
        </span>
        {usage.executor ? (
          <span className="text-[var(--muted-foreground)]">by {usage.executor}</span>
        ) : null}
        <span className="text-[var(--muted-foreground)]">{formatTokens(tokens)} tokens</span>
        <span className="text-[var(--muted-foreground)]">
          {usage.cost_usd === null || usage.cost_usd === undefined
            ? 'cost unknown'
            : formatCost(usage.cost_usd)}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="ml-auto text-xs"
          onClick={() => onShowRaw(!showRaw)}
        >
          {showRaw ? 'Hide raw reply' : 'Show raw reply'}
        </Button>
      </div>

      {errors.length > 0 ? (
        <div className="flex max-h-44 flex-col gap-1.5 overflow-y-auto rounded-md border border-[var(--human)]/40 bg-[var(--human)]/10 p-3 text-xs">
          <span className="font-medium">
            {errors.length} {pluralize(errors.length, 'line')} the model returned could not be read
            — they are not in the box below
          </span>
          {errors.map((error, index) => (
            <div key={index}>
              <span className="tabular font-mono text-[var(--muted-foreground)]">
                line {error.line}
              </span>{' '}
              {error.message}
              {error.raw ? (
                <pre className="mt-0.5 overflow-x-auto rounded bg-[var(--muted)] px-1.5 py-1 font-mono text-[11px]">
                  {error.raw}
                </pre>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}

      {showRaw ? (
        <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-md border border-[var(--border)] bg-[var(--muted)] p-2 font-mono text-[11px]">
          {draft.raw_output}
        </pre>
      ) : null}
    </div>
  )
}
