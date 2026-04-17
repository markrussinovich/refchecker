"""
GROBID integration for PDF reference extraction.

Provides a fallback extraction method that uses a GROBID server
(local Docker or remote) when no LLM is available.

GROBID auto-starts via Docker if available on the host.
"""

import logging
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

GROBID_URL = os.environ.get("GROBID_URL", "http://localhost:8070")
GROBID_DOCKER_IMAGE = "lfoppiano/grobid:0.8.2"
GROBID_CONTAINER_NAME = "refchecker-grobid"

_grobid_auto_started = False


def ensure_grobid_running() -> bool:
    """Auto-start GROBID Docker container if not already running.

    Returns True if GROBID is available after this call.
    Only attempts auto-start once per process.
    """
    global _grobid_auto_started
    import requests as _requests

    # Quick health check
    try:
        resp = _requests.get(f"{GROBID_URL}/api/isalive", timeout=3)
        if resp.status_code == 200:
            return True
    except Exception:
        pass

    if _grobid_auto_started:
        return False
    _grobid_auto_started = True

    # Try to start via Docker — detect whether sudo is needed
    docker_cmd = ["docker"]
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        if result.returncode != 0:
            # Try with sudo (non-interactive)
            result = subprocess.run(["sudo", "-n", "docker", "info"], capture_output=True, timeout=5)
            if result.returncode == 0:
                docker_cmd = ["sudo", "docker"]
            else:
                logger.info("Docker not available, cannot auto-start GROBID")
                return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.info("Docker not found, cannot auto-start GROBID")
        return False

    logger.info("Starting GROBID Docker container (%s)...", GROBID_DOCKER_IMAGE)
    try:
        subprocess.run(
            docker_cmd + ["rm", "-f", GROBID_CONTAINER_NAME],
            capture_output=True, timeout=10
        )
        result = subprocess.run(
            docker_cmd + ["run", "-d", "--name", GROBID_CONTAINER_NAME,
             "-p", "8070:8070", "--rm", GROBID_DOCKER_IMAGE],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            logger.warning("Failed to start GROBID container: %s", result.stderr.strip())
            return False

        import time
        for i in range(90):
            try:
                resp = _requests.get(f"{GROBID_URL}/api/isalive", timeout=3)
                if resp.status_code == 200:
                    logger.info("GROBID ready", i)
                    return True
            except Exception:
                pass
            time.sleep(1)

        logger.warning("GROBID started but not ready after 90s")
        return False
    except Exception as exc:
        logger.warning("Failed to auto-start GROBID: %s", exc)
        return False


def extract_refs_via_grobid(pdf_path: str) -> List[Dict[str, Any]]:
    """Extract references from a PDF using GROBID.

    Auto-starts GROBID Docker container if needed.
    Returns empty list if GROBID is not available.
    """
    import requests as _requests

    if not ensure_grobid_running():
        return []

    try:
        with open(pdf_path, 'rb') as f:
            resp = _requests.post(
                f"{GROBID_URL}/api/processReferences",
                files={"input": f},
                data={"consolidateCitations": "0", "includeRawCitations": "1"},
                timeout=120,
            )
        if resp.status_code != 200:
            logger.warning("GROBID returned status %d", resp.status_code)
            return []
    except Exception as exc:
        logger.info("GROBID request failed: %s", exc)
        return []

    ns = '{http://www.tei-c.org/ns/1.0}'
    refs: List[Dict[str, Any]] = []
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return []

    for bib in root.iter(f'{ns}biblStruct'):
        ref: Dict[str, Any] = {
            "authors": [], "title": "", "venue": "", "year": None,
            "url": "", "doi": None, "type": "other",
        }
        for pers in bib.iter(f'{ns}persName'):
            forenames = [fn.text for fn in pers.iter(f'{ns}forename') if fn.text]
            surname = ""
            for sn in pers.iter(f'{ns}surname'):
                if sn.text:
                    surname = sn.text
            parts = forenames + ([surname] if surname else [])
            if parts:
                ref["authors"].append(" ".join(parts))
        analytic = bib.find(f'{ns}analytic')
        monogr = bib.find(f'{ns}monogr')
        if analytic is not None:
            t = analytic.find(f'{ns}title')
            if t is not None and t.text:
                ref["title"] = t.text.strip()
        if not ref["title"] and monogr is not None:
            t = monogr.find(f'{ns}title')
            if t is not None and t.text:
                ref["title"] = t.text.strip()
        if monogr is not None and analytic is not None:
            for t in monogr.findall(f'{ns}title'):
                if t.text:
                    ref["venue"] = t.text.strip()
                    break
        for d in bib.iter(f'{ns}date'):
            when = d.get('when', '')
            m = re.match(r'(\d{4})', when)
            if m:
                ref["year"] = int(m.group(1))
                break
        for idno in bib.iter(f'{ns}idno'):
            id_type = (idno.get('type') or '').lower()
            if id_type == 'doi' and idno.text:
                ref["doi"] = idno.text.strip()
                if not ref["url"]:
                    ref["url"] = f"https://doi.org/{ref['doi']}"
            elif id_type == 'arxiv' and idno.text:
                ref["url"] = f"https://arxiv.org/abs/{idno.text.strip()}"
                ref["type"] = "arxiv"
        if not ref["url"]:
            for ptr in bib.iter(f'{ns}ptr'):
                target = ptr.get('target', '')
                if target:
                    ref["url"] = target
        if ref["title"] or ref["authors"]:
            refs.append(ref)

    logger.info("GROBID extracted %d references from %s", len(refs), pdf_path)
    return refs
