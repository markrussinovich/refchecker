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
import random
import time
from typing import Any, Dict, List, Optional

from refchecker.config.settings import resolve_api_key, resolve_endpoint, DEFAULT_HALLUCINATION_MODELS

logger = logging.getLogger(__name__)


_ASSESSMENT_SYSTEM_PROMPT = """\
You are an reference-integrity assistant that determines whether a cited \
reference is likely **hallucinated** (fabricated by an AI).

IMPORTANT CONTEXT: The automated checkers have already searched \
Semantic Scholar, OpenAlex, CrossRef, DBLP, and arXiv for this reference. \
If they report it as unverified, the paper was NOT found in any of these \
databases. Do not contradict this unless your web search finds a page that \
shows the paper with the EXACT title listed above. However, if the \
validation summary says the paper WAS found but has metadata mismatches, \
the checkers may have matched a wrong edition or version — use your web \
search to verify the CITED title and authors independently.

MANDATORY: You MUST perform a web search for the cited title or source \
name before rendering your verdict. For academic papers, search for the \
exact title in quotes on the web to check whether the paper actually \
exists. For non-paper sources such as datasets, software, standards, or \
web pages, search for the cited source name and cited URL/domain. Do NOT \
skip the web search — a verdict issued without searching is invalid.

MANDATORY: Do NOT rely on your parametric knowledge to claim a paper \
exists or does not exist. Your training data may be outdated or wrong. \
Only the web search results and the validation summary below count as \
evidence. If you cannot search, verdict UNCERTAIN.

Reply in EXACTLY this structured format (no preamble):

EXPLANATION: <1-2 sentence summary of your finding — NO URLs, NO search narration>
LINK: <URL where the exact paper was found, or NONE if not found>
FOUND_TITLE: <the exact title of the paper as found on the web, or NONE>
FOUND_AUTHORS: <comma-separated author names as found on the web, or NONE>
FOUND_VENUE: <venue or publication/source name as found on the web, or NONE>
FOUND_YEAR: <publication year as found on the web, or NONE>
VERDICT: <LIKELY|UNLIKELY|UNCERTAIN>

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
this exact title exists." or "The exact paper was found in Nature 2024.").
- FOUND_TITLE, FOUND_AUTHORS, FOUND_VENUE, and FOUND_YEAR should contain the metadata \
as shown on the actual web page or database entry you found. If the \
verdict is LIKELY or you did not find the paper, set all four to NONE.

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
citation error, not AI hallucination. Verdict MUST be UNLIKELY. This \
exception applies only when the cited name is recognizably the SAME \
person as the real author. It does NOT apply when a cited coauthor is \
a different person or when fewer than half of the cited authors appear \
on the real paper; those are fabricated-author signals.

(4) NON-ACADEMIC REAL-WORLD SOURCES: References to competitions, datasets, \
ethics codes, standards documents, technical blog posts, software tools, \
model cards, prompt-format documentation, vendor technical reports, \
release announcements, or other real-world non-paper sources (e.g. \
"American Invitational Mathematics Examination", "SPJ Code of Ethics", \
"Gemini CLI", "Llama 4 | Model Cards and Prompt Formats", "Seed1.6 \
Tech Introduction") are valid citations even though they are not academic \
papers. If the cited source is a real, identifiable entity, verdict MUST \
be UNLIKELY regardless of whether it appears in academic databases.

(4a) DATASET REFERENCES: A dataset citation is valid when the cited URL \
resolves to the dataset page and the dataset owner/name or page title \
matches the cited reference after normalizing case, spaces, underscores, \
hyphens, and punctuation. For example, a citation titled "code \
instructions" with URL \
"https://huggingface.co/datasets/red1xe/code_instructions" should be \
treated as the Hugging Face dataset "red1xe/code_instructions" and \
verdict MUST be UNLIKELY if that page exists. Do NOT require datasets to \
have academic-paper authors or an academic database entry.

(4b) OFFICIAL MODEL OR PRODUCT DOCUMENTATION: A model card, prompt-format \
page, API documentation page, model release announcement, or official \
vendor technical introduction is valid when the cited URL resolves to an \
official page and the page title or visible page content matches the cited \
source after normalizing separators such as "|", hyphens, underscores, \
spaces, and case. Do NOT require these sources to be peer-reviewed papers, \
indexed academic records, or formal technical reports. If the automated \
URL checker says the page "does not reference this paper" but the cited \
reference is clearly a non-paper web source, treat that as a limitation \
of the paper-oriented checker, not evidence of hallucination.

(4c) SOFTWARE OR CODE PROJECT REFERENCES: A citation to software, a code \
repository, a game engine, a library, or a project name is valid when web \
search finds a dedicated project/repository/homepage whose name matches \
the cited source. Do NOT require a DOI, paper venue, academic database \
entry, or paper-style author list. If the project identity matches, verdict \
MUST be UNLIKELY unless the cited maintainers/date are clearly impossible. \
For example, "Gian-Carlo Pascutto and Gary Linscott. Leela chess zero, \
March 2019" should be treated as a real software/project citation if the \
Leela Chess Zero project page or repository is found.

(5) INFORMAL OR COLLOQUIAL TITLES: If an author uses a widely recognized \
informal name for a paper or model (e.g. "Llama" instead of the full \
"The Llama 3 Herd of Models"), and the authors substantially match, \
this is a citation style choice, not hallucination. Verdict UNLIKELY.

ARXIV ID WARNING: If the reference includes an arXiv URL/ID, and the \
automated checkers report that the arXiv ID points to a DIFFERENT paper, \
then the arXiv ID is wrong. Do NOT use that arXiv URL in the LINK field — \
it does not prove this paper exists. Search for the paper BY TITLE instead. \
If your search only finds the DIFFERENT paper at that arXiv ID, the \
cited reference is fabricated and the verdict MUST be LIKELY.

VERIFICATION REQUIREMENT: Before writing UNLIKELY for an academic paper, \
ask yourself: "Did my search results contain a page where the PRIMARY \
title (not a citation in another paper's reference list) exactly matches \
the cited title?" If you cannot answer yes, the verdict must be LIKELY. \
For non-paper sources such as datasets or software, answer instead: \
"Did my search results or cited URL contain a dedicated source page whose \
name matches the cited source after normalizing separators and case?" If \
yes, the verdict MUST be UNLIKELY.
"""

_ASSESSMENT_PROMPT = """\
## Reference metadata
Title:   {title}
Authors: {authors}
Venue:   {venue}
Year:    {year}
URL:     {url}

## Validation results from automated checkers
{validation_summary}

Perform the web search and assessment as per the instructions. 
"""


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

    # For ANY error type (not just 'multiple'), if the paper was verified
    # in a database, tell the LLM so it doesn't incorrectly claim the
    # paper doesn't exist.
    if error_type != 'multiple' and error_type != 'unverified' and error_entry.get('ref_verified_url'):
        db = error_entry.get('matched_database', 'an academic database')
        verified_url = error_entry['ref_verified_url']
        lines.append(
            f'\n  NOTE: This paper WAS found and verified in {db} '
            f'(verified URL: {verified_url}). The paper EXISTS — the '
            f'error above is a metadata mismatch, not a missing paper. '
            f'Do NOT claim this paper does not exist.'
        )

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
    _GOOGLE_RETRY_ATTEMPTS = 5
    _GOOGLE_RETRY_INITIAL_DELAY_SECONDS = 1.0
    _GOOGLE_RETRY_MAX_DELAY_SECONDS = 60.0

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
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[google_search_tool],
        )
        resp = self._google_generate_content_with_retry(
            contents=user_prompt,
            config=config,
            purpose='grounded hallucination search',
        )

        text, web_urls = self._extract_google_grounding(resp)

        # If the model returned a LIKELY verdict without grounding, it
        # answered from parametric knowledge only — which is unreliable.
        # Retry once with an explicit instruction to search.
        if not web_urls and 'VERDICT: LIKELY' in text.upper():
            logger.debug('Gemini LIKELY verdict without grounding — retrying with explicit search instruction')
            retry_user_prompt = (
                "IMPORTANT: Your previous answer was not grounded in web search results. "
                "You MUST use the google_search tool NOW to search for the paper title "
                "before answering. Search for the exact title in quotes.\n\n"
                f"{user_prompt}"
            )
            resp2 = self._google_generate_content_with_retry(
                contents=retry_user_prompt,
                config=config,
                purpose='grounded hallucination search retry',
            )
            text2, web_urls2 = self._extract_google_grounding(resp2)
            if web_urls2:
                logger.debug('Gemini retry produced %d grounding URLs', len(web_urls2))
                return text2.strip(), web_urls2
            else:
                logger.debug('Gemini retry still ungrounded — using original response')

        return text.strip(), web_urls

    @staticmethod
    def _extract_google_grounding(resp) -> tuple:
        """Extract response text and grounding URLs from a Gemini response."""
        try:
            text = resp.text or ''
        except (TypeError, ValueError, AttributeError):
            # resp.text can raise when the response has no text parts
            # (e.g. only function_call parts, or content blocked by safety)
            text = ''
        web_urls: List[str] = []
        for candidate in getattr(resp, 'candidates', []):
            grounding = getattr(candidate, 'grounding_metadata', None)
            if grounding:
                # grounding_chunks may exist as an attribute but be None
                for chunk in (getattr(grounding, 'grounding_chunks', None) or []):
                    web_info = getattr(chunk, 'web', None)
                    if web_info:
                        url = getattr(web_info, 'uri', '') or ''
                        if url:
                            web_urls.append(url)
                search_entry = getattr(grounding, 'search_entry_point', None)
                if search_entry:
                    logger.debug('Gemini grounding search entry: %s',
                                 getattr(search_entry, 'rendered_content', '')[:200])

        if web_urls:
            logger.debug('Gemini grounding returned %d URLs', len(web_urls))
        else:
            logger.debug('Gemini grounding returned NO URLs — response is ungrounded')

        return text, web_urls

    def _call_google_chat(self, system_prompt: str, user_prompt: str) -> tuple:
        """Google Gemini without web search."""
        from google.genai import types
        resp = self._google_generate_content_with_retry(
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
            ),
            purpose='hallucination chat fallback',
        )
        return (resp.text or '').strip(), []

    def _google_generate_content_with_retry(self, *, contents: str, config: Any, purpose: str) -> Any:
        """Call Gemini with truncated exponential backoff for transient errors."""
        attempts = self._GOOGLE_RETRY_ATTEMPTS
        for attempt in range(attempts):
            try:
                return self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )
            except Exception as exc:
                if not self._is_google_retryable_error(exc) or attempt == attempts - 1:
                    raise
                wait_time = min(
                    self._GOOGLE_RETRY_MAX_DELAY_SECONDS,
                    self._GOOGLE_RETRY_INITIAL_DELAY_SECONDS * (2 ** attempt) + random.random(),
                )
                logger.debug(
                    'Google %s transient error (%s); retrying in %.1fs (%d/%d)',
                    purpose,
                    exc,
                    wait_time,
                    attempt + 2,
                    attempts,
                )
                time.sleep(wait_time)

        raise RuntimeError('unreachable Google retry state')

    @staticmethod
    def _is_google_retryable_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            '429' in text
            or '408' in text
            or '500' in text
            or '502' in text
            or '503' in text
            or '504' in text
            or 'resource_exhausted' in text
            or 'rate limit' in text
            or 'quota' in text
            or 'timeout' in text
            or 'temporarily unavailable' in text
            or 'unavailable' in text
        )

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
                verdict, explanation, paper_link, found_metadata = self._parse_verdict(hit['text'])
                web_urls = hit.get('web_urls', [])
                logger.debug(
                    'deep hallucination check cache hit: provider=%s model=%s ref=%r web_urls=%d',
                    self.provider,
                    self.model,
                    error_entry.get('ref_title', ''),
                    len(web_urls),
                )
                # Apply verified-paper safety net to cached results too
                verdict, explanation = self._downgrade_ungrounded_unlikely(
                    verdict, explanation, error_entry, web_urls,
                )
                verdict, explanation = self._apply_unlikely_author_mismatch_guard(
                    verdict, explanation, error_entry, web_urls, found_metadata, paper_link,
                )
                verdict, explanation = self._apply_citation_evidence_guard(
                    verdict, explanation, error_entry,
                )
                verdict, explanation = self._apply_verified_safety_net(
                    verdict, explanation, error_entry, web_urls,
                )
                return {
                    'verdict': verdict,
                    'explanation': explanation,
                    'link': paper_link,
                    'found_title': found_metadata.get('title'),
                    'found_authors': found_metadata.get('authors'),
                    'found_venue': found_metadata.get('venue'),
                    'found_year': found_metadata.get('year'),
                    'source': 'deep_hallucination_cache',
                    'web_search': {'found': bool(web_urls),
                                   'academic_urls': web_urls,
                                   'provider': self.provider} if web_urls else None,
                }

        if not self.available:
            return {
                'verdict': 'UNCERTAIN',
                'explanation': 'LLM not available.',
                'web_search': None,
            }

        try:
            logger.debug(
                'deep hallucination check live call: provider=%s model=%s ref=%r',
                self.provider,
                self.model,
                error_entry.get('ref_title', ''),
            )
            response, web_urls = self._call(system_prompt, user_prompt)
            verdict, explanation, paper_link, found_metadata = self._parse_verdict(response)
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

        # Apply verified-paper safety net
        verdict, explanation = self._downgrade_ungrounded_unlikely(
            verdict, explanation, error_entry, web_urls,
        )
        verdict, explanation = self._apply_unlikely_author_mismatch_guard(
            verdict, explanation, error_entry, web_urls, found_metadata, paper_link,
        )
        verdict, explanation = self._apply_citation_evidence_guard(
            verdict, explanation, error_entry,
        )
        verdict, explanation = self._apply_verified_safety_net(
            verdict, explanation, error_entry, web_urls,
        )

        logger.debug(
            'Hallucination assessment: title=%r verdict=%s explanation=%s',
            error_entry.get('ref_title', ''), verdict, explanation,
        )

        return {
            'verdict': verdict,
            'explanation': explanation,
            'link': paper_link,
            'found_title': found_metadata.get('title'),
            'found_authors': found_metadata.get('authors'),
            'found_venue': found_metadata.get('venue'),
            'found_year': found_metadata.get('year'),
            'source': 'deep_hallucination_live',
            'web_search': web_result,
        }

    @staticmethod
    def _downgrade_ungrounded_unlikely(
        verdict: str,
        explanation: str,
        error_entry: Dict[str, Any],
        web_urls: list,
    ) -> tuple:
        """Do not let ungrounded chat fallback prove academic references real."""
        if verdict != 'UNLIKELY' or web_urls:
            return verdict, explanation

        if LLMHallucinationVerifier._is_verified_real_world_source(error_entry):
            return verdict, explanation

        error_type = (error_entry.get('error_type') or '').lower()
        if error_type not in ('unverified', 'multiple'):
            return verdict, explanation

        if error_entry.get('ref_verified_url'):
            return verdict, explanation

        logger.debug(
            'Downgrading ungrounded UNLIKELY hallucination assessment to UNCERTAIN '
            'for academic reference ref=%r',
            error_entry.get('ref_title', ''),
        )
        return (
            'UNCERTAIN',
            explanation + (
                ' (Verdict downgraded: the LLM response was not grounded in web '
                'search results or verified metadata, so it cannot prove this '
                'academic reference has matching title and authors.)'
            ),
        )

    @staticmethod
    def _apply_unlikely_author_mismatch_guard(
        verdict: str,
        explanation: str,
        error_entry: Dict[str, Any],
        web_urls: list,
        found_metadata: Dict[str, Any],
        paper_link: Optional[str] = None,
    ) -> tuple:
        """Do not let low-overlap verified author mismatches become UNLIKELY.

        A real title with mostly fabricated authors is still a hallucinated
        reference unless the LLM found a source whose authors substantially
        match the cited author list. This catches cases where the model says
        "the paper exists, so this is only a metadata error" even though the
        cited coauthors are different people.
        """
        if verdict != 'UNLIKELY':
            return verdict, explanation

        error_type = (error_entry.get('error_type') or '').lower()
        if not (error_type.startswith('author') or error_type == 'multiple'):
            return verdict, explanation

        cited = error_entry.get('ref_authors_cited', '')
        correct = error_entry.get('ref_authors_correct', '')
        if not cited or not correct:
            return verdict, explanation

        from refchecker.core.hallucination_policy import _compute_author_overlap

        cited_list = error_entry.get('_ref_authors_cited_list')
        checker_overlap = _compute_author_overlap(cited, correct, cited_list=cited_list)
        if checker_overlap is None or checker_overlap > 0.5:
            return verdict, explanation

        found_authors = (found_metadata or {}).get('authors')
        found_overlap = None
        if found_authors:
            found_overlap = _compute_author_overlap(cited, found_authors, cited_list=cited_list)
            if found_overlap is not None and found_overlap >= 0.6:
                if not LLMHallucinationVerifier._found_authors_conflict_with_checked_source(
                    found_metadata, error_entry, paper_link,
                ):
                    return verdict, explanation

        logger.debug(
            'Overriding UNLIKELY -> LIKELY for low-overlap author mismatch '
            '(checker_overlap=%s, found_overlap=%s, grounded=%s, ref=%r)',
            f'{checker_overlap * 100:.0f}%',
            'unknown' if found_overlap is None else f'{found_overlap * 100:.0f}%',
            bool(web_urls),
            error_entry.get('ref_title', ''),
        )
        return (
            'LIKELY',
            explanation + (
                ' (Verdict corrected: the cited author list has low overlap '
                'with the verified paper, and the LLM did not provide found '
                'authors that substantially match the cited authors. A real '
                'title with fabricated coauthors is treated as hallucinated.)'
            ),
        )

    @staticmethod
    def _apply_citation_evidence_guard(
        verdict: str,
        explanation: str,
        error_entry: Dict[str, Any],
    ) -> tuple:
        """Do not accept another paper's references as proof a paper exists."""
        if verdict != 'UNLIKELY':
            return verdict, explanation

        if LLMHallucinationVerifier._is_verified_real_world_source(error_entry):
            return verdict, explanation

        if error_entry.get('ref_verified_url'):
            return verdict, explanation

        error_type = (error_entry.get('error_type') or '').lower()
        if error_type not in ('unverified', 'multiple'):
            return verdict, explanation

        text = (explanation or '').lower()
        citation_only_signals = (
            'referenced in another',
            'cited in another',
            'mentioned in another',
            'appears in another',
            'listed in another',
            'referenced by another',
            'cited by another',
            'another arxiv paper',
            'another academic paper',
            'another publication',
            'reference list',
            'bibliography',
        )
        if not any(signal in text for signal in citation_only_signals):
            return verdict, explanation

        logger.debug(
            'Overriding UNLIKELY -> LIKELY because LLM used citation-list evidence ref=%r',
            error_entry.get('ref_title', ''),
        )
        return (
            'LIKELY',
            explanation + (
                ' (Verdict corrected: finding the title only as a citation or '
                'reference in another paper is not proof that the cited paper '
                'has its own dedicated publication page.)'
            ),
        )

    @staticmethod
    def _found_authors_conflict_with_checked_source(
        found_metadata: Dict[str, Any],
        error_entry: Dict[str, Any],
        paper_link: Optional[str],
    ) -> bool:
        """Return True when LLM-found authors contradict a checked source.

        The LLM may sometimes fill FOUND_AUTHORS with the citation's authors
        even while linking to the same arXiv/DOI/source URL that the checker
        already verified. In that case, prefer the checker metadata over the
        LLM-provided field.
        """
        found_authors = (found_metadata or {}).get('authors')
        if not paper_link or not found_authors:
            return False

        found_title = (found_metadata or {}).get('title')
        cited_title = error_entry.get('ref_title', '')
        if found_title and cited_title:
            from refchecker.utils.text_utils import compare_titles_with_latex_cleaning

            if compare_titles_with_latex_cleaning(cited_title, found_title) >= 0.9:
                return False

        checked_urls = [
            error_entry.get('ref_url_cited', ''),
            error_entry.get('ref_verified_url', ''),
        ]
        if not any(
            LLMHallucinationVerifier._same_reference_url(paper_link, url)
            for url in checked_urls
            if url
        ):
            return False

        correct = error_entry.get('ref_authors_correct', '')
        if not correct:
            return False

        from refchecker.core.hallucination_policy import _compute_author_overlap

        found_correct_overlap = _compute_author_overlap(found_authors, correct)
        return found_correct_overlap is not None and found_correct_overlap < 0.6

    @staticmethod
    def _same_reference_url(left: str, right: str) -> bool:
        """Compare reference URLs after basic normalization."""
        from urllib.parse import urlparse

        def normalize(url: str) -> str:
            parsed = urlparse((url or '').strip())
            host = (parsed.hostname or '').lower()
            if host.startswith('www.'):
                host = host[4:]
            path = parsed.path.rstrip('/').lower()
            return f'{host}{path}'

        return bool(left and right and normalize(left) == normalize(right))

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
    def _apply_verified_safety_net(
        verdict: str,
        explanation: str,
        error_entry: Dict[str, Any],
        web_urls: list,
    ) -> tuple:
        """Downgrade LIKELY → UNCERTAIN for verified papers with metadata-only errors.

        If the LLM says LIKELY but the paper was actually verified in a
        database (has a verified URL from a checker) and the error is only
        a metadata mismatch (author, year, venue, doi — possibly with a
        version suffix like 'author (v4 vs v5 update)'), the paper provably
        exists. The author/metadata mismatch may be due to parsing errors,
        edition differences, or version updates. Downgrade to UNCERTAIN.

        This applies regardless of whether web search was used, because
        the database verification is stronger evidence than an LLM's
        assessment of author overlap.
        """
        if verdict != 'LIKELY':
            return verdict, explanation

        verified_url = error_entry.get('ref_verified_url', '')
        if not verified_url:
            return verdict, explanation

        if LLMHallucinationVerifier._is_verified_real_world_source(error_entry):
            logger.debug(
                'Overriding LIKELY → UNLIKELY for verified real-world web source '
                '(verified_url=%s, grounded=%s)',
                verified_url, bool(web_urls),
            )
            verdict = 'UNLIKELY'
            explanation += (
                f' (Verdict corrected: the cited official web source was '
                f'verified at {verified_url}; non-academic documentation, '
                f'model cards, blog posts, release announcements, software, '
                f'and product pages are valid real-world sources.)'
            )
            return verdict, explanation

        error_type = (error_entry.get('error_type') or '').lower()
        # Match error types that are purely metadata mismatches.
        # These can have version suffixes like "author (v4 vs v5 update)".
        _metadata_prefixes = ('author', 'year', 'venue', 'doi')
        if any(error_type.startswith(p) for p in _metadata_prefixes):
            # For author-type errors, check overlap before downgrading.
            # Low-overlap author mismatches are genuine hallucinations, not
            # parsing/edition issues. Only downgrade when most cited authors
            # match the verified paper.
            if error_type.startswith('author'):
                from refchecker.core.hallucination_policy import _compute_author_overlap
                cited_str = error_entry.get('ref_authors_cited', '')
                correct_str = error_entry.get('ref_authors_correct', '')
                overlap = _compute_author_overlap(cited_str, correct_str)
                if overlap is None or overlap <= 0.5:
                    logger.debug(
                        'Keeping LIKELY for verified ref with low author match '
                        '(overlap=%s, error_type=%s, verified_url=%s)',
                        'unknown' if overlap is None else f'{overlap * 100:.0f}%',
                        error_type,
                        verified_url,
                    )
                    return verdict, explanation

            logger.debug(
                'Overriding LIKELY → UNCERTAIN for verified ref '
                '(error_type=%s, verified_url=%s, grounded=%s)',
                error_type, verified_url, bool(web_urls),
            )
            verdict = 'UNCERTAIN'
            explanation += (
                f' (Verdict downgraded: paper was verified in a database '
                f'[{verified_url}] — metadata mismatch is likely a parsing '
                f'or edition issue, not hallucination.)'
            )
        return verdict, explanation

    @staticmethod
    def _is_verified_real_world_source(error_entry: Dict[str, Any]) -> bool:
        """Return True for verified non-academic web sources.

        These are citations to docs, model cards, product pages, release
        announcements, blog posts, datasets, and software pages.  They should
        not be marked hallucinated merely because academic databases do not
        index them or the LLM's web search missed the page.
        """
        from urllib.parse import urlparse

        verified_url = error_entry.get('ref_verified_url') or ''
        cited_url = error_entry.get('ref_url_cited') or ''
        orig = error_entry.get('original_reference') or {}
        url = verified_url or cited_url or orig.get('url', '') or ''
        if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
            return False

        hostname = (urlparse(url).hostname or '').lower()
        if hostname.startswith('www.'):
            hostname = hostname[4:]

        academic_domains = (
            'arxiv.org', 'semanticscholar.org', 'openreview.net',
            'aclanthology.org', 'doi.org', 'crossref.org', 'dblp.org',
            'springer.com', 'ieee.org', 'acm.org', 'sciencedirect.com',
            'wiley.com', 'nature.com', 'science.org', 'pubmed.ncbi.nlm.nih.gov',
            'oup.com', 'cambridge.org', 'tandfonline.com',
        )
        if any(hostname == domain or hostname.endswith('.' + domain) for domain in academic_domains):
            return False

        text = ' '.join(str(part or '') for part in (
            error_entry.get('ref_title'),
            error_entry.get('ref_venue_cited'),
            orig.get('venue'),
            orig.get('journal'),
            orig.get('booktitle'),
            url,
        )).lower()

        source_markers = (
            'docs', 'documentation', 'model card', 'model cards',
            'prompt format', 'prompt formats', 'api', 'developer',
            'blog', 'release', 'announcement', 'technical report',
            'tech introduction', 'product', 'software', 'github',
            'dataset', 'huggingface', 'whitepaper', 'guide', 'manual',
            'reference', 'platform', 'news', 'index/',
        )
        known_real_world_domains = (
            'llama.com', 'ai.meta.com', 'openai.com', 'anthropic.com',
            'platform.openai.com', 'developers.openai.com', 'huggingface.co',
            'github.com', 'microsoft.com', 'google.com', 'nvidia.com',
            'pytorch.org', 'tensorflow.org', 'readthedocs.io',
        )

        return (
            any(marker in text for marker in source_markers)
            or any(hostname == domain or hostname.endswith('.' + domain) for domain in known_real_world_domains)
        )

    @staticmethod
    def _parse_verdict(response: str) -> tuple:
        """Parse the LLM response into (verdict, explanation, link, found_metadata).

        Expects structured format:
            EXPLANATION: ...
            LINK: <url> | NONE
            FOUND_TITLE: <title> | NONE
            FOUND_AUTHORS: <authors> | NONE
            FOUND_VENUE: <venue> | NONE
            FOUND_YEAR: <year> | NONE
            VERDICT: LIKELY|UNLIKELY|UNCERTAIN

        Falls back to unstructured parsing if the format isn't followed.

        Returns
        -------
        tuple of (verdict, explanation, link, found_metadata)
            found_metadata is a dict with 'title', 'authors', 'venue', 'year' keys
            (values may be None if not provided by the LLM).
        """
        import re
        text = response.strip()
        labels = r'(EXPLANATION|LINK|FOUND_TITLE|FOUND_AUTHORS|FOUND_VENUE|FOUND_YEAR|VERDICT)'
        text = re.sub(rf'\*\*\s*{labels}\s*:\s*\*\*', r'\n\1: ', text, flags=re.IGNORECASE)
        text = re.sub(rf'(?<!^)\s+({labels}:)', r'\n\1', text, flags=re.IGNORECASE)
        text = text.strip()

        verdict = 'UNCERTAIN'
        explanation = ''
        link = None
        found_metadata = {'title': None, 'authors': None, 'venue': None, 'year': None}

        # Try structured format first
        verdict_match = re.search(r'^VERDICT:\s*(LIKELY|UNLIKELY|UNCERTAIN)', text, re.IGNORECASE | re.MULTILINE)
        explanation_match = re.search(r'^EXPLANATION:\s*(.+?)(?=^LINK:|\Z)', text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        link_match = re.search(r'^LINK:\s*(.+)', text, re.IGNORECASE | re.MULTILINE)

        # Parse FOUND_TITLE, FOUND_AUTHORS, FOUND_VENUE, FOUND_YEAR
        found_title_match = re.search(r'^FOUND_TITLE:\s*(.+)', text, re.IGNORECASE | re.MULTILINE)
        found_authors_match = re.search(r'^FOUND_AUTHORS:\s*(.+)', text, re.IGNORECASE | re.MULTILINE)
        found_venue_match = re.search(r'^FOUND_VENUE:\s*(.+)', text, re.IGNORECASE | re.MULTILINE)
        found_year_match = re.search(r'^FOUND_YEAR:\s*(.+)', text, re.IGNORECASE | re.MULTILINE)

        if found_title_match:
            val = found_title_match.group(1).strip()
            if val.upper() != 'NONE' and val:
                found_metadata['title'] = val
        if found_authors_match:
            val = found_authors_match.group(1).strip()
            if val.upper() != 'NONE' and val:
                found_metadata['authors'] = val
        if found_venue_match:
            val = found_venue_match.group(1).strip()
            if val.upper() != 'NONE' and val:
                found_metadata['venue'] = val
        if found_year_match:
            val = found_year_match.group(1).strip()
            if val.upper() != 'NONE' and val:
                found_metadata['year'] = val

        if verdict_match:
            verdict = verdict_match.group(1).strip().upper()

        if explanation_match:
            explanation = explanation_match.group(1).strip()
        else:
            # Fallback: use full text minus verdict/link/found lines as explanation
            lines = [l for l in text.splitlines()
                     if not re.match(r'^(VERDICT|LINK|FOUND_TITLE|FOUND_AUTHORS|FOUND_VENUE|FOUND_YEAR):', l, re.IGNORECASE)]
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

        return verdict, explanation, link, found_metadata

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
