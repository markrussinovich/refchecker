"""
Sample data for testing RefChecker functionality.
"""

# Sample paper content for testing
SAMPLE_PAPER_CONTENT = """
Attention Is All You Need: A Comprehensive Analysis

Abstract
We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.

1. Introduction
The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism.

2. Related Work
The goal of reducing sequential computation also forms the core motivation of the Extended Neural GPU, ByteNet and ConvS2S, all of which use convolutional neural networks as basic building block.

References

[1] Attention Is All You Need. Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Lukasz Kaiser, Illia Polosukhin. Neural Information Processing Systems, 2017. https://arxiv.org/abs/1706.03762

[2] BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding. Jacob Devlin, Ming-Wei Chang, Kenton Lee, Kristina Toutanova. 2018. https://arxiv.org/abs/1810.04805

[3] Language Models are Few-Shot Learners. Tom B. Brown, Benjamin Mann, Nick Ryder, Melanie Subbiah, Jared Kaplan, Prafulla Dhariwal, Arvind Neelakantan, Pranav Shyam, Girish Sastry, Amanda Askell, Sandhini Agarwal, Ariel Herbert-Voss, Gretchen Krueger, Tom Henighan, Rewon Child, Aditya Ramesh, Daniel M. Ziegler, Jeffrey Wu, Clemens Winter, Christopher Hesse, Mark Chen, Eric Sigler, Mateusz Litwin, Scott Gray, Benjamin Chess, Jack Clark, Christopher Berner, Sam McCandlish, Alec Radford, Ilya Sutskever, Dario Amodei. Neural Information Processing Systems, 2020.
"""

# Sample references for testing
SAMPLE_REFERENCES = [
    {
        'title': 'Attention Is All You Need',
        'authors': ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar', 'Jakob Uszkoreit', 'Llion Jones', 'Aidan N. Gomez', 'Lukasz Kaiser', 'Illia Polosukhin'],
        'year': 2017,
        'venue': 'Neural Information Processing Systems',
        'url': 'https://arxiv.org/abs/1706.03762',
        'doi': '10.48550/arXiv.1706.03762',
        'type': 'arxiv',
        'raw_text': '[1] Attention Is All You Need. Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Lukasz Kaiser, Illia Polosukhin. Neural Information Processing Systems, 2017. https://arxiv.org/abs/1706.03762'
    },
    {
        'title': 'BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding',
        'authors': ['Jacob Devlin', 'Ming-Wei Chang', 'Kenton Lee', 'Kristina Toutanova'],
        'year': 2018,
        'url': 'https://arxiv.org/abs/1810.04805',
        'doi': '10.48550/arXiv.1810.04805',
        'type': 'arxiv',
        'raw_text': '[2] BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding. Jacob Devlin, Ming-Wei Chang, Kenton Lee, Kristina Toutanova. 2018. https://arxiv.org/abs/1810.04805'
    },
    {
        'title': 'Language Models are Few-Shot Learners',
        'authors': ['Tom B. Brown', 'Benjamin Mann', 'Nick Ryder', 'Melanie Subbiah', 'Jared Kaplan', 'Prafulla Dhariwal', 'Arvind Neelakantan', 'Pranav Shyam', 'Girish Sastry', 'Amanda Askell', 'Sandhini Agarwal', 'Ariel Herbert-Voss', 'Gretchen Krueger', 'Tom Henighan', 'Rewon Child', 'Aditya Ramesh', 'Daniel M. Ziegler', 'Jeffrey Wu', 'Clemens Winter', 'Christopher Hesse', 'Mark Chen', 'Eric Sigler', 'Mateusz Litwin', 'Scott Gray', 'Benjamin Chess', 'Jack Clark', 'Christopher Berner', 'Sam McCandlish', 'Alec Radford', 'Ilya Sutskever', 'Dario Amodei'],
        'year': 2020,
        'venue': 'Neural Information Processing Systems',
        'type': 'journal',
        'raw_text': '[3] Language Models are Few-Shot Learners. Tom B. Brown, Benjamin Mann, Nick Ryder, Melanie Subbiah, Jared Kaplan, Prafulla Dhariwal, Arvind Neelakantan, Pranav Shyam, Girish Sastry, Amanda Askell, Sandhini Agarwal, Ariel Herbert-Voss, Gretchen Krueger, Tom Henighan, Rewon Child, Aditya Ramesh, Daniel M. Ziegler, Jeffrey Wu, Clemens Winter, Christopher Hesse, Mark Chen, Eric Sigler, Mateusz Litwin, Scott Gray, Benjamin Chess, Jack Clark, Christopher Berner, Sam McCandlish, Alec Radford, Ilya Sutskever, Dario Amodei. Neural Information Processing Systems, 2020.'
    }
]

# Sample GitHub references
GITHUB_REFERENCES = [
    {
        'title': 'PyTorch: An Imperative Style Deep Learning Framework',
        'authors': ['PyTorch Team'],
        'year': 2016,
        'url': 'https://github.com/pytorch/pytorch',
        'type': 'github',
        'raw_text': 'PyTorch: An Imperative Style Deep Learning Framework. PyTorch Team. 2016. https://github.com/pytorch/pytorch'
    },
    {
        'title': 'TensorFlow: Large-Scale Machine Learning on Heterogeneous Systems',
        'authors': ['TensorFlow Team'],
        'year': 2015,
        'url': 'https://github.com/tensorflow/tensorflow',
        'type': 'github',
        'raw_text': 'TensorFlow: Large-Scale Machine Learning on Heterogeneous Systems. TensorFlow Team. 2015. https://github.com/tensorflow/tensorflow'
    }
]

# Sample web page references
WEBPAGE_REFERENCES = [
    {
        'title': 'OpenAI API Documentation',
        'authors': ['OpenAI'],
        'year': 2023,
        'url': 'https://platform.openai.com/docs',
        'type': 'webpage',
        'raw_text': 'OpenAI API Documentation. OpenAI. 2023. https://platform.openai.com/docs'
    },
    {
        'title': 'Intel 4th Gen Xeon Scalable Processors',
        'authors': ['Intel Corporation'],
        'year': 2023,
        'url': 'https://www.intel.com/content/dam/www/central-libraries/us/en/documents/2023-09/4th-gen-xeon-revised-product-brief.pdf',
        'type': 'webpage',
        'raw_text': 'Intel 4th Gen Xeon Scalable Processors. Intel Corporation. 2023. https://www.intel.com/content/dam/www/central-libraries/us/en/documents/2023-09/4th-gen-xeon-revised-product-brief.pdf'
    }
]

# Sample malformed references for testing error handling
MALFORMED_REFERENCES = [
    {
        'title': '',  # Empty title
        'authors': [],  # No authors
        'year': None,
        'url': 'invalid_url',
        'raw_text': '[1] Malformed reference without proper structure'
    },
    {
        'title': 'Paper with Missing Fields',
        # Missing authors, year, url
        'raw_text': '[2] Paper with Missing Fields'
    },
    {
        # Completely empty reference
        'raw_text': '[3]'
    }
]

# Sample API responses for mocking
SEMANTIC_SCHOLAR_RESPONSES = {
    'attention_is_all_you_need': {
        'title': 'Attention Is All You Need',
        'authors': [
            {'name': 'Ashish Vaswani'},
            {'name': 'Noam Shazeer'},
            {'name': 'Niki Parmar'},
            {'name': 'Jakob Uszkoreit'},
            {'name': 'Llion Jones'},
            {'name': 'Aidan N. Gomez'},
            {'name': 'Lukasz Kaiser'},
            {'name': 'Illia Polosukhin'}
        ],
        'year': 2017,
        'venue': 'Neural Information Processing Systems',
        'url': 'https://arxiv.org/abs/1706.03762',
        'doi': '10.48550/arXiv.1706.03762',
        'citationCount': 50000,
        'paperId': 'test_paper_id_1'
    },
    'bert': {
        'title': 'BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding',
        'authors': [
            {'name': 'Jacob Devlin'},
            {'name': 'Ming-Wei Chang'},
            {'name': 'Kenton Lee'},
            {'name': 'Kristina Toutanova'}
        ],
        'year': 2018,
        'url': 'https://arxiv.org/abs/1810.04805',
        'doi': '10.48550/arXiv.1810.04805',
        'citationCount': 30000,
        'paperId': 'test_paper_id_2'
    }
}

OPENALEX_RESPONSES = {
    'attention_is_all_you_need': {
        'title': 'Attention Is All You Need',
        'authorships': [
            {'author': {'display_name': 'Ashish Vaswani'}},
            {'author': {'display_name': 'Noam Shazeer'}},
            {'author': {'display_name': 'Niki Parmar'}},
        ],
        'publication_year': 2017,
        'doi': '10.48550/arXiv.1706.03762',
        'host_venue': {'display_name': 'Neural Information Processing Systems'},
        'cited_by_count': 50000
    }
}

CROSSREF_RESPONSES = {
    'attention_doi': {
        'message': {
            'title': ['Attention Is All You Need'],
            'author': [
                {'given': 'Ashish', 'family': 'Vaswani'},
                {'given': 'Noam', 'family': 'Shazeer'},
            ],
            'published-print': {'date-parts': [[2017]]},
            'DOI': '10.48550/arXiv.1706.03762',
            'container-title': ['Neural Information Processing Systems']
        }
    }
}

GITHUB_API_RESPONSES = {
    'pytorch': {
        'name': 'pytorch',
        'full_name': 'pytorch/pytorch',
        'description': 'Tensors and Dynamic neural networks in Python with strong GPU acceleration',
        'html_url': 'https://github.com/pytorch/pytorch',
        'owner': {'login': 'pytorch'},
        'created_at': '2016-08-13T11:14:46Z',
        'updated_at': '2023-12-01T10:30:00Z',
        'stargazers_count': 50000,
        'language': 'Python',
        'license': {'name': 'BSD 3-Clause "New" or "Revised" License'}
    },
    'tensorflow': {
        'name': 'tensorflow',
        'full_name': 'tensorflow/tensorflow',
        'description': 'An Open Source Machine Learning Framework for Everyone',
        'html_url': 'https://github.com/tensorflow/tensorflow',
        'owner': {'login': 'tensorflow'},
        'created_at': '2015-11-07T01:19:20Z',
        'updated_at': '2023-12-01T09:15:00Z',
        'stargazers_count': 180000,
        'language': 'C++',
        'license': {'name': 'Apache License 2.0'}
    }
}

# Sample HTML content for web page testing
SAMPLE_HTML_PAGES = {
    'openai_docs': """
    <!DOCTYPE html>
    <html>
    <head>
        <title>OpenAI API Documentation</title>
        <meta name="description" content="Complete guide to OpenAI API usage and integration.">
    </head>
    <body>
        <h1>OpenAI API Documentation</h1>
        <p>Welcome to the OpenAI API documentation. This guide covers all aspects of API usage.</p>
        <h2>Getting Started</h2>
        <p>To get started with the OpenAI API, you'll need an API key.</p>
    </body>
    </html>
    """,
    'intel_product_brief': """
    <!DOCTYPE html>
    <html>
    <head>
        <title>4th Gen Intel Xeon Scalable Processors</title>
        <meta name="description" content="Product brief for Intel 4th generation Xeon scalable processors.">
    </head>
    <body>
        <h1>4th Gen Intel® Xeon® Scalable Processors</h1>
        <p>The Intel Xeon Scalable processor family delivers breakthrough performance improvements.</p>
        <h2>Key Features</h2>
        <ul>
            <li>Enhanced AI performance</li>
            <li>Improved memory bandwidth</li>
            <li>Advanced security features</li>
        </ul>
    </body>
    </html>
    """
}

# Sample LLM responses for testing
SAMPLE_LLM_RESPONSES = {
    'structured_extraction': """
    Title: Attention Is All You Need
    Authors: Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Lukasz Kaiser, Illia Polosukhin
    Year: 2017
    Venue: Neural Information Processing Systems
    URL: https://arxiv.org/abs/1706.03762
    """,
    'malformed_response': """
    This is not a properly structured response.
    It doesn't follow the expected format and 
    might contain unrelated information.
    """,
    'partial_response': """
    Title: Partial Paper Information
    Authors: Some Author
    # Missing year, venue, URL
    """
}

# Test configuration
TEST_CONFIG = {
    'chunk_size': 1000,
    'overlap_size': 200,
    'max_references_per_paper': 100,
    'api_timeout': 30,
    'retry_attempts': 3,
    'rate_limit_delay': 1
}

# Known arXiv paper IDs for testing
ARXIV_PAPER_IDS = [
    "1706.03762",  # Attention Is All You Need
    "1810.04805",  # BERT
    "2005.14165",  # GPT-3 (Language Models are Few-Shot Learners)
    "1411.1784",   # Adam optimizer
    "1512.03385",  # ResNet
]

# Common venue name variations for testing
VENUE_VARIATIONS = {
    'nips_variations': [
        'NIPS',
        'Neural Information Processing Systems',
        'Advances in Neural Information Processing Systems',
        'NeurIPS'
    ],
    'icml_variations': [
        'ICML',
        'International Conference on Machine Learning',
        'Proc. of ICML',
        'Proceedings of ICML'
    ],
    'iclr_variations': [
        'ICLR',
        'International Conference on Learning Representations',
        'Proc. of ICLR'
    ]
}