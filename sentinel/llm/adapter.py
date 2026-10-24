"""Provider-neutral proposal contract. Credentials never enter the recording store."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
import sqlite3
from contextvars import ContextVar
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import quote, urlsplit
from urllib.error import HTTPError, URLError

from pydantic import BaseModel, ValidationError
from sentinel.schemas import canonical_json, sha256_of


_deadline = ContextVar('llm_deadline', default=None)


class AdapterError(Exception):
    pass


class ReplayMiss(AdapterError):
    pass


class ResponseStore:
    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS llm_attempts (seq INTEGER PRIMARY KEY, input_hash TEXT, request TEXT, response TEXT, error TEXT)')

    def append(self, key, request, response, error=None):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO llm_attempts(input_hash,request,response,error) VALUES (?,?,?,?)',
                       (key, canonical_json(request), canonical_json(response), error))

    def attempts(self, key):
        with sqlite3.connect(self.path) as db:
            return db.execute('SELECT response,error FROM llm_attempts WHERE input_hash=? ORDER BY seq', (key,)).fetchall()

    def export(self):
        with sqlite3.connect(self.path) as db:
            rows = db.execute('SELECT input_hash,request,response,error FROM llm_attempts ORDER BY seq').fetchall()
        return [dict(input_hash=k, request=json.loads(q), response=json.loads(r), error=e) for k,q,r,e in rows]


def proposal_request(role, inputs, schema, prompt_version):
    prompt_path = Path(__file__).with_name('prompts') / f'{role}_v1.md'
    instructions = prompt_path.read_text() if prompt_path.exists() else 'Return only JSON matching the response schema.'
    return dict(role=role, prompt_version=prompt_version, instructions=instructions,
                inputs=inputs, response_schema=schema.model_json_schema())


class Adapter:
    mode = 'live'

    def __init__(self, transport, store: ResponseStore, *, model='configured', timeout_seconds=90,
                 clock=time.monotonic, sleep=time.sleep):
        if timeout_seconds <= 0:
            raise ValueError('timeout_seconds must be positive')
        self.transport, self.store, self.model = transport, store, model
        self.timeout_seconds, self.clock, self.sleep = timeout_seconds, clock, sleep

    def propose(self, role, prompt_inputs, response_schema: type[BaseModel], *, prompt_version='v1'):
        request = proposal_request(role, prompt_inputs, response_schema, prompt_version)
        request['model'] = self.model
        key = sha256_of(request)
        deadline = self.clock() + self.timeout_seconds

        def remaining():
            budget = deadline - self.clock()
            if budget <= 0:
                self.store.append(key, request, None, 'deadline_exceeded')
                raise AdapterError('LLM proposal deadline exceeded')
            return budget

        for attempt in range(3):
            for transport_attempt in range(3):
                budget = remaining()
                token = _deadline.set(time.monotonic() + budget)
                try:
                    raw = self.transport({**request, 'validation_attempt': attempt})
                    remaining()  # never accept a result arriving after the overall deadline
                    break
                except HTTPError as exc:
                    retryable = exc.code in {408, 429, 500, 502, 503, 504}
                    self.store.append(key, request, None, 'transport_error' if retryable else 'permanent_provider_error')
                    if not retryable or transport_attempt == 2:
                        raise AdapterError('LLM provider request failed') from exc
                except (OSError, TimeoutError, URLError) as exc:
                    self.store.append(key, request, None, 'transport_error')
                    if transport_attempt == 2:
                        raise AdapterError('LLM transport failed') from exc
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    self.store.append(key, request, None, 'invalid_provider_response')
                    raise AdapterError('Invalid LLM provider response') from exc
                finally:
                    _deadline.reset(token)
                delay = min(0.5 * 2 ** transport_attempt, remaining())
                self.sleep(delay)
            try:
                result = (response_schema.model_validate_json(raw) if isinstance(raw, str)
                          else response_schema.model_validate(raw))
            except (ValidationError, ValueError, TypeError):
                self.store.append(key, request, raw, 'validation_error')
                continue
            remaining()
            self.store.append(key, request, raw)
            return result
        raise AdapterError('LLM output invalid after three attempts')


class ReplayAdapter:
    mode = 'replay'

    def __init__(self, store: ResponseStore, *, model='configured'):
        self.store, self.model = store, model

    def propose(self, role, prompt_inputs, response_schema, *, prompt_version='v1'):
        request = proposal_request(role, prompt_inputs, response_schema, prompt_version)
        request['model'] = self.model
        rows = self.store.attempts(sha256_of(request))
        if not rows:
            raise ReplayMiss('No recording for this input, schema, model and prompt version')
        for raw, error in rows:
            if error == 'transport_error':
                continue
            if error in {'invalid_provider_response', 'permanent_provider_error', 'deadline_exceeded'}:
                raise AdapterError('Recorded proposal failure: ' + error)
            value = json.loads(raw)
            try:
                return (response_schema.model_validate_json(value) if isinstance(value, str)
                        else response_schema.model_validate(value))
            except (ValidationError, ValueError, TypeError):
                continue
        raise AdapterError('Recorded LLM output failed validation')


class JsonTransport:
    """POST the proposal contract to a configured JSON-schema gateway.

    The gateway returns the response model directly as JSON. Provider-specific SDKs
    can implement the same callable without changing agents or replay keys.
    """
    def __init__(self, endpoint, api_key=None, timeout=60):
        self.endpoint, self.api_key, self.timeout = endpoint, api_key, timeout
        if not endpoint.startswith(('https://', 'http://localhost:', 'http://127.0.0.1:')):
            raise ValueError('LLM endpoint must use HTTPS or loopback HTTP')

    def headers(self):
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        return headers

    def __call__(self, payload):
        endpoint = urlsplit(self.endpoint)
        deadline = _deadline.get() or (time.monotonic() + self.timeout)

        def remaining():
            budget = deadline - time.monotonic()
            if budget <= 0:
                raise TimeoutError('LLM deadline exceeded')
            return min(self.timeout, budget)

        connection_cls = HTTPSConnection if endpoint.scheme == 'https' else HTTPConnection
        connection = connection_cls(endpoint.hostname, endpoint.port, timeout=remaining())
        try:
            connection.connect()
            sock = connection.sock
            sock.settimeout(remaining())
            path = endpoint.path or '/'
            if endpoint.query:
                path += '?' + endpoint.query
            connection.request('POST', path, body=canonical_json(payload).encode(), headers=self.headers())
            sock.settimeout(remaining())
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                # Never include provider response bodies or headers in recordings/errors.
                raise HTTPError(self.endpoint, response.status, 'provider request failed', {}, None)
            chunks, size = [], 0
            while True:
                sock.settimeout(remaining())
                chunk = response.read1(min(65_536, 1_000_001 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > 1_000_000:
                    raise ValueError('LLM response exceeds 1 MB')
                if response.isclosed():
                    break
            return json.loads(b''.join(chunks))
        finally:
            connection.close()


class ChatTransport(JsonTransport):
    """Chat Completions JSON mode; local Pydantic validation remains authoritative.

    https://developers.openai.com/api/docs/guides/structured-outputs
    """
    def __call__(self, payload):
        response = super().__call__({
            'model': payload['model'],
            'messages': [
                {'role': 'system', 'content': payload['instructions']},
                {'role': 'user', 'content': canonical_json({
                    'evidence': payload['inputs'], 'response_schema': payload['response_schema'],
                    'validation_attempt': payload['validation_attempt']})},
            ],
            'response_format': {'type': 'json_object'},
        })
        choice = response['choices'][0]
        if choice.get('finish_reason') != 'stop' or choice['message'].get('refusal'):
            raise ValueError('Provider refused or truncated proposal')
        return choice['message']['content']


class GeminiTransport(JsonTransport):
    """Native Gemini generateContent with a JSON response schema.

    https://ai.google.dev/gemini-api/docs/generate-content/structured-output
    """
    def headers(self):
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['x-goog-api-key'] = self.api_key
        return headers

    def __call__(self, payload):
        response = super().__call__({
            'systemInstruction': {'parts': [{'text': payload['instructions']}]},
            'contents': [{'role': 'user', 'parts': [{'text': canonical_json({
                'evidence': payload['inputs'], 'validation_attempt': payload['validation_attempt']})}]}],
            'generationConfig': {
                'responseMimeType': 'application/json',
                'responseJsonSchema': payload['response_schema'],
            },
        })
        candidate = response['candidates'][0]
        if candidate.get('finishReason') != 'STOP':
            raise ValueError('Gemini blocked or truncated proposal')
        text = ''.join(p['text'] for p in candidate['content']['parts']
                       if 'text' in p and not p.get('thought'))
        if not text:
            raise ValueError('Gemini returned no proposal')
        return text


def from_env(db_path):
    mode = os.environ.get('SENTINEL_LLM_MODE', 'fixture')
    if mode == 'fixture':
        return None
    store = ResponseStore(os.environ.get('SENTINEL_LLM_DB', str(db_path) + '.llm.db'))
    model = os.environ.get('SENTINEL_LLM_MODEL', 'configured')
    timeout_seconds = float(os.environ.get('SENTINEL_LLM_TIMEOUT_SECONDS', '90'))
    if mode == 'replay':
        return ReplayAdapter(store, model=model)
    if mode != 'live':
        raise ValueError('SENTINEL_LLM_MODE must be fixture, live or replay')
    if model == 'configured':
        raise ValueError('Set SENTINEL_LLM_MODEL for live mode')
    provider = os.environ.get('SENTINEL_LLM_PROVIDER', 'gemini')
    if provider not in {'gemini', 'chat', 'gateway'}:
        raise ValueError('SENTINEL_LLM_PROVIDER must be gemini, chat or gateway')
    if provider == 'gemini':
        endpoint = os.environ.get('SENTINEL_LLM_ENDPOINT',
            'https://generativelanguage.googleapis.com/v1beta/models/' + quote(model, safe='') + ':generateContent')
        api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('SENTINEL_LLM_API_KEY')
        if not api_key:
            raise ValueError('Set GEMINI_API_KEY for live Gemini mode')
        return Adapter(GeminiTransport(endpoint, api_key), store, model=model, timeout_seconds=timeout_seconds)
    transport = ChatTransport if provider == 'chat' else JsonTransport
    endpoint = os.environ.get('SENTINEL_LLM_ENDPOINT', 'https://api.openai.com/v1/chat/completions')
    return Adapter(transport(endpoint, os.environ.get('SENTINEL_LLM_API_KEY')), store, model=model, timeout_seconds=timeout_seconds)
