import { AlertTriangle, CheckCircle2, FileText, Upload } from 'lucide-react'
import * as React from 'react'
import { toast } from 'sonner'

import { useImportCases } from '@/api/cases'
import {
  IMPORT_FORMAT_LABELS,
  MAPPABLE_FORMATS,
  type FieldMapping,
  type ImportFormat,
  type ImportResult,
} from '@/api/types'
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
import { pluralize } from '@/lib/format'

const PLACEHOLDERS: Record<ImportFormat, string> = {
  jsonl: '{"title": "…", "input": [{"role": "user", "content": "…"}]}',
  yaml: 'cases:\n  - title: …\n    input:\n      - role: user\n        content: …',
  json: '[{"title": "…", "input": [{"role": "user", "content": "…"}]}]',
  csv: 'question,answer\nWhat is 2+2?,4',
  openai_evals: '{"input": [{"role": "user", "content": "…"}], "ideal": "…"}',
  huggingface: '{"rows": [{"row_idx": 0, "row": {"question": "…", "answer": "…"}}]}',
  promptfoo:
    'tests:\n  - vars:\n      input: …\n    assert:\n      - type: contains\n        value: …',
}

/**
 * Guess the format from a filename, then from the content when it lies.
 *
 * Mirrors the server's inference: `.jsonl` covers both the native shape and
 * openai/evals, and `.yaml` covers both native YAML and a promptfoo config, so
 * the extension alone is not enough. Returns null when nothing is distinctive,
 * leaving whatever the user already chose alone.
 */
function formatFromName(name: string, content: string): ImportFormat | null {
  const lower = name.toLowerCase()
  if (lower.endsWith('.csv') || lower.endsWith('.tsv')) return 'csv'
  if (lower.endsWith('.yaml') || lower.endsWith('.yml')) {
    return /^\s*tests\s*:/m.test(content) ? 'promptfoo' : 'yaml'
  }
  if (lower.endsWith('.json')) {
    return content.trimStart().slice(0, 400).includes('"rows"') ? 'huggingface' : 'json'
  }
  if (lower.endsWith('.jsonl') || lower.endsWith('.ndjson')) {
    const first = content.split('\n').find((line) => line.trim()) ?? ''
    return first.includes('"ideal"') && !first.includes('"title"') ? 'openai_evals' : 'jsonl'
  }
  return null
}

const PLACEHOLDER_HINTS: Record<ImportFormat, string> = {
  jsonl: 'One JSON object per line.',
  yaml: 'A list, or a `cases:` key holding one.',
  json: 'An array of case objects.',
  csv: 'A header row, then one case per line. Tabs and semicolons work too.',
  openai_evals: 'openai/evals rows. A list `ideal` keeps every accepted answer.',
  huggingface: 'Paste a datasets-server /rows response, or a bare array of rows.',
  promptfoo: 'Assertions become scorers where an honest translation exists.',
}

/**
 * Import is all-or-nothing (PRD F1.3), so the dialog's job is to make the
 * *rejected rows* legible: line number, reason, and the offending text. A
 * "Check" pass runs the same validation server-side without writing anything.
 *
 * Warnings are the other half. A promptfoo assertion Gaugix cannot express does
 * not block the import — but a case that quietly lost a check would look scored
 * and not be, so it is reported alongside the success.
 */
export function ImportDialog({
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
  const [content, setContent] = React.useState('')
  const [format, setFormat] = React.useState<ImportFormat>('jsonl')
  const [mapping, setMapping] = React.useState<FieldMapping>({})
  const [result, setResult] = React.useState<ImportResult | null>(null)
  const [file, setFile] = React.useState<{ name: string; bytes: number } | null>(null)
  const fileRef = React.useRef<HTMLInputElement>(null)

  const importPaste = useImportCases()

  React.useEffect(() => {
    if (open) {
      setContent('')
      setResult(null)
      setMapping({})
      setFile(null)
    }
  }, [open])

  function run(dryRun: boolean) {
    const mapped = MAPPABLE_FORMATS.includes(format) && Object.values(mapping).some(Boolean)
    importPaste.mutate(
      {
        content,
        format,
        set_id: setId,
        node_id: nodeId,
        dry_run: dryRun,
        ...(mapped ? { mapping } : {}),
      },
      {
        onSuccess: (res) => {
          setResult(res)
          if (res.ok && !dryRun) {
            toast.success(`Imported ${res.imported} ${pluralize(res.imported, 'case')}`)
            onOpenChange(false)
          } else if (res.ok && dryRun) {
            toast.success(`${res.imported} ${pluralize(res.imported, 'case')} look valid`)
          }
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  /**
   * Load a file into the same buffer a paste fills.
   *
   * Uploading used to be its own endpoint that imported immediately: it
   * ignored the format you had chosen, ignored the column mapping, and skipped
   * Check entirely — so the mapping fields only ever worked for pasted text.
   * Reading the file here puts both routes through one path (D-052).
   */
  async function handleFile(event: React.ChangeEvent<HTMLInputElement>) {
    const picked = event.target.files?.[0]
    event.target.value = ''
    if (!picked) return

    const text = await picked.text()
    setContent(text)
    setFile({ name: picked.name, bytes: picked.size })
    setResult(null)
    const guess = formatFromName(picked.name, text)
    if (guess) setFormat(guess)
  }

  const busy = importPaste.isPending
  // A 3 MB benchmark CSV in a controlled textarea re-renders on every keystroke
  // and stalls the dialog, so past this size the file is summarised instead.
  const tooBigToShow = file !== null && content.length > 200_000

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent widthClass="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Import cases</DialogTitle>
          <DialogDescription>
            {setName ? (
              <>
                Cases are added to <strong>{setName}</strong>
                {nodePath?.length ? ` / ${nodePath.join(' / ')}` : ' / Ungrouped'}, in file order.
                Native <code className="font-mono">group_path</code> values create nested branches
                below this destination.{' '}
              </>
            ) : null}
            Import is all-or-nothing: if any row is invalid, nothing is written.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-2">
          <Select value={format} onValueChange={(f) => setFormat(f as ImportFormat)}>
            <SelectTrigger className="w-[280px]" aria-label="Import format">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(IMPORT_FORMAT_LABELS) as ImportFormat[]).map((value) => (
                <SelectItem key={value} value={value}>
                  {IMPORT_FORMAT_LABELS[value]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => fileRef.current?.click()}
            disabled={busy}
          >
            <Upload />
            Load a file
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept=".jsonl,.json,.yaml,.yml,.csv,.tsv,.ndjson,text/plain"
            onChange={(event) => void handleFile(event)}
            className="hidden"
            aria-label="Case file"
          />
        </div>

        {/*
          Only tabular formats need this. The server guesses from the first row
          and refuses rather than picking wrong, so these fields exist for when
          the guess is wrong or the columns are named something unusual.
        */}
        {MAPPABLE_FORMATS.includes(format) ? (
          <div className="grid grid-cols-2 gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-3 sm:grid-cols-3">
            <p className="col-span-full text-xs text-[var(--muted-foreground)]">
              Leave these blank to let Gaugix guess from the first row — it refuses rather than
              guessing wrong.
            </p>
            <Field label="Prompt column" htmlFor="map-input">
              <Input
                id="map-input"
                value={mapping.input ?? ''}
                onChange={(e) => setMapping({ ...mapping, input: e.target.value || null })}
                placeholder="question"
              />
            </Field>
            <Field label="Expected column" htmlFor="map-reference">
              <Input
                id="map-reference"
                value={mapping.reference ?? ''}
                onChange={(e) => setMapping({ ...mapping, reference: e.target.value || null })}
                placeholder="answer"
              />
            </Field>
            <Field label="Title column" htmlFor="map-title">
              <Input
                id="map-title"
                value={mapping.title ?? ''}
                onChange={(e) => setMapping({ ...mapping, title: e.target.value || null })}
                placeholder="(optional)"
              />
            </Field>
          </div>
        ) : null}

        {tooBigToShow ? (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-sm">
            <FileText className="size-4 shrink-0 text-[var(--muted-foreground)]" />
            <span className="min-w-0 flex-1 truncate">
              <strong>{file.name}</strong>{' '}
              <span className="text-[var(--muted-foreground)]">
                — {(file.bytes / 1e6).toFixed(1)} MB, too large to show. Check and Import read all
                of it.
              </span>
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setContent('')
                setFile(null)
              }}
            >
              Clear
            </Button>
          </div>
        ) : (
          <Field
            label={file ? `Cases from ${file.name}` : 'Paste cases'}
            hint={PLACEHOLDER_HINTS[format]}
            htmlFor="import-content"
          >
            <Textarea
              id="import-content"
              value={content}
              onChange={(e) => {
                setContent(e.target.value)
                setFile(null)
              }}
              rows={12}
              spellCheck={false}
              placeholder={PLACEHOLDERS[format]}
            />
          </Field>
        )}

        {result ? <ImportReport result={result} /> : null}

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => run(true)}
            disabled={!content.trim() || busy}
          >
            Check
          </Button>
          <Button type="button" onClick={() => run(false)} disabled={!content.trim() || busy}>
            {busy ? 'Importing…' : 'Import'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ImportReport({ result }: { result: ImportResult }) {
  const warnings = result.warnings ?? []

  if (result.ok) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2 rounded-md border border-[var(--pass)]/40 bg-[var(--pass)]/10 px-3 py-2 text-sm text-[var(--pass)]">
          <CheckCircle2 className="size-4" />
          {result.dry_run
            ? `${result.imported} ${pluralize(result.imported, 'case')} valid — nothing written yet.`
            : `Imported ${result.imported} ${pluralize(result.imported, 'case')}.`}
        </div>
        {warnings.length > 0 ? (
          <div className="flex max-h-40 flex-col gap-1.5 overflow-y-auto rounded-md border border-[var(--human)]/40 bg-[var(--human)]/10 p-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <AlertTriangle className="size-4" />
              {warnings.length} {pluralize(warnings.length, 'thing')} worth knowing about this
              import
            </div>
            <ul className="flex flex-col gap-1">
              {warnings.map((warning, i) => (
                <li key={i} className="text-xs text-[var(--muted-foreground)]">
                  {warning.message}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className="flex max-h-56 flex-col gap-2 overflow-y-auto rounded-md border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 p-3">
      <div className="flex items-center gap-2 text-sm font-medium text-[var(--destructive)]">
        <AlertTriangle className="size-4" />
        {result.errors.length} {pluralize(result.errors.length, 'row')} rejected — nothing was
        written
      </div>
      <ul className="flex flex-col gap-1.5">
        {result.errors.map((error, i) => (
          <li key={i} className="text-xs">
            <span className="tabular font-mono text-[var(--muted-foreground)]">
              line {error.line}
            </span>{' '}
            {error.message}
            {error.raw ? (
              <pre className="mt-0.5 overflow-x-auto rounded bg-[var(--muted)] px-1.5 py-1 font-mono text-[11px]">
                {error.raw}
              </pre>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  )
}
