import { Download, FileCode2, FileText, Image as ImageIcon, Play, ShieldAlert } from 'lucide-react'
import * as React from 'react'

import {
  artifactContentUrl,
  useArtifactContent,
  useExecArtifact,
  useExecPlan,
} from '@/api/artifacts'
import type { ArtifactRead } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { LoadingState } from '@/components/states'
import { defaultRenderer, type Renderer } from '@/lib/artifacts'
import { formatBytes } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * Rendering a file a model wrote (PRD F6.2).
 *
 * The HTML case is the one with teeth. A generated page rendered on this origin
 * could read the app's state and call its API, so it goes in an iframe with
 * `sandbox="allow-scripts"` and **no** `allow-same-origin` — which makes its
 * origin opaque, so it cannot reach anything of ours. The content also arrives
 * as inert `text/plain` from the server (D-028), so this is the second lock,
 * not the only one.
 */

function artifactIcon(artifact: ArtifactRead) {
  if (artifact.mime.startsWith('image/')) return <ImageIcon className="size-3.5" />
  if (artifact.kind === 'code_block') return <FileCode2 className="size-3.5" />
  return <FileText className="size-3.5" />
}

export function ArtifactViewer({
  artifact,
  renderer,
  className,
}: {
  artifact: ArtifactRead
  renderer?: Renderer
  className?: string
}) {
  const mode = renderer ?? defaultRenderer(artifact)
  const wantsText = artifact.textual && mode !== 'image'
  const content = useArtifactContent(wantsText ? artifact.id : undefined)

  if (mode === 'image') {
    return (
      <img
        src={artifactContentUrl(artifact.id)}
        alt={artifact.filename}
        className={cn(
          'max-h-[520px] max-w-full rounded-md border border-[var(--border)]',
          className,
        )}
      />
    )
  }

  if (!artifact.textual) {
    return (
      <div className="flex flex-col items-start gap-2 rounded-md border border-[var(--border)] px-3 py-4">
        <p className="text-sm text-[var(--muted-foreground)]">
          {artifact.filename} is {formatBytes(artifact.size_bytes)} of{' '}
          <code className="font-mono">{artifact.mime}</code> — nothing useful to show inline.
        </p>
        <Button asChild size="sm" variant="outline">
          <a href={artifactContentUrl(artifact.id, true)} download={artifact.filename}>
            <Download />
            Download
          </a>
        </Button>
      </div>
    )
  }

  if (content.isLoading) return <LoadingState label="Loading file…" rows={3} />
  if (content.isError) {
    return (
      <p className="rounded-md border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 px-3 py-2 text-sm">
        Could not read {artifact.filename}: {content.error.message}
      </p>
    )
  }

  const text = content.data ?? ''

  if (mode === 'html') {
    return <SandboxedHtml html={text} className={className} />
  }

  return (
    <pre
      className={cn(
        'max-h-[520px] overflow-auto whitespace-pre-wrap break-words rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-2 font-mono text-xs leading-relaxed',
        className,
      )}
    >
      {text}
    </pre>
  )
}

/**
 * A model-authored page, rendered where it cannot touch anything.
 *
 * `srcDoc` + `sandbox="allow-scripts"` without `allow-same-origin` gives the
 * frame an opaque origin: no access to our cookies, storage, DOM or API. Adding
 * `allow-same-origin` here would undo the whole protection, which is why it is
 * called out rather than left to be noticed.
 */
function SandboxedHtml({ html, className }: { html: string; className?: string }) {
  const [confirmed, setConfirmed] = React.useState(false)

  if (!confirmed) {
    return (
      <div className="flex flex-col items-start gap-2 rounded-md border border-[var(--error)]/40 bg-[var(--error)]/10 px-3 py-3">
        <p className="flex items-start gap-1.5 text-xs">
          <ShieldAlert className="mt-px size-3.5 shrink-0 text-[var(--error)]" />
          <span>
            This page was written by a model. Rendering it runs its scripts — sandboxed, with no
            access to Gaugix or your data, but still its code.
          </span>
        </p>
        <Button size="sm" variant="outline" onClick={() => setConfirmed(true)}>
          Render it
        </Button>
      </div>
    )
  }

  return (
    <iframe
      title="Generated page"
      srcDoc={html}
      // No allow-same-origin, deliberately — see the docstring above.
      sandbox="allow-scripts"
      className={cn(
        'h-[520px] w-full rounded-md border border-[var(--border)] bg-white',
        className,
      )}
    />
  )
}

/** The file list beside a viewer — grouped, because kinds mean different things. */
export function ArtifactList({
  artifacts,
  selectedId,
  onSelect,
}: {
  artifacts: ArtifactRead[]
  selectedId: number | null
  onSelect: (artifact: ArtifactRead) => void
}) {
  if (artifacts.length === 0) {
    return (
      <p className="text-xs text-[var(--muted-foreground)]">
        No artifacts — this attempt produced no output to store.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      {artifacts.map((artifact) => (
        <button
          key={artifact.id}
          type="button"
          onClick={() => onSelect(artifact)}
          aria-pressed={artifact.id === selectedId}
          className={cn(
            'flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors',
            artifact.id === selectedId
              ? 'bg-[var(--accent)] text-[var(--accent-foreground)]'
              : 'hover:bg-[var(--muted)]',
          )}
        >
          {artifactIcon(artifact)}
          <span className="min-w-0 flex-1 truncate font-mono">{artifact.filename}</span>
          <Badge variant="outline" className="shrink-0 text-[10px]">
            {artifact.kind === 'raw_output'
              ? 'output'
              : artifact.kind === 'code_block'
                ? (artifact.language ?? 'code')
                : 'file'}
          </Badge>
          <span className="tabular shrink-0 text-[10px] text-[var(--muted-foreground)]">
            {formatBytes(artifact.size_bytes)}
          </span>
        </button>
      ))}
    </div>
  )
}

/**
 * The run control (PRD F6.4).
 *
 * Two clicks by construction: the first fetches the plan and shows the exact
 * command, the second sends that plan's token back. There is no code path that
 * starts a process from a single click, and the copy does not claim a sandbox
 * that does not exist.
 */
export function RunArtifact({ artifact }: { artifact: ArtifactRead }) {
  const [asked, setAsked] = React.useState(false)
  const plan = useExecPlan(artifact.id, asked)
  const run = useExecArtifact()

  if (!asked) {
    return (
      <Button size="sm" variant="outline" onClick={() => setAsked(true)}>
        <Play />
        Run this file
      </Button>
    )
  }

  if (plan.isLoading) return <LoadingState label="Working out what would run…" rows={1} />
  if (plan.isError) {
    return (
      <p className="rounded-md border border-[var(--border)] px-3 py-2 text-xs text-[var(--muted-foreground)]">
        {plan.error.message}
      </p>
    )
  }
  if (!plan.data) return null

  return (
    <div className="flex flex-col gap-2 rounded-md border border-[var(--error)]/50 bg-[var(--error)]/10 px-3 py-3">
      <p className="flex items-start gap-1.5 text-xs">
        <ShieldAlert className="mt-px size-3.5 shrink-0 text-[var(--error)]" />
        <span>{plan.data.warning}</span>
      </p>
      <pre className="overflow-x-auto rounded bg-[var(--surface-2)] px-2 py-1.5 font-mono text-[11px]">
        {plan.data.command}
      </pre>
      <p className="text-[11px] text-[var(--muted-foreground)]">
        in {plan.data.workdir} · killed after {plan.data.timeout_s}s
      </p>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="destructive"
          disabled={run.isPending}
          onClick={() => run.mutate({ artifactId: artifact.id, token: plan.data.confirm_token })}
        >
          {run.isPending ? 'Running…' : 'I have read it — run it'}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setAsked(false)}>
          Cancel
        </Button>
      </div>
      {run.data ? (
        <div className="flex flex-col gap-1">
          <span className="text-[11px] text-[var(--muted-foreground)]">
            exit {run.data.exit_code} · {run.data.duration_ms} ms
            {run.data.timed_out ? ' · timed out' : ''}
          </span>
          {run.data.stdout ? (
            <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded bg-[var(--surface-2)] px-2 py-1.5 font-mono text-[11px]">
              {run.data.stdout}
            </pre>
          ) : null}
          {run.data.stderr ? (
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-[var(--destructive)]/10 px-2 py-1.5 font-mono text-[11px] text-[var(--destructive)]">
              {run.data.stderr}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
