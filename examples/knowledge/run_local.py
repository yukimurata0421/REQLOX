"""Run the owned document and native IR workflow without network or providers."""
import argparse
import json
from pathlib import Path

from reqlox import knowledge
from reqlox_knowledge import storage


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir',type=Path)
    args=parser.parse_args()
    inputs=Path(__file__).parent
    documents=json.loads((inputs/'documents.json').read_text())
    imported=knowledge.import_documents(documents,state_dir=args.state_dir)
    indexed=knowledge.build_index(imported['corpus'])
    found=knowledge.search(indexed['index'],'worker lock')
    candidate=json.loads((inputs/'candidate.json').read_text())
    texts=json.loads((inputs/'source-texts.json').read_text())
    prepared=knowledge.prepare_ir(candidate,texts,state_dir=args.state_dir)
    routed=knowledge.route_ir(storage.checked_record(prepared['plan']),{})
    scores=json.loads((inputs/'scores.json').read_text())
    diagnostics=knowledge.partial_scores(scores['rows'],scores['categories'])
    directory=storage.new_directory(storage.state_directory(args.state_dir),'owned-example')
    storage.save(directory/'route.json',routed)
    storage.save(directory/'scores.json',diagnostics)
    print(json.dumps(dict(status='COMPLETE',fixture_kind='OWNED_SYNTHETIC_CONTROL',
        corpus=imported['corpus'],index=indexed['index'],plan=prepared['plan'],output=str(directory),
        search_results=len(found['results']),atomic_projection_present=routed['atomic_projection'] is not None,
        attempted_rows=diagnostics['attempted_rows'],unknown_vectors=diagnostics['unknown_vectors'],
        provider_calls=0,network_calls=0,probabilities_calibrated=False)))


if __name__=='__main__':main()
