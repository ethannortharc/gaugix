import { createBrowserRouter } from 'react-router-dom'

import { AppShell } from '@/components/layout/AppShell'
import BenchmarkDetailPage from '@/pages/BenchmarkDetail'
import BenchmarksPage from '@/pages/Benchmarks'
import CaseDetailPage from '@/pages/CaseDetail'
import CasesPage from '@/pages/Cases'
import ComparePage from '@/pages/Compare'
import SideBySidePage from '@/pages/SideBySide'
import DashboardPage from '@/pages/Dashboard'
import ExecutorsPage from '@/pages/Executors'
import ItemDetailPage from '@/pages/ItemDetail'
import LearnPage from '@/pages/Learn'
import NotFoundPage from '@/pages/NotFound'
import RunDetailPage from '@/pages/RunDetail'
import RunNewPage from '@/pages/RunNew'
import ReviewPage from '@/pages/Review'
import RunsPage from '@/pages/Runs'
import SetDetailPage from '@/pages/SetDetail'
import SetsPage from '@/pages/Sets'
import SettingsPage from '@/pages/Settings'

/** Route table — mirrors ARCHITECTURE §8. */
export const routes = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'sets', element: <SetsPage /> },
      { path: 'sets/:id', element: <SetDetailPage /> },
      { path: 'cases', element: <CasesPage /> },
      { path: 'cases/:id', element: <CaseDetailPage /> },
      { path: 'benchmarks', element: <BenchmarksPage /> },
      { path: 'benchmarks/:slug', element: <BenchmarkDetailPage /> },
      { path: 'executors', element: <ExecutorsPage /> },
      { path: 'runs', element: <RunsPage /> },
      { path: 'runs/new', element: <RunNewPage /> },
      { path: 'runs/:id', element: <RunDetailPage /> },
      { path: 'items/:id', element: <ItemDetailPage /> },
      { path: 'review', element: <ReviewPage /> },
      { path: 'compare', element: <ComparePage /> },
      { path: 'compare/side-by-side', element: <SideBySidePage /> },
      { path: 'learn', element: <LearnPage /> },
      { path: 'learn/:slug', element: <LearnPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

export const router = createBrowserRouter(routes)
