#!/usr/bin/env python3
"""
Validation script for ArXiv Reference Checker

This script tests the reference checking logic with specific papers to validate
that it correctly identifies errors and passes correct references.
"""

import arxiv
import logging
import json
import os
import sys
import argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Import all modules to ensure they're available
import checkers.semantic_scholar
import checkers.google_scholar 
import checkers.local_semantic_scholar
import checkers.hybrid_reference_checker
import utils.text_utils
import utils.author_utils

from core.refchecker import ArxivReferenceChecker, setup_logging

# Set up logging
logger = setup_logging()

def validate_paper(arxiv_id, output_prefix=None, semantic_scholar_api_key=None, db_path=None, use_google_scholar=True):
    """
    Validate the reference checker with a specific paper
    
    Args:
        arxiv_id: ArXiv ID of the paper to validate
        output_prefix: Prefix for output files (defaults to paper ID)
        semantic_scholar_api_key: Optional API key for Semantic Scholar
        db_path: Path to the local Semantic Scholar database (automatically enables local DB mode)
        use_google_scholar: Whether to use Google Scholar API instead of Semantic Scholar
    """
    # Create output directory
    output_dir = "validation_output"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Initialize the reference checker
    checker = ArxivReferenceChecker(
        semantic_scholar_api_key=semantic_scholar_api_key,
        db_path=db_path,
        use_google_scholar=use_google_scholar
    )

    # Set output prefix if not provided
    if not output_prefix:
        output_prefix = arxiv_id.replace('.', '_')

    # Override the output file
    checker.output_file = os.path.join(output_dir, f'{output_prefix}_errors.csv')

    # Set debug mode to False for pretty printing
    debug_mode = False

    # Create output file with headers if it doesn't exist
    if not os.path.exists(checker.output_file):
        with open(checker.output_file, 'w', newline='', encoding='utf-8') as f:
            f.write('paper_id,reference_url,error_type,error_message,cited_info,actual_info\n')

    # Get the paper
    print(f"Fetching paper with ID {arxiv_id}...")

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
        print("No bibliography found or no references extracted.")
        return

    # Count references by type
    arxiv_refs = [ref for ref in bibliography if ref.get('type') == 'arxiv']
    non_arxiv_refs = [ref for ref in bibliography if ref.get('type') == 'non-arxiv']
    
    print(f"Extracted {len(bibliography)} total references:")
    print(f"  - {len(arxiv_refs)} arXiv references")
    print(f"  - {len(non_arxiv_refs)} non-arXiv references")

    # Check each reference
    error_count = 0
    for i, reference in enumerate(bibliography):
        ref_type = reference.get('type', 'unknown')
        print(f"\nReference {i+1} ({ref_type}):")
        print(f"  URL: {reference['url']}")
        if reference.get('doi'):
            print(f"  DOI: {reference['doi']}")
        print(f"  Authors: {', '.join(reference['authors'])}")
        print(f"  Year: {reference['year']}")
        if reference.get('title'):
            print(f"  Title: {reference['title']}")

        # Verify the reference
        errors = checker.verify_reference(paper, reference)

        if errors:
            error_count += 1
            print(f"  Errors found: {len(errors)}")
            for error in errors:
                print(f"    - {error['error_type']}: {error['error_details']}")
        else:
            print("  ✓ No errors found (reference is correct)")

    # Print summary
    print("\nValidation complete.")
    print(f"Total references checked: {len(bibliography)}")
    print(f"References with errors: {error_count}")
    print(f"References without errors: {len(bibliography) - error_count}")

    # Save results to JSON for inspection
    with open(os.path.join(output_dir, f'{output_prefix}_results.json'), 'w') as f:
        json.dump({
            "paper_id": paper.get_short_id(),
            "paper_title": paper.title,
            "paper_authors": [author.name for author in paper.authors],
            "total_references": len(bibliography),
            "arxiv_references": len(arxiv_refs),
            "non_arxiv_references": len(non_arxiv_refs),
            "references_with_errors": error_count,
            "references_without_errors": len(bibliography) - error_count
        }, f, indent=2)

    print(f"\nResults saved to {output_dir}/")
    return bibliography, error_count

def validate_attention_paper(semantic_scholar_api_key=None, db_path=None, use_google_scholar=True):
    """Validate the reference checker with the Attention Is All You Need paper"""
    return validate_paper("1706.03762", "attention_paper", semantic_scholar_api_key, db_path, use_google_scholar)

def validate_website_references_paper(semantic_scholar_api_key=None, db_path=None, use_google_scholar=True):
    """Validate the reference checker with a paper that has website references"""
    return validate_paper("2404.01833", "website_references_paper", semantic_scholar_api_key, db_path, use_google_scholar)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate the ArXiv Reference Checker with specific papers")
    parser.add_argument("--paper", choices=["attention", "website", "custom"], default="attention",
                        help="Paper to validate: 'attention' for Attention Is All You Need, 'website' for paper with website references, or 'custom' for a custom paper ID")
    parser.add_argument("--arxiv-id", type=str, help="Custom ArXiv ID to validate (used with --paper=custom)")
    parser.add_argument("--semantic-scholar-api-key", type=str, help="API key for Semantic Scholar (optional)")
    parser.add_argument("--db-path", type=str, help="Path to local Semantic Scholar database (automatically enables local DB mode)")
    parser.add_argument("--use-google-scholar", action="store_true", default=True, help="Use Google Scholar API instead of Semantic Scholar (default: True)")
    parser.add_argument("--no-google-scholar", action="store_false", dest="use_google_scholar", help="Don't use Google Scholar API")
    args = parser.parse_args()

    if args.paper == "attention":
        validate_attention_paper(args.semantic_scholar_api_key, args.db_path, args.use_google_scholar)
    elif args.paper == "website":
        validate_website_references_paper(args.semantic_scholar_api_key, args.db_path, args.use_google_scholar)
    elif args.paper == "custom":
        if not args.arxiv_id:
            print("Error: --arxiv-id is required when using --paper=custom")
            sys.exit(1)
        validate_paper(args.arxiv_id, semantic_scholar_api_key=args.semantic_scholar_api_key, 
                      db_path=args.db_path, use_google_scholar=args.use_google_scholar)
    else:
        print(f"Error: Unknown paper type: {args.paper}")
        sys.exit(1)
