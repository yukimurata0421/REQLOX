"""Reusable judge client methods from the development implementation."""
from __future__ import annotations
import json
import os
import stat
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
PINNED_MODEL = 'jev-1.13.0'
PROBABILITY_EXACT_TOLERANCE = 1e-06
PROBABILITY_ROUNDING_TOLERANCE = 0.02

class JevSystemOneError(RuntimeError):
    """Fail-closed credential, transport, or provider-response error."""

    def __init__(self, message: str, *, http_status: int | None=None, retryable: bool=False, retry_after_seconds: float | None=None, provider_response_payload: bytes | None=None) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.provider_response_payload = provider_response_payload
Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes, dict[str, str]]]

def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def api_key(*, key_file: Path | None=None) -> str:
    if key_file is None:
        value = os.getenv('TYPESAFE_API_KEY', '').strip()
    else:
        path = Path(key_file).expanduser().absolute()
        if path.resolve() != path or any(p.is_symlink() for p in (path, *path.parents)):
            raise JevSystemOneError('API key path must not contain links or traversal')
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                    raise JevSystemOneError('API key file must be private and owned by the current user')
                value = stream.read(4097).decode('utf-8').strip()
        except (OSError, UnicodeError) as exc:
            raise JevSystemOneError('API key file could not be read') from exc
    if not value or len(value.encode()) > 4096 or '\n' in value or '\r' in value:
        raise JevSystemOneError('TypeSafe API key file must contain one non-empty line')
    return value

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def urllib_transport(url: str, headers: dict[str, str], payload: bytes, timeout: float) -> tuple[int, bytes, dict[str, str]]:
    request = urllib.request.Request(url=url, data=payload, headers=headers, method='POST')
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                raise JevSystemOneError('Provider response exceeds the byte limit')
            return (int(response.status), body, dict(response.headers.items()))
    except urllib.error.HTTPError as exc:
        return (int(exc.code), exc.read(2 * 1024 * 1024), dict(exc.headers.items()))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise JevSystemOneError('TypeSafe System One transport failed', retryable=True) from exc

def retry_after_seconds(headers: dict[str, str]) -> float | None:
    raw = next((value for name, value in headers.items() if name.lower() == 'retry-after'), None)
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None

def safe_provider_error(payload: bytes) -> str:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 'unparseable provider error'
    if not isinstance(value, dict):
        return 'non-object provider error'
    error = value.get('error')
    if isinstance(error, dict):
        code = str(error.get('code', error.get('type', 'UNKNOWN')))[:80]
        message = str(error.get('message', ''))[:400]
        return f'{code}: {message}' if message else code
    return str(value.get('message', 'provider error without structured detail'))[:400]

def validate_choice_answer(answer: Any, *, criteria: dict[str, Any], question_id: str) -> dict[str, Any]:
    if not isinstance(answer, dict) or answer.get('type') != 'choice':
        raise JevSystemOneError(f'{question_id}: expected a Choice answer')
    choice = answer.get('choice')
    probabilities = answer.get('probabilities')
    confidence = answer.get('confidence')
    if choice not in criteria:
        raise JevSystemOneError(f'{question_id}: choice is outside the bounded criteria')
    if not isinstance(probabilities, dict) or set(probabilities) != set(criteria):
        raise JevSystemOneError(f'{question_id}: probability coverage mismatch')
    if any((isinstance(value, bool) or not isinstance(value, (int, float)) or (not 0 <= float(value) <= 1) for value in probabilities.values())):
        raise JevSystemOneError(f'{question_id}: probability is outside [0, 1]')
    provider_probabilities = {key: float(probabilities[key]) for key in criteria}
    provider_sum = sum(provider_probabilities.values())
    if provider_sum <= 0 or abs(provider_sum - 1.0) > PROBABILITY_ROUNDING_TOLERANCE:
        raise JevSystemOneError(f'{question_id}: probabilities do not sum to one')
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or (not 0 <= float(confidence) <= 1):
        raise JevSystemOneError(f'{question_id}: confidence is outside [0, 1]')
    normalization_applied = abs(provider_sum - 1.0) > PROBABILITY_EXACT_TOLERANCE
    normalized = {key: value / provider_sum for key, value in provider_probabilities.items()} if normalization_applied else provider_probabilities
    return {'type': 'choice', 'choice': choice, 'probabilities': normalized, 'confidence': float(confidence), 'provider_probabilities': provider_probabilities, 'provider_probability_sum': provider_sum, 'normalization_applied': normalization_applied}

@dataclass(frozen=True)
class JevSystemOneClient:
    key: str = field(repr=False)
    endpoint: str = ENDPOINT
    model: str = PINNED_MODEL
    timeout_seconds: float = 120.0
    transport: Transport = urllib_transport

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise JevSystemOneError('TypeSafe API key is empty')
        if self.endpoint != ENDPOINT:
            raise JevSystemOneError('unapproved TypeSafe endpoint')
        if self.model != PINNED_MODEL:
            raise JevSystemOneError('Jev model must be pinned to jev-1.13.0')
        if self.timeout_seconds <= 0:
            raise JevSystemOneError('timeout_seconds must be positive')

    @property
    def model_identity(self) -> dict[str, Any]:
        return {'provider': 'typesafe-ai', 'api': 'system-one-v1', 'model': 'jev', 'version': self.model, 'endpoint': self.endpoint, 'execution_environment': 'TYPESAFE_MANAGED_API'}

    def evaluate(self, *, state: dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        if not state or not questions:
            raise JevSystemOneError('state and questions must be non-empty')
        body = {'state': state, 'model': self.model, 'questions': questions}
        request_payload = canonical_json_bytes(body)
        status, payload, headers = self.transport(self.endpoint, {'Authorization': f'Bearer {self.key}', 'Content-Type': 'application/json; charset=utf-8', 'User-Agent': 'reqlox-jev-incident-judge-v1'}, request_payload, self.timeout_seconds)
        if not 200 <= status < 300:
            raise JevSystemOneError(f'TypeSafe System One call failed with HTTP {status}', http_status=status, retryable=status in {429, 529}, retry_after_seconds=retry_after_seconds(headers), provider_response_payload=payload)
        try:
            response = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JevSystemOneError('TypeSafe returned invalid JSON', http_status=status, provider_response_payload=payload) from exc
        if not isinstance(response, dict):
            raise JevSystemOneError('TypeSafe returned a non-object response', http_status=status, provider_response_payload=payload)
        if response.get('model') != self.model:
            raise JevSystemOneError('TypeSafe response model does not match the pinned model', http_status=status, provider_response_payload=payload)
        answers = response.get('answers')
        if not isinstance(answers, dict) or set(answers) != set(questions):
            raise JevSystemOneError('TypeSafe answer coverage mismatch', http_status=status, provider_response_payload=payload)
        try:
            validated_answers = {question_id: validate_choice_answer(answers[question_id], criteria=question['criteria'], question_id=question_id) for question_id, question in questions.items()}
        except JevSystemOneError as exc:
            raise JevSystemOneError(str(exc), http_status=status, provider_response_payload=payload) from exc
        usage = response.get('usage')
        if not isinstance(usage, dict) or isinstance(usage.get('input_tokens'), bool) or (not isinstance(usage.get('input_tokens'), int)) or (usage['input_tokens'] < 0) or isinstance(usage.get('output_tokens'), bool) or (not isinstance(usage.get('output_tokens'), int)) or (usage['output_tokens'] < 0):
            raise JevSystemOneError('TypeSafe response usage is invalid', http_status=status, provider_response_payload=payload)
        return {'model': response['model'], 'answers': validated_answers, 'usage': {'input_tokens': usage['input_tokens'], 'output_tokens': usage['output_tokens']}, 'request_id': response.get('request_id'), '_provider_request_payload': request_payload, '_provider_response_payload': payload}

def replay_response(*, payload: bytes, state: dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Validate and materialize a previously captured response without network I/O."""

    def stored_transport(url: str, headers: dict[str, str], request_payload: bytes, timeout: float) -> tuple[int, bytes, dict[str, str]]:
        del url, headers, request_payload, timeout
        return (200, payload, {})
    return JevSystemOneClient(key='LOCAL_REPLAY_ONLY', transport=stored_transport).evaluate(state=state, questions=questions)
