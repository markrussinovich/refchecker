#!/usr/bin/env python3
"""
Validation script for ArXiv Reference Checker using the "Attention Is All You Need" paper

This script tests the reference checking logic with the well-known "Attention Is All You Need" paper
to validate that it correctly identifies errors and passes correct references.
"""

import arxiv
import logging
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Import all modules to ensure they're available
import checkers.semantic_scholar
import checkers.local_semantic_scholar
import checkers.enhanced_hybrid_checker
import utils.text_utils
import utils.author_utils

from core.refchecker import ArxivReferenceChecker, setup_logging

# Set up logging
logger = setup_logging()

def validate_attention_paper(semantic_scholar_api_key=None, db_path=None):
    """
    Validate the reference checker with the Attention Is All You Need paper
    
    Args:
        semantic_scholar_api_key: Optional API key for Semantic Scholar
        db_path: Path to the local Semantic Scholar database (automatically enables local DB mode)
    """
    # Initialize the reference checker
    checker = ArxivReferenceChecker(
        semantic_scholar_api_key=semantic_scholar_api_key,
        db_path=db_path,
        enable_parallel=False  # Disable parallel for validation testing
    )

    # Database mode is automatically handled by the checker now

    # Set debug mode to False for pretty printing
    debug_mode = False

    # Get the Attention Is All You Need paper
    print("Fetching the 'Attention Is All You Need' paper...")

    # Use the arxiv ID for the paper
    arxiv_id = "1706.03762"

    # Get the paper metadata
    client = arxiv.Client()
    search = arxiv.Search(id_list=[arxiv_id])
    results = list(client.results(search))

    if not results:
        print(f"Error: Could not find paper with ID {arxiv_id}")
        return

    paper = results[0]
    print(f"Found paper: {paper.title} by {', '.join([author.name for author in paper.authors])}")

    # Process the paper
    print("\nExtracting bibliography and checking references...")

    # Extract bibliography
    bibliography = checker.extract_bibliography(paper)

    if not bibliography:
        print("No bibliography found or no references with arxiv links extracted.")
        return

    print(f"Extracted {len(bibliography)} references with arxiv links.")

    # Check each reference
    error_count = 0
    for i, reference in enumerate(bibliography):
        print(f"\nReference {i+1}:")
        print(f"  URL: {reference['url']}")
        print(f"  DOI: {reference.get('doi', 'N/A')}")
        if reference.get('doi'):
            print(f"  DOI: {reference['doi']}")
        else:
            print("  DOI: N/A")
        print(f"  Type: {reference.get('type', 'unknown')}")
        print(f"  Title: {reference['title']}")
        print(f"  Authors: {', '.join(reference['authors'])}")
        print(f"  Year: {reference['year']}")

        # Verify the reference
        errors, reference_url, verified_data = checker.verify_reference(paper, reference)

        if errors:
            error_count += 1
            print(f"  Errors found: {len(errors)}")
            print("   Raw text:")
            print(f"    {reference['raw_text']}")
            for error in errors:
                # Handle both error_type and warning_type
                if 'error_type' in error:
                    print(f"    - {error['error_type']}: {error['error_details']}")
                elif 'warning_type' in error:
                    print(f"    - {error['warning_type']}: {error['warning_details']}")
                else:
                    # Fallback for unexpected error structure
                    print(f"    - unknown: {error}")
        else:
            print("  ✓ No errors found (reference is correct)")

    # Print summary
    print("\nValidation complete.")
    print(f"Total references checked: {len(bibliography)}")
    print(f"References with errors: {error_count}")
    print(f"References without errors: {len(bibliography) - error_count}")

    return bibliography, error_count

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate the ArXiv Reference Checker with the Attention Is All You Need paper")
    parser.add_argument("--semantic-scholar-api-key", type=str, help="API key for Semantic Scholar (optional)")
    parser.add_argument("--db-path", type=str, help="Path to local Semantic Scholar database (automatically enables local DB mode)")
    # Note: Enhanced hybrid mode (including Google Scholar) is used by default
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.db_path:
        print(f"Using local Semantic Scholar database at {args.db_path}")
        args.semantic_scholar_api_key = None
    
    validate_attention_paper(
        semantic_scholar_api_key=args.semantic_scholar_api_key,
        db_path=args.db_path
    )
