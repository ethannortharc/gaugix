import { BookOpen } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'

/**
 * A contextual deep link into the eval guide (PRD F7.3).
 *
 * Placed where a decision is actually being made — the rubric field, the judge
 * picker — rather than as a generic "docs" button. The guide is most useful at
 * the moment you are about to get something subtly wrong.
 */
export function GuideLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link
      to={`/learn/${to}`}
      className="inline-flex items-center gap-1 text-[var(--primary)] hover:underline"
    >
      <BookOpen className="size-3" />
      {children}
    </Link>
  )
}
