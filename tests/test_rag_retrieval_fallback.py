"""Actual hybrid recall must retain sparse-only hits when dense API fails."""
import ast
import logging
import os
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document


@pytest.fixture
def retrieval(monkeypatch):
    monkeypatch.setenv("RAG_RETRIEVAL_MODE","hybrid")
    # Load the actual class without importing the RAG application or opening its live index.
    source=Path(__file__).resolve().parents[1]/'rag/langchain-agent/rag/rag_service.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    definition=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='RagSummarizeService')
    namespace={'Document':Document,'logger':logging.getLogger('test-rag'),'re':re,'threading':threading,'time':time,'os':os}
    exec(compile(ast.Module(body=[definition],type_ignores=[]),str(source),'exec'),namespace)
    service=object.__new__(namespace['RagSummarizeService'])
    service._ensure_collection_ready=lambda:None
    service._expand_query=lambda q:q
    service._expand_query_by_llm=lambda q:[q,q+' expansion']
    service._query_terms=lambda q:[q]
    service._rerank_score=lambda terms,text,score:score
    service.candidate_k=4;service.min_relevance_score=0;service.bm25_top_k=4;service.rrf_k=60;service.top_k=4
    hit=SimpleNamespace(content='生产完成后部件入库，再按BOM齐套组装。',metadata={'source':'assembly.txt','chunk_index':0})
    service.bm25_store=SimpleNamespace(ensure_index=lambda store:None,search=lambda query,top_k:[(hit,3.0)])
    return service


def test_provider_outage_still_returns_local_keyword_hits_and_avoids_repeating_failed_api(retrieval):
    calls=[]
    def failed(*args,**kwargs):
        calls.append(args);raise RuntimeError('429 embedding unavailable')
    retrieval.vector_store=SimpleNamespace(vector_store=SimpleNamespace(similarity_search_with_relevance_scores=failed))
    docs=retrieval.retriever_docs('组装')
    assert len(calls)==1
    assert len(docs)==1 and docs[0].metadata['source']=='assembly.txt'
    assert docs[0].page_content.startswith('生产完成')
    assert docs[0].metadata['retrieval_mode']=='bm25_fallback'


def test_sparse_only_hit_is_retained_during_healthy_hybrid_recall(retrieval):
    dense=Document(page_content='配送安排',metadata={'source':'delivery.txt','chunk_index':0})
    retrieval.vector_store=SimpleNamespace(vector_store=SimpleNamespace(similarity_search_with_relevance_scores=lambda *a,**kw:[(dense,.8)]))
    docs=retrieval.retriever_docs('组装')
    assert {d.metadata['source'] for d in docs}=={'assembly.txt','delivery.txt'}
    assert all(d.metadata['retrieval_mode']=='hybrid' for d in docs)


def test_fallback_answer_preserves_sources_and_explicitly_discloses_retrieval_mode(retrieval):
    def failed(*args,**kwargs):raise RuntimeError('429 embedding unavailable')
    retrieval.vector_store=SimpleNamespace(vector_store=SimpleNamespace(similarity_search_with_relevance_scores=failed))
    retrieval._chain=SimpleNamespace(invoke=lambda context:'部件齐套后开始组装。')
    answer=retrieval.rag_summarize('组装')
    assert '本地关键词检索' in answer and '向量服务暂不可用' in answer
    assert '参考来源' in answer and 'assembly.txt' in answer


@pytest.fixture
def sparse_module(monkeypatch):
    import importlib.util,sys
    path=Path(__file__).resolve().parents[1]/'rag/langchain-agent/rag/bm25_store.py'
    spec=importlib.util.spec_from_file_location('_audit_bm25_store',path)
    module=importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules,spec.name,module);spec.loader.exec_module(module)
    return module


def test_chinese_full_sentence_retrieval_matches_shared_terms_without_embedding(sparse_module):
    module=sparse_module
    store=module.BM25Store()
    store._build_from_records([
        module.BM25Document('a','冰箱生产后的部件需要齐套，才能开始组装。',{'source':'assembly.txt'}),
        module.BM25Document('b','天气变化与道路降雨。',{'source':'weather.txt'})])
    found=store.search('请问冰箱生产如何衔接组装',top_k=2)
    assert found and found[0][0].doc_id=='a' and found[0][1]>0
    assert '组装' in module.BM25Store.tokenize('请问如何衔接组装')


def test_old_tokenizer_cache_is_rejected_and_new_cache_remains_reusable(sparse_module,tmp_path):
    import json
    module=sparse_module;path=tmp_path/'bm25.json'
    store=module.BM25Store(persist_enabled=True,persist_path=str(path))
    store._build_from_records([module.BM25Document('a','冰箱生产与组装',{'source':'assembly.txt'})])
    store.save_to_disk(manifest_hash='fixture',collection_count=1)
    saved=json.loads(path.read_text(encoding='utf-8'))
    assert saved['meta']['tokenizer_version']==module.TOKENIZER_VERSION
    other=module.BM25Store(persist_enabled=True,persist_path=str(path))
    assert other.load_from_disk(expected_manifest_hash='fixture',expected_collection_count=1)
    saved['meta'].pop('tokenizer_version');path.write_text(json.dumps(saved),encoding='utf-8')
    assert not other.load_from_disk(expected_manifest_hash='fixture',expected_collection_count=1)


def test_explicit_keyword_mode_never_calls_dense_and_is_not_reported_as_service_failure(retrieval,monkeypatch):
    monkeypatch.setenv('RAG_RETRIEVAL_MODE','keyword')
    def reject(*args,**kwargs):raise AssertionError('Keyword mode must not call any embedding API')
    retrieval.vector_store=SimpleNamespace(vector_store=SimpleNamespace(similarity_search_with_relevance_scores=reject))
    retrieval._chain=SimpleNamespace(invoke=lambda context:'按BOM齐套后组装。')
    answer=retrieval.rag_summarize('组装')
    assert '本地关键词检索' in answer and '暂不可用' not in answer
    assert 'assembly.txt' in answer
