export const meta = {
  name: 'ai-detection-review-round',
  description: 'Multi-dimension expert review of the AI-detection feature with adversarial verification',
  phases: [
    { title: 'Review', detail: 'fullstack, ml, frontend-theme, logic reviewers read the feature code' },
    { title: 'Verify', detail: 'adversarially verify each finding is real and actionable' },
  ],
}

const FEATURE_FILES = [
  'Python package: src/refchecker/ai_detection/{__init__,base,llm_backend,local_backend,api_backend,model_manager}.py',
  'Python wiring: backend/refchecker_wrapper.py (ProgressRefChecker.__init__ ai_detection_* params; _run_ai_detection passes check_id; check_paper launches _run_ai_detection CONCURRENTLY with _check_references_parallel via asyncio.create_task and awaits both before "completed"; the no-references early-return path also runs detection)',
  'Python wiring: backend/main.py (Form params on /api/check + batch URL/files; run_check threading; update_check_results call; /api/ai-detection/model[/status|/download] + DELETE admin-gated in multiuser; /api/papers/expand now accepts ai_detection and computes a local abstract-based band per expanded item; recheck comment)',
  'Python wiring: backend/database.py (migration for ai_detection_json/score/band; persistence; get_check_by_id parse; get_batch_checks + get_batch_summary SELECTs)',
  'Usage/cost tracking: src/refchecker/ai_detection/base.py (estimate_api_cost, record_detection_usage), local/api/llm backends call it; per-check tracker is src/refchecker/llm/usage_tracker.py record(); web-ui/src/components/MainPanel/LLMUsageBadge.jsx FLOW_LABEL.ai_detection',
  'Frontend stores: web-ui/src/stores/useAiDetectionStore.js, useCheckStore.js (aiDetection state + ai_detection_result WS cases — foreground + concurrent-session), useHistoryStore.js (hydration), web-ui/src/utils/api.js (model + expandPaper ai_detection)',
  'Frontend components: web-ui/src/components/MainPanel/{AIDetectionPanel,InputSection,BatchSummaryView,OnboardingBanner,MainPanel,GraphView}.jsx (GraphView: Refs-only/+AI-gen toggle, per-node AI-gen ring, legend, node-detail band), web-ui/src/components/Settings/SettingsPanel.jsx (renderAIDetectionSection + nav item + sources/credits)',
  'Tests: tests/unit/test_ai_detection.py',
].join('\n')

const CONTEXT = [
  'Repo: /Users/ario/Downloads/refchecker — a Tauri + Python(FastAPI) + React academic reference checker.',
  'A new OPT-IN "AI-generated-text detection" feature analyzes each submitted manuscript body text and reports a low/medium/high AI-likelihood band + advisory flagged passages.',
  'Three pluggable backends: local desklib DeBERTa (default, downloadable, offline), llm-judge (reuses configured LLM), external API (Pangram/GPTZero, key+consent).',
  'Detection runs inside check_paper (only place paper_text is live), streams via an ai_detection_result WS event, persists as ai_detection_json plus promoted scalar columns ai_detection_score/ai_detection_band (batch reads scalar columns).',
  'Honesty policy in ai_detection/base.py: abstain below ~300 words or technical sections, permanent disclaimer, never a binary verdict, llm-judge clamped to only LOWER severity (hard-capped at medium standalone).',
  'ML deps (torch/transformers/onnxruntime) are lazy-imported and NOT bundled into the PyInstaller sidecar.',
  'NEW in this round (review these too): (1) AI detection now runs CONCURRENTLY with reference checking in check_paper — verify no asyncio race on shared state, the task is always awaited (no orphan/leak on exceptions or early returns), and "completed" fires after both. (2) Usage/cost tracking: local records word-count tokens at $0, API records words + estimated $, llm-judge records real tokens, all under flow=ai_detection to the per-check meter — verify check_id threading and thread-safety. (3) Graph /api/papers/expand AI-gen: abstract-based local detection per expanded item, capped, free — verify it never uses a paid backend, handles missing model/abstract gracefully, and the asyncio.gather is bounded. (4) GraphView toggle/ring/legend and Settings credits — verify theme tokens + structure.',
  'Read the ACTUAL files (use Read/Grep) before reporting. Files to review:',
  FEATURE_FILES,
  '',
  'ACCEPTED BY DESIGN — do NOT report these (a prior review round already adjudicated them):',
  '- BatchSummaryView.jsx uses literal hex (#ef4444/#f59e0b) for the AI chip/badge to MATCH that component\'s pre-existing STATUS_COLOR palette; this is intentional consistency, not a defect.',
  '- SettingsPanel.jsx uses var(--color-accent, #3b82f6) fallbacks to match the file-wide convention used by every other section; intentional.',
  '- recheck endpoints intentionally do NOT replay AI detection (it is a live client preference, never persisted per-check); this is documented in code.',
  '- The "high" threshold (~0.85) is a documented heuristic, not a validated FPR operating point; this is surfaced honestly in operating_point and is a known limitation, not a bug.',
  'Only report NEW, real, actionable defects introduced by or remaining in the feature.',
].join('\n')

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['findings'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['title', 'severity', 'file', 'detail', 'suggested_fix'],
        properties: {
          title: { type: 'string' },
          severity: { type: 'string', enum: ['blocker', 'high', 'medium', 'low', 'nit'] },
          file: { type: 'string' },
          line: { type: 'string' },
          detail: { type: 'string' },
          suggested_fix: { type: 'string' },
        },
      },
    },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['is_real', 'reason', 'final_severity'],
  properties: {
    is_real: { type: 'boolean' },
    reason: { type: 'string' },
    final_severity: { type: 'string', enum: ['blocker', 'high', 'medium', 'low', 'nit', 'invalid'] },
  },
}

const DIMENSIONS = [
  {
    key: 'fullstack',
    agentType: 'reviewer',
    prompt: CONTEXT + '\n\nYou are a senior FULLSTACK engineer. Review the backend-to-frontend wiring for CORRECTNESS bugs: request params threaded through single + BOTH batch endpoints (URL + files) into run_check then ProgressRefChecker; the ai_detection_result WS event routed in useCheckStore; DB migration idempotency + scalar columns populated; get_batch_checks/get_batch_summary SELECT the new columns; get_check_by_id parses ai_detection_json; historical hydration in useHistoryStore; model-management endpoints; detector call placed where paper_text is live; no exception can break the citation check. Report real, verified defects only via StructuredOutput.',
  },
  {
    key: 'ml',
    agentType: 'ml-developer',
    prompt: CONTEXT + '\n\nYou are a senior ML engineer. Review the detection logic and honesty guardrails: banding/abstention thresholds in base.py (boundaries, word-count floor, non-prose guard), windowing (no sub-floor windows), local_backend aggregation (mean vs max, span agreement), llm_backend prompt + JSON parsing + clamp/non-native demotion, api_backend response-shape defensiveness, combine_bands_and AND-logic, clamp_not_above only lowers severity, and that NO path can emit a binary "AI-written" verdict or probability-of-guilt. Flag scientific-honesty regressions. Report real issues only via StructuredOutput.',
  },
  {
    key: 'frontend',
    agentType: 'reviewer',
    prompt: CONTEXT + '\n\nYou are a senior FRONTEND engineer with design-system discipline. Check whether the new UI matches the THEME and ORIGINAL STRUCTURE. The app uses CSS-variable tokens (--color-accent, --color-accent-hover, --color-bg-primary/secondary/tertiary, --color-border, --color-text-primary/secondary/muted, --color-success(-bg), --color-error(-bg), --color-warning(-bg), --color-info(-bg), --color-hallucination(-bg)), a shared Button component (web-ui/src/components/common/Button.jsx) and a local Chip in BatchSummaryView. Existing SettingsPanel sections use raw buttons styled "px-3 py-1.5 rounded-lg text-sm font-medium" with var(--color-accent). Check: do AIDetectionPanel.jsx and renderAIDetectionSection in SettingsPanel.jsx use tokens consistently (prefer --color-error/-warning/-success(-bg) over stray hardcoded hex where a token exists), match existing panel/section structure (compare SimilarPapersPanel, renderLLMSection), handle dark mode via tokens, have hover/disabled/focus states, accessible labels, consistent spacing; are OnboardingBanner/BatchSummaryView/MainPanel additions consistent. Report concrete, fixable theme/structure mismatches via StructuredOutput.',
  },
  {
    key: 'logic',
    agentType: 'reviewer',
    prompt: CONTEXT + '\n\nYou are a meticulous bug hunter. Find real LOGIC/CORRECTNESS/edge-case defects: None/empty handling (paper_text empty on .bbl/.bib/arxiv-source paths, missing keys), exceptions escaping run_detection/_run_ai_detection, the early-return-no-references path skipping detection, async/threading in asyncio.to_thread + the model_manager background thread, localStorage parse failures, the polling loop in downloadModel, state reset/stale aiDetection across checks, FormData boolean coercion (true/false strings vs pydantic bool). Report only real, reproducible defects with a concrete fix via StructuredOutput.',
  },
]

function tagFinding(f, dimension, verified, reason, finalSeverity) {
  return Object.assign({}, f, {
    dimension: dimension,
    verified: verified,
    verify_reason: reason,
    final_severity: finalSeverity || f.severity,
  })
}

phase('Review')
const results = await pipeline(
  DIMENSIONS,
  function reviewStage(d) {
    return agent(d.prompt, { label: 'review:' + d.key, phase: 'Review', agentType: d.agentType, schema: FINDINGS_SCHEMA })
      .then(function (r) { return { key: d.key, findings: (r && r.findings) || [] } })
  },
  function verifyStage(reviewed) {
    const findings = reviewed.findings || []
    const toVerify = findings.filter(function (f) { return f.severity === 'blocker' || f.severity === 'high' || f.severity === 'medium' })
    const passthrough = findings
      .filter(function (f) { return f.severity === 'low' || f.severity === 'nit' })
      .map(function (f) { return tagFinding(f, reviewed.key, true, 'low-severity, accepted without adversarial check', f.severity) })
    const verifyThunks = toVerify.map(function (f) {
      return function () {
        const vp = [
          'You are an adversarial verifier. A ' + reviewed.key + ' reviewer claims this defect in the AI-detection feature.',
          'Read the ACTUAL code and decide if it is REAL and actionable, or a false positive / already-handled / out-of-scope. Default to is_real=false if uncertain.',
          'TITLE: ' + f.title,
          'FILE: ' + f.file + ' ' + (f.line || ''),
          'DETAIL: ' + f.detail,
          'SUGGESTED FIX: ' + f.suggested_fix,
          'Return your verdict via StructuredOutput.',
        ].join('\n')
        return agent(vp, { label: 'verify:' + reviewed.key + ':' + f.file, phase: 'Verify', schema: VERDICT_SCHEMA })
          .then(function (v) { return tagFinding(f, reviewed.key, !!(v && v.is_real), v ? v.reason : 'verifier error', v ? v.final_severity : f.severity) })
          .catch(function () { return tagFinding(f, reviewed.key, false, 'verifier crashed', f.severity) })
      }
    })
    return parallel(verifyThunks).then(function (verified) { return verified.filter(Boolean).concat(passthrough) })
  }
)

const all = results.flat().filter(Boolean)
const confirmed = all.filter(function (f) { return f.verified && f.final_severity !== 'invalid' })
function countSev(s) { return confirmed.filter(function (f) { return (f.final_severity || f.severity) === s }).length }
log('Confirmed issues: ' + confirmed.length + ' (blocker ' + countSev('blocker') + ', high ' + countSev('high') + ', medium ' + countSev('medium') + ', low ' + countSev('low') + ', nit ' + countSev('nit') + ')')

return {
  confirmed_count: confirmed.length,
  blocker: countSev('blocker'),
  high: countSev('high'),
  medium: countSev('medium'),
  low: countSev('low'),
  nit: countSev('nit'),
  confirmed: confirmed,
}
