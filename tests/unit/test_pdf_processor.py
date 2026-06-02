#!/usr/bin/env python3
"""Unit tests for PDF processing helpers."""

import unittest

from refchecker.services.pdf_processor import PDFProcessor


class TestPDFProcessor(unittest.TestCase):
    def setUp(self):
        self.processor = PDFProcessor()

    def test_extract_title_skips_usenix_cover_page_boilerplate(self):
        first_page_text = """
This paper is included in the Proceedings of the
30th USENIX Security Symposium.
August 11-13, 2021
978-1-9391 33-24-3
Open access to the Proceedings of the
30th USENIX Security Symposium
is sponsored by USENIX.
Android SmartTVs Vulnerability Discovery via
Log-Guided Fuzzing
Yousra Aafer, University of Waterloo; Wei You, Renmin University of China;
Yi Sun, Yu Shi, and Xiangyu Zhang, Purdue University; Heng Yin, UC Riverside
https://www.usenix.org/conference/usenixsecurity21/presentation/aafer
"""

        title = self.processor._extract_title_from_text(first_page_text)

        self.assertEqual(
            title,
            "Android SmartTVs Vulnerability Discovery via Log-Guided Fuzzing",
        )


if __name__ == '__main__':
    unittest.main()