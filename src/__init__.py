"""
RefChecker - Academic Paper Reference Validation Tool

A comprehensive tool for validating reference accuracy in academic papers.
"""

__version__ = "1.2.1"
__author__ = "RefChecker Team"
__email__ = "markrussinovich@hotmail.com"

from .core.refchecker import ArxivReferenceChecker

__all__ = ["ArxivReferenceChecker"]