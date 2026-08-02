import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import * as React from 'react'
import { Toaster } from 'sonner'

import { ApiError } from '@/api/client'
import { TooltipProvider } from '@/components/ui/misc'
import { useTheme } from '@/lib/theme'

/** One query client for the app; tests build their own with retries off. */
export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          // 4xx means we asked wrong — retrying just burns time.
          if (error instanceof ApiError && error.status < 500) return false
          return failureCount < 2
        },
      },
    },
  })
}

const queryClient = makeQueryClient()

export function AppProviders({
  children,
  client = queryClient,
}: {
  children: React.ReactNode
  client?: QueryClient
}) {
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider delayDuration={250}>
        {children}
        <Toasts />
      </TooltipProvider>
    </QueryClientProvider>
  )
}

/** Toasts follow the palette. Hard-coded dark, they glared in a light window. */
function Toasts() {
  const { resolved } = useTheme()
  return <Toaster position="bottom-right" richColors closeButton theme={resolved} />
}
