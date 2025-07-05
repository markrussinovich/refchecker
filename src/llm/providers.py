"""
LLM provider implementations for reference extraction
"""

import json
import os
from typing import List, Dict, Any, Optional
import logging

from .base import LLMProvider

logger = logging.getLogger(__name__)


class LLMProviderMixin:
    """Common functionality for all LLM providers"""
    
    def _create_extraction_prompt(self, bibliography_text: str) -> str:
        """Create prompt for reference extraction"""
        return f"""
Please extract individual references from the following bibliography text. Each reference should be a complete bibliographic entry.

Instructions:
1. Split the bibliography into individual references
2. Each reference should include authors, title, publication venue, year, and any URLs/DOIs
3. Return ONLY the references, one per line
4. Do not include reference numbers like [1], [2], etc.
5. Each reference should be on its own line
6. Do not add any additional text or explanations

Bibliography text:
{bibliography_text}
"""
    
    def _parse_llm_response(self, content: str) -> List[str]:
        """Parse LLM response into list of references"""
        if not content:
            return []
        
        # Ensure content is a string
        if not isinstance(content, str):
            content = str(content)
        
        # Split by lines and clean up
        references = []
        for line in content.strip().split('\n'):
            line = line.strip()
            if line and not line.startswith('#') and not line.startswith('Reference'):
                # Remove common prefixes
                line = line.lstrip('- *')
                if len(line) > 20:  # Filter out very short lines
                    references.append(line)
        
        return references


class OpenAIProvider(LLMProvider, LLMProviderMixin):
    """OpenAI GPT provider for reference extraction"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or os.getenv("REFCHECKER_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.client = None
        
        if self.api_key:
            try:
                import openai
                self.client = openai.OpenAI(api_key=self.api_key)
            except ImportError:
                logger.error("OpenAI library not installed. Install with: pip install openai")
    
    def is_available(self) -> bool:
        return self.client is not None and self.api_key is not None
    
    def extract_references(self, bibliography_text: str) -> List[str]:
        if not self.is_available():
            raise Exception("OpenAI provider not available")
        
        prompt = self._create_extraction_prompt(bibliography_text)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model or "gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a bibliography parsing expert. Extract individual references from bibliography text."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            
            content = response.choices[0].message.content
            return self._parse_llm_response(content)
            
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            raise


class AnthropicProvider(LLMProvider, LLMProviderMixin):
    """Anthropic Claude provider for reference extraction"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or os.getenv("REFCHECKER_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        self.client = None
        
        if self.api_key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                logger.error("Anthropic library not installed. Install with: pip install anthropic")
    
    def is_available(self) -> bool:
        return self.client is not None and self.api_key is not None
    
    def extract_references(self, bibliography_text: str) -> List[str]:
        if not self.is_available():
            raise Exception("Anthropic provider not available")
        
        prompt = self._create_extraction_prompt(bibliography_text)
        
        try:
            response = self.client.messages.create(
                model=self.model or "claude-3-haiku-20240307",
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            logger.debug(f"Anthropic response type: {type(response.content)}")
            logger.debug(f"Anthropic response content: {response.content}")
            
            # Handle different response formats
            if hasattr(response.content[0], 'text'):
                content = response.content[0].text
            elif isinstance(response.content[0], dict) and 'text' in response.content[0]:
                content = response.content[0]['text']
            else:
                content = str(response.content[0])
            return self._parse_llm_response(content)
            
        except Exception as e:
            logger.error(f"Anthropic API call failed: {e}")
            raise


class GoogleProvider(LLMProvider, LLMProviderMixin):
    """Google Gemini provider for reference extraction"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or os.getenv("REFCHECKER_GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.client = None
        
        if self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self.client = genai.GenerativeModel(self.model or "gemini-1.5-flash")
            except ImportError:
                logger.error("Google Generative AI library not installed. Install with: pip install google-generativeai")
    
    def is_available(self) -> bool:
        return self.client is not None and self.api_key is not None
    
    def extract_references(self, bibliography_text: str) -> List[str]:
        if not self.is_available():
            raise Exception("Google provider not available")
        
        prompt = self._create_extraction_prompt(bibliography_text)
        
        try:
            response = self.client.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": self.max_tokens,
                    "temperature": self.temperature,
                }
            )
            
            content = response.text
            return self._parse_llm_response(content)
            
        except Exception as e:
            logger.error(f"Google API call failed: {e}")
            raise


class AzureProvider(LLMProvider, LLMProviderMixin):
    """Azure OpenAI provider for reference extraction"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or os.getenv("REFCHECKER_AZURE_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
        self.endpoint = config.get("endpoint") or os.getenv("REFCHECKER_AZURE_ENDPOINT") or os.getenv("AZURE_OPENAI_ENDPOINT")
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
        if not self.is_available():
            raise Exception("Azure provider not available")
        
        prompt = self._create_extraction_prompt(bibliography_text)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model or "gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a bibliography parsing expert. Extract individual references from bibliography text."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            
            content = response.choices[0].message.content
            return self._parse_llm_response(content)
            
        except Exception as e:
            logger.error(f"Azure API call failed: {e}")
            raise


