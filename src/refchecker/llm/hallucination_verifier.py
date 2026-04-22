"""LLM-based hallucination verifier for reference checking.

The LLM receives the full reference metadata plus all validation errors
detected by the checkers, and determines whether the reference is likely
fabricated (LIKELY), genuine (UNLIKELY), or unclear (UNCERTAIN).

Supports any configured LLM provider (OpenAI, Anthropic, Google, Azure,
vLLM).  When using OpenAI without a custom endpoint, the verifier uses
the Responses API with the ``web_search_preview`` tool so the LLM can
search the web during its assessment.  For other providers the verifier
falls back to plain chat completions.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from refchecker.config.settings import resolve_api_key, resolve_endpoint, DEFAULT_HALLUCINATION_MODELS

logger = logging.getLogger(__name__)


_ASSESSMENT_SYSTEM_PROMPT = """\
You are an academic-integrity assistant that determines whether a cited \
reference is likely **hallucinated** (fabricated by an AI).

IMPORTANT: Use web search to look up the paper title and authors before \
rendering your verdict. Search for the exact title in quotes on the web \
to check whether the paper actually exists. This is critical — do NOT \
rely solely on the metadata provided; verify it against the open web.

Reply in EXACTLY this structured format (three lines only, no preamble):

VERDICT: <LIKELY|UNLIKELY|UNCERTAIN>
EXPLANATION: <1-2 sentence summary of your finding — NO URLs, NO search narration>
LINK: <URL where the exact paper was found, or NONE if not found>

Verdicts:
  LIKELY    — this reference is probably fabricated
  UNLIKELY  — this reference is probably real despite the errors
  UNCERTAIN — cannot determine with confidence

CRITICAL formatting rules:
- The EXPLANATION must be a short factual conclusion (1-2 sentences max).
- Do NOT narrate your search process (no "I searched for...", "Searching...", \
"Based on my web search...", "I'll search...").
- Do NOT embed URLs or markdown links in the EXPLANATION. Put the URL \
only in the LINK field.
- Start the EXPLANATION directly with your finding (e.g., "No paper with \
this exact title exists." or "The exact paper was found in Nature 2024.")."""

_ASSESSMENT_PROMPT = """\
## Reference metadata
Title:   {title}
Authors: {authors}
Venue:   {venue}
Year:    {year}
URL:     {url}

## Validation results from automated checkers
{validation_summary}

IMPORTANT CONTEXT: The automated checkers above have already searched \
Semantic Scholar, OpenAlex, CrossRef, DBLP, and arXiv for this reference. \
If they report it as unverified, the paper was NOT found in any of these \
databases. Do not contradict this unless your web search finds a page that \
shows the paper with the EXACT title listed above. However, if the \
validation summary says the paper WAS found but has metadata mismatches, \
the checkers may have matched a wrong edition or version — use your web \
search to verify the CITED title and authors independently.

## Instructions
Search the web for the exact paper title (in quotes) to check whether a \
paper with THIS SPECIFIC TITLE actually exists.

CRITICAL: Do NOT hallucinate or confabulate results. If your web search \
does not return a page containing the EXACT title \
\"{title}\", \
then the paper does not exist and the verdict must be LIKELY. Do not claim \
you found the paper if you actually found a DIFFERENT paper with a similar \
but not identical title.

WARNING: Finding this title mentioned as a CITATION inside another paper \
(e.g. on OpenReview, arXiv, or in a reference list) does NOT prove this \
paper exists. The paper must have its OWN dedicated page — a journal \
article page, arXiv entry, or academic database entry with this exact \
title as the primary title. A reference list merely shows someone cited \
it, not that it is real.

Key signals of hallucination (any ONE is sufficient for LIKELY):
- The reference was not found in any academic database (already confirmed above)
- Your web search does not return a page with this exact title
- Web search finds a similar but NOT identical paper (different title, \
different authors) — this is EVIDENCE of hallucination, not evidence the \
reference is real
- Authors are malformed (e.g. "O. T. et al. Unke")
- The ArXiv ID or DOI points to a completely different paper
- The paper title exists but the cited authors are COMPLETELY WRONG — \
i.e. NONE or almost none of the cited authors match the real authors. \
This is the most common form of AI hallucination: grafting a real paper \
title onto fabricated author names. Verdict MUST be LIKELY even though \
the paper itself is real, because the reference as cited is fabricated.

CRITICAL AUTHOR RULE: A reference with a real title but entirely \
fabricated authors is STILL a hallucinated reference. The verdict must \
be LIKELY. You may ONLY override this to UNLIKELY if you find a \
specific paper (with a URL you can cite in the LINK field) that has \
BOTH a matching title AND a substantially matching author list. \
Finding the title alone is NOT sufficient — the authors must also match. \
The ONLY exceptions where author mismatch is acceptable are:
  (a) Large collaborative papers (100+ authors) where the citation uses \
a team name (e.g. "Gemini Team", "Llama Team") instead of individual \
names — this is acceptable shorthand, verdict UNLIKELY.
  (b) Minor author-name formatting differences (initials vs full names, \
transliteration variants) — verdict UNLIKELY.
  (c) The paper has been revised and the author list changed between \
versions — verdict UNLIKELY if the cited authors match an earlier version.
  (d) The automated checker may have matched a DIFFERENT EDITION or \
VERSION of a work with the same title but different authors (e.g. two \
different textbooks titled "Convergence of Probability Measures" by \
different authors, or a database entry with incomplete author data). \
If your web search finds a paper/book with the CITED title AND the \
CITED authors, the checker simply matched the wrong edition — verdict \
UNLIKELY. Trust your own web search results over the checker's \
"correct" authors when they conflict.

Key signals that it is NOT hallucinated (verdict should be UNLIKELY):
- Your web search found a page showing a paper with this EXACT title AND \
the same authors (or substantially overlapping authors) — BOTH must match
- Year off-by-one with otherwise matching title and authors is acceptable
- Venue abbreviation differences are acceptable
- Team/consortium authorship shorthand for large collaborative papers
- The checker's "correct" authors differ from the cited authors, but your \
web search finds the paper with the CITED authors — the checker matched \
a wrong edition or has incomplete data. Trust your search over the checker.

CRITICAL: If the title matches but the authors are completely different, \
do NOT verdict UNLIKELY. A "grafted" reference (real title, fake authors) \
is hallucinated. Only override to UNLIKELY if you find a version of the \
paper where the cited authors actually appear as authors.

IMPORTANT: The following are NOT hallucinations — verdict MUST be UNLIKELY:

(1) TRUNCATED OR INCOMPLETE TITLES: If the title appears cut off or the \
reference is marked "incomplete" or "truncated", this is a PDF extraction \
or parsing failure, NOT an AI fabrication. If you can identify a real paper \
that the truncated title is a prefix of AND the authors match, verdict \
MUST be UNLIKELY. Even if you cannot identify the paper, an obviously \
truncated or incomplete reference should be UNCERTAIN, not LIKELY.

(2) GARBLED OR SWAPPED METADATA: If the title and author fields appear \
swapped, garbled, or contain data from the wrong field (e.g. the title \
field contains author names, or vice versa), this is a metadata extraction \
error, not hallucination. Verdict MUST be UNLIKELY if you can identify \
the real paper being referenced despite the garbled fields.

(3) MINOR AUTHOR NAME TYPOS: If a single-author or few-author paper has \
an author name that is a clear typo or OCR error of the real author \
(e.g. "J. Queen" instead of "J. MacQueen", or "Nestrov" instead of \
"Nesterov"), and the title matches a known paper, this is a human \
citation error, not AI hallucination. Verdict MUST be UNLIKELY.

(4) NON-ACADEMIC REAL-WORLD SOURCES: References to competitions, datasets, \
ethics codes, standards documents, technical blog posts, software tools, \
or other real-world non-paper sources (e.g. "American Invitational \
Mathematics Examination", "SPJ Code of Ethics", "Gemini CLI") are valid \
citations even though they are not academic papers. If the cited source \
is a real, identifiable entity, verdict MUST be UNLIKELY regardless of \
whether it appears in academic databases.

(5) INFORMAL OR COLLOQUIAL TITLES: If an author uses a widely recognized \
informal name for a paper or model (e.g. "Llama" instead of the full \
"The Llama 3 Herd of Models"), and the authors substantially match, \
this is a citation style choice, not hallucination. Verdict UNLIKELY.

Be strict: if this title was not found in any academic database and your \
web search does not find this exact title, the verdict MUST be LIKELY. \
If the title exists but the authors are completely different, the verdict \
MUST also be LIKELY.

Reply in EXACTLY this format:

VERDICT: <LIKELY|UNLIKELY|UNCERTAIN>
EXPLANATION: <concise 2-3 sentence explanation — do NOT include URLs here>
LINK: <URL of the exact paper if found, or NONE>

CRITICAL EVIDENCE RULE: You MUST only verdict UNLIKELY if your web \
search returned a result page whose title matches the CITED title \
above. If your search returned no results, or only returned pages \
with similar-but-different titles, the verdict MUST be LIKELY or \
UNCERTAIN — never UNLIKELY. Do not rely on your parametric knowledge \
to claim a paper exists; provide the URL in the LINK field as proof. \
An UNLIKELY verdict without a valid LINK is always wrong.
EXCEPTION: If the validation summary above says a paper with this \
title WAS found in an academic database (i.e. the checker matched it \
and provided a verified URL), then the paper exists — even if your web \
search cannot find it. In that case, base your verdict on the metadata \
quality (title/author match) not on web-search findability.

ARXIV ID WARNING: If the reference includes an arXiv URL/ID, and the \
automated checkers report that the arXiv ID points to a DIFFERENT paper, \
then the arXiv ID is wrong. Do NOT use that arXiv URL in the LINK field — \
it does not prove this paper exists. Search for the paper BY TITLE instead. \
If your search only finds the DIFFERENT paper at that arXiv ID, the \
cited reference is fabricated and the verdict MUST be LIKELY.

VERIFICATION REQUIREMENT: Before writing UNLIKELY, ask yourself: \
"Did my search results contain a page where the PRIMARY title (not a \
citation in another paper's reference list) exactly matches the cited \
title?" If you cannot answer yes, the verdict must be LIKELY."""

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


def build_assessment_prompt(error_entry: dict) -> tuple:
    """Build the (system_prompt, user_prompt) for hallucination assessment.

    This is the single source of truth for prompt construction so CLI,
    bulk, and WebUI all produce identical cache keys for the same input.
    """
    title = error_entry.get('ref_title', '')
    authors = error_entry.get('ref_authors_cited', '')
    orig = error_entry.get('original_reference', {})
    venue = orig.get('venue', orig.get('journal', '')) or ''
    year = error_entry.get('ref_year_cited') or ''
    if str(year).strip() in ('0', ''):
        year = '(unknown)'
    url = error_entry.get('ref_url_cited', '')

    validation_lines = _build_validation_summary_static(error_entry)

    user_prompt = _ASSESSMENT_PROMPT.format(
        title=title,
        authors=authors,
        venue=venue,
        year=year,
        url=url or '(none)',
        validation_summary=validation_lines or 'No specific errors detected.',
    )
    return _ASSESSMENT_SYSTEM_PROMPT, user_prompt


def _build_validation_summary_static(error_entry: dict) -> str:
    """Build a human-readable summary of validation errors for the prompt.

    Standalone version of LLMHallucinationVerifier._build_validation_summary
    so the prompt can be built without a verifier instance (for caching).
    """
    error_type = error_entry.get('error_type', '')
    error_details = error_entry.get('error_details', '')

    lines = []
    if error_type == 'unverified':
        url = error_entry.get('ref_url_cited', '')
        if url and 'arxiv.org' in url:
            lines.append(
                '- Reference could NOT be found in any academic database '
                '(Semantic Scholar, OpenAlex, CrossRef, DBLP, arXiv).\n'
                '  NOTE: The cited ArXiv URL points to a COMPLETELY DIFFERENT '
                'paper — the URL is likely fabricated along with the rest of '
                'the reference. Search for the cited TITLE to determine if '
                'the paper exists at all.'
            )
        else:
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
        # For verified refs, add context that the paper WAS found
        if error_entry.get('ref_verified_url'):
            lines.append(
                '\n  NOTE: Despite these issues, a paper with this title WAS '
                'found in an academic database. The metadata mismatches may '
                'indicate the checker matched a different edition, version, '
                'or a different paper with the same title. Use web search to '
                'verify whether the CITED title + authors combination exists.'
            )
    elif error_type and error_details:
        lines.append(f'- {error_type}: {error_details}')

    return '\n'.join(lines)


class LLMHallucinationVerifier:
    """LLM-based hallucination verifier.

    Supports OpenAI, Anthropic, Google, Azure, and vLLM providers.
    When using OpenAI (without a custom endpoint), the Responses API with
    ``web_search_preview`` is used so the LLM can verify references against
    the live web.  All other providers use a standard chat completion.
    """

    # Default models per provider (used when caller doesn't specify)
    _DEFAULT_MODELS = DEFAULT_HALLUCINATION_MODELS

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
    ):
        # Resolve provider — fall back to 'openai' if not specified
        self.provider = (provider or 'openai').lower()
        self.api_key = api_key or resolve_api_key(self.provider)
        self.endpoint = endpoint or resolve_endpoint(self.provider)
        self.model = model or self._DEFAULT_MODELS.get(self.provider, DEFAULT_HALLUCINATION_MODELS['openai'])
        self.client = None
        self._use_responses_api = False

        if not self.api_key:
            logger.debug('No API key for hallucination verifier (provider=%s)', self.provider)
            return

        try:
            if self.provider == 'anthropic':
                self._init_anthropic()
            elif self.provider == 'google':
                self._init_google()
            else:
                # OpenAI, Azure, vLLM all use the OpenAI client
                self._init_openai()
        except ImportError as exc:
            logger.warning('Provider package not installed for hallucination verifier: %s', exc)
        except Exception as exc:
            logger.warning('Failed to init hallucination verifier: %s', exc)

    def _init_openai(self) -> None:
        import openai
        kwargs: Dict[str, Any] = {'api_key': self.api_key}
        if self.endpoint:
            base = self.endpoint
            for suffix in ('/chat/completions', '/completions'):
                if base.endswith(suffix):
                    base = base[: -len(suffix)]
            kwargs['base_url'] = base
        self.client = openai.OpenAI(**kwargs)
        # Use Responses API (with web_search_preview) only for vanilla OpenAI
        if not self.endpoint and self.provider == 'openai':
            self._use_responses_api = True
        logger.debug(
            'Hallucination verifier initialized (provider=%s, model=%s, web_search=%s)',
            self.provider, self.model, self._use_responses_api,
        )

    def _init_anthropic(self) -> None:
        import anthropic
        self.client = anthropic.Anthropic(
            api_key=self.api_key,
            timeout=120.0,  # 2 min timeout (web search calls can be slow)
        )
        logger.debug(
            'Hallucination verifier initialized (provider=anthropic, model=%s)',
            self.model,
        )

    def _init_google(self) -> None:
        from google import genai
        self.client = genai.Client(api_key=self.api_key)
        logger.debug(
            'Hallucination verifier initialized (provider=google, model=%s)',
            self.model,
        )

    @property
    def available(self) -> bool:
        return self.client is not None

    # ------------------------------------------------------------------
    # OpenAI call paths
    # ------------------------------------------------------------------

    def _call_openai_with_web_search(self, system_prompt: str, user_prompt: str) -> tuple:
        """OpenAI Responses API with web_search_preview tool."""
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

    def _call_openai_chat(self, system_prompt: str, user_prompt: str) -> tuple:
        """OpenAI / Azure / vLLM chat completions (no web search)."""
        from refchecker.llm.providers import _openai_token_kwargs, _is_openai_reasoning_model
        kwargs = dict(
            model=self.model,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            **_openai_token_kwargs(self.model, 300)
        )
        if not _is_openai_reasoning_model(self.model):
            kwargs['temperature'] = 0.0
        resp = self.client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or '').strip(), []

    # ------------------------------------------------------------------
    # Anthropic call paths
    # ------------------------------------------------------------------

    def _call_anthropic_with_web_search(self, system_prompt: str, user_prompt: str) -> tuple:
        """Anthropic with web_search tool (Citations API)."""
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=[{
                'type': 'text',
                'text': system_prompt,
                'cache_control': {'type': 'ephemeral'},
            }],
            tools=[{
                'type': 'web_search_20250305',
                'name': 'web_search',
                'max_uses': 3,
            }],
            messages=[{'role': 'user', 'content': user_prompt}],
        )

        text_parts: List[str] = []
        web_urls: List[str] = []
        seen_urls: set = set()

        for block in resp.content:
            block_type = getattr(block, 'type', '')
            if block_type == 'text':
                text = getattr(block, 'text', '') or ''
                if text:
                    text_parts.append(text)
                # Extract cited URLs from inline citations (may be None)
                for citation in getattr(block, 'citations', None) or []:
                    url = getattr(citation, 'url', '') or ''
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        web_urls.append(url)
            elif block_type == 'web_search_tool_result':
                # Extract URLs from web search results
                for result in getattr(block, 'content', None) or []:
                    url = getattr(result, 'url', '') or ''
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        web_urls.append(url)

        return '\n'.join(text_parts).strip(), web_urls

    def _call_anthropic_chat(self, system_prompt: str, user_prompt: str) -> tuple:
        """Anthropic without web search."""
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=300,
            system=[{
                'type': 'text',
                'text': system_prompt,
                'cache_control': {'type': 'ephemeral'},
            }],
            messages=[{'role': 'user', 'content': user_prompt}],
        )
        text = ''
        for block in resp.content:
            if getattr(block, 'type', '') == 'text':
                text += getattr(block, 'text', '')
        return text.strip(), []

    # ------------------------------------------------------------------
    # Google call paths
    # ------------------------------------------------------------------

    def _call_google_with_web_search(self, system_prompt: str, user_prompt: str) -> tuple:
        """Google Gemini with google_search grounding.

        Uses the ``GoogleSearch`` tool which enables Google Search
        grounding so the model can verify references against the live web.
        """
        from google.genai import types

        google_search_tool = types.Tool(google_search=types.GoogleSearch())
        resp = self.client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=[google_search_tool],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )

        text = resp.text or ''
        web_urls: List[str] = []
        # Extract grounding URLs from metadata if available
        for candidate in getattr(resp, 'candidates', []):
            grounding = getattr(candidate, 'grounding_metadata', None)
            if grounding:
                # Log the full grounding metadata for debugging
                logger.debug('Gemini grounding_metadata: %s', grounding)

                # Log grounding supports (confidence scores per segment)
                supports = getattr(grounding, 'grounding_supports', None)
                if supports:
                    for i, support in enumerate(supports):
                        segment = getattr(support, 'segment', None)
                        seg_text = getattr(segment, 'text', '')[:120] if segment else ''
                        confidence = getattr(support, 'confidence_scores', [])
                        indices = getattr(support, 'grounding_chunk_indices', [])
                        logger.debug(
                            'Gemini grounding support[%d]: segment=%r confidence=%s chunk_indices=%s',
                            i, seg_text, confidence, indices,
                        )

                # Log web search queries used
                web_queries = getattr(grounding, 'web_search_queries', None)
                if web_queries:
                    logger.debug('Gemini web_search_queries: %s', web_queries)

                for chunk in (getattr(grounding, 'grounding_chunks', None) or []):
                    web_info = getattr(chunk, 'web', None)
                    if web_info:
                        url = getattr(web_info, 'uri', '') or ''
                        title = getattr(web_info, 'title', '') or ''
                        if url:
                            web_urls.append(url)
                            logger.debug('Gemini grounding chunk: url=%s title=%s', url, title)
                # Fallback: extract search result URLs from search_entry_point
                # when grounding_chunks is empty (common with lighter models)
                search_entry = getattr(grounding, 'search_entry_point', None)
                if search_entry and not web_urls:
                    import re as _re
                    rendered = getattr(search_entry, 'rendered_content', '') or ''
                    # Extract href URLs from chip links in the rendered HTML
                    for match in _re.finditer(r'href="(https?://[^"]+)"', rendered):
                        chip_url = match.group(1)
                        if chip_url not in web_urls:
                            web_urls.append(chip_url)
                            logger.debug('Gemini search entry chip URL: %s', chip_url[:120])
                if search_entry:
                    logger.debug('Gemini search entry present (rendered_content: %d chars)',
                                 len(getattr(search_entry, 'rendered_content', '') or ''))

        if web_urls:
            logger.debug('Gemini grounding returned %d URLs', len(web_urls))
        else:
            logger.debug('Gemini grounding returned NO URLs — response is ungrounded')

        return text.strip(), web_urls

    def _call_google_chat(self, system_prompt: str, user_prompt: str) -> tuple:
        """Google Gemini without web search."""
        from google.genai import types
        resp = self.client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        return (resp.text or '').strip(), []

    # ------------------------------------------------------------------
    # Unified dispatch
    # ------------------------------------------------------------------

    def _call(self, system_prompt: str, user_prompt: str) -> tuple:
        """Call the configured LLM, using web search when available.

        Returns (response_text, web_urls).  Results are cached when
        ``self.cache_dir`` is set so repeated runs skip the LLM call.
        """
        # Check cache
        cache_dir = getattr(self, 'cache_dir', None)
        if cache_dir:
            from refchecker.utils.cache_utils import cached_llm_response, cache_llm_response
            hit = cached_llm_response(cache_dir, self.model, system_prompt, user_prompt)
            if hit is not None:
                return hit['text'], hit.get('web_urls', [])

        text, urls = self._call_uncached(system_prompt, user_prompt)

        if cache_dir:
            cache_llm_response(cache_dir, self.model, system_prompt, user_prompt,
                               response={'text': text, 'web_urls': urls})
        return text, urls

    def _call_uncached(self, system_prompt: str, user_prompt: str) -> tuple:
        """Actually call the LLM (no caching)."""
        if self.provider == 'anthropic':
            try:
                return self._call_anthropic_with_web_search(system_prompt, user_prompt)
            except Exception as exc:
                logger.debug('Anthropic web search failed, falling back to chat: %s', exc)
                return self._call_anthropic_chat(system_prompt, user_prompt)

        if self.provider == 'google':
            try:
                return self._call_google_with_web_search(system_prompt, user_prompt)
            except Exception as exc:
                logger.debug('Google web search failed, falling back to chat: %s', exc)
                return self._call_google_chat(system_prompt, user_prompt)

        # OpenAI, Azure, vLLM
        if self._use_responses_api:
            try:
                return self._call_openai_with_web_search(system_prompt, user_prompt)
            except Exception as exc:
                logger.debug('Responses API failed, falling back to chat: %s', exc)
                self._use_responses_api = False
        return self._call_openai_chat(system_prompt, user_prompt)

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
        system_prompt, user_prompt = build_assessment_prompt(error_entry)

        # Check LLM cache before requiring a live client — allows
        # cached results to be used even when no API key is configured.
        cache_dir = getattr(self, 'cache_dir', None)
        if cache_dir and self.model:
            from refchecker.utils.cache_utils import cached_llm_response
            hit = cached_llm_response(cache_dir, self.model, system_prompt, user_prompt)
            if hit is not None:
                verdict, explanation, paper_link = self._parse_verdict(hit['text'])
                return {
                    'verdict': verdict,
                    'explanation': explanation,
                    'link': paper_link,
                    'web_search': {'found': bool(hit.get('web_urls')),
                                   'academic_urls': hit.get('web_urls', []),
                                   'provider': self.provider} if hit.get('web_urls') else None,
                }

        if not self.available:
            return {
                'verdict': 'UNCERTAIN',
                'explanation': 'LLM not available.',
                'web_search': None,
            }

        try:
            response, web_urls = self._call(system_prompt, user_prompt)
            verdict, explanation, paper_link = self._parse_verdict(response)
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
                'found': bool(web_urls),
                'academic_urls': web_urls[:5],
                'provider': self.provider,
            }
            # Note: we do NOT auto-override LIKELY just because web search
            # returned URLs. The URLs may point to similar-but-different
            # papers. The LLM's verdict already accounts for web results.

        # Fallback: use separate web searcher if the LLM didn't do its own
        # web search (e.g. non-OpenAI endpoint) and verdict is ambiguous
        if not web_urls and web_searcher and web_searcher.available and verdict != 'UNLIKELY':
            if self._should_web_search(error_entry):
                try:
                    web_result = web_searcher.check_reference_exists(error_entry)
                    # Let web search influence the verdict — grounded URL
                    # evidence is stronger than an LLM guess.
                    web_verdict = web_result.get('verdict', '')
                    if web_verdict == 'EXISTS' and verdict in ('UNCERTAIN', 'LIKELY'):
                        verdict = 'UNLIKELY'
                        explanation += ' (Web search found the paper.)'
                    elif web_verdict == 'NOT_FOUND' and verdict == 'UNCERTAIN':
                        verdict = 'LIKELY'
                        explanation += ' (Web search also found no evidence this paper exists.)'
                except Exception as exc:
                    logger.debug(f'Web search during assessment failed: {exc}')

        # Post-hoc consistency check: only override LIKELY if the
        # explanation explicitly confirms the EXACT paper was found with
        # matching title and authors.  Phrases like "a similar paper was
        # published in" should NOT override the verdict.
        if verdict == 'LIKELY':
            explanation_lower = explanation.lower()
            # Only override for strong, unambiguous confirmation of the exact paper
            exact_match_signals = (
                'the exact paper was found',
                'this exact paper exists',
                'confirmed the exact reference',
            )
            if any(signal in explanation_lower for signal in exact_match_signals):
                verdict = 'UNLIKELY'
                explanation += ' (Verdict corrected: explanation confirms exact paper was found.)'

        logger.debug(
            'Hallucination assessment: title=%r verdict=%s explanation=%s',
            error_entry.get('ref_title', '')[:60], verdict, explanation[:100],
        )

        return {
            'verdict': verdict,
            'explanation': explanation,
            'link': paper_link,
            'web_search': web_result,
        }

    def _build_validation_summary(self, error_entry: Dict[str, Any]) -> str:
        """Build a human-readable summary of validation errors for the prompt."""
        return _build_validation_summary_static(error_entry)

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
        """Parse the LLM response into (verdict, explanation, link).

        Expects structured format:
            VERDICT: LIKELY|UNLIKELY|UNCERTAIN
            EXPLANATION: ...
            LINK: <url> | NONE

        Falls back to unstructured parsing if the format isn't followed.
        """
        import re
        text = response.strip()

        verdict = 'UNCERTAIN'
        explanation = ''
        link = None

        # Try structured format first
        verdict_match = re.search(r'^VERDICT:\s*(LIKELY|UNLIKELY|UNCERTAIN)', text, re.IGNORECASE | re.MULTILINE)
        explanation_match = re.search(r'^EXPLANATION:\s*(.+?)(?=^LINK:|\Z)', text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        link_match = re.search(r'^LINK:\s*(.+)', text, re.IGNORECASE | re.MULTILINE)

        if verdict_match:
            verdict = verdict_match.group(1).strip().upper()

        if explanation_match:
            explanation = explanation_match.group(1).strip()
        else:
            # Fallback: use full text minus verdict/link lines as explanation
            lines = [l for l in text.splitlines()
                     if not re.match(r'^(VERDICT|LINK):', l, re.IGNORECASE)]
            explanation = ' '.join(lines).strip()

        if link_match:
            raw_link = link_match.group(1).strip()
            if raw_link.upper() != 'NONE':
                # Extract URL from markdown link syntax [text](url) or plain URL
                md_match = re.search(r'\[.*?\]\((https?://\S+?)\)', raw_link)
                if md_match:
                    link = md_match.group(1).rstrip('.)')
                else:
                    url_extract = re.search(r'(https?://\S+)', raw_link)
                    link = url_extract.group(1).rstrip('.)') if url_extract else None

        # Fallback verdict: if structured parse missed it, scan for keywords
        if not verdict_match:
            last_word = text.split()[-1].strip('.,;:!?').upper() if text else ''
            if last_word in ('UNLIKELY', 'LIKELY', 'UNCERTAIN'):
                verdict = last_word
            else:
                matches = re.findall(r'\b(UNLIKELY|LIKELY|UNCERTAIN)\b', text, re.IGNORECASE)
                verdict = matches[-1].upper() if matches else 'UNCERTAIN'

        if not explanation:
            explanation = re.sub(r'\s*(UNLIKELY|LIKELY|UNCERTAIN)\s*$', '', text, flags=re.IGNORECASE).strip()
            if not explanation:
                explanation = text

        # Clean explanation: strip inline markdown links, citations, and chain-of-thought narration
        explanation = LLMHallucinationVerifier._clean_explanation(explanation)

        return verdict, explanation, link

    @staticmethod
    def _clean_explanation(explanation: str) -> str:
        """Strip URLs, markdown links, and search narration from the explanation."""
        import re
        text = explanation.strip()

        # Remove markdown links: [text](url) -> text
        text = re.sub(r'\[([^\]]*?)\]\(https?://[^)]+\)', r'\1', text)

        # Remove bare URLs
        text = re.sub(r'https?://\S+', '', text)

        # Remove OpenAI citation annotations like ([source](url)) or (source)
        text = re.sub(r'\(\[.*?\]\(.*?\)\)', '', text)

        # Strip search narration preambles
        narration_patterns = [
            r"^I'll search for.*?\.\.+\s*",
            r'^Searching for.*?\.\.+\s*',
            r'^A web search for.*?yields?\s+',
            r'^A search for.*?yields?\s+',
            r'^Based on my web search,?\s*',
            r'^I searched for.*?\.',
            r'^I found that\s+',
            r'^Let me search.*?\.\.+\s*',
        ]
        for pattern in narration_patterns:
            text = re.sub(pattern, '', text, count=1, flags=re.IGNORECASE)

        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        # Remove trailing empty parentheses or brackets
        text = re.sub(r'\s*\(\s*\)', '', text)

        return text
