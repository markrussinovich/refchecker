"""Utilities for classifying high-confidence hallucination-like reference issues."""

from __future__ import annotations

from typing import Any, Dict, List


def _count_cited_authors(cited_authors: str) -> int:
	if not cited_authors:
		return 0
	return len([author for author in cited_authors.split(',') if author.strip()])


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

	if error_type == 'unverified':
		reasons.append('unverified')
		score += 0.45
		if has_rich_metadata:
			reasons.append('rich_metadata_not_found')
			score += 0.2

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

	if error_type in {'year', 'venue', 'url'} and score > 0:
		score = max(0.0, score - 0.1)

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
