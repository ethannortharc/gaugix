import { History } from 'lucide-react'
import { Link } from 'react-router-dom'

import { RUN_HISTORY_MAX_LIMIT, useCaseRunHistory, useSetRunHistory } from '@/api/runs'
import { ItemStatusBadge, RunStatusBadge, ScoreBadge } from '@/components/RunBits'
import { LoadMore, TruncatedNotice } from '@/components/LoadMore'
import { ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatCost, formatRelative, pluralize, truncate } from '@/lib/format'
import { usePagedLimit } from '@/lib/paging'

const HISTORY_PAGE_SIZE = 10

export function SetRunHistory({ setId }: { setId: number }) {
  const { limit, more } = usePagedLimit(HISTORY_PAGE_SIZE, RUN_HISTORY_MAX_LIMIT)
  const query = useSetRunHistory(setId, limit)
  const rows = query.data?.items ?? []

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2">
          <History className="size-4" />
          Run history
        </CardTitle>
        <p className="text-xs text-[var(--muted-foreground)]">
          Results are scoped to this set. Partial runs stay visibly separate from full benchmark
          runs.
        </p>
      </CardHeader>
      <CardContent>
        {query.isLoading ? (
          <LoadingState label="Loading run history…" rows={2} />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : rows.length === 0 ? (
          <p className="py-3 text-sm text-[var(--muted-foreground)]">
            This set has not been run yet.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Run</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Coverage</TableHead>
                  <TableHead>Executors</TableHead>
                  <TableHead>Result</TableHead>
                  <TableHead>When</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.run_id}>
                    <TableCell>
                      <Link
                        to={`/runs/${row.run_id}`}
                        className="font-medium hover:text-[var(--primary)] hover:underline"
                      >
                        {row.run_name}
                      </Link>
                      <div className="mt-0.5 flex gap-1">
                        {row.is_baseline ? <Badge variant="primary">baseline</Badge> : null}
                        <span className="text-[11px] text-[var(--muted-foreground)]">
                          {row.item_count} {pluralize(row.item_count, 'item')}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <RunStatusBadge status={row.status} />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        <Badge variant={row.is_partial ? 'human' : 'outline'}>
                          {row.is_partial ? 'partial' : 'full'}
                        </Badge>
                        <span className="whitespace-nowrap text-xs">{row.coverage}</span>
                      </div>
                    </TableCell>
                    <TableCell
                      className="max-w-48 truncate text-xs"
                      title={row.executor_keys.join('\n')}
                    >
                      {row.executor_keys.length === 1
                        ? row.executor_keys[0]
                        : `${row.executor_keys.length} executors`}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs">
                      {row.pass_rate === null ? (
                        <span className="text-[var(--muted-foreground)]">unscored</span>
                      ) : (
                        <>
                          <span className="tabular font-medium">{row.pass_rate}%</span>
                          <span className="ml-1 text-[var(--muted-foreground)]">
                            {row.passed}/{row.scored} passed
                          </span>
                        </>
                      )}
                      {row.unscored > 0 ? (
                        <div className="text-[11px] text-[var(--muted-foreground)]">
                          {row.unscored} unscored
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-[var(--muted-foreground)]">
                      {formatRelative(row.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <HistoryFooter
              shown={rows.length}
              total={query.data?.total ?? rows.length}
              noun="run"
              limit={limit}
              onMore={more}
              busy={query.isFetching}
            />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function CaseRunHistory({ caseId }: { caseId: number }) {
  const { limit, more } = usePagedLimit(HISTORY_PAGE_SIZE, RUN_HISTORY_MAX_LIMIT)
  const query = useCaseRunHistory(caseId, limit)
  const rows = query.data?.items ?? []

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2">
          <History className="size-4" />
          Run history
        </CardTitle>
        <p className="text-xs text-[var(--muted-foreground)]">
          One row per executor and set context. Open a row for its frozen input, output, attempts,
          and score audit.
        </p>
      </CardHeader>
      <CardContent>
        {query.isLoading ? (
          <LoadingState label="Loading run history…" rows={2} />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : rows.length === 0 ? (
          <p className="py-3 text-sm text-[var(--muted-foreground)]">
            This case has not been run yet.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Run</TableHead>
                  <TableHead>Executor</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Result</TableHead>
                  <TableHead>Output</TableHead>
                  <TableHead>When</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.item_id}>
                    <TableCell>
                      <Link
                        to={`/items/${row.item_id}`}
                        className="font-medium hover:text-[var(--primary)] hover:underline"
                      >
                        {row.run_name}
                      </Link>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1">
                        <RunStatusBadge status={row.run_status} />
                        {row.set_id ? (
                          <Link to={`/sets/${row.set_id}`} className="text-[11px] hover:underline">
                            {row.set_name}
                          </Link>
                        ) : (
                          <span className="text-[11px]">{row.set_name}</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="max-w-52 text-xs">
                      <div className="truncate" title={row.executor_key}>
                        {row.executor_key}
                      </div>
                      <div className="text-[11px] text-[var(--muted-foreground)]">
                        {row.latency_ms === null ? 'latency unknown' : `${row.latency_ms} ms`} ·{' '}
                        {row.cost_usd === null ? 'cost unknown' : formatCost(row.cost_usd)}
                      </div>
                    </TableCell>
                    <TableCell>
                      <ItemStatusBadge
                        status={row.item_status}
                        verdict={row.verdict}
                        needsHuman={row.needs_human}
                      />
                    </TableCell>
                    <TableCell>
                      <ScoreBadge verdict={row.verdict} score={row.score_value} />
                    </TableCell>
                    <TableCell
                      className="max-w-80 text-xs text-[var(--muted-foreground)]"
                      title={row.error ?? row.output_preview ?? undefined}
                    >
                      {row.error ? (
                        <span className="text-[var(--destructive)]">
                          {truncate(row.error, 100)}
                        </span>
                      ) : row.output_preview ? (
                        truncate(row.output_preview, 100)
                      ) : (
                        '—'
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-[var(--muted-foreground)]">
                      {formatRelative(row.run_created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <HistoryFooter
              shown={rows.length}
              total={query.data?.total ?? rows.length}
              noun="result"
              limit={limit}
              onMore={more}
              busy={query.isFetching}
            />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function HistoryFooter({
  shown,
  total,
  noun,
  limit,
  onMore,
  busy,
}: {
  shown: number
  total: number
  noun: string
  limit: number
  onMore: () => void
  busy: boolean
}) {
  if (total > shown && limit >= RUN_HISTORY_MAX_LIMIT) {
    return (
      <div className="py-2">
        <TruncatedNotice
          shown={shown}
          total={total}
          noun={noun}
          hint="Older history remains available through the paginated API."
        />
      </div>
    )
  }
  return (
    <LoadMore
      shown={shown}
      total={total}
      noun={noun}
      onMore={onMore}
      busy={busy}
      step={HISTORY_PAGE_SIZE}
    />
  )
}
