"""Structured report building for reference checker results.

Handles text, JSON, JSONL, CSV export and hallucination assessment.
Extracted from ArxivReferenceChecker to keep report logic isolated.
"""

from __future__ import annotations

import csv
import datetime
import json
import logging
from typing import Any, Dict, IO, List, Optional

from refchecker.core.hallucination_policy import should_check_hallucination, assess_hallucination, check_author_hallucination

logger = logging.getLogger(__name__)


class ReportBuilder:
    """Build and write structured reports from reference-checker error entries."""

    def __init__(
        self,
        report_file: Optional[str] = None,
        report_format: str = 'json',
        llm_verifier: Optional[Any] = None,
        web_searcher: Optional[Any] = None,
        # Deprecated parameters kept for backward compatibility
        scan_mode: str = 'standard',
        only_flagged: bool = False,
    ):
        self.report_file = report_file
        self.report_format = report_format
        self.llm_verifier = llm_verifier
        self.web_searcher = web_searcher

    # ------------------------------------------------------------------
    # Payload construction
    # ------------------------------------------------------------------

    def build_structured_report_records(self, errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert collected error entries into report records.

        Hallucination assessment:
        1. Deterministic author-overlap check (no LLM needed): flags refs
           where < 60% of cited authors match the actual authors.
        2. LLM-based assessment for unverified references that pass the
           pre-filter (requires configured LLM).
        """
        records = []
        for error_entry in errors:
            record = dict(error_entry)

            # 1. Deterministic: author-overlap hallucination check (no LLM)
            author_result = check_author_hallucination(record)
            if author_result:
                record['hallucination_assessment'] = author_result
            else:
                # 2. LLM-based: only for unverified references
                error_type = (record.get('error_type') or '').lower()
                is_unverified = (error_type == 'unverified'
                                 or (error_type == 'multiple'
                                     and 'unverified' in (record.get('error_details') or '').lower()))

                if (self.llm_verifier and self.llm_verifier.available
                        and is_unverified
                        and should_check_hallucination(record)):
                    assessment = assess_hallucination(
                        record,
                        llm_client=self.llm_verifier,
                        web_searcher=self.web_searcher,
                    )
                    record['hallucination_assessment'] = assessment

            records.append(record)

        return records

    def build_paper_rollups(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build per-paper triage summaries from structured records."""
        rollups: Dict[str, Dict[str, Any]] = {}
        level_rank = {'none': 0, 'low': 1, 'medium': 2, 'high': 3}

        for record in records:
            key = record.get('source_paper_id') or record.get('source_url') or record.get('source_title')
            if not key:
                continue

            rollup = rollups.setdefault(key, {
                'source_paper_id': record.get('source_paper_id', ''),
                'source_title': record.get('source_title', ''),
                'source_authors': record.get('source_authors', ''),
                'source_year': record.get('source_year'),
                'source_url': record.get('source_url', ''),
                'total_records': 0,
                'flagged_records': 0,
                'max_flag_level': 'none',
                'error_type_counts': {},
                'reason_counts': {},
            })

            rollup['total_records'] += 1

            error_type = record.get('error_type') or 'unknown'
            rollup['error_type_counts'][error_type] = rollup['error_type_counts'].get(error_type, 0) + 1

            assessment = record.get('hallucination_assessment', {}) or {}
            if assessment.get('verdict') == 'LIKELY':
                rollup['flagged_records'] += 1
                level = 'high'
                if level_rank.get(level, 0) > level_rank.get(rollup['max_flag_level'], 0):
                    rollup['max_flag_level'] = level

        result = []
        for rollup in rollups.values():
            rollup['has_flagged_records'] = rollup['flagged_records'] > 0
            rollup['error_type_counts'] = dict(sorted(
                rollup['error_type_counts'].items(),
                key=lambda item: (-item[1], item[0]),
            ))
            rollup['reason_counts'] = dict(sorted(
                rollup['reason_counts'].items(),
                key=lambda item: (-item[1], item[0]),
            ))
            result.append(rollup)

        result.sort(
            key=lambda item: (
                -item['flagged_records'],
                -item['total_records'],
                item['source_title'] or '',
            )
        )
        return result

    def build_structured_report_payload(
        self,
        errors: List[Dict[str, Any]],
        stats: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build the structured summary, paper rollups, and records payload.

        *stats* should contain the keys: total_papers_processed,
        total_references_processed, total_errors_found, total_warnings_found,
        total_info_found, total_unverified_refs.
        """
        records = self.build_structured_report_records(errors)
        paper_rollups = self.build_paper_rollups(records)
        summary = {
            'total_papers_processed': stats.get('total_papers_processed', 0),
            'total_references_processed': stats.get('total_references_processed', 0),
            'total_errors_found': stats.get('total_errors_found', 0),
            'total_warnings_found': stats.get('total_warnings_found', 0),
            'total_info_found': stats.get('total_info_found', 0),
            'total_unverified_refs': stats.get('total_unverified_refs', 0),
            'records_written': len(records),
            'papers_with_records': len(paper_rollups),
        }

        flagged_records = [
            record for record in records
            if record.get('hallucination_assessment', {}).get('verdict') == 'LIKELY'
        ]
        summary['flagged_records'] = len(flagged_records)
        summary['flagged_papers'] = sum(1 for paper in paper_rollups if paper['flagged_records'] > 0)

        return {
            'summary': summary,
            'papers': paper_rollups,
            'records': records,
        }

    # ------------------------------------------------------------------
    # Console output
    # ------------------------------------------------------------------

    def build_hallucination_console_lines(self, payload: Dict[str, Any], max_papers: int = 5) -> List[str]:
        """Build a compact summary of hallucination candidates for console output."""
        summary = payload['summary']
        flagged_count = summary.get('flagged_records', 0)

        if flagged_count == 0:
            return []

        flagged_papers = [paper for paper in payload['papers'] if paper.get('flagged_records', 0) > 0]

        lines = [
            "",
            "HALLUCINATION CANDIDATES",
            "-" * 60,
            f"Flagged references: {flagged_count}",
        ]

        if flagged_papers:
            lines.append("Top flagged papers:")
            for paper in flagged_papers[:max_papers]:
                title = paper.get('source_title') or paper.get('source_paper_id') or 'Unknown paper'
                max_flag_level = (paper.get('max_flag_level') or 'none').upper()
                reasons = ', '.join(list((paper.get('reason_counts') or {}).keys())[:3])
                lines.append(
                    f"[{max_flag_level}] {title} ({paper.get('flagged_records', 0)}/{paper.get('total_records', 0)} flagged)"
                )
                if reasons:
                    lines.append(f"    Signals: {reasons}")

            remaining = len(flagged_papers) - max_papers
            if remaining > 0:
                lines.append(f"... plus {remaining} more flagged paper(s)")

        return lines

    def print_hallucination_console_summary(self, payload: Dict[str, Any]) -> None:
        """Print a compact bulk triage summary for hallucination scans."""
        for line in self.build_hallucination_console_lines(payload):
            print(line)

    # ------------------------------------------------------------------
    # File output
    # ------------------------------------------------------------------

    def write_structured_report(self, payload: Dict[str, Any]) -> None:
        """Write structured output to report_file.

        When *report_file* is set the report goes to that path.
        """
        if not self.report_file:
            return

        records = payload['records']
        paper_rollups = payload['papers']
        summary = payload['summary']

        try:
            with open(self.report_file, 'w', encoding='utf-8', errors='replace') as f:
                self._write_to_handle(f, records, paper_rollups, summary)
        except Exception as e:
            logger.error(f"Failed to write structured report: {e}")

    def _write_to_handle(
        self, f: IO, records: List[Dict[str, Any]],
        paper_rollups: List[Dict[str, Any]], summary: Dict[str, Any],
    ) -> None:
        """Write the report to an open file handle (file or stdout)."""
        if self.report_format == 'csv':
            self._write_csv(f, records)
        elif self.report_format == 'jsonl':
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        elif self.report_format == 'json':
            json_payload = {
                'generated_at': datetime.datetime.utcnow().isoformat() + 'Z',
                'summary': summary,
                'papers': paper_rollups,
                'records': records,
            }
            json.dump(json_payload, f, indent=2, ensure_ascii=False)
            f.write('\n')
        else:
            # text format (default for hallucination mode)
            self._write_text(f, records, summary)

    def _write_csv(self, f, records: List[Dict[str, Any]]) -> None:
        """Write records as CSV, including hallucination columns only when relevant."""
        base_fieldnames = [
            'source_paper_id',
            'source_title',
            'source_authors',
            'source_year',
            'source_url',
            'ref_paper_id',
            'ref_title',
            'ref_authors_cited',
            'ref_year_cited',
            'ref_url_cited',
            'error_type',
            'error_details',
            'ref_verified_url',
            'ref_title_correct',
            'ref_authors_correct',
            'ref_year_correct',
            'ref_url_correct',
            'ref_venue_correct',
        ]

        fieldnames = base_fieldnames + [
            'hallucination_verdict',
            'hallucination_explanation',
        ]

        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for record in records:
            row = dict(record)
            assessment = record.get('hallucination_assessment', {}) or {}
            row['hallucination_verdict'] = assessment.get('verdict', '')
            row['hallucination_explanation'] = assessment.get('explanation', '')
            writer.writerow(row)

    def _write_text(self, f: IO, records: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
        """Write a human-readable text report."""
        f.write('REFERENCE CHECK REPORT\n')
        f.write('=' * 70 + '\n')
        f.write(f'References processed: {summary.get("total_references_processed", 0)}\n')
        flagged = summary.get('flagged_records', 0)
        errors = summary.get('total_errors_found', 0)
        warnings = summary.get('total_warnings_found', 0)
        unverified = summary.get('total_unverified_refs', 0)
        if errors:
            f.write(f'Errors:               {errors}\n')
        if warnings:
            f.write(f'Warnings:             {warnings}\n')
        if unverified:
            f.write(f'Unverified:           {unverified}\n')
        if flagged:
            f.write(f'Hallucination flags:  {flagged}\n')
        f.write('=' * 70 + '\n\n')

        if not records:
            f.write('No issues found.\n')
            return

        for i, record in enumerate(records, 1):
            assessment = record.get('hallucination_assessment', {}) or {}
            verdict = assessment.get('verdict', '')
            error_type = record.get('error_type', 'unknown')
            error_details = record.get('error_details', '')

            if verdict == 'LIKELY':
                f.write(f'[{i}] 🚩 LIKELY HALLUCINATED: {record.get("ref_title", "?")}\n')
            else:
                f.write(f'[{i}] {record.get("ref_title", "?")}\n')

            authors = record.get('ref_authors_cited', '')
            year = record.get('ref_year_cited', '')
            if authors:
                f.write(f'    Authors: {authors}\n')
            if year:
                f.write(f'    Year:    {year}\n')

            f.write(f'    Type:    {error_type}\n')
            if error_details:
                f.write(f'    Details: {error_details}\n')

            if verdict == 'LIKELY':
                explanation = assessment.get('explanation', '')
                if explanation:
                    f.write(f'    Reason:  {explanation}\n')

            f.write('\n')
