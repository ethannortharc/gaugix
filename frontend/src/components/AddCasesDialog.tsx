import { FileUp, PenLine, Sparkles } from 'lucide-react'
import * as React from 'react'

import type { EvalSetNode } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export type AddCasesMethod = 'manual' | 'import' | 'ai'

const METHODS: {
  id: AddCasesMethod
  title: string
  description: string
  detail: string
  icon: React.ComponentType<{ className?: string }>
}[] = [
  {
    id: 'manual',
    title: 'Write one case',
    description: 'Use the guided editor or paste one canonical JSON object.',
    detail: 'Best for a precise regression or a quick manual check.',
    icon: PenLine,
  },
  {
    id: 'import',
    title: 'Import a batch',
    description: 'Paste rows or load JSONL, JSON, YAML, CSV, HuggingFace, or promptfoo.',
    detail: 'Server-side Check validates the entire batch before anything is written.',
    icon: FileUp,
  },
  {
    id: 'ai',
    title: 'Generate with AI',
    description: 'Draft 1–100 cases with any assistant or a configured executor.',
    detail: 'Review generated JSONL and run the same importer before committing.',
    icon: Sparkles,
  },
]

/** One entry point for every case-authoring path, with its destination made explicit. */
export function AddCasesDialog({
  open,
  onOpenChange,
  setName,
  nodes = [],
  defaultNodeId,
  onChoose,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  setName?: string
  nodes?: EvalSetNode[]
  defaultNodeId?: number
  onChoose: (method: AddCasesMethod, nodeId?: number) => void
}) {
  const [nodeId, setNodeId] = React.useState<number | null>(defaultNodeId ?? null)

  React.useEffect(() => {
    if (open) setNodeId(defaultNodeId ?? null)
  }, [open, defaultNodeId])

  const destination = nodes.find((node) => node.id === nodeId)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent widthClass="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Add cases</DialogTitle>
          <DialogDescription>
            Choose how to create them. The destination is carried through every step, including
            batch imports and AI-generated drafts.
          </DialogDescription>
        </DialogHeader>

        {setName ? (
          <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3">
            <div className="grid items-end gap-3 sm:grid-cols-[minmax(0,1fr)_16rem]">
              <div className="min-w-0">
                <p className="text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                  Destination set
                </p>
                <p className="truncate text-sm font-semibold">{setName}</p>
                <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                  {destination ? destination.path.join(' / ') : 'Ungrouped'}
                </p>
              </div>
              {nodes.length > 0 ? (
                <Field label="Branch" htmlFor="add-cases-branch">
                  <Select
                    value={nodeId === null ? '__ungrouped__' : String(nodeId)}
                    onValueChange={(value) =>
                      setNodeId(value === '__ungrouped__' ? null : Number(value))
                    }
                  >
                    <SelectTrigger id="add-cases-branch">
                      <SelectValue />
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
                </Field>
              ) : null}
            </div>
          </div>
        ) : (
          <p className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs text-[var(--muted-foreground)]">
            No destination set selected. New cases will remain in the Case library until you add
            them to a set.
          </p>
        )}

        <div className="grid gap-2">
          {METHODS.map((method) => {
            const Icon = method.icon
            return (
              <button
                key={method.id}
                type="button"
                onClick={() => onChoose(method.id, nodeId ?? undefined)}
                className="group flex items-start gap-3 rounded-lg border border-[var(--border)] bg-[var(--card)] p-3 text-left transition-colors hover:border-[var(--primary)]/60 hover:bg-[var(--primary)]/6"
              >
                <span className="mt-0.5 rounded-md bg-[var(--primary)]/12 p-2 text-[var(--primary)]">
                  <Icon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold">{method.title}</span>
                  <span className="mt-0.5 block text-xs text-[var(--muted-foreground)]">
                    {method.description}
                  </span>
                  <span className="mt-1 block text-[11px] text-[var(--muted-foreground)]/80">
                    {method.detail}
                  </span>
                </span>
                <span className="mt-2 text-xs font-medium text-[var(--primary)] opacity-0 transition-opacity group-hover:opacity-100">
                  Continue →
                </span>
              </button>
            )
          })}
        </div>

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
