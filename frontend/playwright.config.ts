import { defineConfig, devices } from '@playwright/test'

/**
 * The golden path (gate G7).
 *
 * Boots the real backend and the real UI, seeds a fresh database into a
 * throwaway data directory, and walks the loop a new user walks. Nothing is
 * mocked — that is the point: unit tests already cover the pieces, and this
 * exists to catch the wiring between them.
 *
 * `GAUGIX_DATA_DIR` points at a temp directory so a run never touches the
 * developer's own data, and no real API key is needed because the seed uses
 * fake executors.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI ? 'list' : [['list']],
  use: {
    baseURL: 'http://127.0.0.1:8417',
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
  // One server, not two: `make e2e` builds the frontend first and the API serves
  // it, so the golden path exercises the single-process mode a user actually
  // ships with rather than the Vite dev proxy.
  webServer: {
    command: 'npm run e2e:api',
    url: 'http://127.0.0.1:8417/api/health',
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
})
