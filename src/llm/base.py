"""
Base classes for LLM-based reference extraction
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging

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
                self.logger.info("Attempting LLM-based reference extraction")
                references = self.llm_provider.extract_references(bibliography_text)
                if references:
                    self.logger.info(f"Extracted {len(references)} references using LLM")
                    return references
                else:
                    self.logger.warning("LLM returned no references")
            except Exception as e:
                self.logger.error(f"LLM reference extraction failed: {e}")
        
        # Fallback to regex approach
        if self.fallback_enabled and fallback_func:
            self.logger.info("Falling back to regex-based reference extraction")
            return fallback_func(bibliography_text)
        
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