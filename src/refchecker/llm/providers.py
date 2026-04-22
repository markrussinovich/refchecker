"""
LLM provider implementations for reference extraction
"""

import json
import os
import re
import subprocess
from typing import List, Dict, Any, Optional
import logging

from .base import LLMProvider
from refchecker.config.settings import resolve_api_key, resolve_endpoint, DEFAULT_EXTRACTION_MODELS

logger = logging.getLogger(__name__)


def _openai_token_kwargs(model: str, max_tokens: int) -> dict:
    """Return the right max-token kwarg for OpenAI models.

    GPT-5 family models require ``max_completion_tokens``
    and do not support custom temperature;
    older models use ``max_tokens``.
    """
    if model and ('gpt-5' in model or 'o3' in model or 'o4' in model):
        return {'max_completion_tokens': max_tokens}
    return {'max_tokens': max_tokens}


def _is_openai_reasoning_model(model: str) -> bool:
    """Return True if *model* is an OpenAI reasoning/restricted model
    that doesn't support the temperature parameter."""
    if not model:
        return False
    return any(tag in model for tag in ('gpt-5', 'o3', 'o4'))



class LLMProviderMixin:
    """Common functionality for all LLM providers"""

    # Set by the checker when --cache is used; None means disabled.
    cache_dir: str = None

    def _call_llm_cached(self, prompt: str) -> str:
        """Wrapper around _call_llm that checks/saves the LLM response cache."""
        logger.debug("Raw bibliography text passed to LLM (%d chars):\n%s",
                      len(prompt), prompt)
        if self.cache_dir:
            from refchecker.utils.cache_utils import cached_llm_response, cache_llm_response
            system = self._get_system_prompt()
            hit = cached_llm_response(self.cache_dir, self.model, system, prompt)
            if hit is not None:
                logger.debug("Raw LLM extraction response (cached, %d chars):\n%s",
                             len(hit['text']), hit['text'])
                return hit['text']
            result = self._call_llm(prompt)
            logger.debug("Raw LLM extraction response (%d chars):\n%s",
                         len(result), result)
            cache_llm_response(self.cache_dir, self.model, system, prompt, response={'text': result})
            return result
        result = self._call_llm(prompt)
        logger.debug("Raw LLM extraction response (%d chars):\n%s",
                     len(result), result)
        return result

    def _clean_bibtex_for_llm(self, bibliography_text: str) -> str:
        """Clean BibTeX text before sending to LLM to remove formatting artifacts"""
        if not bibliography_text:
            return bibliography_text
        
        # First, protect LaTeX commands from being stripped
        protected_commands = []
        command_pattern = r'\{\\[a-zA-Z]+(?:\s+[^{}]*?)?\}'
        
        def protect_command(match):
            protected_commands.append(match.group(0))
            return f"__PROTECTED_LATEX_{len(protected_commands)-1}__"
        
        text = re.sub(command_pattern, protect_command, bibliography_text)
        
        # Clean up LaTeX math expressions in titles (but preserve the math content)
        # Convert $expression$ to expression and ${expression}$ to expression
        text = re.sub(r'\$\{([^{}]+)\}\$', r'\1', text)  # ${expr}$ -> expr
        text = re.sub(r'\$([^$]+)\$', r'\1', text)        # $expr$ -> expr
        
        # Remove curly braces around titles and other fields
        # Match { content } where content doesn't contain unmatched braces
        text = re.sub(r'\{([^{}]+)\}', r'\1', text)
        
        # Clean up DOI and URL field contamination
        # Fix cases where DOI field contains both DOI and URL separated by *
        # Pattern: DOI*URL -> separate them properly
        text = re.sub(r'(doi\s*=\s*\{?)([^}*,]+)\*http([^},\s]*)\}?', r'\1\2},\n  url = {http\3}', text)
        text = re.sub(r'(\d+\.\d+/[^*\s,]+)\*http', r'\1,\n  url = {http', text)
        
        # Clean up asterisk contamination in DOI values within the text
        text = re.sub(r'(10\.[0-9]+/[A-Za-z0-9\-.:()/_]+)\*http', r'\1', text)
        
        # Restore protected LaTeX commands
        for i, command in enumerate(protected_commands):
            text = text.replace(f"__PROTECTED_LATEX_{i}__", command)
        
        return text

    def _get_system_prompt(self) -> str:
        """System prompt with extraction rules - kept separate from user content to prevent echo-back"""
        return (
            "You are a bibliographic reference extractor. You output ONLY structured "
            "reference data in the exact format specified. Never explain, describe, or "
            "comment on the input. Never output prose or sentences. Never echo back these "
            "instructions. If input contains no extractable references, return a completely "
            "empty response with no text.\n\n"
            "OUTPUT FORMAT (MANDATORY):\n"
            "- Each line must be: Author1*Author2#Title#Venue#Year#URL\n"
            "- Use # between fields, * between authors\n"
            "- One reference per line\n"
            "- NO other text allowed\n"
            "- If no valid references exist, return NOTHING (completely empty response)\n\n"
            "RULES:\n"
            "1. Split by numbered markers [1], [2], etc. OR by author-year entries - references may span multiple lines\n"
            "2. Extract: authors, title, venue (journal/booktitle), year, URLs/DOIs\n"
            "3. For BibTeX: 'title' field = paper title, 'journal'/'booktitle' = venue\n"
            "4. Handle author formats: 'Last, First' becomes 'First Last', separate with *\n"
            "5. Faithfully include all authors - do not inject 'et al' if not present, but preserve it if it is\n"
            "6. Faithfully preserve 'et al' and variants like 'et al.' exactly as written as a separate author\n"
            "7. Skip entries that are only URLs without bibliographic data\n"
            "8. If no author field exists, start with # (empty author). Anonymous entries like standards \n"
            "   (e.g. 'ISO/PAS-8800...', 'IEEE Std...') or datasets are separate references with no authors.\n"
            "   Do NOT merge them with the next entry — output them as #Title#Venue#Year#URL\n"
            "9. Use the EXACT title from the bibliography text - never shorten, paraphrase, or summarize titles\n"
            "10. IGNORE non-reference text: theorems, proofs, algorithms, equations, discussion prose, "
            "section headers, figure/table captions. Only extract actual bibliographic entries\n"
            "11. If references suddenly change format (e.g. numbered refs followed by unnumbered prose), "
            "stop extracting - the later text is likely appendix content, not references\n\n"
            "EXAMPLES (input → output):\n\n"
            "Input:\n"
            "Mark Chen, Jerry Tworek, Heewoo Jun, Qiming Yuan, et al. Evaluating large language models\n"
            "trained on code. arXiv preprint arXiv:2107.03374, 2021.\n"
            "Output:\n"
            "Mark Chen*Jerry Tworek*Heewoo Jun*Qiming Yuan*et al.#Evaluating large language models trained on code#arXiv preprint arXiv:2107.03374#2021\n\n"
            "Input:\n"
            "[17] David Rein, Betty Li Hou, Asa Cooper Stickland, Jackson Petty, Richard Yuanzhe Pang, Julien\n"
            "Dirani, Julian Michael, and Samuel R. Bowman. GPQA: A graduate-level google-proof Q&A\n"
            "benchmark. In First Conference on Language Modeling, 2024.\n"
            "Output:\n"
            "David Rein*Betty Li Hou*Asa Cooper Stickland*Jackson Petty*Richard Yuanzhe Pang*Julien Dirani*Julian Michael*Samuel R. Bowman#GPQA: A graduate-level google-proof Q&A benchmark#First Conference on Language Modeling#2024\n\n"
            "Input:\n"
            "Mathematical Association of America. American invitational mathematics examination (AIME).\n"
            "Mathematics Competition Series. https://maa.org/math-competitions/aime\n"
            "Output:\n"
            "Mathematical Association of America#American invitational mathematics examination (AIME)#Mathematics Competition Series#n.d.#https://maa.org/math-competitions/aime"
        )

    def _create_extraction_prompt(self, bibliography_text: str) -> str:
        """Create user prompt for reference extraction - contains only the bibliography text"""
        # Log the raw bibliography text before any cleaning/preprocessing
        logger.debug("Raw bibliography text before preprocessing (%d chars):\n%s",
                      len(bibliography_text), bibliography_text)

        # Clean BibTeX formatting before sending to LLM
        cleaned_bibliography = self._clean_bibtex_for_llm(bibliography_text)
        
        # Pre-process: insert blank lines between author-year style entries
        # to help the LLM identify reference boundaries.
        cleaned_bibliography = self._insert_entry_separators(cleaned_bibliography)

        return f"""Extract references from this bibliography text. Output ONLY lines in Author1*Author2#Title#Venue#Year#URL format.

{cleaned_bibliography}
"""
    
    @staticmethod
    def _insert_entry_separators(text: str) -> str:
        """Insert blank lines between consecutive bibliography entries in author-year format.
        
        Detects boundaries where a line ending with a year/page/URL is followed
        by a line starting with an author name or anonymous title, and inserts
        a blank line separator to help the LLM parse entries correctly.
        """
        import re
        lines = text.split('\n')
        result = []
        for i, line in enumerate(lines):
            result.append(line)
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                curr_stripped = line.strip()
                # A new entry likely starts when the current line ends with
                # a year, page number, URL, or period, AND the next line
                # starts with a capital letter (author last name or title)
                # AND there isn't already a blank line.
                if (
                    curr_stripped
                    and next_line
                    and not next_line.startswith((' ', '\t'))  # Not a continuation
                    and re.search(r'(?:\b\d{4}\b|(?:https?://\S+))\s*\.?\s*$', curr_stripped)
                    and re.match(r'^[A-Z]', next_line)
                ):
                    result.append('')  # Insert blank separator
        return '\n'.join(result)
    
    def _parse_llm_response(self, content: str) -> List[str]:
        """Parse LLM response into list of references"""
        if not content:
            return []

        # Ensure content is a string
        if not isinstance(content, str):
            content = str(content)

        # Clean the content - remove leading/trailing whitespace
        content = content.strip()

        # Detect prompt echo-back: LLM regurgitated extraction instructions
        prompt_echo_markers = [
            'extraction rules:', 'output format (mandatory):',
            'split by numbered markers', 'handle author formats',
            'no other text allowed', 'bibliography text:',
            'each line must be: author',
        ]
        content_lower = content.lower()
        if any(marker in content_lower for marker in prompt_echo_markers):
            logger.warning("LLM response contains echoed prompt instructions - discarding")
            return []

        # Early check: if no # delimiters at all, likely all prose/explanatory text
        if '#' not in content:
            logger.warning("LLM response contains no structured references (no # delimiters found)")
            return []

        # Normalize the response into logical references. Some models emit
        # multiple one-line references inside a paragraph, while others wrap a
        # single reference across multiple physical lines.
        references = []
        potential_refs = []
        current_parts = []

        def flush_current_parts():
            if not current_parts:
                return
            candidate = ' '.join(part for part in current_parts if part).strip()
            if candidate:
                potential_refs.append(candidate)
            current_parts.clear()

        def looks_like_complete_reference(ref_text: str) -> bool:
            segments = [segment.strip() for segment in ref_text.split('#') if segment.strip()]
            if len(segments) >= 4:
                return True
            if len(segments) != 3:
                return False

            last_segment = segments[-1]
            return bool(re.match(r'^(19|20)\d{2}$', last_segment) or last_segment.startswith('http'))

        for raw_line in content.splitlines():
            line = raw_line.strip()

            if not line:
                flush_current_parts()
                continue

            if not current_parts:
                current_parts.append(line)
                continue

            current_ref = ' '.join(current_parts)
            current_has_delimiter = '#' in current_ref
            current_is_complete = looks_like_complete_reference(current_ref)
            line_looks_like_new_ref = '#' in line and len(line) > 30

            if line_looks_like_new_ref and (current_is_complete or not current_has_delimiter):
                flush_current_parts()
                current_parts.append(line)
                continue

            current_parts.append(line)

        flush_current_parts()

        # Common prose patterns that indicate explanatory text
        prose_starters = (
            'this ', 'the ', 'i ', 'looking ', 'based on', 'it ',
            'there ', 'these ', 'here ', 'note', 'please ', 'however',
            'unfortunately', 'appears to', 'contains', 'following',
            'above', 'below', 'after', 'before', 'when ', 'if ',
            'as ', 'for ', 'from ', 'with ', 'without ', 'although'
        )

        for ref in potential_refs:
            ref = ref.strip()

            # Skip empty lines
            if not ref:
                continue

            # Skip lines starting with # (markdown headers or empty author field without title)
            if ref.startswith('#') and not re.match(r'^#[^#]', ref):
                continue

            # Check for prose/explanatory text patterns
            ref_lower = ref.lower()

            # Skip common explanatory headers
            if ref_lower.startswith(('reference', 'here are', 'below are', 'extracted', 'bibliography')):
                continue

            # Skip verbose LLM explanatory responses
            skip_patterns = [
                'extracted from the bibliography',
                'formatted as a complete',
                'cannot extract',
                'appears to be from',
                'no numbered reference markers',
                'only figures',
                'i cannot',
                'i return nothing',
                'return nothing',
                'no valid bibliographic',
                'numbered format specified',
                'it contains',
                'it does not contain',
                'text appears to be',
                'does not appear to contain',
                'no references found',
                'empty response',
                'no bibliography',
                'no actual bibliographic',
                'no academic references',
                'contains only numerical',
                'data tables',
                'evaluation rubric',
                'publication metadata',
                'citable sources',
                'reference list',
            ]
            if any(pattern in ref_lower for pattern in skip_patterns):
                continue

            # Skip lines starting with common prose patterns
            if ref_lower.startswith(prose_starters):
                continue
            if ref_lower.startswith('looking at'):
                continue
            if ref_lower.startswith('since there are'):
                continue

            # Key structural check: valid references MUST have # delimiters
            if '#' not in ref:
                # No delimiter = not a valid reference, skip it
                logger.debug(f"Skipping line without # delimiter: {ref[:80]}...")
                continue

            # Remove common prefixes (bullets, numbers, etc.)
            ref = ref.lstrip('- *•')
            ref = ref.strip()

            # Remove reference numbers like "1.", "[1]", "(1)" from the beginning
            ref = re.sub(r'^(\d+\.|\[\d+\]|\(\d+\))\s*', '', ref)

            # Filter out very short lines (likely not complete references)
            if len(ref) > 30:  # Minimum length for academic references
                references.append(ref)

        return references


class OpenAIProvider(LLMProviderMixin, LLMProvider):
    """OpenAI GPT provider for reference extraction"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or resolve_api_key('openai')
        self.endpoint = config.get("endpoint")
        self.client = None
        
        if self.api_key:
            try:
                import openai
                import httpx
                client_kwargs = {
                    "api_key": self.api_key,
                    "timeout": httpx.Timeout(60.0, connect=5.0),
                }
                if self.endpoint:
                    base = self.endpoint
                    for suffix in ('/chat/completions', '/completions'):
                        if base.endswith(suffix):
                            base = base[: -len(suffix)]
                    client_kwargs["base_url"] = base
                self.client = openai.OpenAI(**client_kwargs)
            except ImportError:
                logger.error("OpenAI library not installed. Install with: pip install openai")
    
    def is_available(self) -> bool:
        return self.client is not None and self.api_key is not None
    
    def extract_references(self, bibliography_text: str) -> List[str]:
        return self.extract_references_with_chunking(bibliography_text)
    
    def _call_llm(self, prompt: str) -> str:
        """Make the actual OpenAI API call and return the response text"""
        try:
            _model = self.model or DEFAULT_EXTRACTION_MODELS['openai']
            kwargs = dict(
                model=_model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                **_openai_token_kwargs(_model, self.max_tokens)
            )
            if not _is_openai_reasoning_model(_model):
                kwargs['temperature'] = self.temperature
            response = self.client.chat.completions.create(**kwargs)
            
            return response.choices[0].message.content or ""
            
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            raise


class AnthropicProvider(LLMProviderMixin, LLMProvider):
    """Anthropic Claude provider for reference extraction"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or resolve_api_key('anthropic')
        self.client = None
        
        if self.api_key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key, timeout=120.0)
            except ImportError:
                logger.error("Anthropic library not installed. Install with: pip install anthropic")
    
    def is_available(self) -> bool:
        return self.client is not None and self.api_key is not None
    
    def extract_references(self, bibliography_text: str) -> List[str]:
        return self.extract_references_with_chunking(bibliography_text)
    
    def _call_llm(self, prompt: str) -> str:
        """Make the actual Anthropic API call and return the response text"""
        try:
            response = self.client.messages.create(
                model=self.model or DEFAULT_EXTRACTION_MODELS['anthropic'],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=[{
                    'type': 'text',
                    'text': self._get_system_prompt(),
                    'cache_control': {'type': 'ephemeral'},
                }],
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            logger.debug(f"Anthropic response type: {type(response.content)}")
            logger.debug(f"Anthropic response content: {response.content}")
            
            # Handle empty content list (e.g., when no references found)
            if not response.content:
                logger.debug("Anthropic returned empty content list")
                return ""
            
            # Handle different response formats
            if hasattr(response.content[0], 'text'):
                content = response.content[0].text
            elif isinstance(response.content[0], dict) and 'text' in response.content[0]:
                content = response.content[0]['text']
            elif hasattr(response.content[0], 'content'):
                content = response.content[0].content
            else:
                content = str(response.content[0])
            
            # Ensure content is a string
            if not isinstance(content, str):
                content = str(content)
            
            return content
            
        except Exception as e:
            logger.error(f"Anthropic API call failed: {e}")
            raise


class GoogleProvider(LLMProviderMixin, LLMProvider):
    """Google Gemini provider for reference extraction"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or resolve_api_key('google')
        self.client = None
        
        if self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
            except ImportError:
                logger.error("Google Gen AI library not installed. Install with: pip install google-genai")
    
    def is_available(self) -> bool:
        return self.client is not None and self.api_key is not None
    
    def extract_references(self, bibliography_text: str) -> List[str]:
        return self.extract_references_with_chunking(bibliography_text)
    
    def _call_llm(self, prompt: str) -> str:
        """Make the actual Google API call and return the response text"""
        try:
            response = self.client.models.generate_content(
                model=self.model or DEFAULT_EXTRACTION_MODELS['google'],
                contents=prompt,
                config={
                    'max_output_tokens': self.max_tokens,
                    'temperature': self.temperature,
                },
            )
            
            # Handle empty responses (content safety filter or other issues)
            if not response.candidates:
                logger.warning("Google API returned empty candidates (possibly content filtered)")
                return ""
            
            return response.text or ""
            
        except Exception as e:
            logger.error(f"Google API call failed: {e}")
            raise


class AzureProvider(LLMProviderMixin, LLMProvider):
    """Azure OpenAI provider for reference extraction"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or resolve_api_key('azure')
        self.endpoint = config.get("endpoint") or resolve_endpoint('azure')
        self.client = None
        
        logger.debug(f"Azure provider initialized - API key present: {self.api_key is not None}, Endpoint present: {self.endpoint is not None}")
        
        if self.api_key and self.endpoint:
            try:
                import openai
                self.client = openai.AzureOpenAI(
                    api_key=self.api_key,
                    api_version="2024-02-01",
                    azure_endpoint=self.endpoint
                )
                logger.debug("Azure OpenAI client created successfully")
            except ImportError:
                logger.error("OpenAI library not installed. Install with: pip install openai")
        else:
            logger.warning(f"Azure provider not available - missing {'API key' if not self.api_key else 'endpoint'}")
    
    def is_available(self) -> bool:
        available = self.client is not None and self.api_key is not None and self.endpoint is not None
        if not available:
            logger.debug(f"Azure provider not available: client={self.client is not None}, api_key={self.api_key is not None}, endpoint={self.endpoint is not None}")
        return available
    
    def extract_references(self, bibliography_text: str) -> List[str]:
        return self.extract_references_with_chunking(bibliography_text)
    
    def _call_llm(self, prompt: str) -> str:
        """Make the actual Azure OpenAI API call and return the response text"""
        try:
            _model = self.model or DEFAULT_EXTRACTION_MODELS['azure']
            kwargs = dict(
                model=_model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                **_openai_token_kwargs(_model, self.max_tokens)
            )
            if not _is_openai_reasoning_model(_model):
                kwargs['temperature'] = self.temperature
            response = self.client.chat.completions.create(**kwargs)
            
            return response.choices[0].message.content or ""
            
        except Exception as e:
            logger.error(f"Azure API call failed: {e}")
            raise

class vLLMProvider(LLMProviderMixin, LLMProvider):
    """vLLM provider using OpenAI-compatible server mode for local Hugging Face models"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.model_name = config.get("model") or "microsoft/DialoGPT-medium"
        # endpoint (from CLI --llm-endpoint) takes priority over server_url (from config)
        self.server_url = config.get("endpoint") or config.get("server_url") or os.getenv("REFCHECKER_VLLM_SERVER_URL") or "http://localhost:8000"
        # If user explicitly provided an endpoint via CLI or env var, don't
        # auto-start a server — assume the user manages it themselves.
        explicit_endpoint = bool(config.get("endpoint") or os.getenv("REFCHECKER_VLLM_SERVER_URL"))
        self.auto_start_server = config.get("auto_start_server",
            False if explicit_endpoint else os.getenv("REFCHECKER_VLLM_AUTO_START", "true").lower() == "true"
        )
        self.server_timeout = config.get("server_timeout", int(os.getenv("REFCHECKER_VLLM_TIMEOUT", "300")))
        
        # Allow skipping initialization for testing
        self.skip_initialization = config.get("skip_initialization", False)
        
        self.client = None
        self.server_process = None
        
        logger.info(f"vLLM provider initialized - Server URL: {self.server_url}, Model: {self.model_name}, Auto start: {self.auto_start_server}")
        
        # Only initialize if not skipping
        if not self.skip_initialization:
            # Clean debugger environment variables early
            self._clean_debugger_environment()
            
            if self.auto_start_server:
                if self._ensure_server_running() == False:
                    logger.error("Failed to start vLLM server, provider will not be available")
                    # this is a fatal error that shouldn't create the object
                    raise Exception("vLLM server failed to start")
            
            try:
                import openai
                # vLLM provides OpenAI-compatible API
                self.client = openai.OpenAI(
                    api_key="EMPTY",  # vLLM doesn't require API key
                    base_url=f"{self.server_url}/v1"
                )
                logger.info("OpenAI client configured for vLLM server")
            except ImportError:
                logger.error("OpenAI library not installed. Install with: pip install openai")
    
    def _clean_debugger_environment(self):
        """Clean debugger environment variables that interfere with vLLM"""
        debugger_vars = [
            'DEBUGPY_LAUNCHER_PORT',
            'PYDEVD_LOAD_VALUES_ASYNC', 
            'PYDEVD_USE_FRAME_EVAL',
            'PYDEVD_WARN_SLOW_RESOLVE_TIMEOUT'
        ]
        
        for var in debugger_vars:
            if var in os.environ:
                logger.debug(f"Removing debugger variable: {var}")
                del os.environ[var]
        
        # Clean PYTHONPATH of debugger modules
        if 'PYTHONPATH' in os.environ:
            pythonpath_parts = os.environ['PYTHONPATH'].split(':')
            clean_pythonpath = [p for p in pythonpath_parts if 'debugpy' not in p and 'pydevd' not in p]
            if clean_pythonpath != pythonpath_parts:
                logger.debug("Cleaned PYTHONPATH of debugger modules")
                os.environ['PYTHONPATH'] = ':'.join(clean_pythonpath)

    def _get_optimal_tensor_parallel_size(self):
        """Determine optimal tensor parallel size based on available GPUs"""
        try:
            import torch
            
            available_gpus = torch.cuda.device_count() if torch.cuda.is_available() else 1
            
            if available_gpus <= 1:
                return 1
            
            # For most models, use up to 4 GPUs for stability
            return min(available_gpus, 4)
        
        except Exception as e:
            logger.debug(f"Error determining tensor parallel size: {e}, defaulting to 1")
            return 1
    
    def _kill_existing_server(self):
        """Kill any existing vLLM server processes"""
        try:
            import subprocess
            # Use a more specific pattern to only kill vLLM server processes, not any process containing "vllm"
            subprocess.run(["pkill", "-f", "vllm.entrypoints.openai.api_server"], timeout=10, capture_output=True)
            import time
            time.sleep(2)  # Wait for cleanup
        except Exception as e:
            logger.debug(f"Error killing existing server: {e}")
    
    def _start_server(self):
        """Start vLLM server using standalone launcher"""
        try:
            import subprocess
            import torch
            
            # Kill any existing server
            self._kill_existing_server()
            
            # Determine optimal tensor parallel size
            tensor_parallel_size = self._get_optimal_tensor_parallel_size()
            
            # Always use standalone server launcher for reliability
            return self._start_server_standalone(tensor_parallel_size)
            
        except Exception as e:
            logger.error(f"Failed to start vLLM server: {e}")
            return False
    
    def _find_vllm_launcher_script(self):
        """Find the vLLM launcher script, supporting both development and PyPI installs"""
        import pkg_resources
        
        # First try to find it as a package resource (for PyPI installs)
        try:
            script_path = pkg_resources.resource_filename('refchecker', 'scripts/start_vllm_server.py')
            if os.path.exists(script_path):
                logger.debug(f"Found vLLM launcher script via pkg_resources: {script_path}")
                return script_path
        except Exception as e:
            logger.debug(f"Could not find script via pkg_resources: {e}")
        
        # Try relative path for development installs
        current_dir = os.path.dirname(os.path.dirname(__file__))  # src/llm -> src
        project_root = os.path.dirname(current_dir)  # src -> project root
        script_path = os.path.join(project_root, "scripts", "start_vllm_server.py")
        
        if os.path.exists(script_path):
            logger.debug(f"Found vLLM launcher script via relative path: {script_path}")
            return script_path
        
        # Try looking in the same directory structure as this file (for src-based installs)
        src_dir = os.path.dirname(os.path.dirname(__file__))  # src/llm -> src
        script_path = os.path.join(src_dir, "scripts", "start_vllm_server.py")
        
        if os.path.exists(script_path):
            logger.debug(f"Found vLLM launcher script in src directory: {script_path}")
            return script_path
        
        # If all else fails, try to create a temporary script
        logger.warning("Could not find standalone vLLM launcher script, creating temporary one")
        return self._create_temporary_launcher_script()
    
    def _create_temporary_launcher_script(self):
        """Create a temporary launcher script if the packaged one cannot be found"""
        import tempfile
        import textwrap
        
        # Create a temporary file with the launcher script content
        fd, temp_script_path = tempfile.mkstemp(suffix='.py', prefix='vllm_launcher_')
        
        launcher_code = textwrap.dedent('''
            #!/usr/bin/env python3
            """
            Temporary vLLM server launcher script
            """
            
            import sys
            import subprocess
            import os
            import time
            import argparse
            import signal
            
            def start_vllm_server(model_name, port=8000, tensor_parallel_size=1, max_model_len=None, gpu_memory_util=0.9):
                """Start vLLM server with specified parameters"""
                
                # Kill any existing server on the port
                try:
                    subprocess.run(["pkill", "-f", "vllm.entrypoints.openai.api_server"], 
                                  timeout=10, capture_output=True)
                    time.sleep(2)
                except:
                    pass
                
                # Build command
                cmd = [
                    sys.executable, "-m", "vllm.entrypoints.openai.api_server",
                    "--model", model_name,
                    "--host", "0.0.0.0",
                    "--port", str(port),
                    "--tensor-parallel-size", str(tensor_parallel_size),
                    "--gpu-memory-utilization", str(gpu_memory_util)
                ]
                
                if max_model_len:
                    cmd.extend(["--max-model-len", str(max_model_len)])
                
                print(f"Starting vLLM server: {' '.join(cmd)}")
                
                # Create clean environment without debugger variables
                clean_env = {}
                for key, value in os.environ.items():
                    if not any(debug_key in key.upper() for debug_key in ['DEBUGPY', 'PYDEVD']):
                        clean_env[key] = value
                
                # Remove debugger paths from PYTHONPATH if present
                if 'PYTHONPATH' in clean_env:
                    pythonpath_parts = clean_env['PYTHONPATH'].split(':')
                    clean_pythonpath = [p for p in pythonpath_parts if 'debugpy' not in p and 'pydevd' not in p]
                    if clean_pythonpath:
                        clean_env['PYTHONPATH'] = ':'.join(clean_pythonpath)
                    else:
                        del clean_env['PYTHONPATH']
                
                # Start server as daemon if requested
                if '--daemon' in sys.argv:
                    # Start server in background
                    process = subprocess.Popen(cmd, env=clean_env, start_new_session=True,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f"Started vLLM server as daemon with PID: {process.pid}")
                else:
                    # Start server in foreground
                    subprocess.run(cmd, env=clean_env)
            
            if __name__ == "__main__":
                parser = argparse.ArgumentParser(description="Start vLLM server")
                parser.add_argument("--model", required=True, help="Model name")
                parser.add_argument("--port", type=int, default=8000, help="Port number")
                parser.add_argument("--tensor-parallel-size", type=int, default=1, help="Tensor parallel size")
                parser.add_argument("--max-model-len", type=int, help="Maximum model length")
                parser.add_argument("--gpu-memory-util", type=float, default=0.9, help="GPU memory utilization")
                parser.add_argument("--daemon", action="store_true", help="Run as daemon")
                
                args = parser.parse_args()
                
                start_vllm_server(
                    model_name=args.model,
                    port=args.port,
                    tensor_parallel_size=args.tensor_parallel_size,
                    max_model_len=args.max_model_len,
                    gpu_memory_util=args.gpu_memory_util
                )
        ''')
        
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(launcher_code)
            
            # Make the script executable
            os.chmod(temp_script_path, 0o755)
            
            logger.info(f"Created temporary vLLM launcher script: {temp_script_path}")
            return temp_script_path
            
        except Exception as e:
            os.close(fd)  # Clean up if writing failed
            os.unlink(temp_script_path)
            raise Exception(f"Failed to create temporary launcher script: {e}")

    def _start_server_standalone(self, tensor_parallel_size):
        """Start server using standalone script"""
        import subprocess
        import torch
        import os
        
        # Find the standalone launcher script - support both development and PyPI installs
        script_path = self._find_vllm_launcher_script()
        
        # Build command for standalone launcher
        cmd = [
            "python", script_path,
            "--model", self.model_name,
            "--port", "8000",
            "--tensor-parallel-size", str(tensor_parallel_size)
        ]
        
        # Add daemon flag unless explicitly disabled via environment variable or debug mode
        # Check if we're in debug mode by examining the current logging level
        import logging
        current_logger = logging.getLogger()
        is_debug_mode = current_logger.getEffectiveLevel() <= logging.DEBUG
        
        if not (os.getenv('VLLM_NO_DAEMON', '').lower() in ('1', 'true', 'yes') or is_debug_mode):
            cmd.append("--daemon")
        
        # Add memory optimization for smaller GPUs
        if torch.cuda.is_available():
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)  # GB
            if gpu_memory < 40:  # Less than 40GB VRAM
                cmd.extend([
                    "--gpu-memory-util", "0.8",
                    "--max-model-len", "4096"
                ])
        
        logger.info(f"Starting vLLM server via standalone launcher: {' '.join(cmd)}")
        
        # Check if daemon mode is disabled
        daemon_mode = "--daemon" in cmd
        
        if daemon_mode:
            # Daemon mode: start launcher and wait for it to complete
            launcher_timeout = 120  # 2 minutes for launcher to complete
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=launcher_timeout)
                
                if result.returncode == 0:
                    logger.info("vLLM server launcher completed successfully")
                    logger.debug(f"Launcher stdout: {result.stdout}")
                    # The actual server process is running as daemon, we don't have direct handle
                    self.server_process = None  # We don't manage the daemon directly
                    return True
                else:
                    logger.error(f"vLLM server launcher failed with return code {result.returncode}")
                    logger.error(f"Launcher stderr: {result.stderr}")
                    logger.error(f"Launcher stdout: {result.stdout}")
                    return False
                    
            except subprocess.TimeoutExpired:
                logger.error(f"vLLM server launcher timed out after {launcher_timeout} seconds")
                logger.error("This may happen if the model is large and takes time to download/load")
                return False
                
        else:
            # Non-daemon mode: start launcher and let it stream output
            logger.info("Starting vLLM server in non-daemon mode (output will be visible)")
            try:
                # Start the launcher without capturing output so logs are visible
                process = subprocess.Popen(cmd, stdout=None, stderr=None)
                self.server_process = process
                
                # Give the server a moment to start
                import time
                time.sleep(5)
                
                # Check if the process is still running (hasn't crashed immediately)
                if process.poll() is None:
                    logger.info("vLLM server launcher started successfully in foreground mode")
                    return True
                else:
                    logger.error(f"vLLM server launcher exited immediately with code {process.returncode}")
                    return False
                    
            except Exception as e:
                logger.error(f"Failed to start vLLM server launcher: {e}")
                return False
    
    def _wait_for_server(self, timeout=300):
        """Wait for vLLM server to be ready"""
        import time
        import requests
        
        start_time = time.time()
        
        logger.info(f"Waiting for vLLM server to start (timeout: {timeout}s)...")
        
        while (time.time() - start_time) < timeout:
            try:
                # Check health endpoint
                response = requests.get(f"{self.server_url}/health", timeout=5)
                if response.status_code == 200:
                    logger.info("vLLM server health check passed")
                    
                    # Check models endpoint
                    response = requests.get(f"{self.server_url}/v1/models", timeout=5)
                    if response.status_code == 200:
                        models_data = response.json()
                        loaded_models = [model["id"] for model in models_data.get("data", [])]
                        logger.info(f"vLLM server is ready with models: {loaded_models}")
                        return True
                    
            except requests.exceptions.RequestException as e:
                logger.debug(f"Server not ready yet: {e}")
                pass
            
            elapsed = time.time() - start_time
            if elapsed % 30 == 0:  # Log every 30 seconds
                logger.info(f"Still waiting for server... ({elapsed:.0f}s elapsed)")
            
            time.sleep(2)
        
        logger.error(f"vLLM server failed to start within {timeout} seconds")
        return False
    
    def _ensure_server_running(self):
        """Ensure vLLM server is running, start if necessary"""
        # First check if server is already running
        if self._check_server_health():
            logger.info("vLLM server is already running and healthy")
            return True
        
        logger.info("Starting vLLM server...")
        
        # Try to start the server
        if self._start_server():
            if self._wait_for_server(self.server_timeout):
                return True
        
        # If we get here, server failed to start
        logger.error("Server startup failed")
        return False
    
    def _check_server_health(self):
        """Check if vLLM server is healthy and has the correct model"""
        try:
            import requests
            
            # First check if server is responding
            response = requests.get(f"{self.server_url}/health", timeout=10)
            if response.status_code != 200:
                logger.debug(f"Health check failed: {response.status_code}")
                return False
            
            # Check if the correct model is loaded
            response = requests.get(f"{self.server_url}/v1/models", timeout=10)
            if response.status_code == 200:
                models_data = response.json()
                loaded_models = [model["id"] for model in models_data.get("data", [])]
                if self.model_name in loaded_models:
                    logger.debug(f"Correct model {self.model_name} is loaded")
                    return True
                else:
                    logger.info(f"Wrong model loaded. Expected: {self.model_name}, Found: {loaded_models}")
                    return False
            
            return False
            
        except requests.exceptions.RequestException as e:
            logger.debug(f"Server health check failed: {e}")
            return False
    
    def is_available(self) -> bool:
        """Check if vLLM server is available"""
        if not self.client:
            return False
        
        # Check server health
        if self._check_server_health():
            return True
        
        # If auto_start_server is enabled, try to start it
        if self.auto_start_server:
            logger.info("vLLM server not responding, attempting to restart...")
            return self._ensure_server_running()
        
        return False

    def extract_references(self, bibliography_text: str) -> List[str]:
        return self.extract_references_with_chunking(bibliography_text)
    
    def _call_llm(self, prompt: str) -> str:
        """Make the actual vLLM API call and return the response text"""
        try:
            logger.debug(f"Sending prompt to vLLM server (length: {len(prompt)})")
            
            # Use chat completions API - vLLM will automatically apply chat templates
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stop=None  # Let the model use its default stop tokens
            )
            
            content = response.choices[0].message.content
            
            logger.debug(f"Received response from vLLM server:")
            logger.debug(f"  Length: {len(content)}")
            logger.debug(f"  First 200 chars: {content[:200]}...")
            logger.debug(f"  Finish reason: {response.choices[0].finish_reason}")
            
            return content or ""
            
        except Exception as e:
            logger.error(f"vLLM server API call failed: {e}")
            raise

    def test_server_response(self):
        """Test method to verify server is responding correctly"""
        if not self.is_available():
            print("Server not available")
            return
            
        test_prompt = "What is 2+2? Answer briefly."
        
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "user", "content": test_prompt}
                ],
                max_tokens=50,
                temperature=0.1
            )
            
            content = response.choices[0].message.content
            print(f"Test successful!")
            print(f"Prompt: {test_prompt}")
            print(f"Response: {content}")
            print(f"Finish reason: {response.choices[0].finish_reason}")
            
        except Exception as e:
            print(f"Test failed: {e}")
    
    def cleanup(self):
        """Cleanup vLLM server resources"""
        # Only kill the server if we auto-started it; if the user manages
        # their own server (via --llm-endpoint / REFCHECKER_VLLM_SERVER_URL),
        # leave it alone.
        if not self.auto_start_server:
            return
        logger.info("Shutting down vLLM server...")
        try:
            self._kill_existing_server()
        except Exception as e:
            logger.error(f"Error during vLLM server cleanup: {e}")
    
    def __del__(self):
        """Cleanup on deletion"""
        self.cleanup()
