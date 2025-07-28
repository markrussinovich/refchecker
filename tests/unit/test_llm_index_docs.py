
import os
import sys
import pytest
import importlib.util
script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts/llm_index_docs.py'))
spec = importlib.util.spec_from_file_location("llm_index_docs", script_path)
llm_index_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(llm_index_docs)
spec = importlib.util.spec_from_file_location("llm_index_docs", script_path)
llm_index_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(llm_index_docs)

def test_collect_markdown_docs(tmp_path):
    # Create sample markdown files
    file1 = tmp_path / "a.md"
    file2 = tmp_path / "b.md"
    file1.write_text("# Title A\nContent A")
    file2.write_text("# Title B\nContent B")
    docs = llm_index_docs.collect_markdown_docs(str(tmp_path))
    assert str(file1) in docs
    assert str(file2) in docs
    assert docs[str(file1)].startswith("# Title A")
    assert docs[str(file2)].startswith("# Title B")

def test_get_specification_text(tmp_path, monkeypatch):
    # Create dummy spec files
    readme = tmp_path / "README.md"
    copilot = tmp_path / ".github/copilot-instructions.md"
    readme.write_text("README content")
    copilot.parent.mkdir(parents=True, exist_ok=True)
    copilot.write_text("Copilot content")
    monkeypatch.chdir(tmp_path)
    spec = llm_index_docs.get_specification_text()
    assert "README content" in spec
    assert "Copilot content" in spec

def test_prompt_truncation(monkeypatch):
    # Test that the prompt is truncated to avoid context overflow
    docs = {f"doc{i}.md": "A" * 2000 for i in range(10)}
    spec = "S" * 5000
    api_key = "sk-test"
    # Patch openai client to not actually call LLM
    class DummyStream:
        def __iter__(self):
            return iter([])
    class DummyClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    # Check prompt length and number of docs
                    prompt = kwargs["messages"][0]["content"]
                    assert len(prompt) < 10000
                    assert prompt.count("---\n") <= 5
                    return DummyStream()
    monkeypatch.setattr(llm_index_docs, "openai", type("Dummy", (), {"OpenAI": lambda **kwargs: DummyClient(), "api_key": "sk-test"}))
    llm_index_docs.ask_llm_to_index(docs, spec, api_key)
