"""Utilities for classifying high-confidence hallucination-like reference issues."""

from __future__ import annotations

import re
from typing import Any, Dict, List


NON_SUSPICIOUS_UNVERIFIED_MARKERS = (
	'rate limit',
	'network error',
	'api error',
	'api failed',
	'http error',
	'could not fetch',
	'could not download',
	'could not extract pdf content',
	'pdf processing error',
	'internal processing error',
	'timeout',
	'timed out',
	'repository not found or is private',
	'no url provided',
	'paper not verified but url references paper',
)

# Trendy ML/AI buzzwords that appear disproportionately in hallucinated titles.
# A high density of these with no specific contribution marker is suspicious.
_BUZZWORDS = frozenset({
	'efficient', 'scalable', 'robust', 'adaptive', 'self-organizing',
	'cross-domain', 'multi-modal', 'multimodal', 'iterative', 'unified',
	'generalized', 'neural', 'deep', 'transformer', 'transformers',
	'representation', 'reinforcement', 'adversarial', 'contrastive',
	'federated', 'meta-learning', 'self-supervised', 'semi-supervised',
	'pre-training', 'pre-trained', 'fine-tuning', 'fine-tuned',
	'attention', 'graph', 'knowledge', 'distillation', 'pruning',
	'quantization', 'sparse', 'continual', 'curriculum', 'alignment',
})


def _count_cited_authors(cited_authors: str) -> int:
	if not cited_authors:
		return 0
	return len([author for author in cited_authors.split(',') if author.strip()])


def _is_non_suspicious_unverified(error_details: str) -> bool:
	if not error_details:
		return False
	return any(marker in error_details for marker in NON_SUSPICIOUS_UNVERIFIED_MARKERS)


_ARXIV_ID_PATTERN = re.compile(r'(\d{2})(\d{2})\.\d{4,5}')


def _check_arxiv_year_consistency(error_entry: Dict[str, Any]) -> int | None:
	"""Return the year implied by an arXiv ID, or None if no arXiv ID is present.

	ArXiv IDs since April 2007 follow the format YYMM.NNNNN where YY is the
	two-digit year and MM is the month. Comparing this to the cited year is a
	fully deterministic fabrication signal.
	"""
	for field in ('ref_url_cited', 'ref_paper_id'):
		value = error_entry.get(field) or ''
		m = _ARXIV_ID_PATTERN.search(value)
		if m:
			return 2000 + int(m.group(1))
	return None


def _title_buzzword_density(title: str) -> float:
	"""Return the fraction of words in `title` that are ML buzzwords.

	Hallucinated titles tend to be generic combinations of trendy terminology
	(e.g. "Self-Organizing Transformers for Cross-domain Representation Learning").
	Real titles usually contain specific system names, datasets, or claims.
	"""
	words = re.findall(r'[a-z]+(?:-[a-z]+)*', title.lower())
	if len(words) < 4:
		return 0.0
	buzz_count = sum(1 for w in words if w in _BUZZWORDS)
	return buzz_count / len(words)


def _has_many_authors(cited_authors: str) -> bool:
	"""Return True if the citation lists 3+ authors — a proxy for a plausible
	fabrication with realistic-looking authorship."""
	return _count_cited_authors(cited_authors) >= 3


def assess_hallucination_candidate(error_entry: Dict[str, Any]) -> Dict[str, Any]:
	"""Score a structured error entry for hallucination likelihood.

	The policy is intentionally conservative. It should elevate only strong signals
	like identifier conflicts, multi-field disagreements, or rich citations that no
	source can verify.
	"""
	error_type = (error_entry.get('error_type') or '').lower()
	error_details = (error_entry.get('error_details') or '').lower()
	reasons: List[str] = []
	score = 0.0

	title = (error_entry.get('ref_title') or '').strip()
	cited_authors = error_entry.get('ref_authors_cited') or ''
	author_count = _count_cited_authors(cited_authors)
	has_rich_metadata = bool(title and len(title) >= 20 and author_count >= 1)

	if error_type in {'api_failure', 'processing_failed'}:
		return {
			'candidate': False,
			'level': 'none',
			'score': 0.0,
			'reasons': ['verification_infrastructure_issue'],
		}

	if error_type == 'unverified':
		reasons.append('unverified')
		if _is_non_suspicious_unverified(error_details):
			reasons.append('verification_infrastructure_issue')
		else:
			score += 0.45
			if has_rich_metadata:
				reasons.append('rich_metadata_not_found')
				score += 0.2

			# Graduated non-existence confidence: the more independent databases
			# that returned negative, the higher our confidence this is fabricated.
			# With DBLP we now have up to 4+ sources (SS, OpenAlex, CrossRef, DBLP).
			sources_negative = error_entry.get('sources_negative', 0)
			if sources_negative >= 4:
				reasons.append('multi_source_negative_very_high')
				score += 0.20
			elif sources_negative >= 3:
				reasons.append('multi_source_negative_high')
				score += 0.15
			elif sources_negative == 2:
				reasons.append('multi_source_negative')
				score += 0.05

			# Title fabrication pattern: high buzzword density suggests a
			# generic "word salad" title typical of LLM hallucinations.
			if title:
				buzz = _title_buzzword_density(title)
				if buzz >= 0.5:
					reasons.append('high_buzzword_density')
					score += 0.10
				elif buzz >= 0.35:
					reasons.append('moderate_buzzword_density')
					score += 0.05

			# Rich author list on an unverifiable paper is a Frankenstein
			# hallucination signal (real-looking authors + fabricated title).
			if _has_many_authors(cited_authors):
				reasons.append('rich_author_list_unverified')
				score += 0.05

	if error_type in {'doi', 'arxiv_id', 'arxiv'}:
		reasons.append(f'{error_type}_conflict')
		score += 0.65

	if error_type in {'title', 'author'}:
		reasons.append(f'{error_type}_mismatch')
		score += 0.25

	if error_type == 'multiple':
		major_signals = 0
		for token, reason in [
			('title', 'title_mismatch'),
			('author', 'author_mismatch'),
			('doi', 'doi_conflict'),
			('arxiv', 'arxiv_conflict'),
		]:
			if token in error_details:
				major_signals += 1
				if reason not in reasons:
					reasons.append(reason)

		if major_signals >= 2:
			reasons.append('multiple_major_mismatches')
			score += 0.7
		elif major_signals == 1:
			score += 0.3

	# Dampen score when the *primary* error type is a weak signal.
	# For standalone year/venue/url errors score is already 0, so
	# this only fires when a weak type appears inside a 'multiple'
	# block or is combined with other signals in future rules.
	if error_type in {'year', 'venue', 'url'}:
		score = max(0.0, score - 0.1)

	# ArXiv ID year consistency: if the arXiv ID implies a different year
	# than the one cited, that is a deterministic fabrication signal.
	arxiv_year = _check_arxiv_year_consistency(error_entry)
	if arxiv_year is not None:
		cited_year = error_entry.get('ref_year_cited')
		if cited_year and str(cited_year).isdigit():
			year_diff = abs(arxiv_year - int(cited_year))
			if year_diff >= 2:
				reasons.append('arxiv_year_conflict')
				score += 0.3
			elif year_diff == 1:
				# Off-by-one is common (Dec submission → Jan publication)
				reasons.append('arxiv_year_minor_conflict')
				score += 0.05

	score = min(score, 1.0)

	if score >= 0.85:
		level = 'high'
	elif score >= 0.6:
		level = 'medium'
	elif score >= 0.35:
		level = 'low'
	else:
		level = 'none'

	return {
		'candidate': score >= 0.6,
		'level': level,
		'score': round(score, 2),
		'reasons': reasons,
	}
