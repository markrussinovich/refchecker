"""LLM-based hallucination verification for flagged references.

This module provides two optional LLM checks that run ONLY on references
already flagged as hallucination candidates by deterministic checks:

  4A — Plausibility judge: asks the LLM whether the paper exists.
  4B — Author-work consistency: asks whether the claimed author(s) are
       known for work matching the paper title/venue.

Both signals are supplementary (+0.05 to +0.10) and never the sole basis
for flagging.  Requires an OpenAI-compatible API key.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_PLAUSIBILITY_PROMPT = """\
You are a research-integrity assistant. Given the following academic reference,
determine whether it corresponds to a real, published paper.

Title:   {title}
Authors: {authors}
Venue:   {venue}
Year:    {year}

Reply with EXACTLY one of:
  REAL    — you are confident this paper exists
  FAKE    — you are confident this paper does NOT exist
  UNSURE  — you cannot determine with confidence

Then on a new line, give a one-sentence justification."""

_AUTHOR_CONSISTENCY_PROMPT = """\
You are a research-integrity assistant. Consider the following reference:

Title:   {title}
Authors: {authors}
Venue:   {venue}
Year:    {year}

For each listed author, briefly state whether they are known researchers and
whether they have published work related to the topic described in the title.
Then state whether the combination of these authors on this topic is plausible.

Reply with EXACTLY one of on the first line:
  PLAUSIBLE   — the author-topic combination is believable
  IMPLAUSIBLE — one or more authors are unlikely to have written this
  UNSURE      — insufficient information

Then on new lines, give brief justifications."""


class LLMHallucinationVerifier:
    """Lightweight LLM verifier for hallucination candidates."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        model: str = 'gpt-4.1',
    ):
        self.api_key = (
            api_key
            or os.getenv('OPENAI_CHAT_KEY')
            or os.getenv('OPENAI_API_KEY')
            or os.getenv('REFCHECKER_OPENAI_API_KEY')
        )
        self.endpoint = endpoint or os.getenv('OPENAI_CHAT_ENDPOINT')
        self.model = model
        self.client = None

        if self.api_key:
            try:
                import openai
                kwargs: Dict[str, Any] = {'api_key': self.api_key}
                if self.endpoint:
                    # Strip trailing path segments if endpoint includes /chat/completions
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

    # ------------------------------------------------------------------
    # 4A: Plausibility judge
    # ------------------------------------------------------------------
    def check_plausibility(self, error_entry: Dict[str, Any]) -> Dict[str, Any]:
        """Ask the LLM whether a flagged reference is real or fabricated.

        Returns a dict with:
          verdict: 'REAL' | 'FAKE' | 'UNSURE' | 'ERROR'
          justification: str
          score_delta: float (0.0 for REAL/UNSURE, +0.10 for FAKE)
        """
        if not self.available:
            return {'verdict': 'ERROR', 'justification': 'LLM not available', 'score_delta': 0.0}

        title = error_entry.get('ref_title', '')
        authors = error_entry.get('ref_authors_cited', '')
        venue = error_entry.get('original_reference', {}).get('venue',
                    error_entry.get('original_reference', {}).get('journal', ''))
        year = error_entry.get('ref_year_cited', '')

        prompt = _PLAUSIBILITY_PROMPT.format(
            title=title, authors=authors, venue=venue, year=year,
        )

        try:
            response = self._call(prompt)
            first_line = response.split('\n')[0].strip().upper()

            if 'FAKE' in first_line:
                verdict = 'FAKE'
                score_delta = 0.10
            elif 'REAL' in first_line:
                verdict = 'REAL'
                score_delta = 0.0
            else:
                verdict = 'UNSURE'
                score_delta = 0.0

            justification = '\n'.join(response.split('\n')[1:]).strip()
            return {'verdict': verdict, 'justification': justification, 'score_delta': score_delta}

        except Exception as exc:
            logger.warning(f'LLM plausibility check failed: {exc}')
            return {'verdict': 'ERROR', 'justification': str(exc), 'score_delta': 0.0}

    # ------------------------------------------------------------------
    # 4B: Author-work consistency
    # ------------------------------------------------------------------
    def check_author_consistency(self, error_entry: Dict[str, Any]) -> Dict[str, Any]:
        """Ask the LLM whether the author-topic combination is plausible.

        Returns a dict with:
          verdict: 'PLAUSIBLE' | 'IMPLAUSIBLE' | 'UNSURE' | 'ERROR'
          justification: str
          score_delta: float
        """
        if not self.available:
            return {'verdict': 'ERROR', 'justification': 'LLM not available', 'score_delta': 0.0}

        title = error_entry.get('ref_title', '')
        authors = error_entry.get('ref_authors_cited', '')
        venue = error_entry.get('original_reference', {}).get('venue',
                    error_entry.get('original_reference', {}).get('journal', ''))
        year = error_entry.get('ref_year_cited', '')

        prompt = _AUTHOR_CONSISTENCY_PROMPT.format(
            title=title, authors=authors, venue=venue, year=year,
        )

        try:
            response = self._call(prompt)
            first_line = response.split('\n')[0].strip().upper()

            if 'IMPLAUSIBLE' in first_line:
                verdict = 'IMPLAUSIBLE'
                score_delta = 0.05
            elif 'PLAUSIBLE' in first_line:
                verdict = 'PLAUSIBLE'
                score_delta = 0.0
            else:
                verdict = 'UNSURE'
                score_delta = 0.0

            justification = '\n'.join(response.split('\n')[1:]).strip()
            return {'verdict': verdict, 'justification': justification, 'score_delta': score_delta}

        except Exception as exc:
            logger.warning(f'LLM author consistency check failed: {exc}')
            return {'verdict': 'ERROR', 'justification': str(exc), 'score_delta': 0.0}
