# 📄 The Paper: *Phantom References*

> **[Phantom References: Hallucinated Citations That Survive Peer Review at Top-Tier Conferences](https://arxiv.org/abs/2607.00738)**
> Mark Russinovich, Ram Shankar Siva Kumar, Ahmed Salem — arXiv:2607.00738

RefChecker is the verification pipeline built for this study, and the study is the flagship
demonstration of its **[bulk scanning](../README.md#bulk-checking)** capability: we pointed
RefChecker at the accepted camera-ready papers of **ICLR, ICML, NeurIPS, and USENIX Security**
and audited their bibliographies end to end.

## What the scan found

Published papers really do carry wrong and even fabricated references:

- **Hallucinated citations have entered the archival record.** Measured with a deliberately
  conservative definition: only *identity-level* failures — works that do not exist, or
  substantial author-list mismatches — explicitly excluding ordinary bibliographic drift
  such as venue/year differences, publication-status updates, or minor name variants.
- **Reference-level rates are usually below 1%**, but proceedings are large enough that the
  paper level tells the story: in **2025, roughly one in twenty NeurIPS and USENIX Security
  papers** contained **at least two** likely hallucinated academic-paper-like references.
- **Post-ChatGPT increases** in several venues, including a tail of papers with **5+ failures
  in a single bibliography** — and likely hallucinated citations even among **award-winning
  papers**.
- **Peer review alone does not reliably enforce citation integrity** — yet auditing is
  tractable: about **$0.04 per paper** in one venue-scale scan.

## Reproducing the scan

That is exactly the workflow this repo supports: run the same engine across a whole
conference, a reading list, or your own draft before you submit.

- **[Bulk Checking](../README.md#bulk-checking)** — run hundreds of papers in one batch.
- **[OpenReview Integration](../README.md#openreview-integration)** — fetch and scan an entire
  venue's accepted papers or public submissions.
- **[Hallucination Detection](../README.md#hallucination-detection)** — the three-stage pipeline
  behind the identity-level verdicts used in the paper.

<sub>Please cite the paper if RefChecker helps your work.</sub>

---

Back to the [project README](../README.md) · more guides in [docs/README.md](README.md).
