"""rag_bridge 知识库文档路径与上传校验。"""

from __future__ import annotations

import pytest

from metaforge.services.rag_bridge import (
    ALLOWED_KB_EXTENSIONS,
    _normalize_kb_filename,
    knowledge_data_dir,
)


def test_knowledge_data_dir_exists():
    path = knowledge_data_dir()
    assert path.name == "data"
    assert "langchain-agent" in str(path)


@pytest.mark.parametrize("filename", ["guide.txt", "manual.pdf", "faq.docx", "items.json"])
def test_normalize_kb_filename_ok(filename):
    assert _normalize_kb_filename(filename) == filename


def test_normalize_kb_filename_accepts_uppercase_ext():
    assert _normalize_kb_filename("manual.PDF") == "manual.PDF"


def test_normalize_kb_filename_rejects_bad_ext():
    with pytest.raises(ValueError, match="仅支持"):
        _normalize_kb_filename("virus.exe")


def test_normalize_kb_filename_strips_path():
    assert _normalize_kb_filename("../../secret.txt") == "secret.txt"


def test_allowed_extensions():
    assert ".txt" in ALLOWED_KB_EXTENSIONS
