import { describe, it, expect } from 'vitest'
import { formatCount, formatRelativeDays } from '../src/lib/format.js'

describe('formatCount', () => {
  it('shows values under 1000 as-is', () => {
    expect(formatCount(0)).toBe('0')
    expect(formatCount(999)).toBe('999')
  })

  it('abbreviates values at or above 1000 with one decimal', () => {
    expect(formatCount(1000)).toBe('1k')
    expect(formatCount(1234)).toBe('1.2k')
    expect(formatCount(12800)).toBe('12.8k')
    expect(formatCount(999999)).toBe('1000k')
  })

  it('treats missing/non-numeric input as 0', () => {
    expect(formatCount(undefined)).toBe('0')
    expect(formatCount(null)).toBe('0')
  })
})

describe('formatRelativeDays', () => {
  // Constructed from local-time fields (not UTC ISO strings) so the "same calendar day" math in
  // formatRelativeDays (which compares local Y/M/D) isn't at the mercy of the test runner's
  // timezone offset shifting a UTC timestamp across a local midnight boundary.
  const now = new Date(2026, 6, 13, 10, 0, 0)

  it('labels the same calendar day as 今天', () => {
    expect(formatRelativeDays(new Date(2026, 6, 13, 2, 0, 0), { now })).toBe('今天')
  })

  it('labels one day earlier as 昨天', () => {
    expect(formatRelativeDays(new Date(2026, 6, 12, 23, 0, 0), { now })).toBe('昨天')
  })

  it('labels N days earlier as "N 天前"', () => {
    expect(formatRelativeDays(new Date(2026, 6, 10, 0, 0, 0), { now })).toBe('3 天前')
  })

  it('returns an empty string for an unparseable date', () => {
    expect(formatRelativeDays('not-a-date', { now })).toBe('')
  })
})
