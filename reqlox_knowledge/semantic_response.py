"""Reusable semantic response methods from the development implementation."""
from copy import deepcopy
from . import reference as c

def fingerprint(answer):
    try:
        return c.digest(answer)
    except (ValueError, TypeError):
        return None

def check(answer, categories):
    c.require('UNRESOLVED' in categories, 'SEMANTIC_RESPONSE_UNRESOLVED_CATEGORY')
    if not isinstance(answer, dict):
        return dict(status='MISSING_ANSWER', accepted='UNRESOLVED', choice=None, probabilities=None, model_execution_authority=False)
    raw_choice = answer.get('choice')
    choice = raw_choice if type(raw_choice) is str else None
    if choice is not None:
        try:
            choice.encode()
        except UnicodeError:
            choice = None
    try:
        p = c.probabilities(answer.get('probabilities'), categories)
    except (ValueError, TypeError, OverflowError):
        return dict(status='INVALID_PROBABILITY_VECTOR', accepted='UNRESOLVED', choice=choice, probabilities=None, raw_answer_sha256=fingerprint(answer), model_execution_authority=False)
    status = 'VALID' if type(choice) is str and choice in p and (p[choice] == max(p.values())) else 'INVALID_CHOICE_ARGMAX'
    accepted = choice if status == 'VALID' and p[choice] >= c.FLOOR else 'UNRESOLVED'
    return dict(status=status, accepted=accepted, choice=choice, probabilities=deepcopy(p), raw_answer_sha256=fingerprint(answer), probability_vector_preserved=True, choice_repaired=False, model_execution_authority=False)
