/**
 * Style-aware journal venue abbreviation handling (client-side).
 *
 * Mirrors src/refchecker/utils/venue_abbreviations.py. Backend always
 * emits venue mismatch warnings; the FE applies the active citation
 * style and suppresses the warning when the cited venue is an
 * acceptable abbreviation under that style. This keeps style changes
 * instant — flipping the dropdown re-evaluates without re-running
 * the check.
 *
 * Coverage is a bootstrap list — extend NLM_ABBREV_TO_FULL as new
 * journals surface. Or load the official NLM J_Medline.txt at build
 * time once we want full coverage.
 */

// Per-style policy: do citations in this style use NLM-abbreviated form?
const STYLE_VENUE_POLICY = {
  vancouver: { acceptsAbbrev: true, prefersAbbrev: true },
  nlm: { acceptsAbbrev: true, prefersAbbrev: true },
  ama: { acceptsAbbrev: true, prefersAbbrev: true },
  ieee: { acceptsAbbrev: true, prefersAbbrev: true },
  acs: { acceptsAbbrev: true, prefersAbbrev: true },
  aip: { acceptsAbbrev: true, prefersAbbrev: true },

  apa: { acceptsAbbrev: false, prefersAbbrev: false },
  mla: { acceptsAbbrev: false, prefersAbbrev: false },
  chicago: { acceptsAbbrev: false, prefersAbbrev: false },
  harvard: { acceptsAbbrev: false, prefersAbbrev: false },
  turabian: { acceptsAbbrev: false, prefersAbbrev: false },

  bibtex: { acceptsAbbrev: true, prefersAbbrev: false },
  plaintext: { acceptsAbbrev: true, prefersAbbrev: false },
  acm: { acceptsAbbrev: true, prefersAbbrev: false },
}

// NLM Title Abbreviations — bootstrap list. Keys are normalized
// lowercase abbreviations; values are normalized lowercase full titles.
const NLM_ABBREV_TO_FULL = {
  'n engl j med': 'new england journal of medicine',
  'jama': 'journal of the american medical association',
  'bmj': 'british medical journal',
  'lancet': 'the lancet',
  'ann intern med': 'annals of internal medicine',

  'ann surg': 'annals of surgery',
  'br j surg': 'british journal of surgery',
  'j am coll surg': 'journal of the american college of surgeons',
  'anz j surg': 'anz journal of surgery',
  'world j surg': 'world journal of surgery',
  'surgery': 'surgery',
  'jama surg': 'jama surgery',
  'surg endosc': 'surgical endoscopy',
  'dis colon rectum': 'diseases of the colon and rectum',
  'colorectal dis': 'colorectal disease',
  'eur j surg oncol': 'european journal of surgical oncology',
  'j surg oncol': 'journal of surgical oncology',
  'int j colorectal dis': 'international journal of colorectal disease',
  'tech coloproctol': 'techniques in coloproctology',

  'clin anat': 'clinical anatomy',
  'surg radiol anat': 'surgical and radiologic anatomy',
  'j anat': 'journal of anatomy',
  'anat sci int': 'anatomical science international',
  'ann anat': 'annals of anatomy',
  'radiology': 'radiology',
  'eur radiol': 'european radiology',
  'radiographics': 'radiographics',
  'br j radiol': 'british journal of radiology',
  'ajr am j roentgenol': 'american journal of roentgenology',
  'j magn reson imaging': 'journal of magnetic resonance imaging',
  // Orthopaedics / sports medicine (v0.7.58)
  'orthop clin north am': 'orthopedic clinics of north america',
  'j orthop res': 'journal of orthopaedic research',
  'j bone joint surg am': 'journal of bone and joint surgery american volume',
  'j bone joint surg br': 'journal of bone and joint surgery british volume',
  'j arthroplasty': 'the journal of arthroplasty',
  'am j sports med': 'the american journal of sports medicine',
  'arthrosc': 'arthroscopy',
  'arthroscopy': 'arthroscopy the journal of arthroscopic and related surgery',
  'osteoarthritis cartilage': 'osteoarthritis and cartilage',
  'clin orthop relat res': 'clinical orthopaedics and related research',
  'knee surg sports traumatol arthrosc': 'knee surgery sports traumatology arthroscopy',
  // v0.7.67 additions
  'bone joint j': 'the bone and joint journal',
  'clin sports med': 'clinics in sports medicine',
  'j orthop trauma': 'journal of orthopaedic trauma',
  'acta diabetol': 'acta diabetologica',
  'jama netw open': 'jama network open',
  'ajnr': 'american journal of neuroradiology',
  'am j neuroradiol': 'american journal of neuroradiology',
  'ajnr am j neuroradiol': 'american journal of neuroradiology',
  'neuroradiology': 'neuroradiology',
  'j neurointerv surg': 'journal of neurointerventional surgery',
  'j neurosurg': 'journal of neurosurgery',
  'neurosurgery': 'neurosurgery',
  'stroke': 'stroke',
  'spine (phila pa 1976)': 'spine',
  'spine': 'spine',
  'j vasc interv radiol': 'journal of vascular and interventional radiology',
  'cardiovasc intervent radiol': 'cardiovascular and interventional radiology',

  'j clin oncol': 'journal of clinical oncology',
  'cancer': 'cancer',
  'lancet oncol': 'the lancet oncology',
  'ann oncol': 'annals of oncology',
  'jnci': 'journal of the national cancer institute',
  'j natl cancer inst': 'journal of the national cancer institute',

  'cell': 'cell',
  'nature': 'nature',
  'science': 'science',
  'pnas': 'proceedings of the national academy of sciences',
  'proc natl acad sci u s a': 'proceedings of the national academy of sciences',
  'nat med': 'nature medicine',
  'nat genet': 'nature genetics',
  'nat methods': 'nature methods',
  'nat commun': 'nature communications',
  'plos one': 'plos one',
  'plos med': 'plos medicine',
  'bmc med': 'bmc medicine',

  'ieee trans pattern anal mach intell': 'ieee transactions on pattern analysis and machine intelligence',
  'ieee trans image process': 'ieee transactions on image processing',
  'ieee trans signal process': 'ieee transactions on signal processing',
  'ieee trans neural netw learn syst': 'ieee transactions on neural networks and learning systems',
  'ieee trans parallel distrib syst': 'ieee transactions on parallel and distributed systems',
}

const STOPWORDS = new Set(['of', 'the', 'and', 'in', 'on', 'for', 'a', 'an', 'to', 'with'])

function normalizeVenue(v) {
  if (!v) return ''
  let s = String(v).trim().toLowerCase()
  // Strip wrapping quotes / brackets
  s = s.replace(/^["'“”‘’<>[\](){}]+|["'“”‘’<>[\](){}]+$/g, '')
  s = s.replace(/\.\s*$/, '')
  s = s.replace(/,\s*$/, '')
  // v0.7.67: strip internal punctuation, hyphen-joiners, and leading "the"
  // so "Journal of Bone and Joint Surgery. British Volume" /
  // "Journal of Bone and Joint Surgery-british Volume" normalize equal.
  s = s.replace(/[\.,]/g, ' ')
  s = s.replace(/[-‐‑–—]/g, ' ')
  s = s.replace(/^the\s+/, '')
  s = s.replace(/\s+/g, ' ')
  return s.trim()
}

export function styleAcceptsAbbreviatedVenue(style) {
  if (!style) return true
  const policy = STYLE_VENUE_POLICY[String(style).trim().toLowerCase()]
  if (!policy) return true
  return !!policy.acceptsAbbrev
}

function _tokensPrefixMatch(citedTokens, fullTokens) {
  if (citedTokens.length < 2 || fullTokens.length < 2) return false
  if (Math.abs(citedTokens.length - fullTokens.length) > 1) return false
  let fIdx = 0
  for (const c of citedTokens) {
    if (fIdx >= fullTokens.length) return false
    if (!fullTokens[fIdx].toLowerCase().startsWith(c.toLowerCase())) return false
    fIdx += 1
  }
  return true
}

/**
 * Does the candidate acronym `acr` plausibly derive from the letters of
 * `full`? Walks through the concatenated full string and checks every
 * letter of `acr` appears in order. Lets us recognise things like
 * "AJNR" inside "American Journal of NeuroRadiology" without
 * enumerating every journal.
 */
function _isPlausibleAcronymOf(acr, fullTokens) {
  if (!acr || acr.length < 2 || acr.length > 8) return false
  if (!/^[a-z]+$/.test(acr)) return false
  const stream = fullTokens.join('').toLowerCase()
  let i = 0
  for (const ch of stream) {
    if (i >= acr.length) break
    if (ch === acr[i]) i += 1
  }
  return i === acr.length
}

function looksLikeWordAbbreviation(cited, full) {
  const citedTokens = cited.split(/\s+/).map(t => t.replace(/\.$/, '')).filter(Boolean)
  const fullTokens = full.split(/\s+/).filter(t => t && !STOPWORDS.has(t.toLowerCase()))
  if (_tokensPrefixMatch(citedTokens, fullTokens)) return true
  // Allow a leading "journal acronym" token in the cited string (e.g.
  // "AJNR" in "AJNR Am J Neuroradiol", "AJR" in "AJR Am J Roentgenol",
  // "JCI" in "JCI Insight"). Strip it and retry, but only when it
  // plausibly derives from the full title's letters — that gate stops
  // arbitrary leading garbage from matching.
  if (citedTokens.length >= 2 && _isPlausibleAcronymOf(citedTokens[0].toLowerCase(), fullTokens)) {
    if (_tokensPrefixMatch(citedTokens.slice(1), fullTokens)) return true
  }
  return false
}

/**
 * Is `cited` an acceptable NLM-style abbreviation of `full` under `style`?
 *
 * Returns true only when the active style permits abbreviated venues AND
 * the cited string normalises to a known NLM abbreviation whose full form
 * matches the database venue.
 */
export function isAcceptableAbbreviation(cited, full, style) {
  if (!cited || !full) return false
  if (!styleAcceptsAbbreviatedVenue(style)) return false

  const c = normalizeVenue(cited)
  const f = normalizeVenue(full)
  if (!c || !f) return false

  const expectedFull = NLM_ABBREV_TO_FULL[c]
  if (expectedFull && (expectedFull === f || f.includes(expectedFull))) return true

  // Reverse — cited might be the full and full is the abbreviation.
  for (const [abbrev, fullV] of Object.entries(NLM_ABBREV_TO_FULL)) {
    if (fullV === c && abbrev === f) return true
  }

  if (looksLikeWordAbbreviation(c, f)) return true
  if (looksLikeWordAbbreviation(f, c)) return true

  return false
}

/**
 * Pull cited + actual venue strings out of a warning details string of
 * the form: "Venue mismatch:\n  cited: 'X'\n  actual: 'Y'". Returns
 * null if the format doesn't match.
 */
export function parseVenueWarning(details) {
  if (!details) return null
  const citedMatch = details.match(/cited:\s*['"]?([^'"\n]+?)['"]?\s*$/m)
  const actualMatch = details.match(/actual:\s*['"]?([^'"\n]+?)['"]?\s*$/m)
  if (!citedMatch || !actualMatch) return null
  return { cited: citedMatch[1].trim(), actual: actualMatch[1].trim() }
}

/**
 * Reverse lookup: given a full journal name, return its NLM acronym
 * (uppercase-preserving canonical form) when one exists. Returns null
 * if the journal isn't in the bootstrap table.
 *
 * Display-only — the reference card calls this to show
 * "ANZ Journal of Surgery (ANZ J Surg)" so the user sees both forms
 * regardless of which one was cited.
 */
export function acronymFor(fullName) {
  if (!fullName) return null
  const f = normalizeVenue(fullName)
  if (!f) return null
  // The table values are full names; find the abbreviation key whose
  // value matches. Cap the iteration since the table is bounded.
  for (const [abbrev, full] of Object.entries(NLM_ABBREV_TO_FULL)) {
    if (full === f) return prettyCase(abbrev)
  }
  return null
}

/**
 * Reverse: given an abbreviation, return the canonical full name.
 * Lets the card surface the unabbreviated form when only the
 * acronym was cited.
 */
export function fullNameFor(abbrev) {
  if (!abbrev) return null
  const a = normalizeVenue(abbrev)
  if (!a) return null
  const full = NLM_ABBREV_TO_FULL[a]
  return full ? prettyCase(full) : null
}

/**
 * Title-case the table's lowercase keys/values for display, preserving
 * common all-caps tokens (JAMA, BMJ, IEEE, PNAS, MAG, etc.) and the
 * single-letter Roman numeral that occurs in some NLM titles.
 */
const _ALL_CAPS_TOKENS = new Set([
  'jama', 'bmj', 'ieee', 'pnas', 'mag', 'plos', 'anz', 'jnci', 'acl',
  'iclr', 'icml', 'nips', 'neurips', 'eurosys', 'nsdi', 'sosp', 'phys',
])
function prettyCase(s) {
  if (!s) return s
  return s.split(/\s+/).map(tok => {
    const lo = tok.toLowerCase()
    if (_ALL_CAPS_TOKENS.has(lo)) return lo.toUpperCase()
    if (lo.length <= 3 && /^[a-z]+$/.test(lo)) {
      // Single-letter / 2-letter alphabetic tokens like 'a', 'b' (NLM
      // journal-section letters): all-caps.
      return lo.toUpperCase()
    }
    return lo.charAt(0).toUpperCase() + lo.slice(1)
  }).join(' ')
}

/**
 * Decide whether a venue warning/correction should be hidden under
 * the currently active citation style. Returns true when the cited
 * venue is an acceptable abbreviation of the actual venue.
 */
export function shouldSuppressVenueWarning(warning, style) {
  if (!warning) return false
  const cited = warning.cited_value || warning.cited
  const actual = warning.actual_value || warning.actual || warning.ref_venue_correct
  if (cited && actual) {
    return isAcceptableAbbreviation(cited, actual, style)
  }
  // Fallback: try to parse from the details string.
  const details = warning.warning_details || warning.error_details || warning.message
  const parsed = parseVenueWarning(details)
  if (parsed) return isAcceptableAbbreviation(parsed.cited, parsed.actual, style)
  return false
}
