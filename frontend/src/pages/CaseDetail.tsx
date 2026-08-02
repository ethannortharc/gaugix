import { ArrowLeft, Copy, Pencil, RotateCcw, Trash2 } from 'lucide-react'
import * as React from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { useCase, useDeleteCase, useDuplicateCase, useRestoreCase } from '@/api/cases'
import { CaseEditorDialog } from '@/components/CaseEditorDialog'
import { PageHeader } from '@/components/layout/AppShell'
import { CaseRunHistory } from '@/components/RunHistory'
import { ScoringSummary } from '@/components/ScoringBuilder'
import { ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDateTime } from '@/lib/format'

export default function CaseDetailPage() {
  const params = useParams()
  const navigate = useNavigate()
  const caseId = Number(params.id)

  const [editing, setEditing] = React.useState(false)
  const query = useCase(caseId)
  const remove = useDeleteCase()
  const restore = useRestoreCase()
  const duplicate = useDuplicateCase()

  if (query.isLoading) return <LoadingState label="Loading case…" />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  if (!query.data) return null

  const item = query.data
  const trashed = item.deleted_at !== null

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <Button asChild variant="ghost" size="icon-sm" aria-label="Back">
              <Link to={item.sets[0] ? `/sets/${item.sets[0].id}` : '/sets'}>
                <ArrowLeft />
              </Link>
            </Button>
            {item.title}
            {trashed ? <Badge variant="error">in trash</Badge> : null}
          </span>
        }
        actions={
          trashed ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                restore.mutate(item.id, { onSuccess: () => toast.success('Restored') })
              }
            >
              <RotateCcw />
              Restore
            </Button>
          ) : (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  duplicate.mutate(
                    { id: item.id, setId: item.sets[0]?.id },
                    {
                      onSuccess: (copy) => {
                        toast.success('Duplicated')
                        navigate(`/cases/${copy.id}`)
                      },
                    },
                  )
                }
              >
                <Copy />
                Duplicate
              </Button>
              <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                <Pencil />
                Edit
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-[var(--destructive)]"
                onClick={() =>
                  remove.mutate(
                    { id: item.id },
                    {
                      onSuccess: () => {
                        toast.success('Moved to trash')
                        navigate(item.sets[0] ? `/sets/${item.sets[0].id}` : '/sets')
                      },
                    },
                  )
                }
              >
                <Trash2 />
                Delete
              </Button>
            </>
          )
        }
      >
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {item.tags.map((tag) => (
            <Badge key={tag}>{tag}</Badge>
          ))}
          {item.sets.map((set) => (
            <Link key={set.id} to={`/sets/${set.id}`}>
              <Badge variant="outline" className="cursor-pointer hover:border-[var(--primary)]">
                in {set.name}
              </Badge>
            </Link>
          ))}
        </div>
      </PageHeader>

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Input</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {item.input.map((message, index) => (
                <div key={index} className="rounded-md border border-[var(--border)]">
                  <div className="border-b border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)]">
                    {message.role}
                  </div>
                  <pre className="overflow-x-auto whitespace-pre-wrap break-words px-2.5 py-2 font-mono text-xs leading-relaxed">
                    {message.content}
                  </pre>
                </div>
              ))}
            </CardContent>
          </Card>

          {item.reference ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle>Reference</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="whitespace-pre-wrap text-sm">{item.reference}</p>
              </CardContent>
            </Card>
          ) : null}

          {item.notes ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle>Notes</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="whitespace-pre-wrap text-sm text-[var(--muted-foreground)]">
                  {item.notes}
                </p>
              </CardContent>
            </Card>
          ) : null}
        </div>

        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Scoring</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <ScoringSummary scoring={item.scoring} />
              {item.scoring.map((scorer, index) => (
                <div key={index} className="rounded-md border border-[var(--border)] p-2">
                  <div className="mb-1 flex items-center gap-1.5 text-xs">
                    <Badge variant={scorer.required ? 'primary' : 'outline'}>{scorer.type}</Badge>
                    <span className="text-[var(--muted-foreground)]">
                      {scorer.required ? 'required' : 'optional'} · weight {scorer.weight}
                    </span>
                  </div>
                  <pre className="overflow-x-auto rounded bg-[var(--muted)] p-1.5 font-mono text-[11px]">
                    {JSON.stringify(scorer.params, null, 2)}
                  </pre>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Metadata</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-1 text-xs text-[var(--muted-foreground)]">
              <div className="flex justify-between gap-2">
                <span>ID</span>
                <span className="tabular font-mono">{item.id}</span>
              </div>
              <div className="flex justify-between gap-2">
                <span>Created</span>
                <span>{formatDateTime(item.created_at)}</span>
              </div>
              <div className="flex justify-between gap-2">
                <span>Updated</span>
                <span>{formatDateTime(item.updated_at)}</span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="mt-4">
        <CaseRunHistory caseId={item.id} />
      </div>

      <CaseEditorDialog open={editing} onOpenChange={setEditing} caseData={item} />
    </>
  )
}
