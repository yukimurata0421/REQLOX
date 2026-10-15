"""Reusable hybrid methods from the development implementation."""
from __future__ import annotations
import hashlib
import json
import math
import re
from collections import Counter
import numpy as np
MODEL_ID = 'local-hashed-tfidf-facet'
MODEL_VERSION = '1.0.0'
TOKENIZER_VERSION = 'incident-word-bigram-ja-alias.v1'
HASH_ALGORITHM = 'blake2b-72'
DEFAULT_DIMENSION = 768
WORD_RE = re.compile('[a-z0-9]+(?:[._:/+-][a-z0-9]+)*', re.IGNORECASE)
CJK_RE = re.compile('[\\u3040-\\u30ff\\u3400-\\u9fff]{2,}')
NON_ALNUM_RE = re.compile('[^a-z0-9]+')
SEMANTIC_ALIASES = {'failure_domains.application': ['application', 'app', '\u30a2\u30d7\u30ea', '\u30a2\u30d7\u30ea\u30b1\u30fc\u30b7\u30e7\u30f3'], 'failure_domains.cache': ['cache', 'redis', 'memcached', '\u30ad\u30e3\u30c3\u30b7\u30e5'], 'failure_domains.compute_runtime': ['compute', 'runtime', 'process', 'vm', '\u30b3\u30f3\u30d4\u30e5\u30fc\u30c8', '\u30d7\u30ed\u30bb\u30b9'], 'failure_domains.database': ['database', 'db', 'mysql', 'postgres', '\u30c7\u30fc\u30bf\u30d9\u30fc\u30b9'], 'failure_domains.dns_service_discovery': ['dns', 'service discovery', '\u540d\u524d\u89e3\u6c7a', '\u30b5\u30fc\u30d3\u30b9\u30c7\u30a3\u30b9\u30ab\u30d0\u30ea'], 'failure_domains.identity_access': ['identity', 'authentication', 'iam', '\u8a8d\u8a3c', '\u8a8d\u53ef', '\u30a2\u30a4\u30c7\u30f3\u30c6\u30a3\u30c6\u30a3'], 'failure_domains.kubernetes_control_plane': ['kubernetes', 'k8s', 'control plane', '\u30b3\u30f3\u30c8\u30ed\u30fc\u30eb\u30d7\u30ec\u30fc\u30f3'], 'failure_domains.load_balancer_proxy': ['load balancer', 'proxy', '\u30ed\u30fc\u30c9\u30d0\u30e9\u30f3\u30b5', '\u30d7\u30ed\u30ad\u30b7'], 'failure_domains.network_routing': ['network', 'routing', 'bgp', '\u30cd\u30c3\u30c8\u30ef\u30fc\u30af', '\u30eb\u30fc\u30c6\u30a3\u30f3\u30b0'], 'failure_domains.observability': ['observability', 'monitoring', 'telemetry', '\u53ef\u89b3\u6e2c\u6027', '\u76e3\u8996'], 'failure_domains.power_facility': ['power', 'facility', '\u96fb\u6e90', '\u8a2d\u5099'], 'failure_domains.queue_scheduler': ['queue', 'scheduler', 'job backlog', '\u30ad\u30e5\u30fc', '\u30b9\u30b1\u30b8\u30e5\u30fc\u30e9'], 'failure_domains.storage': ['storage', 'disk', 'filesystem', '\u30b9\u30c8\u30ec\u30fc\u30b8', '\u30c7\u30a3\u30b9\u30af'], 'failure_domains.third_party_dependency': ['dependency', 'third party', '\u4f9d\u5b58', '\u5916\u90e8\u30b5\u30fc\u30d3\u30b9'], 'failure_domains.time_clock': ['clock', 'time', 'leap second', '\u6642\u523b', '\u6642\u8a08', '\u3046\u308b\u3046\u79d2'], 'mechanisms.cache_expiry_or_staleness': ['stale cache', 'cache expiry', '\u30ad\u30e3\u30c3\u30b7\u30e5\u671f\u9650', '\u53e4\u3044\u30ad\u30e3\u30c3\u30b7\u30e5'], 'mechanisms.cascading_failure': ['cascade', 'cascading failure', '\u9023\u9396\u969c\u5bb3', '\u30ab\u30b9\u30b1\u30fc\u30c9\u969c\u5bb3'], 'mechanisms.configuration_propagation': ['configuration propagation', 'config propagation', '\u8a2d\u5b9a\u4f1d\u64ad'], 'mechanisms.data_loss_or_corruption': ['data loss', 'corruption', '\u30c7\u30fc\u30bf\u640d\u5931', '\u30c7\u30fc\u30bf\u7834\u640d'], 'mechanisms.deadlock_or_race': ['deadlock', 'race condition', '\u30c7\u30c3\u30c9\u30ed\u30c3\u30af', '\u7af6\u5408\u72b6\u614b'], 'mechanisms.dependency_coupling': ['dependency coupling', 'coupled dependency', '\u4f9d\u5b58\u95a2\u4fc2', '\u5bc6\u7d50\u5408'], 'mechanisms.failover_failure': ['failover failure', 'failed failover', 'failover failed', '\u30d5\u30a7\u30a4\u30eb\u30aa\u30fc\u30d0\u30fc\u5931\u6557'], 'mechanisms.overload_saturation': ['overload', 'saturation', 'over capacity', '\u904e\u8ca0\u8377', '\u98fd\u548c'], 'mechanisms.quota_or_limit_exhaustion': ['quota', 'limit exhausted', '\u4e0a\u9650\u5230\u9054', '\u30af\u30a9\u30fc\u30bf'], 'mechanisms.resource_exhaustion': ['resource exhaustion', 'out of memory', '\u30ea\u30bd\u30fc\u30b9\u67af\u6e07', '\u30e1\u30e2\u30ea\u4e0d\u8db3'], 'mechanisms.retry_amplification': ['retry storm', 'retry amplification', '\u518d\u8a66\u884c\u5897\u5e45', '\u30ea\u30c8\u30e9\u30a4\u30b9\u30c8\u30fc\u30e0'], 'mechanisms.rollback_failure': ['rollback failed', 'rollback failure', '\u30ed\u30fc\u30eb\u30d0\u30c3\u30af\u5931\u6557'], 'mechanisms.split_brain_conflicting_state': ['split brain', 'conflicting state', '\u30b9\u30d7\u30ea\u30c3\u30c8\u30d6\u30ec\u30a4\u30f3', '\u72b6\u614b\u7af6\u5408'], 'trigger_categories.configuration_change': ['configuration change', 'config change', '\u8a2d\u5b9a\u5909\u66f4'], 'trigger_categories.credential_or_certificate_lifecycle': ['certificate', 'credential', '\u8a3c\u660e\u66f8', '\u8cc7\u683c\u60c5\u5831'], 'trigger_categories.dependency_failure': ['dependency failure', '\u4f9d\u5b58\u5148\u969c\u5bb3'], 'trigger_categories.hardware_failure': ['hardware failure', 'hardware fault', '\u30cf\u30fc\u30c9\u30a6\u30a7\u30a2\u969c\u5bb3'], 'trigger_categories.infrastructure_maintenance': ['maintenance', '\u30e1\u30f3\u30c6\u30ca\u30f3\u30b9', '\u4fdd\u5b88\u4f5c\u696d'], 'trigger_categories.operator_action': ['operator error', 'human error', '\u64cd\u4f5c\u30df\u30b9', '\u4eba\u70ba\u30df\u30b9'], 'trigger_categories.power_loss': ['power loss', 'power outage', '\u505c\u96fb', '\u96fb\u6e90\u65ad'], 'trigger_categories.schema_migration': ['schema migration', 'database migration', '\u30b9\u30ad\u30fc\u30de\u79fb\u884c'], 'trigger_categories.security_event': ['security event', 'attack', 'ddos', '\u653b\u6483', '\u30bb\u30ad\u30e5\u30ea\u30c6\u30a3'], 'trigger_categories.software_release': ['deployment', 'software release', 'rollout', '\u30c7\u30d7\u30ed\u30a4', '\u30ea\u30ea\u30fc\u30b9'], 'trigger_categories.time_event': ['time event', 'leap second', '\u6642\u523b\u30a4\u30d9\u30f3\u30c8', '\u3046\u308b\u3046\u79d2'], 'trigger_categories.traffic_or_load_spike': ['traffic spike', 'load spike', '\u30c8\u30e9\u30d5\u30a3\u30c3\u30af\u6025\u5897', '\u8ca0\u8377\u6025\u5897'], 'impacts.authentication_or_access_failure': ['authentication failure', 'access denied', '\u8a8d\u8a3c\u5931\u6557', '\u30a2\u30af\u30bb\u30b9\u4e0d\u80fd'], 'impacts.data_corruption': ['data corruption', '\u30c7\u30fc\u30bf\u7834\u640d'], 'impacts.data_loss': ['data loss', '\u30c7\u30fc\u30bf\u640d\u5931'], 'impacts.degraded_performance': ['degraded performance', 'latency', '\u6027\u80fd\u52a3\u5316', '\u9045\u5ef6'], 'impacts.delayed_or_stuck_work': ['stuck jobs', 'delayed jobs', '\u51e6\u7406\u9045\u5ef6', '\u30b8\u30e7\u30d6\u505c\u6b62'], 'impacts.elevated_errors': ['elevated errors', 'error rate', '\u30a8\u30e9\u30fc\u7387', '\u30a8\u30e9\u30fc\u5897\u52a0'], 'impacts.incorrect_results': ['incorrect result', 'wrong result', '\u8aa4\u7d50\u679c', '\u4e0d\u6b63\u306a\u7d50\u679c'], 'impacts.observability_loss': ['monitoring loss', 'telemetry loss', '\u76e3\u8996\u4e0d\u80fd'], 'impacts.unavailability': ['unavailable', 'outage', 'downtime', '\u5229\u7528\u4e0d\u80fd', '\u505c\u6b62', '\u969c\u5bb3'], 'recovery_patterns.failover': ['failover', '\u30d5\u30a7\u30a4\u30eb\u30aa\u30fc\u30d0\u30fc'], 'recovery_patterns.restart_or_redeploy': ['restart', 'redeploy', '\u518d\u8d77\u52d5', '\u518d\u30c7\u30d7\u30ed\u30a4'], 'recovery_patterns.restore_from_backup': ['restore backup', 'restore from backup', '\u30d0\u30c3\u30af\u30a2\u30c3\u30d7\u5fa9\u5143'], 'recovery_patterns.rollback_or_revert': ['rollback', 'revert', '\u30ed\u30fc\u30eb\u30d0\u30c3\u30af', '\u5207\u308a\u623b\u3057'], 'recovery_patterns.traffic_shift_or_shedding': ['traffic shift', 'load shedding', '\u30c8\u30e9\u30d5\u30a3\u30c3\u30af\u5207\u66ff', '\u8ca0\u8377\u906e\u65ad'], 'candidate_injection_primitives.connection_or_worker_exhaustion': ['connection exhaustion', 'worker exhaustion', '\u63a5\u7d9a\u67af\u6e07', '\u30ef\u30fc\u30ab\u30fc\u67af\u6e07'], 'candidate_injection_primitives.cpu_pressure': ['cpu pressure', 'cpu load', 'cpu\u8ca0\u8377'], 'candidate_injection_primitives.database_failover_or_lock': ['database failover', 'database lock', 'db failover', 'db\u30ed\u30c3\u30af'], 'candidate_injection_primitives.dependency_error_or_latency': ['dependency latency', 'dependency error', '\u4f9d\u5b58\u5148\u9045\u5ef6', '\u4f9d\u5b58\u5148\u30a8\u30e9\u30fc'], 'candidate_injection_primitives.disk_or_storage_fault': ['disk fault', 'storage fault', '\u30c7\u30a3\u30b9\u30af\u969c\u5bb3', '\u30b9\u30c8\u30ec\u30fc\u30b8\u969c\u5bb3'], 'candidate_injection_primitives.dns_failure': ['dns failure', 'dns outage', 'dns\u969c\u5bb3', '\u540d\u524d\u89e3\u6c7a\u5931\u6557'], 'candidate_injection_primitives.memory_pressure': ['memory pressure', '\u30e1\u30e2\u30ea\u8ca0\u8377'], 'candidate_injection_primitives.network_partition_or_packet_loss': ['network partition', 'packet loss', '\u30cd\u30c3\u30c8\u30ef\u30fc\u30af\u5206\u65ad', '\u30d1\u30b1\u30c3\u30c8\u30ed\u30b9'], 'candidate_injection_primitives.queue_backlog': ['queue backlog', '\u30ad\u30e5\u30fc\u6ede\u7559'], 'candidate_injection_primitives.rate_or_quota_limit': ['rate limit', 'quota limit', '\u30ec\u30fc\u30c8\u5236\u9650', '\u30af\u30a9\u30fc\u30bf\u5236\u9650'], 'candidate_injection_primitives.route_withdrawal_or_leak': ['route leak', 'route withdrawal', '\u7d4c\u8def\u30ea\u30fc\u30af', '\u7d4c\u8def\u64a4\u56de'], 'candidate_injection_primitives.zone_or_power_loss': ['zone failure', 'power loss', '\u30be\u30fc\u30f3\u969c\u5bb3', '\u96fb\u6e90\u65ad']}

def semantic_token(field: str, value: str) -> str:
    return 'facet' + NON_ALNUM_RE.sub('', field.lower()) + 'x' + NON_ALNUM_RE.sub('', value.lower())

def lexical_tokens(text: str) -> list[str]:
    lowered = text.lower()
    words = [value for value in WORD_RE.findall(lowered) if len(value) > 1]
    cjk = CJK_RE.findall(lowered)
    return words + cjk

def query_semantic_tokens(query: str, aliases: dict[str, list[str]] | None=None) -> list[str]:
    aliases = aliases or SEMANTIC_ALIASES
    lowered = query.lower()
    matched = []
    for key, values in aliases.items():
        if any((value.lower() in lowered for value in values)):
            field, facet = key.split('.', 1)
            matched.append(semantic_token(field, facet))
    return sorted(set(matched))

def document_semantic_tokens(facets: dict[str, list[str]], claim_categories: list[str]) -> list[str]:
    values = [semantic_token(field, value) for field, items in facets.items() for value in items]
    values.extend(('claim' + NON_ALNUM_RE.sub('', value.lower()) for value in claim_categories))
    return sorted(set(values))

def weighted_features(text: str, title: str='', semantic_tokens: list[str] | None=None) -> Counter[str]:
    counts: Counter[str] = Counter()
    body = lexical_tokens(text)
    counts.update(body)
    for left, right in zip(body, body[1:]):
        counts['bigram:' + left + '_' + right] += 0.5
    for token in lexical_tokens(title):
        counts['title:' + token] += 3.0
    for token in semantic_tokens or []:
        counts['semantic:' + token] += 4.0
    return counts

def bucket_for(token: str, dimension: int) -> tuple[int, float]:
    digest = hashlib.blake2b(token.encode('utf-8'), digest_size=9).digest()
    bucket = int.from_bytes(digest[:8], 'big') % dimension
    sign = 1.0 if digest[8] & 1 else -1.0
    return (bucket, sign)

def bucket_counts(features: Counter[str], dimension: int) -> dict[int, float]:
    result: dict[int, float] = {}
    for token, weight in features.items():
        bucket, sign = bucket_for(token, dimension)
        result[bucket] = result.get(bucket, 0.0) + float(weight) * sign
    return {key: value for key, value in result.items() if value}

def idf_from_document_frequencies(document_frequencies: np.ndarray, count: int) -> np.ndarray:
    return (np.log((1.0 + count) / (1.0 + document_frequencies)) + 1.0).astype(np.float32)

def vector_from_features(features: Counter[str], dimension: int, idf: np.ndarray) -> np.ndarray:
    vector = np.zeros(dimension, dtype=np.float32)
    for bucket, value in bucket_counts(features, dimension).items():
        vector[bucket] = math.copysign(math.log1p(abs(value)), value) * idf[bucket]
    norm = float(np.linalg.norm(vector))
    if norm:
        vector /= norm
    return vector

def query_vector(query: str, config: dict, idf: np.ndarray) -> np.ndarray:
    semantic = query_semantic_tokens(query, config['semantic_aliases'])
    semantic_with_document = semantic + ['document' + value for value in semantic]
    features = weighted_features(query, semantic_tokens=semantic_with_document)
    return vector_from_features(features, config['dimension'], idf)

def split_text_windows(text: str, max_characters: int, overlap_characters: int) -> list[tuple[int, int, str]]:
    if max_characters < 100 or overlap_characters < 0 or overlap_characters >= max_characters:
        raise ValueError('invalid chunk size/overlap')
    windows = []
    start = 0
    length = len(text.rstrip())
    while start < length:
        while start < length and text[start].isspace():
            start += 1
        if start >= length:
            break
        if windows and length - start < max_characters:
            adjusted = max(0, length - max_characters)
            if adjusted > windows[-1][0]:
                start = adjusted
        hard_end = min(length, start + max_characters)
        end = hard_end
        if hard_end < length:
            floor = start + max_characters * 3 // 5
            segment = text[floor:hard_end]
            boundaries = [segment.rfind(marker) for marker in ('\n', '. ', '? ', '! ', '; ')]
            boundary = max(boundaries)
            if boundary >= 0:
                marker_length = 1 if segment[boundary] == '\n' else 1
                end = floor + boundary + marker_length
        while end > start and text[end - 1].isspace():
            end -= 1
        if end <= start:
            end = hard_end
        chunk = text[start:end]
        windows.append((start, end, chunk))
        if end >= length:
            break
        next_start = max(start + 1, end - overlap_characters)
        whitespace = text.find(' ', next_start, min(length, next_start + 80))
        start = whitespace + 1 if whitespace >= 0 else next_start
    return windows

def aliases_sha256(aliases: dict[str, list[str]] | None=None) -> str:
    payload = json.dumps(aliases or SEMANTIC_ALIASES, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()
