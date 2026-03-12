"""Structured report building for reference checker results.

Handles JSON, JSONL, CSV export and hallucination triage console output.
Extracted from ArxivReferenceChecker to keep report logic isolated.
"""

from __future__ import annotations

import csv
import datetime
import json
import logging
from typing import Any, Dict, List, Optional

from refchecker.core.hallucination_policy import assess_hallucination_candidate

logger = logging.getLogger(__name__)


class ReportBuilder:
    """Build and write structured reports from reference-checker error entries."""

    def __init__(
        self,
        scan_mode: str = 'standard',
        report_file: Optional[str] = None,
        report_format: str = 'json',
        only_flagged: bool = False,
        llm_verifier: Optional[Any] = None,
        web_searcher: Optional[Any] = None,
    ):
        self.scan_mode = scan_mode
        self.report_file = report_file
        self.report_format = report_format
        self.only_flagged = only_flagged
        self.llm_verifier = llm_verifier
        self.web_searcher = web_searcher

    # ------------------------------------------------------------------
    # Payload construction
    # ------------------------------------------------------------------

    def build_structured_report_records(self, errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert collected error entries into report records."""
        records = []
        for error_entry in errors:
            record = dict(error_entry)
            if self.scan_mode == 'hallucination':
                assessment = assess_hallucination_candidate(record)

                # Run web search on flagged candidates (can reduce or boost score)
                if assessment['candidate'] and self.web_searcher and self.web_searcher.available:
                    web_result = self._run_web_search_verification(record, assessment)
                    if web_result:
                        record['web_search_verification'] = web_result

                # Run LLM verification on flagged candidates (supplementary signal)
                if assessment['candidate'] and self.llm_verifier and self.llm_verifier.available:
                    llm_results = self._run_llm_verification(record, assessment)
                    if llm_results:
                        record['llm_verification'] = llm_results

                record['hallucination_assessment'] = assessment
            records.append(record)

        if self.scan_mode == 'hallucination' and self.only_flagged:
            records = [
                record for record in records
                if record.get('hallucination_assessment', {}).get('candidate')
            ]

        return records

    def _run_web_search_verification(
        self, record: Dict[str, Any], assessment: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Run a web search to see if a flagged reference exists online."""
        try:
            result = self.web_searcher.check_reference_exists(record)
        except Exception as exc:
            logger.warning(f'Web search verification failed: {exc}')
            return None

        delta = result.get('score_delta', 0.0)
        verdict = result.get('verdict', '')
        logger.debug(
            'Web search: title=%r verdict=%s delta=%.2f urls=%s',
            record.get('ref_title', '')[:60], verdict, delta, result.get('academic_urls', []),
        )

        if delta != 0.0:
            new_score = max(min(assessment['score'] + delta, 1.0), 0.0)
            assessment['score'] = round(new_score, 2)

            if delta < 0:
                assessment['reasons'].append('web_search_found')
            else:
                assessment['reasons'].append('web_search_not_found')

            # Re-evaluate candidacy and level after score adjustment
            if new_score < 0.6:
                assessment['candidate'] = False
                assessment['level'] = 'low' if new_score >= 0.35 else 'none'
            elif new_score >= 0.85:
                assessment['level'] = 'high'
            else:
                assessment['level'] = 'medium'

        return result

    def _run_llm_verification(
        self, record: Dict[str, Any], assessment: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Run LLM plausibility and author-consistency checks on a flagged candidate."""
        results: Dict[str, Any] = {}
        total_delta = 0.0

        try:
            plausibility = self.llm_verifier.check_plausibility(record)
            results['plausibility'] = plausibility
            total_delta += plausibility.get('score_delta', 0.0)
        except Exception as exc:
            logger.warning(f'LLM plausibility check failed: {exc}')

        try:
            author_check = self.llm_verifier.check_author_consistency(record)
            results['author_consistency'] = author_check
            total_delta += author_check.get('score_delta', 0.0)
        except Exception as exc:
            logger.warning(f'LLM author consistency check failed: {exc}')

        # Apply LLM score adjustments to the assessment
        if total_delta > 0:
            new_score = min(assessment['score'] + total_delta, 1.0)
            assessment['score'] = round(new_score, 2)
            assessment['reasons'].append('llm_verification_suspicious')
            # Recalculate level
            if new_score >= 0.85:
                assessment['level'] = 'high'
            elif new_score >= 0.6:
                assessment['level'] = 'medium'

        return results if results else None

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
            if assessment.get('candidate'):
                rollup['flagged_records'] += 1
                level = assessment.get('level', 'none')
                if level_rank.get(level, 0) > level_rank.get(rollup['max_flag_level'], 0):
                    rollup['max_flag_level'] = level
                for reason in assessment.get('reasons', []):
                    rollup['reason_counts'][reason] = rollup['reason_counts'].get(reason, 0) + 1

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
            'scan_mode': self.scan_mode,
            'total_papers_processed': stats.get('total_papers_processed', 0),
            'total_references_processed': stats.get('total_references_processed', 0),
            'total_errors_found': stats.get('total_errors_found', 0),
            'total_warnings_found': stats.get('total_warnings_found', 0),
            'total_info_found': stats.get('total_info_found', 0),
            'total_unverified_refs': stats.get('total_unverified_refs', 0),
            'records_written': len(records),
            'papers_with_records': len(paper_rollups),
        }

        if self.scan_mode == 'hallucination':
            flagged_records = [
                record for record in records
                if record.get('hallucination_assessment', {}).get('candidate')
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
        """Build a compact bulk triage summary for hallucination scans."""
        if self.scan_mode != 'hallucination':
            return []

        summary = payload['summary']
        flagged_papers = [paper for paper in payload['papers'] if paper.get('flagged_records', 0) > 0]

        lines = [
            "",
            "HALLUCINATION TRIAGE",
            "-" * 60,
            f"Flagged papers: {summary.get('flagged_papers', 0)}",
            f"Flagged references: {summary.get('flagged_records', 0)}",
        ]

        if not flagged_papers:
            lines.append("No high-confidence hallucination candidates found.")
            return lines

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
        """Write structured output for downstream triage workflows."""
        if not self.report_file:
            return

        records = payload['records']
        paper_rollups = payload['papers']
        summary = payload['summary']

        try:
            with open(self.report_file, 'w', encoding='utf-8', errors='replace') as f:
                if self.report_format == 'csv':
                    self._write_csv(f, records)
                elif self.report_format == 'jsonl':
                    for record in records:
                        f.write(json.dumps(record, ensure_ascii=False) + '\n')
                else:
                    json_payload = {
                        'generated_at': datetime.datetime.utcnow().isoformat() + 'Z',
                        'summary': summary,
                        'papers': paper_rollups,
                        'records': records,
                    }
                    json.dump(json_payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to write structured report: {e}")

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

        if self.scan_mode == 'hallucination':
            fieldnames = base_fieldnames + [
                'hallucination_candidate',
                'hallucination_level',
                'hallucination_score',
                'hallucination_reasons',
            ]
        else:
            fieldnames = base_fieldnames

        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for record in records:
            row = dict(record)
            if self.scan_mode == 'hallucination':
                assessment = record.get('hallucination_assessment', {}) or {}
                row['hallucination_candidate'] = assessment.get('candidate', False)
                row['hallucination_level'] = assessment.get('level', 'none')
                row['hallucination_score'] = assessment.get('score', 0)
                row['hallucination_reasons'] = ';'.join(assessment.get('reasons', []))
            writer.writerow(row)
