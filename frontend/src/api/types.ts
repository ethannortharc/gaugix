/**
 * Types mirroring the backend DTOs (`gaugix/schemas/*`).
 *
 * Hand-maintained rather than generated: the surface is small, and the compile
 * error you get when they drift is more useful than a regeneration step nobody
 * remembers to run.
 */

export type Role = 'system' | 'user' | 'assistant'

export interface Message {
  role: Role
  content: string
}

export type ScorerType =
  'contains' | 'not_contains' | 'regex' | 'json_schema' | 'python' | 'llm_judge' | 'human'

export interface ScorerSpec {
  type: ScorerType
  params: Record<string, unknown>
  required: boolean
  weight: number
}

export interface SetRef {
  id: number
  name: string
  position: number
}

export interface EvalCase {
  id: number
  title: string
  input: Message[]
  reference: string | null
  scoring: ScorerSpec[]
  tags: string[]
  notes: string | null
  deleted_at: string | null
  created_at: string
  updated_at: string
  sets: SetRef[]
  position: number | null
}

/**
 * Where a set's cases came from, when it was installed from the catalogue.
 *
 * `modified` is computed live rather than stored: a benchmark set someone has
 * added to, removed from or edited is a *derived* set. It may be a better eval
 * than the original; what it is not is the benchmark.
 */
export interface SetProvenance {
  benchmark?: string
  benchmark_name?: string
  scope?: string
  installed_at?: string
  case_count?: number
  sample_seed?: number | null
  licence?: string
  method_fidelity?: string
  method_version?: string
  comparable_to_published?: boolean
  source_url?: string | null
  source_revision?: string | null
  source_sha256?: string | null
  rows_downloaded?: number | null
  modified?: boolean
  modified_reasons?: string[]
  /**
   * Installed before Gaugix recorded provenance. The benchmark is inferred from
   * the set's tags; `method_fidelity` and `method_version` read `unrecorded`
   * and must not be rendered as if they were a real method (they were shown as
   * "Gaugix adaptation · unrecorded vunrecorded").
   */
  legacy?: boolean
}

export interface EvalSet {
  id: number
  name: string
  description: string | null
  tags: string[]
  default_scoring: ScorerSpec[]
  case_count: number
  deleted_at: string | null
  created_at: string
  updated_at: string
  /** Empty for hand-made sets. */
  provenance: SetProvenance
}

export interface CountResponse {
  ok: boolean
  count: number
  message: string | null
}

export interface ImportRowError {
  line: number
  message: string
  raw: string | null
}

export interface ImportResult {
  ok: boolean
  imported: number
  errors: ImportRowError[]
  /** Imported, but something was lost on the way — never blocking. */
  warnings: ImportRowError[]
  case_ids: number[]
  dry_run: boolean
}

/** Which source column becomes which part of a case. Tabular formats only. */
export interface FieldMapping {
  input?: string | null
  reference?: string | null
  title?: string | null
  system?: string | null
  tags?: string | null
  notes?: string | null
  title_prefix?: string
}

export interface GenPromptResponse {
  prompt: string
  example_case_ids: number[]
}

export type ExportFormat = 'jsonl' | 'yaml' | 'json' | 'csv' | 'openai_evals'

/** Everything the importer reads. `huggingface` and `promptfoo` are import-only. */
export type ImportFormat = ExportFormat | 'huggingface' | 'promptfoo'

export const IMPORT_FORMAT_LABELS: Record<ImportFormat, string> = {
  jsonl: 'JSONL — Gaugix’s own shape',
  yaml: 'YAML — Gaugix’s own shape',
  json: 'JSON array — Gaugix’s own shape',
  csv: 'CSV / TSV — any table, columns mapped',
  openai_evals: 'openai/evals JSONL — {input, ideal}',
  huggingface: 'HuggingFace rows — a datasets-server payload',
  promptfoo: 'promptfoo YAML — tests, vars and assertions',
}

/** Formats that need to be told which column is the prompt. */
export const MAPPABLE_FORMATS: ImportFormat[] = ['csv', 'huggingface']

/** The canonical import/export shape — no ids, no timestamps (PRD Appendix B). */
export interface CaseIO {
  title: string
  input: Message[]
  reference?: string | null
  scoring?: ScorerSpec[]
  tags?: string[]
  notes?: string | null
}

export const SCORER_TYPES: ScorerType[] = [
  'contains',
  'not_contains',
  'regex',
  'json_schema',
  'python',
  'llm_judge',
  'human',
]

/** One-line explanation shown next to each scorer type in the builder UI. */
export const SCORER_LABELS: Record<ScorerType, string> = {
  contains: 'Output must contain this text',
  not_contains: 'Output must NOT contain this text',
  regex: 'Output must (not) match this regular expression',
  json_schema: 'Output (or an extracted JSON block) validates against a schema',
  python: 'A Python function decides — runs on this machine in a separate process',
  llm_judge: 'Another model grades the output against a rubric',
  human: 'You decide, in the review queue',
}

// -- executors (PRD F2) --------------------------------------------------------

export type Provider = 'anthropic' | 'openai' | 'gemini' | 'openai_compatible' | 'fake'
export type HarnessKind = 'direct' | 'fake' | 'cli'

export interface Pricing {
  input_per_1m: number
  output_per_1m: number
}

export interface ModelProfile {
  id: number
  name: string
  provider: Provider
  model_id: string
  base_url: string | null
  api_key_env: string | null
  params: Record<string, unknown>
  pricing: Pricing | null
  archived: boolean
  key_present: boolean
  created_at: string
  updated_at: string
}

export interface HarnessProfile {
  id: number
  name: string
  kind: HarnessKind
  config: Record<string, unknown>
  archived: boolean
  created_at: string
  updated_at: string
}

export interface Executor {
  id: number
  name: string
  model_profile_id: number
  harness_profile_id: number
  model_name: string
  model_id: string
  provider: Provider
  harness_name: string
  harness_kind: HarnessKind
  overrides: Record<string, unknown>
  archived: boolean
  run_count: number
  created_at: string
  updated_at: string
}

export interface TestConnectionResult {
  ok: boolean
  message: string
  latency_ms: number | null
  prompt_tokens: number | null
  completion_tokens: number | null
  cost_usd: number | null
  output_preview: string | null
  error_kind: string | null
}

// -- runs (PRD F3) -------------------------------------------------------------

export type RunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'canceled' | 'interrupted'

export type ItemStatus =
  'pending' | 'invoking' | 'scoring' | 'passed' | 'failed' | 'error' | 'skipped'

export interface RunTotals {
  items: number
  pending: number
  invoking: number
  scoring: number
  passed: number
  failed: number
  error: number
  skipped: number
  needs_human: number
  /** Items with an actual verdict — the pass-rate denominator. */
  scored: number
  verdict_passed: number
  /** Finished cleanly but nothing judged them. */
  unscored: number
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
  judge_cost_usd: number
  /** True when at least one attempt had no computable cost — the total is a floor. */
  cost_unknown: boolean
}

export interface ExecutorSnapshot {
  executor_id: number | null
  key: string
  model: {
    name: string
    provider: Provider
    model_id: string
    base_url?: string | null
    api_key_env?: string | null
    params: Record<string, unknown>
  }
  harness: { name: string; kind: HarnessKind; config: Record<string, unknown> }
  overrides: Record<string, unknown>
}

export interface RunConfig {
  executors: ExecutorSnapshot[]
  sets: { id: number; name: string }[]
  concurrency: number
  auto_score: boolean
}

export interface Run {
  id: number
  name: string
  status: RunStatus
  parent_run_id: number | null
  config: RunConfig
  totals: RunTotals
  is_baseline_for: number[]
  error: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  is_active: boolean
  /** True only when a resume would actually schedule something. */
  is_resumable: boolean
  /** How many items a resume would run. */
  resumable_items: number
  /** True when this run covered only part of at least one of its sets. */
  is_partial: boolean
  /** "Guardrail regression: 2 of 5 cases", per partially covered set. */
  partial_coverage: string[]
}

export interface SetRunHistoryRow {
  run_id: number
  run_name: string
  status: RunStatus
  created_at: string
  finished_at: string | null
  executor_keys: string[]
  item_count: number
  case_count: number
  coverage: string
  is_partial: boolean
  is_baseline: boolean
  scored: number
  passed: number
  failed: number
  unscored: number
  /** Passed / scored as a percentage, or null when no item has a verdict. */
  pass_rate: number | null
}

export interface CaseRunHistoryRow {
  item_id: number
  run_id: number
  run_name: string
  run_status: RunStatus
  run_created_at: string
  set_id: number | null
  set_name: string
  executor_key: string
  item_status: ItemStatus
  verdict: boolean | null
  score_value: number | null
  needs_human: boolean
  error: string | null
  output_preview: string | null
  latency_ms: number | null
  cost_usd: number | null
  attempt_n: number | null
}

export interface TrendPoint {
  run_id: number
  run_name: string
  created_at: string
  scored: number
  passed: number
  pass_rate: number
  partial: boolean
  /** "2 of 5 cases", or "all 5 cases". */
  coverage: string
}

/** One set's pass rate over recent runs, oldest first, computed from its own items. */
export interface SetTrend {
  set_id: number
  set_name: string
  points: TrendPoint[]
  /**
   * Partial runs left out of `points`.
   *
   * A rate over two of five cases is not a point on the same line as a rate
   * over five, so those runs are excluded — and counted, so the gap in the
   * line can be explained rather than just being short.
   */
  partial_runs_excluded: number
}

export interface RunPreview {
  sets: { set_id: number; name: string; case_count: number; available_case_count: number }[]
  executors: { key: string; provider: string }[]
  case_count: number
  /** Cases in the chosen sets before any subset filter — the "of 400" in "12 of 400". */
  available_case_count: number
  executor_count: number
  item_count: number
  suggested_name: string
  estimated_cost_usd: number | null
}

export interface RunItemNav {
  run_name: string
  /** Neighbours in the same executor lane, resolved server-side. */
  prev_item_id: number | null
  next_item_id: number | null
  lane_position: number
  lane_total: number
}

export interface RunItem {
  id: number
  run_id: number
  set_id: number | null
  set_name: string
  case_id: number | null
  executor_key: string
  position: number
  title: string
  status: ItemStatus
  verdict: boolean | null
  score_value: number | null
  needs_human: boolean
  error: string | null
  /** Latest scorer explanation, so a failed row says why before drill-down. */
  score_summary: string | null
  updated_at: string
}

export interface AttemptRead {
  id: number
  n: number
  status: 'ok' | 'error'
  request: Record<string, unknown>
  output_text: string
  messages: { role: string; content: string }[]
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number | null
  latency_ms: number
  error: string | null
  error_kind: string | null
  retries: number
  superseded: boolean
  created_at: string
}

export interface ScoreRead {
  id: number
  scorer_index: number
  scorer_type: ScorerType
  scorer_config_hash: string
  passed: boolean | null
  value: number | null
  rationale: string | null
  source: 'auto' | 'judge' | 'human'
  judge_meta: Record<string, unknown> | null
  version: number
  created_at: string
}

export interface RunItemDetail extends RunItem, RunItemNav {
  input: Message[]
  reference: string | null
  case_snapshot: CaseIO & { case_id: number | null }
  executor_snapshot: ExecutorSnapshot | null
  attempts: AttemptRead[]
  scores: ScoreRead[]
  artifacts: Record<string, unknown>[]
}

// -- settings (PRD F8.1) -------------------------------------------------------

export interface ProviderKeyStatus {
  provider: string
  env_var: string
  present: boolean
  masked: string | null
}

export interface PricingEntry {
  model_id: string
  input_per_1m: number
  output_per_1m: number
  /** `manual` rows are the user's and a litellm pull never overwrites them. */
  source: 'manual' | 'litellm'
}

export interface ModelCapabilities {
  model_id: string
  /** False when litellm has never heard of the model — every flag is then permissive. */
  known: boolean
  supported: string[]
  reasoning_effort: boolean
  temperature: boolean
  max_tokens: boolean
  thinking: boolean
  effort_levels: string[]
}

export interface PricingPullResult {
  added: string[]
  updated: string[]
  unchanged: string[]
  not_found: string[]
  settings: SettingsRead
}

export interface SettingsRead {
  providers: ProviderKeyStatus[]
  pricing: PricingEntry[]
  default_concurrency: number
  provider_concurrency: number
  default_judge_executor_id: number | null
  data_dir: string
  db_path: string
  version: string
}

/** Item status → badge variant. Colour always means the same thing (index.css). */
export const STATUS_VARIANT: Record<ItemStatus, string> = {
  pending: 'pending',
  invoking: 'running',
  scoring: 'running',
  passed: 'pass',
  failed: 'fail',
  error: 'error',
  skipped: 'default',
}

export const RUN_STATUS_VARIANT: Record<RunStatus, string> = {
  pending: 'pending',
  running: 'running',
  completed: 'pass',
  failed: 'fail',
  canceled: 'default',
  interrupted: 'error',
}

// -- comparison (PRD F5.2–F5.4) ------------------------------------------------

export interface BucketStats {
  items: number
  scored: number
  passed: number
  failed: number
  unscored: number
  errors: number
  needs_human: number
  /** null, not 0, when nothing was scored — 0% reads as total failure. */
  pass_rate: number | null
  mean_score: number | null
  mean_latency_ms: number | null
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number | null
  /** True when some call could not be priced, so cost_usd is a floor. */
  cost_unknown: boolean
  latency_ms: number
}

export interface CompareRunOption {
  id: number
  name: string
  status: string
  created_at: string
  finished_at: string | null
  is_baseline_for: number[]
  set_ids: number[]
  totals: RunTotals
}

export interface CompareOptions {
  runs: CompareRunOption[]
  sets: { id: number; name: string }[]
  executors: string[]
}

export type DiffKind = 'regressed' | 'improved' | 'unchanged' | 'new' | 'removed' | 'unresolved'

export interface DiffEntry {
  case_id: number | null
  title: string
  set_id: number | null
  set_name: string
  executor_key: string
  kind: DiffKind
  baseline_item_id: number | null
  current_item_id: number | null
  baseline_verdict: boolean | null
  current_verdict: boolean | null
  baseline_status: string | null
  current_status: string | null
  baseline_score: number | null
  current_score: number | null
  score_delta: number | null
  note: string | null
}

export interface SideBySide {
  current: number | null
  baseline: number | null
}

/** Both runs restricted to the identities they share — the only fair delta. */
export interface PairedMetrics {
  items: number
  pass_rate: SideBySide
  mean_score: SideBySide
}

export interface SetCoverage {
  set_id: number
  set_name: string
  baseline_run_id: number | null
  baseline_run_name: string
  /** False when this set's baseline is a different run and it was left out. */
  included: boolean
  reason: string | null
}

/**
 * What each side of a diff actually ran, for one set.
 *
 * The paired delta already restricts the arithmetic to shared identities, so
 * the numbers are sound without this. This is the sentence a reader needs:
 * "40% → 100%" means something else entirely when the second run covered two
 * of those five cases.
 */
export interface CaseUniverse {
  set_id: number
  set_name: string
  /** "2 of 5 cases", "all 5 cases", or "not in this run". */
  current: string
  baseline: string
  current_partial: boolean
  baseline_partial: boolean
  /** null when either run predates coverage recording. */
  same_universe: boolean | null
}

export interface DiffRead {
  /** False when there is no baseline yet — a normal state, not an error. */
  available: boolean
  reason: string | null
  current_run_id: number
  baseline_run_id: number
  counts: Record<DiffKind, number>
  entries: DiffEntry[]
  executors: { both: string[]; only_current: string[]; only_baseline: string[] }
  /** False when the runs share no (set, case, executor) — no delta is meaningful. */
  comparable: boolean
  paired: PairedMetrics
  coverage: SetCoverage[]
  case_universes: CaseUniverse[]
  scoped_set_ids: number[]
  /** Each side over everything it contained — context only, not a delta. */
  pass_rate: SideBySide
  mean_score: SideBySide
}

export interface LeaderboardRow extends BucketStats {
  executor_key: string
  /** null when the executor scored nothing — it has no rank to claim. */
  rank: number | null
}

export interface LeaderboardRead {
  run_ids: number[]
  rows: LeaderboardRow[]
  totals: BucketStats
}

export interface MatrixCell {
  item_id: number
  run_id: number
  status: ItemStatus
  verdict: boolean | null
  score_value: number | null
  needs_human: boolean
  error: string | null
}

export interface MatrixRow {
  set_id: number | null
  set_name: string
  case_id: number | null
  title: string
  position: number
  cells: Record<string, MatrixCell>
}

export interface MatrixRead {
  executors: string[]
  rows: MatrixRow[]
}

export interface AggregateRow {
  set_id: number | null
  set_name: string
  cells: Record<string, BucketStats>
  totals: BucketStats
}

export interface AggregateMatrixRead {
  executors: string[]
  rows: AggregateRow[]
  totals: BucketStats
}

export interface ErrorKindCount {
  kind: string
  count: number
}

/**
 * One bucket of a class-graded judge.
 *
 * Only rubrics declaring `classes` produce these — SimpleQA's CORRECT /
 * INCORRECT / NOT_ATTEMPTED is the case in the catalogue. Accuracy alone hides
 * whether a model was wrong or simply declined, which is what it exists to
 * separate.
 */
export interface JudgeClassCount {
  name: string
  count: number
  /** Percentage of classified scores in the run. */
  share: number
}

// -- artifacts (PRD F6) --------------------------------------------------------

export interface ArtifactRead {
  id: number
  attempt_id: number
  /** raw_output | code_block | workdir_file | capture */
  kind: string
  filename: string
  mime: string
  size_bytes: number
  sha256: string
  language: string | null
  block_index: number | null
  /** Whether the viewer can show this as text rather than offering a download. */
  textual: boolean
  created_at: string
}

export interface ArtifactSide {
  item_id: number
  run_id: number
  executor_key: string
  title: string
  status: ItemStatus
  verdict: boolean | null
  score_value: number | null
  output_text: string
  artifacts: ArtifactRead[]
}

export interface ArtifactCompare {
  sides: ArtifactSide[]
}

export interface ExecPlanRead {
  artifact_id: number
  command: string
  argv: string[]
  workdir: string
  timeout_s: number
  /** Authorises exactly this command. Invalid after a server restart. */
  confirm_token: string
  warning: string
}

export interface ExecResultRead {
  exit_code: number
  stdout: string
  stderr: string
  duration_ms: number
  timed_out: boolean
}

// -- learning center (PRD F7) --------------------------------------------------

export interface ChapterSummary {
  slug: string
  order: number
  title: string
  summary: string
  tags: string[]
  word_count: number
}

export interface ChapterRead extends ChapterSummary {
  body: string
  headings: { text: string; anchor: string }[]
  previous: ChapterSummary | null
  next: ChapterSummary | null
}

export interface SearchHit {
  slug: string
  title: string
  excerpt: string
  score: number
}

// -- benchmark catalogue -------------------------------------------------------

export interface BenchmarkSource {
  url: string
  host: string
  encoding: string
  approx_bytes: number
  /** The immutable revision the URL pins, when the host publishes one. */
  revision: string
  sha256: string
  expected_rows: number
}

/**
 * Whether a number from Gaugix is the benchmark's number.
 *
 * `official-compatible` reproduces the published method within the stated
 * deviations. `gaugix-adaptation` runs the benchmark's data through a method
 * of Gaugix's own — useful for comparing your models, never a leaderboard score.
 */
export interface BenchmarkMethod {
  fidelity: 'official-compatible' | 'gaugix-adaptation'
  comparable: boolean
  deviations: string[]
  version: string
}

export interface InstalledSetRef {
  id: number
  name: string
  case_count: number
}

export interface BenchmarkSummary {
  slug: string
  name: string
  publisher: string
  year: number
  licence: string
  task: string
  summary: string
  full_size: number
  sample_size: number
  tags: string[]
  requires_judge: boolean
  requires_code_execution: boolean
  method: BenchmarkMethod
  installed: InstalledSetRef[]
}

export interface BenchmarkDetail extends BenchmarkSummary {
  description: string
  what_it_measures: string
  /** Reasons to distrust the number. Never empty — see the catalogue module. */
  caveats: string[]
  scoring_note: string
  languages: string[]
  homepage: string
  licence_url: string
  /** Set when the dataset's licence differs from the repository's. */
  licence_note: string | null
  paper: string | null
  source: BenchmarkSource | null
  sample_cases: CaseIO[]
}

export type InstallScope = 'sample' | 'full'

export interface InstallRequest {
  scope: InstallScope
  set_name?: string | null
  limit?: number | null
  /** With a limit, draw a reproducible random sample rather than the first N. */
  sample_seed?: number | null
  accept_code_execution?: boolean
  /** Required when the download no longer matches the catalogue's checksum. */
  accept_drift?: boolean
}

export interface InstallPreview {
  slug: string
  scope: InstallScope
  set_name: string
  case_count: number
  warnings: string[]
  source: BenchmarkSource | null
  requires_judge: boolean
  requires_code_execution: boolean
  method: BenchmarkMethod
}

export interface InstallResult {
  ok: boolean
  set_id: number
  set_name: string
  imported: number
  scope: InstallScope
  warnings: string[]
  /** Revision, checksum, licence and scorer version of what was installed. */
  provenance: Record<string, unknown>
}

// -- run preflight -------------------------------------------------------------

export interface PreflightFinding {
  /** blocker disables launch; warning and note do not. */
  severity: 'blocker' | 'warning' | 'note'
  code: string
  message: string
  detail: string | null
  count: number
}

export interface PreflightRead {
  ok: boolean
  findings: PreflightFinding[]
  case_count: number
  executor_count: number
  item_count: number
  estimated_cost_usd: number | null
  /** What the estimate assumed, so it is never read as a quote. */
  cost_assumptions: string
  /** Judge calls folded into the estimate — the half people forget. */
  judge_call_count: number
  estimated_judge_cost_usd: number | null
  /** True when a scorer here runs model-written code on this machine. */
  requires_code_execution: boolean
  code_execution_sets: string[]
}
