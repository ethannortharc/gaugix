import { Plus, Trash2 } from 'lucide-react'
import * as React from 'react'

import { SCORER_LABELS, SCORER_TYPES, type ScorerSpec, type ScorerType } from '@/api/types'
import { JudgeExecutorSelect, SelfJudgeWarning } from '@/components/JudgeSelect'
import { GuideLink } from '@/components/GuideLink'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field, Input, Label, Textarea } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/misc'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useRubrics } from '@/api/runs'
import { judgeExecutorId, useSelfJudging } from '@/lib/judge'
import { DEFAULT_PARAMS, newScorer } from '@/lib/scorers'
import { cn } from '@/lib/utils'

/**
 * Per-type forms for a case's scoring config (PRD F1.7).
 *
 * Each scorer type gets fields that match its actual params rather than one
 * generic JSON box — the point is that a wrong regex should be obvious before
 * a run burns tokens on it. A JSON escape hatch stays available per scorer for
 * the types whose params are genuinely structural (json_schema, python).
 */

export function ScoringBuilder({
  value,
  onChange,
  emptyHint,
}: {
  value: ScorerSpec[]
  onChange: (scoring: ScorerSpec[]) => void
  emptyHint?: React.ReactNode
}) {
  function update(index: number, patch: Partial<ScorerSpec>) {
    onChange(value.map((s, i) => (i === index ? { ...s, ...patch } : s)))
  }

  function updateParams(index: number, patch: Record<string, unknown>) {
    onChange(value.map((s, i) => (i === index ? { ...s, params: { ...s.params, ...patch } } : s)))
  }

  return (
    <div className="flex flex-col gap-3">
      {value.length === 0 ? (
        <p className="rounded-md border border-dashed border-[var(--border)] px-3 py-4 text-xs text-[var(--muted-foreground)]">
          {emptyHint ?? 'No scorers — this case inherits its set’s default scoring config.'}
        </p>
      ) : null}

      {value.map((scorer, index) => (
        <div
          key={index}
          className="flex flex-col gap-3 rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={scorer.type}
              onValueChange={(type) =>
                update(index, {
                  type: type as ScorerType,
                  params: structuredClone(DEFAULT_PARAMS[type as ScorerType]),
                })
              }
            >
              <SelectTrigger className="h-8 w-[180px]" aria-label={`Scorer ${index + 1} type`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SCORER_TYPES.map((type) => (
                  <SelectItem key={type} value={type}>
                    {type}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <label className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
              <Checkbox
                checked={scorer.required}
                onCheckedChange={(checked) => update(index, { required: checked === true })}
                aria-label={`Scorer ${index + 1} required`}
              />
              required
            </label>

            <label className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
              weight
              <Input
                type="number"
                min={0}
                step={0.5}
                value={scorer.weight}
                onChange={(e) => update(index, { weight: Number(e.target.value) })}
                className="h-8 w-16"
                aria-label={`Scorer ${index + 1} weight`}
              />
            </label>

            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="ml-auto text-[var(--muted-foreground)] hover:text-[var(--destructive)]"
              onClick={() => onChange(value.filter((_, i) => i !== index))}
              aria-label={`Remove scorer ${index + 1}`}
            >
              <Trash2 />
            </Button>
          </div>

          <p className="text-xs text-[var(--muted-foreground)]">{SCORER_LABELS[scorer.type]}</p>

          <ScorerParams
            index={index}
            scorer={scorer}
            onParams={(patch) => updateParams(index, patch)}
            onReplaceParams={(params) => update(index, { params })}
          />
        </div>
      ))}

      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onChange([...value, newScorer()])}
        >
          <Plus />
          Add scorer
        </Button>
        {value.length > 0 ? (
          <span className="text-xs text-[var(--muted-foreground)]">
            Verdict = every <strong>required</strong> scorer passes.
          </span>
        ) : null}
      </div>
    </div>
  )
}

function ScorerParams({
  index,
  scorer,
  onParams,
  onReplaceParams,
}: {
  index: number
  scorer: ScorerSpec
  onParams: (patch: Record<string, unknown>) => void
  onReplaceParams: (params: Record<string, unknown>) => void
}) {
  const p = scorer.params as Record<string, never>

  switch (scorer.type) {
    case 'contains':
    case 'not_contains':
      return (
        <div className="flex flex-col gap-2">
          <Field label="Text" htmlFor={`text-${index}`}>
            <Input
              id={`text-${index}`}
              value={String(p.text ?? '')}
              onChange={(e) => onParams({ text: e.target.value })}
              placeholder='e.g. "action": "block"'
              className="font-mono text-xs"
            />
          </Field>
          <label className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
            <Checkbox
              checked={Boolean(p.case_sensitive)}
              onCheckedChange={(c) => onParams({ case_sensitive: c === true })}
            />
            case sensitive
          </label>
        </div>
      )

    case 'regex':
      return (
        <div className="flex flex-col gap-2">
          <Field label="Pattern (Python regex)" htmlFor={`pattern-${index}`}>
            <Input
              id={`pattern-${index}`}
              value={String(p.pattern ?? '')}
              onChange={(e) => onParams({ pattern: e.target.value })}
              placeholder="^```go\\n"
              className="font-mono text-xs"
            />
          </Field>
          <label className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
            <Checkbox
              checked={p.should_match !== false}
              onCheckedChange={(c) => onParams({ should_match: c === true })}
            />
            must match (uncheck for “must not match”)
          </label>
        </div>
      )

    case 'json_schema':
      return (
        <div className="flex flex-col gap-2">
          <JsonField
            label="JSON Schema"
            id={`schema-${index}`}
            value={p.schema ?? {}}
            onChange={(schema) => onParams({ schema })}
          />
          <label className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
            <Checkbox
              checked={p.extract_json !== false}
              onCheckedChange={(c) => onParams({ extract_json: c === true })}
            />
            extract a JSON block from prose output first
          </label>
        </div>
      )

    case 'python':
      return (
        <div className="flex flex-col gap-2">
          <Field
            label="score(case, output) → {passed, value, rationale}"
            hint="Runs on this machine in a separate process, with a hard timeout."
            htmlFor={`code-${index}`}
          >
            <Textarea
              id={`code-${index}`}
              value={String(p.code ?? '')}
              onChange={(e) => onParams({ code: e.target.value })}
              rows={8}
            />
          </Field>
          {/*
            This used to say "sandboxed subprocess", which is a claim Gaugix
            cannot honour: `python -I` isolates import paths, not the filesystem
            or the network. Saying so is the difference between a user pasting
            a scorer from the internet and reading it first.
          */}
          <p className="rounded-md border border-[var(--border)] bg-[var(--muted)]/40 px-2.5 py-1.5 text-xs text-[var(--muted-foreground)]">
            <strong className="text-[var(--foreground)]">This is not a sandbox.</strong> The
            separate process and the timeout stop mistakes, not malice — your code can still read
            and write your files, reach the network and start other programs. Only paste scorers you
            have read.
          </p>
        </div>
      )

    case 'llm_judge':
      return <JudgeParams index={index} p={p} onParams={onParams} />

    case 'human':
      return (
        <Field label="Instructions for the reviewer" htmlFor={`instructions-${index}`}>
          <Input
            id={`instructions-${index}`}
            value={String(p.instructions ?? '')}
            onChange={(e) => onParams({ instructions: e.target.value })}
            placeholder="What should I look at when scoring this?"
          />
        </Field>
      )

    default:
      return (
        <JsonField
          label="Params"
          id={`params-${index}`}
          value={scorer.params}
          onChange={(params) => onReplaceParams(params as Record<string, unknown>)}
        />
      )
  }
}

/**
 * The judge form, split out because it needs hooks (executor list, settings) and
 * `ScorerParams` reaches it through a switch — a conditional hook call otherwise.
 */
function JudgeParams({
  index,
  p,
  onParams,
}: {
  index: number
  p: Record<string, never>
  onParams: (patch: Record<string, unknown>) => void
}) {
  const judge = judgeExecutorId(p.judge_executor)
  const selfJudging = useSelfJudging(p.judge_executor)
  const rubrics = useRubrics()

  return (
    <div className="flex flex-col gap-2">
      {/*
        The library existed on the server and had no way in. Starting from a
        saved rubric is how a judged comparison stays comparable: two scorers
        with subtly different wording are two different measurements.
      */}
      <Field label="Start from a saved rubric" htmlFor={`rubric-ref-${index}`}>
        <Select
          value={String(p.rubric_ref ?? 'inline')}
          onValueChange={(key) =>
            key === 'inline'
              ? onParams({ rubric_ref: undefined })
              : onParams({
                  rubric_ref: key,
                  rubric: rubrics.data?.find((r) => r.key === key)?.text ?? p.rubric,
                })
          }
        >
          <SelectTrigger id={`rubric-ref-${index}`} aria-label={`Scorer ${index + 1} rubric`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="inline">Write it here</SelectItem>
            {(rubrics.data ?? []).map((rubric) => (
              <SelectItem key={rubric.key} value={rubric.key}>
                {rubric.name}
                {rubric.builtin ? ' (built in)' : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field
        label="Rubric"
        hint={
          <>
            Describe what a passing answer must do, with an anchor per scale point.{' '}
            <GuideLink to="writing-rubrics">How to write one</GuideLink>
          </>
        }
        htmlFor={`rubric-${index}`}
      >
        <Textarea
          id={`rubric-${index}`}
          value={String(p.rubric ?? '')}
          onChange={(e) => onParams({ rubric: e.target.value, rubric_ref: undefined })}
          rows={4}
        />
      </Field>

      <Field
        label="Judge model"
        hint={
          <>
            Who grades. A judge is billed like any other call, and its cost shows in the run totals.{' '}
            <GuideLink to="judge-calibration">Calibration &amp; bias</GuideLink>
          </>
        }
      >
        <JudgeExecutorSelect
          value={judge}
          onChange={(next) => onParams({ judge_executor: next ?? undefined })}
          inheritLabel="Use the default judge (Settings)"
          ariaLabel={`Scorer ${index + 1} judge model`}
        />
      </Field>
      {selfJudging ? <SelfJudgeWarning /> : null}

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label>Scale</Label>
          <Select value={String(p.scale ?? '1-5')} onValueChange={(scale) => onParams({ scale })}>
            <SelectTrigger className="h-8 w-28" aria-label={`Scorer ${index + 1} scale`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {['binary', '1-5', '0-100'].map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Field label="Pass threshold" htmlFor={`threshold-${index}`}>
          <Input
            id={`threshold-${index}`}
            type="number"
            step={0.5}
            value={p.pass_threshold === undefined ? '' : String(p.pass_threshold)}
            onChange={(e) =>
              onParams({
                pass_threshold: e.target.value === '' ? undefined : Number(e.target.value),
              })
            }
            className="h-8 w-24"
          />
        </Field>
      </div>
    </div>
  )
}

/** JSON editing with live validation — invalid JSON never reaches the parent. */
function JsonField({
  label,
  id,
  value,
  onChange,
}: {
  label: string
  id: string
  value: unknown
  onChange: (parsed: unknown) => void
}) {
  const [text, setText] = React.useState(() => JSON.stringify(value ?? {}, null, 2))
  const [error, setError] = React.useState<string | null>(null)

  function handle(next: string) {
    setText(next)
    try {
      onChange(JSON.parse(next))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'invalid JSON')
    }
  }

  return (
    <Field label={label} htmlFor={id} error={error}>
      <Textarea
        id={id}
        value={text}
        onChange={(e) => handle(e.target.value)}
        rows={6}
        className={cn(error && 'border-[var(--destructive)]')}
        spellCheck={false}
      />
    </Field>
  )
}

/** Compact read-only summary used in tables and drill-downs. */
export function ScoringSummary({
  scoring,
  inherits = true,
}: {
  scoring: ScorerSpec[]
  /** False for a case no set holds — there is no default for it to inherit. */
  inherits?: boolean
}) {
  if (scoring.length === 0) {
    return (
      <span className="text-xs text-[var(--muted-foreground)]">
        {inherits ? 'set default' : 'none — in no set'}
      </span>
    )
  }
  return (
    <div className="flex flex-wrap gap-1">
      {scoring.map((s, i) => (
        <Badge key={i} variant={s.required ? 'primary' : 'outline'} title={SCORER_LABELS[s.type]}>
          {s.type}
        </Badge>
      ))}
    </div>
  )
}
