"Score finite forecasts while retaining unknown labels and missing answers."
from collections import Counter
from copy import deepcopy
import math

from . import incident_choice_response as responses
from . import incident_reference as c

BINS=(0.,.2,.4,.6,.8,1.)
THRESHOLDS=(.65,.70,.85)


def apply_postprocessor(model,rows):
    "Apply postprocessor."
    c.check_seal(model)
    c.require(model['schema_version']=='reqlox.finite-forecast-sigmoid.v0.1'
        and model['feature_clipping_epsilon']==1e-6 and model['slope_l2_regularization']==.05
        and model['nonnegative_slope'] is True and model['parameters']['converged'] is True
        and model['probabilities_calibrated'] is False and model['execution_authority'] is False,
        'PROBABILITY_POSTPROCESSOR_BOUNDARY')
    slope=model['parameters']['slope'];intercept=model['parameters']['intercept']
    c.require(type(slope) in (int,float) and type(intercept) in (int,float)
        and math.isfinite(slope) and math.isfinite(intercept) and 0<=slope<=1000 and -1000<=intercept<=1000,
        'PROBABILITY_POSTPROCESSOR_PARAMETERS')
    c.require(type(rows) is list and rows and len({r['id'] for r in rows})==len(rows),
              'PROBABILITY_POSTPROCESSOR_ROWS')
    c.require(not ({r['id'] for r in rows}&set(model['training_ids'])),
              'PROBABILITY_POSTPROCESSOR_TRAINING_EVALUATION_OVERLAP')
    result=[]
    for row in rows:
        c.require(row['event']==model['event'] and row['method_revision']==model['original_method_revision'],
                  'PROBABILITY_POSTPROCESSOR_EVENT_OR_METHOD_DRIFT')
        checked=responses.check(row.get('answer'),['PASS','FAIL']);new=deepcopy(row)
        new.update(raw_answer=deepcopy(row.get('answer')),raw_method_revision=row['method_revision'],
                   method_revision=model['record_sha256'])
        if checked['status']=='VALID':
            # Only the declared logit feature is clipped. Proper scores use the
            # original or derived probabilities without hidden score clipping.
            bounded=min(1-1e-6,max(1e-6,checked['probabilities']['PASS']))
            value=slope*(math.log(bounded)-math.log1p(-bounded))+intercept
            p=1/(1+math.exp(-value)) if value>=0 else math.exp(value)/(1+math.exp(value))
            new['answer']=dict(choice='PASS' if p>=.5 else 'FAIL',probabilities={'PASS':p,'FAIL':1-p},
                learned_postprocessor=True,raw_answer_preserved=True)
        else:new['answer']=None
        result.append(new)
    return result


def component_assignments(rows):
    parents=list(range(len(rows)));seen={}
    def find(index):
        while parents[index]!=index:
            parents[index]=parents[parents[index]];index=parents[index]
        return index
    for index,row in enumerate(rows):
        for axis in ('source_group','target_group','mechanism_group','dependency_component'):
            key=(axis,row[axis])
            if key in seen:parents[find(index)]=find(seen[key])
            else:seen[key]=index
    return {row['id']:find(index) for index,row in enumerate(rows)}


def evaluate(rows,*,event,predictor_revision,prospective=False,binding_checks=None):
    c.require(prospective is False,'PROBABILITY_PROSPECTIVE_REQUIRES_EVIDENCE')
    c.require(type(rows) is list and len({r['id'] for r in rows})==len(rows),'PROBABILITY_ROW_IDENTITIES')
    c.require(type(event) is str and bool(event) and type(predictor_revision) is str
        and bool(predictor_revision),'PROBABILITY_EVENT_OR_PREDICTOR')
    for row in rows:
        c.require(row['event']==event and row['method_revision']==predictor_revision,'PROBABILITY_EVENT_DRIFT')
        c.require(row.get('label') in (None,'PASS','FAIL'),'PROBABILITY_LABEL')
        c.require(row.get('label') is None or row.get('label_authority') in
            ('CONSTRUCTED_FINITE_ORACLE','NATIVE_FINITE_REQUIREMENT_ORACLE'),'PROBABILITY_UNKNOWN_TRUTH_AUTHORITY')
        c.require(all(type(row.get(k)) is str and row[k] for k in
            ('source_group','target_group','mechanism_group','dependency_component')),'PROBABILITY_GROUP_UNKNOWN')
    checked=[responses.check(r.get('answer'),['PASS','FAIL']) for r in rows]
    bindings_verified=False
    if binding_checks is not None:
        c.require(type(binding_checks) is list and len(binding_checks)==len(rows)
            and {check['subject_id'] for check in binding_checks}=={r['id'] for r in rows},
            'PROBABILITY_BINDING_IDENTITIES')
        by_id={check['subject_id']:check for check in binding_checks}
        for row in rows:
            check=by_id[row['id']];c.check_seal(check)
            c.require(check['kind'] in ('ARCHIVED_FORECAST_EXECUTION_BINDING_CHECK_V1',
                                       'RAW_CONTEXT_FORECAST_EXECUTION_BINDING_CHECK_V1')
                and check['event']==event
                and check['predictor_revision']==row.get('raw_method_revision',predictor_revision)
                and check['execution']['label']==row['label']
                and check['execution']['label_authority']==row['label_authority']
                and check['structural_forecast_binding_verified'] is True
                and check['same_original_inputs_verified'] is True
                and check['labels_withheld_in_prediction_verified'] is True
                and (check['kind']=='ARCHIVED_FORECAST_EXECUTION_BINDING_CHECK_V1'
                     and check['frozen_postprocessor_application_verified'] is True
                     or check['kind']=='RAW_CONTEXT_FORECAST_EXECUTION_BINDING_CHECK_V1'
                     and check['frozen_raw_forecast_verified'] is True
                     and (row.get('raw_method_revision') is None
                          or check['fixed_postprocessor_sha256']==predictor_revision)),
                'PROBABILITY_BINDING_DRIFT')
        bindings_verified=bool(rows)
    known=[(r,v['probabilities']['PASS'],int(r['label']=='PASS')) for r,v in zip(rows,checked)
        if v['status']=='VALID' and r.get('label') is not None]
    n=len(known);unknown=len(rows)-n
    scalar=math.fsum((p-y)**2 for _,p,y in known)
    logterms=[-math.log(p if y else 1-p) if (p if y else 1-p)>0 else math.inf for _,p,y in known]
    finite=all(math.isfinite(v) for v in logterms)
    components=component_assignments(rows)
    bins=[]
    for index,(low,high) in enumerate(zip(BINS,BINS[1:])):
        points=[(r,p,y) for r,p,y in known if low<=p and (p<high or index==len(BINS)-2 and p==high)]
        count=len(points);mean=math.fsum(p for _,p,_ in points)/count if count else None
        rate=sum(y for _,_,y in points)/count if count else None
        bins.append(dict(low=low,high=high,count=count,mean_pass_probability=mean,observed_pass_fraction=rate,
            absolute_gap=abs(mean-rate) if count else None,project_groups=len({r['target_group'] for r,_,_ in points}),
            dependency_components=len({components[r['id']] for r,_,_ in points}),confidence_interval=None))
    decisions=[]
    for threshold in THRESHOLDS:
        selected=[];unscored=0;abstained=0;false_accepts=0;false_rejects=0
        for row,answer in zip(rows,checked):
            accepted=answer['choice'] if answer['status']=='VALID' and max(answer['probabilities'].values())>=threshold else None
            if accepted is None:abstained+=1;continue
            if row.get('label') is None:unscored+=1;continue
            selected.append(accepted)
            false_accepts+=accepted=='PASS' and row['label']=='FAIL'
            false_rejects+=accepted=='FAIL' and row['label']=='PASS'
        decisions.append(dict(threshold=threshold,pass_accepts=selected.count('PASS'),fail_accepts=selected.count('FAIL'),
            false_accepts=false_accepts,false_rejects=false_rejects,abstentions=abstained,
            selected_unknown_labels=unscored,scored_selection_coverage=len(selected)/len(rows) if rows else None))
    by_project={}
    for row,p,y in known:by_project.setdefault(row['target_group'],[]).append((p-y)**2)
    project_score=math.fsum(math.fsum(v)/len(v) for v in by_project.values())/len(by_project) if by_project else None
    return c.seal(dict(kind='FINITE_QUALIFICATION_PROBABILITY_EVALUATION_V1',event=event,predictor_revision=predictor_revision,
        total_rows=len(rows),valid_forecasts=sum(v['status']=='VALID' for v in checked),scored_rows=n,
        unknown_rows=unknown,truth_counts=dict(Counter(r.get('label') or 'UNKNOWN' for r in rows)),
        scalar_binary_brier=scalar/n if n else None,categorical_binary_brier=2*scalar/n if n else None,
        categorical_brier_definition='SUM_OVER_PASS_FAIL_SQUARED_PROBABILITY_ERROR',
        categorical_brier_all_rows_bounds=[2*scalar/len(rows),2*(scalar+unknown)/len(rows)] if rows else None,
        binary_log_loss=sum(logterms)/n if n and finite else None,log_loss_infinite=bool(n and not finite),
        equal_project_scalar_brier=project_score,project_groups=len({r['target_group'] for r in rows}),
        dependency_components=len(set(components.values())),reliability_bins=bins,thresholds=decisions,
        empirical_ece=math.fsum(b['count']*b['absolute_gap'] for b in bins if b['count'])/n if n else None,
        prospective_binding_verified=False,forecast_execution_bindings_verified=bindings_verified,
        trusted_forecast_before_execution_time_attested=False,
        all_chat_unused_verified=False,iid_attested=False,
        confidence_intervals_eligible=False,probabilities_calibrated=False,independent_samples_certified=False,
        calibration_certification='HELD_NO_INDEPENDENCE_AND_SAMPLING_ATTESTATION',
        brier_improvement_is_not_calibration_certification=True,adopted_threshold=None,execution_authority=False))
