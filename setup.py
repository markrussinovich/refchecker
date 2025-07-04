#!/usr/bin/env python3
"""
Setup script for RefChecker
"""

from setuptools import setup, find_packages
import os

# Read the README file
def read_readme():
    with open(os.path.join(os.path.dirname(__file__), 'README.md'), 'r', encoding='utf-8') as f:
        return f.read()

# Read requirements
def read_requirements():
    with open(os.path.join(os.path.dirname(__file__), 'requirements.txt'), 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name="refchecker",
    version="1.0.0",
    author="Mark Russinovich",
    author_email="markrussinovich@hotmail.com", 
    description="A comprehensive tool for validating reference accuracy in academic papers",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/markrussinovich/refchecker",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Information Analysis",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.7",
    install_requires=read_requirements(),
    extras_require={
        "dev": [
            "pytest>=6.0.0",
            "pytest-cov>=2.0.0",
            "black>=21.0.0",
            "isort>=5.0.0",
            "flake8>=3.9.0",
            "mypy>=0.910",
        ],
        "docs": [
            "sphinx>=4.0.0",
            "sphinx-rtd-theme>=0.5.0",
        ],
        "optional": [
            "lxml>=4.6.0",
            "selenium>=4.0.0", 
            "pikepdf>=5.0.0",
            "nltk>=3.6.0",
            "scikit-learn>=1.0.0",
            "joblib>=1.1.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "refchecker=core.refchecker:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)