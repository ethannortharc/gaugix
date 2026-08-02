import * as React from 'react'

/**
 * Markdown parsing for the eval guide (PRD F7.1).
 *
 * Hand-written rather than pulling in `marked` + `dompurify` (D-030): the input
 * is our own content, shipped in the wheel and never user-supplied, and the
 * subset the guide uses is small enough to implement in a page.
 *
 * It produces React elements — never raw HTML — so even if this were ever
 * pointed at untrusted text, the worst case is ugly output rather than injected
 * markup.
 *
 * Split out from `components/Markdown` so that file exports only components,
 * which is what Fast Refresh (and the lint rule) require.
 */

type Block =
  | { kind: 'heading'; level: 2 | 3; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'quote'; text: string }
  | { kind: 'code'; language: string | null; text: string }
  | { kind: 'table'; header: string[]; rows: string[][] }

export function slugify(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/[\s-]+/g, '-')
    .replace(/^-|-$/g, '')
}

export function parseMarkdown(source: string): Block[] {
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  const blocks: Block[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]

    if (!line.trim()) {
      index += 1
      continue
    }

    // Fenced code — consumed verbatim, so markdown inside it stays literal.
    const fence = line.match(/^```+\s*(\S*)/)
    if (fence) {
      const body: string[] = []
      index += 1
      while (index < lines.length && !/^```+\s*$/.test(lines[index])) {
        body.push(lines[index])
        index += 1
      }
      index += 1
      blocks.push({ kind: 'code', language: fence[1] || null, text: body.join('\n') })
      continue
    }

    const heading = line.match(/^(#{2,3})\s+(.*)$/)
    if (heading) {
      blocks.push({
        kind: 'heading',
        level: heading[1].length === 2 ? 2 : 3,
        text: heading[2].trim(),
      })
      index += 1
      continue
    }

    if (line.startsWith('> ')) {
      const body: string[] = []
      while (index < lines.length && lines[index].startsWith('>')) {
        body.push(lines[index].replace(/^>\s?/, ''))
        index += 1
      }
      blocks.push({ kind: 'quote', text: body.join(' ').trim() })
      continue
    }

    if (line.startsWith('|')) {
      const rows: string[][] = []
      while (index < lines.length && lines[index].startsWith('|')) {
        const cells = lines[index]
          .replace(/^\||\|$/g, '')
          .split('|')
          .map((cell) => cell.trim())
        // The `|---|---|` separator row carries no data.
        if (!cells.every((cell) => /^:?-{2,}:?$/.test(cell))) rows.push(cells)
        index += 1
      }
      if (rows.length) blocks.push({ kind: 'table', header: rows[0], rows: rows.slice(1) })
      continue
    }

    const bullet = line.match(/^\s*([-*]|\d+\.)\s+/)
    if (bullet) {
      const ordered = /\d/.test(bullet[1])
      const items: string[] = []
      while (index < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*([-*]|\d+\.)\s+/, ''))
        index += 1
        // A wrapped continuation line belongs to the item above it.
        while (index < lines.length && /^\s{2,}\S/.test(lines[index])) {
          items[items.length - 1] += ` ${lines[index].trim()}`
          index += 1
        }
      }
      blocks.push({ kind: 'list', ordered, items })
      continue
    }

    const paragraph: string[] = []
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^(#{2,3}\s|>\s|\||```)/.test(lines[index]) &&
      !/^\s*([-*]|\d+\.)\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index].trim())
      index += 1
    }
    blocks.push({ kind: 'paragraph', text: paragraph.join(' ') })
  }

  return blocks
}

/** Inline spans: `code`, **bold**, *italic*, [link](href). */
export function renderInline(text: string, keyPrefix = 'i'): React.ReactNode[] {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g
  const out: React.ReactNode[] = []
  let last = 0
  let match: RegExpExecArray | null
  let n = 0

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index))
    const token = match[0]
    const key = `${keyPrefix}-${n++}`

    if (token.startsWith('`')) {
      out.push(
        <code key={key} className="rounded bg-[var(--muted)] px-1 py-0.5 font-mono text-[0.875em]">
          {token.slice(1, -1)}
        </code>,
      )
    } else if (token.startsWith('**')) {
      out.push(<strong key={key}>{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('*')) {
      out.push(<em key={key}>{token.slice(1, -1)}</em>)
    } else {
      const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
      if (link) {
        const href = link[2]
        const internal = href.startsWith('/')
        out.push(
          <a
            key={key}
            href={href}
            className="text-[var(--primary)] underline underline-offset-2"
            {...(internal ? {} : { target: '_blank', rel: 'noreferrer noopener' })}
          >
            {link[1]}
          </a>,
        )
      } else {
        out.push(token)
      }
    }
    last = match.index + token.length
  }

  if (last < text.length) out.push(text.slice(last))
  return out
}
