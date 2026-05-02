const FINAL_STATUSES = ['error', 'warning', 'suggestion', 'unverified', 'verified', 'hallucination']

export const normalizeForMetadataComparison = (value) => String(value || '')
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, ' ')
  .trim()

export const lastNameTokens = (authors) => (authors || [])
  .map(author => String(author || '').trim().split(/\s+/).filter(Boolean).pop()?.toLowerCase())
  .filter(Boolean)

export const llmFoundMetadataMatchesCitation = (reference = {}) => {
  const assessment = reference.hallucination_assessment || {}
  const foundAuthorsText = String(assessment.found_authors || '').toLowerCase()
  const citedLastNames = lastNameTokens(reference.authors)

  return assessment.verdict === 'LIKELY'
    && Boolean(assessment.link)
    && normalizeForMetadataComparison(assessment.found_title) === normalizeForMetadataComparison(reference.title)
    && citedLastNames.length > 0
    && citedLastNames.every(name => foundAuthorsText.includes(name))
    && (!reference.year || String(assessment.found_year || '').includes(String(reference.year)))
}

export const getEffectiveReferenceStatus = (reference = {}, isCheckComplete = false) => {
  const baseStatus = (reference.status || '').trim().toLowerCase()

  if (reference.hallucination_check_pending && !reference.hallucination_assessment) {
    return 'checking'
  }

  if (baseStatus === 'unverified' && !reference.hallucination_assessment && !isCheckComplete) {
    return 'checking'
  }

  // Check for errors, warnings, suggestions BEFORE applying llm override
  // Warnings and errors should NOT be overridden, even if LLM assessment matches
  const hasErrors = Array.isArray(reference.errors) && reference.errors.some(
    e => (e?.error_type || '').toLowerCase() !== 'unverified'
  )
  const hasWarnings = Array.isArray(reference.warnings) && reference.warnings.length > 0
  const hasSuggestions = Array.isArray(reference.suggestions) && reference.suggestions.length > 0

  // Hallucinated refs should display as hallucinated even when individual
  // metadata errors are also present (the errors are evidence of the
  // hallucination, not a separate problem). The LLM-match override
  // (citation matches the LLM-found paper) still demotes to verified.
  const llmMatch = llmFoundMetadataMatchesCitation(reference)
  const isHallucinated = !llmMatch && (
    baseStatus === 'hallucination'
    || reference.hallucination_assessment?.verdict === 'LIKELY'
  )
  if (isHallucinated) return 'hallucination'

  // Apply warnings/errors/suggestions priority BEFORE any other overrides
  if (hasErrors) return 'error'
  if (hasWarnings) return 'warning'
  if (hasSuggestions) return 'suggestion'

  // Only apply llmFoundMetadataMatchesCitation override if no warnings/errors/suggestions
  if (llmMatch) {
    return 'verified'
  }

  if (FINAL_STATUSES.includes(baseStatus)) {
    return baseStatus
  }

  if (baseStatus === 'pending' || baseStatus === 'checking' ||
      ['in_progress', 'queued', 'processing', 'started'].includes(baseStatus)) {
    if (isCheckComplete) {
      return 'unchecked'
    }
    return baseStatus === 'pending' ? 'pending' : 'checking'
  }

  return 'verified'
}