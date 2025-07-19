#!/usr/bin/env python3
"""
Validation script for ArXiv Reference Checker

This script tests the reference checking logic with known references to validate
that it correctly identifies errors and passes correct references.
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

class MockPaper:
    """Mock paper class to simulate an ArXiv paper"""
    def __init__(self, paper_id, title, authors, year):
        self.paper_id = paper_id
        self.title = title
        self.authors = authors
        self.published = type('obj', (object,), {'year': year})

    def get_short_id(self):
        return self.paper_id

class MockAuthor:
    """Mock author class to simulate an ArXiv author"""
    def __init__(self, name):
        self.name = name

def create_test_references():
    """Create test references with known errors"""
    # These are real ArXiv papers
    arxiv_references = [
        # Correct reference
        {
            'url': 'https://arxiv.org/abs/2303.08774v1',  # Correct URL with version
            'year': 2023,  # Correct year
            'authors': ['OpenAI'],  # Correct author
            'title': 'State of GPT', # Incorrect title (should be 'GPT-4 Technical Report'),
            'type': 'arxiv'
        },
        # Correct reference with multiple authors
        {
            'url': 'https://arxiv.org/abs/1706.03762v7',  # Correct URL with version
            'year': 2017,  # Correct year
            'authors': ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar', 'Jakob Uszkoreit',
                       'Llion Jones', 'Aidan N. Gomez', 'Lukasz Kaiser', 'Illia Polosukhin'],  # Correct authors
            'title': 'Attention Is All You Need',
            'type': 'arxiv'
        },
        # Author error (missing authors)
        {
            'url': 'https://arxiv.org/abs/1706.03762v7',  # Correct URL with version
            'year': 2017,  # Correct year
            'authors': ['Ashish Vaswani', 'Noam Shazeer'],  # Incomplete author list
            'title': 'Attention Is All You Need',
            'type': 'arxiv'
        },
        # Year error
        {
            'url': 'https://arxiv.org/abs/1409.0473v7',  # Correct URL with version
            'year': 2015,  # Incorrect year (should be 2014)
            'authors': ['Dzmitry Bahdanau', 'Kyunghyun Cho', 'Yoshua Bengio'],  # Correct authors
            'title': 'Neural Machine Translation by Jointly Learning to Align and Translate',
            'type': 'arxiv'
        },
        # URL error (missing version)
        {
            'url': 'https://arxiv.org/abs/1706.03762',  # Missing version (should be v7)
            'year': 2017,  # Correct year
            'authors': ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar', 'Jakob Uszkoreit',
                       'Llion Jones', 'Aidan N. Gomez', 'Lukasz Kaiser', 'Illia Polosukhin'],  # Correct authors
            'title': 'Attention Is All You Need',
            'type': 'arxiv'
        }
    ]
    
    # These are non-arXiv papers (using DOI or other URLs)
    non_arxiv_references = [
        # Correct reference with DOI
        {
            'url': 'https://doi.org/10.1038/s41586-021-03819-2',
            'doi': '10.1038/s41586-021-03819-2',
            'year': 2021,
            'authors': ['Aakanksha Chowdhery', 'Sharan Narang', 'Jacob Devlin'],
            'title': 'PaLM: Scaling Language Modeling with Pathways',
            'raw_text': 'Chowdhery, A., Narang, S., Devlin, J. et al. PaLM: Scaling Language Modeling with Pathways. Nature, 2021.',
            'type': 'non-arxiv'
        },
        # Year error with DOI
        {
            'url': 'https://doi.org/10.1145/3442188.3445922',
            'doi': '10.1145/3442188.3445922',
            'year': 2020,  # Incorrect year (should be 2021)
            'authors': ['Timnit Gebru', 'Emily M. Bender', 'Angelina McMillan-Major', 'Shmargaret Shmitchell'], # incorrect author ordering
            'title': 'On the Dangers of Stochastic Parrots: Can Language Models Be Too Big?',
            'raw_text': 'Gebru, T., Bender, E. M., McMillan-Major, A., & Shmitchell, S. (2020). On the Dangers of Stochastic Parrots: Can Language Models Be Too Big? In Proceedings of the 2021 ACM Conference on Fairness, Accountability, and Transparency (pp. 610-623).',
            'type': 'non-arxiv'
        },
        # Author error with URL
        {
            'url': 'https://proceedings.neurips.cc/paper/2020/hash/1457c0d6bfcb4ab1d292c78e9a5ea4a1-Abstract.html',
            'year': 2020,
            'authors': ['Tom Brown', 'Benjamin Mann'],  # Incomplete author list
            'title': 'Language Models are Few-Shot Learners',
            'raw_text': 'Brown, T., Mann, B. (2020). Language Models are Few-Shot Learners. In Advances in Neural Information Processing Systems, 33, 1877-1901.',
            'type': 'non-arxiv'
        },
        # Reference without URL or DOI (should be verified using title and authors)
        {
            'url': '',
            'year': 2023, # incorrect year (should be 2024)
            'authors': ['Mark Russinovich', 'Ahmed Salem', 'Ronen Eldan'],
            'title': 'Great Now Write an Article About That: The Crescendo Multi-Turn LLM Jailbreak Attack',
            'raw_text': 'Russinovich, M., Salem, A., & Eldan, R. (2023). Great Now Write an Article About That: The Crescendo Multi-Turn LLM Jailbreak Attack.',
            'type': 'other'
        }
    ]
    
    # Combine both types of references
    return arxiv_references + non_arxiv_references

def validate_reference_checker(db_path=None):
    """Validate the reference checker logic"""
    # Create output directory
    output_dir = "validation_output"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Create a mock source paper
    source_paper = MockPaper(
        paper_id="test_paper_v1",
        title="Test Paper for Reference Validation",
        authors=[MockAuthor("Test Author")],
        year=2025
    )

    # Create test references
    test_references = create_test_references()

    # Initialize the reference checker
    checker = ArxivReferenceChecker(
        semantic_scholar_api_key=None,
        db_path=db_path,
        output_file=os.path.join(output_dir, 'validation_verification.txt'),
        enable_parallel=False  # Disable parallel for validation testing
    )

    # Database mode is automatically handled by the checker now

    # Override the output file
    checker.output_file = os.path.join(output_dir, 'validation_errors.csv')

    # Set debug mode to False for pretty printing
    debug_mode = False

    # Create output file with headers if it doesn't exist
    if not os.path.exists(checker.output_file):
        with open(checker.output_file, 'w', newline='', encoding='utf-8') as f:
            f.write('paper_id,reference_url,error_type,error_message,cited_info,actual_info\n')

    # Process each reference
    print("Validating reference checker with test references...")
    results = []

    for i, reference in enumerate(test_references):
        print(f"\nReference {i+1}:")
        print(f"  Title: {reference.get('title', 'No title provided')}")
        print(f"  URL: {reference['url']}")
        print(f"  Authors: {', '.join(reference['authors'])}")
        print(f"  Year: {reference['year']}")

        # Verify the reference
        errors, reference_url = checker.verify_reference(source_paper, reference)

        if errors:
            print(f"  Errors found: {len(errors)}")
            for error in errors:
                # Handle both error_type and warning_type
                error_type = error.get('error_type') or error.get('warning_type', 'unknown')
                error_details = error.get('error_details') or error.get('warning_details', 'No details provided')
                
                # Use different symbols for errors vs warnings
                if 'warning_type' in error:
                    print(f"    ⚠️ {error_type}: {error_details}")
                else:
                    print(f"    ❌ {error_type}: {error_details}")
                # Skip adding to dataset to avoid issues with the mock paper
                # checker.add_error_to_dataset(source_paper, reference, [error])
            results.append({"reference": reference, "errors": errors})
        else:
            print("  ✓ No errors found (reference is correct)")
            results.append({"reference": reference, "errors": None})

    # Save results to JSON for inspection
    with open(os.path.join(output_dir, 'validation_results.json'), 'w') as f:
        # Convert to serializable format
        serializable_results = []
        for result in results:
            serializable_result = {
                "reference": result["reference"],
                "errors": result["errors"] if result["errors"] else None
            }
            serializable_results.append(serializable_result)

        json.dump(serializable_results, f, indent=2)

    print(f"\nValidation complete. Results saved to {output_dir}/")
    return results

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate the ArXiv Reference Checker with test references")
    parser.add_argument("--db-path", type=str, help="Path to local Semantic Scholar database (automatically enables local DB mode)")
    # Note: Google Scholar API is used by default in enhanced hybrid mode
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    validate_reference_checker(db_path=args.db_path)
