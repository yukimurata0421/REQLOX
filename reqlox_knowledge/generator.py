"""Reusable generator methods from the development implementation."""
from __future__ import annotations
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
DEFAULT_PROJECT_ID = 'reqlox'
MODEL_ID = 'gemini-3.8-flash'
MODEL_RELEASE_DATE = '2026-09-02'
LOCATION = 'global'
THINKING_LEVEL = 'LOW'
TOTAL_ATTEMPTS = 3
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
PROJECT_ID_PATTERN = re.compile('^[a-z][a-z0-9-]{5,29}$')

class VertexGeminiError(RuntimeError):
    """Fail-closed error from authentication, transport, or response parsing."""
    def __init__(self, message, *, provider_response_payload=None):
        super().__init__(message)
        self.provider_response_payload = provider_response_payload

class VertexGeminiResponseError(VertexGeminiError):
    """A provider response was received but cannot be accepted as complete output."""

    def __init__(self, message: str, *, provider_response: dict[str, Any], provider_response_payload=None):
        super().__init__(message, provider_response_payload=provider_response_payload)
        self.provider_response = provider_response
TokenProvider = Callable[[], str]
Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]
Sleeper = Callable[[float], None]

def gcloud_access_token() -> str:
    """Return an access token without ever including it in an error message."""
    try:
        result = subprocess.run(['gcloud', 'auth', 'print-access-token'], check=False, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VertexGeminiError('gcloud access-token acquisition failed') from exc
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        raise VertexGeminiError('gcloud access-token acquisition failed')
    return token

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def urllib_transport(url: str, headers: dict[str, str], payload: bytes, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url=url, data=payload, headers=headers, method='POST')
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                raise VertexGeminiError('GENERATION_RESPONSE_BOUND')
            return (int(response.status), body)
    except urllib.error.HTTPError as exc:
        return (int(exc.code), exc.read(2 * 1024 * 1024))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VertexGeminiError('Vertex AI transport failed') from exc

def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def _safe_error_message(payload: bytes) -> str:
    """Extract only the provider error status/message; never echo request data."""
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 'unparseable provider error'
    error = value.get('error') if isinstance(value, dict) else None
    if not isinstance(error, dict):
        return 'provider error without structured detail'
    status = str(error.get('status', 'UNKNOWN'))
    message = str(error.get('message', ''))[:500]
    return f'{status}: {message}' if message else status

def validate_vertex_response_schema(schema: dict[str, Any]) -> None:
    """Reject response-schema constructs known to be invalid at Vertex.

    Vertex's Schema message represents ``enum`` as repeated strings, even when
    the declared JSON value type is numeric. Exact numeric values therefore
    need ``minimum``/``maximum`` rather than a numeric enum. Reject locally so
    an invalid request cannot consume a provider attempt.
    """

    def visit(value: Any, path: str) -> None:
        if not isinstance(value, dict):
            raise VertexGeminiError(f'response schema node is not an object: {path}')
        enum = value.get('enum')
        if enum is not None:
            if not isinstance(enum, list) or not enum:
                raise VertexGeminiError(f'response schema enum must be non-empty: {path}')
            if any((not isinstance(item, str) for item in enum)):
                raise VertexGeminiError(f'Vertex response schema enum values must be strings: {path}')
        properties = value.get('properties', {})
        if properties is not None:
            if not isinstance(properties, dict):
                raise VertexGeminiError(f'response schema properties must be an object: {path}')
            for key, child in properties.items():
                visit(child, f'{path}.properties.{key}')
        if 'items' in value:
            visit(value['items'], f'{path}.items')
    if not isinstance(schema, dict) or not schema:
        raise VertexGeminiError('response schema must be a non-empty object')
    visit(schema, '$')

@dataclass(frozen=True)
class VertexGeminiFlashClient:
    project_id: str = DEFAULT_PROJECT_ID
    timeout_seconds: float = 120.0
    total_attempts: int = TOTAL_ATTEMPTS
    token_provider: TokenProvider = gcloud_access_token
    transport: Transport = urllib_transport
    sleeper: Sleeper = time.sleep

    def __post_init__(self) -> None:
        if not PROJECT_ID_PATTERN.fullmatch(self.project_id):
            raise VertexGeminiError(f'invalid Google Cloud project id: {self.project_id}')
        if self.timeout_seconds <= 0:
            raise VertexGeminiError('timeout_seconds must be positive')
        if not 1 <= self.total_attempts <= TOTAL_ATTEMPTS:
            raise VertexGeminiError(f'total_attempts must be between 1 and {TOTAL_ATTEMPTS}')

    @property
    def model_identity(self) -> dict[str, str]:
        return {'provider': 'google-cloud-vertex-ai', 'model': MODEL_ID, 'version': MODEL_RELEASE_DATE, 'execution_environment': 'VERTEX_AI_MANAGED', 'location': LOCATION, 'thinking_level': THINKING_LEVEL}

    def _url(self, method: str) -> str:
        if method not in {'countTokens', 'generateContent'}:
            raise VertexGeminiError(f'unsupported Vertex AI method: {method}')
        return f'https://aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{LOCATION}/publishers/google/models/{MODEL_ID}:{method}'

    def _post(self, method: str, body: dict[str, Any], *, preserve_wire=False):
        payload = _json_bytes(body)
        last_status: int | None = None
        last_detail = 'request did not complete'
        for attempt in range(1, self.total_attempts + 1):
            token = self.token_provider()
            headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json; charset=utf-8', 'User-Agent': 'reqlox-gemini-flash-v1'}
            status, response_payload = self.transport(self._url(method), headers, payload, self.timeout_seconds)
            last_status = status
            if 200 <= status < 300:
                try:
                    value = json.loads(response_payload)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise VertexGeminiError('Vertex AI returned invalid JSON', provider_response_payload=response_payload) from exc
                if not isinstance(value, dict):
                    raise VertexGeminiError('Vertex AI returned a non-object response', provider_response_payload=response_payload)
                return (value, response_payload) if preserve_wire else value
            last_detail = _safe_error_message(response_payload)
            if status not in RETRYABLE_HTTP_STATUS or attempt == self.total_attempts:
                break
            self.sleeper(min(2 ** (attempt - 1), 4))
        raise VertexGeminiError(f'Vertex AI {method} failed with HTTP {last_status}', provider_response_payload=response_payload)

    @staticmethod
    def _content(prompt: str) -> list[dict[str, Any]]:
        if not prompt.strip():
            raise VertexGeminiError('prompt must not be empty')
        return [{'role': 'USER', 'parts': [{'text': prompt}]}]

    @staticmethod
    def _system_instruction(value: str) -> dict[str, Any]:
        if not value.strip():
            raise VertexGeminiError('system instruction must not be empty')
        return {'parts': [{'text': value}]}

    def count_tokens(self, *, prompt: str, system_instruction: str) -> int:
        response = self._post('countTokens', {'contents': self._content(prompt), 'systemInstruction': self._system_instruction(system_instruction)})
        total = response.get('totalTokens')
        if not isinstance(total, int) or total < 1:
            raise VertexGeminiError('countTokens response is missing totalTokens')
        return total

    def generate_structured(self, *, prompt: str, system_instruction: str, response_schema: dict[str, Any], max_output_tokens: int) -> dict[str, Any]:
        if not isinstance(response_schema, dict) or not response_schema:
            raise VertexGeminiError('response_schema must be a non-empty object')
        validate_vertex_response_schema(response_schema)
        if not 1 <= max_output_tokens <= 65536:
            raise VertexGeminiError('max_output_tokens is outside the model limit')
        response, response_payload = self._post('generateContent', {'contents': self._content(prompt), 'systemInstruction': self._system_instruction(system_instruction), 'generationConfig': {'maxOutputTokens': max_output_tokens, 'responseMimeType': 'application/json', 'responseSchema': response_schema, 'thinkingConfig': {'thinkingLevel': THINKING_LEVEL}}}, preserve_wire=True)
        candidates = response.get('candidates')
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise VertexGeminiError('expected exactly one Vertex AI candidate', provider_response_payload=response_payload)
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise VertexGeminiError('Vertex AI candidate is not an object', provider_response_payload=response_payload)
        finish_reason = candidate.get('finishReason')
        if finish_reason != 'STOP':
            raise VertexGeminiResponseError(f'Vertex AI response did not finish normally: {finish_reason}', provider_response=response, provider_response_payload=response_payload)
        content = candidate.get('content')
        parts = content.get('parts') if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise VertexGeminiError('Vertex AI response is missing content parts', provider_response_payload=response_payload)
        texts = [part['text'] for part in parts if isinstance(part, dict) and isinstance(part.get('text'), str) and (not part.get('thought', False))]
        if len(texts) != 1:
            raise VertexGeminiError('expected one structured-output text part', provider_response_payload=response_payload)
        try:
            output = json.loads(texts[0])
        except json.JSONDecodeError as exc:
            raise VertexGeminiError('structured output is not valid JSON', provider_response_payload=response_payload) from exc
        if not isinstance(output, dict):
            raise VertexGeminiError('structured output must be a JSON object', provider_response_payload=response_payload)
        return {'output': output, 'model_version': response.get('modelVersion'), 'response_id': response.get('responseId'), 'create_time': response.get('createTime'), 'usage_metadata': response.get('usageMetadata', {}), 'finish_reason': finish_reason, 'provider_response': response, '_provider_response_payload': response_payload}
