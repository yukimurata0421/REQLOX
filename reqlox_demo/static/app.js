"use strict";
const $ = id => document.getElementById(id);
let config, lastDownload, originalCaller, running=false, hasResult=false;
const methodNames={MECHANICAL_BASELINE:"Included text rules",RECORDED_MODEL_JUDGMENT:"Recorded assessment",LIVE_MODEL_JUDGMENT:"New model assessment"};
const stageNames={HEALTHY:"Normal path",FAULT:"Injected fault",REPAIR:"Changed caller",REINJECTION:"Same fault again"};
const sampleCopy={reported:["Failure reported","An exception leaves the lock held. Check whether the next worker is blocked."],negative:["Cleanup worked","The report says cleanup succeeded. The check should stop before testing an unsupported failure."],unknown:["Missing evidence","The report lacks cleanup observations. The check should retain the uncertainty."]};
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function hidden(id,value){$(id).classList.toggle("hidden",value);}
function options(){
  if(!config)return;
  for(const [id,value,available] of [["method","live",config.live_model_available],["method","recorded",config.recorded_model_available],["repair","live",config.live_repair_available],["repair","recorded",config.recorded_repair_available]])$(id).querySelector(`[value="${value}"]`).disabled=!available;
}
function controls(disabled){
  document.querySelectorAll('.input-panel button,.input-panel input,.input-panel textarea,.input-panel select').forEach(n=>{n.disabled=disabled;});
  options();$("run").disabled=true;$("try-recorded-example").disabled=disabled||!config;
}
function reset(changed=false){
  lastDownload=undefined;hasResult=false;
  for(const id of ["evidence-panel","experiment-panel","repair-panel","measurement-panel","result-next"])hidden(id,true);
  $("status-pill").textContent=changed?"Input changed":"Not run yet";$("status-pill").className="pill neutral";
  $("result-title").textContent=changed?"Save these inputs or open an archived record.":"What does this report let us check?";
  $("result-message").textContent=changed?"The previous result belonged to different inputs. It is no longer displayed as the current result.":"Run the example to see whether the lock stays held after an exception, and whether the changed caller releases it.";
  hidden("error",true);
}
function changed(){if(hasResult||lastDownload)reset(true);}
function methodNote(){
  if(config?.execution_policy?.mode==='OFFLINE_RECORDS_ONLY'){
    $('method-note').textContent=document.documentElement.lang==='ja'?'この入力は下書きとして保存できます。新しい判定・注入は停止中です。':'Save this input as a draft. New assessments and native execution are disabled.';
    $('repair-note').textContent=document.documentElement.lang==='ja'?'修復・再注入の結果は記録・履歴から確認してください。':'Open Records & history for saved repair and reinjection observations.';
    return;
  }

  const method=$("method").value;
  $("method-note").textContent=method==="baseline"?"Included rules assess the text. No model call is made.":method==="recorded"?"Replay an assessment bound to this exact input and caller; run the check afresh.":"Send the report to the configured provider. The prediction is separate from the observation.";
  const repair=$("repair").value;
  $("repair-note").textContent=repair==="rule"?"Apply the included context-cleanup change, then test the same fault again.":repair==="recorded"?"Test a supplied candidate in isolation. No new generation call is made.":"Request a candidate before testing it. This requires a bounded model scope.";
  hidden("model-consent-wrap",method!=="live"&&repair!=="live");
}
function fillSample(sample){
  changed();$("report").value=sample.report;$("caller").value=sample.caller;originalCaller=sample.caller;
  $("source-kind").textContent="Owned synthetic report";$("use-repair").textContent="Use the repaired structure";
  $("sample-help").textContent=(sampleCopy[sample.id]||["","Included example"])[1];
  for(const b of $("samples").children){const active=b.dataset.sample===sample.id;b.classList.toggle("active",active);b.setAttribute("aria-pressed",String(active));}
}
function stageCards(result){
  const cases=result.cases||[];
  for(const name of Object.keys(stageNames)){
    const stages=cases.map(c=>(c.stages||[]).find(s=>s.stage===name));
    const receipts=stages.filter(s=>s&&!s.missing&&s.observed);
    const held=receipts.filter(s=>s.observed.locked_after_first===true).length;
    const released=receipts.filter(s=>s.observed.locked_after_first===false).length;
    const entered=receipts.filter(s=>s.observed.second_entered===true).length;
    const blocked=receipts.filter(s=>s.observed.second_entered===false).length;
    const matches=stages.filter(s=>s&&!s.missing&&s.matches_gold===true).length;
    const lockUnknown=cases.length-held-released,workerUnknown=cases.length-entered-blocked;
    const incomplete=lockUnknown>0||workerUnknown>0||matches!==cases.length;
    const card=node("div",undefined,"stage-card"+(incomplete?" unverified":held>0?" fault":""));
    card.append(node("span",`${String(Object.keys(stageNames).indexOf(name)+1).padStart(2,"0")} / ${name}`,"stage-label"));
    card.append(node("div",incomplete?"?":held>0?"⊘":"✓","stage-icon"),node("strong",stageNames[name]));
    card.append(node("p",`Lock: ${released} released · ${held} held${lockUnknown?` · ${lockUnknown} unknown`:""}`));
    card.append(node("p",`Next worker: ${entered} entered · ${blocked} blocked${workerUnknown?` · ${workerUnknown} unknown`:""}`));
    card.append(node("span",`${matches}/${cases.length} conditions match the expected result`,"stage-score"));$("stage-cards").append(card);
  }
}
function display(result,download,submittedCaller=""){
  lastDownload=download;hasResult=true;
  const ok=result.status==="REPRODUCED_AND_REPAIRED",normal=result.status==="NOT_REPRODUCED",unsupported=result.status==="NOT_SUPPORTED",stopped=["STOPPED","CONTRACT_MISMATCH"].includes(result.status);
  $("status-pill").textContent=ok?"Reproduced and repaired":normal?"Not reproduced":unsupported?"Condition not supported":stopped?"Stopped":"More evidence needed";
  $("status-pill").className="pill "+(ok||normal?"green":stopped?"red":"amber");
  $("result-title").textContent=ok?"The exception blocked the next worker. Cleanup fixed this check.":normal?"The submitted structure released the lock in these conditions.":unsupported?"This report does not support the selected failure.":stopped?"The check stopped without a verified outcome.":"The report does not yet tell us enough.";
  $("result-message").textContent=result.message;
  hidden("result-next",false);
  $("result-next").textContent=ok?"Inspect the caller change below. The same fault was tested again; this result covers only the displayed caller and conditions.":normal?"This is a result for the tested conditions. It does not rule out failures outside this check.":unsupported?"No target experiment was run. Select a report that describes a lock left held after an exception, or use the Evaluation lab for another supported mechanism.":stopped?"Read the retained details before making another check. A stopped operation does not verify a repair.":"No repair is verified. Add observations about cleanup and the next worker, or keep this report unresolved.";
  hidden("evidence-panel",false);hidden("measurement-panel",false);
  const assessment=result.assessment||{};
  $("assessment-method").textContent=methodNames[assessment.method]||assessment.method||"Unknown";$("evidence-quotes").replaceChildren();
  if(!(assessment.evidence||[]).length)$("evidence-quotes").append(node("p","No supporting quotation was selected.","muted small"));
  for(const q of assessment.evidence||[]){const box=node("blockquote",q.text,"quote");box.append(node("span",`${q.id} · source characters ${q.start_char}–${q.end_char}`,"quote-meta"));$("evidence-quotes").append(box);}
  $("hypothesis").textContent=assessment.hypothesis||"";$("assessment-note").textContent=assessment.note||"";
  const executed=result.native_executions>0&&(result.cases||[]).length>0;
  hidden("experiment-panel",!executed);hidden("repair-panel",!executed||!result.repair_candidate);
  $("stage-cards").replaceChildren();$("trace-body").replaceChildren();
  if(executed){
    $("stage-count").textContent=`${result.cases.length} conditions × 4 stages · ${result.stage_matches}/${result.stage_observations} observations match`;stageCards(result);
    for(const c of result.cases)for(const s of c.stages||[]){
      const tr=node("tr"),o=s.missing?undefined:s.observed;
      for(const [text,cls] of [[`${c.mode} / ${c.exception}`,""],[stageNames[s.stage]||s.stage,""],[o&&typeof o.locked_after_first==="boolean"?(o.locked_after_first?"held":"released"):"Unknown",o&&o.locked_after_first?"trace-held":""],[o&&typeof o.second_entered==="boolean"?(o.second_entered?"entered":"blocked"):"Unknown",""],[s.missing?"missing":s.matches_gold?"match":"mismatch",!s.missing&&s.matches_gold?"trace-pass":""]])tr.append(node("td",text,cls));$("trace-body").append(tr);
    }
    $("target-result").textContent=`${result.target.name} ${result.target.version} · ${result.cases.length} conditions · ${result.source_unchanged===true?"library source unchanged":result.source_unchanged===false?"source changed":"source preservation unverified"}`;
    $("runtime-result").textContent=`${result.namespace_isolated===true?"Isolated worker":"Isolation unverified"} · network attempts ${Number.isInteger(result.network_attempts)?result.network_attempts:"unknown"}`;
    $("original-code").textContent=submittedCaller;
    $("repair-code").textContent=result.repair_candidate?result.repair_candidate.code:"No candidate supplied";
    $("repair-method").textContent=result.candidate_code_executed?"Candidate code executed":"Included cleanup rule";
    $("repair-result-note").textContent=result.candidate_code_executed?`Repair and repeat-fault checks matched ${result.repair_case_pairs_passed}/${result.repair_case_pairs} conditions. Inspect all observations above.`:"The change puts cleanup inside a context manager, so the lock is released when work raises an exception. The check evaluates the caller structure; it does not execute arbitrary entered code.";
  }
  const support=assessment.probabilities,forecast=result.probability_evaluation;
  $("measurements").replaceChildren();
  const paid=assessment.method==="LIVE_MODEL_JUDGMENT"||result.repair_requested==="live";
  const metrics=[support?["Model support score",`${Math.round(support.SUPPORTED*100)}%`,"Uncalibrated / separate from observations"]:["Evidence assessment","Included rules","No model probability"],forecast?[result.repair_event?"Repair forecast":"Pre-execution forecast",`${Math.round(forecast.probability*100)}%`,forecast.brier===null?"Outcome unknown / Brier unscored":`Uncalibrated · Brier ${forecast.brier.toFixed(4)}`]:["Observed stages",String(result.stage_observations??0),executed?"Finite conditions":result.native_attempts>0?"Attempted / outcome unknown":"No target experiment"],["Elapsed time",`${Number(result.elapsed_seconds).toFixed(2)}s`,paid?"Bounded model scope":"New paid calls 0"]];
  for(const [label,value,unit] of metrics){const n=node("div",undefined,"metric");n.append(node("span",label,"label"),node("strong",value),node("span",unit,"unit"));$("measurements").append(n);}
  $("probability-note").textContent=forecast?"Forecasts describe a declared event. Replayed forecasts are not independent accuracy samples, and these figures do not establish population calibration.":"A match covers this finite contract. It does not establish general natural-language accuracy or an unseen-repository success rate.";
  $("provenance").replaceChildren();
  for(const [key,value] of [["Run",result.run_id],["Source SHA-256",result.source_sha256],["Caller SHA-256",result.caller&&result.caller.input_sha256],["Plan SHA-256",result.plan_sha256||"Not executed"],["Observation SHA-256",result.observation_sha256||"Not executed"]])$("provenance").append(node("dt",key),node("dd",value));
}

// Curated aggregate evidence; no raw source, private paths, or model responses.
const repairExamples = [
  {
    "id": "lock-cleanup",
    "source_kind": "OWNED_SYNTHETIC_REPORT",
    "source_label": "Owned fictional report",
    "source_description": "A fictional owner-authored incident report; this is not evidence of transfer from a natural incident.",
    "label": "Lock cleanup",
    "headline": "An exception kept the next worker out.",
    "targets": [
      "py-cachify 3.1.0",
      "readerwriterlock 1.0.9"
    ],
    "date": "2026-10-08",
    "metric": "12 / 12",
    "metric_label": "repair + same-fault conditions passed",
    "repair_type": "Generated caller repair",
    "injection": "Exceptions and task cancellation while the caller holds a lock.",
    "before": "The caller entered manually. An exception could skip release and block the next acquisition.",
    "after": "A generated context-cleanup candidate ran work while held, released the lock, and preserved exception propagation.",
    "verification": "12 repair/reinjection condition pairs passed across two known libraries. All four stages matched in 48/48 observations.",
    "stages": [
      {
        "title": "Normal behavior",
        "outcome": "Observed",
        "text": "Work ran while the lock was held; normal cleanup released it."
      },
      {
        "title": "Injected fault",
        "outcome": "Failure reproduced",
        "text": "The original caller left the lock held after an exception; the next acquisition was blocked."
      },
      {
        "title": "Repair candidate",
        "outcome": "Passed the finite contract",
        "text": "The saved generated code was compiled and executed in an isolated worker."
      },
      {
        "title": "Same fault again",
        "outcome": "12 / 12 conditions passed",
        "text": "Cleanup, work count, lock release, and exception propagation met the declared obligations."
      }
    ],
    "source_value": "Source benefit not established",
    "source_note": "This recorded run qualifies one generated candidate on known targets. It does not isolate the added effect of external knowledge.",
    "boundary": "One generated proposal, two known target libraries, and dependent test conditions. The 12 conditions are not 12 independent repair trials. The repair changes the caller, not the upstream libraries.",
    "current_check_available": true,
    "current_check_note": "The fresh check below uses the included cleanup rule. The generated-code result above is an archived experiment; its saved candidate is not available for replay in this cloud deployment.",
    "record_fingerprint": "ebb90a0e2e33915cb0b332ec3e89a9ee080a1460daec0386271ee2f4cc8ab65d",
    "record_kind": "ARCHIVED_FINITE_REPAIR_EVIDENCE",
    "independent_generalization_certified": false,
    "probability_calibration_certified": false
  },
  {
    "id": "elapsed-time-ttl",
    "source_kind": "INCIDENT_CLOCK_KNOWLEDGE",
    "source_label": "Incident clock knowledge",
    "source_description": "Clock failure knowledge from incident material informed exploration order. The TTL requirement and caller were owner-prepared; semantic transfer was not certified.",
    "label": "TTL expiry",
    "headline": "Clock changes broke elapsed-time expiry.",
    "targets": [
      "cachelib 0.13.0 \u00b7 SimpleCache",
      "expiringdict 1.2.2 \u00b7 ExpiringDict"
    ],
    "date": "2026-10-09",
    "metric": "29 / 29",
    "metric_label": "cases passed per final candidate and arm",
    "repair_type": "Deterministic clock repair",
    "injection": "Backward, forward, stopped, and fractional clock trajectories inside the worker. The owned contract requires a five-second elapsed-time TTL.",
    "before": "The original classes passed normal cases but violated the owned elapsed-time requirement in 22/25 SimpleCache probes and 16/25 ExpiringDict probes.",
    "after": "The candidates use the elapsed-time clock. SimpleCache also removes clock rounding that shortened lifetime at fractional times.",
    "verification": "Each final candidate passed all 29 normal and probe cases in both knowledge arms. Re-injection used a different seed; the original wheel files were unchanged.",
    "stages": [
      {
        "title": "Normal behavior",
        "outcome": "4 / 4 per target",
        "text": "Both original classes met the selected normal conditions."
      },
      {
        "title": "Injected clock changes",
        "outcome": "Requirement violations observed",
        "text": "22/25 SimpleCache probes and 16/25 ExpiringDict probes violated the owned elapsed-time contract."
      },
      {
        "title": "Repair candidate",
        "outcome": "Final candidates passed",
        "text": "The clock change alone missed three SimpleCache fractional-time cases. Its successor also removed integer rounding."
      },
      {
        "title": "Same mechanism again",
        "outcome": "29 / 29 per candidate and arm",
        "text": "Fresh instances and a separately seeded case sequence verified the final candidates."
      }
    ],
    "source_value": "Measured added benefit: 0",
    "source_note": "Both knowledge arms found and repaired the same finite failures. The report changed exploration order; all cases were run.",
    "boundary": "Purpose-selected known targets, an owned elapsed-time contract, and fresh instances only. This does not declare an upstream specification violation or certify an unseen-OSS success rate. Stored timestamp migration was not tested.",
    "current_check_available": false,
    "current_check_note": "This is an archived experiment. The Guided check does not run this TTL campaign. The Evaluation lab prepares supported Python callers; it does not automatically replay this record.",
    "record_fingerprint": "0c55cace73857891722f27c7d12d97844d888ee69ba440a3a51665604b182396",
    "record_kind": "ARCHIVED_FINITE_REPAIR_EVIDENCE",
    "independent_generalization_certified": false,
    "probability_calibration_certified": false
  },
  {
    "id": "temporary-file-cleanup",
    "source_kind": "API_REFERENCE_SUMMARY",
    "source_label": "API reference summary",
    "source_description": "A supplied API reference summary about deletion errors. The one-time EIO policy is an owned condition, not a natural incident report.",
    "label": "Temporary file cleanup",
    "headline": "A deletion error left a file behind.",
    "targets": [
      "temppath 2021.236.907"
    ],
    "date": "2026-10-11",
    "metric": "FAIL \u2192 PASS",
    "metric_label": "added cleanup condition after the repair",
    "repair_type": "Bounded EIO retry",
    "injection": "A single EIO during cleanup deletion. \u201cFails once, then succeeds\u201d is an owned experiment condition, not a natural incident frequency claim.",
    "before": "The original implementation passed the original conditions. Adding the cleanup EIO condition left a temporary resource unreleased and produced FAIL.",
    "after": "A private code copy retries deletion once for EIO. Other errors and a persistent EIO are not converted into success.",
    "verification": "The repaired copy passed the original conditions and the added cleanup condition. The repair was adopted only within this private finite experiment; the original distribution was unchanged.",
    "stages": [
      {
        "title": "Original conditions",
        "outcome": "PASS",
        "text": "The original implementation passed the selected normal and body-exception checks."
      },
      {
        "title": "Added deletion fault",
        "outcome": "FAIL",
        "text": "A one-time EIO reached cleanup and left a temporary resource behind."
      },
      {
        "title": "Repair candidate",
        "outcome": "Private copy changed",
        "text": "A common rewrite added one bounded EIO retry to the supported deletion call."
      },
      {
        "title": "Conditions repeated",
        "outcome": "PASS + PASS",
        "text": "The repaired copy passed both the original conditions and the added cleanup condition."
      }
    ],
    "source_value": "One finite added condition found a failure",
    "source_note": "The earlier comparison used a narrower baseline. Later full-budget generic exploration found the fault in both arms, with zero additional Source adoptions. Natural incident transfer remains unverified.",
    "boundary": "One already-observed target at repair time, a supplied reference summary, and an owned transient-error policy. Its original prospective PASS and this later repair are distinct evaluations. Neither establishes independent repair generalization or population calibration.",
    "current_check_available": false,
    "current_check_note": "This is an archived experiment, not a currently running cleanup repair. The original files and detailed private records are not included in this page.",
    "record_fingerprint": "aeb6e4ff02335dc52e26f753837542e7e0862e565330fa35ac9186a6da65223d",
    "record_kind": "ARCHIVED_FINITE_REPAIR_EVIDENCE",
    "independent_generalization_certified": false,
    "probability_calibration_certified": false
  }
];
// This walkthrough reads curated records only; it never executes a check.
const tourEnglish = document.documentElement.lang !== "ja";
const tourWords = tourEnglish ? {
  steps:["Input", "Detection", "Repair", "Reinjection"],
  source:"Source summary", targets:"Recorded targets", condition:"Injected condition", before:"Original caller / implementation summary",
  normal:"Normal conditions", fault:"Fault observation", change:"Candidate change", candidate:"Candidate validation",
  observed:"Repeated-fault observation", verified:"What was verified", outcome:"Recorded outcome",
  progress:(n)=>`Step ${n} of 4 · archived record`, next:(n)=>`Next: ${n} →`, previous:"← Previous", complete:"Record complete",
  temppath:"This earlier repair is separate from the later copied-module result: HELD 4 atomic bindings; temppath repair not performed."
} : {
  steps:["入力", "検出", "修復", "再注入"],
  source:"Sourceの要約", targets:"記録の対象", condition:"注入した条件", before:"元のcaller／実装の要約",
  normal:"正常条件の観測", fault:"故障の観測", change:"修復候補の変更", candidate:"候補の検証",
  observed:"故障を繰り返した観測", verified:"確認された範囲", outcome:"記録された結果",
  progress:(n)=>`4段階中 ${n}段階目・過去の記録`, next:(n)=>`次へ：${n} →`, previous:"← 戻る", complete:"記録を最後まで確認しました",
  temppath:"この以前の修復記録は、今回のコピー済みモジュールの結果とは別です。今回の結果はatomic bindingがHELD 4件、temppath修復未実施です。"
};
let tourRecord = repairExamples[0], tourIndex = 0;
function renderRecordedTour(focus=false) {
  const e=tourRecord, w=tourWords, steps=e.stages;
  $("tour-example").value=e.id;
  $("tour-record-title").textContent=e.headline;
  $("tour-record-date").textContent=`${e.date} (JST) · ${e.targets.join(" / ")}`;
  $("tour-progress").textContent=w.progress(tourIndex+1);
  $("tour-step-title").textContent=`${tourIndex+1}. ${w.steps[tourIndex]}`;
  const fields = tourIndex===0 ? [[w.source,e.source_description],[w.targets,e.targets.join(" / ")],[w.condition,e.injection],[w.before,e.before]]
    : tourIndex===1 ? [[w.normal,`${steps[0].outcome}: ${steps[0].text}`],[w.fault,`${steps[1].outcome}: ${steps[1].text}`],[w.before,e.before]]
    : tourIndex===2 ? [[w.change,e.after],[w.candidate,`${steps[2].outcome}: ${steps[2].text}`]]
    : [[w.observed,`${steps[3].outcome}: ${steps[3].text}`],[w.verified,e.verification]];
  $("tour-step-fields").replaceChildren();
  for (const [label,text] of fields) {
    const box=node("div",undefined,"tour-field");box.append(node("h4",label),node("p",text));$("tour-step-fields").append(box);
  }
  for (const [index,button] of Array.from($("tour-steps").querySelectorAll("button")).entries()) {
    button.textContent=`${index+1}. ${w.steps[index]}`;
    if(index===tourIndex)button.setAttribute("aria-current","step");else button.removeAttribute("aria-current");
  }
  $("tour-previous").disabled=tourIndex===0;$("tour-previous").textContent=w.previous;
  $("tour-next").disabled=tourIndex===3;$("tour-next").textContent=tourIndex===3?w.complete:w.next(w.steps[tourIndex+1]);
  $("tour-boundary").textContent=e.boundary;$("tour-source-value").textContent=e.source_value;$("tour-source-note").textContent=e.source_note;
  $("tour-fingerprint").textContent=e.record_fingerprint;
  hidden("tour-temppath-note",e.id!=="temporary-file-cleanup");$("tour-temppath-note").textContent=w.temppath;
  $("tour-more").open=false;
  if(focus){$("tour-step-title").focus({preventScroll:true});$("tour-step-panel").scrollIntoView({behavior:"auto",block:"nearest"});}
}
function openRecordedTour(id,focus=false) {
  const record=repairExamples.find(e=>e.id===id);if(!record)return;
  tourRecord=record;tourIndex=0;renderRecordedTour(focus);
  if(focus)$("recorded-demo").scrollIntoView({behavior:"auto",block:"start"});
}
function initializeRecordedTour() {
  for(const e of repairExamples){const option=node("option",e.label);option.value=e.id;$("tour-example").append(option);}
  $("tour-example").addEventListener("change",()=>openRecordedTour($("tour-example").value,true));
  for(const [index,button] of Array.from($("tour-steps").querySelectorAll("button")).entries())button.addEventListener("click",()=>{tourIndex=index;renderRecordedTour(true);});
  $("tour-previous").addEventListener("click",()=>{if(tourIndex>0){tourIndex--;renderRecordedTour(true);}});
  $("tour-next").addEventListener("click",()=>{if(tourIndex<3){tourIndex++;renderRecordedTour(true);}});
  $("start-recorded-demo").addEventListener("click",event=>{event.preventDefault();openRecordedTour("lock-cleanup",true);});
  renderRecordedTour();window.reqloxRecordedTourReady=true;
}
if($("recorded-demo"))initializeRecordedTour();

let selectedRepairExample;
function selectRepairExample(id){
  const example=repairExamples.find(row=>row.id===id);if(!example)return;
  selectedRepairExample=example;hidden("repair-example-detail",false);
  for(const button of document.querySelectorAll("[data-repair-example]")){const selected=button.dataset.repairExample===id;button.setAttribute("aria-expanded",String(selected));button.closest(".repair-example-card").classList.toggle("selected",selected);}
  $("repair-example-title").textContent=example.headline;$("repair-example-targets").textContent=`${example.targets.join(" · ")} / ${example.repair_type}`;
  $("repair-example-source-kind").textContent=`Source: ${example.source_label}. ${example.source_description}`;
  $("repair-example-before").textContent=example.before;$("repair-example-after").textContent=example.after;
  $("repair-example-verification").textContent=example.verification;$("repair-example-source-value").textContent=example.source_value;$("repair-example-source-note").textContent=example.source_note;
  $("repair-example-boundary").textContent=example.boundary;$("repair-example-current-note").textContent=example.current_check_note;
  $("repair-example-date").textContent=`Recorded ${example.date} (JST). ${example.record_kind}.`;$("repair-example-fingerprint").textContent=example.record_fingerprint;
  $("repair-example-stages").replaceChildren();
  for(const [index,stage] of example.stages.entries()){const box=node("div",undefined,"repair-story-step");box.append(node("span",`0${index+1} / ${stage.title}`,"stage-label"),node("strong",stage.outcome),node("p",stage.text));$("repair-example-stages").append(box);}
  hidden("try-recorded-example",!example.current_check_available);$("try-recorded-example").disabled=!config||running;
}
function initializeRepairEvidence(){
  for(const example of repairExamples){
    const card=node("article",undefined,"repair-example-card"),heading=node("h3",example.headline),button=node("button","Inspect the repair →","text-button");
    button.type="button";button.dataset.repairExample=example.id;button.setAttribute("aria-controls","repair-example-detail");button.setAttribute("aria-expanded","false");button.setAttribute("aria-label",`Inspect ${example.label.toLowerCase()} repair evidence`);
    button.addEventListener("click",()=>{selectRepairExample(example.id);if(matchMedia("(max-width: 800px)").matches)$("repair-example-detail").scrollIntoView({behavior:"auto",block:"start"});});
    card.append(node("span",example.label,"eyebrow"),node("p",example.targets.join(" / "),"repair-target-names"),heading,node("p",`Source: ${example.source_label}`,"small muted"),node("p",example.injection,"repair-card-condition"));
    const result=node("div",undefined,"recorded-metric");result.append(node("strong",example.metric),node("span",example.metric_label));card.append(result);
    card.append(node("span",`Recorded ${example.date} · isolated experiment`,"recorded-date"),button);$("repair-example-cards").append(card);
  }
  $("close-repair-example").addEventListener("click",()=>{const id=selectedRepairExample?.id;hidden("repair-example-detail",true);for(const button of document.querySelectorAll("[data-repair-example]")){button.setAttribute("aria-expanded","false");button.closest(".repair-example-card").classList.remove("selected");if(button.dataset.repairExample===id)button.focus();}});
  $("try-recorded-example").addEventListener("click",()=>{if(!config||running||selectedRepairExample?.id!=="lock-cleanup")return;fillSample(config.samples.find(s=>s.id==="reported"));$("method").value="baseline";$("repair").value="rule";$("model-consent").checked=false;methodNote();reset();$("check").scrollIntoView({behavior:"auto",block:"start"});$("run").focus({preventScroll:true});});
  $("download-repair-example").addEventListener("click",()=>{if(!selectedRepairExample)return;const summary={schema:"REQLOX_PUBLIC_REPAIR_EVIDENCE_SUMMARY_V1",evidence_state:"ARCHIVED_NOT_CURRENT_EXECUTION",...selectedRepairExample,raw_records_included:false,execution_authority:false};const url=URL.createObjectURL(new Blob([JSON.stringify(summary,null,2)+"\n"],{type:"application/json"}));const anchor=node("a");anchor.href=url;anchor.download=`reqlox-evidence-${summary.id}.json`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  window.reqloxEvidenceReady=true;
}
initializeRepairEvidence();

let guidedSourceId;
async function saveGuided(){
  window.updateGuidedSource?.();
  const fields={};for(const id of ['report','caller','target','method','repair'])if($(id))fields[id]=$(id).value;
  await window.reqloxWorkspace.save('guided',{fields,sourceId:guidedSourceId});
  $('guided-restoration').textContent=document.documentElement.lang==='ja'?'入力をprivate workspaceへ保存しました。新規実行なし。':'Input draft saved in the private workspace. No new execution.';
}
async function restoreGuided(){
  await window.reqloxWorkspaceReady;
  const saved=await window.reqloxWorkspace.restore('guided');
  for(const [id,value] of Object.entries(saved.data?.fields||{}))if($(id))$(id).value=value;
  guidedSourceId=saved.data?.sourceId;
  if(guidedSourceId){
    const response=await fetch('/api/knowledge/get-excerpt',{method:'POST',headers:{'Content-Type':'application/json','X-REQLOX-Token':config.token},body:JSON.stringify({id:guidedSourceId})});
    const source=await response.json();if(!response.ok)throw Error(source.error||'Source binding unavailable.');
    const showSource=()=>{
      const exact=$('report').value===source.text;
      $('source-kind').textContent=exact?'Exact bound quotation · incident truth unverified':'Edited input · original quotation retained';
      $('guided-source-detail').textContent=JSON.stringify({source_id:source.source_ref.id,source_revision:source.source_ref.revision_id,source_url:source.source_ref.canonical_url,document_id:source.document_ref.id,original_text_sha256:source.document_ref.text_sha256,quotation_span:source.source_location,exact_quotation:source.text,current_input_matches_quotation:exact,natural_truth_certified:false},null,2);
    };
    window.updateGuidedSource=showSource;showSource();$('guided-source-trace').open=true;$('report').addEventListener('input',showSource);
  }
  $('guided-restoration').textContent=saved.data?'Saved input and Source reference restored. No experiment rerun.':'Input can be saved. New experiments and model calls are disabled.';
  document.querySelector('.input-panel').addEventListener('click',()=>setTimeout(()=>window.updateGuidedSource?.(),0));
  $('guided-save').addEventListener('click',()=>saveGuided().catch(error=>{$('guided-restoration').textContent=error.message;}));
  $('run').disabled=true;$('run').textContent=document.documentElement.lang==='ja'?'新規実行は停止中':'New execution disabled';
  let saveTimer;for(const id of ['report','caller','target','method','repair'])$(id).addEventListener('input',()=>{clearTimeout(saveTimer);saveTimer=setTimeout(()=>saveGuided().catch(error=>{$('guided-restoration').textContent=error.message;}),300);});
}
async function execute(){
  if(running||!config)return;
  const payload={report:$("report").value,caller:$("caller").value,target:$("target").value,method:$("method").value,repair:$("repair").value,send_to_model:$("model-consent").checked};
  reset();running=true;controls(true);$("status-pill").textContent="Checking";$("result-title").textContent="Checking the supplied report and caller.";$("result-message").textContent="Observations appear when the operation returns.";hidden("busy",false);$("results-column").setAttribute("aria-busy","true");
  try{
    const response=await fetch("/api/run",{method:"POST",headers:{"Content-Type":"application/json","X-REQLOX-Token":config.token},body:JSON.stringify(payload)});
    const data=await response.json();if(!response.ok)throw Error(data.error||"The check could not be verified.");display(data.result,data.download,payload.caller);
  }catch(error){hasResult=true;$("error").textContent=error.message;hidden("error",false);$("status-pill").textContent="Stopped";$("status-pill").className="pill red";$("result-title").textContent="The operation could not be verified.";$("result-message").textContent=error.message;}
  finally{running=false;controls(false);hidden("busy",true);$("results-column").setAttribute("aria-busy","false");}
}
async function init(){
  try{
    const response=await fetch("/api/config");if(!response.ok)throw Error("The startup configuration could not be verified.");config=await response.json();
    for(const sample of config.samples){const button=node("button",(sampleCopy[sample.id]||[sample.id])[0],"sample");button.type="button";button.dataset.sample=sample.id;button.addEventListener("click",()=>fillSample(sample));$("samples").append(button);}
    for(const target of config.targets){const option=node("option",`${target.name} ${target.version}`);option.value=target.name;$("target").append(option);}
    options();if(!config.recorded_repair_available)$("repair").value="rule";fillSample(config.samples[0]);methodNote();
    for(const id of ["report","caller","target","method","repair","model-consent"])$(id).addEventListener(id==="report"||id==="caller"?"input":"change",changed);
    for(const id of ["method","repair"])$(id).addEventListener("change",methodNote);
    $("run").addEventListener("click",execute);
    $("report").addEventListener("input",()=>{$("source-kind").textContent="Supplied text";$("sample-help").textContent="This guided check supports the included lock-cleanup contract. Other mechanisms may remain unresolved.";for(const b of $("samples").children){b.classList.remove("active");b.setAttribute("aria-pressed","false");}});
    $("use-repair").addEventListener("click",()=>{changed();const repaired=$("caller").value===config.repaired_caller;$("caller").value=repaired?originalCaller:config.repaired_caller;$("use-repair").textContent=repaired?"Use the repaired structure":"Restore the original structure";});
    $("download").addEventListener("click",()=>{if(!lastDownload)return;const blob=new Blob([JSON.stringify(lastDownload,null,2)+"\n"],{type:"application/json"});const url=URL.createObjectURL(blob);const a=node("a");a.href=url;a.download=`reqlox-result-${lastDownload.run_id.slice(0,8)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
    try{const raw=sessionStorage.getItem("reqlox-check-excerpt");sessionStorage.removeItem("reqlox-check-excerpt");if(raw){const excerpt=JSON.parse(raw);if(typeof excerpt.text==="string"&&excerpt.text.length<=12000){$("report").value=excerpt.text;$("source-kind").textContent="Supplied excerpt";$("sample-help").textContent=`From ${String(excerpt.title||"your report").slice(0,120)}. The excerpt is not a verified failure or a supported caller contract.`;for(const b of $("samples").children){b.classList.remove("active");b.setAttribute("aria-pressed","false");}}}}catch(_){$("sample-help").textContent="The excerpt could not be restored. Paste it into the report field.";}
    $("run").disabled=true;$("try-recorded-example").disabled=false;await restoreGuided();window.reqloxDemoReady=true;
  }catch(error){$("error").textContent=error.message;hidden("error",false);$("run").disabled=true;}
}
init();
