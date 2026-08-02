import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Download,
  ExternalLink,
  FileText,
  Globe,
  Scale,
} from 'lucide-react'
import * as React from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { useBenchmark, useInstallBenchmark } from '@/api/benchmarks'
import type { ApiError } from '@/api/client'
import type { BenchmarkDetail, CaseIO, InstallScope } from '@/api/types'
import { MethodBadge, MethodPanel } from '@/components/BenchmarkBits'
import { PageHeader } from '@/components/layout/AppShell'
import { Markdown } from '@/components/Markdown'
import { ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/misc'
import { pluralize } from '@/lib/format'

/**
 * One benchmark, in enough depth to decide against it.
 *
 * The order is deliberate: what it measures, then what it does *not* tell you,
 * then how Gaugix scores it, then the sample cases, and only then the install
 * buttons. A benchmark you install without reading the caveats is a number you
 * will quote without them too.
 */
export default function BenchmarkDetailPage() {
  const { slug } = useParams<{ slug: string }>()
  const benchmark = useBenchmark(slug)
  const [scope, setScope] = React.useState<InstallScope | null>(null)

  if (benchmark.isLoading) {
    return (
      <>
        <PageHeader title="Benchmark" />
        <LoadingState label="Loading…" rows={4} />
      </>
    )
  }
  if (benchmark.isError || !benchmark.data) {
    return (
      <>
        <PageHeader title="Benchmark" />
        <ErrorState error={benchmark.error} onRetry={() => void benchmark.refetch()} />
      </>
    )
  }

  const entry = benchmark.data

  return (
    <>
      <PageHeader
        title={entry.name}
        description={`${entry.task} · ${entry.publisher}, ${entry.year}`}
        actions={
          <>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/benchmarks">
                <ArrowLeft />
                Library
              </Link>
            </Button>
            <Button variant="outline" size="sm" onClick={() => setScope('sample')}>
              Install {entry.sample_size} samples
            </Button>
            <Button size="sm" onClick={() => setScope('full')} disabled={!entry.source}>
              <Download />
              Install all {entry.full_size.toLocaleString()}
            </Button>
          </>
        }
      >
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <MethodBadge method={entry.method} />
          <Badge variant="outline">{entry.licence}</Badge>
          {entry.tags.map((tag) => (
            <Badge key={tag}>{tag}</Badge>
          ))}
        </div>
      </PageHeader>

      {entry.installed.length > 0 ? (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-md border border-[var(--pass)]/40 bg-[var(--pass)]/10 px-3 py-2 text-sm">
          <Check className="size-4 text-[var(--pass)]" />
          Already installed as
          {entry.installed.map((set) => (
            <Link key={set.id} to={`/sets/${set.id}`} className="font-medium hover:underline">
              {set.name} ({set.case_count})
            </Link>
          ))}
        </div>
      ) : null}

      {/*
        Above everything, including the description: whether a number from this
        is the benchmark's number. Read after the install, it is trivia; read
        before it, it decides what the result can be used for.
      */}
      <div className="mb-4">
        <MethodPanel method={entry.method} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle>What this is</CardTitle>
            </CardHeader>
            <CardContent>
              <Markdown source={entry.description} className="text-sm" />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle>What a score means</CardTitle>
            </CardHeader>
            <CardContent>
              <Markdown source={entry.what_it_measures} className="text-sm" />
            </CardContent>
          </Card>

          {/*
            The section this page exists for. Every benchmark here has a real
            reason to distrust it, and a library that hides them is helping you
            fool yourself.
          */}
          <Card className="border-[var(--error)]/40">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="size-4 text-[var(--error)]" />
                Before you quote a number from this
              </CardTitle>
              <CardDescription>
                {entry.caveats.length} {pluralize(entry.caveats.length, 'reason')} the score can
                mislead.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="flex flex-col gap-2.5">
                {entry.caveats.map((caveat, index) => (
                  <li key={index} className="flex gap-2 text-sm">
                    <span className="tabular mt-0.5 text-xs text-[var(--muted-foreground)]">
                      {index + 1}.
                    </span>
                    <Markdown source={caveat} className="text-sm" />
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle>How Gaugix scores it</CardTitle>
            </CardHeader>
            <CardContent>
              <Markdown source={entry.scoring_note} className="text-sm" />
            </CardContent>
          </Card>

          <SampleCases cases={entry.sample_cases} />
        </div>

        <FactsPanel entry={entry} />
      </div>

      <InstallDialog entry={entry} scope={scope} onClose={() => setScope(null)} />
    </>
  )
}

function FactsPanel({ entry }: { entry: BenchmarkDetail }) {
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle>Facts</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
          <Fact label="Cases" value={entry.full_size.toLocaleString()} />
          <Fact label="Bundled sample" value={String(entry.sample_size)} />
          <Fact label="Languages" value={entry.languages.join(', ')} />
          <Fact label="Licence" value={entry.licence} href={entry.licence_url} />
          <Fact label="Homepage" value="source repository" href={entry.homepage} />
          {entry.paper ? <Fact label="Paper" value="arXiv" href={entry.paper} /> : null}
          {/*
            Repository licence and dataset licence are not the same thing, and
            assuming they are is the commonest — and the only legal — trap here.
          */}
          {entry.licence_note ? (
            <p className="border-t border-[var(--border)] pt-2 text-xs text-[var(--muted-foreground)]">
              {entry.licence_note}
            </p>
          ) : null}
        </CardContent>
      </Card>

      {entry.source ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2">
              <Globe className="size-4" />
              The one request
            </CardTitle>
            <CardDescription>
              Installing the full set makes a single HTTPS GET to this address, and nothing else.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <code className="block overflow-x-auto rounded bg-[var(--muted)] px-2 py-1.5 font-mono text-[11px]">
              {entry.source.url}
            </code>
            <p className="text-xs text-[var(--muted-foreground)]">
              {entry.source.host} · about {(entry.source.approx_bytes / 1e6).toFixed(1)} MB · the
              bundled sample needs no network at all.
            </p>
            {/*
              A URL that tracks `main` quietly redefines the benchmark under
              you — TruthfulQA lost 27 questions that way. The revision and the
              checksum are what make "we ran this dataset" a checkable claim,
              and the install verifies both.
            */}
            <div className="flex flex-col gap-1 border-t border-[var(--border)] pt-2 text-[11px] text-[var(--muted-foreground)]">
              {entry.source.revision ? (
                <span>
                  Pinned to revision{' '}
                  <code className="font-mono">{entry.source.revision.slice(0, 12)}</code>
                </span>
              ) : (
                <span>No revision to pin — this host publishes none.</span>
              )}
              {entry.source.sha256 ? (
                <span>
                  Expects <code className="font-mono">{entry.source.sha256.slice(0, 12)}…</code> and{' '}
                  {entry.source.expected_rows.toLocaleString()} rows. An install that finds
                  something else stops and shows you the difference.
                </span>
              ) : null}
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}

function Fact({ label, value, href }: { label: string; value: string; href?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-xs text-[var(--muted-foreground)]">{label}</span>
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 text-right text-[var(--primary)] hover:underline"
        >
          {value}
          <ExternalLink className="size-3" />
        </a>
      ) : (
        <span className="text-right">{value}</span>
      )}
    </div>
  )
}

/** The real cases an install creates, built by the same adapter. */
function SampleCases({ cases }: { cases: CaseIO[] }) {
  const [open, setOpen] = React.useState(false)
  const shown = open ? cases : cases.slice(0, 1)

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2">
          <FileText className="size-4" />
          What a case looks like
        </CardTitle>
        <CardDescription>
          Built by the same adapter an install uses — this is exactly what lands in your set.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {shown.map((sample, index) => (
          <div
            key={index}
            className="flex flex-col gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-3"
          >
            <p className="text-xs font-medium">{sample.title}</p>
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-[var(--muted)] px-2 py-1.5 font-mono text-[11px]">
              {sample.input.map((m) => `${m.role}: ${m.content}`).join('\n\n')}
            </pre>
            {sample.reference ? (
              <p className="text-xs">
                <span className="text-[var(--muted-foreground)]">Expected: </span>
                <span className="font-mono">{sample.reference.slice(0, 200)}</span>
              </p>
            ) : null}
            <div className="flex flex-wrap gap-1.5">
              {(sample.scoring ?? []).map((scorer, i) => (
                <Badge key={i} variant="primary">
                  {scorer.type}
                </Badge>
              ))}
              {(sample.tags ?? []).map((tag) => (
                <Badge key={tag}>{tag}</Badge>
              ))}
            </div>
          </div>
        ))}
        {cases.length > 1 ? (
          <Button variant="ghost" size="sm" className="self-start" onClick={() => setOpen(!open)}>
            {open ? 'Show less' : `Show all ${cases.length} samples`}
          </Button>
        ) : null}
      </CardContent>
    </Card>
  )
}

function InstallDialog({
  entry,
  scope,
  onClose,
}: {
  entry: BenchmarkDetail
  scope: InstallScope | null
  onClose: () => void
}) {
  const navigate = useNavigate()
  const install = useInstallBenchmark()
  const [name, setName] = React.useState('')
  const [accepted, setAccepted] = React.useState(false)
  // "" means everything. A number caps the install, and because a benchmark's
  // file order is rarely arbitrary, the cap is drawn as a seeded random sample
  // rather than taken off the top of the file.
  const [limit, setLimit] = React.useState('')
  const [seed, setSeed] = React.useState('1')
  // What the server refused, when it refused for drift. The message told
  // people to resend with a flag they had no way to set (D-065).
  const [drift, setDrift] = React.useState<string[] | null>(null)

  React.useEffect(() => {
    if (scope) {
      setName(scope === 'sample' ? `${entry.name} (sample)` : entry.name)
      setAccepted(false)
      setLimit('')
      setSeed('1')
      setDrift(null)
    }
  }, [scope, entry.name])

  // The gate is the same one the API enforces: a benchmark whose scoring runs
  // model-written code cannot be installed by accident.
  const blocked = entry.requires_code_execution && !accepted
  const capped = scope === 'full' && Number(limit) > 0
  const count = capped ? Math.min(Number(limit), entry.full_size) : entry.full_size

  function run(acceptDrift = false) {
    if (!scope) return
    install.mutate(
      {
        slug: entry.slug,
        scope,
        set_name: name.trim() || null,
        limit: capped ? Number(limit) : null,
        sample_seed: capped && seed.trim() !== '' ? Number(seed) : null,
        accept_code_execution: accepted,
        accept_drift: acceptDrift,
      },
      {
        onSuccess: (result) => {
          toast.success(`Installed ${result.imported} ${pluralize(result.imported, 'case')}`)
          if (result.warnings.length > 0) {
            toast.warning(result.warnings[0], { duration: 12_000 })
          }
          onClose()
          navigate(`/sets/${result.set_id}`)
        },
        onError: (error) => {
          const details = (error as ApiError).details as { drift?: string[] } | undefined
          if (details?.drift?.length) setDrift(details.drift)
          else toast.error(error.message)
        },
      },
    )
  }

  return (
    <Dialog open={scope !== null} onOpenChange={(next) => (next ? undefined : onClose())}>
      <DialogContent widthClass="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            Install {entry.name} — {scope === 'full' ? 'full set' : 'sample'}
          </DialogTitle>
          <DialogDescription>
            {scope === 'full' && entry.source ? (
              <>
                This downloads {entry.full_size.toLocaleString()} cases from{' '}
                <strong>{entry.source.host}</strong> — the only outbound request Gaugix makes.
              </>
            ) : (
              <>
                This installs {entry.sample_size} cases bundled with Gaugix. No network, and the
                numbers are a smoke test rather than a result.
              </>
            )}
          </DialogDescription>
        </DialogHeader>

        {/*
          The server refuses a download that no longer matches the catalogue —
          its caveats, size and comparability all describe another version. The
          refusal used to arrive as a toast telling people to "resend with
          accept_drift=true", which is not something a page offers (D-065).
        */}
        {drift ? (
          <div className="flex flex-col gap-2 rounded-md border border-[var(--human)]/50 bg-[var(--human)]/10 px-3 py-2 text-xs">
            <span className="flex items-center gap-1.5 font-medium">
              <AlertTriangle className="size-3.5 shrink-0" />
              This is not the dataset this page describes
            </span>
            {drift.map((line, index) => (
              <span key={index} className="text-[var(--muted-foreground)]">
                {line}
              </span>
            ))}
            <span className="text-[var(--muted-foreground)]">
              Installing it anyway is fine — but its caveats, size and comparability on this page
              are about the older version, and the set will record what actually arrived.
            </span>
          </div>
        ) : null}

        <Field label="Set name" htmlFor="install-name">
          <Input id="install-name" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>

        {/*
          Between "five bundled cases" and "all 4,326" there was nothing, which
          made trying a large benchmark an all-or-nothing decision. A cap needs
          a seed to be a sample rather than a prefix: GSM8K's file is roughly
          ordered by difficulty and SimpleQA's clusters by topic, so the first
          hundred rows of either are not a hundred random cases.
        */}
        {scope === 'full' ? (
          <div className="grid gap-2 sm:grid-cols-2">
            <Field
              label="How many cases"
              hint={`Blank installs all ${entry.full_size.toLocaleString()}.`}
              htmlFor="install-limit"
            >
              <Input
                id="install-limit"
                type="number"
                min={1}
                max={entry.full_size}
                value={limit}
                placeholder="all"
                onChange={(e) => setLimit(e.target.value)}
              />
            </Field>
            <Field
              label="Sample seed"
              hint="Same seed, same cases. Clear it to take them in file order instead."
              htmlFor="install-seed"
            >
              <Input
                id="install-seed"
                type="number"
                min={0}
                value={seed}
                disabled={!capped}
                onChange={(e) => setSeed(e.target.value)}
              />
            </Field>
            {capped ? (
              <p className="col-span-full text-xs text-[var(--muted-foreground)]">
                Installing {count.toLocaleString()} of {entry.full_size.toLocaleString()} cases
                {seed.trim() !== ''
                  ? `, drawn at random with seed ${seed}. A score over them is an estimate of the full set's, not the full set's.`
                  : ' — the first ones in the file, which is not a random sample.'}
              </p>
            ) : null}
          </div>
        ) : null}

        {entry.requires_judge ? (
          <p className="flex items-start gap-2 rounded-md border border-[var(--human)]/40 bg-[var(--human)]/10 px-3 py-2 text-xs">
            <Scale className="mt-0.5 size-3.5 shrink-0" />
            <span>
              Every case here is graded by a judge model, so each run costs money. Set a default
              judge on{' '}
              <Link to="/settings" className="underline">
                Settings
              </Link>{' '}
              first, or the model under test will grade its own work.
            </span>
          </p>
        ) : null}

        {entry.requires_code_execution ? (
          <label className="flex cursor-pointer items-start gap-2 rounded-md border border-[var(--error)]/50 bg-[var(--error)]/10 px-3 py-2 text-xs">
            <Checkbox
              checked={accepted}
              onCheckedChange={(checked) => setAccepted(checked === true)}
              aria-label="Accept code execution"
              className="mt-0.5"
            />
            <span>
              <strong>Scoring this benchmark runs code the model wrote, on this machine.</strong>{' '}
              Gaugix has no sandbox: that code can read and write your files and reach the network.
              Tick this only if you accept that.
            </span>
          </label>
        ) : null}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => run(drift !== null)}
            disabled={blocked || install.isPending || !name.trim()}
          >
            {install.isPending ? 'Installing…' : drift ? 'Install the changed dataset' : 'Install'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
