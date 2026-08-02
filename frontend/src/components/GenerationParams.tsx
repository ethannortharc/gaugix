import * as React from 'react'

import { useModelCapabilities } from '@/api/runs'
import type { Provider } from '@/api/types'
import { Field, Input, Label } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

/**
 * Generation params, with real controls for the ones that matter.
 *
 * Params are spread straight into the provider call, so a raw JSON box was
 * already *functional* — you just had to know that `reasoning_effort` exists,
 * that o3 takes it and gpt-4o-mini refuses it, and how to spell it. The model's
 * own capability list (from litellm, via `/model-capabilities`) decides which
 * controls appear, so the form cannot offer a knob the model will reject.
 *
 * The JSON escape hatch stays: anything without a control here still works by
 * typing it, and the two views edit the same object.
 */

export const UNSET = '__unset__'

type Params = Record<string, unknown>

function setParam(params: Params, key: string, value: unknown): Params {
  const next = { ...params }
  if (value === undefined || value === '' || value === null) {
    delete next[key]
  } else {
    next[key] = value
  }
  return next
}

function numberValue(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : ''
}

export function GenerationParams({
  provider,
  modelId,
  value,
  onChange,
  idPrefix,
  label = 'Generation params',
  hint,
}: {
  provider: Provider
  modelId: string
  value: Params
  onChange: (next: Params) => void
  idPrefix: string
  label?: string
  hint?: React.ReactNode
}) {
  const caps = useModelCapabilities(provider, modelId)
  const capabilities = caps.data

  const effort = typeof value.reasoning_effort === 'string' ? value.reasoning_effort : UNSET
  const showEffort = capabilities?.reasoning_effort ?? true
  const showTemperature = capabilities?.temperature ?? true
  const showMaxTokens = capabilities?.max_tokens ?? true

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <Label>{label}</Label>
        {hint ? <p className="text-xs text-[var(--muted-foreground)]">{hint}</p> : null}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        {showEffort ? (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${idPrefix}-effort`}>Reasoning effort</Label>
            <Select
              value={effort}
              onValueChange={(next) =>
                onChange(setParam(value, 'reasoning_effort', next === UNSET ? undefined : next))
              }
            >
              <SelectTrigger
                id={`${idPrefix}-effort`}
                className="h-8 w-36"
                aria-label="Reasoning effort"
              >
                <SelectValue placeholder="model default" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={UNSET}>model default</SelectItem>
                {(capabilities?.effort_levels ?? ['low', 'medium', 'high']).map((level) => (
                  <SelectItem key={level} value={level}>
                    {level}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}

        {showTemperature ? (
          <Field label="Temperature" htmlFor={`${idPrefix}-temperature`}>
            <Input
              id={`${idPrefix}-temperature`}
              type="number"
              min={0}
              max={2}
              step={0.1}
              value={numberValue(value.temperature)}
              onChange={(e) =>
                onChange(
                  setParam(
                    value,
                    'temperature',
                    e.target.value === '' ? undefined : Number(e.target.value),
                  ),
                )
              }
              className="h-8 w-24"
              placeholder="default"
            />
          </Field>
        ) : null}

        {showMaxTokens ? (
          <Field label="Max tokens" htmlFor={`${idPrefix}-max-tokens`}>
            <Input
              id={`${idPrefix}-max-tokens`}
              type="number"
              min={1}
              step={64}
              value={numberValue(value.max_tokens)}
              onChange={(e) =>
                onChange(
                  setParam(
                    value,
                    'max_tokens',
                    e.target.value === '' ? undefined : Number(e.target.value),
                  ),
                )
              }
              className="h-8 w-28"
              placeholder="default"
            />
          </Field>
        ) : null}
      </div>

      {capabilities && !capabilities.known && modelId ? (
        <p className="text-xs text-[var(--muted-foreground)]">
          litellm does not recognise <code className="font-mono">{modelId}</code>, so every control
          is offered. If the provider rejects one, the run will say so.
        </p>
      ) : null}
      {capabilities?.known && !capabilities.reasoning_effort ? (
        <p className="text-xs text-[var(--muted-foreground)]">
          <code className="font-mono">{modelId}</code> is not a reasoning model — it rejects
          <code className="font-mono"> reasoning_effort</code>.
        </p>
      ) : null}

      <ParamsJson id={`${idPrefix}-params`} value={value} onChange={onChange} />
    </div>
  )
}

/** The escape hatch: everything the controls above do not cover. */
function ParamsJson({
  id,
  value,
  onChange,
}: {
  id: string
  value: Params
  onChange: (next: Params) => void
}) {
  const serialized = React.useMemo(() => JSON.stringify(value, null, 2), [value])
  const [text, setText] = React.useState(serialized)
  const [error, setError] = React.useState<string | null>(null)
  const [open, setOpen] = React.useState(false)

  // The object is the source of truth: when a control above changes it, the
  // JSON follows. Editing the JSON while it is invalid never reaches the parent.
  React.useEffect(() => {
    if (!error) setText(serialized)
  }, [serialized, error])

  return (
    <details open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer text-xs text-[var(--muted-foreground)]">
        All params (JSON)
      </summary>
      <div className="mt-2">
        <textarea
          id={id}
          aria-label="Generation params JSON"
          value={text}
          spellCheck={false}
          rows={4}
          onChange={(e) => {
            setText(e.target.value)
            try {
              const parsed = JSON.parse(e.target.value || '{}')
              if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
                setError('expected a JSON object')
                return
              }
              setError(null)
              onChange(parsed as Params)
            } catch {
              setError('invalid JSON')
            }
          }}
          className={cn(
            'w-full rounded-md border border-[var(--input)] bg-[var(--background)] px-2.5 py-1.5 font-mono text-xs leading-relaxed',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]',
            error && 'border-[var(--destructive)]',
          )}
        />
        {error ? (
          <p role="alert" data-testid="params-error" className="text-xs text-[var(--destructive)]">
            {error}
          </p>
        ) : null}
      </div>
    </details>
  )
}

/** Compact read-only summary — used wherever an executor is listed. */
export function ParamsSummary({ params }: { params: Params }) {
  const entries = Object.entries(params ?? {})
  if (entries.length === 0) return null
  return (
    <span className="font-mono text-[11px] text-[var(--muted-foreground)]">
      {entries.map(([key, value]) => `${key}=${String(value)}`).join(' · ')}
    </span>
  )
}
