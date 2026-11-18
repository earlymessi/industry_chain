"""RAG chat and tool-calling agent must honor the selected DeepSeek provider."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest


@pytest.fixture
def factory(monkeypatch):
    settings=SimpleNamespace(rag_conf={'chat_model_name':'legacy','embedding_model_name':'embedding-2'})
    monkeypatch.setitem(sys.modules,'utils.config_handler',settings)
    source=Path(__file__).resolve().parents[1]/'rag/langchain-agent/model/factory.py'
    spec=importlib.util.spec_from_file_location('_rag_provider_test',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'_require_model_api_key',lambda:None)
    monkeypatch.setenv('DEEPSEEK_API_KEY','fixture-deepseek-key')
    monkeypatch.setenv('DEEPSEEK_MODEL','deepseek-v4-pro')
    monkeypatch.setenv('DEEPSEEK_BASE_URL','https://api.deepseek.com')
    monkeypatch.setenv('RAG_CHAT_PROVIDER','deepseek')
    monkeypatch.setenv('LLM_API_KEY','fixture-old-zhipu-key')
    def reject(*args,**kwargs):raise AssertionError('Zhipu must not be used for the selected DeepSeek chat provider')
    monkeypatch.setattr(module,'ChatZhipuAI',reject)
    return module


def test_chat_and_agent_both_use_deepseek_even_when_old_zhipu_key_exists(factory):
    for model in [factory.get_chat_model(),factory.get_agent_chat_model()]:
        assert model.model_name=='deepseek-v4-pro'
        assert model.openai_api_key.get_secret_value()=='fixture-deepseek-key'
        assert model.extra_body['thinking']=={'type':'disabled'}
        assert model.extra_body['max_tokens']==2048
    assert factory.get_agent_chat_model().streaming is False


def test_deepseek_agent_can_bind_real_tool_schema(factory):
    from langchain_core.tools import tool
    @tool
    def current_month() -> str:
        """Return the current execution month."""
        return '2026-11'
    bound=factory.get_agent_chat_model().bind_tools([current_month])
    assert bound.kwargs['tools'][0]['function']['name']=='current_month'


def test_explicit_deepseek_without_key_reports_configuration_error_instead_of_using_zhipu(factory,monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY')
    with pytest.raises(EnvironmentError,match='DEEPSEEK_API_KEY'):
        factory.ChatModelFactory().generate()


def test_keyword_mode_rejects_embedding_initialization_before_choosing_a_paid_provider(factory,monkeypatch):
    monkeypatch.setenv('RAG_RETRIEVAL_MODE','keyword')
    with pytest.raises(EnvironmentError,match='不启用嵌入模型'):
        factory.EmbeddingsFactory().generate()
