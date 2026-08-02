import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ArtifactRead } from '@/api/types'
import { AppProviders } from '@/app/providers'
import { ArtifactList, ArtifactViewer } from '@/components/ArtifactViewer'
import { defaultRenderer } from '@/lib/artifacts'
import { testQueryClient } from '@/test/utils'

function artifact(overrides: Partial<ArtifactRead> = {}): ArtifactRead {
  return {
    id: 1,
    attempt_id: 1,
    kind: 'code_block',
    filename: 'block-1.py',
    mime: 'text/x-python',
    size_bytes: 24,
    sha256: 'abc',
    language: 'python',
    block_index: 0,
    textual: true,
    created_at: new Date(0).toISOString(),
    ...overrides,
  }
}

function stubContent(text: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(text, { status: 200 })),
  )
}

beforeEach(() => stubContent('print(1)'))

function show(a: ArtifactRead, renderer?: 'text' | 'markdown' | 'html' | 'image') {
  return render(
    <AppProviders client={testQueryClient()}>
      <ArtifactViewer artifact={a} renderer={renderer} />
    </AppProviders>,
  )
}

describe('defaultRenderer', () => {
  it('picks a renderer from the mime type', () => {
    expect(defaultRenderer(artifact({ mime: 'image/png' }))).toBe('image')
    expect(defaultRenderer(artifact({ mime: 'text/html' }))).toBe('html')
    expect(defaultRenderer(artifact({ mime: 'text/markdown' }))).toBe('markdown')
    expect(defaultRenderer(artifact({ mime: 'text/x-python' }))).toBe('text')
  })
})

describe('ArtifactViewer', () => {
  it('shows a text artifact inline', async () => {
    show(artifact())
    expect(await screen.findByText('print(1)')).toBeInTheDocument()
  })

  it('offers a download instead of inlining a binary', () => {
    show(artifact({ textual: false, mime: 'application/octet-stream', filename: 'a.bin' }))
    expect(screen.getByRole('link', { name: /download/i })).toBeInTheDocument()
    expect(screen.getByText(/nothing useful to show inline/i)).toBeInTheDocument()
  })

  it('does not render generated HTML until you say so', async () => {
    stubContent('<h1>hi</h1><script>alert(1)</script>')
    show(artifact({ mime: 'text/html', filename: 'page.html' }))

    expect(await screen.findByText(/written by a model/i)).toBeInTheDocument()
    expect(document.querySelector('iframe')).toBeNull()
  })

  it('sandboxes the iframe without same-origin once confirmed', async () => {
    const user = userEvent.setup()
    stubContent('<h1>hi</h1>')
    show(artifact({ mime: 'text/html', filename: 'page.html' }))

    await user.click(await screen.findByRole('button', { name: /render it/i }))

    const frame = document.querySelector('iframe')
    expect(frame).not.toBeNull()
    // allow-same-origin would undo the whole protection — see D-028.
    expect(frame?.getAttribute('sandbox')).toBe('allow-scripts')
    expect(frame?.getAttribute('srcdoc')).toContain('<h1>hi</h1>')
  })

  it('renders an image from its content URL rather than fetching text', () => {
    show(artifact({ mime: 'image/png', filename: 'shot.png', textual: false }))
    const img = screen.getByRole('img', { name: 'shot.png' })
    expect(img.getAttribute('src')).toContain('/artifacts/1/content')
  })
})

describe('ArtifactList', () => {
  it('says so when an attempt produced nothing', () => {
    render(<ArtifactList artifacts={[]} selectedId={null} onSelect={() => {}} />)
    expect(screen.getByText(/no artifacts/i)).toBeInTheDocument()
  })

  it('labels each artifact by what it is', () => {
    render(
      <ArtifactList
        artifacts={[
          artifact({ id: 1, kind: 'raw_output', filename: 'output.md' }),
          artifact({ id: 2, kind: 'code_block', language: 'go' }),
          artifact({ id: 3, kind: 'workdir_file', filename: 'main.go' }),
        ]}
        selectedId={2}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByText('output')).toBeInTheDocument()
    expect(screen.getByText('go')).toBeInTheDocument()
    expect(screen.getByText('file')).toBeInTheDocument()
  })

  it('reports which artifact is selected', () => {
    render(
      <ArtifactList
        artifacts={[artifact({ id: 1 }), artifact({ id: 2, filename: 'block-2.py' })]}
        selectedId={2}
        onSelect={() => {}}
      />,
    )
    const buttons = screen.getAllByRole('button')
    expect(buttons[1]).toHaveAttribute('aria-pressed', 'true')
    expect(buttons[0]).toHaveAttribute('aria-pressed', 'false')
  })

  it('calls back with the artifact that was clicked', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(
      <ArtifactList
        artifacts={[artifact({ id: 7, filename: 'chosen.py' })]}
        selectedId={null}
        onSelect={onSelect}
      />,
    )
    await user.click(screen.getByText('chosen.py'))
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }))
  })
})
