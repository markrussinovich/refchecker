"""LLM-based hallucination verifier for reference checking.

The LLM receives the full reference metadata plus all validation errors
detected by the checkers, and determines whether the reference is likely
fabricated (LIKELY), genuine (UNLIKELY), or unclear (UNCERTAIN).

If web search is available, the LLM first decides whether a search would
provide a useful additional signal. Minor author-name or year mismatches
don't warrant a search; unverified references with plausible metadata do.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from refchecker.config.settings import resolve_api_key, resolve_endpoint

logger = logging.getLogger(__name__)


_ASSESSMENT_PROMPT = """\
You are an academic-integrity assistant that determines whether a cited \
reference is likely **hallucinated** (fabricated by an AI).

Today's date is {today}.

## Reference metadata
Title:   {title}
Authors: {authors}
Venue:   {venue}
Year:    {year}
URL:     {url}

## Validation results from automated checkers
{validation_summary}

## Instructions
Based on the reference metadata and the validation errors above, determine \
whether this reference is a hallucinated (fabricated) citation.

Key signals of hallucination:
- The reference could not be found in ANY academic database (Semantic Scholar, \
OpenAlex, CrossRef, DBLP, arXiv)
- Authors are obviously fake ("John Doe", "Jane Smith") or don't work in the \
cited field
- The ArXiv ID or DOI points to a completely different paper
- The title sounds generic/buzzwordy with no specific contribution
- Multiple major metadata fields conflict with what databases found

Key signals that it is NOT hallucinated:
- The paper was found and verified, even with minor metadata errors
- Year off-by-one, venue abbreviation differences, or author name formatting \
differences are common in real citations and NOT signs of hallucination
- Author count mismatches where the names mostly overlap are NOT hallucination

Reply with EXACTLY one of these verdicts on the FIRST line:
  LIKELY    — this reference is probably fabricated
  UNLIKELY  — this reference is probably real despite the errors
  UNCERTAIN — cannot determine with confidence

Then on the following lines, give a concise explanation (2-3 sentences max)."""

_WEB_SEARCH_DECISION_PROMPT = """\
Given this reference that could not be verified by academic databases:
Title:   {title}
Authors: {authors}
Year:    {year}

Errors: {errors}

Would a web search provide useful additional signal to determine if this is \
a hallucinated reference? Answer YES or NO on the first line.
Only answer YES for references that are unverified or have major conflicts. \
Minor author-name or year differences do NOT warrant a search."""


class LLMHallucinationVerifier:
    """LLM-based hallucination verifier.

    Requires an OpenAI-compatible API key. Uses a single prompt to
    evaluate the reference + its validation errors.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        model: str = 'gpt-4.1-mini',
    ):
        self.api_key = api_key or resolve_api_key('openai')
        self.endpoint = endpoint or resolve_endpoint('openai')
        self.model = model
        self.client = None

        if self.api_key:
            try:
                import openai
                kwargs: Dict[str, Any] = {'api_key': self.api_key}
                if self.endpoint:
                    base = self.endpoint
                    for suffix in ('/chat/completions', '/completions'):
                        if base.endswith(suffix):
                            base = base[: -len(suffix)]
                    kwargs['base_url'] = base
                self.client = openai.OpenAI(**kwargs)
                logger.debug(f'LLM hallucination verifier initialized (model={self.model})')
            except ImportError:
                logger.warning('openai package not installed — LLM verification disabled')

    @property
    def available(self) -> bool:
        return self.client is not None

    def _call(self, prompt: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=300,
            temperature=0.0,
        )
        return (resp.choices[0].message.content or '').strip()

    def assess(
        self,
        error_entry: Dict[str, Any],
        web_searcher: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Assess whether a reference is likely hallucinated.

        Parameters
        ----------
        error_entry : dict
            Consolidated error entry with reference metadata and errors.
        web_searcher : optional
            Web search checker; used only if the LLM recommends a search.

        Returns
        -------
        dict with verdict, explanation, and optional web_search results.
        """
        if not self.available:
            return {
                'verdict': 'UNCERTAIN',
                'explanation': 'LLM not available.',
                'web_search': None,
            }

        title = error_entry.get('ref_title', '')
        authors = error_entry.get('ref_authors_cited', '')
        orig = error_entry.get('original_reference', {})
        venue = orig.get('venue', orig.get('journal', '')) or ''
        year = error_entry.get('ref_year_cited', '')
        url = error_entry.get('ref_url_cited', '')

        # Build a human-readable summary of validation errors
        validation_lines = self._build_validation_summary(error_entry)

        import datetime
        today = datetime.date.today().isoformat()

        prompt = _ASSESSMENT_PROMPT.format(
            title=title,
            authors=authors,
            venue=venue,
            year=year,
            url=url or '(none)',
            today=today,
            validation_summary=validation_lines or 'No specific errors detected.',
        )

        try:
            response = self._call(prompt)
            verdict, explanation = self._parse_verdict(response)
        except Exception as exc:
            logger.warning(f'LLM hallucination assessment failed: {exc}')
            return {
                'verdict': 'UNCERTAIN',
                'explanation': f'LLM call failed: {exc}',
                'web_search': None,
            }

        # Optionally run web search for additional signal
        web_result = None
        if web_searcher and web_searcher.available and verdict != 'UNLIKELY':
            if self._should_web_search(error_entry):
                try:
                    web_result = web_searcher.check_reference_exists(error_entry)
                    # Let web search influence the verdict
                    web_verdict = web_result.get('verdict', '')
                    if web_verdict == 'EXISTS' and verdict == 'UNCERTAIN':
                        verdict = 'UNLIKELY'
                        explanation += ' (Web search found the paper.)'
                    elif web_verdict == 'NOT_FOUND' and verdict == 'UNCERTAIN':
                        verdict = 'LIKELY'
                        explanation += ' (Web search also found no evidence this paper exists.)'
                except Exception as exc:
                    logger.debug(f'Web search during assessment failed: {exc}')

        logger.debug(
            'Hallucination assessment: title=%r verdict=%s explanation=%s',
            title[:60], verdict, explanation[:100],
        )

        return {
            'verdict': verdict,
            'explanation': explanation,
            'web_search': web_result,
        }

    def _build_validation_summary(self, error_entry: Dict[str, Any]) -> str:
        """Build a human-readable summary of validation errors for the prompt."""
        error_type = error_entry.get('error_type', '')
        error_details = error_entry.get('error_details', '')

        lines = []
        if error_type == 'unverified':
            lines.append('- Reference could NOT be found in any academic database '
                         '(Semantic Scholar, OpenAlex, CrossRef, DBLP, arXiv)')
        elif error_type == 'multiple':
            lines.append('- Multiple issues detected:')
            for detail in error_details.split('\n'):
                detail = detail.strip()
                if detail.startswith('- '):
                    lines.append(f'  {detail}')
                elif detail:
                    lines.append(f'  - {detail}')
        elif error_type and error_details:
            lines.append(f'- {error_type}: {error_details}')

        return '\n'.join(lines)

    def _should_web_search(self, error_entry: Dict[str, Any]) -> bool:
        """Decide if a web search would provide useful signal.

        Skip searches for minor mismatches (author formatting, year off-by-one).
        """
        error_type = (error_entry.get('error_type') or '').lower()
        if error_type == 'unverified':
            return True
        if error_type in ('doi', 'arxiv_id', 'arxiv'):
            return True
        if error_type == 'multiple':
            details = (error_entry.get('error_details') or '').lower()
            if 'title' in details or 'not found' in details:
                return True
        return False

    @staticmethod
    def _parse_verdict(response: str) -> tuple:
        """Parse the LLM response into verdict and explanation."""
        lines = response.strip().split('\n')
        first_line = lines[0].strip().upper() if lines else ''

        if 'LIKELY' in first_line and 'UNLIKELY' not in first_line:
            verdict = 'LIKELY'
        elif 'UNLIKELY' in first_line:
            verdict = 'UNLIKELY'
        else:
            verdict = 'UNCERTAIN'

        explanation = '\n'.join(lines[1:]).strip()
        if not explanation:
            # Use the full first line as explanation if no separate reasoning
            explanation = lines[0].strip() if lines else ''
        return verdict, explanation
