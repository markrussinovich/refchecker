"""
Configuration settings for RefChecker
"""

import os
from typing import Dict, Any

# Default configuration
DEFAULT_CONFIG = {
    # API Settings
    "semantic_scholar": {
        "base_url": "https://api.semanticscholar.org/graph/v1",
        "rate_limit_delay": 1.0,
        "max_retries": 3,
        "timeout": 30,
    },
    
    "arxiv": {
        "base_url": "https://export.arxiv.org/api/query",
        "rate_limit_delay": 3.0,
        "max_retries": 5,
        "timeout": 30,
    },
    
    # Processing Settings
    "processing": {
        "max_papers": 50,
        "days_back": 365,
        "batch_size": 100,
    },
    
    # Output Settings
    "output": {
        "debug_dir": "debug",
        "logs_dir": "logs", 
        "output_dir": "output",
        "validation_output_dir": "validation_output",
    },
    
    # Database Settings
    "database": {
        "default_path": "semantic_scholar_db/semantic_scholar.db",
        "download_batch_size": 100,
    },
    
    # Text Processing Settings
    "text_processing": {
        "max_title_similarity": 0.8,
        "max_author_similarity": 0.7,
        "year_tolerance": 1,
    },
    
    # LLM Settings
    "llm": {
        "enabled": False,
        "provider": "openai",
        "fallback_enabled": True,
        "openai": {
            "model": "gpt-4o-mini",
            "max_tokens": 4000,
            "temperature": 0.1,
        },
        "anthropic": {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 4000,
            "temperature": 0.1,
        },
        "google": {
            "model": "gemini-1.5-flash",
            "max_tokens": 4000,
            "temperature": 0.1,
        },
        "azure": {
            "model": "gpt-4o",
            "max_tokens": 4000,
            "temperature": 0.1,
        }
    }
}

def get_config() -> Dict[str, Any]:
    """Get configuration with environment variable overrides"""
    config = DEFAULT_CONFIG.copy()
    
    # Override with environment variables if present
    if os.getenv("SEMANTIC_SCHOLAR_API_KEY"):
        config["semantic_scholar"]["api_key"] = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    
    if os.getenv("REFCHECKER_DEBUG"):
        config["debug"] = os.getenv("REFCHECKER_DEBUG").lower() == "true"
    
    if os.getenv("REFCHECKER_OUTPUT_DIR"):
        config["output"]["output_dir"] = os.getenv("REFCHECKER_OUTPUT_DIR")
    
    # LLM configuration from environment variables
    if os.getenv("REFCHECKER_USE_LLM"):
        config["llm"]["enabled"] = os.getenv("REFCHECKER_USE_LLM").lower() == "true"
    
    if os.getenv("REFCHECKER_LLM_PROVIDER"):
        config["llm"]["provider"] = os.getenv("REFCHECKER_LLM_PROVIDER")
    
    if os.getenv("REFCHECKER_LLM_FALLBACK_ON_ERROR"):
        config["llm"]["fallback_enabled"] = os.getenv("REFCHECKER_LLM_FALLBACK_ON_ERROR").lower() == "true"
    
    # Provider-specific API keys
    if os.getenv("REFCHECKER_OPENAI_API_KEY"):
        config["llm"]["openai"]["api_key"] = os.getenv("REFCHECKER_OPENAI_API_KEY")
    
    if os.getenv("REFCHECKER_ANTHROPIC_API_KEY"):
        config["llm"]["anthropic"]["api_key"] = os.getenv("REFCHECKER_ANTHROPIC_API_KEY")
    
    if os.getenv("REFCHECKER_GOOGLE_API_KEY"):
        config["llm"]["google"]["api_key"] = os.getenv("REFCHECKER_GOOGLE_API_KEY")
    
    if os.getenv("REFCHECKER_AZURE_API_KEY"):
        config["llm"]["azure"]["api_key"] = os.getenv("REFCHECKER_AZURE_API_KEY")
    
    if os.getenv("REFCHECKER_AZURE_ENDPOINT"):
        config["llm"]["azure"]["endpoint"] = os.getenv("REFCHECKER_AZURE_ENDPOINT")
    
    # Model configuration
    if os.getenv("REFCHECKER_LLM_MODEL"):
        provider = config["llm"]["provider"]
        if provider in config["llm"]:
            config["llm"][provider]["model"] = os.getenv("REFCHECKER_LLM_MODEL")
    
    if os.getenv("REFCHECKER_LLM_MAX_TOKENS"):
        provider = config["llm"]["provider"]
        if provider in config["llm"]:
            config["llm"][provider]["max_tokens"] = int(os.getenv("REFCHECKER_LLM_MAX_TOKENS"))
    
    if os.getenv("REFCHECKER_LLM_TEMPERATURE"):
        provider = config["llm"]["provider"]
        if provider in config["llm"]:
            config["llm"][provider]["temperature"] = float(os.getenv("REFCHECKER_LLM_TEMPERATURE"))
    
    return config