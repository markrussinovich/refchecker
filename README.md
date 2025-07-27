# 📚 Academic Paper Reference Checker

*Developed by Mark Russinovich with various AI assistants, including Cursor, GitHub Copilot and Claude Code*

A comprehensive tool for validating reference accuracy in academic papers, useful for both authors checking their bibliography and conference reviewers ensuring that paper references are authentic and accurate. This tool processes papers from various local and online sources including ArXiv, PDF files, LaTeX documents, and text files to verify the accuracy of references by comparing cited information against authoritative sources.

## 📊 Sample Output

```
📄 Processing: Attention Is All You Need
   URL: https://arxiv.org/abs/1706.03762

[1/45] Neural machine translation in linear time
       Nal Kalchbrenner, Lasse Espeholt, Karen Simonyan, Aaron van den Oord, Alex Graves, Koray Kavukcuoglu
       2017
         ⚠️  year: Year mismatch: cited as 2017 but actually 2016

[2/45] Effective approaches to attention-based neural machine translation
       Minh-Thang Luong, Hieu Pham, Christopher D. Manning
       2015
         ❌  author: First author mismatch: 'Minh-Thang Luong' vs 'Thang Luong'

[3/45] Deep Residual Learning for Image Recognition
       Kaiming He, Xiangyu Zhang, Shaoqing Ren, Jian Sun
       Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition
       2016
       https://doi.org/10.1109/CVPR.2016.91
         ❌  doi: DOI mismatch: cited as '10.1109/CVPR.2016.91' but actually '10.1109/CVPR.2016.90'

============================================================
📋 SUMMARY
============================================================
📚 Total references processed: 68
❌ Total errors: 55
⚠️  Total warnings: 16
❓ References that couldn't be verified: 15

💾 Detailed results saved to: reference_errors.txt
```

## 📋 Table of Contents

- [📊 Sample Output](#-sample-output)
- [🎯 Features](#-features)
- [🚀 Quick Start](#-quick-start)
- [🤖 LLM-Enhanced Reference Extraction](#-llm-enhanced-reference-extraction)
- [📦 Installation](#-installation)
- [📖 Usage](#-usage)
- [📊 Output and Results](#-output-and-results)
- [⚙️ Configuration](#-configuration)
- [🗄️ Local Database Setup](#-local-database-setup)
- [🧪 Testing](#-testing)
- [📦 Building the Package](#-building-the-package)
- [📄 License](#-license)

## 🎯 Features

- **📄 Multiple Input Formats**: Process ArXiv papers, local PDFs, LaTeX files, and text documents
- **🔍 Advanced Bibliography Detection**: Uses intelligent pattern matching to identify bibliography sections
- **🤖 LLM-Enhanced Reference Extraction**: Recommended AI-powered bibliography parsing with support for OpenAI, Anthropic, Google, Azure, and local vLLM
- **✅ Comprehensive Error Detection**: Identifies issues with titles, authors, years, venues, URLs, and DOIs
- **🔄 Multi-Tier Verification Sources**: Uses a prioritized check of Semantic Scholar, OpenAlex, and CrossRef with intelligent retry logic
- **🧠 Smart Title Matching**: Advanced similarity algorithms handle common academic formatting variations (BERT vs B-ERT, pre-trained vs pretrained)
- **🏢 Venue Normalization**: Recognizes common journal and conference abbreviation patterns
- **📊 Detailed Reporting**: Generates comprehensive error reports with drop-in corrected references

## 🚀 Quick Start

### Check Your First Paper

1. **Check a famous paper:**
   ```bash
   python refchecker.py --paper 1706.03762
   ```

2. **Check your own PDF:**
   ```bash
   python refchecker.py --paper /path/to/your/paper.pdf
   ```

3. **For faster processing with local database** (see [Local Database Setup](#local-database-setup)):
   ```bash
   python refchecker.py --paper 1706.03762 --db-path semantic_scholar_db/semantic_scholar.db
   ```

> **⚡ Performance Tip**: Reference verification takes 5-10 seconds per reference without a Semantic Scholar API key due to rate limiting. With an API key, verification speeds up to 1-2 seconds per reference. Set `SEMANTIC_SCHOLAR_API_KEY` environment variable or use `--semantic-scholar-api-key` for faster processing.

## 🤖 LLM-Enhanced Reference Extraction

RefChecker supports AI-powered bibliography parsing using Large Language Models (LLMs) for improved accuracy with complex citation formats. While models as small as Llama 3.1-8B are fairly reliable at reference extraction, they can struggle with non-standard bibliographies. GPT-4o frequently hallucinates DOIs while Sonnet 4 has shown the best performance on large, complex bibliographies.

### Supported LLM Providers

- **OpenAI** e.g., GPT-4o, o3
- **Anthropic** e.g., Claude Sonnet 4
- **Google** e.g., Gemini 2.5
- **Azure OpenAI** e.g., GPT-4o, o3
- **vLLM** e.g., Local Hugging Face models via OpenAI-compatible server

### Quick LLM Setup 

1. **Using Environment Variables**:
   ```bash
   # Enable LLM with Anthropic Claude
   export REFCHECKER_USE_LLM=true
   export REFCHECKER_LLM_PROVIDER=anthropic
   export ANTHROPIC_API_KEY=your_api_key_here
   
   python refchecker.py --paper 1706.03762
   ```

2. **Using Command Line Arguments**:
   ```bash
   # Enable LLM with specific provider and model
   python refchecker.py --paper 1706.03762 \
     --llm-provider anthropic \
     --llm-model claude-sonnet-4-20250514 \
   ```
   API keys are obtained from environment variables, or if not found, the tool will prompt you interactively to enter them securely.

### LLM Examples

#### OpenAI GPT-4

With `OPENAI_API_KEY` environment variable: 

```bash
python refchecker.py --paper /path/to/paper.pdf \
  --llm-provider openai \
  --llm-model gpt-4o \
```

#### Anthropic Claude

With `ANTHROPIC_API_KEY` environment variable: 

```bash
python refchecker.py --paper https://arxiv.org/abs/1706.03762 \
  --llm-provider anthropic \
  --llm-model claude-sonnet-4-20250514 \
```

#### Google Gemini

```bash
python refchecker.py --paper paper.tex \
  --llm-provider google \
  --llm-model gemini-2.5-flash
```

#### Azure OpenAI

```bash
python refchecker.py --paper paper.txt \
  --llm-provider azure \
  --llm-model gpt-4 \
  --llm-endpoint https://your-resource.openai.azure.com/
```

#### vLLM (Local Models)

For running models locally:

```bash
# automatic Huggingface model download with VLLM server launch 
python refchecker.py --paper paper.pdf \
  --llm-provider vllm \
  --llm-model meta-llama/Llama-3.1-8B-Instruct 
```

You can debug vllm server issues by running refchecker with the `--debug` flag. 

## 📦 Installation

### Option 1: Install from Test PyPI (Recommended for Testing)

For the latest development version with all features:

```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ refchecker[llm,dev,optional]
```

This installs RefChecker with:
- **llm**: Support for OpenAI, Anthropic, Google, Azure, and vLLM providers
- **dev**: Development tools (pytest, black, flake8, mypy)
- **optional**: Enhanced features (lxml, selenium, pikepdf, nltk, scikit-learn)

For a minimal installation:
```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ refchecker
```

### Option 2: Install from Source

#### 1. Clone the Repository

```bash
git clone https://github.com/markrussinovich/refchecker.git
cd refchecker
```

#### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 3. (Optional) Install Additional Dependencies

For enhanced performance and LLM support, you can install optional dependencies:

```bash
# For LLM providers
pip install openai           # For OpenAI GPT models
pip install anthropic        # For Anthropic Claude models
pip install google-generativeai  # For Google Gemini models

# For faster XML/HTML parsing
pip install lxml

# For dynamic web scraping (if needed)
pip install selenium

# For better PDF processing
pip install pikepdf
```

## 📖 Usage

Check papers in various formats and online locations:

#### ArXiv Papers

```bash
# Check a specific ArXiv paper by ID
python refchecker.py --paper 1706.03762

# Check by ArXiv URL
python refchecker.py --paper https://arxiv.org/abs/1706.03762

# Check by ArXiv PDF URL
python refchecker.py --paper https://arxiv.org/pdf/1706.03762.pdf
```

#### Local PDF Files

```bash
# Check a local PDF file
python refchecker.py --paper /path/to/your/paper.pdf

# Check with offline database for faster processing
python refchecker.py --paper /path/to/your/paper.pdf --db-path semantic_scholar_db/semantic_scholar.db
```

#### LaTeX Files

```bash
# Check a LaTeX document
python refchecker.py --paper /path/to/your/paper.tex

# Check with debug mode for detailed processing info
python refchecker.py --paper /path/to/your/paper.tex --debug
```

#### Text Files

```bash
# Check a plain text file containing paper content
python refchecker.py --paper /path/to/your/paper.txt

# Combine with local database for offline verification
python refchecker.py --paper /path/to/your/paper.txt --db-path semantic_scholar_db/semantic_scholar.db
```

## 📊 Output and Results

### Generated Files

- **`reference_errors.txt`**: Detailed report of references with errors and warnings, including corrected references

### Error Types

- **❌ Errors**: Critical issues that need correction
  - `author`: Author name mismatches
    ```
    [16/19] Bag of tricks: Benchmarking of jailbreak attacks on llms
           T. Xie, X. Qi, Y. Zeng, Y. Huang, U. M. Sehwag, K. Huang, L. He, B. Wei, D. Li, Y. Sheng et al
           ❌  author: First author mismatch: 'T. Xie' vs 'Zhao Xu'
    ```
  - `title`: Title discrepancies
    ```
    [8/19] BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding
           J. Devlin, M.-W. Chang, K. Lee, K. Toutanova
           ❌  title: Title mismatch: cited as 'BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding' but actually 'BERT: Pre-training of Deep Bidirectional Transformers for Language Comprehension'
    ```
  - `url`: Incorrect URLs or arXiv IDs
    ```
    [5/19] Jbshield: Neural representation-level defense against adversarial prompts in large language models
           W. Zhang, M. Li, H. Wang
           ❌  arxiv_id: Incorrect ArXiv ID: ArXiv ID 2503.01234 points to 'Self-Adaptive Gamma Context-Aware SSM-based Model for Metal Defect Detection'
    ```
  - `doi`: DOI mismatches
    ```
    [12/19] Attention Is All You Need
           Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Lukasz Kaiser, Illia Polosukhin
           Neural Information Processing Systems
           2017
           https://doi.org/10.5555/3295222.3295349
           ❌  doi: DOI mismatch: cited as '10.5555/3295222.3295349' but actually '10.48550/arXiv.1706.03762'
    ```

- **⚠️ Warnings**: Minor issues that may need attention
  - `year`: Publication year differences (common due to multiple paper versions)
    ```
    [14/19] Smoothllm: Defending large language models against jailbreaking attacks
           A. Robey, E. Wong, H. Hassani, G. J. Pappas
           ⚠️  year: Year mismatch: cited as 2024 but actually 2023
    ```
  - `venue`: Venue format variations
    ```
    [2/19] Gradient cuff: Detecting jailbreak attacks on large language models by exploring refusal loss landscapes
           X. Hu, P.-Y. Chen, T.-Y. Ho
           ⚠️  venue: Venue mismatch: cited as 'arXiv, 2024' but actually 'Neural Information Processing Systems'
    ```

- **❓ Unverified**: References that couldn't be verified with any of the checker APIs
  ```
  [15/19] Llama guard: A fine-tuned safety model for prompt moderation
         M. A. Research
         ❓ Could not verify: Llama guard: A fine-tuned safety model for prompt moderation
            Cited as: M. A. Research (2024)
            URL: https://research.meta.com/publications/llama-guard-a-fine-tuned-safety-model-for-prompt-moderation/
  ```

## ⚙️ Configuration

### Command Line Arguments

```bash
# Basic options
--paper PAPER                    # Paper to check (ArXiv ID, URL, or file path)
--debug                          # Enable debug mode
--semantic-scholar-api-key KEY   # Semantic Scholar API key (1-2s vs 5-10s without key; can also use SEMANTIC_SCHOLAR_API_KEY env var) 
--db-path PATH                   # Local database path

# LLM options
--llm-provider {openai,anthropic,google,azure,vllm}  # Enable LLM with provider
--llm-model MODEL                # Override default model
--llm-endpoint URL               # Override endpoint (for Azure/vLLM)
```

### API Key Handling

The refchecker tool automatically handles API keys for LLM providers in the following order:

1. **Environment Variables** (recommended): The tool checks for provider-specific environment variables
2. **Interactive Prompts**: If no API key is found in environment variables, the tool will securely prompt you to enter it

When you use an LLM provider without setting the corresponding environment variable, you'll see a prompt like:
```
OpenAI API key not found in environment variables.
Checked environment variables: REFCHECKER_OPENAI_API_KEY, OPENAI_API_KEY
Please enter your OpenAI API key (input will be hidden):
API key: [your input is hidden]
```

This approach ensures your API keys are never exposed in command line history while providing a seamless user experience.

### Environment Variables

```bash
# Enable/disable LLM
export REFCHECKER_USE_LLM=true

# Provider selection
export REFCHECKER_LLM_PROVIDER=anthropic        # openai, anthropic, google, azure

# Semantic Scholar API key (for higher rate limits and faster verification: 1-2s vs 5-10s without key)
export SEMANTIC_SCHOLAR_API_KEY=your_key

# Provider-specific API keys (native environment variables preferred)
export OPENAI_API_KEY=your_key                    # or REFCHECKER_OPENAI_API_KEY
export ANTHROPIC_API_KEY=your_key                 # or REFCHECKER_ANTHROPIC_API_KEY
export GOOGLE_API_KEY=your_key                    # or REFCHECKER_GOOGLE_API_KEY
export AZURE_OPENAI_API_KEY=your_key              # or REFCHECKER_AZURE_API_KEY
export AZURE_OPENAI_ENDPOINT=your_endpoint        # or REFCHECKER_AZURE_ENDPOINT

# Model configuration
export REFCHECKER_LLM_MODEL=claude-sonnet-4-20250514
export REFCHECKER_LLM_MAX_TOKENS=4000
export REFCHECKER_LLM_TEMPERATURE=0.1
```


## 🗄️ Local Database Setup

### Downloading the Database

Create a local database for offline verification:

```bash
# Download recent computer science papers
python download_semantic_scholar_db.py \
  --field "computer science" \
  --start-year 2020 \
  --end-year 2024 \
  --batch-size 100

# Download papers matching a specific query
python download_semantic_scholar_db.py \
  --query "attention is all you need" \
  --batch-size 50

# Download with API key for higher rate limits
python download_semantic_scholar_db.py \
  --api-key YOUR_API_KEY \
  --field "machine learning" \
  --start-year 2023
```

### Database Options

- **`--output-dir`**: Directory to store database (default: `semantic_scholar_db`)
- **`--batch-size`**: Papers per batch (default: 100)
- **`--api-key`**: Semantic Scholar API key for higher limits
- **`--fields`**: Metadata fields to include
- **`--query`**: Search query for specific papers
- **`--start-year`/`--end-year`**: Year range filter

## 🧪 Testing

RefChecker includes a comprehensive test suite with 124 tests covering unit, integration, and end-to-end scenarios. The tests ensure reliability across all components and provide examples of how to use the system.

### Quick Test Run

```bash
# Run all tests
pytest tests/

# Run specific test categories
pytest tests/unit/              # Unit tests only
pytest tests/integration/       # Integration tests only  
pytest tests/e2e/              # End-to-end tests only

# Run with coverage
pytest --cov=src --cov-report=html tests/

# Run tests in parallel (if pytest-xdist installed)
pytest -n auto tests/
```

### Test Categories

- **Unit Tests** (47 tests): Individual components like text utilities, error handling, and reference extraction
- **Integration Tests** (63 tests): API interactions, LLM providers, and component integration  
- **End-to-End Tests** (14 tests): Complete workflows, performance testing, and edge cases

### Test Structure

```
tests/
├── unit/                   # Unit tests for individual components
├── integration/            # Integration tests for APIs and services
├── e2e/                   # End-to-end workflow tests
├── fixtures/              # Test data and mock objects
└── README.md              # Detailed testing documentation
```

For detailed testing information, test execution options, and guidance on writing new tests, see the **[Testing Documentation](tests/README.md)**.

## 📦 Building the Package

To build RefChecker for distribution:

```bash
# Install build tool if needed
pip install build

# Build wheel and source distribution
python -m build
```

The built packages will be available in the `dist/` directory.

### Version Management

The package version is centrally managed in `src/__version__.py`. To update the version:

1. Edit `src/__version__.py` and change the `__version__` string
2. Rebuild the package with `python -m build`

This ensures the version is consistent across the package metadata, script output, and documentation.

### Publishing to PyPI

To publish the package for testing and distribution:

```bash
# Install twine for uploading
pip install twine

# Option 1: Use API token directly (recommended for CI/automation)
twine upload --repository testpypi dist/* --username __token__ --password pypi-your-api-token-here

# Option 2: Set up ~/.pypirc file for repeated uploads
cat > ~/.pypirc << EOF
[distutils]
index-servers =
    testpypi
    pypi

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-your-testpypi-token

[pypi]
repository = https://upload.pypi.org/legacy/
username = __token__
password = pypi-your-production-token
EOF

# Then upload without entering credentials
twine upload --repository testpypi dist/*

# Test install from Test PyPI
pip install --index-url https://test.pypi.org/simple/ refchecker

# Upload to production PyPI
twine upload dist/*
```

**Setup Requirements**:
1. Create accounts on [Test PyPI](https://test.pypi.org/) and [PyPI](https://pypi.org/)
2. Generate API tokens in your account settings
3. Use `__token__` as username and your API token as password

**Common Issues**:
- **400 Bad Request**: Usually means the version already exists. Bump the version in `pyproject.toml` and rebuild
- **403 Forbidden**: Check your API token and package name permissions
- **Package name taken**: Choose a different name or add a suffix (e.g., `refchecker-yourname`)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
