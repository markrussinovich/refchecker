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
    
    return config