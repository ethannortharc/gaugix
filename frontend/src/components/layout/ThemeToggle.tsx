import { Monitor, Moon, Sun } from 'lucide-react'

import { setTheme, useTheme, type Theme } from '@/lib/theme'
import { cn } from '@/lib/utils'

const OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'system', label: 'Follow the system', icon: Monitor },
  { value: 'dark', label: 'Dark', icon: Moon },
]

/**
 * Three explicit choices rather than a cycling button.
 *
 * A single button that rotates light → dark → system cannot show you where you
 * are without a label, and "system" is invisible in it: you press it twice and
 * cannot tell whether you are following the OS or happen to match it. Three
 * segments cost the same width and answer both questions at a glance.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme } = useTheme()

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className={cn(
        'flex items-center gap-0.5 rounded-md border border-[var(--border)] p-0.5',
        className,
      )}
    >
      {OPTIONS.map(({ value, label, icon: Icon }) => {
        const active = theme === value
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={label}
            title={label}
            onClick={() => setTheme(value)}
            className={cn(
              'grid size-6 place-items-center rounded transition-colors',
              active
                ? 'bg-[var(--primary)]/15 text-[var(--primary)]'
                : 'text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]',
            )}
          >
            <Icon className="size-3.5" />
          </button>
        )
      })}
    </div>
  )
}
