#!/usr/bin/env python3
"""
Validation script for Local Semantic Scholar Database

This script tests the local Semantic Scholar database functionality by verifying references
for a specific paper. It first downloads paper metadata for the Attention Is All You Need paper
and its references, then validates the references using the local database.

Usage:
    python validate_local_db.py [--db-path PATH] [--api-key KEY]
    
Options:
    --db-path PATH         Path to the local Semantic Scholar database (default: semantic_scholar_db/semantic_scholar.db)
    --api-key KEY          Semantic Scholar API key (optional, increases rate limits)
"""

import argparse
import logging
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
try:
    from database.download_semantic_scholar_db import SemanticScholarDownloader
except ImportError:
    from download_semantic_scholar_db import SemanticScholarDownloader
from validate_papers import validate_paper

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def download_attention_paper_data(api_key=None, db_path=None):
    """
    Download metadata for the Attention Is All You Need paper and its references
    
    Args:
        api_key: Semantic Scholar API key (optional)
        db_path: Path to the local database (default: semantic_scholar_db/semantic_scholar.db)
    """
    # Set default database path
    if not db_path:
        db_path = "semantic_scholar_db/semantic_scholar.db"
    
    # Extract directory from database path
    db_dir = os.path.dirname(db_path)
    
    logger.info("Downloading metadata for the Attention Is All You Need paper and its references")
    
    # Initialize downloader
    downloader = SemanticScholarDownloader(
        output_dir=db_dir,
        batch_size=50,
        api_key=api_key,
        fields=["id", "title", "authors", "year", "externalIds", "url", "abstract", "references"]
    )
    
    try:
        # Search for the Attention paper
        logger.info("Searching for the Attention Is All You Need paper")
        paper_ids = downloader.search_papers(
            query="Attention Is All You Need Vaswani",
            start_year=2017,
            end_year=2017,
            limit=10
        )
        
        if not paper_ids:
            logger.error("Could not find the Attention Is All You Need paper")
            return False
        
        # Download the paper
        logger.info("Downloading the Attention paper metadata")
        downloader.download_papers(paper_ids)
        
        # Get reference IDs from the paper
        logger.info("Extracting reference IDs from the paper")
        reference_ids = []
        
        # Query the database for the paper using the new column-based schema
        cursor = downloader.conn.cursor()
        cursor.execute("SELECT json_data FROM papers WHERE title LIKE '%Attention Is All You Need%'")
        row = cursor.fetchone()
        
        if row:
            import json
            paper_data = json.loads(row[0])
            references = paper_data.get("references", [])
            reference_ids = [ref.get("paperId") for ref in references if ref.get("paperId")]
            logger.info(f"Found {len(reference_ids)} reference IDs")
        else:
            logger.warning("Could not find the paper in the database")
        
        # Download reference metadata
        if reference_ids:
            logger.info(f"Downloading metadata for {len(reference_ids)} references")
            downloader.download_papers(reference_ids)
        
        # Download some additional papers for testing
        logger.info("Downloading additional papers for testing")
        additional_ids = downloader.search_papers(
            query="transformer neural machine translation",
            start_year=2015,
            end_year=2018,
            limit=100
        )
        
        if additional_ids:
            logger.info(f"Downloading metadata for {len(additional_ids)} additional papers")
            downloader.download_papers(additional_ids)
        
        logger.info("Database download complete")
        return True
    except Exception as e:
        logger.error(f"Error downloading paper data: {str(e)}")
        return False
    finally:
        # Close database connection
        downloader.close()

def validate_local_db(db_path=None):
    """
    Validate the local Semantic Scholar database by verifying references for a paper
    
    Args:
        db_path: Path to the local database (default: semantic_scholar_db/semantic_scholar.db)
    """
    # Set default database path
    if not db_path:
        db_path = "semantic_scholar_db/semantic_scholar.db"
    
    # Check if the database exists
    if not os.path.exists(db_path):
        logger.error(f"Database file not found: {db_path}")
        return False
    
    logger.info(f"Validating local database: {db_path}")
    
    # Validate the Attention Is All You Need paper using the local database
    logger.info("Validating references for the Attention Is All You Need paper")
    validate_paper(
        "1706.03762",
        output_prefix="local_db_attention_paper",
        db_path=db_path
    )
    
    logger.info("Validation complete")
    return True

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Validate the local Semantic Scholar database")
    parser.add_argument("--db-path", type=str,
                        help="Path to the local Semantic Scholar database (default: semantic_scholar_db/semantic_scholar.db)")
    parser.add_argument("--api-key", type=str,
                        help="Semantic Scholar API key (optional, increases rate limits)")
    parser.add_argument("--download-only", action="store_true",
                        help="Only download the database, don't validate")
    parser.add_argument("--validate-only", action="store_true",
                        help="Only validate the database, don't download")
    
    args = parser.parse_args()
    
    # Set default database path
    db_path = args.db_path or "semantic_scholar_db/semantic_scholar.db"
    
    # Create database directory if it doesn't exist
    db_dir = os.path.dirname(db_path)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
    
    # Download data if needed
    if not args.validate_only:
        success = download_attention_paper_data(api_key=args.api_key, db_path=db_path)
        if not success:
            logger.error("Failed to download paper data")
            return 1
    
    # Validate the database if needed
    if not args.download_only:
        success = validate_local_db(db_path=db_path)
        if not success:
            logger.error("Failed to validate local database")
            return 1
    
    logger.info("All operations completed successfully")
    return 0

if __name__ == "__main__":
    sys.exit(main())
