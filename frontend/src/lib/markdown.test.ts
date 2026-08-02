import { describe, expect, it } from 'vitest'

import { parseMarkdown, slugify } from '@/lib/markdown'

describe('slugify', () => {
  it('makes a stable anchor from a heading', () => {
    expect(slugify('LLM-as-judge: calibration & bias')).toBe('llm-as-judge-calibration-bias')
    expect(slugify('  Spaced  Out  ')).toBe('spaced-out')
  })
})

describe('parseMarkdown', () => {
  it('reads headings at two levels', () => {
    const blocks = parseMarkdown('## Two\n\n### Three')
    expect(blocks).toEqual([
      { kind: 'heading', level: 2, text: 'Two' },
      { kind: 'heading', level: 3, text: 'Three' },
    ])
  })

  it('joins a wrapped paragraph into one block', () => {
    const blocks = parseMarkdown('A sentence that\nwraps across lines.')
    expect(blocks).toEqual([{ kind: 'paragraph', text: 'A sentence that wraps across lines.' }])
  })

  it('separates paragraphs on a blank line', () => {
    expect(parseMarkdown('One.\n\nTwo.')).toHaveLength(2)
  })

  it('reads bulleted and numbered lists', () => {
    const [bullets, numbers] = parseMarkdown('- a\n- b\n\n1. first\n2. second')
    expect(bullets).toEqual({ kind: 'list', ordered: false, items: ['a', 'b'] })
    expect(numbers).toEqual({ kind: 'list', ordered: true, items: ['first', 'second'] })
  })

  it('folds a wrapped list item back into its bullet', () => {
    const [list] = parseMarkdown('- a long item that\n  continues here\n- second')
    expect(list).toEqual({
      kind: 'list',
      ordered: false,
      items: ['a long item that continues here', 'second'],
    })
  })

  it('keeps fenced code verbatim, markdown and all', () => {
    const [block] = parseMarkdown('```python\n# not a heading\nx = 1\n```')
    expect(block).toEqual({ kind: 'code', language: 'python', text: '# not a heading\nx = 1' })
  })

  it('reads a table and drops its separator row', () => {
    const [table] = parseMarkdown('| A | B |\n|---|---|\n| 1 | 2 |')
    expect(table).toEqual({ kind: 'table', header: ['A', 'B'], rows: [['1', '2']] })
  })

  it('reads a blockquote', () => {
    const [quote] = parseMarkdown('> quoted line\n> and more')
    expect(quote).toEqual({ kind: 'quote', text: 'quoted line and more' })
  })

  it('handles an empty document', () => {
    expect(parseMarkdown('')).toEqual([])
    expect(parseMarkdown('\n\n  \n')).toEqual([])
  })
})
