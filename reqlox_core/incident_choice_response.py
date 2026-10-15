"Keep decision abstention separate from the finite truth categories."
from copy import deepcopy

from . import incident_reference as c
from . import incident_provider_scores as provider
from .incident_semantic_response import fingerprint


def check(answer, categories):
    c.require(type(categories) in (tuple, list) and 2 <= len(categories) <= 64
              and all(type(k) is str and k for k in categories) and len(set(categories)) == len(categories),
              'CHOICE_RESPONSE_CATEGORIES')
    probabilities = provider.categorical_vector(answer, categories)
    raw_choice = answer.get('choice') if type(answer) is dict else None
    choice = raw_choice if type(raw_choice) is str else None
    if choice is not None:
        try:
            choice.encode()
        except UnicodeError:
            choice = None
    status = ('MISSING_ANSWER' if type(answer) is not dict else
              'INVALID_PROBABILITY_VECTOR' if probabilities is None else
              'VALID' if choice in probabilities and probabilities[choice] == max(probabilities.values()) else
              'INVALID_CHOICE_ARGMAX')
    accepted = choice if status == 'VALID' and probabilities[choice] >= c.FLOOR else None
    return dict(status=status, choice=choice, accepted=accepted,
                decision_status='ACCEPTED' if accepted is not None else 'ABSTAINED',
                probabilities=deepcopy(probabilities), raw_answer_sha256=fingerprint(answer),
                probability_vector_preserved=probabilities is not None, choice_repaired=False,
                abstention_is_not_a_truth_category=True, execution_authority=False)
