import { AlertTriangle } from 'lucide-react'
import * as React from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, Input } from '@/components/ui/input'

/**
 * A confirmation for something that cannot be undone.
 *
 * Two deliberate choices. First, `impact` is a list of what will actually be
 * destroyed, with counts — "Delete this run?" tells you nothing, while "412
 * items, 438 attempts, 9 saved artifacts" tells you whether you meant it.
 * Second, `confirmText` makes the user type the name: reserved for the cases
 * where the data is genuinely gone afterwards, because a dialog you can dismiss
 * with a reflexive second click is not a confirmation.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  impact,
  confirmText,
  confirmLabel = 'Delete permanently',
  busy,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: React.ReactNode
  /** What will be destroyed. Shown as a list; empty entries are skipped. */
  impact?: (string | null | undefined | false)[]
  /** When set, the user must type this exactly before the button enables. */
  confirmText?: string
  confirmLabel?: string
  busy?: boolean
  onConfirm: () => void
}) {
  const [typed, setTyped] = React.useState('')

  React.useEffect(() => {
    if (open) setTyped('')
  }, [open])

  const lines = (impact ?? []).filter((line): line is string => Boolean(line))
  const unlocked = !confirmText || typed.trim() === confirmText.trim()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent widthClass="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="size-4 text-[var(--destructive)]" />
            {title}
          </DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>

        {lines.length > 0 ? (
          <ul className="flex flex-col gap-1 rounded-md border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 px-3 py-2 text-sm">
            {lines.map((line, index) => (
              <li key={index} className="flex gap-2">
                <span className="text-[var(--destructive)]">•</span>
                {line}
              </li>
            ))}
          </ul>
        ) : null}

        {confirmText ? (
          <Field
            label={`Type “${confirmText}” to confirm`}
            hint="This cannot be undone, so it asks for the name rather than another click."
            htmlFor="confirm-text"
          >
            <Input
              id="confirm-text"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
          </Field>
        ) : null}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={!unlocked || busy}>
            {busy ? 'Working…' : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
