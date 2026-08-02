import { PlayCircle, Plus, RotateCw } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { useRerunWholeRun, useRuns } from '@/api/runs'
import { PageHeader } from '@/components/layout/AppShell'
import { RunStatusBadge } from '@/components/RunBits'
import { LoadMore } from '@/components/LoadMore'
import { usePagedLimit } from '@/lib/paging'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatCost, formatRelative, formatTokens, pluralize } from '@/lib/format'

export default function RunsPage() {
  const navigate = useNavigate()
  const rerun = useRerunWholeRun()
  const { limit, more } = usePagedLimit()
  const query = useRuns({ limit })
  const runs = query.data?.items ?? []

  return (
    <>
      <PageHeader
        title="Runs"
        description="Every execution, with its frozen config and totals."
        actions={
          <Button asChild size="sm">
            <Link to="/runs/new">
              <Plus />
              New run
            </Link>
          </Button>
        }
      />

      {query.isLoading ? (
        <LoadingState label="Loading runs…" rows={5} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : runs.length === 0 ? (
        <EmptyState
          icon={<PlayCircle className="size-6" />}
          title="No runs yet"
          description="A run executes every chosen set against every chosen executor. Start with a fake executor — it costs nothing and behaves deterministically."
          action={
            <Button asChild size="sm">
              <Link to="/runs/new">
                <Plus />
                Start a run
              </Link>
            </Button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Run</TableHead>
                <TableHead className="w-32">Status</TableHead>
                <TableHead className="w-24">Items</TableHead>
                <TableHead className="w-32">Pass rate</TableHead>
                <TableHead className="w-24">Tokens</TableHead>
                <TableHead className="w-24">Cost</TableHead>
                <TableHead className="w-32">When</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((run) => {
                const rate =
                  run.totals.scored > 0 ? run.totals.verdict_passed / run.totals.scored : null
                return (
                  <TableRow key={run.id}>
                    <TableCell>
                      <Link
                        to={`/runs/${run.id}`}
                        className="font-medium hover:text-[var(--primary)] hover:underline"
                      >
                        {run.name}
                      </Link>
                      <div className="flex flex-wrap items-center gap-1 pt-0.5">
                        {run.is_baseline_for.length > 0 ? (
                          <Badge variant="primary">baseline</Badge>
                        ) : null}
                        {run.parent_run_id ? (
                          <Badge variant="outline">rerun of #{run.parent_run_id}</Badge>
                        ) : null}
                        <span className="text-[11px] text-[var(--muted-foreground)]">
                          {run.config.executors?.length ?? 0}{' '}
                          {pluralize(run.config.executors?.length ?? 0, 'executor')}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <RunStatusBadge status={run.status} />
                    </TableCell>
                    <TableCell className="tabular text-sm">{run.totals.items}</TableCell>
                    <TableCell className="tabular text-sm">
                      {rate === null ? (
                        <span className="text-[var(--muted-foreground)]">—</span>
                      ) : (
                        `${Math.round(rate * 100)}%`
                      )}
                    </TableCell>
                    <TableCell className="tabular text-sm">
                      {formatTokens(run.totals.prompt_tokens + run.totals.completion_tokens)}
                    </TableCell>
                    <TableCell className="tabular text-sm">
                      {run.totals.cost_unknown ? '≥ ' : ''}
                      {formatCost(run.totals.cost_usd)}
                    </TableCell>
                    <TableCell className="text-xs text-[var(--muted-foreground)]">
                      {formatRelative(run.created_at)}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Rerun ${run.name}`}
                        title="Start a fresh run with the same sets and executors"
                        disabled={run.is_active || rerun.isPending}
                        onClick={() =>
                          rerun.mutate(run.id, {
                            onSuccess: (child) => {
                              toast.success('Rerun started')
                              navigate(`/runs/${child.id}`)
                            },
                            onError: (e) => toast.error(e.message),
                          })
                        }
                      >
                        <RotateCw />
                      </Button>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
          <LoadMore
            shown={runs.length}
            total={query.data?.total ?? runs.length}
            noun="run"
            onMore={more}
            busy={query.isFetching}
          />
        </div>
      )}
    </>
  )
}
