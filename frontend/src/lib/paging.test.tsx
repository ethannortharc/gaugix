import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { usePagedLimit } from '@/lib/paging'

describe('usePagedLimit', () => {
  it('stops at the server ceiling instead of issuing an invalid next request', () => {
    const { result } = renderHook(() => usePagedLimit(10, 25))

    act(() => {
      result.current.more()
      result.current.more()
      result.current.more()
    })
    expect(result.current.limit).toBe(25)

    act(() => result.current.more())
    expect(result.current.limit).toBe(25)
  })
})
