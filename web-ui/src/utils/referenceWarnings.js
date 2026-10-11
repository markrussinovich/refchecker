// Consolidate historical cache warnings without losing distinct prior values.
export function consolidateCacheWarnings(warnings) {
  const matches = warnings.filter(w => (w.warning_type || w.error_type) === 'cache_inconsistency')
  if (matches.length < 2) return warnings
  const intro = 'You cited this same title differently in an earlier check. Confirm which version is correct.'
  const details = [...new Set(matches.map(w => (w.warning_details || w.error_details || '')
    .replace(intro, '').trim()).filter(Boolean))]
  const merged = {
    ...matches[0],
    warning_details: `${intro} ${details.join('; ')}`,
    error_details: `${intro} ${details.join('; ')}`,
    cached_matches: matches.flatMap(w => w.cached_matches || [w]),
  }
  let inserted = false
  return warnings.flatMap(w => {
    if ((w.warning_type || w.error_type) !== 'cache_inconsistency') return [w]
    if (inserted) return []
    inserted = true
    return [merged]
  })
}
