import { useMutation } from '@tanstack/react-query'

import { apiFetch } from '@/api/client'
import type { Message, PlaygroundResponse } from '@/api/types'

export function usePlaygroundInvoke() {
  return useMutation({
    mutationFn: (body: {
      executor_id: number
      messages: Message[]
      params?: Record<string, unknown>
      timeout_s?: number
    }) => apiFetch<PlaygroundResponse>('/playground/invoke', { method: 'POST', body }),
  })
}
