#!/usr/bin/env python3
"""
Regression tests for bare (unquoted) BibTeX field values.

BibTeX permits numeric and macro values without braces or quotes, e.g.
``year = 2017`` or ``month = jan``. The parser used to accept only braced and
quoted values, so a bare year was silently dropped: the reference year became
``None`` and year mismatches were never reported.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.bibtex_parser import (
    parse_bibtex_entries,
    parse_bibtex_references,
)


DENSENET = (
    '@article{x, title={Densely Connected Convolutional Networks}, '
    'author={Huang, Gao}, year=%s}'
)


class TestBareBibtexValues(unittest.TestCase):
    """Bare numeric/macro values must be parsed like braced or quoted ones."""

    def test_bare_numeric_year_is_parsed(self):
        """year = 2017 (unbraced) must yield 2017, not None."""
        ref = parse_bibtex_references(DENSENET % '2017')[0]
        self.assertEqual(ref['year'], 2017)

    def test_bare_incorrect_year_is_kept_for_verification(self):
        """A wrong bare year must survive parsing so it can be flagged later."""
        ref = parse_bibtex_references(DENSENET % '2012')[0]
        self.assertEqual(ref['year'], 2012)

    def test_value_styles_are_equivalent(self):
        """Braced, quoted and bare years produce the same reference."""
        braced = parse_bibtex_references(DENSENET % '{2017}')[0]
        quoted = parse_bibtex_references(DENSENET % '"2017"')[0]
        bare = parse_bibtex_references(DENSENET % '2017')[0]
        for field in ('title', 'authors', 'year'):
            self.assertEqual(braced[field], quoted[field])
            self.assertEqual(braced[field], bare[field])

    def test_bare_value_does_not_swallow_following_fields(self):
        """Parsing must resume at the field separator after a bare value."""
        entry = (
            '@article{y, title={Focal Loss for Dense Object Detection}, '
            'author={Lin, Tsung-Yi}, year=2020, volume=12, number=3, '
            'pages=2980--2988}'
        )
        fields = parse_bibtex_entries(entry)[0]['fields']
        self.assertEqual(fields['year'], '2020')
        self.assertEqual(fields['volume'], '12')
        self.assertEqual(fields['number'], '3')
        self.assertEqual(fields['pages'], '2980--2988')

    def test_mixed_braced_and_bare_values(self):
        """Entries that mix braced titles with bare numbers keep both."""
        entry = (
            '@inproceedings{z, title={Attention Is All You Need}, '
            'booktitle={NeurIPS}, year=2017, pages=5998--6008}'
        )
        ref = parse_bibtex_references(entry)[0]
        self.assertEqual(ref['title'], 'Attention Is All You Need')
        self.assertEqual(ref['year'], 2017)
        self.assertEqual(ref['pages'], '5998--6008')

    def test_macro_value_is_parsed(self):
        """Bare macros such as month = jan are kept as values."""
        fields = parse_bibtex_entries(
            '@article{m, title={T}, month=jan, year=2019}'
        )[0]['fields']
        self.assertEqual(fields['month'], 'jan')
        self.assertEqual(fields['year'], '2019')

    def test_bare_value_survives_trailing_whitespace(self):
        """Whitespace around a bare value is stripped, including newlines."""
        entry = '@article{w,\n  title={T},\n  year = 2017 ,\n  volume = 4\n}'
        fields = parse_bibtex_entries(entry)[0]['fields']
        self.assertEqual(fields['year'], '2017')
        self.assertEqual(fields['volume'], '4')

    def test_leading_zeros_and_short_values(self):
        """Numeric-looking bare values are not coerced or truncated."""
        fields = parse_bibtex_entries(
            '@article{o, title={T}, year=0999, number=07}'
        )[0]['fields']
        self.assertEqual(fields['year'], '0999')
        self.assertEqual(fields['number'], '07')

    def test_missing_year_still_none(self):
        """Entries without a year keep year=None (no invented default)."""
        ref = parse_bibtex_references(
            '@article{n, title={T}, author={Doe, Jane}}'
        )[0]
        self.assertIsNone(ref['year'])

    def test_nested_braces_unchanged(self):
        """Nested braces in braced values still parse correctly."""
        ref = parse_bibtex_references(
            '@article{b, title={KernelBench: Can {LLM}s Write Efficient '
            '{GPU} Kernels?}, author={Ouyang, Anne}, year={2025}}'
        )[0]
        self.assertIn('KernelBench', ref['title'])
        self.assertEqual(ref['year'], 2025)


if __name__ == '__main__':
    unittest.main()
