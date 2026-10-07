"""Offline SDK compatibility: real harness, scripted provider, no credentials/network/audio."""
import json

import pytest

pytest.importorskip('deepagents')
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

from linguaflow.knowledge.api import DeepSeekService, RequestBudget
from linguaflow.knowledge.harness import EXCLUDED_TOOLS, run_agent
from linguaflow.knowledge.schemas import NoteJob


class ScriptedModel(BaseChatModel):
    responses: list = Field(default_factory=list)
    seen_tools: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return 'deepseek'

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        message = self.responses.pop(0)
        message.usage_metadata = {'input_tokens': 50, 'output_tokens': 30, 'total_tokens': 80}
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs):
        names = [convert_to_openai_tool(tool)['function']['name'] for tool in tools]
        self.seen_tools.extend(names)
        return self.bind(tools=[convert_to_openai_tool(tool) for tool in tools], **kwargs)

    def get_num_tokens(self, text):
        return len(text.encode('utf-8'))


def test_budget_before_dispatch_and_missing_usage():
    budget = RequestBudget()
    with pytest.raises(ValueError):
        budget.reserve('big', ['x' * 17000])
    assert budget.calls == 0
    budget.reserve('small', ['hello'])
    reservation = budget.tokens
    budget.finish('small', None)
    assert budget.uncertain and budget.tokens == reservation
    for index in range(11):
        budget.reserve(index, ['hi'])
        budget.finish(index, {'total_tokens': 10})
    with pytest.raises(ValueError):
        budget.reserve('13th', ['hi'])


def test_real_harness_scoped_tool_roundtrip():
    model = ScriptedModel(responses=[
        AIMessage(content='', tool_calls=[{'name': 'read_transcript_spans', 'args': {'ids': ['caption:1']}, 'id': 'read'}]),
        AIMessage(content='', tool_calls=[{'name': 'CourseAnswer', 'args': {
            'answer': '使用梯度下降。', 'refs': [{'id': 'caption:1', 'quote': 'gradient descent'}]}, 'id': 'answer'}])])
    service = DeepSeekService(model=model)
    job = NoteJob('job', 'epoch', 0, {'caption:1': {'text': 'Use gradient descent.', 'kind': 'caption',
                  'source_version': 1}}, ('课堂讲述',), question='What method?')
    import asyncio
    result = asyncio.run(run_agent(service, job, answer=True))
    assert result['refs'][0]['id'] == 'caption:1'
    assert not EXCLUDED_TOOLS & set(model.seen_tools)
    assert service.budget.calls == 2 and service.budget.tokens == 160


def test_structured_response_and_bad_reference_rejected():
    from linguaflow.knowledge.schemas import DocumentBlock
    model = ScriptedModel(responses=[AIMessage(content=json.dumps({'terms': [{'canonical': 'invented',
        'aliases': [], 'refs': [{'id': 'doc:1', 'quote': 'real term'}]}]}))])
    import asyncio
    with pytest.raises(ValueError, match='术语未出现'):
        asyncio.run(DeepSeekService(model=model).extract_terms([DocumentBlock('doc:1', 'doc', 1, '', 'real term', '1')]))


def test_hallucinated_file_tool_cannot_execute():
    import asyncio
    model = ScriptedModel(responses=[AIMessage(content='', tool_calls=[
        {'name': 'read_file', 'args': {'file_path': '/outside-user-file'}, 'id': 'forbidden'}])])
    job = NoteJob('job', 'epoch', 0, {}, ('课堂讲述',), question='read file')
    with pytest.raises(ValueError, match='未授权工具'):
        asyncio.run(run_agent(DeepSeekService(model=model), job, answer=True))


def test_actual_deepseek_sdk_payload_usage_and_client_cleanup(monkeypatch):
    import asyncio

    import httpx

    import linguaflow.knowledge.api as api
    from linguaflow.knowledge.schemas import DocumentBlock
    async_client = httpx.AsyncClient
    captured = []
    def respond(request):
        captured.append(json.loads(request.content))
        assert str(request.url) == 'https://api.deepseek.com/chat/completions'
        content = {'terms': [{'canonical': 'gradient descent', 'aliases': [],
                             'refs': [{'id': 'doc:1', 'quote': 'gradient descent'}]}]}
        return httpx.Response(200, json={'id': 'offline', 'object': 'chat.completion', 'created': 0,
            'model': 'deepseek-flash', 'choices': [{'index': 0, 'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': json.dumps(content)}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30}})
    monkeypatch.setattr(api, 'read_credential', lambda: 'test-placeholder-key')
    class OfflineClient(async_client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(httpx, 'AsyncClient', OfflineClient)
    async def scenario():
        service = DeepSeekService()
        try:
            result = await service.extract_terms([DocumentBlock('doc:1', 'doc', 1, '', 'gradient descent', '1')])
            assert result[0]['canonical'] == 'gradient descent'
            assert service.budget.calls == 1 and service.budget.tokens == 30
            assert not service.budget.view()['uncertain']
        finally:
            await service.close()
        assert service.http.is_closed and service.model.root_client.is_closed()
    asyncio.run(scenario())
    assert captured[0]['model'] == 'deepseek-flash'
    assert captured[0]['thinking']['type'] == 'disabled'
    assert captured[0]['response_format'] == {'type': 'json_object'}
