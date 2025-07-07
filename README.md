# Academic Paper Reference Checker

*Vibe coded by Mark Russinovich and Github Copilot Agent with Sonnet 4*

A comprehensive tool for validating reference accuracy in academic papers. This tool can check individual papers from various sources including ArXiv, local PDF files, LaTeX documents, and text files to verify the accuracy of references by comparing cited information against authoritative sources.

## 🎯 Features

- **📄 Multiple Input Formats**: Process ArXiv papers, local PDFs, LaTeX files, and text documents
- **🔍 Advanced Bibliography Detection**: Uses intelligent pattern matching to identify bibliography sections
- **🤖 LLM-Enhanced Reference Extraction**: Optional AI-powered bibliography parsing with support for OpenAI, Anthropic, Google, and Azure
- **🧠 Smart Reference Parsing**: Handles various academic citation formats and styles (including CoRR format)
- **✅ Comprehensive Error Detection**: Identifies issues with authors, years, URLs, and DOIs
- **🔄 Multiple Verification Sources**: Supports arXiv API, Semantic Scholar API, Google Scholar, and local databases
- **📊 Detailed Reporting**: Generates comprehensive error reports with statistics and icons
- **⏸️ Resumable Processing**: Can continue from where it left off if interrupted
- **🚦 Rate Limiting**: Respects API constraints with intelligent backoff strategies
- **🎛️ Highly Configurable**: Support for offline verification and various input sources
- **⚡ Performance Optimized**: Batch processing, caching, and concurrent API calls for fast verification

## Quick Start

### Check Your First Paper

1. **Check a famous paper:**
   ```bash
   python refchecker.py --paper 1706.03762
   ```

2. **Check your own PDF:**
   ```bash
   python refchecker.py --paper /path/to/your/paper.pdf
   ```

3. **For faster processing, set up local database:**
   ```bash
   # Download database (optional but recommended)
   python download_semantic_scholar_db.py --field "computer science" --start-year 2020

   # Use offline verification
   python refchecker.py --paper 1706.03762 --db-path semantic_scholar_db/semantic_scholar.db
   ```

## 🤖 LLM-Enhanced Reference Extraction

RefChecker supports AI-powered bibliography parsing using Large Language Models (LLMs) for improved accuracy with complex citation formats.

### Supported LLM Providers

- **OpenAI** (GPT-4, GPT-3.5)
- **Anthropic** (Claude 3.5, Claude 3)
- **Google** (Gemini)
- **Azure OpenAI**

### Quick LLM Setup (Recommended)

1. **Using Environment Variables**:
   ```bash
   # Enable LLM with Anthropic Claude
   export REFCHECKER_USE_LLM=true
   export REFCHECKER_LLM_PROVIDER=anthropic
   export REFCHECKER_ANTHROPIC_API_KEY=your_api_key_here
   
   python refchecker.py --paper 1706.03762
   ```

2. **Using Command Line Arguments**:
   ```bash
   # Enable LLM with specific provider and model
   python refchecker.py --paper 1706.03762 \
     --llm-provider anthropic \
     --llm-model claude-3-haiku-20240307 \
     --llm-key your_api_key_here
   ```

3. **For Maximum Speed (When Needed)**:
   ```bash
   # Disable LLM for fastest processing
   python refchecker.py --paper 1706.03762 \
     --disable-llm \
     --skip-google-scholar-single
   ```

### LLM Configuration Options

#### Environment Variables
```bash
# Enable/disable LLM
export REFCHECKER_USE_LLM=true

# Provider selection
export REFCHECKER_LLM_PROVIDER=anthropic        # openai, anthropic, google, azure

# Provider-specific API keys
export REFCHECKER_OPENAI_API_KEY=your_key
export REFCHECKER_ANTHROPIC_API_KEY=your_key
export REFCHECKER_GOOGLE_API_KEY=your_key
export REFCHECKER_AZURE_API_KEY=your_key
export REFCHECKER_AZURE_ENDPOINT=your_endpoint

# Model configuration
export REFCHECKER_LLM_MODEL=claude-3-haiku-20240307
export REFCHECKER_LLM_MAX_TOKENS=4000
export REFCHECKER_LLM_TEMPERATURE=0.1
export REFCHECKER_LLM_FALLBACK_ON_ERROR=true
```

#### Command Line Arguments
```bash
# LLM provider and configuration
--llm-provider {openai,anthropic,google,azure}  # Enable LLM with specified provider
--llm-model MODEL_NAME                          # Override default model
--llm-key API_KEY                               # API key (optional if env var set)
--llm-endpoint ENDPOINT_URL                     # Override default endpoint

# Performance options
--disable-llm                                   # Disable LLM for faster processing
--skip-google-scholar-single                    # Skip Google Scholar for single papers
```

### LLM Examples

#### OpenAI GPT-4
```bash
python refchecker.py --paper /path/to/paper.pdf \
  --llm-provider openai \
  --llm-model gpt-4 \
  --llm-key sk-your-openai-key
```

#### Anthropic Claude
```bash
python refchecker.py --paper https://arxiv.org/abs/1706.03762 \
  --llm-provider anthropic \
  --llm-model claude-3-sonnet-20240229 \
  --llm-key your-anthropic-key
```

#### Google Gemini
```bash
python refchecker.py --paper paper.tex \
  --llm-provider google \
  --llm-model gemini-1.5-flash \
  --llm-key your-google-key
```

#### Azure OpenAI
```bash
python refchecker.py --paper paper.txt \
  --llm-provider azure \
  --llm-model gpt-4 \
  --llm-key your-azure-key \
  --llm-endpoint https://your-resource.openai.azure.com/
```

## 🚀 Installation

### 1. Clone the Repository

```bash
git clone https://github.com/markrussinovich/refchecker.git
cd refchecker
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. (Optional) Install Additional Dependencies

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

### Individual Paper Checking (Recommended)

The primary use case is checking individual papers from various sources:

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

### Verification Options

```bash
# Use local database for fastest offline verification
python refchecker.py --paper 1706.03762 --db-path semantic_scholar_db/semantic_scholar.db

# Use Semantic Scholar API key for higher rate limits
python refchecker.py --paper 1706.03762 --semantic-scholar-api-key YOUR_API_KEY

# Enable LLM for best accuracy (recommended)
python refchecker.py --paper 1706.03762 --llm-provider anthropic --llm-key YOUR_API_KEY

# Run in debug mode with verbose logging
python refchecker.py --paper 1706.03762 --debug

# Optimize for speed when accuracy can be compromised
python refchecker.py --paper 1706.03762 --disable-llm --skip-google-scholar-single
```

## 🗄️ Database and API Priority

The system uses a sophisticated multi-tier approach for reference verification:

### 1. **Local Database (Highest Priority)**
- **When**: `--db-path` is specified
- **Advantages**: Fastest, no rate limits, works offline
- **Setup**: Use `download_semantic_scholar_db.py` to create local database
- **Performance**: ~1000 references/second

### 2. **Hybrid Mode (Default)**
- **Primary**: Semantic Scholar API
- **Fallback**: Google Scholar API
- **Advantages**: Good coverage, handles rate limits gracefully
- **Performance**: ~10-50 references/second (depending on rate limits)

### 3. **Semantic Scholar Only**
- **When**: `--semantic-scholar-api-key` provided, no `--db-path`
- **Advantages**: Most accurate, higher rate limits with API key
- **Performance**: ~20-100 references/second

### 4. **ArXiv API Only**
- **When**: Only arXiv references are being verified
- **Advantages**: Direct access to arXiv metadata
- **Performance**: ~5-10 references/second

## 📊 Output and Results

### Generated Files

- **`reference_errors.txt`**: Detailed error report with full context

### Error Types

- **❌ Errors**: Critical issues that need correction
  - `author`: Author name mismatches
  - `title`: Title discrepancies
  - `url`: Incorrect URLs or arXiv IDs
  - `doi`: DOI mismatches

- **⚠️ Warnings**: Minor issues that may need attention
  - `year`: Publication year differences
  - `unverified`: References that couldn't be verified

### Sample Output

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

📊 Paper summary: 1 errors, 1 warnings found

============================================================
📋 FINAL SUMMARY
============================================================
📄 Total papers processed: 1
📚 Total references processed: 45
❌ Papers with errors: 1
⚠️  Papers with warnings: 1
❌ Total errors found: 1
⚠️  Total warnings found: 1
❓ References that couldn't be verified: 2

💾 Detailed results saved to: reference_errors.txt
```

## Local Database Setup

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

## 🧪 Testing and Validation

### Run Validation Tests

```bash
# Test with local database
python validate_refchecker.py --db-path semantic_scholar_db/semantic_scholar.db

# Test without database (online mode)
python validate_refchecker.py

# Test specific paper
python validate_attention_paper.py --db-path semantic_scholar_db/semantic_scholar.db
```

### Validation Scripts

- **`validate_refchecker.py`**: Comprehensive validation suite
- **`validate_papers.py`**: Paper-specific validation
- **`validate_local_db.py`**: Database integrity checks
- **`validate_attention_paper.py`**: Specific paper validation

## ⚙️ Configuration

### Environment Variables

```bash
# Semantic Scholar API key
export SEMANTIC_SCHOLAR_API_KEY="your_api_key_here"

# LLM Configuration
export REFCHECKER_USE_LLM=true
export REFCHECKER_LLM_PROVIDER=anthropic
export REFCHECKER_ANTHROPIC_API_KEY="your_anthropic_key"
export REFCHECKER_OPENAI_API_KEY="your_openai_key"
export REFCHECKER_GOOGLE_API_KEY="your_google_key"
export REFCHECKER_AZURE_API_KEY="your_azure_key"
export REFCHECKER_AZURE_ENDPOINT="https://your-resource.openai.azure.com/"

# Advanced LLM Configuration
export REFCHECKER_LLM_MODEL="claude-3-haiku-20240307"
export REFCHECKER_LLM_MAX_TOKENS=4000
export REFCHECKER_LLM_TEMPERATURE=0.1
export REFCHECKER_LLM_FALLBACK_ON_ERROR=true

# Google Scholar proxy settings (if needed)
export GOOGLE_SCHOLAR_PROXY="http://proxy:port"

# Performance settings
export REFCHECKER_DEBUG=false
export REFCHECKER_OUTPUT_DIR="output"
```

### Command Line Arguments

```bash
# Basic options
--paper PAPER                    # Paper to check (ArXiv ID, URL, or file path)
--max-papers N                   # Maximum papers to process (default: 50)
--days N                         # Days to look back (default: 365) 
--category CATEGORY              # ArXiv category filter
--debug                          # Enable debug mode
--semantic-scholar-api-key KEY   # Semantic Scholar API key
--db-path PATH                   # Local database path

# LLM options
--llm-provider {openai,anthropic,google,azure}  # Enable LLM with provider
--llm-model MODEL                # Override default model
--llm-key KEY                    # API key for LLM provider
--llm-endpoint URL               # Override endpoint (for Azure)
--disable-llm                    # Disable LLM for faster processing

# Performance options
--skip-google-scholar-single     # Skip Google Scholar for single papers
```

### Rate Limiting

The system automatically handles rate limiting:
- **ArXiv API**: 3-second delays between requests
- **Semantic Scholar**: Exponential backoff with 1-5 second delays
- **Google Scholar**: Random delays to avoid detection
- **LLM APIs**: 30-second timeout with automatic retry on failure

## ⚡ Performance Considerations

### Speed Optimization

For fastest processing, use these options:
```bash
# Maximum speed configuration
python refchecker.py --paper YOUR_PAPER \
  --disable-llm \
  --skip-google-scholar-single \
  --db-path semantic_scholar_db/semantic_scholar.db
```

### Processing Time Estimates

| Configuration | Single Paper | 10 Papers | Notes |
|---------------|--------------|-----------|-------|
| **Optimized** | ~5-15 seconds | ~1-5 minutes | Local DB + no LLM + no Google Scholar |
| **Standard** | ~15-30 seconds | ~5-15 minutes | Online APIs + no LLM |
| **LLM Enabled** | ~30-60 seconds | ~15-30 minutes | With AI-enhanced parsing |
| **Full Featured** | ~60-120 seconds | ~30-60 minutes | LLM + Google Scholar fallback |

### Performance Tips

1. **Use local database** for offline processing and maximum speed
2. **Enable LLM** for best accuracy with diverse citation formats (recommended)
3. **Disable LLM** (`--disable-llm`) only when speed is critical and accuracy can be compromised
4. **Skip Google Scholar** (`--skip-google-scholar-single`) for single papers
5. **Use API keys** to get higher rate limits
6. **Process in batches** rather than one-by-one for multiple papers

### Memory Usage

- **Without LLM**: ~50-100 MB per paper
- **With LLM**: ~200-500 MB per paper (depending on model)
- **Local database**: ~1-10 GB disk space (depending on scope)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
