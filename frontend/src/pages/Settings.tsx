import { Gavel, KeyRound, Plus, RefreshCw, Save, Trash2 } from 'lucide-react'
import * as React from 'react'
import { toast } from 'sonner'

import {
  useAppSettings,
  useDeleteRubric,
  usePullPricing,
  useRubrics,
  useSaveRubric,
  useUpdateAppSettings,
} from '@/api/runs'
import type { PricingEntry } from '@/api/types'
import { GuideLink } from '@/components/GuideLink'
import { JudgeExecutorSelect, SelfJudgeWarning } from '@/components/JudgeSelect'
import { PageHeader } from '@/components/layout/AppShell'
import { ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, Input, Textarea } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export default function SettingsPage() {
  const query = useAppSettings()
  const update = useUpdateAppSettings()
  const pull = usePullPricing()

  const [pricing, setPricing] = React.useState<PricingEntry[]>([])
  const [concurrency, setConcurrency] = React.useState(4)
  const [judgeId, setJudgeId] = React.useState<number | null>(null)
  const [dirty, setDirty] = React.useState(false)

  React.useEffect(() => {
    if (!query.data) return
    setPricing(query.data.pricing)
    setConcurrency(query.data.default_concurrency)
    setJudgeId(query.data.default_judge_executor_id)
    setDirty(false)
  }, [query.data])

  const settings = query.data

  function save() {
    update.mutate(
      { pricing, default_concurrency: concurrency, default_judge_executor_id: judgeId },
      {
        onSuccess: () => {
          toast.success('Settings saved')
          setDirty(false)
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  /** Editing a rate makes the row the user's, so a later pull leaves it alone. */
  function patch(index: number, changes: Partial<PricingEntry>) {
    setPricing((prev) =>
      prev.map((p, i) => (i === index ? { ...p, ...changes, source: 'manual' } : p)),
    )
    setDirty(true)
  }

  function pullPricing(refresh: boolean) {
    pull.mutate(
      { refresh },
      {
        onSuccess: (result) => {
          setPricing(result.settings.pricing)
          const filled = result.added.length + result.updated.length
          if (filled === 0 && result.not_found.length === 0) {
            toast.success('Every model already priced')
          } else if (filled === 0) {
            toast.warning(`litellm does not know ${result.not_found.join(', ')} — enter it by hand`)
          } else {
            toast.success(
              `Priced ${filled} ${filled === 1 ? 'model' : 'models'}` +
                (result.not_found.length ? ` · no rates for ${result.not_found.join(', ')}` : ''),
            )
          }
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  if (query.isError) {
    return (
      <>
        <PageHeader title="Settings" />
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Settings"
        description="Provider keys, model pricing and defaults."
        actions={
          <Button size="sm" onClick={save} disabled={!settings || !dirty || update.isPending}>
            <Save />
            {update.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        }
      />

      {!settings ? (
        <LoadingState label="Loading settings…" rows={4} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Provider keys</CardTitle>
              <CardDescription>
                Read from the environment at call time. Gaugix never stores a key in its database,
                logs it, or puts it in an exported report.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {settings.providers.map((provider) => (
                <div
                  key={provider.provider}
                  className="flex items-center justify-between gap-2 rounded-md border border-[var(--border)] px-2.5 py-2"
                >
                  <div className="flex min-w-0 flex-col">
                    <span className="text-sm font-medium">{provider.provider}</span>
                    <code className="font-mono text-[11px] text-[var(--muted-foreground)]">
                      {provider.env_var}
                    </code>
                  </div>
                  {provider.present ? (
                    <span className="flex items-center gap-1.5">
                      <code className="font-mono text-xs text-[var(--muted-foreground)]">
                        {provider.masked}
                      </code>
                      <Badge variant="pass" className="gap-1">
                        <KeyRound className="size-3" />
                        set
                      </Badge>
                    </span>
                  ) : (
                    <Badge variant="default">not set</Badge>
                  )}
                </div>
              ))}
              <p className="text-xs text-[var(--muted-foreground)]">
                To add one, put it in <code className="font-mono">.env</code> at the repo root and
                restart the server.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Defaults & paths</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <Field
                label="Default concurrency"
                hint="Pre-filled in the run builder. 1 runs serially."
                htmlFor="default-concurrency"
              >
                <Input
                  id="default-concurrency"
                  type="number"
                  min={1}
                  max={64}
                  value={concurrency}
                  onChange={(e) => {
                    setConcurrency(Math.max(1, Number(e.target.value)))
                    setDirty(true)
                  }}
                />
              </Field>
              <div className="flex flex-col gap-1 text-xs text-[var(--muted-foreground)]">
                <div className="flex justify-between gap-2">
                  <span>Per-provider cap</span>
                  <span className="tabular">{settings.provider_concurrency}</span>
                </div>
                <div className="flex justify-between gap-2">
                  <span>Data directory</span>
                  <code className="truncate font-mono">{settings.data_dir}</code>
                </div>
                <div className="flex justify-between gap-2">
                  <span>Database</span>
                  <code className="truncate font-mono">{settings.db_path}</code>
                </div>
                <div className="flex justify-between gap-2">
                  <span>Version</span>
                  <span className="tabular">{settings.version}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-1.5">
                <Gavel className="size-4 text-[var(--primary)]" />
                Default judge
              </CardTitle>
              <CardDescription>
                Which executor grades when an <code className="font-mono">llm_judge</code> scorer
                does not name one of its own. A judge is billed like any other call — its tokens and
                cost appear in the run totals.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="max-w-md">
                <JudgeExecutorSelect
                  value={judgeId}
                  onChange={(next) => {
                    setJudgeId(next)
                    setDirty(true)
                  }}
                  inheritLabel="None — each executor grades itself"
                  ariaLabel="Default judge executor"
                />
              </div>
              {judgeId === null ? (
                <SelfJudgeWarning className="max-w-2xl" />
              ) : (
                <p className="max-w-2xl text-xs text-[var(--muted-foreground)]">
                  Prefer a judge that is not competing in the comparison. Grading its own output is
                  the obvious bias; a judge that is also one of the models being ranked is the
                  subtle one. <GuideLink to="judge-calibration">Calibration &amp; bias</GuideLink>
                </p>
              )}
            </CardContent>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex flex-col gap-1">
                  <CardTitle>Pricing table</CardTitle>
                  <CardDescription>
                    USD per 1M tokens. Seeded from litellm’s bundled cost map when you add a model,
                    and used whenever litellm cannot price a call itself. Without an entry, cost
                    shows as “n/a” rather than a misleading zero — edit any row and it becomes
                    yours, safe from later pulls.
                  </CardDescription>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  disabled={pull.isPending}
                  onClick={() => pullPricing(false)}
                >
                  <RefreshCw className={pull.isPending ? 'animate-spin' : undefined} />
                  {pull.isPending ? 'Pulling…' : 'Pull from litellm'}
                </Button>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {pricing.length > 0 ? (
                <div className="overflow-hidden rounded-md border border-[var(--border)]">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Model id</TableHead>
                        <TableHead className="w-40">Input $ / 1M</TableHead>
                        <TableHead className="w-40">Output $ / 1M</TableHead>
                        <TableHead className="w-24">Source</TableHead>
                        <TableHead className="w-16" />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {pricing.map((entry, index) => (
                        <TableRow key={index}>
                          <TableCell>
                            <Input
                              value={entry.model_id}
                              onChange={(e) => patch(index, { model_id: e.target.value })}
                              className="h-8 font-mono text-xs"
                              aria-label={`Model id ${index + 1}`}
                            />
                          </TableCell>
                          <TableCell>
                            <Input
                              type="number"
                              step="0.01"
                              min="0"
                              value={entry.input_per_1m}
                              onChange={(e) =>
                                patch(index, { input_per_1m: Number(e.target.value) })
                              }
                              className="h-8"
                              aria-label={`Input rate ${index + 1}`}
                            />
                          </TableCell>
                          <TableCell>
                            <Input
                              type="number"
                              step="0.01"
                              min="0"
                              value={entry.output_per_1m}
                              onChange={(e) =>
                                patch(index, { output_per_1m: Number(e.target.value) })
                              }
                              className="h-8"
                              aria-label={`Output rate ${index + 1}`}
                            />
                          </TableCell>
                          <TableCell>
                            <Badge variant={entry.source === 'manual' ? 'primary' : 'outline'}>
                              {entry.source === 'manual' ? 'yours' : 'litellm'}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              onClick={() => {
                                setPricing((prev) => prev.filter((_, i) => i !== index))
                                setDirty(true)
                              }}
                              aria-label={`Remove pricing row ${index + 1}`}
                            >
                              <Trash2 />
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <p className="text-sm text-[var(--muted-foreground)]">
                  Nothing yet. Adding a model profile fills its rates in automatically, or pull for
                  every model at once.
                </p>
              )}

              <Button
                variant="outline"
                size="sm"
                className="self-start"
                onClick={() => {
                  setPricing((prev) => [
                    ...prev,
                    { model_id: '', input_per_1m: 0, output_per_1m: 0, source: 'manual' },
                  ])
                  setDirty(true)
                }}
              >
                <Plus />
                Add a model
              </Button>
            </CardContent>
          </Card>

          <RubricLibrary />
        </div>
      )}
    </>
  )
}

/**
 * Saved rubrics (PRD F4.5).
 *
 * The library existed on the server with no way to reach it, which mattered
 * more than it sounds: two judge scorers with subtly different wording are two
 * different measurements, and the only defence is writing the rubric once and
 * pointing at it. The scoring builder picks from this list.
 */
function RubricLibrary() {
  const rubrics = useRubrics()
  const save = useSaveRubric()
  const remove = useDeleteRubric()
  const [key, setKey] = React.useState('')
  const [text, setText] = React.useState('')

  const rows = rubrics.data ?? []

  function submit(event: React.FormEvent) {
    event.preventDefault()
    save.mutate(
      { key: key.trim(), text: text.trim() },
      {
        onSuccess: () => {
          toast.success(`Saved “${key.trim()}”`)
          setKey('')
          setText('')
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <Card className="lg:col-span-2">
      <CardHeader className="pb-2">
        <CardTitle>Rubric library</CardTitle>
        <CardDescription>
          Write a rubric once and point every judge scorer at it. Two scorers with slightly
          different wording are two different measurements, which is how a comparison stops
          comparing.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {rows.map((rubric) => (
          <div key={rubric.key} className="rounded-md border border-[var(--border)] p-3">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs font-medium">{rubric.key}</span>
              {rubric.builtin ? <Badge variant="outline">built in</Badge> : null}
              {!rubric.builtin ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto text-[var(--destructive)]"
                  disabled={remove.isPending}
                  onClick={() =>
                    remove.mutate(rubric.key, {
                      onSuccess: () => toast.success(`Deleted “${rubric.key}”`),
                      onError: (error) => toast.error(error.message),
                    })
                  }
                >
                  <Trash2 />
                  Delete
                </Button>
              ) : null}
            </div>
            <p className="whitespace-pre-wrap text-xs text-[var(--muted-foreground)]">
              {rubric.text}
            </p>
          </div>
        ))}

        <form
          onSubmit={submit}
          className="flex flex-col gap-2 border-t border-[var(--border)] pt-3"
        >
          <Field
            label="New rubric key"
            htmlFor="rubric-key"
            hint="Short and stable — scorers reference it by this name."
          >
            <Input
              id="rubric-key"
              value={key}
              onChange={(event) => setKey(event.target.value)}
              placeholder="tone-of-voice"
            />
          </Field>
          <Field label="Rubric text" htmlFor="rubric-text">
            <Textarea
              id="rubric-text"
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={4}
              className="font-sans text-sm"
            />
          </Field>
          <Button
            type="submit"
            size="sm"
            className="self-start"
            disabled={!key.trim() || !text.trim() || save.isPending}
          >
            <Plus />
            {save.isPending ? 'Saving…' : 'Save rubric'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
