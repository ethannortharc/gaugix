import { Code2, GripVertical, Plus, Trash2 } from 'lucide-react'
import * as React from 'react'
import { toast } from 'sonner'

import { useCreateCase, useUpdateCase } from '@/api/cases'
import type { EvalCase, Message, Role, ScorerSpec } from '@/api/types'
import { ScoringBuilder } from '@/components/ScoringBuilder'
import { TagInput } from '@/components/TagInput'
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

const ROLES: Role[] = ['system', 'user', 'assistant']

/**
 * Case editor: a message-list form for the common path, plus a JSON source view
 * for when you want to paste a whole case in. The JSON tab validates on every
 * keystroke and refuses to hand invalid content back to the form (PRD F1.7).
 */
export function CaseEditorDialog({
  open,
  onOpenChange,
  caseData,
  setId,
  setDefaultScoring = [],
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  caseData: EvalCase | null
  setId?: number
  setDefaultScoring?: ScorerSpec[]
}) {
  const create = useCreateCase()
  const update = useUpdateCase()

  const [title, setTitle] = React.useState('')
  const [messages, setMessages] = React.useState<Message[]>([{ role: 'user', content: '' }])
  const [reference, setReference] = React.useState('')
  const [notes, setNotes] = React.useState('')
  const [tags, setTags] = React.useState<string[]>([])
  const [scoring, setScoring] = React.useState<ScorerSpec[]>([])
  const [tab, setTab] = React.useState('form')
  const [jsonText, setJsonText] = React.useState('')
  const [jsonError, setJsonError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!open) return
    setTab('form')
    setJsonError(null)
    setTitle(caseData?.title ?? '')
    setMessages(caseData?.input?.length ? caseData.input : [{ role: 'user' as Role, content: '' }])
    setReference(caseData?.reference ?? '')
    setNotes(caseData?.notes ?? '')
    setTags(caseData?.tags ?? [])
    setScoring(caseData?.scoring ?? [])
  }, [open, caseData])

  const payload = React.useMemo(
    () => ({
      title: title.trim(),
      input: messages,
      reference: reference.trim() || null,
      scoring,
      tags,
      notes: notes.trim() || null,
    }),
    [title, messages, reference, scoring, tags, notes],
  )

  // Entering the JSON tab shows the current form state; leaving it applies the
  // parsed value — so the two views can never silently disagree.
  function switchTab(next: string) {
    if (next === 'json') {
      setJsonText(JSON.stringify(payload, null, 2))
      setJsonError(null)
    }
    setTab(next)
  }

  function applyJson(text: string) {
    setJsonText(text)
    try {
      const parsed = JSON.parse(text)
      if (typeof parsed?.title !== 'string') throw new Error('`title` must be a string')
      if (!Array.isArray(parsed?.input)) throw new Error('`input` must be an array of messages')
      setTitle(parsed.title)
      setMessages(parsed.input)
      setReference(parsed.reference ?? '')
      setNotes(parsed.notes ?? '')
      setTags(parsed.tags ?? [])
      setScoring(parsed.scoring ?? [])
      setJsonError(null)
    } catch (error) {
      setJsonError(error instanceof Error ? error.message : 'invalid JSON')
    }
  }

  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (jsonError) {
      toast.error('Fix the JSON before saving')
      return
    }
    const onError = (error: Error) => toast.error(error.message)

    if (caseData) {
      update.mutate(
        { id: caseData.id, ...payload },
        {
          onSuccess: () => {
            toast.success('Case saved')
            onOpenChange(false)
          },
          onError,
        },
      )
    } else {
      create.mutate(
        { ...payload, set_id: setId },
        {
          onSuccess: () => {
            toast.success('Case created')
            onOpenChange(false)
          },
          onError,
        },
      )
    }
  }

  const busy = create.isPending || update.isPending
  const valid = title.trim().length > 0 && messages.some((m) => m.content.trim())

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent widthClass="max-w-3xl">
        <form onSubmit={submit} className="flex min-h-0 flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{caseData ? 'Edit case' : 'New case'}</DialogTitle>
            <DialogDescription>
              One behaviour per case — it should be able to fail for exactly one reason.
            </DialogDescription>
          </DialogHeader>

          <Tabs value={tab} onValueChange={switchTab} className="flex min-h-0 flex-col">
            <TabsList className="self-start">
              <TabsTrigger value="form">Editor</TabsTrigger>
              <TabsTrigger value="json">
                <Code2 className="size-3.5" />
                JSON
              </TabsTrigger>
            </TabsList>

            <TabsContent
              value="form"
              className="scroll-gutter flex max-h-[58vh] flex-col gap-4 overflow-y-auto"
            >
              <Field label="Title" htmlFor="case-title">
                <Input
                  id="case-title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Jailbreak: grandma napalm story"
                  autoFocus
                  required
                />
              </Field>

              <div className="flex flex-col gap-2">
                <span className="text-xs font-medium text-[var(--muted-foreground)]">Input</span>
                {messages.map((message, index) => (
                  <div key={index} className="flex items-start gap-2">
                    <GripVertical className="mt-2 size-4 shrink-0 text-[var(--muted-foreground)]" />
                    <Select
                      value={message.role}
                      onValueChange={(role) =>
                        setMessages(
                          messages.map((m, i) => (i === index ? { ...m, role: role as Role } : m)),
                        )
                      }
                    >
                      <SelectTrigger
                        className="w-28 shrink-0"
                        aria-label={`Message ${index + 1} role`}
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {ROLES.map((role) => (
                          <SelectItem key={role} value={role}>
                            {role}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Textarea
                      value={message.content}
                      onChange={(e) =>
                        setMessages(
                          messages.map((m, i) =>
                            i === index ? { ...m, content: e.target.value } : m,
                          ),
                        )
                      }
                      rows={3}
                      aria-label={`Message ${index + 1} content`}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      className="mt-1 text-[var(--muted-foreground)] hover:text-[var(--destructive)]"
                      onClick={() => setMessages(messages.filter((_, i) => i !== index))}
                      disabled={messages.length === 1}
                      aria-label={`Remove message ${index + 1}`}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                ))}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="self-start"
                  onClick={() => setMessages([...messages, { role: 'user', content: '' }])}
                >
                  <Plus />
                  Add message
                </Button>
              </div>

              <Field
                label="Reference"
                hint="What a correct answer must contain — for scorers and for you, later."
                htmlFor="case-reference"
              >
                <Textarea
                  id="case-reference"
                  value={reference}
                  onChange={(e) => setReference(e.target.value)}
                  rows={2}
                  className="font-sans text-sm"
                />
              </Field>

              <div className="flex flex-col gap-2">
                <span className="text-xs font-medium text-[var(--muted-foreground)]">Scoring</span>
                <ScoringBuilder
                  value={scoring}
                  onChange={setScoring}
                  emptyHint={
                    setDefaultScoring.length > 0
                      ? `No scorers — this case inherits the set default (${setDefaultScoring
                          .map((s) => s.type)
                          .join(', ')}).`
                      : undefined
                  }
                />
              </div>

              <Field label="Tags">
                <TagInput value={tags} onChange={setTags} />
              </Field>

              <Field label="Notes" htmlFor="case-notes">
                <Textarea
                  id="case-notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={2}
                  className="font-sans text-sm"
                />
              </Field>
            </TabsContent>

            <TabsContent value="json">
              <Field
                label="Case JSON"
                hint="The canonical import/export schema. Edits apply to the editor tab live."
                error={jsonError}
                htmlFor="case-json"
              >
                <Textarea
                  id="case-json"
                  value={jsonText}
                  onChange={(e) => applyJson(e.target.value)}
                  rows={20}
                  spellCheck={false}
                />
              </Field>
            </TabsContent>
          </Tabs>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!valid || busy || Boolean(jsonError)}>
              {busy ? 'Saving…' : caseData ? 'Save case' : 'Create case'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
