import {
  BarChart3,
  BookOpen,
  Cpu,
  FileText,
  FlaskConical,
  LayoutDashboard,
  Layers,
  Library,
  Menu,
  PlayCircle,
  Settings as SettingsIcon,
  UserRound,
  X,
} from 'lucide-react'
import * as React from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { HealthChip } from '@/components/layout/HealthChip'
import { ThemeToggle } from '@/components/layout/ThemeToggle'
import { Separator } from '@/components/ui/misc'
import { cn } from '@/lib/utils'

/**
 * The places you work.
 *
 * Settings is deliberately not among them. It is somewhere you go a handful of
 * times — to add a key, pick a judge — and listing it in the same rhythm as the
 * eight destinations you use constantly gave it the same weight as Runs. It
 * lives at the foot of the rail instead, where a tool's configuration usually
 * sits, with the theme switch next to it.
 */
const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/sets', label: 'Eval sets', icon: Layers },
  { to: '/cases', label: 'Cases', icon: FileText },
  { to: '/benchmarks', label: 'Benchmarks', icon: Library },
  { to: '/executors', label: 'Executors', icon: Cpu },
  { to: '/runs', label: 'Runs', icon: PlayCircle },
  { to: '/review', label: 'Review', icon: UserRound },
  { to: '/compare', label: 'Compare', icon: BarChart3 },
] as const

function Wordmark() {
  return (
    <div className="flex items-center gap-2 px-3 py-3">
      <span className="grid size-7 place-items-center rounded-md bg-[var(--primary)] text-[var(--primary-foreground)]">
        <FlaskConical className="size-4" />
      </span>
      <span className="text-sm font-semibold tracking-tight">Gaugix</span>
    </div>
  )
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav
      aria-label="Main"
      className="flex h-full w-52 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-2)]"
    >
      <Wordmark />
      <Separator />
      <ul className="flex flex-1 flex-col gap-0.5 overflow-y-auto p-2">
        {NAV.map(({ to, label, icon: Icon, ...rest }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={'end' in rest ? rest.end : undefined}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors',
                  isActive
                    ? 'bg-[var(--primary)]/12 font-medium text-[var(--primary)]'
                    : 'text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]',
                )
              }
            >
              <Icon className="size-4 shrink-0" />
              {label}
            </NavLink>
          </li>
        ))}
      </ul>

      <Separator />
      <div className="flex items-center gap-1.5 p-2">
        <NavLink
          to="/settings"
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex min-w-0 flex-1 items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors',
              isActive
                ? 'bg-[var(--primary)]/12 font-medium text-[var(--primary)]'
                : 'text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]',
            )
          }
        >
          <SettingsIcon className="size-4 shrink-0" />
          <span className="truncate">Settings</span>
        </NavLink>
        <ThemeToggle />
      </div>
    </nav>
  )
}

/** Unobtrusive learning-center entrance, per PRD F7.2. */
function Footer() {
  return (
    <footer className="flex items-center justify-between gap-4 border-t border-[var(--border)] px-5 py-2 text-[11px] text-[var(--muted-foreground)]">
      <span>© 2026 Ethan H.B. Zhou</span>
      <NavLink
        to="/learn"
        className="transition-colors hover:text-[var(--foreground)] hover:underline"
      >
        <span className="inline-flex items-center gap-1.5">
          <BookOpen className="size-3" />
          Eval Guide
        </span>
      </NavLink>
    </footer>
  )
}

/**
 * The application frame.
 *
 * The sidebar is permanent from `md` up and a drawer below it. At 390px the
 * fixed 208px rail left 182px of content — every table crushed, every header
 * wrapped three deep — so below the breakpoint it slides over the content
 * instead of stealing from it, and closes on navigation because a drawer that
 * stays open after you have used it is in the way.
 */
export function AppShell() {
  const [drawerOpen, setDrawerOpen] = React.useState(false)
  const location = useLocation()
  const drawerRef = React.useRef<HTMLDivElement>(null)

  /*
    Escape closes it, and Tab stays inside it while it is open. Without the
    trap, tabbing out of an open drawer lands on the page behind — which is
    covered by the scrim, so focus goes somewhere invisible and unusable.
  */
  React.useEffect(() => {
    if (!drawerOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setDrawerOpen(false)
        return
      }
      if (event.key !== 'Tab' || !drawerRef.current) return
      const focusable = drawerRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (!first || !last) return
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    drawerRef.current?.querySelector<HTMLElement>('a[href], button')?.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [drawerOpen])

  React.useEffect(() => setDrawerOpen(false), [location.pathname])

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[var(--background)]">
      <div className="hidden md:flex">
        <Sidebar />
      </div>

      {drawerOpen ? (
        <div className="fixed inset-0 z-40 md:hidden">
          {/*
            The scrim closes on click but is hidden from assistive technology
            and out of the tab order: it used to be a second control announcing
            "Close navigation", identical to the header's toggle, with no way to
            tell which one you had landed on.
          */}
          <button
            type="button"
            aria-hidden="true"
            tabIndex={-1}
            className="absolute inset-0 bg-black/40"
            onClick={() => setDrawerOpen(false)}
          />
          <div
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="absolute inset-y-0 left-0 shadow-xl"
          >
            <Sidebar onNavigate={() => setDrawerOpen(false)} />
          </div>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-[var(--border)] px-4 md:px-5">
          <button
            type="button"
            onClick={() => setDrawerOpen((open) => !open)}
            aria-label={drawerOpen ? 'Close navigation' : 'Open navigation'}
            aria-expanded={drawerOpen}
            className="-ml-1 grid size-8 place-items-center rounded-md text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] md:hidden"
          >
            {drawerOpen ? <X className="size-4" /> : <Menu className="size-4" />}
          </button>
          <span className="text-sm font-semibold tracking-tight md:hidden">Gaugix</span>
          <div className="ml-auto">
            <HealthChip />
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-6">
          <Outlet />
        </main>
        <Footer />
      </div>
    </div>
  )
}

/** Consistent page title + description + actions row. */
export function PageHeader({
  title,
  description,
  actions,
  children,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
  children?: React.ReactNode
}) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 flex-col gap-1">
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {description ? (
          <p className="text-sm text-[var(--muted-foreground)]">{description}</p>
        ) : null}
        {children}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}
