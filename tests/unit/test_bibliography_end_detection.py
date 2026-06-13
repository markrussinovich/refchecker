"""Tests for bibliography end detection patterns"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import pytest
from unittest.mock import Mock, patch
from refchecker.core.refchecker import ArxivReferenceChecker


class TestBibliographyEndDetection:
    """Test bibliography section boundary detection"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.checker = ArxivReferenceChecker()
    
    def test_bibliography_stops_before_evaluation_details(self):
        """Test that bibliography correctly stops before 'C Evaluation Details' appendix section"""
        # Sample text simulating the problematic paper structure
        sample_text = """
        References
        [1] Author One, Title One, Journal One, 2020.
        [2] Author Two, Title Two, Conference Two, 2021.
        
        Some final reference content ending with consistent with Appendix B.
        
        C Evaluation Details
        Benchmark. To comprehensively evaluate the performance of model, our benchmarks include
        college-level question, math-related question and challenging scientific reasoning.
        """
        
        bibliography_text = self.checker.find_bibliography_section(sample_text)
        
        # Verify bibliography was found
        assert bibliography_text is not None
        assert len(bibliography_text) > 0
        
        # Verify bibliography doesn't include the appendix content
        assert "C Evaluation Details" not in bibliography_text
        assert "Benchmark. To comprehensively evaluate" not in bibliography_text
        
        # Verify bibliography includes the reference content
        assert "[1] Author One" in bibliography_text
        assert "[2] Author Two" in bibliography_text
        assert "consistent with Appendix B." in bibliography_text
    
    def test_bibliography_stops_before_appendix_patterns(self):
        """Test that bibliography stops before various appendix section patterns"""
        appendix_patterns = [
            "A Theoretical Analysis",
            "B Implementation Details", 
            "C Evaluation Details",
            "D Additional Results",
            "E Prompt",
            "F Limitations",
            "G Broader Impacts"
        ]
        
        for pattern in appendix_patterns:
            # Create longer, more realistic bibliography content to avoid the 100-char filter
            sample_text = f"""
            References
            [1] First Author, "A comprehensive study on machine learning approaches for data analysis", 
                Journal of Computer Science, vol. 45, no. 3, pp. 123-145, 2020.
            [2] Second Author, "Novel algorithms for optimization in deep neural networks", 
                Proceedings of International Conference on AI, pp. 67-89, 2021.
            [3] Third Author, "Statistical methods for evaluating model performance", 
                IEEE Transactions on Pattern Analysis, vol. 12, pp. 234-256, 2022.
            [4] Fourth Author, "Advanced techniques in computational linguistics", 
                ACL Conference Proceedings, pp. 456-478, 2023.
            
            {pattern}
            This is appendix content that should not be included in bibliography.
            """
            
            bibliography_text = self.checker.find_bibliography_section(sample_text)
            
            # Verify bibliography was found and doesn't include appendix content
            assert bibliography_text is not None
            assert pattern not in bibliography_text, f"Bibliography incorrectly includes '{pattern}'"
            assert "This is appendix content" not in bibliography_text
            assert "[1] First Author" in bibliography_text
    
    def test_bibliography_handles_multiple_appendix_sections(self):
        """Test bibliography extraction with multiple appendix sections"""
        sample_text = """
        References
        [1] First Author, "Comprehensive analysis of machine learning models in practice", 
            International Journal of AI Research, vol. 15, pp. 100-120, 2020.
        [2] Second Author, "Optimization techniques for large-scale neural network training", 
            Conference on Neural Information Processing Systems, pp. 250-265, 2021.
        [3] Third Author, "Statistical approaches to model evaluation and validation", 
            Journal of Machine Learning Research, vol. 22, pp. 450-470, 2022.
        
        A Theoretical Analysis
        Some theoretical content here.
        
        B Implementation Details
        Implementation details here.
        
        C Evaluation Details
        Evaluation content here.
        """
        
        bibliography_text = self.checker.find_bibliography_section(sample_text)
        
        # Should stop at the first appendix section (A Theoretical Analysis)
        assert bibliography_text is not None
        assert "A Theoretical Analysis" not in bibliography_text
        assert "B Implementation Details" not in bibliography_text
        assert "C Evaluation Details" not in bibliography_text
        
        # Should include all references
        assert "[1] First Author" in bibliography_text
        assert "[2] Second Author" in bibliography_text
        assert "[3] Third Author" in bibliography_text

    def test_final_reference_year_before_appendix_is_preserved(self):
        """A previous reference year must not be consumed as a numbered appendix heading."""
        sample_text = """
        References
        [1] First Author. First title. In Conference, 2020.
        [2] Jixuan Zhou, Dan Feng, and Bo Li. A fuzzing method
        based on dual variation strategy for cisco ios. In ICCC,
        2017.
        APPENDIX
        A Optimization Strategies
        Appendix prose should not be included.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert "In ICCC," in bibliography_text
        assert "2017." in bibliography_text
        assert "APPENDIX" not in bibliography_text

    def test_bibliography_stops_before_period_lettered_appendix_headings(self):
        """Regression for ICML PDFs whose appendices start as 'A. ...'."""
        appendix_patterns = [
            "A. Preliminaries",
            "A. More on Related Work",
            "A. Detailed discussion of related work",
            "A. The Central Role of Defect Detection in Code Review",
            "A. General Topology",
            "A. Cognitive Framework",
            "A. Frequently Used Notation",
            "A. The Unfolding Procedure",
        ]

        for pattern in appendix_patterns:
            sample_text = f"""
            References
            Alon, N., Livni, R., Malliaris, M., and Moran, S. Private pac learning
            implies finite littlestone dimension. In Proceedings of STOC, 2019.

            Bun, M., Dwork, C., Rothblum, G. N., and Steinke, T. Composable and
            versatile privacy via truncated CDP. In Proceedings of STOC, 2018.

            Hopkins, M. and Moran, S. The role of randomness in stability.
            International Conference on Machine Learning, 2025.

            {pattern}
            This appendix content contains citations (Bun et al., 2020), theorem
            statements, and prose that should not become bibliography text.
            """

            bibliography_text = self.checker.find_bibliography_section(sample_text)

            assert bibliography_text is not None
            assert "Composable and" in bibliography_text
            assert pattern not in bibliography_text
            assert "This appendix content" not in bibliography_text

    def test_bibliography_does_not_stop_at_reference_title_starting_with_initial(self):
        """A reference title may begin with 'A.' and should not be an end marker."""
        sample_text = """
        References
        Rafailov, R., Sharma, A., Mitchell, E., Manning, C. D., Ermon, S., and Finn,
        C. Direct preference optimization: Your language model is secretly a reward
        model. Advances in Neural Information Processing Systems, 2023.

        Lee, H., Phatale, S., Mansoor, H., Lu, K. R., Mesnard, T., Ferret, J.,
        Bishop, C., Hall, E., Carbune, V., and Rastogi,
        A. RLAIF: Scaling reinforcement learning from human feedback with ai feedback. 2023.

        Huang, A., Zhan, W., Xie, T., Lee, J. D., Sun, W., Krishnamurthy, A., and
        Foster, D. J. Correcting the mythos of kl-regularization. arXiv e-prints, 2024.

        A. Missing Details in the Main Text
        This appendix content should not be included.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "A. RLAIF: Scaling reinforcement learning" in bibliography_text
        assert "Correcting the mythos" in bibliography_text
        assert "A. Missing Details" not in bibliography_text
        assert "This appendix content" not in bibliography_text

    def test_bibliography_stops_at_dotted_appendix_after_page_header(self):
        """PDF extraction may glue a page header before an appendix heading."""
        sample_text = """
        References
        Zheng, T., Zhang, G., Shen, T., Liu, X., Lin, B. Y., Fu, J., Chen, W.,
        and Yue, X. Opencodeinterpreter: Integrating code generation with execution
        and refinement. arXiv preprint arXiv:2402.14658, 2024.

        Zheng, Y., Zhang, R., Zhang, J., Ye, Y., Luo, Z., Feng, Z., and Ma, Y.
        Llamafactory: Unified efficient fine-tuning of 100+ language models. In
        Proceedings of the Association for Computational Linguistics, 2024.

        14 CODE SYNC: Synchronizing Large Language Models with Dynamic Code Evolution at Scale A. Comprehensive Related Works
        Deep Learning for Code Intelligence. Neural language models have made
        progress in code intelligence (Wan et al., 2024), including code search
        and code generation. This appendix prose should not be parsed as references.

        B. Detailed Experiment Setups
        Further appendix content.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Opencodeinterpreter" in bibliography_text
        assert "Llamafactory" in bibliography_text
        assert "A. Comprehensive Related Works" not in bibliography_text
        assert "Deep Learning for Code Intelligence" not in bibliography_text
        assert "B. Detailed Experiment Setups" not in bibliography_text

    def test_bibliography_stops_before_icml_2024_appendix_edge_headings(self):
        """Regression coverage for ICML 2024 appendix headings missed after references."""
        appendix_cases = [
            (
                "B. Full Related Work",
                "Cross-modal Understanding and Generation should not become a reference title.",
            ),
            (
                "A.2.1. M ODULE 2.1: A XIOMS OF UTILITY IN\nDETERMINISTIC ENVIRONMENTS",
                "Element 2.2.b (Avoidance of Endowment Effect) should not be parsed as a citation.",
            ),
            (
                "B. S6 Parameterization",
                "Corollary 3.3 then allows us to conclude appendix prose is not bibliography.",
            ),
            (
                "E. ATT-friendly adaptive MCMC schemes",
                "Tibbits et al. (2014) appendix prose should not become a cited title.",
            ),
            (
                "A. Parameterized Complexity",
                "For a complete introduction to parameterized complexity, appendix prose should not be parsed.",
            ),
            (
                "A. The Proof of the Key Theoretical Results",
                "In the main text, we present Lemma 3.2; this proof prose is not a reference.",
            ),
            (
                "D. Choice of Sampling Strategy",
                "We carefully selected the program sampling strategy; this is appendix prose.",
            ),
            (
                "D. Privacy Proofs",
                "Proof Sketch of Lemma 3.3 should not be parsed as bibliography text.",
            ),
            (
                "A. New tasks: datasets, benchmarks, and code",
                "Context-specific metrics and benchmark prose should not be parsed as citations.",
            ),
            (
                "A. Differential Privacy Basics",
                "Differential privacy definitions belong to appendix prose, not the bibliography.",
            ),
            (
                "B. Frequency Estimation",
                "Frequency-estimation appendix details should not be parsed as references.",
            ),
            (
                "C. Sparse Oblivious Subspace Embeddings",
                "Subspace embedding proof details should not be parsed as references.",
            ),
            (
                "A. Expanded Related Works",
                "Mechanistic-interpretability related-work prose should not be parsed as references.",
            ),
            (
                "B. Program Structure",
                "Program examples in the appendix should not be parsed as references.",
            ),
            (
                "C. Tokenization Details",
                "Tokenization appendix details should not be parsed as references.",
            ),
        ]

        for heading, appendix_prose in appendix_cases:
            sample_text = f"""
            References
            Alon, N., Livni, R., Malliaris, M., and Moran, S. Private pac learning
            implies finite littlestone dimension. In Proceedings of STOC, 2019.

            Bun, M., Dwork, C., Rothblum, G. N., and Steinke, T. Composable and
            versatile privacy via truncated CDP. In Proceedings of STOC, 2018.

            Hopkins, M. and Moran, S. The role of randomness in stability.
            International Conference on Machine Learning, 2025.

            {heading}
            {appendix_prose}
            """

            bibliography_text = self.checker.find_bibliography_section(sample_text)

            assert bibliography_text is not None
            assert "Composable and" in bibliography_text
            assert heading not in bibliography_text
            assert appendix_prose not in bibliography_text

    def test_bibliography_stops_before_regressed_dotted_appendix_headings(self):
        """Current >=3-flag reruns exposed dotted appendix headings after references."""
        appendix_cases = [
            (
                "B. Interpretation of DMPMs",
                "This appendix interpretation derives the forward Markov process and is not bibliography.",
            ),
            (
                "C. Variational Bound",
                "The reverse process is formalized here as appendix prose, not as a citation.",
            ),
            (
                "A. Table of Notations and Definitions",
                "Symbol definitions and notation tables should not be parsed as reference entries.",
            ),
            (
                "A. Individual Dataset Details",
                "Dataset descriptions and cohort statistics should not become unverified citations.",
            ),
            (
                "A. The Algorithm of AESL",
                "Algorithm details belong to the appendix and must not be included in the bibliography.",
            ),
            (
                "A. Coloring the plane with seven colors",
                "Grid diagrams and coloring construction details are appendix content.",
            ),
            (
                "A. Broader Impacts and Limitations",
                "Impact and limitation discussion after references should not be scanned as references.",
            ),
            (
                "A. Other Related Works",
                "Related-work appendix prose about B-Trees should not become bibliography.",
            ),
            (
                "B. Examples of the DSP Issues",
                "Example proof-step generation details belong in the appendix.",
            ),
            (
                "A. Step-size Optimization for Different Choices of Base and Meta updates",
                "Notation conventions in all appendices should not be parsed as references.",
            ),
            (
                "A. The Effect of the Number of LoRAs on Semantic Convergence",
                "Figure axes and LoRA counts after references should not be parsed.",
            ),
            (
                "A. Existing works on diffusion-based generative models for discrete data",
                "Embedding discrete structure in the continuous space is appendix prose, not bibliography.",
            ),
            (
                "A. Gaussian Noise Distorts Angular Relationship",
                "The following lemma establishes how Gaussian noise fails to maintain angular class structure.",
            ),
            (
                "B. Class Separation using vMF",
                "This result provides a theoretical foundation for setting kappa in appendix analysis.",
            ),
            (
                "A. Continuity of the time-shift operator for ODEs",
                "Continuity proofs for the time-shift operator should not be parsed as references.",
            ),
        ]

        for heading, appendix_prose in appendix_cases:
            sample_text = f"""
            References
            Alon, N., Livni, R., Malliaris, M., and Moran, S. Private pac learning
            implies finite littlestone dimension. In Proceedings of STOC, 2019.

            Bun, M., Dwork, C., Rothblum, G. N., and Steinke, T. Composable and
            versatile privacy via truncated CDP. In Proceedings of STOC, 2018.

            Hopkins, M. and Moran, S. The role of randomness in stability.
            International Conference on Machine Learning, 2025.

            {heading}
            {appendix_prose}
            """

            bibliography_text = self.checker.find_bibliography_section(sample_text)

            assert bibliography_text is not None
            assert "Composable and" in bibliography_text
            assert heading not in bibliography_text
            assert appendix_prose not in bibliography_text

    def test_bibliography_stops_before_standalone_appendices_heading(self):
        """Some PDFs use a standalone plural Appendices heading after references."""
        sample_text = """
        References
        Asi, H. and Duchi, J. The importance of better models in stochastic optimization.
        Proceedings of the National Academy of Sciences, 2019.

        Franceschi, L., Donini, M., Frasconi, P., and Pontil, M. Bilevel programming
        for hyperparameter optimization and meta-learning. In International Conference
        on Machine Learning, 2018.

        Young, K., Wang, B., and Taylor, M. E. Metatrace: Online step-size tuning by
        meta-gradient descent for reinforcement learning control. arXiv preprint, 2018.

        11
        MetaOptimize
        Appendices
        A. Notation conventions
        Appendix notation and experimental details should not be parsed as references.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Metatrace" in bibliography_text
        assert "MetaOptimize" not in bibliography_text
        assert "Appendices" not in bibliography_text
        assert "Notation conventions" not in bibliography_text

    def test_bibliography_stops_before_letter_digit_spaced_appendix_heading(self):
        """PDF extraction can render appendix headings as 'A12 E XPERIMENT SETTINGS'."""
        sample_text = """
        References
        Fan, Z., Li, J., and Chen, Y. Graph transformer models for circuit design.
        Proceedings of the International Conference on Machine Learning, 2024.

        Guo, J., Wang, L., and Zhang, T. Timing graph convolutional networks.
        IEEE Transactions on Computer-Aided Design, 2022.

        Xie, M., Lee, R., and Kumar, S. Net length prediction with graph attention.
        In Proceedings of the ACM Design Automation Conference, 2021.

        A12 E XPERIMENT SETTINGS
        To overcome these limitations, recent works have developed GNN variants
        specifically tailored for EDA tasks. This appendix prose is not a reference.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Timing graph convolutional networks" in bibliography_text
        assert "A12 E XPERIMENT SETTINGS" not in bibliography_text
        assert "specifically tailored for EDA tasks" not in bibliography_text

    def test_bibliography_stops_before_regressed_collapsed_appendix_headings(self):
        """ICLR PDFs can collapse appendix section letters into the heading text."""
        sample_text = """
        References
        Schops, T., Schonberger, J. L., Galliani, S., Sattler, T., Schindler, K.,
        Pollefeys, M., and Geiger, A. A multi-view stereo benchmark with high-resolution images
        and multi-camera videos. In Proceedings of CVPR, 2017.

        Shen, X., Cai, Z., Yin, W., and Wang, K. GL3D: A large-scale benchmark for
        geometric learning. In Proceedings of Computer Vision and Pattern Recognition, 2018.

        BPREVENTOVERFITTING
        Preventing overfitting is crucial when training with large-scale video data.

        CHANDLINGNOISYANDLOW-QUALITYDATA
        Figure6: Sample video data and generated labels should not be bibliography.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "multi-view stereo benchmark" in bibliography_text
        assert "BPREVENTOVERFITTING" not in bibliography_text
        assert "Preventing overfitting" not in bibliography_text
        assert "Figure6" not in bibliography_text

    def test_bibliography_stops_before_spaced_caps_appendix_with_punctuation(self):
        """Spaced all-caps appendix headings may contain punctuation and acronyms."""
        sample_text = """
        References
        Zhang, T., Qiu, L., Guo, Q., Deng, C., and Zhou, T. Enhancing uncertainty-based
        hallucination detection with stronger focus. In Proceedings of EMNLP, 2023.

        Zhu, Q., Duan, J., Chen, C., Liu, S., and Li, X. Near-lossless acceleration
        of long context llm inference with adaptive sparse attention. arXiv:2406.15486, 2024.

        A F ULL BACKGROUND ON ATTENTION HEADS , FFN S, AND LOGIT LENS
        The theoretical foundation of our work is grounded in mechanistic interpretability.
        FFNl equations and residual stream details should not become bibliography.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Near-lossless acceleration" in bibliography_text
        assert "F ULL BACKGROUND" not in bibliography_text
        assert "mechanistic interpretability" not in bibliography_text
        assert "FFNl equations" not in bibliography_text

    def test_bibliography_stops_before_numbered_spaced_post_reference_headings(self):
        """Post-reference sections can be numbered with PDF-spaced heading words."""
        sample_text = """
        References
        Zhou, T., Niu, P., Sun, L., and Jin, R. One fits all: Power general time
        series analysis by pretrained language models. NeurIPS, 2023.

        Zhou, Y., Xiao, C., and Liu, Y. Multivariate time-series anomaly detection
        via graph attention networks. In ICDM, pp. 841-850, 2020.

        8 R EPRODUCIBILITY
        We will make our dataset public through the project page.

        9 E THICAL CONSIDERATIONS
        This post-reference prose should not be in the bibliography.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "graph attention networks" in bibliography_text
        assert "8 R EPRODUCIBILITY" not in bibliography_text
        assert "make our dataset public" not in bibliography_text
        assert "E THICAL" not in bibliography_text

    def test_bibliography_stops_before_symbol_table_rows(self):
        """Guardrail comparison tables after references should end bibliography extraction."""
        sample_text = """
        References
        Zhao, R., Li, X., Joty, S., Qin, C., and Bing, L. Verify-and-edit: A
        knowledge-enhanced chain-of-thought framework. arXiv:2305.03268, 2023.

        Zou, A., Wang, Z., Kolter, J. Z., and Fredrikson, M. Universal and transferable
        adversarial attacks on aligned language models. arXiv:2307.15043, 2023.

        Monitoring rules ! ! !
        Enforcement rules % ! !
        Multi-modal support ! ! %
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Verify-and-edit" in bibliography_text
        assert "Universal and transferable" in bibliography_text
        assert "Monitoring rules" not in bibliography_text
        assert "Multi-modal support" not in bibliography_text

    def test_bibliography_uses_earliest_heuristic_end_marker(self):
        """A later table caption must not win over an earlier symbol-table row."""
        sample_text = """
        References
        Zhao, R., Li, X., Joty, S., Qin, C., and Bing, L. Verify-and-edit: A
        knowledge-enhanced chain-of-thought framework. arXiv:2305.03268, 2023.

        Zou, A., Wang, Z., Kolter, J. Z., and Fredrikson, M. Universal and transferable
        adversarial attacks on aligned language models. arXiv:2307.15043, 2023.

        Monitoring rules ! ! !
        Enforcement rules % ! !
        Table 2. Compared Results of Guardrail Frameworks under Qualitative Analysis Dimensions
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Universal and transferable" in bibliography_text
        assert "Monitoring rules" not in bibliography_text
        assert "Table 2" not in bibliography_text

    def test_bibliography_trims_single_trailing_artifact_line(self):
        """A single non-reference artifact after the final citation should be trimmed."""
        sample_text = """
        References
        Zhi-Yi, C., Chieh-Ming, J., Ching-Chun, H., Pin-Yu, C., and Wei-Chen, C.
        Prompting4debugging: Red-teaming text-to-image diffusion models by finding
        problematic prompts. In ICML, pp. 8468-8486, 2024.

        Zhou, Y., Liu, B., Zhu, Y., Yang, X., Chen, C., and Xu, J. Shifted diffusion
        for text-to-image generation. In CVPR, pp. 10157-10166, 2023.

        dasdsa
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Prompting4debugging" in bibliography_text
        assert "Shifted diffusion" in bibliography_text
        assert "dasdsa" not in bibliography_text

    def test_bibliography_trims_artifact_after_pdf_page_header(self):
        """A lowercase artifact after a PDF page header should not survive cleanup."""
        sample_text = """
        References
        Zhi-Yi, C., Chieh-Ming, J., Ching-Chun, H., Pin-Yu, C., and Wei-Chen, C.
        Prompting4debugging: Red-teaming text-to-image diffusion models by finding
        problematic prompts. In ICML, pp. 8468-8486, 2024.

        Zhou, Y., Liu, B., Zhu, Y., Yang, X., Chen, C., and Xu, J. Shifted diffusion
        for text-to-image generation. In CVPR, pp. 10157-10166, 2023.
        12
        Collaborative Erasing Framework for Diffusion Models
        dasdsa
        Contents
        A. Experimental Settings 14
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Shifted diffusion" in bibliography_text
        assert "Collaborative Erasing Framework" not in bibliography_text
        assert "dasdsa" not in bibliography_text
        assert "Experimental Settings" not in bibliography_text

    def test_bibliography_keeps_valid_reference_boundary_lookalikes(self):
        """Lock correct cases that broad appendix guards might accidentally truncate."""
        sample_text = """
        References
        Villani, C. Optimal transport: old and new, volume 338. Springer, 2009.

        Waissi, G. R. Network flows: Theory, algorithms, and applications, 1994.

        Zhang, X. and Lee, Y. Artificial intelligence for planning, Part II 16,
        pp. 402-419. Springer, 2020.

        Lee, H., Phatale, S., Mansoor, H., Lu, K. R., Mesnard, T., Ferret, J.,
        Bishop, C., Hall, E., Carbune, V., and Rastogi,
        A. RLAIF: Scaling reinforcement learning from human feedback with ai feedback. 2023.

        A. Table of Notations and Definitions
        Appendix notation content should not be included.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Optimal transport" in bibliography_text
        assert "Part II 16" in bibliography_text
        assert "A. RLAIF: Scaling reinforcement learning" in bibliography_text
        assert "A. Table of Notations" not in bibliography_text
        assert "Appendix notation content" not in bibliography_text

    def test_bibliography_stops_before_letter_digit_dotted_appendix_headings(self):
        """ICML PDFs can use headings like A1. Review or A2. Additional after refs."""
        appendix_cases = [
            "A1. Review of Existing Conformal Inference Methods",
            "A2. Additional Methodological Details",
        ]

        for heading in appendix_cases:
            sample_text = f"""
            References
            Candès, E. J., Lei, L., and Ren, Z. Conformalized survival analysis.
            Journal of the Royal Statistical Society, 2023.

            Barber, R. F., Candès, E. J., Ramdas, A., and Tibshirani, R. J.
            Conformal prediction beyond exchangeability. Annals of Statistics, 2023.

            {heading}
            Algorithm A1 outlines additional implementation details that are not references.
            """

            bibliography_text = self.checker.find_bibliography_section(sample_text)

            assert bibliography_text is not None
            assert "Conformalized survival analysis" in bibliography_text
            assert heading not in bibliography_text
            assert "Algorithm A1" not in bibliography_text

    def test_fallback_does_not_treat_isolated_bracketed_table_indices_as_refs(self):
        """Fallback should not turn body/table markers like X[15] into bibliography."""
        sample_text = """
        1 Introduction
        We analyze tree splits and report node statistics below.

        X[15] <= 0.437
        32560
        [24719, 7841]
        X[15] <= 0.159
        25106
        [22593, 2513]
        True
        X[14] <= 0.305

        All proofs are postponed to the appendix. This paper does not expose a
        bibliography heading in extracted PDF text.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is None

    def test_bibliography_stops_at_appendix_structure_prose_after_references(self):
        sample_text = """
        References
        Alayrac, J.-B., Donahue, J., Luc, P., Miech, A., Barr, I., Hasson, Y.,
        Lenc, K., Mensch, A., Millican, K., Reynolds, M., et al. Flamingo: a
        visual language model for few-shot learning. NeurIPS, 2022.

        Chen, X., Wang, X., Changpinyo, S., Piergiovanni, A., Padlewski, P.,
        Salz, D., Goodman, S., Grycner, A., Mustafa, B., Beyer, L., et al. Pali:
        A jointly-scaled multilingual language-image model. ICLR, 2023.

        Sun, C., Shrivastava, A., Singh, S., and Gupta, A. Revisiting unreasonable
        effectiveness of data in deep learning era. ICCV, 2017.

        The Appendix is structured as follows—we provide model
        and dataset details in Sections B and C respectively.
        PaLI scoring is length normalized and should not be parsed as a title.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Flamingo" in bibliography_text
        assert "The Appendix is structured" not in bibliography_text
        assert "PaLI scoring" not in bibliography_text

    def test_bibliography_stops_at_collapsed_appendix_for_heading(self):
        sample_text = """
        References
        Agarwal, A., Kakade, S., Krishnamurthy, A., and Sun, W. Flambe:
        Structural complexity and representation learning of low rank mdps.
        Advances in neural information processing systems, 2020.

        Zhang, Y., Zhang, F., Yang, Z., and Wang, Z. What and how does
        in-context learning learn? Bayesian model averaging, parameterization,
        and generalization. arXiv preprint arXiv:2305.19420, 2023.

        13
        From Words to Actions: Unveiling the Theoretical Underpinnings of LLM-Driven Autonomous Systems

        Appendixfor
        “From Words to Actions: Unveiling the Theoretical Underpinnings of
        LLM-Driven Autonomous Systems”
        A.AdditionalBackgroundandRelatedWorks
        Q-learning with language models should not be parsed as a title.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Flambe" in bibliography_text
        assert "Appendixfor" not in bibliography_text
        assert "Q-learning with language models" not in bibliography_text

    def test_inline_references_heading_before_author_year_entries(self):
        """PDF extraction can put REFERENCES and the first author on one line."""
        sample_text = """
        Acknowledgments We thank the reviewers for helpful suggestions. REFERENCES Steven Bills, Nick Cammarata, Dan Mossing, Henk Tillman, Leo Gao, Gabriel Goh, Ilya Sutskever, Jan Leike, Jeff Wu, and William Saunders. Language models can explain neurons in language models, 2023.
        Kevin Clark, Urvashi Khandelwal, Omer Levy, and Christopher D. Manning. What does BERT look at? An analysis of BERT's attention. In ACL, 2019.

        A. Additional Experiments
        Appendix prose must not be included.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Language models can explain neurons" in bibliography_text
        assert "What does BERT look at" in bibliography_text
        assert "Additional Experiments" not in bibliography_text
        assert "Appendix prose" not in bibliography_text

    def test_prefers_first_valid_references_over_later_appendix_example_section(self):
        """Appendix examples can contain their own References section after the real bib."""
        sample_text = """
        Introduction text mentions references below without starting the bibliography.

        REFERENCES Jean-Baptiste Alayrac, Jeff Donahue, Pauline Luc, Antoine Miech, Iain Barr, Yana Hasson, Karel Lenc, Arthur Mensch, Katherine Millican, Malcolm Reynolds, et al. Flamingo: a visual language model for few-shot learning. Advances in Neural Information Processing Systems, 2022.
        Arian Bakhtiarnia, Qi Zhang, and Alexandros Iosifidis. Multi-exit vision transformer for dynamic inference. arXiv preprint arXiv:2106.15183, 2021.
        Tolga Bolukbasi, Joseph Wang, Ofer Dekel, and Venkatesh Saligrama. Adaptive neural networks. ICML, 2020.

        A. Prompt Examples
        The model writes the following analysis.
        References Mengzhao Chen, Wenqi Shao, Peng Xu, Mingbao Lin, Kaipeng Zhang, Fei Chao, Rongrong Ji, Yu Qiao, and Ping Luo. Diffrate: Differentiable compression rate for efficient vision transformers. arXiv preprint arXiv:2305.17997, 2023.
        Kaiming He, Xinlei Chen, Saining Xie, Yanghao Li, Piotr Dollar, and Ross Girshick. Masked autoencoders are scalable vision learners. CVPR, 2022.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Flamingo" in bibliography_text
        assert "Adaptive neural networks" in bibliography_text
        assert "Prompt Examples" not in bibliography_text
        assert "Diffrate" not in bibliography_text

    def test_bibliography_stops_before_plural_supplementary_materials(self):
        sample_text = """
        References
        Liu, J., Shen, D., Zhang, Y., Dolan, B., Carin, L., and Chen, W. What makes
        good in-context examples for gpt-3? arXiv preprint arXiv:2101.06804, 2021.

        Rubin, O., Herzig, J., and Berant, J. Learning to retrieve prompts for
        in-context learning. arXiv preprint arXiv:2112.08633, 2021.

        Supplementary Materials: FEEDER
        A2.2. Set Level Metrics
        We extend definitions here; this is appendix content, not a reference.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Learning to retrieve prompts" in bibliography_text
        assert "Supplementary Materials" not in bibliography_text
        assert "Set Level Metrics" not in bibliography_text

    def test_bibliography_stops_before_appendix_outline(self):
        sample_text = """
        References
        Zhang, S., Yu, D., Sharma, H., Zhong, H., Liu, Z., Yang, Z., Wang, S.,
        Hassan, H., and Wang, Z. Self-exploring language models: Active preference
        elicitation for online alignment. arXiv preprint arXiv:2405.19332, 2024.

        Ziebart, B. D., Maas, A. L., Bagnell, J. A., Dey, A. K., et al. Maximum
        entropy inverse reinforcement learning. In AAAI, 2008.

        Outline of the Appendix
        • Appx. A: Frequently Used Notation.
        • Appx. B: Missing Details in the Main Text.

        A. Frequently Used Notation
        Notation table content follows.
        """

        bibliography_text = self.checker.find_bibliography_section(sample_text)

        assert bibliography_text is not None
        assert "Maximum" in bibliography_text
        assert "Outline of the Appendix" not in bibliography_text
        assert "Appx. A" not in bibliography_text
        assert "Notation table" not in bibliography_text

    def test_paper_2507_16814_specific_case(self):
        """Regression test for the specific paper that was failing"""
        # This test ensures the fix works for the exact pattern from paper 2507.16814
        sample_text = """
        References
        [68] Reference content here.
        [69] Another reference.
        [70] Final reference ending with learning rate of 5 × 10−7,
        with all other settings consistent with Appendix B.
        
        C Evaluation Details
        Benchmark. To comprehensively evaluate the performance of model, our benchmarks include
        college-level question, math-related question and challenging scientific reasoning. The specific split
        of datasets is shown as below.
        """
        
        bibliography_text = self.checker.find_bibliography_section(sample_text)
        
        # Verify the fix works correctly
        assert bibliography_text is not None
        assert "C Evaluation Details" not in bibliography_text
        assert "Benchmark. To comprehensively evaluate" not in bibliography_text
        assert "consistent with Appendix B." in bibliography_text
        
        # Verify references are included
        assert "[68] Reference content" in bibliography_text
        assert "[69] Another reference" in bibliography_text
        assert "[70] Final reference" in bibliography_text

    def test_paper_2505_09338_lre_dataset_case(self):
        """Regression test for paper 2505.09338 with 'A LRE Dataset' appendix"""
        # This test ensures the fix works for the specific paper https://arxiv.org/pdf/2505.09338
        # that was incorrectly including "A LRE Dataset" appendix content in bibliography
        sample_text = """
        References
        Lei Yu, Jingcheng Niu, Zining Zhu, and Gerald Penn.
        2024a. Are LLMs classical or nonmonotonic rea-
        soners? Lessons from generics. In Proceedings
        of the 2024 Conference on Empirical Methods in
        Natural Language Processing: Main Conference,
        EMNLP 2024, pages 7943–7956, Miami, Florida, USA.
        Association for Computational Linguistics.
        
        Lei Yu, Jingcheng Niu, Zining Zhu, and Gerald Penn.
        2024b. Functional Faithfulness in the Wild: Circuit
        Discovery with Differentiable Computation Graph
        Pruning. Preprint, arXiv:2407.03779.
        
        Relation # Samples Context Templates Query Templates
        company hq 674 The headquarters of {} is in the
        city of
        Where are the headquarters of {}?
        
        A LRE Dataset
        We construct our experimental prompts using commonsense and factual data from the LRE dataset
        (Hernandez et al., 2024). This dataset comprises 47 relations with over 10,000 instances, spanning
        four categories: factual associations, commonsense knowledge, implicit biases, and linguistic patterns.
        """
        
        bibliography_text = self.checker.find_bibliography_section(sample_text)
        
        # Verify the fix works correctly
        assert bibliography_text is not None
        
        # Should include the references
        assert "Lei Yu, Jingcheng Niu" in bibliography_text
        assert "arXiv:2407.03779" in bibliography_text
        
        # Should NOT include the table data or appendix content
        assert "Relation # Samples" not in bibliography_text
        assert "company hq 674" not in bibliography_text
        assert "A LRE Dataset" not in bibliography_text
        assert "We construct our experimental prompts" not in bibliography_text
        assert "commonsense and factual data" not in bibliography_text
        assert "47 relations with over 10,000 instances" not in bibliography_text
        
        # Verify bibliography ends at the proper boundary (just after the last reference)
        assert bibliography_text.strip().endswith("arXiv:2407.03779.")
    
    def test_acronym_appendix_patterns(self):
        """Test that bibliography correctly handles appendix sections starting with acronyms"""
        # Test various acronym-based appendix patterns that could be problematic
        acronym_patterns = [
            "A LRE Dataset",
            "B CNN Architecture", 
            "C GPU Configuration",
            "D API Documentation",
            "E NLP Preprocessing",
            "F SQL Queries",
            "G XML Schemas"
        ]
        
        for pattern in acronym_patterns:
            sample_text = f"""
            References
            [1] First Author, "Deep learning approaches to natural language processing",
                Journal of Artificial Intelligence, vol. 30, no. 2, pp. 145-167, 2023.
            [2] Second Author, "Statistical methods for machine learning evaluation", 
                Proceedings of ICML Conference, pp. 234-251, 2022.
            [3] Third Author, "Advanced neural network architectures for computer vision",
                IEEE Transactions on Pattern Analysis and Machine Intelligence, vol. 45, pp. 678-695, 2024.
            
            {pattern}
            This is detailed appendix content that describes technical implementation details
            and should not be included in the bibliography section of the paper.
            """
            
            bibliography_text = self.checker.find_bibliography_section(sample_text)
            
            # Should find bibliography but exclude appendix content
            assert bibliography_text is not None
            assert pattern not in bibliography_text, f"Bibliography incorrectly includes '{pattern}'"
            assert "This is detailed appendix content" not in bibliography_text
            assert "technical implementation details" not in bibliography_text
            
            # Should include all references
            assert "[1] First Author" in bibliography_text
            assert "[2] Second Author" in bibliography_text  


# ── Regression tests for specific ICLR 2026 papers ──

MULTI_PAGE_REFS = (
    "E. Abbe, J. Fan, and K. Wang. An theory of pca and spectral clustering. "
    "The Annals of Statistics, 50(4):2359, 2022.\n"
    "Z. Allen-Zhu and L. Silvio. A local algorithm for finding well-connected clusters. "
    "In ICML, pp. 396-404, 2017.\n"
    "A. Baranwal, K. Fountoulakis, and A. Jagannath. Graph convolution for semi-supervised "
    "classification. In NeurIPS, 2021.\n"
    "J. Chen and X. Li. Stochastic gradient descent with momentum. "
    "Journal of Machine Learning Research, 23(1):1-45, 2022.\n"
    "Y. LeCun, Y. Bengio, and G. Hinton. Deep learning. Nature, 521:436-444, 2015.\n"
    "A. Vaswani, N. Shazeer, N. Parmar, J. Uszkoreit, L. Jones, A. Gomez, L. Kaiser, "
    "and I. Polosukhin. Attention is all you need. In NeurIPS, 2017.\n"
    "K. He, X. Zhang, S. Ren, and J. Sun. Deep residual learning for image recognition. "
    "In CVPR, pp. 770-778, 2016.\n"
    "I. Goodfellow, J. Pouget-Abadie, M. Mirza, B. Xu, D. Warde-Farley, S. Ozair, "
    "A. Courville, and Y. Bengio. Generative adversarial nets. In NeurIPS, 2014.\n"
)


class TestBibliographyEndDetectionRegression:
    """Regression tests for bibliography end detection on real paper patterns."""

    def setup_method(self):
        self.checker = ArxivReferenceChecker()

    def _build(self, refs, after, header="References\n"):
        return "Title\n\nAbstract.\n\n1 Introduction\nText.\n\n" + header + refs + "\n" + after

    def test_appendix_with_contents_toc(self):
        """Regression for n28wnc2QTc: Appendix + CONTENTS block should end bibliography."""
        text = self._build(
            MULTI_PAGE_REFS,
            "17\nPublished as a conference paper at ICLR 2026\n"
            "Appendix\nCONTENTS\nA1 Extended Related Work 19\n"
            "A1.1 Retrieval-Augmented Generation.\nSome appendix text."
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Appendix" not in bib
        assert "CONTENTS" not in bib
        assert "Extended Related Work" not in bib
        assert "Vaswani" in bib

    def test_contents_section_after_page_break(self):
        """Regression for T1h5em349L: CONTENTS after page break should end bibliography."""
        text = self._build(
            MULTI_PAGE_REFS,
            "15\nPublished as a conference paper at ICLR 2026\n"
            "CONTENTS\n1 Introduction 1\n2 Methods 3\n"
            "A LLM Usage Declaration 18\nB Discussion 18"
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "CONTENTS" not in bib
        assert "LLM Usage Declaration" not in bib
        assert "Vaswani" in bib

    def test_appendixcontents_no_space(self):
        """Regression for FRkJ3ehpNN: APPENDIXCONTENTS (no space) should end bibliography."""
        text = self._build(
            MULTI_PAGE_REFS,
            "APPENDIXCONTENTS\nA Literature Review\nB Experimental Setup"
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "APPENDIXCONTENTS" not in bib
        assert "Literature Review" not in bib

    def test_page_breaks_within_bibliography_preserved(self):
        """Page breaks mid-bibliography must NOT truncate references.

        Regression: "\n11\nPublished as a conference paper at ICLR 2026\n"
        appearing between reference entries was cutting off 85% of references.
        """
        page1_refs = (
            "E. Abbe. Theory of PCA. Annals of Statistics, 2022.\n"
            "Z. Allen-Zhu. A local algorithm. In ICML, 2017.\n"
        )
        page_break = "11\nPublished as a conference paper at ICLR 2026\n"
        page2_refs = (
            "K. He. Deep residual learning. In CVPR, 2016.\n"
            "A. Vaswani. Attention is all you need. In NeurIPS, 2017.\n"
        )
        appendix = "Appendix\nA Extended Related Work\nSome discussion."

        text = self._build(page1_refs + page_break + page2_refs, appendix)
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Abbe" in bib
        assert "Vaswani" in bib
        assert "Extended Related Work" not in bib

    def test_author_starting_with_single_letter_not_truncated(self):
        """Author names like 'A. Baranwal' must NOT be mistaken for appendix headers."""
        refs_with_a_author = (
            "A. Baranwal, K. Fountoulakis, and A. Jagannath. Graph convolution for "
            "semi-supervised classification. In NeurIPS, 2021.\n"
            "B. Smith and C. Jones. Another paper. In ICML, 2022.\n"
            "D. Wilson. Yet another paper. In AAAI, 2023.\n"
        )
        text = self._build(
            refs_with_a_author,
            "Appendix\nA Proofs\nSome proof content."
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Baranwal" in bib
        assert "Smith" in bib
        assert "Wilson" in bib
        assert "Some proof content" not in bib

    def test_trailing_page_number_trimmed(self):
        """Bare page numbers at the end of bibliography should be trimmed."""
        text = self._build(
            MULTI_PAGE_REFS + "\n17\n",
            "Appendix\nA Some Section"
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        stripped = bib.rstrip()
        last_line = stripped.split('\n')[-1].strip()
        assert not last_line.isdigit(), f"Bibliography ends with bare page number: '{last_line}'"

    def test_pdf_word_break_appendix_header(self):
        """Regression for KR8viVTrX4: PDF word-break in appendix header.

        PDF extraction can break words like 'INTRODUCTORY' into
        'I NTRODUCTORY', producing appendix headers like
        'A I NTRODUCTORY MATERIAL'.  The end-detection must still
        recognise this as a section boundary and not include it
        (or subsequent appendix content) in the bibliography.
        """
        text = self._build(
            MULTI_PAGE_REFS,
            "16\nPublished as a conference paper at ICLR 2026\n"
            "A I NTRODUCTORY MATERIAL\n"
            "The main purpose of this appendix section is to provide further details.\n"
            "B C OMPUTATIONAL REDUCTIONS\n"
            "Further appendix content."
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Vaswani" in bib
        assert "NTRODUCTORY" not in bib
        assert "appendix section" not in bib
        assert "OMPUTATIONAL" not in bib

    def test_mixed_case_contents_toc(self):
        """Regression for vxq1OnaAMq: mixed-case 'Contents' should end bibliography."""
        text = self._build(
            MULTI_PAGE_REFS,
            "17\n"
            "Contents\n"
            "A Related Work on NN Feasibility 19\n"
            "B Gauge Mapping over General Convex Sets 19\n"
            "B.1 Handling Linear Equality Constraints . . . . . . . . . . 20\n"
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Vaswani" in bib
        assert "Contents" not in bib
        assert "Feasibility" not in bib

    def test_pdf_broken_appendix_word(self):
        """Regression for GVVNG2EMQv: 'APPENDIX' broken by PDF extraction.

        PDF extraction can split 'APPENDIX' into 'A PPENDIX', producing
        headers like 'B A PPENDIX : D ETAILED DERIVATION'.
        """
        text = self._build(
            MULTI_PAGE_REFS,
            "B A PPENDIX : D ETAILED DERIVATION AND PROOFS\n"
            "This appendix provides the full mathematical derivation.\n"
            "B.1 S TEP 1: K INEMATICS\n"
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Vaswani" in bib
        assert "PPENDIX" not in bib
        assert "mathematical derivation" not in bib

    def test_published_as_header_trimmed(self):
        """'Published as a conference paper' line should be trimmed from end."""
        text = self._build(
            MULTI_PAGE_REFS,
            "Published as a conference paper at ICLR 2026\n"
            "Appendix\nA Some Section"
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None

    def test_author_year_bibliography_not_body_text(self):
        """Regression for Ig6goVdtjb: author-year papers must not pick body text 'references'.

        When a paper uses author-year citations (no [1], [2] markers), the word
        "references" appears many times in body text (e.g. "see references therein").
        The extractor must find the actual REFERENCES section heading near the end,
        not a false positive from body text.
        """
        body_text = (
            "1 Introduction\n"
            "Recent work has made references to foundation models for robotics.\n"
            "We refer to prior references in the field of embodied AI (Wu et al. (2023)).\n"
            "\n"
            "2 Related Work\n"
            "Several references discuss reward learning from language preferences.\n"
            "\n"
            "3 Method\n"
            "Our method builds on references from reinforcement learning.\n"
        )
        bib_refs = (
            "Michael Ahn, Anthony Brohan, and Noah Brown. Do as i can, not as i say: "
            "Grounding language in robotic affordances, 2022.\n"
            "Jimmy Wu, Rika Antonova, Adam Kan, and Thomas Funkhouser. Tidybot: "
            "Personalized robot assistance with large language models. "
            "Autonomous Robots, 47(8):1087-1102, 2023a.\n"
            "Yufei Wang and David Held. Rl-vlm-f: Reinforcement learning from "
            "vision language foundation model feedback, 2024.\n"
        )
        text = body_text + "\nREFERENCES\n" + bib_refs

        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        # Must contain actual bibliography entries
        assert "Tidybot" in bib
        assert "Jimmy Wu" in bib
        assert "Michael Ahn" in bib
        # Must NOT contain body text
        assert "1 Introduction" not in bib
        assert "2 Related Work" not in bib
        assert "Our method builds on" not in bib
        assert "Published as a conference paper" not in bib

    def test_appendix_with_dotted_subsections(self):
        """Regression for l9mqzHROGu: appendix subsections like A.1 should end bibliography.

        Some papers use "A.1 RELATED WORK", "A.2 DETAILS OF THE BASELINES" etc.
        as appendix headings, preceded by a standalone "A" line. The extractor
        must stop before these.
        """
        refs = (
            "Sara Abdali and Jia He. Detecting ai text. In KDD, pp. 6428, 2024.\n"
            "Xianjun Yang and Haifeng Chen. DNA-GPT: Divergent n-gram analysis. "
            "In ICLR, 2024.\n"
        )
        appendix = (
            "14\n"
            "Published as a conference paper at ICLR 2026\n"
            "A\n"
            "A.1 RELATED WORK\n"
            "Machine Text Generation. Modern large language models are predominantly\n"
            "autoregressive Transformers trained with next-token prediction.\n"
            "A.2 DETAILS OF THE BASELINES\n"
            "DetectGPT uses random perturbations to detect machine text.\n"
        )
        text = self._build(refs, appendix, header="REFERENCES\n")

        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Sara Abdali" in bib
        assert "DNA-GPT" in bib
        # Appendix content must NOT be included
        assert "A.1 RELATED WORK" not in bib
        assert "Machine Text Generation" not in bib
        assert "DETAILS OF THE BASELINES" not in bib

    def test_spaced_out_appendix_marker(self):
        """Regression for 9ZogcRkhoG: fully spaced 'AP P E N D I X' from PDF extraction."""
        refs = MULTI_PAGE_REFS
        appendix = (
            "AP P E N D I X\n"
            "B D ETAILS OF THE EXPERIMENTS\n"
            "Here we provide additional experimental details.\n"
        )
        text = self._build(refs, appendix)
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Vaswani" in bib
        assert "AP P E N D I X" not in bib
        assert "EXPERIMENTS" not in bib

    def test_spaced_supplementary_material_marker(self):
        """Regression for 7dvYWzOiEu: letter-spaced supplementary heading."""
        refs = MULTI_PAGE_REFS
        for heading in (
            "S UPPLEMENTARY M ATERIAL : M ETA L EARNING T HEORY I NFORMED\n"
            "I NDUCTIVE B IASES USING D EEP K ERNEL G AUSSIAN P ROCESSES",
            "SUPPLEMENTARYMATERIAL: METALEARNINGTHEORYINFORMED\n"
            "INDUCTIVEBIASES USINGDEEPKERNELGAUSSIANPROCESSES",
        ):
            appendix = (
                "15\n"
                "Published as a conference paper at ICLR 2026\n"
                f"{heading}\n"
                "S.A Extended Related Work . . . . . . . . . . . . . . . . . . . S2\n"
                "Our work is also related to Kobalczyk & van der Schaar (2025), "
                "whose informed neural process framework is discussed here.\n"
            )
            text = self._build(refs, appendix)
            bib = self.checker.find_bibliography_section(text)
            assert bib is not None
            assert "Vaswani" in bib
            assert "SUPPLEMENTARY" not in bib.replace(" ", "")
            assert "informed neural process" not in bib

    def test_reviewer_scores_marker_ends_embedded_references(self):
        """Regression for Fllp8l6Puy: reviewer-score blocks after references are not bibliography."""
        refs = (
            "Josh Achiam, Steven Adler, Sandhini Agarwal, Lama Ahmad, Ilge Akkaya, "
            "Florencia Leoni Aleman, Diogo Almeida, Janko Altenschmidt, Sam Altman, "
            "Shyamal Anadkat, et al. 2023. Gpt-4 technical report. arXiv preprint arXiv:2303.08774.\n"
            "Abhimanyu Dubey, Abhinav Jauhri, Abhinav Pandey, Abhishek Kadian, Ahmad Al-Dahle, "
            "Aiesha Letman, Akhil Mathur, Alan Schelten, Amy Yang, Angela Fan, et al. 2024. "
            "The llama 3 herd of models. arXiv preprint arXiv:2407.21783.\n"
            "Lianmin Zheng, Wei-Lin Chiang, Ying Sheng, Siyuan Zhuang, Zhanghao Wu, "
            "Yonghao Zhuang, Zi Lin, Zhuohan Li, Dacheng Li, Eric Xing, et al. 2024. "
            "Judging llm-as-a-judge with mt-bench and chatbot arena. Advances in Neural "
            "Information Processing Systems, 36.\n"
        )
        after = (
            "Published as a conference paper at ICLR 2026\n"
            "Reviewer Scores:\n"
            "From Ideation Study:\n"
            "Novelty: 5.5\n"
            "Title: Adaptive Contextual Pruning: Improving Relevance and Conciseness in Long-Form Generation\n"
            "Chang et al. (2024), technical documentation generation (Dvivedi et al., 2024), "
            "and retrieval-augmented generation appear in the reproduced idea text.\n"
        )
        text = self._build(refs, after)
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Josh Achiam" in bib
        assert "Judging llm-as-a-judge" in bib
        assert "Reviewer Scores" not in bib
        assert "Adaptive Contextual Pruning" not in bib
        assert "retrieval-augmented generation" not in bib

    def test_algorithm_header_ends_bibliography(self):
        """Regression for EOV1q1U23N: 'Algorithm 3 ...' should end bibliography."""
        refs = MULTI_PAGE_REFS
        appendix = (
            "Algorithm 3 Discounted Regret Matching\n"
            "Input: Action set A, discount factor gamma\n"
            "Initialize cumulative regret R_a = 0 for all a in A\n"
        )
        text = self._build(refs, appendix)
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Vaswani" in bib
        assert "Algorithm 3" not in bib
        assert "discount factor" not in bib

    def test_theorem_header_ends_bibliography(self):
        """Regression for Iw0tMeLed8: 'Theorem 1.' in appendix should end bibliography."""
        refs = MULTI_PAGE_REFS
        appendix = (
            "Theorem 1. Fix a time horizon T >= 4. Let the confidence level\n"
            "satisfy delta in (0, 1/e). Then with probability at least 1 - delta\n"
        )
        text = self._build(refs, appendix)
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Vaswani" in bib
        assert "Theorem 1" not in bib
        assert "time horizon" not in bib

    def test_fallback_path_applies_end_detection(self):
        """Regression for 9ZogcRkhoG: fallback regex path must also trim at end markers.

        When no References header is found, the fallback grabs from the first
        reference-like indicator. It must still stop at definitive end markers
        like APPENDIX rather than running to end of document.
        """
        # No explicit "References" header — simulate paper with no section title
        body = (
            "1 Introduction\n"
            "This paper studies neural networks.\n"
            "Smith, J. showed improved results (2020).\n"
            "2 Method\n"
            "We follow Jones, K. (2021).\n"
        )
        refs = (
            "Smith, J. Neural network advances. Nature, 2020.\n"
            "Jones, K. Deep learning methods. ICML, 2021.\n"
            "Brown, A. and White, B. Optimization theory. NeurIPS, 2022.\n"
        )
        appendix = (
            "Appendix\n"
            "A Proofs\n"
            "Here we provide the full derivation.\n"
        )
        # No "References" header — concatenate directly
        text = body + refs + appendix
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        # Must NOT include appendix
        assert "Proofs" not in bib


# ── Regression tests for ICLR papers with spaced-out / ALL CAPS appendix headers ──

class TestICLRAppendixOverrun:
    """Regression tests for bibliography overrun into appendix sections.

    These tests simulate real ICLR 2026 paper patterns where PDF text extraction
    produces spaced-out or all-caps appendix headers that were not being detected
    as end markers, causing bibliography extraction to include appendix content.
    """

    def setup_method(self):
        self.checker = ArxivReferenceChecker()

    def _build(self, refs, after, header="REFERENCES\n"):
        return "Title\n\nAbstract.\n\n1 Introduction\nText.\n\n" + header + refs + "\n" + after

    # -- HL3TvE4Afm: spaced-out "A E XTENDED RELATED WORK" --

    def test_HL3TvE4Afm_spaced_extended_related_work(self):
        """Regression for HL3TvE4Afm: 'A E XTENDED RELATED WORK' with PDF word-break."""
        refs = (
            "E. Abbe, J. Fan, and K. Wang. An theory of pca. "
            "The Annals of Statistics, 50(4):2359, 2022.\n"
            "Z. Allen-Zhu and L. Silvio. A local algorithm. In ICML, pp. 396, 2017.\n"
            "A. Vaswani et al. Attention is all you need. In NeurIPS, 2017.\n"
            "K. He, X. Zhang, S. Ren, and J. Sun. Deep residual learning. In CVPR, 2016.\n"
        )
        appendix = (
            "11\n"
            "Published as a conference paper at ICLR 2026\n"
            "A E XTENDED RELATED WORK\n"
            "In this section we provide extended discussion of related work "
            "in the areas of optimization and neural network theory.\n"
            "B P ROOF OF THEOREM 3.1\n"
            "We present the full proof below.\n"
        )
        bib = self.checker.find_bibliography_section(self._build(refs, appendix))
        assert bib is not None
        assert "Vaswani" in bib
        assert "E XTENDED RELATED WORK" not in bib
        assert "optimization and neural network" not in bib
        assert "P ROOF" not in bib

    # -- wWxdT6LB2D: ALL CAPS "A RELATED WORK", "B PROOFS AND SUPPORTING RESULTS" --

    def test_wWxdT6LB2D_all_caps_related_work(self):
        """Regression for wWxdT6LB2D: ALL CAPS 'A RELATED WORK' appendix header."""
        refs = (
            "P. Alquier. User-friendly introduction to PAC-Bayes bounds, 2024.\n"
            "R. Amit and R. Meir. Meta-learning by adjusting priors. In NeurIPS, 2018.\n"
            "Y. Balaji et al. MetaReg: Towards domain generalization. In NeurIPS, 2018.\n"
            "M. Beitner and S. Huckemann. On the geometry of metric spaces. JFA, 2024.\n"
        )
        appendix = (
            "11\n"
            "Published as a conference paper at ICLR 2026\n"
            "A RELATED WORK\n"
            "Test-time training has attracted significant attention in recent years.\n"
            "B PROOFS AND SUPPORTING RESULTS\n"
            "We provide detailed proofs of our theoretical claims.\n"
        )
        bib = self.checker.find_bibliography_section(self._build(refs, appendix))
        assert bib is not None
        assert "Alquier" in bib
        assert "A RELATED WORK" not in bib
        assert "test-time training" not in bib.lower()
        assert "PROOFS AND SUPPORTING" not in bib

    # -- Iw0tMeLed8: "C PROOFS OF THE THEORETICAL RESULTS" --

    def test_Iw0tMeLed8_all_caps_proofs_of_theoretical(self):
        """Regression for Iw0tMeLed8: 'C PROOFS OF THE THEORETICAL RESULTS'."""
        refs = (
            "A. Angelopoulos et al. Prediction-powered inference. Science, 382:669, 2023.\n"
            "A. Angelopoulos et al. PPI++: When is prediction-powered inference worth it? 2023.\n"
            "L. Brown and T. Cai. Confidence intervals for a binomial proportion. SS, 2001.\n"
            "P. Groeneboom and J. Wellner. Information bounds. Birkhauser, 1992.\n"
        )
        appendix = (
            "10\n"
            "Published as a conference paper at ICLR 2026\n"
            "A E XPERIMENTS ON THE EFFECT OF THE MIXING PARAMETER\n"
            "We investigate the effect of the mixing parameter on coverage.\n"
            "B E XTENDED RELATED WORK\n"
            "Additional references on conformal prediction methods.\n"
            "C P ROOFS OF THE THEORETICAL RESULTS IN S ECTION 4\n"
            "Theorem 1. Fix a time horizon T >= 4.\n"
        )
        bib = self.checker.find_bibliography_section(self._build(refs, appendix))
        assert bib is not None
        assert "Angelopoulos" in bib
        assert "XPERIMENTS ON THE EFFECT" not in bib
        assert "mixing parameter" not in bib
        assert "P ROOFS" not in bib

    # -- EOV1q1U23N: "A FURTHER RELATED WORK" --

    def test_EOV1q1U23N_further_related_work(self):
        """Regression for EOV1q1U23N: 'A FURTHER RELATED WORK' with ALL CAPS."""
        refs = (
            "G. Brown and Y. Song. Regret matching for stochastic games. In ICML, 2024.\n"
            "M. Bowling et al. Heads-up limit hold'em poker is solved. Science, 2015.\n"
            "N. Brown and T. Sandholm. Superhuman AI for multiplayer poker. Science, 2019.\n"
            "L. Shapley. Stochastic games. PNAS, 39(10):1095-1100, 1953.\n"
        )
        appendix = (
            "11\n"
            "Published as a conference paper at ICLR 2026\n"
            "A FURTHER RELATED WORK\n"
            "We extend the discussion of related work on regret minimization "
            "by Hart and Mas-Colell 2000 and its connections to correlated equilibria.\n"
            "B FURTHER BACKGROUND\n"
            "Additional background on extensive-form games.\n"
            "C OMITTED PROOFS\n"
            "C.1 PROOFS FROM SECTION 3\n"
            "Proof of Theorem 3.1. Fix epsilon > 0.\n"
        )
        bib = self.checker.find_bibliography_section(self._build(refs, appendix))
        assert bib is not None
        assert "Shapley" in bib
        assert "FURTHER RELATED WORK" not in bib
        assert "regret minimization" not in bib
        assert "OMITTED PROOFS" not in bib

    # -- WjEAMyLDoh: numbered "7 APPENDIX A", "9 APPENDIX C: DERIVATION" --

    def test_WjEAMyLDoh_numbered_appendix_sections(self):
        """Regression for WjEAMyLDoh: numbered appendix sections without period."""
        refs = (
            "C. Szepesvari. Algorithms for reinforcement learning. MC, 2010.\n"
            "R. Sutton and A. Barto. Reinforcement learning. MIT Press, 2018.\n"
            "J. Tsitsiklis and B. Van Roy. Analysis of TD-learning. ML, 1997.\n"
            "C. Watkins and P. Dayan. Q-learning. Machine Learning, 8:279-292, 1992.\n"
        )
        appendix = (
            "11\n"
            "Published as a conference paper at ICLR 2026\n"
            "7 APPENDIX A\n"
            "Here we present additional proofs.\n"
            "8 APPENDIX B: DISCUSSION ON STRONG APPROXIMATION OF Q-LEARNING\n"
            "We provide analysis of the convergence rate.\n"
            "9 APPENDIX C: DERIVATION OF ASSUMPTION 3.2\n"
            "Starting from the definition...\n"
            "10 ADDITIONAL EXPERIMENTS\n"
            "We report additional experimental results.\n"
        )
        bib = self.checker.find_bibliography_section(self._build(refs, appendix))
        assert bib is not None
        assert "Watkins" in bib
        assert "APPENDIX A" not in bib
        assert "additional proofs" not in bib
        assert "APPENDIX B" not in bib
        assert "ADDITIONAL EXPERIMENTS" not in bib

    def test_WjEAMyLDoh_pdf_wordbreak_numbered_appendix(self):
        """Regression for WjEAMyLDoh: numbered appendix with PDF word-break 'A PPENDIX'."""
        refs = (
            "C. Szepesvari. Algorithms for reinforcement learning. MC, 2010.\n"
            "R. Sutton and A. Barto. Reinforcement learning. MIT Press, 2018.\n"
            "J. Tsitsiklis and B. Van Roy. Analysis of TD-learning. ML, 1997.\n"
        )
        appendix = (
            "7 A PPENDIX A\n"
            "Here we present additional proofs.\n"
            "8 A PPENDIX B: D ISCUSSION ON S TRONG APPROXIMATION\n"
            "Analysis of convergence.\n"
        )
        bib = self.checker.find_bibliography_section(self._build(refs, appendix))
        assert bib is not None
        assert "Szepesvari" in bib
        assert "PPENDIX" not in bib
        assert "additional proofs" not in bib

    # -- vLFqOoMBol: mixed-case appendix headers --

    def test_vLFqOoMBol_comparison_appendix(self):
        """Regression for vLFqOoMBol: 'B Comparison to existing verification systems'."""
        refs = (
            "A. Blum et al. On-line algorithms in machine teaching. ML, 2020.\n"
            "A. Goldwasser and S. Micali. Probabilistic encryption. JCSS, 1984.\n"
            "S. Garg et al. Can neural network memorization be localized? In ICML, 2023.\n"
            "P. Kirchner. Forgery-resistant cryptographic attestation. In IEEE S&P, 2024.\n"
        )
        appendix = (
            "10\n"
            "Published as a conference paper at ICLR 2026\n"
            "A Centered logits also lie on an ellipse\n"
            "Lemma A.1. Let f be a classifier with centered logits.\n"
            "B Comparison to existing verification systems\n"
            "We compare our approach to C2PA and other systems.\n"
        )
        bib = self.checker.find_bibliography_section(self._build(refs, appendix))
        assert bib is not None
        assert "Kirchner" in bib
        assert "Comparison to existing" not in bib
        assert "C2PA" not in bib

    def test_vLFqOoMBol_centered_logits_appendix(self):
        """Regression for vLFqOoMBol: 'A Centered logits also lie on an ellipse'.

        This appendix header starts with a single uppercase letter followed by
        a Capitalized word + lowercase words. The keyword 'Centered' is matched.
        """
        refs = (
            "A. Goldwasser and S. Micali. Probabilistic encryption. JCSS, 1984.\n"
            "S. Garg et al. Can neural network memorization be localized? ICML, 2023.\n"
            "P. Kirchner. Forgery-resistant attestation. In IEEE S&P, 2024.\n"
        )
        appendix = (
            "A Centered logits also lie on an ellipse\n"
            "Lemma A.1. Let f be a classifier with K classes.\n"
        )
        bib = self.checker.find_bibliography_section(self._build(refs, appendix))
        assert bib is not None
        assert "Kirchner" in bib
        assert "Centered logits" not in bib
        assert "Lemma A.1" not in bib

    # -- 9ZogcRkhoG: fallback start detection picks up body text --

    def test_9ZogcRkhoG_fallback_prefers_late_matches(self):
        """Regression for 9ZogcRkhoG: fallback regex must prefer matches in last 50%.

        When no References header is found, the fallback uses indicator patterns
        like '\\d+.\\s+[A-Z]'. Body text with numbered lists can match this early
        in the document. The fix prefers matches in the last 50% of the document.
        """
        body_early = (
            "1. Introduction\n"
            "This paper studies protein ML models.\n"
            "2. Related Work\n"
            "Prior work includes several approaches.\n"
            "3. Methods\n"
            "We propose a novel framework.\n"
            "4. Results\n"
            "Our experiments show improvements.\n"
            "5. Discussion\n"
            "We discuss the implications of our results.\n"
        )
        # Pad to ensure body is > 50% of document
        body_padding = "Additional body text. " * 100 + "\n"
        refs = (
            "Baranwal, A., Fountoulakis, K., and Jagannath, A. Graph convolution for "
            "semi-supervised classification. In NeurIPS, 2021.\n"
            "Chen, J. and Li, X. Stochastic gradient descent with momentum. "
            "JMLR, 23(1):1-45, 2022.\n"
            "LeCun, Y., Bengio, Y., and Hinton, G. Deep learning. Nature, 521:436, 2015.\n"
            "Vaswani, A. et al. Attention is all you need. In NeurIPS, 2017.\n"
        )
        appendix = (
            "Appendix\n"
            "A Summary of experiments\n"
            "We summarize our experimental configurations.\n"
        )
        # No "References" header — body + refs + appendix
        text = body_early + body_padding + refs + appendix
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        # Must contain actual references (from the late section)
        assert "Vaswani" in bib
        assert "LeCun" in bib
        # Must NOT contain body text
        assert "1. Introduction" not in bib
        assert "This paper studies" not in bib
        # Must NOT contain appendix
        assert "Summary of experiments" not in bib

    # -- General: ALL CAPS keywords should be detected --

    def test_all_caps_keywords_detected(self):
        """Test that ALL CAPS appendix keywords are correctly detected."""
        keywords_to_test = [
            ("A EXTENDED RELATED WORK", "extended discussion"),
            ("A ADDITIONAL EXPERIMENTS", "more experiments"),
            ("B FURTHER ANALYSIS", "deeper analysis"),
            ("A SUPPLEMENTARY MATERIAL", "extra material"),
            ("B BACKGROUND ON METHODS", "method background"),
            ("A RELATED WORK", "related work discussion"),
            ("A SUMMARY OF RESULTS", "results summary"),
        ]
        for header, content in keywords_to_test:
            refs = MULTI_PAGE_REFS
            appendix = f"{header}\n{content.capitalize()} here.\n"
            text = self._build(refs, appendix)
            bib = self.checker.find_bibliography_section(text)
            assert bib is not None, f"No bib found for appendix header: {header}"
            assert header not in bib, f"Bib should not include appendix header: {header}"
            assert content not in bib.lower(), f"Bib should not include content after: {header}"
            assert "Vaswani" in bib, f"Bib should include refs before: {header}"

    def test_QcRto0GjxC_concatenated_appendix_with_parenthetical(self):
        """Regression for QcRto0GjxC: 'A QUANTUMRANDOMACCESSMEMORY(QRAM)'.

        PDF extraction can collapse multi-word all-caps appendix headings and
        leave a parenthetical acronym attached. The bibliography must stop
        before that appendix rather than feeding proofs/lemmas to LLM extraction.
        """
        refs = (
            "Todd Tilma and E. C. G. Sudarshan. Generalized euler angle parametrization "
            "for su(n). Journal of Physics A, 35:10467-10501, 2002.\n"
            "Joel A. Tropp. Improved analysis of the subsampled randomized hadamard "
            "transform. Advances in Adaptive Data Analysis, 3(1-2):115-126, 2011.\n"
            "Chao-Yang Wang, Lexing Ying, and Di Fang. Quantum algorithm for nonlinear "
            "dynamics. SIAM Journal on Scientific Computing, 47(2):A883-A905, 2025.\n"
            "Kianna Wan, Mario Berta, and Earl Campbell. Randomized quantum algorithm "
            "for statistical phase estimation. Physical Review Letters, 2022.\n"
        )
        appendix = (
            "20\n"
            "Published as a conference paper at ICLR 2026\n"
            "TECHNICALAPPENDICES ANDSUPPLEMENTARYMATERIAL\n"
            "In Appendix A we present a summary of Quantum Random Access Memory (QRAM), "
            "which we subsequently use. In Appendix B we present techniques.\n"
            "A QUANTUMRANDOMACCESSMEMORY(QRAM)\n"
            "In this section, we will formally define QRAM, and state the assumed complexities.\n"
            "B QUANTUMMATRIX-VECTORARITHMETIC\n"
            "Lemma B.1(Product of block encodings). If U is a block-encoding...\n"
        )
        text = self._build(refs, appendix)
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Todd Tilma" in bib
        assert "Kianna Wan" in bib
        assert "TECHNICALAPPENDICES" not in bib
        assert "In Appendix A we present" not in bib
        assert "QUANTUMRANDOMACCESSMEMORY" not in bib
        assert "formally define QRAM" not in bib
        assert "Lemma B.1" not in bib

    def test_owZ6KNAtYU_spaced_appendix_with_continued_parenthetical(self):
        """Regression for owZ6KNAtYU: 'A E XPERIMENTAL S ETTINGS (C ONT ' D )'.

        PDF extraction can split all-caps appendix headings into alternating
        initials and word fragments, then preserve a parenthetical continuation
        marker. The bibliography must stop before the appendix table/list text.
        """
        refs = (
            "Yilun Zheng, Xiang Li, Sitao Luan, Xiaojiang Peng, and Lihui Chen. "
            "Let your features tell the differences: Understanding graph convolution "
            "by feature splitting. In ICLR, 2025.\n"
            "Jiong Zhu, Yujun Yan, Lingxiao Zhao, Mark Heimann, Leman Akoglu, "
            "and Danai Koutra. Beyond homophily in graph neural networks: Current "
            "limitations and effective designs. In NeurIPS, 2020.\n"
            "Jiaru Zou, Xiyuan Yang, Ruizhong Qiu, Gaotang Li, Katherine Tieu, "
            "Pan Lu, Ke Shen, Hanghang Tong, Yejin Choi, Jingrui He, James Zou, "
            "Mengdi Wang, and Ling Yang. Latent collaboration in multi-agent systems. "
            "arXiv preprint, 2025b.\n"
        )
        appendix = (
            "19\n"
            "Published as a conference paper at ICLR 2026\n"
            "A     E XPERIMENTAL S ETTINGS (C ONT ' D )\n"
            "A.1   DATASETS (C ONT ' D )\n"
            "For heterophilic group, we consider the following datasets.\n"
            "APPNP (Gasteiger et al., 2019): Combines personalized PageRank "
            "with neural propagation.\n"
            "We train the GNN using the Adam optimizer (Kingma & Ba, 2014).\n"
        )
        text = self._build(refs, appendix)
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Yilun Zheng" in bib
        assert "Latent collaboration" in bib
        assert "E XPERIMENTAL S ETTINGS" not in bib
        assert "DATASETS" not in bib
        assert "Combines personalized PageRank" not in bib
        assert "Adam optimizer" not in bib

    def test_pypdf_references_heading_with_trailing_line_number(self):
        """pypdf can append source line numbers to section headings.

        A heading like ``References287`` must be treated as the real references
        section rather than falling back to an earlier body citation such as
        ``[2025]``.
        """
        text = """
        Related work162
        Prior work discusses online self-play [2025] and moving targets.163
        More body text before the bibliography.164
        8
        References287
        Andy Arditi, Oscar Obeso, Aaquib Syed, Daniel Paleka, Nina Panickssery,
        Wes Gurnee, and Neel Nanda. Refusal in language models is mediated by a
        single direction, 2024. URL https://arxiv.org/abs/2406.11717.290
        Alex Beutel, Kai Xiao, Johannes Heidecke, and Lilian Weng. Diverse and
        effective red teaming with auto-generated rewards and multi-step
        reinforcement learning, 2024. URL https://arxiv.org/abs/2412.18693.293
        Daya Guo, Dejian Yang, Haowei Zhang, Junxiao Song, and many collaborators.
        Deepseek-r1 incentivizes reasoning in llms through reinforcement learning.
        Nature, 645(8081):633-638, September 2025. doi: 10.1038/s41586-025-09422-z.
        URL http://dx.doi.org/10.1038/s41586-025-09422-z.321
        S. S. Li, Shuang Zhou, Shaoqing Wu, Tao Yun, Tian Pei, Tianyu Sun,
        T. Wang, Wangding Zeng, and Wen Liu. Continuation of the same long
        author list should not be mistaken for an appendix heading.322
        Seungju Han, Kavel Rao, Allyson Ettinger, Liwei Jiang, Bill Yuchen Lin,
        Nathan Lambert, Yejin Choi, and Nouha Dziri. Wildguard: Open one-stop
        moderation tools for safety risks, jailbreaks, and refusals of llms,
        2024. URL https://arxiv.org/abs/2406.18495.365
        11
        A Reward function details425
        This appendix content should not be included.
        """

        bib = self.checker.find_bibliography_section(text)

        assert bib is not None
        assert "Prior work discusses online self-play" not in bib
        assert "Andy Arditi" in bib
        assert "Deepseek-r1 incentivizes" in bib
        assert "S. S. Li" in bib
        assert "Wildguard" in bib
        assert "Reward function details" not in bib
        assert "appendix content" not in bib

    def test_dotted_appendix_detection_does_not_truncate_multi_initial_authors(self):
        """Generic dotted appendix headings must not match author initials.

        This protects against regressions where a boundary rule for headings like
        ``B. S6 Parameterization`` treats ``S. S. Li, ...`` inside a long author
        list as the start of an appendix and drops all later references.
        """
        text = """
        References
        Daya Guo, Dejian Yang, Haowei Zhang, Junxiao Song, Peiyi Wang,
        R. J. Chen, R. L. Jin, Ruyi Chen, Shanghao Lu, Shangyan Zhou,
        S. S. Li, Shuang Zhou, Shaoqing Wu, Tao Yun, Tian Pei, Tianyu Sun,
        T. Wang, Wangding Zeng, Wen Liu, and Zhen Zhang. Deepseek-r1 incentivizes
        reasoning in llms through reinforcement learning. Nature, 645(8081):633-638,
        September 2025. doi: 10.1038/s41586-025-09422-z.
        Seungju Han, Kavel Rao, Allyson Ettinger, Liwei Jiang, Bill Yuchen Lin,
        Nathan Lambert, Yejin Choi, and Nouha Dziri. Wildguard: Open one-stop
        moderation tools for safety risks, jailbreaks, and refusals of llms,
        2024. URL https://arxiv.org/abs/2406.18495.

        B Training hyperparameters
        Appendix content starts here.
        """

        bib = self.checker.find_bibliography_section(text)

        assert bib is not None
        assert "S. S. Li" in bib
        assert "T. Wang" in bib
        assert "Wildguard" in bib
        assert "Training hyperparameters" not in bib
        assert "Appendix content starts here" not in bib

    def test_looks_like_ref_validation_not_too_broad(self):
        """Test that looks_like_ref doesn't reject valid appendix headers.

        When appendix content after the header mentions years (e.g., citing
        prior work like 'Smith 2020'), the validator must NOT treat this as
        a reference entry and reject the header.
        """
        refs = MULTI_PAGE_REFS
        appendix = (
            "A FURTHER RELATED WORK\n"
            "Recent advances in deep learning, following the seminal work "
            "of LeCun 2015 and Goodfellow 2014, have led to significant progress "
            "in computer vision and natural language processing.\n"
        )
        text = self._build(refs, appendix)
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "FURTHER RELATED WORK" not in bib
        assert "seminal work" not in bib

    def test_page_breaks_mid_references_not_split(self):
        """Page breaks within the reference section must not truncate bibliography.

        ICLR papers have page numbers and 'Published as a conference paper'
        headers mid-references. These must be treated as part of the references.
        """
        refs_page1 = (
            "E. Abbe. Theory of PCA. Annals of Statistics, 2022.\n"
            "Z. Allen-Zhu. Local algorithm. In ICML, 2017.\n"
        )
        page_break = "11\nPublished as a conference paper at ICLR 2026\n"
        refs_page2 = (
            "K. He. Deep residual learning. In CVPR, 2016.\n"
            "A. Vaswani. Attention is all you need. In NeurIPS, 2017.\n"
        )
        appendix = (
            "13\n"
            "Published as a conference paper at ICLR 2026\n"
            "A EXTENDED RELATED WORK\n"
            "Here we discuss additional related work.\n"
        )
        text = self._build(refs_page1 + page_break + refs_page2, appendix)
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Abbe" in bib
        assert "Vaswani" in bib
        assert "EXTENDED RELATED WORK" not in bib

    def test_WZYxJhvAvD_mixed_case_appendix_with_lowercase_words(self):
        """Regression for WZYxJhvAvD: 'A Theoretical Arguments for Section 3'.

        Appendix headers containing lowercase connecting words ('for', 'of', 'the')
        and digits were not detected as end markers because the generic
        single-letter pattern required every word to be title-case or ALL CAPS.
        """
        refs = (
            "Arditi, A. & Chughtai, A. Refusal in language models is mediated by a single direction. "
            "arXiv preprint, 2024.\n"
            "Hong, S., Lee, J., & Kim, J. Probing concept representations in LLMs. "
            "In NeurIPS, 2024.\n"
            "Lucki, M. et al. An adversarial perspective on machine unlearning. "
            "In ICLR, 2024.\n"
            "Sun, T. et al. Evaluating machine unlearning methods. "
            "ACM Computing Surveys, 2025.\n"
        )
        appendix = (
            "16\n"
            "Preprint. Under review.\n"
            "A Theoretical Arguments for Section 3\n"
            "Proof of Theorem 3.1. Let z1,...,z n-1 be the calibration samples "
            "for a fixed direction, and let zn be a fresh in-distribution sample.\n"
            "B Algorithm Details\n"
            "We provide an illustration of our main algorithm in Figure 4.\n"
        )
        text = self._build(refs, appendix, header="References\n")
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        # Must include references
        assert "Arditi" in bib
        assert "Hong" in bib
        assert "Lucki" in bib
        assert "Sun" in bib
        # Must NOT include appendix content
        assert "A Theoretical Arguments" not in bib
        assert "Proof of Theorem" not in bib
        assert "calibration samples" not in bib
        assert "B Algorithm Details" not in bib

    def test_appendix_with_lowercase_connecting_words(self):
        """Appendix headers with lowercase prepositions must end bibliography.

        Patterns like 'A Proof of Theorem 4.2', 'B Analysis on the Effect',
        'C Bounds for k = 5' contain lowercase words and digits that the
        generic pattern must handle.
        """
        test_cases = [
            "A Proof of Theorem 4",
            "B Analysis on the Effect",
            "C Bounds for Large Networks",
            "D Details of the Experimental Setup",
            "E Convergence in the Limit",
        ]
        for header in test_cases:
            refs = MULTI_PAGE_REFS
            appendix = (
                f"{header}\n"
                "This is appendix content that should not be in bibliography.\n"
            )
            text = self._build(refs, appendix)
            bib = self.checker.find_bibliography_section(text)
            assert bib is not None, f"No bibliography found for appendix header: {header}"
            assert header not in bib, f"Bibliography includes appendix header: {header}"
            assert "appendix content" not in bib
            assert "Vaswani" in bib
        assert "full derivation" not in bib

class TestTitleCaseLetteredAppendix:
    """Regression tests for Title-case lettered appendix headings.

    Pattern: "A. Additional Related Work", "B. Additional Experimental Results"
    where a single capital letter + period + space + title-case heading marks
    the start of an appendix that was previously not detected.
    """

    def setup_method(self):
        self.checker = ArxivReferenceChecker()

    def test_paper_6XQOarhYF8_additional_related_work(self):
        """Regression for ICML 2025 paper 6XQOarhYF8: 'A. Additional Related Work'."""
        text = (
            "Title\n\nAbstract.\n\n1 Introduction\nBody.\n\n"
            "References\n"
            "Z. Zhang, Y. Li, and S. Wang. Near-optimal online learning. "
            "In ICLR, 2025.\n"
            "P. Zhao and L. Lai. Distributed online algorithms. JMLR, 2024.\n"
            "Q. Zhou, R. Smith, and T. Brown. Continuous optimization. "
            "In NeurIPS, 2023.\n"
            "Y. Zhu, X. Chen, and W. Liu. Submodular bandits. "
            "Operations Research, 2024.\n"
            "\n"
            "A. Additional Related Work\n"
            "Submodular maximization has been studied extensively under "
            "diverse settings (Chen and Yu, 2024; Anonymous, 2205.00000).\n"
            "B. Additional Experimental Results\n"
            "We report runtime numbers in Table 5.\n"
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        # Final true references must be retained
        assert "Near-optimal online learning" in bib
        assert "Y. Zhu" in bib
        # Appendix content must be excluded
        assert "A. Additional Related Work" not in bib
        assert "Submodular maximization has been studied" not in bib
        assert "B. Additional Experimental Results" not in bib

    def test_lettered_dotted_appendix_variants(self):
        """Title-case 'X. <Keyword>' headings end the bibliography."""
        cases = [
            "A. Additional Related Work",
            "B. Additional Experimental Results",
            "C. Implementation Details",
            "D. Proofs of Main Theorems",
            "E. Supplementary Discussion",
        ]
        for heading in cases:
            text = (
                "References\n"
                "Smith, J. and Doe, A. A useful paper title. "
                "Journal of Things, 2024.\n"
                "Brown, T. Another paper. ICML, 2023.\n"
                "Wilson, P. Yet another paper. NeurIPS, 2022.\n"
                "\n"
                f"{heading}\n"
                "Body of the appendix that must not be included.\n"
            )
            bib = self.checker.find_bibliography_section(text)
            assert bib is not None, heading
            assert heading not in bib, heading
            assert "Body of the appendix" not in bib
            assert "useful paper title" in bib

    def test_icml_lettered_dotted_appendix_headings(self):
        """ICML-style dotted appendix headings should end the bibliography.

        These headings appeared after references in ICML 2025 PDFs and caused
        appendix prose/tables to be sent to the LLM as bibliography text.
        """
        cases = [
            "A. Detailed Related Works",
            "A. LLM Details.",
            "B. Non-Transitivity in Preference",
            "A. Assumptions",
            "B. Estimation Details of the Dropout Propensity Model",
            "C. A Brief Introduction to B-Spline and Wavelet Basis Functions",
            "D. More on Simulations",
            "A. Data and link prediction methods",
            "B. AUC-ROC for the preferential attachment method",
            "D. Decomposition analysis of AUC-ROC scores",
            "A. Entropic estimation of OT maps",
            "A. Prior Work",
            "B. Justification of Section 4.2",
            "C. Defense Methods Configurations",
            "D. Surrogate Process of Gradient Computation",
            "E. Adaptive White-box PGD+EOT Attack for SSNI",
        ]
        refs = (
            "Smith, J. and Doe, A. A useful paper title. Journal of Things, 2024.\n"
            "Brown, T. Another paper. ICML, 2023.\n"
            "Wilson, P. Yet another paper for the regression suite. NeurIPS, 2022.\n"
        )
        for heading in cases:
            text = (
                "References\n"
                f"{refs}\n"
                f"{heading}\n"
                "This appendix prose cites Smith et al. (2024) and includes tables, proofs, and formulas.\n"
            )
            bib = self.checker.find_bibliography_section(text)
            assert bib is not None, heading
            assert "useful paper title" in bib, heading
            assert heading not in bib, heading
            assert "This appendix prose" not in bib, heading

    def test_fallback_path_stops_at_dotted_appendix_heading(self):
        """Fallback bibliography start detection must share dotted-heading end detection."""
        body = (
            "1 Introduction\n"
            "This paper contains numbered lists before the bibliography.\n"
            "1. First body item.\n"
            "2. Second body item.\n"
            "Additional body text. " * 80
        )
        refs = (
            "Smith, J. Neural network advances. Nature, 2020.\n"
            "Jones, K. Deep learning methods. ICML, 2021.\n"
            "Brown, A. and White, B. Optimization theory. NeurIPS, 2022.\n"
        )
        text = body + refs + "A. Prior Work\nThis appendix body must not be included.\n"

        bib = self.checker.find_bibliography_section(text)

        assert bib is not None
        assert "Optimization theory" in bib
        assert "A. Prior Work" not in bib
        assert "appendix body" not in bib

    def test_lettered_dotted_does_not_match_author_names(self):
        """Author lines like 'A. Baranwal' must NOT be treated as appendix headers."""
        text = (
            "References\n"
            "A. Baranwal, K. Fountoulakis, and A. Jagannath. Graph convolution. "
            "In NeurIPS, 2021.\n"
            "B. Smith and C. Jones. Another paper title here for testing. "
            "In ICML, 2022.\n"
            "D. Wilson. Yet another paper title for the regression suite. "
            "In AAAI, 2023.\n"
            "\n"
            "A. Additional Related Work\n"
            "This appendix discusses related literature in more depth.\n"
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Baranwal" in bib
        assert "Smith" in bib
        assert "Wilson" in bib
        assert "A. Additional Related Work" not in bib
        assert "discusses related literature" not in bib

    def test_wrapped_author_initial_with_heading_keyword_not_truncated(self):
        """Wrapped author initials can look like dotted appendix headings."""
        text = (
            "References\n"
            "Liao, F., Liang, M., Dong, Y., Pang, T., Hu, X., and Zhu,\n"
            "J. Defense-guided diffusion purification for adversarial robustness. ICML, 2023.\n"
            "Smith, J. and Doe, A. Another useful paper title. Journal of Things, 2024.\n"
            "\n"
            "A. Detailed Related Work\n"
            "This appendix discusses attacks and defenses in prose.\n"
        )

        bib = self.checker.find_bibliography_section(text)

        assert bib is not None
        assert "Defense-guided diffusion purification" in bib
        assert "Another useful paper title" in bib
        assert "A. Detailed Related Work" not in bib
        assert "appendix discusses" not in bib


class TestEndOfBibCaseInsensitive:
    """All keyword-driven end-of-bibliography heuristics should be case-insensitive.

    The same heading word can appear as APPENDIX, Appendix, or appendix in different
    PDFs. Casing must not affect detection.
    """

    def setup_method(self):
        self.checker = ArxivReferenceChecker()

    def _build(self, refs, after, header="References\n"):
        return "Title\n\nAbstract.\n\n1 Introduction\nText.\n\n" + header + refs + "\n" + after

    def test_lowercase_appendix_definitive(self):
        text = self._build(MULTI_PAGE_REFS, "appendix\nLowercase appendix body content here.\n")
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Vaswani" in bib
        assert "Lowercase appendix body" not in bib

    def test_lowercase_acknowledgments_definitive(self):
        text = self._build(MULTI_PAGE_REFS, "acknowledgments\nWe thank our colleagues.\n")
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Vaswani" in bib
        assert "We thank our colleagues" not in bib

    def test_lowercase_supplementary_material_definitive(self):
        text = self._build(MULTI_PAGE_REFS, "supplementary material\nExtra results below.\n")
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Vaswani" in bib
        assert "Extra results below" not in bib

    def test_lowercase_lettered_appendix_heuristic(self):
        # Same Title-case appendix heading but with all-lowercase keyword
        refs = (
            "Smith, J. and Doe, A. A useful paper title. Journal of Things, 2024.\n"
            "Brown, T. Another paper. ICML, 2023.\n"
            "Wilson, P. Yet another paper for the test suite. NeurIPS, 2022.\n"
        )
        text = "References\n" + refs + "\nA. additional related work\nThe appendix prose.\n"
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "useful paper title" in bib
        assert "A. additional related work" not in bib
        assert "The appendix prose" not in bib

    def test_uppercase_lettered_appendix_heuristic(self):
        refs = (
            "Smith, J. and Doe, A. A useful paper title. Journal of Things, 2024.\n"
            "Brown, T. Another paper. ICML, 2023.\n"
            "Wilson, P. Yet another paper for the test suite. NeurIPS, 2022.\n"
        )
        text = "References\n" + refs + "\nA. ADDITIONAL RELATED WORK\nThe appendix prose.\n"
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "useful paper title" in bib
        assert "A. ADDITIONAL RELATED WORK" not in bib
        assert "The appendix prose" not in bib
