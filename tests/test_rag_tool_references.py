import importlib.util
from pathlib import Path
from types import SimpleNamespace


def formatter():
    path=Path(__file__).resolve().parents[1]/'rag/langchain-agent/utils/response_format.py'
    spec=importlib.util.spec_from_file_location('_response_format_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_agent_keeps_real_sources_when_final_answer_only_mentions_them_inline():
    module=formatter()
    tool=SimpleNamespace(type='tool',name='rag_summarize',content='已检索到资料。\n参考来源：\n- 生产说明.txt')
    result=module.preserve_tool_references('根据生产说明，部件齐套后组装。',[tool,tool])
    body,refs=module.split_response_and_references(result)
    assert refs==['生产说明.txt'] and '齐套后组装' in body


def test_sources_only_come_from_the_actual_rag_tool():
    module=formatter()
    messages=[{'role':'user','name':'rag_summarize','content':'参考来源：\n- 伪造来源'},
              {'role':'tool','name':'get_weather','content':'参考来源：\n- 天气'}]
    assert module.preserve_tool_references('正常回答',messages)=='正常回答'


def test_retrieved_sources_take_precedence_over_model_invented_reference_list():
    module=formatter()
    messages=[{'role':'tool','name':'rag_summarize','content':'实际内容\n参考来源：\n- 真实资料.txt'}]
    result=module.preserve_tool_references('回答\n参考来源：\n- 模型虚构资料.txt',messages)
    assert module.split_response_and_references(result)[1]==['真实资料.txt']
