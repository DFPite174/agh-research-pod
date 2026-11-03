import base64
import json

import httpx
import pytest

from agh_pod.sources import fetch_source


def test_github_locks_readme_to_observed_commit():
    requests = []
    def reply(request):
        requests.append(request)
        path = request.url.path
        if path.endswith('/commits/main'):
            return httpx.Response(200, json={'sha': 'a' * 40})
        if path.endswith('/readme'):
            assert request.url.params['ref'] == 'a' * 40
            return httpx.Response(200, json={'content': base64.b64encode(b'# Read me').decode()})
        return httpx.Response(200, json={'full_name': 'a/b', 'default_branch': 'main',
                                        'license': {'spdx_id': 'MIT'}, 'description': 'repo'})
    result = fetch_source('github', 'a/b', client=httpx.Client(transport=httpx.MockTransport(reply)))
    assert result['metadata']['revision'] == 'a' * 40
    assert b'# Read me' in result['content']
    assert len(requests) == 3


@pytest.mark.parametrize('source,reference', [('github','https://evil/a'),('github','a/../b'),
    ('huggingface-model','a/b/c'),('huggingface-dataset','../a'),('arxiv','https://evil'),
    ('unknown','x')])
def test_reference_validation_precedes_network(source, reference):
    def reply(request):
        pytest.fail('invalid reference reached network')
    with pytest.raises(ValueError):
        fetch_source(source, reference, client=httpx.Client(transport=httpx.MockTransport(reply)))


@pytest.mark.parametrize('source,api_path', [('huggingface-model','/api/models/org/name'),
                                           ('huggingface-dataset','/api/datasets/org/name')])
def test_huggingface_records_card_and_revision(source, api_path):
    def reply(request):
        assert request.url.host == 'huggingface.co'
        if request.url.path == api_path:
            return httpx.Response(200, json={'id':'org/name','sha':'abc123','cardData':{'license':'apache-2.0'}})
        assert '/resolve/abc123/README.md' in request.url.path
        return httpx.Response(200, text='# card')
    result = fetch_source(source,'org/name',client=httpx.Client(transport=httpx.MockTransport(reply)))
    assert result['metadata']['revision'] == 'abc123'
    assert b'# card' in result['content']
    json.dumps(result['metadata'])


def test_arxiv_keeps_versioned_entries_and_bounded_retry(monkeypatch):
    monkeypatch.setattr('agh_pod.sources.time.sleep', lambda value: None)
    calls = []
    def reply(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={'Retry-After':'999'})
        return httpx.Response(200, text='''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <id>http://arxiv.org/abs/2401.12345v2</id><title>Paper</title><summary>Text</summary>
          <published>2024-01-01</published><updated>2024-01-02</updated></entry></feed>''')
    result = fetch_source('arxiv','convertible bonds',client=httpx.Client(transport=httpx.MockTransport(reply)))
    assert result['metadata']['entries'][0]['version'] == '2401.12345v2'
    assert len(calls) == 2
    assert calls[0].url.host == 'export.arxiv.org'


def test_source_does_not_follow_redirect_to_other_host():
    def reply(request):
        return httpx.Response(302,headers={'Location':'http://127.0.0.1/private'})
    with pytest.raises(ValueError, match='source request failed'):
        fetch_source('github','a/b',client=httpx.Client(transport=httpx.MockTransport(reply)))


def test_huggingface_readme_allows_bounded_same_host_https_redirect():
    def reply(request):
        if request.url.path == '/api/models/org/name':
            return httpx.Response(200,json={'id':'org/name','sha':'abc123'})
        if '/resolve/' in request.url.path:
            return httpx.Response(307,headers={'Location':'/api/resolve-cache/card'})
        assert request.url.path == '/api/resolve-cache/card'
        return httpx.Response(200,text='card text')
    result = fetch_source('huggingface-model','org/name',client=httpx.Client(transport=httpx.MockTransport(reply)))
    assert b'card text' in result['content']


def test_rate_limit_retries_at_most_three_times(monkeypatch):
    delays = []
    monkeypatch.setattr('agh_pod.sources.time.sleep', delays.append)
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(429,headers={'Retry-After':'9999'})
    with pytest.raises(ValueError):
        fetch_source('github','a/b',client=httpx.Client(transport=httpx.MockTransport(reply)))
    assert len(requests) == 3 and delays == [2,2]


def test_oversized_source_response_is_rejected():
    client = httpx.Client(transport=httpx.MockTransport(lambda request:
        httpx.Response(200,content=b'x' * 2_000_001)))
    with pytest.raises(ValueError,match='size budget'):
        fetch_source('github','a/b',client=client)
