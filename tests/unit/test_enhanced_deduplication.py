"""Tests for enhanced deduplication logic that handles chunk boundary issues"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import pytest
from unittest.mock import Mock, patch
from refchecker.core.refchecker import ArxivReferenceChecker


class TestEnhancedDeduplication:
    """Test enhanced deduplication with segment-based matching"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.checker = ArxivReferenceChecker()
    
    def test_exact_duplicate_detection(self):
        """Test that exact duplicates are properly detected"""
        references = [
            "Qiying Yu, Zheng Zhang, Ruofei Zhu # Dapo: An open-source llm reinforcement learning system at scale # arXiv preprint # 2025",
            "Qiying Yu, Zheng Zhang, Ruofei Zhu # Dapo: An open-source llm reinforcement learning system at scale # arXiv preprint # 2025"
        ]
        
        unique_refs = self.checker._deduplicate_references_with_segment_matching(references)
        
        # Should keep only one reference
        assert len(unique_refs) == 1
        assert unique_refs[0] == references[0]
    
    def test_chunk_boundary_duplicate_detection(self):
        """Test detection of duplicates caused by chunk boundary cuts in author lists"""
        references = [
            # Full author list
            "Qiying Yu, Zheng Zhang, Ruofei Zhu, Yufeng Yuan, Xiaochen Zuo, Yu Yue, Tiantian Fan, Gaohong Liu, Lingjun Liu, Xin Liu, Haibin Lin, Zhiqi Lin, Bole Ma, Guangming Sheng, Yuxuan Tong, Chi Zhang, Mofan Zhang, Wang Zhang, Hang Zhu, Jinhua Zhu, Jiaze Chen, Jiangjie Chen, Chengyi Wang, Hongli Yu, Weinan Dai, Yuxuan Song, Xiangpeng Wei, Hao Zhou, Jingjing Liu, Wei-Ying Ma, Ya-Qin Zhang, Lin Yan, Mu Qiao, Yonghui Wu, Mingxuan Wang # Dapo: An open-source llm reinforcement learning system at scale # arXiv preprint arXiv:2503.14476 # 2025",
            # Partial author list (chunk boundary cut off the beginning)
            "gjie Chen, Chengyi Wang, Hongli Yu, Weinan Dai, Yuxuan Song, Xiangpeng Wei, Hao Zhou, Jingjing Liu, Wei-Ying Ma, Ya-Qin Zhang, Lin Yan, Mu Qiao, Yonghui Wu, Mingxuan Wang # Dapo: An open-source llm reinforcement learning system at scale # arXiv preprint arXiv:2503.14476 # 2025"
        ]
        
        unique_refs = self.checker._deduplicate_references_with_segment_matching(references)
        
        # Should keep only one reference (the duplicate should be removed)
        assert len(unique_refs) == 1
        # Should keep the first one (full author list)
        assert "Qiying Yu" in unique_refs[0]
    
    def test_different_titles_not_duplicates(self):
        """Test that references with different titles are not considered duplicates"""
        references = [
            "Scott Fujimoto, David Meger, Doina Precup # Off-policy deep reinforcement learning without exploration # Proceedings of ICML # 2019",
            "Herman Kahn, Andy W Marshall # Methods of reducing sample size in monte carlo computations # Journal of Operations Research # 1953"
        ]
        
        unique_refs = self.checker._deduplicate_references_with_segment_matching(references)
        
        # Should keep both references
        assert len(unique_refs) == 2
    
    def test_same_title_different_authors_are_duplicates(self):
        """Test that references with same title but different authors are considered duplicates"""
        references = [
            "John Smith, Jane Doe # A Survey of Machine Learning # JMLR # 2020",
            "Different Author # A Survey of Machine Learning # JMLR # 2020"
        ]
        
        unique_refs = self.checker._deduplicate_references_with_segment_matching(references)
        
        # Should keep only one reference (duplicate titles)
        assert len(unique_refs) == 1
    
    def test_author_substring_matching(self):
        """Test that author substring matching works for chunk boundaries"""
        references = [
            # Full author list
            "Alice Johnson, Bob Smith, Carol Davis, David Wilson, Eve Brown # Test Paper # Test Venue # 2023",
            # Partial author list (substring of the full list)
            "Bob Smith, Carol Davis, David Wilson # Test Paper # Test Venue # 2023"
        ]
        
        unique_refs = self.checker._deduplicate_references_with_segment_matching(references)
        
        # Should be detected as duplicates
        assert len(unique_refs) == 1
    
    def test_author_overlap_threshold(self):
        """Test that author overlap threshold works correctly"""
        references = [
            # Authors: alice, bob, carol, david (4 names)
            "Alice Johnson, Bob Smith, Carol Davis, David Wilson # Test Paper # Test Venue # 2023",
            # Authors: bob, carol, eve, frank (4 names, 2 overlap = 50%)
            "Bob Smith, Carol Davis, Eve Brown, Frank Miller # Test Paper # Test Venue # 2023"
        ]
        
        unique_refs = self.checker._deduplicate_references_with_segment_matching(references)
        
        # Should be detected as duplicates due to 50% overlap (2/4 names match)
        assert len(unique_refs) == 1
    
    def test_same_title_always_duplicate(self):
        """Test that same titles are always considered duplicates regardless of authors"""
        references = [
            # Authors: alice, bob, carol, david (4 names)
            "Alice Johnson, Bob Smith, Carol Davis, David Wilson # Test Paper # Test Venue # 2023",
            # Authors: eve, frank, george, henry (4 names, 0 overlap)
            "Eve Brown, Frank Miller, George White, Henry Black # Test Paper # Test Venue # 2023"
        ]
        
        unique_refs = self.checker._deduplicate_references_with_segment_matching(references)
        
        # Should be considered duplicates because titles match (primary criterion)
        assert len(unique_refs) == 1
    
    def test_segment_parsing(self):
        """Test that reference segment parsing works correctly"""
        ref_str = "John Smith, Jane Doe # A Survey of ML # JMLR # 2020"
        
        segments = self.checker._parse_reference_segments(ref_str)
        
        assert segments['author'] == "john smith, jane doe"
        assert segments['title'] == "a survey of ml"
        assert segments['venue'] == "jmlr"
        assert segments['year'] == "2020"
    
    def test_incomplete_segments(self):
        """Test parsing of references with incomplete segments"""
        ref_str = "John Smith # A Survey of ML"  # Only author and title
        
        segments = self.checker._parse_reference_segments(ref_str)
        
        assert segments['author'] == "john smith"
        assert segments['title'] == "a survey of ml"
        assert segments['venue'] == ""
        assert segments['year'] == ""
    
    def test_real_world_dapo_example(self):
        """Test the actual Dapo reference example that was failing"""
        references = [
            # Simulated full author list from first chunk
            "Qiying Yu, Zheng Zhang, Ruofei Zhu, Yufeng Yuan, Xiaochen Zuo, Yu Yue, Tiantian Fan, Gaohong Liu, Lingjun Liu, Xin Liu, Haibin Lin, Zhiqi Lin, Bole Ma, Guangming Sheng, Yuxuan Tong, Chi Zhang, Mofan Zhang, Wang Zhang, Hang Zhu, Jinhua Zhu, Jiaze Chen, Jiangjie Chen, Chengyi Wang, Hongli Yu, Weinan Dai, Yuxuan Song, Xiangpeng Wei, Hao Zhou, Jingjing Liu, Wei-Ying Ma, Ya-Qin Zhang, Lin Yan, Mu Qiao, Yonghui Wu, Mingxuan Wang # Dapo: An open-source llm reinforcement learning system at scale # arXiv preprint arXiv:2503.14476 # 2025",
            # Simulated partial author list from second chunk (cut off beginning)
            "gjie Chen, Chengyi Wang, Hongli Yu, Weinan Dai, Yuxuan Song, Xiangpeng Wei, Hao Zhou, Jingjing Liu, Wei-Ying Ma, Ya-Qin Zhang, Lin Yan, Mu Qiao, Yonghui Wu, Mingxuan Wang # Dapo: An open-source llm reinforcement learning system at scale # arXiv preprint arXiv:2503.14476 # 2025"
        ]
        
        unique_refs = self.checker._deduplicate_references_with_segment_matching(references)
        
        # Should detect as duplicates and keep only one
        assert len(unique_refs) == 1
        
        # Should keep the first one (with full author list)
        kept_ref = unique_refs[0]
        assert "Qiying Yu" in kept_ref
        assert "Dapo: An open-source llm reinforcement learning system at scale" in kept_ref
    
    def test_case_insensitive_title_deduplication(self):
        """Regression test for case-insensitive title matching in deduplication
        
        Previously, "Awq:" and "AWQ:" were treated as different papers due to 
        case-sensitive comparison, causing duplicate references to appear.
        """
        # Create segments with same content but different title capitalization (AWQ example)
        seg1 = {
            'title': 'Awq: Activation-aware weight quantization for on-device llm compression and acceleration',
            'author': 'Ji Lin, Jiaming Tang, Haotian Tang, Shang Yang',
            'venue': 'Machine Learning and Systems',
            'year': '2024'
        }
        
        seg2 = {
            'title': 'AWQ: Activation-aware Weight Quantization for On-Device LLM Compression and Acceleration',
            'author': 'Ji Lin, Jiaming Tang, Haotian Tang, Shang Yang', 
            'venue': 'Machine Learning and Systems',
            'year': '2024'
        }
        
        # Should detect as duplicates despite different capitalization
        is_duplicate = self.checker._are_references_duplicates(seg1, seg2)
        assert is_duplicate, "Titles with different capitalization should be detected as duplicates"
    
    def test_case_insensitive_author_matching(self):
        """Test case-insensitive author comparison in duplicate detection"""
        # Same authors with different case, one title is substring of other
        seg1 = {
            'title': 'Neural Networks for NLP',
            'author': 'John Smith, Jane Doe',
            'venue': 'Conference',
            'year': '2024'
        }
        
        seg2 = {
            'title': 'Neural Networks for NLP: A Comprehensive Survey',
            'author': 'john smith, jane doe',  # Different case
            'venue': 'Conference',
            'year': '2024'
        }
        
        # Should detect as duplicates due to same authors (case-insensitive) and substring titles
        is_duplicate = self.checker._are_references_duplicates(seg1, seg2)
        assert is_duplicate, "References with same authors (different case) and substring titles should be duplicates"
    
    def test_bibliography_entry_deduplication(self):
        """Test case-insensitive deduplication of structured bibliography entries
        
        This tests the _deduplicate_bibliography_entries function which is applied
        to all bibliography sources (BibTeX, LaTeX, etc.) to remove duplicates like
        the AWQ paper appearing as both 'Awq:' and 'AWQ:' in the same bibliography.
        """
        bibliography = [
            {
                'title': 'Awq: Activation-aware weight quantization for on-device llm compression',
                'authors': ['Ji Lin', 'Jiaming Tang'],
                'venue': 'Machine Learning and Systems',
                'year': '2024'
            },
            {
                'title': 'Different Paper',
                'authors': ['Other Author'],
                'venue': 'Other Conference', 
                'year': '2023'
            },
            {
                # Same paper as first but different capitalization
                'title': 'AWQ: Activation-aware Weight Quantization for On-Device LLM Compression',
                'authors': ['Ji Lin', 'Jiaming Tang'],
                'venue': 'Machine Learning and Systems',
                'year': '2024'
            }
        ]
        
        deduplicated = self.checker._deduplicate_bibliography_entries(bibliography)
        
        # Should remove the duplicate (3 -> 2)
        assert len(deduplicated) == 2, f"Expected 2 unique references, got {len(deduplicated)}"
        
        # Should keep the first occurrence and the different paper
        titles = [ref['title'] for ref in deduplicated]
        assert any('Awq:' in title for title in titles), "Should keep first AWQ occurrence"
        assert any('Different Paper' in title for title in titles), "Should keep different paper"
        assert not any(title.startswith('AWQ:') for title in titles), "Should not keep duplicate AWQ"