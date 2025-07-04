# RefChecker Project Structure

This document describes the reorganized project structure for better maintainability and organization.

## Directory Layout

```
refchecker/
├── README.md                    # Main documentation
├── requirements.txt             # Python dependencies
├── setup.py                     # Package installation script
├── Makefile                     # Build and development commands
├── .gitignore                   # Git ignore rules
├── refchecker.py               # Main CLI entry point
│
├── src/                        # Source code
│   ├── __init__.py
│   ├── core/                   # Core functionality
│   │   ├── __init__.py
│   │   └── refchecker.py       # Main ArxivReferenceChecker class
│   ├── checkers/               # Reference verification modules
│   │   ├── __init__.py
│   │   ├── semantic_scholar.py        # Semantic Scholar API client
│   │   ├── google_scholar.py          # Google Scholar client
│   │   ├── local_semantic_scholar.py  # Local database client
│   │   └── hybrid_reference_checker.py # Multi-source verification
│   ├── utils/                  # Utility functions
│   │   ├── __init__.py
│   │   ├── text_utils.py       # Text processing utilities
│   │   └── author_utils.py     # Author comparison functions
│   └── database/               # Database management
│       ├── __init__.py
│       ├── download_semantic_scholar_db.py # DB download script
│       └── semantic_dataset_download.py   # Dataset utilities
│
├── tests/                      # Test and validation scripts
│   ├── __init__.py
│   ├── validate_refchecker.py      # Main validation tests
│   ├── validate_papers.py          # Paper-specific tests
│   ├── validate_attention_paper.py # Attention paper test
│   └── validate_local_db.py        # Database validation
│
├── scripts/                    # Utility scripts
│   ├── download_db.py          # Database download wrapper
│   └── run_tests.py            # Test runner
│
├── config/                     # Configuration files
│   ├── logging.conf            # Logging configuration
│   └── settings.py             # Default settings
│
├── logs/                       # Log files (generated)
├── debug/                      # Debug output (generated)
├── output/                     # Processing output (generated)
├── validation_output/          # Validation results (generated)
└── semantic_scholar_db/        # Local database (generated)
```

## Key Improvements

### 1. **Modular Organization**
- **Core**: Main application logic in `src/core/`
- **Checkers**: Reference verification modules in `src/checkers/`
- **Utils**: Reusable utility functions in `src/utils/`
- **Database**: Database management in `src/database/`

### 2. **Proper Package Structure**
- Each directory has `__init__.py` files for proper Python packaging
- Clear imports and dependencies
- Easy to install with `pip install -e .`

### 3. **Separation of Concerns**
- **Tests**: All validation and testing code in `tests/`
- **Scripts**: Convenience scripts in `scripts/`
- **Config**: Configuration and settings in `config/`

### 4. **Development Tools**
- **Makefile**: Common development tasks (`make test`, `make clean`, etc.)
- **setup.py**: Proper Python package configuration
- **Enhanced .gitignore**: Comprehensive ignore rules

### 5. **Entry Points**
- **refchecker.py**: Main CLI entry point (backward compatible)
- **scripts/**: Additional utility scripts
- **Console script**: Can be installed as `refchecker` command

## Usage

### Installation
```bash
# Install in development mode
pip install -e .

# Or install with optional dependencies
pip install -e ".[dev,optional]"
```

### Running
```bash
# Using the main script
python refchecker.py --paper 1706.03762

# Using make targets
make run
make test
make clean
```

### Development
```bash
# Format code
make format

# Run linting
make lint

# Type checking
make type-check

# Download database
make download-db
```

## Migration Notes

The reorganization maintains backward compatibility:
- Main `refchecker.py` entry point works as before
- All validation scripts work with updated imports
- Generated output directories remain the same
- Configuration and behavior unchanged

## Benefits

1. **Maintainability**: Clear separation of concerns and logical organization
2. **Testability**: Isolated test modules and proper package structure
3. **Extensibility**: Easy to add new checker modules or utilities
4. **Documentation**: Clear structure makes the codebase easier to understand
5. **Distribution**: Proper package structure for PyPI distribution
6. **Development**: Improved development workflow with Makefile and scripts