import { describe, expect, it } from 'vitest'

import {
  formatCost,
  formatDurationMs,
  formatPercent,
  formatScore,
  formatTokens,
  NOT_AVAILABLE,
  pluralize,
  truncate,
} from '@/lib/format'

describe('formatCost', () => {
  it('renders unknown cost as n/a, never as zero', () => {
    // A fabricated $0.00 would silently misreport a leaderboard.
    expect(formatCost(null)).toBe(NOT_AVAILABLE)
    expect(formatCost(undefined)).toBe(NOT_AVAILABLE)
    expect(formatCost(Number.NaN)).toBe(NOT_AVAILABLE)
  })

  it('renders a genuine zero as $0.00', () => {
    expect(formatCost(0)).toBe('$0.00')
  })

  it('keeps sub-cent runs legible', () => {
    expect(formatCost(0.00042)).toBe('$0.0004')
    expect(formatCost(0.0731)).toBe('$0.073')
    expect(formatCost(12.3456)).toBe('$12.35')
  })
})

describe('formatTokens', () => {
  it('compacts large counts', () => {
    expect(formatTokens(842)).toBe('842')
    expect(formatTokens(1500)).toBe('1.5k')
    expect(formatTokens(42_000)).toBe('42k')
    expect(formatTokens(3_500_000)).toBe('3.50M')
  })

  it('reports unknown as n/a', () => {
    expect(formatTokens(null)).toBe(NOT_AVAILABLE)
  })
})

describe('formatDurationMs', () => {
  it('scales the unit to the magnitude', () => {
    expect(formatDurationMs(420)).toBe('420ms')
    expect(formatDurationMs(4200)).toBe('4.2s')
    expect(formatDurationMs(42_000)).toBe('42s')
    expect(formatDurationMs(125_000)).toBe('2m 5s')
    expect(formatDurationMs(7_800_000)).toBe('2h 10m')
  })
})

describe('formatScore', () => {
  it('drops the decimal for whole scores', () => {
    expect(formatScore(100)).toBe('100')
    expect(formatScore(87.5)).toBe('87.5')
    expect(formatScore(null)).toBe(NOT_AVAILABLE)
  })
})

describe('formatPercent', () => {
  it('formats a fraction', () => {
    expect(formatPercent(0.75)).toBe('75%')
    expect(formatPercent(0.8333, 1)).toBe('83.3%')
    expect(formatPercent(undefined)).toBe(NOT_AVAILABLE)
  })
})

describe('misc helpers', () => {
  it('truncates with an ellipsis only when needed', () => {
    expect(truncate('short', 10)).toBe('short')
    expect(truncate('abcdefghij', 5)).toBe('abcd…')
  })

  it('pluralizes', () => {
    expect(pluralize(1, 'case')).toBe('case')
    expect(pluralize(2, 'case')).toBe('cases')
    expect(pluralize(2, 'entry', 'entries')).toBe('entries')
  })
})
