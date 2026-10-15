"""Reusable observed v2 methods from the development implementation."""
import copy
from . import observed as previous
from .reference import require
PURPOSE = 'observed_event_atomicity'
ATOMIC = 'ATOMIC_OBSERVATION'
NON_ATOMIC = 'NON_ATOMIC_OR_NOT_OBSERVED'
UNKNOWN = 'INSUFFICIENT_INFORMATION'
CHOICES = [ATOMIC, UNKNOWN, NON_ATOMIC]
RUBRIC = dict(choices=CHOICES, instructions='Evaluate only this candidate assertion and its own source quotations. Assess structural event atomicity, separately from whether the words are quoted accurately. An accurately quoted compound of two actions is still NON_ATOMIC_OR_NOT_OBSERVED. Do not treat one predicate string containing two verbs as one event. Report one source-reported actual occurrence or observed condition with one predicate and necessary arguments. Actual observed conditions are permitted; a component taxonomy, general rule or hypothetical advice is not an observed occurrence. Do not classify technology or decide incident membership, applicability or causality.', criteria={ATOMIC: 'One source-reported actual observed occurrence or condition, one predicate with necessary arguments.', NON_ATOMIC: 'Multiple independent actions or events combined, or only taxonomy, classification, hypothetical statement or general advice.', UNKNOWN: 'The candidate or its own evidence does not permit an atomicity decision.'})

def adapt(row):
    value = copy.deepcopy(row)
    value['purpose'] = PURPOSE
    value['choices'] = CHOICES
    assertion = value['input']['claim_atom']['arguments'][0]['value']
    value['input'] = dict(source_document_sha256=value['input']['source_document_sha256'], candidate_assertion=assertion, evidence_spans=value['input']['evidence_spans'])
    return value

def requests(candidate):
    return [adapt(r) for r in previous.requests(candidate)]

def controls():
    rows, key = previous.controls()
    mapping = {'ENTAILED': ATOMIC, 'CONTRADICTED': NON_ATOMIC, 'INSUFFICIENT_INFORMATION': UNKNOWN}
    return ([adapt(r) for r in rows], {sid: dict(wanted=mapping[v['wanted']], purpose=PURPOSE) for sid, v in key.items()})

def positive(answer):
    return answer['choice'] == ATOMIC and min(answer['confidence'], answer['probabilities'][ATOMIC]) >= 0.85

def control_assessment(key, answers):
    first = {sid: answers[sid][0] for sid in key if answers.get(sid)}
    false_accepts = sum((label['wanted'] != ATOMIC and positive(a) for sid, label in key.items() for a in answers.get(sid, [])))
    return dict(first_pass_accuracy=sum((a['choice'] == key[sid]['wanted'] for sid, a in first.items())) / len(key) if first else None, false_accepts=false_accepts, gate_passed=all((len(answers.get(sid, [])) == 3 for sid in key)) and false_accepts == 0)

def project(candidate, fidelity_projection, rows, answers, *, controls_pass):
    require(all((row['purpose'] == PURPOSE and row['choices'] == CHOICES for row in rows)), 'ATOMICITY_V2_PURPOSE')
    mapping = {ATOMIC: 'ENTAILED', NON_ATOMIC: 'CONTRADICTED', UNKNOWN: 'INSUFFICIENT_INFORMATION'}
    translated = {}
    for row in rows:
        translated[row['id']] = [dict(choice=mapping[a['choice']], confidence=a['confidence'], probabilities={mapping[k]: v for k, v in a['probabilities'].items()}) for a in answers.get(row['id'], [])]
    return previous.project(candidate, fidelity_projection, rows, translated, controls_pass=controls_pass)
