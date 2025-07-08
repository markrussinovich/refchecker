#!/usr/bin/env python3
"""
Configuration validation utilities for ArXiv Reference Checker
Provides validation for configuration files and settings
"""

import logging
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of configuration validation"""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []


class ConfigValidator:
    """Validates configuration dictionaries"""
    
    def __init__(self):
        self.required_sections = ['llm', 'processing', 'apis']
        self.llm_providers = ['openai', 'anthropic', 'google', 'azure', 'vllm']
        
    def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """
        Validate a complete configuration dictionary
        
        Args:
            config: Configuration dictionary to validate
            
        Returns:
            ValidationResult with validation status and messages
        """
        errors = []
        warnings = []
        
        # Check required sections
        for section in self.required_sections:
            if section not in config:
                errors.append(f"Missing required section: {section}")
            else:
                # Validate individual sections
                section_result = self._validate_section(section, config[section])
                errors.extend(section_result.errors)
                warnings.extend(section_result.warnings)
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
    
    def _validate_section(self, section_name: str, section_config: Dict[str, Any]) -> ValidationResult:
        """Validate a specific configuration section"""
        if section_name == 'llm':
            return self._validate_llm_config(section_config)
        elif section_name == 'processing':
            return self._validate_processing_config(section_config)
        elif section_name == 'apis':
            return self._validate_apis_config(section_config)
        else:
            return ValidationResult(True, [], [])
    
    def _validate_llm_config(self, llm_config: Dict[str, Any]) -> ValidationResult:
        """Validate LLM configuration"""
        errors = []
        warnings = []
        
        # Check provider configurations
        for provider in self.llm_providers:
            if provider in llm_config:
                provider_config = llm_config[provider]
                if not isinstance(provider_config, dict):
                    errors.append(f"LLM provider {provider} config must be a dictionary")
                    continue
                
                # Validate provider-specific settings
                provider_result = self._validate_llm_provider_config(provider, provider_config)
                errors.extend(provider_result.errors)
                warnings.extend(provider_result.warnings)
        
        return ValidationResult(len(errors) == 0, errors, warnings)
    
    def _validate_llm_provider_config(self, provider: str, config: Dict[str, Any]) -> ValidationResult:
        """Validate configuration for a specific LLM provider"""
        errors = []
        warnings = []
        
        # Common validations
        if 'model' in config and not isinstance(config['model'], str):
            errors.append(f"{provider} model must be a string")
        
        if 'max_tokens' in config:
            if not isinstance(config['max_tokens'], int) or config['max_tokens'] <= 0:
                errors.append(f"{provider} max_tokens must be a positive integer")
        
        if 'temperature' in config:
            if not isinstance(config['temperature'], (int, float)) or config['temperature'] < 0 or config['temperature'] > 2:
                errors.append(f"{provider} temperature must be a number between 0 and 2")
        
        if 'timeout' in config:
            if not isinstance(config['timeout'], (int, float)) or config['timeout'] <= 0:
                errors.append(f"{provider} timeout must be a positive number")
        
        # Provider-specific validations
        if provider == 'azure':
            if 'endpoint' in config and not isinstance(config['endpoint'], str):
                errors.append("Azure endpoint must be a string")
            if 'api_version' in config and not isinstance(config['api_version'], str):
                errors.append("Azure api_version must be a string")
        elif provider == 'vllm':
            if 'server_url' in config and not isinstance(config['server_url'], str):
                errors.append("vLLM server_url must be a string")
            if 'server_url' in config and not config['server_url'].startswith(('http://', 'https://')):
                errors.append("vLLM server_url must be a valid URL")
            if 'download_path' in config and not isinstance(config['download_path'], str):
                errors.append("vLLM download_path must be a string")
            if 'auto_download' in config and not isinstance(config['auto_download'], bool):
                errors.append("vLLM auto_download must be a boolean")
        
        return ValidationResult(len(errors) == 0, errors, warnings)
    
    def _validate_processing_config(self, processing_config: Dict[str, Any]) -> ValidationResult:
        """Validate processing configuration"""
        errors = []
        warnings = []
        
        # Validate concurrent requests
        if 'max_concurrent_requests' in processing_config:
            max_concurrent = processing_config['max_concurrent_requests']
            if not isinstance(max_concurrent, int) or max_concurrent <= 0:
                errors.append("max_concurrent_requests must be a positive integer")
            elif max_concurrent > 20:
                warnings.append("max_concurrent_requests > 20 may cause rate limiting")
        
        # Validate request delay
        if 'request_delay' in processing_config:
            delay = processing_config['request_delay']
            if not isinstance(delay, (int, float)) or delay < 0:
                errors.append("request_delay must be a non-negative number")
        
        # Validate retry attempts
        if 'retry_attempts' in processing_config:
            retry = processing_config['retry_attempts']
            if not isinstance(retry, int) or retry < 0:
                errors.append("retry_attempts must be a non-negative integer")
            elif retry > 10:
                warnings.append("retry_attempts > 10 may cause long delays")
        
        return ValidationResult(len(errors) == 0, errors, warnings)
    
    def _validate_apis_config(self, apis_config: Dict[str, Any]) -> ValidationResult:
        """Validate APIs configuration"""
        errors = []
        warnings = []
        
        # Validate known API configurations
        known_apis = ['semantic_scholar', 'arxiv', 'google_scholar']
        
        for api_name in known_apis:
            if api_name in apis_config:
                api_config = apis_config[api_name]
                if not isinstance(api_config, dict):
                    errors.append(f"{api_name} API config must be a dictionary")
                    continue
                
                # Validate common API settings
                if 'base_url' in api_config:
                    if not isinstance(api_config['base_url'], str):
                        errors.append(f"{api_name} base_url must be a string")
                    elif not api_config['base_url'].startswith(('http://', 'https://')):
                        errors.append(f"{api_name} base_url must be a valid URL")
                
                if 'timeout' in api_config:
                    timeout = api_config['timeout']
                    if not isinstance(timeout, (int, float)) or timeout <= 0:
                        errors.append(f"{api_name} timeout must be a positive number")
                
                if 'api_key' in api_config:
                    if not isinstance(api_config['api_key'], str):
                        errors.append(f"{api_name} api_key must be a string")
        
        return ValidationResult(len(errors) == 0, errors, warnings)
    
    def validate_llm_command_args(self, args: Dict[str, Any]) -> ValidationResult:
        """
        Validate LLM command line arguments
        
        Args:
            args: Dictionary of command line arguments
            
        Returns:
            ValidationResult with validation status and messages
        """
        errors = []
        warnings = []
        
        # Validate provider
        if 'llm_provider' in args and args['llm_provider']:
            provider = args['llm_provider']
            if provider not in self.llm_providers:
                errors.append(f"Unknown LLM provider: {provider}. Valid providers: {', '.join(self.llm_providers)}")
        
        # Validate model
        if 'llm_model' in args and args['llm_model']:
            model = args['llm_model']
            if not isinstance(model, str):
                errors.append("LLM model must be a string")
        
        # Validate endpoint
        if 'llm_endpoint' in args and args['llm_endpoint']:
            endpoint = args['llm_endpoint']
            if not isinstance(endpoint, str):
                errors.append("LLM endpoint must be a string")
            elif not endpoint.startswith(('http://', 'https://')):
                errors.append("LLM endpoint must be a valid URL")
        
        # Validate API key
        if 'llm_key' in args and args['llm_key']:
            key = args['llm_key']
            if not isinstance(key, str):
                errors.append("LLM API key must be a string")
            elif len(key) < 10:
                warnings.append("LLM API key seems too short")
        
        return ValidationResult(len(errors) == 0, errors, warnings)
    
    def suggest_fixes(self, validation_result: ValidationResult) -> List[str]:
        """
        Suggest fixes for validation errors
        
        Args:
            validation_result: Result from validate_config
            
        Returns:
            List of suggested fixes
        """
        suggestions = []
        
        for error in validation_result.errors:
            if "Missing required section" in error:
                section = error.split(": ")[1]
                suggestions.append(f"Add {section} section to your configuration")
            elif "must be a positive integer" in error:
                suggestions.append(f"Ensure {error.split()[0]} is set to a positive integer value")
            elif "must be a string" in error:
                suggestions.append(f"Ensure {error.split()[0]} is set to a string value")
            elif "must be a valid URL" in error:
                suggestions.append(f"Ensure URL starts with http:// or https://")
        
        return suggestions