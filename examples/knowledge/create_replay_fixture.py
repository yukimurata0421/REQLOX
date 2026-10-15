"""Create an owned synthetic protocol control; never call a provider."""
from copy import deepcopy
import json
from pathlib import Path

from reqlox_knowledge import generation, generator, ir, native, observed_v2, pipeline, reference, storage


def build_fixture():
    root = Path(__file__).resolve().parent
    texts = json.loads((root / 'source-texts.json').read_text())
    draft = json.loads((root / 'draft.json').read_text())
    plan = generation.freeze(texts['owned-lock-report'], source_id='owned-lock-report', project_id='example-project',
                             created_at='2026-10-13T00:00:00+00:00')
    response = dict(modelVersion=generator.MODEL_ID, responseId='OWNED_SYNTHETIC_GENERATION_CONTROL',
        candidates=[dict(finishReason='STOP',content=dict(parts=[dict(text=json.dumps(dict(payload_json=json.dumps(draft))))]))],
        usageMetadata=dict(promptTokenCount=100,candidatesTokenCount=100,totalTokenCount=200))
    candidate = generation.materialize(plan, dict(payload_json=json.dumps(draft)))
    review = ir.freeze(candidate, texts, created_at=plan['created_at'])
    rows = {row['id']:row for row in review['requests']}
    exchanges=[]
    for batch in review['batches']:
        answers={}
        for qid, ident in batch['mapping'].items():
            row=rows[ident]
            wanted=review['control_key'].get(ident,{}).get('wanted') or (
                observed_v2.ATOMIC if row['purpose']==observed_v2.PURPOSE else native.EXPECTED[row['purpose']])
            answers[qid]=dict(type='choice',choice=wanted,confidence=.95,
                probabilities={key:float(key==wanted) for key in row['choices']})
        raw=reference.canonical(dict(model=pipeline.judge_client.PINNED_MODEL,answers=answers,
            usage=dict(input_tokens=100,output_tokens=100),request_id='OWNED_SYNTHETIC_JUDGE_CONTROL'))
        exchange=dict(request=pipeline.wire(pipeline.judge_request(batch)),response=pipeline.wire(raw),http_status=200)
        exchanges.extend(dict(batch_id=batch['id'],repeat=n,exchange=deepcopy(exchange)) for n in range(3))
    return reference.seal(dict(schema_version=pipeline.SCHEMA,response_provenance='OWNED_SYNTHETIC_CONTROL',
        generation_plan=plan,generation_exchange=dict(request=pipeline.wire(pipeline.generation_request(plan)),
            response=pipeline.wire(reference.canonical(response)),http_status=200),judge_exchanges=exchanges))


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    value=build_fixture()
    storage.save(args.output,value)
    print(json.dumps(dict(status='OWNED_SYNTHETIC_CONTROL_CREATED',output=str(args.output),
                         bundle_sha256=value['record_sha256'],provider_calls=0,target_executions=0)))


if __name__=='__main__':
    main()
