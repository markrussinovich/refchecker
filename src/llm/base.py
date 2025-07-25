"""
Base classes for LLM-based reference extraction
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging
import re

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model = config.get("model")
        self.max_tokens = config.get("max_tokens", 4000)
        self.temperature = config.get("temperature", 0.1)
    
    @abstractmethod
    def extract_references(self, bibliography_text: str) -> List[str]:
        """
        Extract references from bibliography text using LLM
        
        Args:
            bibliography_text: Raw bibliography text
            
        Returns:
            List of extracted references
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the LLM provider is properly configured and available"""
        pass
    
    def _create_extraction_prompt(self, bibliography_text: str) -> str:
        """Create the prompt for reference extraction - should be overridden by subclasses"""
        raise NotImplementedError("Subclasses must implement _create_extraction_prompt")
    
    def _call_llm(self, prompt: str) -> str:
        """Make the actual LLM API call and return the response text - should be overridden by subclasses"""
        raise NotImplementedError("Subclasses must implement _call_llm")
    
    def _chunk_bibliography(self, bibliography_text: str, max_tokens: int = 2000) -> List[str]:
        """Split bibliography into chunks without cutting references in the middle, prioritizing natural boundaries"""
        
        # First, try to split by natural boundaries (newlines) and common reference patterns
        # Look for numbered references like [1], (1), 1., etc.
        
        # Split on common reference number patterns at the start of lines
        reference_patterns = [
            r'\n\s*\[\d+\]',  # [1], [2], etc.
            r'\n\s*\(\d+\)',  # (1), (2), etc. 
            r'\n\s*\d+\.',    # 1., 2., etc.
            r'\n\s*\d+\)',    # 1), 2), etc.
        ]
        
        # Try each pattern to find the best way to split
        potential_references = []
        for pattern in reference_patterns:
            splits = re.split(pattern, bibliography_text)
            if len(splits) > 1:
                # Reconstruct references with their numbers
                refs = []
                matches = re.findall(pattern, bibliography_text)
                
                if splits[0].strip():  # First part before any numbered reference
                    refs.append(splits[0].strip())
                
                for i, match in enumerate(matches):
                    if i + 1 < len(splits):
                        ref_text = match.strip() + splits[i + 1]
                        refs.append(ref_text.strip())
                
                if len(refs) > len(potential_references):
                    potential_references = refs
                break
        
        # If no clear reference pattern found, prioritize natural boundaries
        if not potential_references:
            # First try double newlines (paragraph breaks)
            paragraphs = [ref.strip() for ref in bibliography_text.split('\n\n') if ref.strip()]
            if len(paragraphs) > 1:
                potential_references = paragraphs
            else:
                # Then try single newlines as natural boundaries
                lines = [line.strip() for line in bibliography_text.split('\n') if line.strip()]
                if len(lines) > 1:
                    potential_references = lines
        
        # If still no good splits, split by single newlines but be more careful
        if len(potential_references) <= 1:
            lines = bibliography_text.split('\n')
            potential_references = []
            current_ref = ""
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                # Check if this line starts a new reference (has typical reference indicators)
                if (re.match(r'^\[\d+\]|^\(\d+\)|^\d+\.|^\d+\)', line) or 
                    (current_ref and len(line) > 50 and any(indicator in line.lower() for indicator in ['journal', 'proceedings', 'conference', 'arxiv', 'doi']))):
                    if current_ref:
                        potential_references.append(current_ref.strip())
                    current_ref = line
                else:
                    current_ref += " " + line
            
            if current_ref:
                potential_references.append(current_ref.strip())
        
        # Now group references into chunks that fit within token limit
        chunks = []
        current_chunk = ""
        
        for ref in potential_references:
            # Rough estimate: 1 token ≈ 4 characters (conservative estimate)
            estimated_tokens = len(current_chunk + "\n" + ref) // 4
            
            if estimated_tokens > max_tokens and current_chunk:
                # Current chunk is getting too large, start a new one
                chunks.append(current_chunk.strip())
                current_chunk = ref
            else:
                if current_chunk:
                    current_chunk += "\n" + ref
                else:
                    current_chunk = ref
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        # If we still have chunks that are too large, split them more aggressively
        # but still prioritize natural boundaries
        final_chunks = []
        for chunk in chunks:
            chunk_tokens = len(chunk) // 4
            if chunk_tokens > max_tokens:
                logger.warning(f"Chunk still too large ({chunk_tokens} tokens), splitting more aggressively")
                # First try splitting by newlines within the chunk
                lines = chunk.split('\n')
                if len(lines) > 1:
                    sub_chunk = ""
                    for line in lines:
                        test_chunk = sub_chunk + "\n" + line if sub_chunk else line
                        if len(test_chunk) // 4 > max_tokens and sub_chunk:
                            final_chunks.append(sub_chunk.strip())
                            sub_chunk = line
                        else:
                            sub_chunk = test_chunk
                    
                    if sub_chunk:
                        final_chunks.append(sub_chunk.strip())
                else:
                    # Only as last resort, split by sentences or semicolons
                    sentences = re.split(r'[.;]\s+', chunk)
                    sub_chunk = ""
                    
                    for sentence in sentences:
                        test_chunk = sub_chunk + sentence + ". " if sub_chunk else sentence
                        if len(test_chunk) // 4 > max_tokens and sub_chunk:
                            final_chunks.append(sub_chunk.strip())
                            sub_chunk = sentence + ". "
                        else:
                            sub_chunk = test_chunk
                    
                    if sub_chunk:
                        final_chunks.append(sub_chunk.strip())
            else:
                final_chunks.append(chunk)
        
        logger.info(f"Split bibliography into {len(final_chunks)} chunks (max {max_tokens} tokens each)")
        return final_chunks
    
    def _parse_llm_response(self, response_text: str) -> List[str]:
        """Parse LLM response and extract individual references"""
        if not response_text:
            return []
        
        # Split by newlines and filter out empty lines
        references = []
        for line in response_text.strip().split('\n'):
            line = line.strip()
            if line and not line.startswith('#') and len(line) > 10:  # Basic filtering
                references.append(line)
        
        return references
    
    def extract_references_with_chunking(self, bibliography_text: str) -> List[str]:
        """
        Template method that handles chunking for all providers.
        Subclasses should implement _call_llm instead of extract_references.
        """
        if not self.is_available():
            raise Exception(f"{self.__class__.__name__} not available")
        
        # Get model's max_tokens from configuration - try to get provider-specific config
        from config.settings import get_config
        config = get_config()
        
        # Try to get provider-specific max_tokens, fall back to general config
        provider_name = self.__class__.__name__.lower().replace('provider', '')
        model_max_tokens = config.get('llm', {}).get(provider_name, {}).get('max_tokens', self.max_tokens)
        
        # Check if bibliography is too long and needs chunking
        estimated_tokens = len(bibliography_text) // 4  # Rough estimate
        
        # Account for prompt overhead
        prompt_overhead = 300  # Conservative estimate for prompt template and system messages
        # Ensure prompt is < 1/2 the model's total token limit to leave room for response
        max_input_tokens = (model_max_tokens // 2) - prompt_overhead
        
        logger.info(f"Using model max_tokens: {model_max_tokens}, max_input_tokens: {max_input_tokens}")
        
        if estimated_tokens > max_input_tokens:
            logger.info(f"Bibliography too long ({estimated_tokens} estimated tokens), splitting into chunks")
            chunks = self._chunk_bibliography(bibliography_text, max_input_tokens)
            
            all_references = []
            for i, chunk in enumerate(chunks):
                logger.info(f"Processing chunk {i+1}/{len(chunks)}")
                prompt = self._create_extraction_prompt(chunk)
                
                response_text = self._call_llm(prompt)
                chunk_references = self._parse_llm_response(response_text)
                all_references.extend(chunk_references)
            
            # Remove duplicates while preserving order
            seen = set()
            unique_references = []
            for ref in all_references:
                ref_normalized = ref.strip().lower()
                if ref_normalized not in seen:
                    seen.add(ref_normalized)
                    unique_references.append(ref)
            
            logger.info(f"Extracted {len(unique_references)} unique references from {len(chunks)} chunks")
            return unique_references
        else:
            # Process normally for short bibliographies
            prompt = self._create_extraction_prompt(bibliography_text)
            response_text = self._call_llm(prompt)
            return self._parse_llm_response(response_text)


class ReferenceExtractor:
    """Main class for LLM-based reference extraction with fallback"""
    
    def __init__(self, llm_provider: Optional[LLMProvider] = None, fallback_enabled: bool = True):
        self.llm_provider = llm_provider
        self.fallback_enabled = fallback_enabled
        self.logger = logging.getLogger(__name__)
    
    def extract_references(self, bibliography_text: str, fallback_func=None) -> List[str]:
        """
        Extract references with LLM and fallback to regex if needed
        
        Args:
            bibliography_text: Raw bibliography text
            fallback_func: Function to call if LLM extraction fails
            
        Returns:
            List of extracted references
        """
        if not bibliography_text:
            return []
        
        # Try LLM extraction first
        if self.llm_provider and self.llm_provider.is_available():
            try:
                model_name = self.llm_provider.model or "unknown"
                self.logger.info(f"Attempting LLM-based reference extraction using {model_name}")
                references = self.llm_provider.extract_references(bibliography_text)
                if references:
                    self.logger.info(f"Extracted {len(references)} references using LLM")
                    return references
                else:
                    self.logger.warning("LLM returned no references")
            except Exception as e:
                self.logger.error(f"LLM reference extraction failed: {e}")
        
        # If LLM was specified but failed, don't fallback - that's terminal
        self.logger.error("LLM-based reference extraction failed and fallback is disabled")
        return []


def create_llm_provider(provider_name: str, config: Dict[str, Any]) -> Optional[LLMProvider]:
    """Factory function to create LLM provider instances"""
    from .providers import OpenAIProvider, AnthropicProvider, GoogleProvider, AzureProvider, vLLMProvider
    
    providers = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "google": GoogleProvider,
        "azure": AzureProvider,
        "vllm": vLLMProvider,
    }
    
    if provider_name not in providers:
        logger.error(f"Unknown LLM provider: {provider_name}")
        return None
    
    try:
        return providers[provider_name](config)
    except Exception as e:
        logger.error(f"Failed to create {provider_name} provider: {e}")
        return None