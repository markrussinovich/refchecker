"""
Base classes for LLM-based reference extraction
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

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
        """Split bibliography into balanced overlapping chunks to prevent reference loss at boundaries"""
        
        # Calculate target chunk size in characters (rough estimate: 1 token ≈ 4 characters)
        target_chunk_size = max_tokens * 4
        total_length = len(bibliography_text)
        
        # Calculate how many chunks we need for balanced processing
        num_chunks = max(1, (total_length + target_chunk_size - 1) // target_chunk_size)
        
        # Use overlap of ~10% of chunk size to ensure references aren't lost
        overlap_size = target_chunk_size // 10
        
        # Calculate actual chunk size for balanced distribution
        effective_chunk_size = (total_length + num_chunks - 1) // num_chunks
        
        logger.debug(f"Bibliography length: {total_length} chars, target: {target_chunk_size}, "
                    f"creating {num_chunks} balanced chunks of ~{effective_chunk_size} chars with {overlap_size} overlap")
        
        chunks = []
        start = 0
        
        for i in range(num_chunks):
            if i == num_chunks - 1:
                # Last chunk gets all remaining content
                chunk = bibliography_text[start:].strip()
                if chunk and len(chunk) > 50:
                    chunks.append(chunk)
                    logger.debug(f"Chunk {len(chunks)} (final): {len(chunk)} characters")
                break
            
            # Calculate end position for this chunk
            end = min(start + effective_chunk_size, total_length)
            
            # Look for reference boundaries within reasonable distance
            search_window = effective_chunk_size // 5  # Look within 20% of target size
            search_start = max(start, end - search_window)
            search_end = min(total_length, end + search_window)
            
            text_section = bibliography_text[search_start:search_end]
            
            # Find the latest reference start pattern like "\n[32]"
            best_break = end
            ref_boundary_matches = list(re.finditer(r'\n\[\d+\]', text_section))
            if ref_boundary_matches:
                # Use the last reference boundary found within the search window
                last_match = ref_boundary_matches[-1]
                best_break = search_start + last_match.start() + 1  # +1 to include the \n
            
            # Extract chunk
            chunk = bibliography_text[start:best_break].strip()
            
            if chunk and len(chunk) > 50:
                chunks.append(chunk)
                logger.debug(f"Chunk {len(chunks)}: {len(chunk)} characters, starts with: {chunk[:60]}...")
            
            # For next chunk, start with fixed overlap size
            next_start = max(0, best_break - overlap_size)
            
            start = next_start
        
        logger.debug(f"Created {len(chunks)} balanced overlapping chunks for parallel processing")
        return chunks

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
        
        logger.debug(f"Using model max_tokens: {model_max_tokens}, max_input_tokens: {max_input_tokens}")
        
        if estimated_tokens > max_input_tokens:
            logger.debug(f"Bibliography too long ({estimated_tokens} estimated tokens), splitting into chunks")
            chunks = self._chunk_bibliography(bibliography_text, max_input_tokens)
            
            # Process chunks in parallel
            all_references = self._process_chunks_parallel(chunks)
            
            # Remove duplicates while preserving order based on reference numbers
            seen_ref_nums = set()
            unique_references = []
            for ref in all_references:
                # Extract reference number for more robust deduplication
                ref_num_match = re.search(r'\[(\d+)\]', ref)
                if ref_num_match:
                    ref_num = ref_num_match.group(1)
                    if ref_num not in seen_ref_nums:
                        seen_ref_nums.add(ref_num)
                        unique_references.append(ref)
                    else:
                        logger.debug(f"Skipping duplicate reference [{ref_num}]: {ref[:100]}...")
                else:
                    # Fallback to segment-based deduplication for references without numbers
                    # Split into segments separated by '#' and compare first two (author list and title)
                    segments = ref.split('#')
                    if len(segments) >= 2:
                        # Normalize author names by removing spaces around periods in initials
                        # This handles cases like "D.Iosifidis" vs "D. Iosifidis"
                        author_normalized = re.sub(r'\s*\.\s*', '.', segments[0].strip().lower())
                        title_normalized = segments[1].strip().lower()
                        
                        author_title_key = (author_normalized, title_normalized)
                        if author_title_key not in seen_ref_nums:
                            seen_ref_nums.add(author_title_key)
                            unique_references.append(ref)
                        else:
                            logger.debug(f"Skipping duplicate reference (same author+title): {ref[:100]}...")
                    else:
                        # No segments, fallback to full text deduplication
                        ref_normalized = ref.strip().lower()
                        if ref_normalized not in seen_ref_nums:
                            seen_ref_nums.add(ref_normalized)
                            unique_references.append(ref)
            
            logger.debug(f"Extracted {len(unique_references)} unique references from {len(chunks)} chunks")
            return unique_references
        else:
            # Process normally for short bibliographies
            prompt = self._create_extraction_prompt(bibliography_text)
            response_text = self._call_llm(prompt)
            return self._parse_llm_response(response_text)
    
    def _process_chunks_parallel(self, chunks: List[str]) -> List[str]:
        """
        Process chunks in parallel using ThreadPoolExecutor
        
        Args:
            chunks: List of bibliography text chunks to process
            
        Returns:
            List of all extracted references from all chunks
        """
        # Get configuration for parallel processing
        from config.settings import get_config
        config = get_config()
        
        # Check if parallel processing is enabled
        llm_config = config.get('llm', {})
        parallel_enabled = llm_config.get('parallel_chunks', True)
        max_workers = llm_config.get('max_chunk_workers', 4)
        
        # If parallel processing is disabled, fall back to sequential
        if not parallel_enabled:
            logger.info("Parallel chunk processing disabled, using sequential processing")
            return self._process_chunks_sequential(chunks)
        
        # Limit max_workers based on number of chunks
        effective_workers = min(max_workers, len(chunks))
        logger.info(f"Processing {len(chunks)} chunks in parallel with {effective_workers} workers")
        
        start_time = time.time()
        all_references = []
        
        def process_single_chunk(chunk_data):
            """Process a single chunk and return results"""
            chunk_index, chunk_text = chunk_data
            try:
                logger.debug(f"Processing chunk {chunk_index + 1}/{len(chunks)}")
                prompt = self._create_extraction_prompt(chunk_text)
                response_text = self._call_llm(prompt)
                chunk_references = self._parse_llm_response(response_text)
                logger.debug(f"Chunk {chunk_index + 1} extracted {len(chunk_references)} references")
                return chunk_index, chunk_references
            except Exception as e:
                logger.error(f"Failed to process chunk {chunk_index + 1}: {e}")
                return chunk_index, []
        
        # Create indexed chunks for processing
        indexed_chunks = [(i, chunk) for i, chunk in enumerate(chunks)]
        
        # Process chunks in parallel
        with ThreadPoolExecutor(max_workers=effective_workers, thread_name_prefix="LLMChunk") as executor:
            # Submit all chunks for processing
            future_to_chunk = {
                executor.submit(process_single_chunk, chunk_data): chunk_data[0] 
                for chunk_data in indexed_chunks
            }
            
            # Collect results as they complete
            chunk_results = {}
            for future in as_completed(future_to_chunk):
                chunk_index = future_to_chunk[future]
                try:
                    result_index, references = future.result()
                    chunk_results[result_index] = references
                    logger.debug(f"Completed chunk {result_index + 1}/{len(chunks)}")
                except Exception as e:
                    logger.error(f"Chunk {chunk_index + 1} processing failed: {e}")
                    chunk_results[chunk_index] = []
        
        # Combine results in original order
        for i in range(len(chunks)):
            if i in chunk_results:
                all_references.extend(chunk_results[i])
        
        processing_time = time.time() - start_time
        logger.debug(f"Parallel chunk processing completed in {processing_time:.2f}s, "
                   f"extracted {len(all_references)} total references")
        
        return all_references
    
    def _process_chunks_sequential(self, chunks: List[str]) -> List[str]:
        """
        Process chunks sequentially (fallback method)
        
        Args:
            chunks: List of bibliography text chunks to process
            
        Returns:
            List of all extracted references from all chunks
        """
        logger.info(f"Processing {len(chunks)} chunks sequentially")
        start_time = time.time()
        
        all_references = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i+1}/{len(chunks)}")
            try:
                prompt = self._create_extraction_prompt(chunk)
                response_text = self._call_llm(prompt)
                chunk_references = self._parse_llm_response(response_text)
                all_references.extend(chunk_references)
                logger.debug(f"Chunk {i+1} extracted {len(chunk_references)} references")
            except Exception as e:
                logger.error(f"Failed to process chunk {i+1}: {e}")
        
        processing_time = time.time() - start_time
        logger.info(f"Sequential chunk processing completed in {processing_time:.2f}s, "
                   f"extracted {len(all_references)} total references")
        
        return all_references


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