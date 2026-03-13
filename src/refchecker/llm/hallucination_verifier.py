"""LLM-based hallucination verifier for reference checking.

The LLM receives the full reference metadata plus all validation errors
detected by the checkers, and determines whether the reference is likely
fabricated (LIKELY), genuine (UNLIKELY), or unclear (UNCERTAIN).

When using OpenAI, the verifier uses the Responses API with the
``web_search_preview`` tool so the LLM can search the web during its
assessment.  For non-OpenAI endpoints or when the Responses API is
unavailable the verifier falls back to plain chat completions.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from refchecker.config.settings import resolve_api_key, resolve_endpoint

logger = logging.getLogger(__name__)


_ASSESSMENT_SYSTEM_PROMPT = """\
You are an academic-integrity assistant that determines whether a cited \
reference is likely **hallucinated** (fabricated by an AI).

IMPORTANT: Use web search to look up the paper title and authors before \
rendering your verdict. Search for the exact title in quotes on the web \
to check whether the paper actually exists. This is critical — do NOT \
rely solely on the metadata provided; verify it against the open web.

Reply with EXACTLY one of these verdicts on the FIRST line:
  LIKELY    — this reference is probably fabricated
  UNLIKELY  — this reference is probably real despite the errors
  UNCERTAIN — cannot determine with confidence

Then on the following lines, give a concise explanation (2-3 sentences max). \
If you found the paper via web search, include the URL(s) where it appears."""

_ASSESSMENT_PROMPT = """\
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
First, search the web for the exact paper title (in quotes) to check whether \
this paper actually exists. Then, based on both the web search results AND \
the validation errors above, determine whether this reference is a \
hallucinated (fabricated) citation.

Key signals of hallucination:
- The reference could not be found in ANY academic database (Semantic Scholar, \
OpenAlex, CrossRef, DBLP, arXiv)
- A web search for the exact title returns no matching results
- Authors are obviously fake ("John Doe", "Jane Smith") or don't work in the \
cited field
- The ArXiv ID or DOI points to a completely different paper
- The title sounds generic/buzzwordy with no specific contribution
- Multiple major metadata fields conflict with what databases found

Key signals that it is NOT hallucinated:
- The paper was found via web search or verified in a database, even with \
minor metadata errors
- Year off-by-one, venue abbreviation differences, or author name formatting \
differences are common in real citations and NOT signs of hallucination
- Author count mismatches where the names mostly overlap are NOT hallucination

Reply with your verdict on the FIRST line (LIKELY, UNLIKELY, or UNCERTAIN) \
followed by your concise explanation (2-3 sentences max)."""

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
        self._use_responses_api = False

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
                # Use the Responses API (with web_search_preview) when available.
                # Custom endpoints may not support it, so probe and fall back.
                if not self.endpoint:
                    self._use_responses_api = True
                logger.debug(
                    'LLM hallucination verifier initialized '
                    '(model=%s, web_search=%s)',
                    self.model, self._use_responses_api,
                )
            except ImportError:
                logger.warning('openai package not installed — LLM verification disabled')

    @property
    def available(self) -> bool:
        return self.client is not None

    def _call_with_web_search(self, system_prompt: str, user_prompt: str) -> tuple:
        """Call the LLM via the Responses API with web search enabled.

        Returns (response_text, web_urls) where web_urls is a list of
        URLs cited by the model from its web search results.
        """
        resp = self.client.responses.create(
            model=self.model,
            instructions=system_prompt,
            tools=[{'type': 'web_search_preview'}],
            input=user_prompt,
        )

        text_parts: List[str] = []
        web_urls: List[str] = []
        seen_urls: set = set()

        for item in resp.output:
            content = getattr(item, 'content', None)
            if not content:
                continue
            for block in content:
                text = getattr(block, 'text', '') or ''
                if text:
                    text_parts.append(text)
                for ann in getattr(block, 'annotations', []):
                    url = getattr(ann, 'url', '') or ''
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        web_urls.append(url)

        return '\n'.join(text_parts).strip(), web_urls

    def _call_chat(self, system_prompt: str, user_prompt: str) -> tuple:
        """Fallback: plain chat completions without web search."""
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            max_tokens=300,
            temperature=0.0,
        )
        return (resp.choices[0].message.content or '').strip(), []

    def _call(self, system_prompt: str, user_prompt: str) -> tuple:
        """Call the LLM, using web search when available.

        Returns (response_text, web_urls).
        """
        if self._use_responses_api:
            try:
                return self._call_with_web_search(system_prompt, user_prompt)
            except Exception as exc:
                logger.debug('Responses API failed, falling back to chat: %s', exc)
                self._use_responses_api = False
        return self._call_chat(system_prompt, user_prompt)

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
        year = error_entry.get('ref_year_cited') or ''
        # Never send "0" as year to the LLM — treat it as unknown
        if str(year).strip() in ('0', ''):
            year = '(unknown)'
        url = error_entry.get('ref_url_cited', '')

        # Build a human-readable summary of validation errors
        validation_lines = self._build_validation_summary(error_entry)

        import datetime
        today = datetime.date.today().isoformat()

        user_prompt = _ASSESSMENT_PROMPT.format(
            title=title,
            authors=authors,
            venue=venue,
            year=year,
            url=url or '(none)',
            today=today,
            validation_summary=validation_lines or 'No specific errors detected.',
        )

        try:
            response, web_urls = self._call(_ASSESSMENT_SYSTEM_PROMPT, user_prompt)
            verdict, explanation = self._parse_verdict(response)
        except Exception as exc:
            logger.warning(f'LLM hallucination assessment failed: {exc}')
            return {
                'verdict': 'UNCERTAIN',
                'explanation': f'LLM call failed: {exc}',
                'web_search': None,
            }

        # Build web_result from inline web search URLs if the LLM found any
        web_result = None
        if web_urls:
            web_result = {
                'found': verdict == 'UNLIKELY',
                'academic_urls': web_urls[:5],
                'provider': 'openai_responses',
            }

        # Fallback: use separate web searcher if the LLM didn't do its own
        # web search (e.g. non-OpenAI endpoint) and verdict is ambiguous
        if not web_urls and web_searcher and web_searcher.available and verdict != 'UNLIKELY':
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
