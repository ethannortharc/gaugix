import { BadgeCheck, Database, FlaskConical } from 'lucide-react'

import type { BenchmarkMethod, SetProvenance } from '@/api/types'
import { Markdown } from '@/components/Markdown'
import { Badge } from '@/components/ui/badge'

/**
 * Whether a number from Gaugix is the benchmark's own number.
 *
 * The distinction this makes is the difference between "our model scores 71 on
 * MT-Bench" and "our model scores 71 on a first-turn-only variant of MT-Bench
 * graded by a model we chose". Both are useful; only one can be put next to a
 * published figure, and nothing else on the page tells them apart.
 */
export function MethodBadge({ method }: { method: BenchmarkMethod }) {
  const official = method.fidelity === 'official-compatible'
  return (
    <Badge
      variant={official ? 'primary' : 'human'}
      className="gap-1"
      title={
        official
          ? 'Reproduces the published scoring method, within the deviations listed on its page.'
          : 'Runs this benchmark’s data through a Gaugix method. Useful for comparing your own models; not a published score.'
      }
    >
      {official ? <BadgeCheck className="size-3" /> : <FlaskConical className="size-3" />}
      {official ? 'official method' : 'Gaugix adaptation'}
    </Badge>
  )
}

/** The same claim at full length, with every deviation spelled out. */
export function MethodPanel({ method }: { method: BenchmarkMethod }) {
  const official = method.fidelity === 'official-compatible'
  return (
    <div
      className={`flex flex-col gap-2 rounded-lg border p-3 ${
        official
          ? 'border-[var(--primary)]/40 bg-[var(--primary)]/8'
          : 'border-[var(--human)]/40 bg-[var(--human)]/10'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <MethodBadge method={method} />
        <span className="text-sm font-medium">
          {method.comparable
            ? 'Comparable with published scores'
            : 'Not comparable with published scores'}
        </span>
        <span className="ml-auto text-[11px] text-[var(--muted-foreground)]">
          method v{method.version}
        </span>
      </div>
      <p className="text-xs text-[var(--muted-foreground)]">
        {method.comparable
          ? 'Gaugix follows the published method, with the differences below. A number from it can reasonably sit next to one from the paper or a leaderboard.'
          : 'Gaugix runs this benchmark’s data through a method of its own. The number is meaningful for comparing your models against each other and must not be quoted as a benchmark result.'}
      </p>
      {/* Markdown, like the caveats list — these carry `code` spans and emphasis. */}
      <ul className="flex list-disc flex-col gap-1 pl-4 text-xs">
        {method.deviations.map((deviation, index) => (
          <li key={index}>
            <Markdown source={deviation} className="text-xs" />
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Which dataset a set actually holds.
 *
 * Provenance was being recorded at install and then never shown, which made it
 * unusable for the thing it exists for: proving, months later, which revision
 * of which benchmark a number came from. The `modified` line matters most —
 * a benchmark set someone has edited is a derived set, and it must stop
 * presenting itself as the benchmark (D-056).
 */
export function ProvenanceCard({ provenance }: { provenance: SetProvenance }) {
  if (!provenance.benchmark) return null

  const modified = provenance.modified === true
  const comparable = provenance.comparable_to_published === true
  // A set installed before provenance was recorded is neither an adaptation nor
  // a verified install — its method is simply unknown, and the badge fell
  // through to "Gaugix adaptation", which is a claim about a method nobody
  // recorded (D-066).
  const legacy = provenance.legacy === true

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="gap-1">
          <Database className="size-3" />
          {provenance.benchmark_name ?? provenance.benchmark}
        </Badge>
        {provenance.scope ? <Badge variant="default">{provenance.scope}</Badge> : null}
        {modified ? (
          <Badge variant="human" title={(provenance.modified_reasons ?? []).join(' ')}>
            modified since install
          </Badge>
        ) : null}
        <Badge variant={comparable && !modified && !legacy ? 'primary' : 'human'}>
          {modified
            ? 'derived — not the benchmark'
            : legacy
              ? 'installed before provenance was recorded'
              : comparable
                ? 'comparable with published scores'
                : 'Gaugix adaptation'}
        </Badge>
        {provenance.licence ? (
          <span className="text-[var(--muted-foreground)]">{provenance.licence}</span>
        ) : null}
      </div>

      {modified ? (
        <ul className="flex list-disc flex-col gap-0.5 pl-4 text-[var(--muted-foreground)]">
          {(provenance.modified_reasons ?? []).map((reason, index) => (
            <li key={index}>{reason}</li>
          ))}
          <li>
            Results from this set describe these cases, not the published benchmark. Reinstall it
            under a new name if you need the original back.
          </li>
        </ul>
      ) : null}

      {legacy ? (
        <p className="text-[var(--muted-foreground)]">
          This set came from the catalogue, but was installed before Gaugix recorded which revision
          and which scoring method it used — so results from it cannot be checked against published
          scores. Reinstall it from the catalogue to get a citable record.
        </p>
      ) : null}

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[var(--muted-foreground)]">
        {provenance.source_revision ? (
          <>
            <dt>revision</dt>
            <dd className="truncate font-mono">{provenance.source_revision}</dd>
          </>
        ) : null}
        {provenance.source_sha256 ? (
          <>
            <dt>sha256</dt>
            <dd className="truncate font-mono">{provenance.source_sha256}</dd>
          </>
        ) : null}
        <dt>method</dt>
        <dd>
          {legacy ? (
            'not recorded at install'
          ) : (
            <>
              {provenance.method_fidelity} v{provenance.method_version}
            </>
          )}
        </dd>
        {provenance.installed_at ? (
          <>
            <dt>installed</dt>
            <dd>
              {provenance.installed_at}
              {provenance.case_count !== undefined ? ` · ${provenance.case_count} cases` : ''}
              {provenance.sample_seed !== null && provenance.sample_seed !== undefined
                ? ` · seed ${provenance.sample_seed}`
                : ''}
            </dd>
          </>
        ) : null}
      </dl>
    </div>
  )
}
