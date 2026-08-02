import * as React from 'react'

import { parseMarkdown, renderInline, slugify } from '@/lib/markdown'
import { cn } from '@/lib/utils'

/**
 * A markdown renderer for the eval guide (PRD F7.1).
 *
 * Hand-written rather than pulling in `marked` + `dompurify`, for two reasons:
 * the input is **our own content**, shipped in the wheel and never user-supplied,
 * so the sanitiser those libraries exist to justify has nothing to defend
 * against; and the subset the guide uses is small enough to implement in a page.
 *
 * It renders React elements, never `dangerouslySetInnerHTML` — so even if this
 * were ever pointed at untrusted text, the worst case is ugly output rather than
 * injected markup. If the guide ever needs footnotes or nested lists, add them
 * here or reconsider the dependency; do not reach for innerHTML.
 */

export function Markdown({ source, className }: { source: string; className?: string }) {
  const blocks = React.useMemo(() => parseMarkdown(source), [source])

  return (
    <div className={cn('flex flex-col gap-4 text-[15px] leading-relaxed', className)}>
      {blocks.map((block, index) => {
        switch (block.kind) {
          case 'heading': {
            const anchor = slugify(block.text)
            return block.level === 2 ? (
              <h2
                key={index}
                id={anchor}
                className="mt-4 scroll-mt-20 text-lg font-semibold tracking-tight"
              >
                {renderInline(block.text, `h${index}`)}
              </h2>
            ) : (
              <h3 key={index} id={anchor} className="mt-2 scroll-mt-20 text-base font-semibold">
                {renderInline(block.text, `h${index}`)}
              </h3>
            )
          }
          case 'paragraph':
            return <p key={index}>{renderInline(block.text, `p${index}`)}</p>
          case 'list':
            return block.ordered ? (
              <ol key={index} className="flex list-decimal flex-col gap-1.5 pl-5">
                {block.items.map((item, i) => (
                  <li key={i}>{renderInline(item, `l${index}-${i}`)}</li>
                ))}
              </ol>
            ) : (
              <ul key={index} className="flex list-disc flex-col gap-1.5 pl-5">
                {block.items.map((item, i) => (
                  <li key={i}>{renderInline(item, `l${index}-${i}`)}</li>
                ))}
              </ul>
            )
          case 'quote':
            return (
              <blockquote
                key={index}
                className="border-l-2 border-[var(--primary)] pl-3 text-[var(--muted-foreground)]"
              >
                {renderInline(block.text, `q${index}`)}
              </blockquote>
            )
          case 'code':
            return (
              <pre
                key={index}
                className="overflow-x-auto rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 font-mono text-xs leading-relaxed"
              >
                {block.text}
              </pre>
            )
          case 'table':
            return (
              <div key={index} className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr>
                      {block.header.map((cell, i) => (
                        <th
                          key={i}
                          className="border-b border-[var(--border)] px-2 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]"
                        >
                          {renderInline(cell, `th${index}-${i}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, r) => (
                      <tr key={r}>
                        {row.map((cell, c) => (
                          <td
                            key={c}
                            className="border-b border-[var(--border)] px-2 py-1.5 align-top"
                          >
                            {renderInline(cell, `td${index}-${r}-${c}`)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
        }
      })}
    </div>
  )
}
