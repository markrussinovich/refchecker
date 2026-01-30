# 📚 Academic Paper Reference Checker

*Developed by Mark Russinovich with various AI assistants, including Cursor, GitHub Copilot and Claude Code*

A comprehensive tool for validating reference accuracy in academic papers, useful for both authors checking their bibliography and conference reviewers ensuring that paper references are authentic and accurate. This tool processes papers from various local and online sources including ArXiv, PDF files, LaTeX documents, and text files to verify the accuracy of references by comparing cited information against authoritative sources.

## 🎥 Project Deep Dive

Learn about RefChecker's design philosophy and development process in this detailed discussion between Mark Russinovich (RefChecker's author) and Scott Hanselman. Mark shares insights into how he leveraged AI coding assistants including Cursor, GitHub Copilot, and Claude to build this comprehensive academic reference validation tool.

**[📺 Watch: "AI Coding with Mark Russinovich: Building RefChecker"](https://www.youtube.com/watch?v=n929Alz-fjo)**

*This video provides valuable insights into modern AI-assisted development workflows and the technical decisions behind RefChecker's architecture.*

## 📊 Sample Output

```
📄 Processing: Attention Is All You Need
   URL: https://arxiv.org/abs/1706.03762

[1/45] Neural machine translation in linear time
       Nal Kalchbrenner, Lasse Espeholt, Karen Simonyan, Aaron van den Oord, Alex Graves, Koray Kavukcuoglu
       2017

       Verified URL: https://www.semanticscholar.org/paper/5f4ac1ac7ca4b17d3db1b52d9aafd9e8b26c0d7
       ArXiv URL: https://arxiv.org/abs/1610.10099
       DOI URL: https://doi.org/10.48550/arxiv.1610.10099
      ⚠️  Warning: Year mismatch:
               cited:  '2017'
               actual: '2016'

[2/45] Effective approaches to attention-based neural machine translation
       Minh-Thang Luong, Hieu Pham, Christopher D. Manning
       2015

       Verified URL: https://www.semanticscholar.org/paper/93499a7c7f699b6630a86fad964536f9423bb6d0
       ArXiv URL: https://arxiv.org/abs/1508.04025
       DOI URL: https://doi.org/10.18653/v1/d15-1166
      ❌ Error: First author mismatch:
               cited:  'Minh-Thang Luong'
               actual: 'Thang Luong'

[3/45] Deep Residual Learning for Image Recognition
       Kaiming He, Xiangyu Zhang, Shaoqing Ren, Jian Sun
       Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition
       2016
       https://doi.org/10.1109/CVPR.2016.91

       Verified URL: https://www.semanticscholar.org/paper/2c03df8b48bf3fa39054345bafabfeff15bfd11d
       ArXiv URL: https://arxiv.org/abs/1512.03385
       DOI URL: https://doi.org/10.1109/CVPR.2016.90
      ❌ Error: DOI mismatch:
               cited:  '10.1109/CVPR.2016.91'
               actual: '10.1109/CVPR.2016.90'

============================================================
📋 SUMMARY
============================================================
📚 Total references processed: 68
❌ Total errors: 55
⚠️  Total warnings: 16
❓ References that couldn't be verified: 15
```

## 📋 Table of Contents

- [🎥 Project Deep Dive](#-project-deep-dive)
- [📊 Sample Output](#-sample-output)
- [🎯 Features](#-features)
- [🚀 Quick Start](#-quick-start)
- [🐳 Docker (Recommended)](#-docker-recommended)
- [🌐 Web UI](#-web-ui)
- [🤖 LLM-Enhanced Reference Extraction](#-llm-enhanced-reference-extraction)
- [📦 Installation](#-installation)
- [📖 Usage](#-usage)
- [📊 Output and Results](#-output-and-results)
- [⚙️ Configuration](#-configuration)
- [🗄️ Local Database Setup](#-local-database-setup)
- [🧪 Testing](#-testing)
- [📄 License](#-license)

## 🎯 Features

- **📄 Multiple Input Formats**: Process ArXiv papers, local PDFs, LaTeX files, and text documents
- **🔍 Advanced Bibliography Detection**: Uses intelligent pattern matching to identify bibliography sections
- **🤖 LLM-Enhanced Reference Extraction**: Recommended AI-powered bibliography parsing with support for OpenAI, Anthropic, Google, Azure, and local vLLM
- **✅ Comprehensive Error Detection**: Identifies issues with titles, authors, years, venues, URLs, and DOIs
- **🔄 Multi-Tier Verification Sources**: Uses a prioritized check of Semantic Scholar, OpenAlex, and CrossRef with intelligent retry logic
- **🔗 Enhanced URL Discovery**: Automatically discovers and displays additional authoritative URLs (Semantic Scholar, ArXiv, DOI) obtained through verification
- **🧠 Smart Title Matching**: Advanced similarity algorithms handle common academic formatting variations (BERT vs B-ERT, pre-trained vs pretrained)
- **🏢 Venue Normalization**: Recognizes common journal and conference abbreviation patterns
- **📊 Detailed Reporting**: Generates comprehensive error reports with drop-in corrected references

## 🚀 Quick Start

### Easiest: Use Docker

```bash
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=your_key ghcr.io/markrussinovich/refchecker:latest
```

Open **http://localhost:8000** in your browser. See [Docker](#-docker-recommended) for more options.

### Command Line (requires Python installation)

1. **Check a famous paper:**
   ```bash
   python run_refchecker.py --paper 1706.03762
   ```

2. **Check your own PDF:**
   ```bash
   python run_refchecker.py --paper /path/to/your/paper.pdf
   ```

3. **For faster processing with local database** (see [Local Database Setup](#local-database-setup)):
   ```bash
   python run_refchecker.py --paper 1706.03762 --db-path semantic_scholar_db/semantic_scholar.db
   ```

> **⚡ Performance Tip**: Reference verification takes 5-10 seconds per reference without a Semantic Scholar API key due to rate limiting. With an API key, verification speeds up to 1-2 seconds per reference. Set `SEMANTIC_SCHOLAR_API_KEY` environment variable or use `--semantic-scholar-api-key` for faster processing.

## 🐳 Docker (Recommended)

The easiest way to run RefChecker is with Docker. Pre-built images are automatically published to GitHub Container Registry on every release.

### Quick Start

```bash
# Pull and run the latest image (works on Intel/AMD and Apple Silicon)
docker run -p 8000:8000 ghcr.io/markrussinovich/refchecker:latest
```

Open **http://localhost:8000** in your browser.

### With LLM API Keys

To use LLM-powered reference extraction (recommended for best accuracy), pass your API key:

```bash
# Using Anthropic Claude (recommended)
docker run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=your_key_here \
  ghcr.io/markrussinovich/refchecker:latest

# Using OpenAI
docker run -p 8000:8000 \
  -e OPENAI_API_KEY=your_key_here \
  ghcr.io/markrussinovich/refchecker:latest

# Using Google Gemini
docker run -p 8000:8000 \
  -e GOOGLE_API_KEY=your_key_here \
  ghcr.io/markrussinovich/refchecker:latest
```

### Persistent Data

To persist check history and settings between container restarts:

```bash
docker run -p 8000:8000 \
  -v refchecker-data:/app/data \
  -e ANTHROPIC_API_KEY=your_key_here \
  ghcr.io/markrussinovich/refchecker:latest
```

### Using Docker Compose

For easier configuration, clone the repo and use the included `docker-compose.yml`:

```bash
git clone https://github.com/markrussinovich/refchecker.git
cd refchecker

# Copy the example environment file and add your API keys
cp .env.example .env
# Edit .env with your API keys

# Start RefChecker
docker compose up

# Or run in background
docker compose up -d
```

### GPU Support for Local Models

For running local LLMs with vLLM (no API keys needed), use the GPU-enabled image:

```bash
# Pull the GPU image (amd64/NVIDIA only)
docker pull ghcr.io/markrussinovich/refchecker:gpu

# Run with GPU access
docker run --gpus all -p 8000:8000 \
  -v refchecker-data:/app/data \
  -v refchecker-models:/app/models \
  ghcr.io/markrussinovich/refchecker:gpu
```

Or with Docker Compose:

```bash
# Start with GPU profile
docker compose --profile gpu up
```

### Available Image Tags

| Tag | Description | Architectures | Size |
|-----|-------------|---------------|------|
| `latest` | Latest stable release with cloud LLM support | amd64, arm64 | ~800MB |
| `X.Y.Z` | Specific version (e.g., `1.2.50`) | amd64, arm64 | ~800MB |
| `gpu` | GPU-enabled with vLLM/PyTorch for local models | amd64 only | ~12GB |
| `X.Y.Z-gpu` | Specific GPU version | amd64 only | ~12GB |

> **Note**: The `gpu` images are amd64 only because CUDA is not available on ARM. For Apple Silicon Macs, use the standard `latest` tag with cloud LLM APIs.

### Building Locally

```bash
# Build standard image
make docker-build

# Build GPU image  
make docker-build-gpu

# Run locally
make docker-run

# Test the build
make docker-test
```

## 🌐 Web UI

RefChecker includes a modern web interface with real-time progress updates, check history, and export options.

![RefChecker Web UI](assets/webui.png)

### Features

- ✨ Real-time validation with live progress updates
- 📄 Support for ArXiv URLs and file uploads (PDF, LaTeX, text)
- 📊 Live statistics with filtering by status
- 📋 Export references as Markdown, plain text, or BibTeX (with corrected values)
- 📚 Persistent check history
- 🌓 Automatic dark/light mode

### Option 1: Docker (See Above)

The Docker image includes the complete Web UI - just run the container and open http://localhost:8000.

### Option 2: Install from PyPI

```bash
# Install RefChecker with Web UI support
pip install academic-refchecker[llm,webui]

# Start the web server
refchecker-webui
```

Then open **http://localhost:8000** in your browser.

**Options:**
```bash
refchecker-webui --port 8080      # Use a different port
refchecker-webui --host 0.0.0.0   # Allow external connections
```

### Option 3: Run from Cloned Repository (Development)

If you're developing or modifying the Web UI:

**Prerequisites:**
- **Python 3.8+** with dependencies installed
- **Node.js 18+** and npm

```bash
# Clone the repository
git clone https://github.com/markrussinovich/refchecker.git
cd refchecker

# Install Python dependencies
pip install -e ".[llm,webui]"

# Install and run the frontend development server
cd web-ui
npm install    # First time only
npm start      # Starts both backend and frontend
```

Then open **http://localhost:5173** in your browser.

**Alternative: Start Servers Separately**

*Terminal 1 - Backend:*
```bash
python -m uvicorn backend.main:app --reload --port 8000
```

*Terminal 2 - Frontend:*
```bash
cd web-ui
npm run dev
```

For complete Web UI documentation, see **[web-ui/README.md](web-ui/README.md)**.

## 🤖 LLM-Enhanced Reference Extraction

RefChecker supports AI-powered bibliography parsing using Large Language Models (LLMs) for improved accuracy with complex citation formats. While models as small as Llama 3.1-8B are fairly reliable at reference extraction, they can struggle with non-standard bibliographies. GPT-4o frequently hallucinates DOIs while Sonnet 4 has shown the best performance on large, complex bibliographies.

### Supported LLM Providers

- **OpenAI** e.g., GPT-4.1, o3
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
   
   python run_refchecker.py --paper 1706.03762
   ```

2. **Using Command Line Arguments**:
   ```bash
   # Enable LLM with specific provider and model
   python run_refchecker.py --paper 1706.03762 \
     --llm-provider anthropic \
     --llm-model claude-sonnet-4-20250514 \
   ```
   API keys are obtained from environment variables, or if not found, the tool will prompt you interactively to enter them securely.

### LLM Examples

#### OpenAI GPT-4

With `OPENAI_API_KEY` environment variable: 

```bash
python run_refchecker.py --paper /path/to/paper.pdf \
  --llm-provider openai \
  --llm-model gpt-4o \
```

#### Anthropic Claude

With `ANTHROPIC_API_KEY` environment variable: 

```bash
python run_refchecker.py --paper https://arxiv.org/abs/1706.03762 \
  --llm-provider anthropic \
  --llm-model claude-sonnet-4-20250514 \
```

#### Google Gemini

With `GOOGLE_API_KEY` environment variable:  

```bash
python run_refchecker.py --paper paper.tex \
  --llm-provider google \
  --llm-model gemini-2.5-flash
```

#### Azure OpenAI

With `AZURE_OPENAI_API_KEY` environment variable:

```bash
python run_refchecker.py --paper paper.txt \
  --llm-provider azure \
  --llm-model gpt-4 \
  --llm-endpoint https://your-resource.openai.azure.com/
```

#### vLLM (Local Models)

For running models locally:

```bash
# automatic Huggingface model download with VLLM server launch 
python run_refchecker.py --paper paper.pdf \
  --llm-provider vllm \
  --llm-model meta-llama/Llama-3.1-8B-Instruct 
```

You can debug vllm server issues by running refchecker with the `--debug` flag. 

## 📦 Installation

### Option 1: Docker (Recommended)

No installation required - just run the Docker image:

```bash
docker run -p 8000:8000 ghcr.io/markrussinovich/refchecker:latest
```

See [Docker](#-docker-recommended) section for full details on configuration, persistent data, and GPU support.

### Option 2: Install from PyPI

**Prerequisites:**
- **Python 3.8+** (3.10+ recommended)

For the latest stable release with all features:

```bash
pip install academic-refchecker[llm,webui]
```

This installs RefChecker with:
- **llm**: Support for OpenAI, Anthropic, Google, Azure, and vLLM providers
- **webui**: Web interface dependencies (FastAPI, uvicorn, etc.)

For a minimal installation (CLI only, no LLM or Web UI):
```bash
pip install academic-refchecker
```

Other optional extras:
- **dev**: Development tools (pytest, black, flake8, mypy)
- **optional**: Enhanced features (lxml, selenium, pikepdf, nltk, scikit-learn)
- **vllm**: Local model inference with vLLM

### Option 3: Install from Source

**Prerequisites:**
- **Python 3.8+** (3.10+ recommended)
- **Node.js 18+** and npm (only required for Web UI development)

#### 1. Clone the Repository

```bash
git clone https://github.com/markrussinovich/refchecker.git
cd refchecker
```

#### 2. Create and Activate Virtual Environment (Recommended)

```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate
```

#### 3. Install Dependencies

```bash
# Install all dependencies including LLM and Web UI support
pip install -e ".[llm,webui]"

# Or install from requirements.txt
pip install -r requirements.txt
```

#### 4. (Optional) Install Additional Dependencies

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

### Web UI Installation

The Web UI requires Node.js 18+ in addition to the Python dependencies:

```bash
cd web-ui
npm install
```

## 📖 Usage

Check papers in various formats and online locations:

#### ArXiv Papers

```bash
# Check a specific ArXiv paper by ID
python run_refchecker.py --paper 1706.03762

# Check by ArXiv URL
python run_refchecker.py --paper https://arxiv.org/abs/1706.03762

# Check by ArXiv PDF URL
python run_refchecker.py --paper https://arxiv.org/pdf/1706.03762.pdf
```

#### Local PDF Files

```bash
# Check a local PDF file
python run_refchecker.py --paper /path/to/your/paper.pdf

# Check with offline database for faster processing
python run_refchecker.py --paper /path/to/your/paper.pdf --db-path semantic_scholar_db/semantic_scholar.db
```

#### LaTeX Files

```bash
# Check a LaTeX document
python run_refchecker.py --paper /path/to/your/paper.tex

# Check with debug mode for detailed processing info
python run_refchecker.py --paper /path/to/your/paper.tex --debug
```

#### Text Files

```bash
# Check a plain text file containing paper content
python run_refchecker.py --paper /path/to/your/paper.txt

# Combine with local database for offline verification
python run_refchecker.py --paper /path/to/your/paper.txt --db-path semantic_scholar_db/semantic_scholar.db
```


## 📊 Output and Results

### Generated Files

By default, no files are generated. To save detailed results, use the `--output-file` option:

```bash
# Save to default filename (reference_errors.txt)
python run_refchecker.py --paper 1706.03762 --output-file

# Save to custom filename
python run_refchecker.py --paper 1706.03762 --output-file my_errors.txt
```

The output file contains a detailed report of references with errors and warnings, including corrected references.

### Enhanced URL Display

RefChecker automatically discovers and displays authoritative URLs for verified references:

- **Verified URL**: The primary authoritative source (typically Semantic Scholar)
- **ArXiv URL**: Direct link to the ArXiv preprint when available
- **DOI URL**: Digital Object Identifier link when available
- **Additional URLs**: Other relevant sources discovered during verification

This enhanced URL display helps users access multiple authoritative sources for each reference and provides comprehensive citation information.

### Error Types

- **❌ Errors**: Critical issues that need correction
  - `author`: Author name mismatches
    ```
    [16/19] Bag of tricks: Benchmarking of jailbreak attacks on llms
           T. Xie, X. Qi, Y. Zeng, Y. Huang, U. M. Sehwag, K. Huang, L. He, B. Wei, D. Li, Y. Sheng et al

           Verified URL: https://www.semanticscholar.org/paper/a1b2c3d4e5f6789012345678901234567890abcd
           ArXiv URL: https://arxiv.org/abs/2312.02119
           DOI URL: https://doi.org/10.48550/arxiv.2312.02119
          ❌ Error: First author mismatch:
                   cited:  'T. Xie'
                   actual: 'Zhao Xu'
    ```
  - `title`: Title discrepancies
    ```
    [8/19] BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding
           J. Devlin, M.-W. Chang, K. Lee, K. Toutanova

           Verified URL: https://www.semanticscholar.org/paper/df2b0e26d0599ce3e70df8a9da02e51594e0e992
           ArXiv URL: https://arxiv.org/abs/1810.04805
           DOI URL: https://doi.org/10.18653/v1/n19-1423
          ❌ Error: Title mismatch:
                   cited:  'BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding'
                   actual: 'BERT: Pre-training of Deep Bidirectional Transformers for Language Comprehension'
    ```
  - `arxiv_id`: Incorrect URLs or arXiv IDs
    ```
    [5/19] Jbshield: Neural representation-level defense against adversarial prompts in large language models
           W. Zhang, M. Li, H. Wang
           https://arxiv.org/abs/2503.01234

           Verified URL: https://www.semanticscholar.org/paper/e1f2a3b4c5d6e7f8901234567890123456789012
           DOI URL: https://doi.org/10.48550/arxiv.2401.12345
          ❌ Error: Incorrect ArXiv ID: ArXiv ID 2503.01234 points to 'Self-Adaptive Gamma Context-Aware SSM-based Model for Metal Defect Detection'
    ```
  - `doi`: DOI mismatches
    ```
    [12/19] Attention Is All You Need
           Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Lukasz Kaiser, Illia Polosukhin
           Neural Information Processing Systems
           2017
           https://doi.org/10.5555/3295222.3295349

           Verified URL: https://www.semanticscholar.org/paper/204e3073870fae3d05bcbc2f6a8e263d9b72e776
           ArXiv URL: https://arxiv.org/abs/1706.03762
           DOI URL: https://doi.org/10.48550/arXiv.1706.03762
          ❌ Error: DOI mismatch:
                   cited:  '10.5555/3295222.3295349'
                   actual: '10.48550/arXiv.1706.03762'
    ```

- **⚠️ Warnings**: Minor issues that may need attention
  - `year`: Publication year differences (common due to multiple paper versions)
    ```
    [14/19] Smoothllm: Defending large language models against jailbreaking attacks
           A. Robey, E. Wong, H. Hassani, G. J. Pappas
           2024

           Verified URL: https://www.semanticscholar.org/paper/f1a2b3c4d5e6f7890123456789012345678901ab
           ArXiv URL: https://arxiv.org/abs/2310.03684
           DOI URL: https://doi.org/10.48550/arxiv.2310.03684
          ⚠️  Warning: Year mismatch:
                   cited:  '2024'
                   actual: '2023'
    ```
  - `venue`: Venue format variations
    ```
    [2/19] Gradient cuff: Detecting jailbreak attacks on large language models by exploring refusal loss landscapes
           X. Hu, P.-Y. Chen, T.-Y. Ho
           arXiv, 2024

           Verified URL: https://www.semanticscholar.org/paper/c1d2e3f4a5b6c7d8e9f0123456789012345678ab
           ArXiv URL: https://arxiv.org/abs/2403.02151
           DOI URL: https://doi.org/10.48550/arxiv.2403.02151
          ⚠️  Warning: Venue mismatch:
                   cited:  'arXiv, 2024'
                   actual: 'Neural Information Processing Systems'
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
--output-file [PATH]             # Path to output file for reference discrepancies (default: reference_errors.txt if flag provided, no file if not provided)

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

RefChecker includes a comprehensive test suite with **490+ tests** covering unit, integration, and end-to-end scenarios. The tests ensure reliability across all components and provide examples of how to use the system.

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

- **Unit Tests** Individual components like text utilities, error handling, and reference extraction
- **Integration Tests** API interactions, LLM providers, and component integration  
- **End-to-End Tests** Complete workflows, performance testing, and edge cases

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


## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
