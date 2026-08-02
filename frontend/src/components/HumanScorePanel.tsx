import { Check, UserRound, X } from 'lucide-react'
import * as React from 'react'
import { toast } from 'sonner'

import { useSubmitHumanScore } from '@/api/runs'
import type { ScorerSpec } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, Input } from '@/components/ui/input'

/**
 * Keyboard-first human scoring (PRD F4.4).
 *
 * `p` passes, `f` fails, `Enter` submits — because the realistic use is grinding
 * through a queue of twenty items, not scoring one thoughtfully.
 */
export function HumanScorePanel({
  itemId,
  scorerIndex,
  spec,
  onDone,
}: {
  itemId: number
  scorerIndex: number
  spec?: ScorerSpec
  onDone?: () => void
}) {
  const submit = useSubmitHumanScore()
  const [passed, setPassed] = React.useState<boolean | null>(null)
  const [value, setValue] = React.useState('')
  const [note, setNote] = React.useState('')

  const instructions =
    typeof spec?.params?.instructions === 'string' ? spec.params.instructions : null

  const send = React.useCallback(
    (verdict: boolean | null) => {
      const numeric = value.trim() === '' ? null : Number(value)
      if (verdict === null && numeric === null) {
        toast.error('Choose pass/fail or enter a score')
        return
      }
      submit.mutate(
        {
          itemId,
          scorer_index: scorerIndex,
          passed: verdict,
          value: numeric,
          note: note.trim(),
        },
        {
          onSuccess: (result) => {
            toast.success(
              result.disagreed_with_machine
                ? 'Recorded — you overturned the machine (counted for calibration)'
                : 'Score recorded',
            )
            setPassed(null)
            setValue('')
            setNote('')
            onDone?.()
          },
          onError: (error) => toast.error(error.message),
        },
      )
    },
    [itemId, scorerIndex, value, note, submit, onDone],
  )

  React.useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) {
        if (event.key === 'Enter' && passed !== null) send(passed)
        return
      }
      if (event.key === 'p' || event.key === 'P') {
        setPassed(true)
        send(true)
      } else if (event.key === 'f' || event.key === 'F') {
        setPassed(false)
        send(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [passed, send])

  return (
    <Card className="border-[var(--human)]/40">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-1.5">
          <UserRound className="size-4 text-[var(--human)]" />
          Your review
        </CardTitle>
        <CardDescription>
          {instructions ?? 'Score this item yourself. Your call overrides the machine.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex gap-2">
          <Button
            variant={passed === true ? 'default' : 'outline'}
            size="sm"
            className="flex-1"
            onClick={() => send(true)}
            disabled={submit.isPending}
          >
            <Check />
            Pass <kbd className="ml-1 opacity-60">p</kbd>
          </Button>
          <Button
            variant={passed === false ? 'destructive' : 'outline'}
            size="sm"
            className="flex-1"
            onClick={() => send(false)}
            disabled={submit.isPending}
          >
            <X />
            Fail <kbd className="ml-1 opacity-60">f</kbd>
          </Button>
        </div>

        <Field label="Score (0–100, optional)" htmlFor={`human-value-${itemId}`}>
          <Input
            id={`human-value-${itemId}`}
            type="number"
            min={0}
            max={100}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="—"
          />
        </Field>

        <Field label="Note" htmlFor={`human-note-${itemId}`}>
          <Input
            id={`human-note-${itemId}`}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What made you decide that?"
          />
        </Field>

        {value.trim() !== '' && passed === null ? (
          <Button size="sm" onClick={() => send(null)} disabled={submit.isPending}>
            Submit score only
          </Button>
        ) : null}
      </CardContent>
    </Card>
  )
}
