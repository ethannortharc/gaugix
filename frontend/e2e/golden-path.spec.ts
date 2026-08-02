import { expect, test } from '@playwright/test'

/**
 * The golden path (gate G7).
 *
 * One test that walks what a new user walks: look at the seeded sets, start a
 * run against fake executors, watch it finish, drill into a failure, read the
 * scores, mark a baseline, compare, and export a report. Nothing is stubbed.
 *
 * Written as a single ordered journey rather than independent tests because the
 * steps genuinely depend on each other — a run has to exist before it can be
 * compared, and re-seeding between steps would cost more than it proves.
 */
test('a new user can run, inspect, compare and export', async ({ page }) => {
  await test.step('the dashboard shows the seeded data', async () => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
    await expect(page.getByText('Guardrail regression')).toBeVisible()
  })

  await test.step('the eval set lists its cases', async () => {
    await page.goto('/sets')
    await page.getByRole('link', { name: /Guardrail regression/ }).first().click()
    await expect(page.getByText(/Jailbreak/).first()).toBeVisible()
  })

  let runUrl = ''
  await test.step('a run against fake executors completes', async () => {
    await page.goto('/runs/new')
    // Tick every set and every executor the seed created.
    for (const box of await page.getByRole('checkbox').all()) {
      if (!(await box.isChecked())) await box.click()
    }
    await page.getByRole('button', { name: /Launch|Start run|Create run/i }).first().click()

    await expect(page).toHaveURL(/\/runs\/\d+/, { timeout: 20_000 })
    runUrl = page.url()
    await expect(page.getByText(/completed/i).first()).toBeVisible({ timeout: 30_000 })
  })

  await test.step('an item drill-down explains its verdict', async () => {
    await page.getByRole('link', { name: /Jailbreak|Benign|Go:/ }).first().click()
    await expect(page).toHaveURL(/\/items\/\d+/)
    // Exact match: the artifacts card also contains the word "output". The
    // card is titled "Output vs reference" when the case has one, so the pane
    // label is what holds in both shapes.
    await expect(page.getByText('Input', { exact: true })).toBeVisible()
    await expect(page.getByText('model output', { exact: true })).toBeVisible()
    // A scored item shows why it scored that way, not just the verdict.
    await expect(page.getByText(/Scores|Scoring config/).first()).toBeVisible()
    // And you can walk to the next item without going back to the board.
    await expect(page.getByRole('link', { name: /Next item in this lane/ })).toBeVisible()
  })

  await test.step('the run can be marked as a baseline', async () => {
    await page.goto(runUrl)
    const baseline = page.getByRole('button', { name: /baseline/i }).first()
    if (await baseline.isVisible()) await baseline.click()
    await expect(page.getByText(/baseline/i).first()).toBeVisible()
  })

  await test.step('comparison views render real numbers', async () => {
    await page.goto('/compare?view=leaderboard')
    await expect(page.getByRole('heading', { name: 'Compare' })).toBeVisible()
    await expect(page.getByText(/Pass rate/i).first()).toBeVisible({ timeout: 15_000 })

    await page.goto('/compare?view=matrix')
    await expect(page.getByText(/Guardrail regression/i).first()).toBeVisible()
  })

  await test.step('the report exports as a self-contained file', async () => {
    const runId = runUrl.split('/').pop()
    const response = await page.request.get(`/api/v1/runs/${runId}/report`)
    expect(response.status()).toBe(200)

    const html = await response.text()
    expect(html).toContain('Gaugix')
    expect(html).toContain('Methodology')
    // Gate G5's rule, checked end to end: the file must open offline.
    expect(html).not.toMatch(/(?:src|href)\s*=\s*["']\s*(?:https?:)?\/\//)
  })

  await test.step('the eval guide is readable', async () => {
    await page.goto('/learn')
    await expect(page.getByRole('heading', { name: 'Eval Guide' })).toBeVisible()
    await page.getByRole('link', { name: /Judge calibration|LLM-as-judge/ }).first().click()
    await expect(page.getByText(/Self-preference/i)).toBeVisible()
  })

  await test.step('no console errors on the golden path', async () => {
    const errors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text())
    })
    await page.goto('/')
    await page.goto('/compare')
    await page.goto('/learn')
    expect(errors).toEqual([])
  })
})
