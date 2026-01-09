"""
Pydantic models for API request/response validation
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class CheckSource(str, Enum):
    """Source type for paper check"""
    URL = "url"
    FILE = "file"
    TEXT = "text"


class CheckRequest(BaseModel):
    """Request to check a paper"""
    source_type: CheckSource
    source_value: str  # URL or filename
    llm_provider: Optional[str] = "anthropic"
    llm_model: Optional[str] = None
    use_llm: bool = True


class ReferenceError(BaseModel):
    """Error or warning in a reference"""
    error_type: str  # 'author', 'title', 'year', 'doi', 'venue', 'arxiv_id', 'unverified'
    error_details: str
    cited_value: Optional[str] = None
    actual_value: Optional[str] = None


class ReferenceURL(BaseModel):
    """Authoritative URL for a reference"""
    type: str  # 'semantic_scholar', 'arxiv', 'doi', 'other'
    url: str


class ReferenceResult(BaseModel):
    """Result for a single reference check"""
    index: int
    title: str
    authors: List[str]
    year: Optional[str] = None
    venue: Optional[str] = None
    cited_url: Optional[str] = None
    status: str  # 'verified', 'error', 'warning', 'unverified'
    errors: List[ReferenceError] = []
    warnings: List[ReferenceError] = []
    authoritative_urls: List[ReferenceURL] = []
    corrected_reference: Optional[str] = None


class SummaryStats(BaseModel):
    """Summary statistics for check"""
    total_refs: int
    processed_refs: int
    errors_count: int
    warnings_count: int
    unverified_count: int
    verified_count: int
    progress_percent: float


class CheckStatus(str, Enum):
    """Status of check operation"""
    STARTED = "started"
    EXTRACTING = "extracting"
    CHECKING = "checking"
    COMPLETED = "completed"
    ERROR = "error"


class WebSocketMessage(BaseModel):
    """WebSocket message format"""
    type: str  # 'started', 'progress', 'reference_result', 'summary_update', 'completed', 'error'
    data: Dict[str, Any]


class CheckHistoryItem(BaseModel):
    """History item summary"""
    id: int
    paper_title: str
    paper_source: str
    timestamp: str
    total_refs: int
    errors_count: int
    warnings_count: int
    unverified_count: int
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    status: str = "completed"
    source_type: Optional[str] = None


class CheckHistoryDetail(CheckHistoryItem):
    """Detailed history item with full results"""
    results: List[ReferenceResult]
