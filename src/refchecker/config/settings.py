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
    
    "arxiv_citation": {
        "base_url": "https://arxiv.org/bibtex",
        "rate_limit_delay": 3.0,  # Share rate limiting with other ArXiv endpoints
        "timeout": 30,
        "use_as_authoritative": True,  # Use ArXiv BibTeX as authoritative source
        "enabled": True,  # Enable ArXiv citation checker in hybrid checker
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
        "similarity_threshold": 0.8,
        "max_title_similarity": 0.8,
        "max_author_similarity": 0.7,
        "year_tolerance": 1,
    },
    
    # LLM Settings
    "llm": {
        "enabled": False,
        "provider": "openai",
        "fallback_enabled": True,
        "parallel_chunks": True,  # Enable parallel chunk processing
        "max_chunk_workers": 4,   # Maximum number of parallel workers for chunk processing
        "openai": {
            "model": "gpt-4.1",
            "max_tokens": 4000,
            "temperature": 0.1,
            "timeout": 30,
        },
        "anthropic": {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 4000,
            "temperature": 0.1,
            "timeout": 30,
        },
        "google": {
            "model": "gemini-2.5-flash",
            "max_tokens": 4000,
            "temperature": 0.1,
            "timeout": 30,
        },
        "azure": {
            "model": "gpt-4o",
            "max_tokens": 4000,
            "temperature": 0.1,
            "timeout": 30,
        },
        "vllm": {
            "model": "meta-llama/Llama-3.1-8B-Instruct",
            "max_tokens": 4000,
            "temperature": 0.1,
            "timeout": 30,
            "server_url": "http://localhost:8000",
            "download_path": "./models",
            "auto_download": True,
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
    
    # Provider-specific API keys - check native variables first, then fallback to refchecker-prefixed
    if os.getenv("OPENAI_API_KEY") or os.getenv("REFCHECKER_OPENAI_API_KEY"):
        config["llm"]["openai"]["api_key"] = os.getenv("OPENAI_API_KEY") or os.getenv("REFCHECKER_OPENAI_API_KEY")
    
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("REFCHECKER_ANTHROPIC_API_KEY"):
        config["llm"]["anthropic"]["api_key"] = os.getenv("ANTHROPIC_API_KEY") or os.getenv("REFCHECKER_ANTHROPIC_API_KEY")
    
    if os.getenv("GOOGLE_API_KEY") or os.getenv("REFCHECKER_GOOGLE_API_KEY"):
        config["llm"]["google"]["api_key"] = os.getenv("GOOGLE_API_KEY") or os.getenv("REFCHECKER_GOOGLE_API_KEY")
    
    if os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("REFCHECKER_AZURE_API_KEY"):
        config["llm"]["azure"]["api_key"] = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("REFCHECKER_AZURE_API_KEY")
    
    if os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("REFCHECKER_AZURE_ENDPOINT"):
        config["llm"]["azure"]["endpoint"] = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("REFCHECKER_AZURE_ENDPOINT")
    
    # vLLM configuration
    if os.getenv("REFCHECKER_VLLM_SERVER_URL"):
        config["llm"]["vllm"]["server_url"] = os.getenv("REFCHECKER_VLLM_SERVER_URL")
    
    if os.getenv("REFCHECKER_VLLM_DOWNLOAD_PATH"):
        config["llm"]["vllm"]["download_path"] = os.getenv("REFCHECKER_VLLM_DOWNLOAD_PATH")
    
    if os.getenv("REFCHECKER_VLLM_AUTO_DOWNLOAD"):
        config["llm"]["vllm"]["auto_download"] = os.getenv("REFCHECKER_VLLM_AUTO_DOWNLOAD").lower() == "true"
    
    # Parallel processing configuration
    if os.getenv("REFCHECKER_LLM_PARALLEL_CHUNKS"):
        config["llm"]["parallel_chunks"] = os.getenv("REFCHECKER_LLM_PARALLEL_CHUNKS").lower() == "true"
    
    if os.getenv("REFCHECKER_LLM_MAX_CHUNK_WORKERS"):
        config["llm"]["max_chunk_workers"] = int(os.getenv("REFCHECKER_LLM_MAX_CHUNK_WORKERS"))
    
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