import { Columns3 } from 'lucide-react'
import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { useArtifactCompare } from '@/api/artifacts'
import type { ArtifactSide, ArtifactRead } from '@/api/types'
import { ArtifactList, ArtifactViewer } from '@/components/ArtifactViewer'
import { PageHeader } from '@/components/layout/AppShell'
import { defaultRenderer, RENDERERS, type Renderer } from '@/lib/artifacts'
import { ItemStatusBadge, ScoreBadge } from '@/components/RunBits'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

/**
 * The same case across 2–4 executors, side by side (PRD F6.5).
 *
 * The renderer choice is **synchronised across panes** on purpose: comparing
 * one model's rendered HTML against another's source would flatter whichever
 * happened to be prettier. Same lens on both sides, or it is not a comparison.
 */

export default function SideBySidePage() {
  const [params] = useSearchParams()
  const itemIds = React.useMemo(
    () =>
      (params.get('items') ?? '')
        .split(',')
        .map(Number)
        .filter((value) => Number.isFinite(value) && value > 0),
    [params],
  )
  const [renderer, setRenderer] = React.useState<Renderer | 'auto'>('auto')
  const query = useArtifactCompare(itemIds)

  if (itemIds.length < 2) {
    return (
      <>
        <PageHeader title="Side by side" />
        <EmptyState
          icon={<Columns3 className="size-6" />}
          title="Pick two to four items"
          description="Open a run's matrix and choose the same case across executors, or add ?items=1,2 to this URL."
          action={<Link to="/compare?view=matrix">Go to the matrix</Link>}
        />
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Side by side"
        description="The same case across executors. One renderer for every pane, so nothing is flattered."
        actions={
          <Select value={renderer} onValueChange={(value) => setRenderer(value as Renderer)}>
            <SelectTrigger className="h-8 w-40" aria-label="Renderer">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">match each file</SelectItem>
              {RENDERERS.map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />

      {query.isLoading ? (
        <LoadingState label="Loading panes…" rows={4} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <div
          className="grid gap-4"
          style={{
            gridTemplateColumns: `repeat(${Math.min(query.data?.sides.length ?? 1, 4)}, minmax(0, 1fr))`,
          }}
        >
          {(query.data?.sides ?? []).map((side) => (
            <Pane key={side.item_id} side={side} renderer={renderer} />
          ))}
        </div>
      )}
    </>
  )
}

function Pane({ side, renderer }: { side: ArtifactSide; renderer: Renderer | 'auto' }) {
  const [selectedId, setSelectedId] = React.useState<number | null>(null)
  const selected: ArtifactRead | undefined =
    side.artifacts.find((a) => a.id === selectedId) ?? side.artifacts[0]

  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="font-mono text-[11px]">
          {side.executor_key}
        </Badge>
        <ItemStatusBadge status={side.status} verdict={side.verdict} needsHuman={false} />
        <ScoreBadge verdict={side.verdict} score={side.score_value} />
        <Link
          to={`/items/${side.item_id}`}
          className="ml-auto text-xs text-[var(--muted-foreground)] hover:underline"
        >
          open
        </Link>
      </div>

      <ArtifactList
        artifacts={side.artifacts}
        selectedId={selected?.id ?? null}
        onSelect={(artifact) => setSelectedId(artifact.id)}
      />

      {selected ? (
        <ArtifactViewer
          artifact={selected}
          renderer={renderer === 'auto' ? defaultRenderer(selected) : renderer}
        />
      ) : (
        <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap break-words rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-2 font-mono text-xs">
          {side.output_text || 'No output.'}
        </pre>
      )}
    </div>
  )
}
