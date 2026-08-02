import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from '@/lib/utils'

/**
 * Status colour is meaning, not decoration: pass/fail/error/human map to the
 * semantic tokens defined in index.css and are used identically everywhere.
 */
const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-4 whitespace-nowrap',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-[var(--muted)] text-[var(--muted-foreground)]',
        outline: 'border-[var(--border)] text-[var(--foreground)]',
        primary: 'border-transparent bg-[var(--primary)]/15 text-[var(--primary)]',
        pass: 'border-transparent bg-[var(--pass)]/15 text-[var(--pass)]',
        fail: 'border-transparent bg-[var(--fail)]/15 text-[var(--fail)]',
        error: 'border-transparent bg-[var(--error)]/15 text-[var(--error)]',
        pending: 'border-transparent bg-[var(--pending)]/15 text-[var(--muted-foreground)]',
        running: 'border-transparent bg-[var(--running)]/15 text-[var(--running)]',
        human: 'border-transparent bg-[var(--human)]/15 text-[var(--human)]',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

// forwardRef so Radix `asChild` triggers (Tooltip, Popover) can attach a ref.
const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant, ...props }, ref) => (
    <span ref={ref} className={cn(badgeVariants({ variant }), className)} {...props} />
  ),
)
Badge.displayName = 'Badge'

export { Badge, badgeVariants }
