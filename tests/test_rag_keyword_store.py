import importlib.util
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def store(tmp_path):
    source = Path(__file__).resolve().parents[1] / 'rag/langchain-agent/rag/keyword_store.py'
    spec = importlib.util.spec_from_file_location('_keyword_store_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    legacy = tmp_path / 'legacy.sqlite3'
    with closing(sqlite3.connect(legacy)) as conn, conn:
        conn.executescript("""
            CREATE TABLE collections(id TEXT,name TEXT);
            CREATE TABLE segments(id TEXT,collection TEXT);
            CREATE TABLE embeddings(id INTEGER,segment_id TEXT,embedding_id TEXT);
            CREATE TABLE embedding_metadata(id INTEGER,key TEXT,string_value TEXT,int_value INTEGER,float_value REAL,bool_value INTEGER);
            INSERT INTO collections VALUES ('c','agent');
            INSERT INTO segments VALUES ('s','c');
            INSERT INTO embeddings VALUES (1,'s','old-id');
            INSERT INTO embedding_metadata VALUES (1,'source','old.txt',NULL,NULL,NULL);
            INSERT INTO embedding_metadata VALUES (1,'chunk_index',NULL,0,NULL,NULL);
            INSERT INTO embedding_metadata VALUES (1,'chroma:document','原始生产知识',NULL,NULL,NULL);
        """)
    adapter = module.KeywordDocumentStore(legacy, 'agent', tmp_path / 'keyword.sqlite3')
    return adapter, legacy


def doc(source, text):
    return SimpleNamespace(page_content=text, metadata={'source': source, 'chunk_index': 0})


def test_keyword_storage_reuses_legacy_text_without_changing_original_index(store):
    adapter, legacy = store
    before = legacy.read_bytes()
    assert adapter.count() == 1
    assert adapter.get()['documents'] == ['原始生产知识']
    adapter.add_documents([doc('new.txt', '新增知识')], ids=['new-id'])
    assert adapter.count() == 2
    assert legacy.read_bytes() == before


def test_reingestion_overrides_source_and_delete_does_not_resurrect_old_chunks(store):
    adapter, legacy = store
    before = legacy.read_bytes()
    adapter.delete(where={'source': 'old.txt'})
    adapter.add_documents([doc('old.txt', '更新后的知识')], ids=['new-id'])
    assert adapter.get()['documents'] == ['更新后的知识']
    adapter.delete(where={'source': 'old.txt'})
    assert adapter.count() == 0
    assert legacy.read_bytes() == before


def test_keyword_rebuild_only_clears_local_view_and_releases_database_handles(store):
    adapter, legacy = store
    before = legacy.read_bytes()
    old_revision = adapter.revision_token()
    adapter.clear()
    assert adapter.count() == 0
    assert adapter.revision_token() != old_revision
    assert legacy.read_bytes() == before
    # On Windows an unclosed connection would prevent moving the new local database.
    moved = adapter.database.with_name('closed.sqlite3')
    adapter.database.rename(moved)
    moved.rename(adapter.database)


def test_keyword_add_is_idempotent_and_source_deletion_requires_an_explicit_target(store):
    adapter, _ = store
    adapter.add_documents([doc('new.txt', '新知识')], ids=['new-id'])
    adapter.add_documents([doc('new.txt', '新知识')], ids=['new-id'])
    assert adapter.count() == 2
    with pytest.raises(ValueError):
        adapter.delete(where={})
