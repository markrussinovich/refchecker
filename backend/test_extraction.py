#!/usr/bin/env python3
"""Quick test of reference extraction with the fix"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from database import Database
from refchecker_wrapper import ProgressRefChecker
import arxiv
from refchecker.services.pdf_processor import PDFProcessor

async def test():
    db = Database()
    await db.init_db()
    
    configs = await db.get_llm_configs()
    config = await db.get_llm_config_by_id(configs[0]['id'])
    print(f"Using: {config['provider']}/{config['model']}")
    
    checker = ProgressRefChecker(
        llm_provider=config['provider'],
        llm_model=config['model'],
        api_key=config.get('api_key'),
        use_llm=True,
        progress_callback=None
    )
    
    arxiv_id = "2310.02238"
    print(f"Fetching paper {arxiv_id}...")
    search = arxiv.Search(id_list=[arxiv_id])
    paper = next(search.results())
    print(f"Title: {paper.title}")
    
    pdf_path = f"/tmp/arxiv_{arxiv_id}.pdf"
    paper.download_pdf(filename=pdf_path)
    
    pdf_processor = PDFProcessor()
    paper_text = pdf_processor.extract_text_from_pdf(pdf_path)
    print(f"Extracted {len(paper_text)} chars of text")
    
    refs = await checker._extract_references(paper_text)
    print(f"\nExtracted {len(refs)} references:")
    
    # Write results to file
    with open('extraction_test.txt', 'w', encoding='utf-8') as f:
        f.write(f"Extracted {len(refs)} references:\n\n")
        for i, ref in enumerate(refs, 1):
            title = ref.get('title', 'Unknown')
            authors = ref.get('authors', [])
            year = ref.get('year')
            f.write(f"{i}. {title}\n")
            f.write(f"   Authors: {', '.join(authors[:3])}{'...' if len(authors) > 3 else ''}\n")
            f.write(f"   Year: {year}\n\n")
    
    print("Results written to extraction_test.txt")
    
    # Show first 3
    for i, ref in enumerate(refs[:3], 1):
        title = ref.get('title', 'Unknown')[:60]
        print(f"  {i}. {title}")

asyncio.run(test())
