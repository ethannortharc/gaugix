import type { ScorerSpec, ScorerType } from '@/api/types'

/**
 * Scorer defaults, kept out of the component file so the builder stays a
 * component-only module (and so seeds/tests can use them without importing UI).
 */
export const DEFAULT_PARAMS: Record<ScorerType, Record<string, unknown>> = {
  contains: { text: '', case_sensitive: false },
  not_contains: { text: '', case_sensitive: false },
  regex: { pattern: '', should_match: true },
  json_schema: { schema: { type: 'object' }, extract_json: true },
  python: {
    code: 'def score(case, output):\n    ok = bool(output.strip())\n    return {"passed": ok, "value": 100 if ok else 0, "rationale": "non-empty"}\n',
  },
  llm_judge: { rubric: '', scale: '1-5', pass_threshold: 4 },
  human: { instructions: '' },
}

/** A fresh scorer with deep-copied params, so two scorers never share state. */
export function newScorer(type: ScorerType = 'contains'): ScorerSpec {
  return { type, params: structuredClone(DEFAULT_PARAMS[type]), required: true, weight: 1 }
}
