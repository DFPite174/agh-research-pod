"""Read public research metadata from fixed providers; never execute fetched text."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import httpx


def _request(client, method, url, *, attempts=3, max_bytes=2_000_000, **kwargs):
    """Bound retries, redirects, response size and request time; never echo bodies."""
    origin = httpx.URL(url)
    for attempt in range(attempts):
        try:
            with client.stream(method, url, timeout=15, follow_redirects=False, **kwargs) as response:
                if 300 <= response.status_code < 400 and method == 'GET' and attempt + 1 < attempts:
                    target = httpx.URL(url).join(response.headers.get('Location', ''))
                    if (target.scheme == 'https' and target.host == origin.host and target.port == origin.port
                            and not target.userinfo and not target.fragment):
                        url = str(target)
                        kwargs.pop('params', None)
                        continue
                if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
                    delay = response.headers.get('Retry-After', '0.25')
                    try:
                        delay = float(delay)
                    except ValueError:
                        try:
                            delay = (parsedate_to_datetime(delay) - datetime.now(timezone.utc)).total_seconds()
                        except (ValueError, TypeError, OverflowError):
                            delay = .25
                    time.sleep(max(0, min(delay, 2)))
                    continue
                if not 200 <= response.status_code < 300:
                    raise ValueError(f'source request failed (HTTP {response.status_code})')
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError('source response exceeds size budget')
                    chunks.append(chunk)
                return b''.join(chunks)
        except httpx.RequestError:
            if attempt + 1 == attempts:
                raise ValueError('source request failed (transport)') from None
    raise ValueError('source request failed')


def _json_request(client, url, **kwargs):
    try:
        result = json.loads(_request(client, 'GET', url, **kwargs))
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (json.JSONDecodeError, UnicodeError, TypeError):
        raise ValueError('source returned invalid metadata') from None


def _reference(source, reference):
    if source not in {'arxiv', 'github', 'huggingface-model', 'huggingface-dataset'}:
        raise ValueError('unknown source')
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 300:
        raise ValueError('invalid reference')
    if any(ord(c) < 32 for c in reference) or '://' in reference or '..' in reference or '\\' in reference:
        raise ValueError('invalid reference')
    reference = reference.strip()
    if source == 'arxiv':
        if '/' in reference:
            raise ValueError('arxiv requires a search query')
    else:
        parts = reference.split('/')
        expected = {2} if source == 'github' else {1, 2}
        if len(parts) not in expected or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', p)
                                             for p in parts):
            raise ValueError('invalid repository identifier')
    return reference


def fetch_source(source, reference, *, client=None):
    reference = _reference(source, reference)
    owned = client is None
    client = client or httpx.Client()
    try:
        metadata = {'source': source, 'reference': reference,
                    'retrieved_at': datetime.now(timezone.utc).isoformat(), 'trust': 'external-untrusted'}
        if source == 'github':
            url = f'https://api.github.com/repos/{reference}'
            repo = _json_request(client, url)
            branch = repo.get('default_branch')
            if not isinstance(branch, str) or not branch or len(branch) > 200:
                raise ValueError('missing repository default branch')
            commit = _json_request(client, f'{url}/commits/{quote(branch, safe="")}')
            revision = commit.get('sha', '')
            if not re.fullmatch('[a-fA-F0-9]{40}', revision):
                raise ValueError('missing locked repository commit')
            readme = _json_request(client, f'{url}/readme', params={'ref': revision})
            try:
                card = base64.b64decode(''.join(readme['content'].split()), validate=True).decode('utf-8', 'replace')
            except (KeyError, ValueError, TypeError):
                raise ValueError('invalid repository readme') from None
            title = repo.get('full_name', reference)
            metadata.update(url=f'https://github.com/{reference}', revision=revision, license=repo.get('license'))
            content = json.dumps({'repository': repo, 'readme': card}, ensure_ascii=False).encode()
        elif source.startswith('huggingface-'):
            kind = 'models' if source == 'huggingface-model' else 'datasets'
            repo = _json_request(client, f'https://huggingface.co/api/{kind}/{reference}')
            revision = repo.get('sha', '')
            if not re.fullmatch('[A-Za-z0-9-]{1,100}', revision):
                raise ValueError('missing locked Hugging Face revision')
            prefix = '' if kind == 'models' else 'datasets/'
            url = f'https://huggingface.co/{prefix}{reference}'
            card = _request(client, 'GET', f'{url}/resolve/{revision}/README.md').decode('utf-8', 'replace')
            title = repo.get('id', reference)
            metadata.update(url=url, revision=revision, card=repo.get('cardData'))
            content = json.dumps({'repository': repo, 'card': card}, ensure_ascii=False).encode()
        else:
            url = 'https://export.arxiv.org/api/query'
            content = _request(client, 'GET', url, params={'search_query': reference, 'max_results': 5,
                                                         'sortBy': 'relevance'})
            if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
                raise ValueError('unsafe arxiv XML')
            try:
                root = ET.fromstring(content)
                ns = {'a': 'http://www.w3.org/2005/Atom'}
                entries = []
                for entry in root.findall('a:entry', ns):
                    identifier = entry.findtext('a:id', '', ns)
                    match = re.fullmatch(r'https?://arxiv.org/abs/([A-Za-z0-9./-]+v\d+)', identifier)
                    if not match:
                        raise ValueError('arxiv entry has no versioned identifier')
                    entries.append({'id': identifier, 'version': match[1],
                                    'title': entry.findtext('a:title', '', ns).strip(),
                                    'updated': entry.findtext('a:updated', '', ns),
                                    'published': entry.findtext('a:published', '', ns)})
            except ET.ParseError:
                raise ValueError('invalid arxiv XML') from None
            title = f'arXiv: {reference}'
            metadata.update(url=url, entries=entries)
        metadata['sha256'] = hashlib.sha256(content).hexdigest()
        return {'title': str(title)[:300], 'content': content, 'metadata': metadata}
    finally:
        if owned:
            client.close()
