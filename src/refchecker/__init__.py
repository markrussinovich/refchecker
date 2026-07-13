"""
RefChecker - Academic Paper Reference Validation Tool

A comprehensive tool for validating reference accuracy in academic papers.
"""

from .__version__ import __version__  # single source of truth (see __version__.py)
__author__ = "RefChecker Team"
__email__ = "markrussinovich@hotmail.com"

from .core.refchecker import ArxivReferenceChecker

__all__ = ["ArxivReferenceChecker"]