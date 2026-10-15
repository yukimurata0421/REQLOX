"Validate quotation spans and sealed references without execution authority."
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math

BOUNDARIES = ("SINGLE_INCIDENT", "MULTIPLE_INCIDENTS", "NOT_INCIDENT", "INSUFFICIENT_INFORMATION")
RELATIONS = ("causes", "contributes_to", "amplifies", "triggers", "prevents_recovery", "masks", "correlated_with", "unknown")
FLOOR = .85


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def seal(value):
    value = {k: v for k, v in value.items() if k != "record_sha256"}
    return {**value, "record_sha256": digest(value)}


def check_seal(value):
    require(type(value) is dict and seal(value) == value, "REFERENCE_HASH_DRIFT")


def quote_span(text, quote, occurrence, *, start_char=0):
    "Quote span."
    require(type(text) is str and type(quote) is str and 1 <= len(quote) <= 400, "REFERENCE_QUOTE_BOUND")
    require(type(occurrence) is int and 0 <= occurrence <= 100, "REFERENCE_QUOTE_OCCURRENCE")
    require(type(start_char) is int and start_char >= 0, "REFERENCE_SCOPE_START")
    matches, cursor = [], 0
    while True:
        found = text.find(quote, cursor)
        if found < 0:
            break
        matches.append(found)
        cursor = found + 1
    require(occurrence < len(matches), "REFERENCE_QUOTE_NOT_FOUND")
    pos = matches[occurrence]
    return dict(start_char=start_char + pos, end_char=start_char + pos + len(quote),
                content_hash=hashlib.sha256(quote.encode()).hexdigest(), occurrence=occurrence,
                matching_occurrences=len(matches))


def probabilities(value, categories):
    require(type(value) is dict and set(value) == set(categories), "REFERENCE_PROBABILITY_COVERAGE")
    require(all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in value.values()),
            "REFERENCE_PROBABILITY_VALUE")
    require(abs(math.fsum(value.values()) - 1) <= 1e-6, "REFERENCE_PROBABILITY_SUM")
    return value


def validate_output(output, packet, taxonomy):
    from jsonschema import Draft202012Validator
    schema = output_schema(taxonomy)
    require(not list(Draft202012Validator(schema).iter_errors(output)), "REFERENCE_OUTPUT_SCHEMA")
    probabilities(output["boundary_probabilities"], BOUNDARIES)
    verdict = output["boundary_verdict"]
    require(output["boundary_probabilities"][verdict] == max(output["boundary_probabilities"].values()),
            "REFERENCE_BOUNDARY_ARGMAX")
    text = packet["review_material"]["scope_text"]
    start = packet["subject"]["scope"]["start_char"]
    boundary_span = None
    if output["boundary_quote"]:
        boundary_span = quote_span(text, output["boundary_quote"], output["boundary_occurrence"], start_char=start)
    else:
        require(verdict == "INSUFFICIENT_INFORMATION", "REFERENCE_BOUNDARY_QUOTE_REQUIRED")
    events = {e["id"]: e for e in output["events"]}
    require(len(events) == len(output["events"]), "REFERENCE_DUPLICATE_EVENT")
    layers = {p["id"]: p["layer"] for p in taxonomy["primitives"]}
    event_spans, edge_spans = {}, {}
    for event in output["events"]:
        require(event["layer"] == layers[event["primitive"]], "REFERENCE_TAXONOMY_LAYER")
        event_spans[event["id"]] = quote_span(text, event["quote"], event["occurrence"], start_char=start)
    require(len({e["id"] for e in output["edges"]}) == len(output["edges"]), "REFERENCE_DUPLICATE_EDGE")
    edge_signatures = set()
    for edge in output["edges"]:
        require(edge["from_event"] in events and edge["to_event"] in events and
                edge["from_event"] != edge["to_event"], "REFERENCE_EDGE_ENDPOINT")
        require(events[edge["from_event"]]["incident_index"] == events[edge["to_event"]]["incident_index"],
                "REFERENCE_CROSS_INCIDENT_EDGE")
        signature = (edge["from_event"], edge["to_event"], edge["relation"])
        require(signature not in edge_signatures, "REFERENCE_DUPLICATE_EDGE_SIGNATURE")
        edge_signatures.add(signature)
        edge_spans[edge["id"]] = quote_span(text, edge["quote"], edge["occurrence"], start_char=start)
    incident_count = len({e["incident_index"] for e in events.values()})
    if verdict in ("NOT_INCIDENT", "INSUFFICIENT_INFORMATION"):
        require(not events and not output["edges"], "REFERENCE_NONINCIDENT_EVENTS")
    elif output["coverage"] == "COMPLETE_FOR_SCOPE":
        require(incident_count == 1 if verdict == "SINGLE_INCIDENT" else incident_count >= 2,
                "REFERENCE_INCIDENT_BOUNDARY_COUNT")
    return dict(boundary_span=boundary_span, event_spans=event_spans, edge_spans=edge_spans,
                authority="INDEPENDENT_ORACLE_FOR_EXACT_SOURCE_ANCHOR_ONLY",
                causal_or_incident_truth=False, semantic_completeness_certified=False)


def obj(properties, **kwargs):
    return dict(type="object", additionalProperties=False, required=list(properties), properties=properties, **kwargs)


def output_schema(taxonomy):
    string = dict(type="string", minLength=1, maxLength=220)
    quote = dict(type="string", minLength=1, maxLength=400)
    occurrence = dict(type="integer", minimum=0, maximum=100)
    number = dict(type="number", minimum=0, maximum=1)
    return obj(dict(
        boundary_verdict=dict(type="string", enum=list(BOUNDARIES)),
        boundary_probabilities=obj({b: number for b in BOUNDARIES}),
        boundary_quote=dict(type="string", maxLength=400), boundary_occurrence=occurrence,
        coverage=dict(type="string", enum=["COMPLETE_FOR_SCOPE", "PARTIAL", "UNRESOLVED"]),
        events=dict(type="array", maxItems=10, items=obj(dict(
            id=dict(type="string", pattern="^e[0-9]{1,2}$"), incident_index=dict(type="integer", minimum=0, maximum=9),
            primitive=dict(type="string", enum=[p["id"] for p in taxonomy["primitives"]]),
            layer=dict(type="string", enum=taxonomy["layers"]), description=string,
            origin=dict(type="string", enum=["SOURCE_OBSERVED", "ANNOTATOR_INFERENCE"]),
            quote=quote, occurrence=occurrence))),
        edges=dict(type="array", maxItems=12, items=obj(dict(
            id=dict(type="string", pattern="^r[0-9]{1,2}$"), from_event=dict(type="string", pattern="^e[0-9]{1,2}$"),
            to_event=dict(type="string", pattern="^e[0-9]{1,2}$"), relation=dict(type="string", enum=list(RELATIONS)),
            origin=dict(type="string", enum=["EXPLICIT_SOURCE", "ANNOTATOR_INFERENCE"]), quote=quote, occurrence=occurrence))),
    ))


def route_reference(packet, draft, source_judgments, supported_judgments, mechanical):
    "Route reference."
    boundary = source_judgments["boundary"]
    require(boundary["choice"] in BOUNDARIES, "REFERENCE_SOURCE_BOUNDARY_CHOICE")
    probabilities(boundary["probabilities"], BOUNDARIES)
    agreement = boundary["choice"] == draft["boundary_verdict"]
    eligible = agreement and boundary["choice"] != "INSUFFICIENT_INFORMATION" and \
        boundary["probabilities"][boundary["choice"]] >= FLOOR and \
        draft["boundary_probabilities"][draft["boundary_verdict"]] >= FLOOR
    retained_events, retained_edges, exceptions = [], [], []
    for event in draft["events"]:
        presence = source_judgments["primitive_" + event["primitive"]]
        support = supported_judgments["event_" + event["id"]]
        supported = support["choice"] == "SUPPORTED" and support["probabilities"]["SUPPORTED"] >= FLOOR
        present = presence["choice"] == "PRESENT" and presence["probabilities"]["PRESENT"] >= FLOOR
        if supported and (present or event["origin"] == "ANNOTATOR_INFERENCE"):
            retained_events.append(event)
        else:
            exceptions.append(dict(kind="EVENT", id=event["id"], primitive=event["primitive"],
                                   presence=presence["choice"], support=support["choice"]))
    event_ids = {e["id"] for e in retained_events}
    for edge in draft["edges"]:
        support = supported_judgments["edge_" + edge["id"]]
        if edge["from_event"] in event_ids and edge["to_event"] in event_ids and \
                support["choice"] == "SUPPORTED" and support["probabilities"]["SUPPORTED"] >= FLOOR:
            retained_edges.append(edge)
        else:
            exceptions.append(dict(kind="EDGE", id=edge["id"], support=support["choice"]))
    reported = {e["primitive"] for e in retained_events if e["origin"] == "SOURCE_OBSERVED"}
    omitted = [k[len("primitive_"):] for k, v in source_judgments.items() if k.startswith("primitive_") and
               v["choice"] == "PRESENT" and v["probabilities"]["PRESENT"] >= FLOOR and k[len("primitive_"):] not in reported]
    return seal(dict(schema_version="reqlox.automated-incident-reference.v0.1", task_id=packet["task_ref"]["id"],
                source_group=packet["subject"]["canonical_group_id"], source_document_id=packet["source_document_id"],
                source_text_sha256=packet["subject"]["scope"]["text_sha256"],
                authority="LLM_ADJUDICATED_REFERENCE", boundary_verdict=draft["boundary_verdict"] if eligible else None,
                boundary_distribution=boundary["probabilities"], boundary_agreement=agreement,
                boundary_eligible=eligible, draft_coverage=draft["coverage"],
                events=retained_events, edges=retained_edges, exceptions=exceptions, omitted_primitives=omitted,
                reference_complete=draft["coverage"] == "COMPLETE_FOR_SCOPE" and eligible and not exceptions and not omitted,
                mechanical=mechanical, model_probabilities_calibrated=False,
                candidate_proposals_accessed=False, independent_model_errors_assumed=False,
                human_adjudication_performed=False, natural_incident_truth_certified=False,
                execution_authority=False, canonicalization_authority=False))


def expected_multiclass_brier(prediction, reference):
    "Expected multiclass brier."
    probabilities(prediction, BOUNDARIES)
    probabilities(reference, BOUNDARIES)
    return math.fsum(prediction[k] ** 2 - 2 * prediction[k] * reference[k] + reference[k] for k in BOUNDARIES)


def compare_boundary(references, predictions):
    require(len({r["task_id"] for r in references}) == len(references) > 0, "REFERENCE_TASK_COVERAGE")
    require(set(predictions) == {r["task_id"] for r in references}, "REFERENCE_PREDICTION_COVERAGE")
    rows = []
    for ref in references:
        check_seal(ref)
        pred = predictions[ref["task_id"]]
        eligible = ref["boundary_eligible"]
        observed = pred is not None
        if observed:
            require(pred["choice"] in BOUNDARIES, "REFERENCE_PREDICTION_CHOICE")
            if pred.get("probabilities") is not None:
                probabilities(pred["probabilities"], BOUNDARIES)
        agreement = observed and eligible and pred["choice"] == ref["boundary_verdict"]
        score = expected_multiclass_brier(pred["probabilities"], ref["boundary_distribution"]) if observed and pred.get("probabilities") is not None else None
        rows.append(dict(task_id=ref["task_id"], source_group=ref["source_group"],
                         source_text_sha256=ref["source_text_sha256"], prediction_observed=observed,
                         reference_eligible=eligible, agrees=agreement, reference_expected_brier=score))
    eligible_rows = [r for r in rows if r["reference_eligible"]]
    agreements = sum(r["agrees"] for r in eligible_rows)
    observed_eligible = sum(r["prediction_observed"] for r in eligible_rows)
    
    parent = {}
    def find(key):
        parent.setdefault(key, key)
        if parent[key] != key:
            parent[key] = find(parent[key])
        return parent[key]
    for row in rows:
        parent[find(("group", row["source_group"]))] = find(("text", row["source_text_sha256"]))
    groups = {}
    for row in rows:
        groups.setdefault(find(("group", row["source_group"])), []).append(row)
    scores = [sum(r["reference_expected_brier"] for r in g if r["reference_expected_brier"] is not None) /
              sum(r["reference_expected_brier"] is not None for r in g) for g in groups.values()
              if any(r["reference_expected_brier"] is not None for r in g)]
    complete_groups = [g for g in groups.values() if all(r["reference_eligible"] for r in g)]
    group_agreements = sum(all(r["agrees"] for r in g) for g in complete_groups)
    from qualification_probability import exact_interval, beta_posterior
    return seal(dict(schema_version="reqlox.reference-comparison.v0.1", attempted_tasks=len(rows),
                eligible_reference_tasks=len(eligible_rows), unresolved_reference_tasks=len(rows)-len(eligible_rows),
                observed_predictions=sum(r["prediction_observed"] for r in rows),
                missing_predictions=sum(not r["prediction_observed"] for r in rows), agreements=agreements,
                agreement_over_all_attempts=agreements/len(rows),
                agreement_over_eligible_references=agreements/len(eligible_rows) if eligible_rows else None,
                agreement_over_observed_eligible=agreements/observed_eligible if observed_eligible else None,
                unresolved_reference_agreement_bounds=[agreements/len(rows),
                    (agreements+sum(r["prediction_observed"] and not r["reference_eligible"] for r in rows))/len(rows)],
                dependency_groups=len(groups), group_equal_weight_reference_expected_brier=sum(scores)/len(scores) if scores else None,
                complete_reference_groups=len(complete_groups), all_member_agreement_groups=group_agreements,
                conditional_reference_agreement_interval=exact_interval(group_agreements, len(complete_groups)),
                conditional_reference_agreement_posterior=beta_posterior(group_agreements, len(complete_groups)),
                interval_event="ALL_MEMBER_AGREEMENT_WITH_LLM_REFERENCE_UNDER_EXCHANGEABLE_GROUP_ASSUMPTION",
                true_accuracy=None, true_brier=None, population_generalization_certified=False,
                reference_probability_truth_assumption_verified=False, rows=rows))
