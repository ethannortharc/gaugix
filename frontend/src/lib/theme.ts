/**
 * Light, dark, or whatever the OS says.
 *
 * Both palettes existed in `index.css` from the start; `index.html` hard-coded
 * `class="dark"`, so the light one was written and unreachable. This makes the
 * choice real and remembers it.
 *
 * Three states rather than two. "System" is not a tidier default for the same
 * thing — it is a different behaviour: it follows the OS when the OS changes,
 * which is what someone on a machine that flips at sunset actually wants. A
 * two-state toggle silently converts that person into a manual switcher the
 * first time they touch it.
 */

import * as React from 'react'

export type Theme = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'gaugix-theme'
const THEMES: Theme[] = ['light', 'dark', 'system']

/** Shared with the inline script in `index.html`, which runs before React. */
export function readStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return THEMES.includes(stored as Theme) ? (stored as Theme) : 'system'
  } catch {
    // Private browsing, or storage disabled. Following the OS is a fine default
    // and a broken preference must not break the app.
    return 'system'
  }
}

export function systemTheme(): ResolvedTheme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function resolve(theme: Theme): ResolvedTheme {
  return theme === 'system' ? systemTheme() : theme
}

function apply(theme: Theme): void {
  const resolved = resolve(theme)
  document.documentElement.classList.toggle('dark', resolved === 'dark')
  // Tells the browser which palette to use for form controls, scrollbars and
  // the like — the parts of the page CSS variables cannot reach.
  document.documentElement.style.colorScheme = resolved
}

// -- a store small enough not to need a library ---------------------------------

let current: Theme = 'system'
const listeners = new Set<() => void>()

/**
 * `preference:resolved` — both halves, because subscribers care about both.
 *
 * The snapshot used to be the preference alone, and `useSyncExternalStore`
 * skips the re-render when the snapshot is unchanged. So on `system` an OS
 * flip repainted the CSS (that goes through a class on `<html>`, not React)
 * while every consumer of `resolved` kept the old value: the snapshot was the
 * string `system` before and after. The Toaster stayed in the dead theme until
 * something else re-rendered it.
 *
 * A string, not an object, so repeated `getSnapshot()` calls are referentially
 * equal and React does not loop.
 */
let snapshot = 'system:light'

function refresh(): void {
  snapshot = `${current}:${resolve(current)}`
}

function emit(): void {
  refresh()
  for (const listener of listeners) listener()
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function getSnapshot(): string {
  return snapshot
}

export function getTheme(): Theme {
  return current
}

export function setTheme(theme: Theme): void {
  current = theme
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // Unwritable storage costs the preference on reload, not the switch itself.
  }
  apply(theme)
  emit()
}

/**
 * Read the stored preference and start following the OS.
 *
 * Called once at startup. The media-query listener stays for the life of the
 * page: on `system` the app must repaint when the OS flips, and re-subscribing
 * per component would fire the same work once per subscriber.
 */
export function initTheme(): void {
  current = readStoredTheme()
  apply(current)
  refresh()
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (current === 'system') {
      apply(current)
      emit()
    }
  })
}

/** The current preference, and the palette it currently resolves to. */
export function useTheme(): { theme: Theme; resolved: ResolvedTheme } {
  const value = React.useSyncExternalStore(subscribe, getSnapshot, () => 'system:light')
  const [theme, resolved] = value.split(':')
  return { theme: theme as Theme, resolved: resolved as ResolvedTheme }
}
