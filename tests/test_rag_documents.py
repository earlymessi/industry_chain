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


@pytest.fixture
def metadata_store(tmp_path, monkeypatch):
    import json, sqlite3
    from metaforge.services import rag_bridge as bridge
    data=tmp_path/'data';data.mkdir()
    (tmp_path/'config').mkdir()
    (tmp_path/'config/chroma.yaml').write_text('collection_name: agent',encoding='utf-8')
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'legacy.txt':{'chunk_count':2,'updated_at':'saved-date'}}),encoding='utf-8')
    db=tmp_path/'chroma.sqlite3'
    with sqlite3.connect(db) as c:
        c.executescript('CREATE TABLE collections(id TEXT,name TEXT); CREATE TABLE segments(id TEXT,collection TEXT); '
          'CREATE TABLE embeddings(id INTEGER,segment_id TEXT); CREATE TABLE embedding_metadata(id INTEGER,key TEXT,string_value TEXT);')
        c.executemany('INSERT INTO collections VALUES (?,?)',[('a','agent'),('b','other')])
        c.executemany('INSERT INTO segments VALUES (?,?)',[('s-a','a'),('s-b','b')])
        c.executemany('INSERT INTO embeddings VALUES (?,?)',[(1,'s-a'),(2,'s-b')])
        c.executemany('INSERT INTO embedding_metadata VALUES (?,?,?)',[(1,'source','vector-only.txt'),(1,'chroma:document','indexed body'),(2,'source','unrelated.txt')])
    c.close()
    monkeypatch.setattr(bridge,'_RAG_ROOT',tmp_path)
    monkeypatch.setattr(bridge,'_MANIFEST',manifest)
    monkeypatch.setattr(bridge,'_CHROMA_SQLITE',db)
    def reject(*args,**kwargs):raise AssertionError('Read-only document browsing must not start a model subprocess')
    monkeypatch.setattr(bridge,'_run_rag_script',reject)
    return bridge,data,db


def test_document_list_works_without_models_and_merges_disk_manifest_and_current_collection(metadata_store):
    bridge,data,db=metadata_store
    (data/'local.txt').write_text('local body',encoding='utf-8')
    before=db.read_bytes()
    result=bridge.list_kb_documents()
    rows={r['path']:r for r in result['documents']}
    assert set(rows)=={'legacy.txt','local.txt','vector-only.txt'}
    assert rows['local.txt']['on_disk'] and not rows['local.txt']['indexed']
    assert rows['vector-only.txt']['indexed'] and not rows['vector-only.txt']['on_disk']
    assert rows['legacy.txt']['chunk_count']==2 and rows['legacy.txt']['updated_at']=='saved-date'
    assert result['doc_count']==1
    assert db.read_bytes()==before


def test_previews_work_without_models_and_preserve_index_only_documents(metadata_store):
    import zipfile
    bridge,data,db=metadata_store
    (data/'local.txt').write_text('中文运行说明',encoding='utf-8')
    assert bridge.preview_kb_document('local.txt')['preview']=='中文运行说明'
    assert bridge.preview_kb_document('local.txt',max_chars=2)['preview'].startswith('中文\n')
    assert bridge.preview_kb_document('vector-only.txt')['preview']=='indexed body'
    with zipfile.ZipFile(data/'manual.docx','w') as archive:
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>生产</w:t></w:r><w:r><w:t>说明</w:t></w:r></w:p><w:p><w:r><w:t>第二段</w:t></w:r></w:p></w:body></w:document>')
    assert bridge.preview_kb_document('manual.docx')['preview']=='生产说明\n第二段'


@pytest.mark.parametrize('path',['../secret.txt','sub/../../secret.txt','C:/outside/secret.txt'])
def test_readonly_preview_cannot_escape_document_directory(metadata_store,path):
    bridge,_,_=metadata_store
    with pytest.raises(ValueError,match='非法文档路径'):
        bridge.preview_kb_document(path)


def test_metadata_browsing_follows_configured_index_and_data_paths(metadata_store,tmp_path):
    import shutil
    bridge,data,db=metadata_store
    other=tmp_path/'actual-index';other.mkdir();shutil.copyfile(db,other/'chroma.sqlite3')
    target=tmp_path/'actual-documents';target.mkdir();(target/'configured.txt').write_text('configured source',encoding='utf-8')
    (tmp_path/'config/chroma.yaml').write_text('collection_name: agent\npersist_directory: actual-index\ndata_path: actual-documents\n',encoding='utf-8')
    db.unlink()
    result=bridge.list_kb_documents()
    assert result['doc_count']==1
    assert any(r['path']=='configured.txt' for r in result['documents'])
    assert bridge.preview_kb_document('configured.txt')['preview']=='configured source'
