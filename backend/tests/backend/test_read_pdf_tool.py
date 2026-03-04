from __future__ import annotations

from pathlib import Path

from tools.base import ToolContext
from tools.read_pdf_tool import ReadPdfTool


def test_read_pdf_reports_missing_dependency(monkeypatch, tmp_path: Path):
    import tools.read_pdf_tool as module

    def _raise_missing(name: str):  # type: ignore[no-untyped-def]
        _ = name
        raise ModuleNotFoundError("pypdf")

    monkeypatch.setattr(module.importlib, "import_module", _raise_missing)

    target = tmp_path / "sample.pdf"
    target.write_bytes(b"%PDF-1.4\n%%EOF")
    tool = ReadPdfTool(root_dir=tmp_path)
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")

    result = tool.run({"path": "sample.pdf"}, context)
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_INTERNAL"
    assert "pypdf" in result.error.message


def test_read_pdf_extracts_selected_pages_with_fake_reader(monkeypatch, tmp_path: Path):
    import tools.read_pdf_tool as module

    class _FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _FakeReader:
        def __init__(self, path: str) -> None:
            _ = path
            self.pages = [_FakePage("one"), _FakePage("two")]

    class _FakePypdf:
        PdfReader = _FakeReader

    monkeypatch.setattr(module.importlib, "import_module", lambda _: _FakePypdf)

    target = tmp_path / "sample.pdf"
    target.write_bytes(b"%PDF-1.4\n%%EOF")
    tool = ReadPdfTool(root_dir=tmp_path, max_chars_default=1000)
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")

    result = tool.run({"path": "sample.pdf", "pages": [2]}, context)
    assert result.ok is True
    assert result.data["page_count"] == 2
    assert result.data["pages_read"] == [2]
    assert "[Page 2]" in result.data["content"]
    assert "two" in result.data["content"]
