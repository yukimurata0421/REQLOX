"Reject repaired probability vectors from raw forecast evaluation."
from copy import deepcopy
from . import incident_reference as c
from . import incident_semantic_response as previous


def raw_answers(answers):
    c.require(type(answers) is dict,'PROVIDER_SCORE_ANSWERS')
    rejected=[];result={}
    for key,value in answers.items():
        flag=value.get('normalization_applied',False) if type(value) is dict else False
        if type(flag) is not bool or flag:
            rejected.append(key)
        else:result[key]=deepcopy(value)
    return result,rejected


def check(answer,categories):
    clean,rejected=raw_answers({'answer':answer})
    if rejected:
        return dict(status='PROVIDER_NORMALIZATION_NOT_ADOPTED',accepted='UNRESOLVED',choice=None,
            probabilities=None,raw_answer_sha256=previous.fingerprint(answer),probability_repaired=False,
            model_execution_authority=False)
    return previous.check(clean['answer'],categories)


def categorical_vector(answer,categories):
    clean,rejected=raw_answers({'answer':answer})
    if rejected:return None
    value=clean['answer']
    try:return c.probabilities(value.get('probabilities') if type(value) is dict else None,categories)
    except (ValueError,TypeError,OverflowError):return None


def coverage_evaluate(evaluator,request,answers,**kwargs):
    clean,rejected=raw_answers(answers)
    metric=evaluator(request,clean,**kwargs);metric.pop('record_sha256')
    return c.seal(dict(**metric,normalized_provider_vectors_rejected=rejected,
        provider_probability_normalization_adopted=False,raw_provider_answers_preserved_by_caller=True))
