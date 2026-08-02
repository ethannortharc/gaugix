import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getSnapshot,
  getTheme,
  initTheme,
  readStoredTheme,
  resolve,
  setTheme,
  subscribe,
} from '@/lib/theme'

function mockSystem(dark: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockReturnValue({
      matches: dark,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  )
}

/** A matchMedia whose `change` listener can actually be fired, and whose
 *  `matches` can be flipped the way an OS sunset switch flips it. */
function mockFlippableSystem(dark: boolean) {
  const query = {
    matches: dark,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue(query))
  return {
    flip(nowDark: boolean) {
      query.matches = nowDark
      for (const [event, handler] of query.addEventListener.mock.calls) {
        if (event === 'change') (handler as () => void)()
      }
    },
  }
}

describe('theme', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.className = ''
    mockSystem(false)
  })

  it('follows the system when nothing has been chosen', () => {
    expect(readStoredTheme()).toBe('system')
  })

  it('resolves system against the OS rather than guessing', () => {
    mockSystem(true)
    expect(resolve('system')).toBe('dark')
    mockSystem(false)
    expect(resolve('system')).toBe('light')
    // An explicit choice ignores the OS entirely.
    mockSystem(true)
    expect(resolve('light')).toBe('light')
  })

  it('applies and remembers an explicit choice', () => {
    setTheme('light')

    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(document.documentElement.style.colorScheme).toBe('light')
    expect(localStorage.getItem('gaugix-theme')).toBe('light')

    setTheme('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('reads the stored choice back at startup', () => {
    localStorage.setItem('gaugix-theme', 'light')
    mockSystem(true)

    initTheme()

    expect(getTheme()).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('ignores a stored value it does not recognise', () => {
    localStorage.setItem('gaugix-theme', 'neon')
    expect(readStoredTheme()).toBe('system')
  })

  it('survives storage being unavailable', () => {
    const boom = vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })

    // The preference is lost on reload; the switch itself must still work.
    expect(() => setTheme('dark')).not.toThrow()
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    boom.mockRestore()
  })

  it('notifies subscribers so the toaster and the toggle stay in step', () => {
    const seen: string[] = []
    initTheme()
    setTheme('dark')
    seen.push(getTheme())
    setTheme('system')
    seen.push(getTheme())

    expect(seen).toEqual(['dark', 'system'])
  })

  it('changes its snapshot when the OS flips under `system`', () => {
    // The snapshot used to be the preference alone, so this whole sequence
    // produced the string `system` at every step. useSyncExternalStore skips
    // the re-render when the snapshot is unchanged, so the CSS repainted (that
    // is a class on <html>, not React) while the Toaster kept the dead theme.
    const os = mockFlippableSystem(false)
    initTheme()
    expect(getSnapshot()).toBe('system:light')

    os.flip(true)
    expect(getSnapshot()).toBe('system:dark')

    os.flip(false)
    expect(getSnapshot()).toBe('system:light')
  })

  it('tells subscribers about an OS flip, not just about a click', () => {
    const os = mockFlippableSystem(false)
    initTheme()
    const listener = vi.fn()
    const unsubscribe = subscribe(listener)

    os.flip(true)
    expect(listener).toHaveBeenCalledTimes(1)
    expect(getSnapshot()).toBe('system:dark')

    unsubscribe()
    os.flip(false)
    expect(listener).toHaveBeenCalledTimes(1)
  })

  it('leaves the snapshot alone when the OS flips under an explicit choice', () => {
    const os = mockFlippableSystem(false)
    initTheme()
    setTheme('light')
    expect(getSnapshot()).toBe('light:light')

    os.flip(true)
    expect(getSnapshot()).toBe('light:light')
  })
})
