import { X } from 'lucide-react'
import * as React from 'react'

import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

/**
 * Comma/Enter-separated tag entry. Tags are a set: duplicates and blanks are
 * dropped here so the server never has to guess what the user meant.
 */
export function TagInput({
  value,
  onChange,
  placeholder = 'Add a tag…',
  className,
  id,
}: {
  value: string[]
  onChange: (tags: string[]) => void
  placeholder?: string
  className?: string
  id?: string
}) {
  const [draft, setDraft] = React.useState('')

  function commit(raw: string) {
    const additions = raw
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    if (additions.length === 0) return
    onChange([...new Set([...value, ...additions])].sort())
    setDraft('')
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault()
      commit(draft)
    } else if (event.key === 'Backspace' && draft === '' && value.length > 0) {
      onChange(value.slice(0, -1))
    }
  }

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      {value.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {value.map((tag) => (
            <Badge key={tag} variant="outline" className="gap-1 pr-1">
              {tag}
              <button
                type="button"
                onClick={() => onChange(value.filter((t) => t !== tag))}
                className="rounded-sm p-0.5 hover:bg-[var(--muted)]"
                aria-label={`Remove tag ${tag}`}
              >
                <X className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
      ) : null}
      <Input
        id={id}
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => commit(draft)}
      />
    </div>
  )
}
