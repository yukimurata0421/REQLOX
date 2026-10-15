"use strict";
const byId=id=>document.getElementById(id);
let studyConfig, preparationId, capsuleId, frozenId, registrationId, lastSummary;
let busy=false, nativeRunning=false,studyRecordIds={};
const pretty=value=>JSON.stringify(value,null,2);
const parse=id=>JSON.parse(byId(id).value);
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const errorMessages={
  PREPARATION_HELD:"Preparation is held. Resolve its missing or unsupported prerequisites first.",
  CONFIRMATION_DEPENDENCY_OR_GROUP_OVERLAP:"Training and confirmation share declared groups or content. Use separate inputs.",
  CONFIRMATION_ALREADY_LABELED:"Registration requires unlabeled confirmation forecasts.",
  CONFIRMATION_FORECAST_DRIFT:"Confirmation changed the frozen forecasts. Only labels and their authority may change.",
  UI_FROZEN_COMPARISON_ALREADY_STARTED:"This freeze has already run. Create a fresh freeze for another comparison.",
  UI_ANOTHER_RUN_ACTIVE:"An experiment is active. Wait for its retained result.",
  UI_NATIVE_EXECUTION_NOT_SELECTED:"Select isolated execution before starting the comparison.",
  UI_NATIVE_EXECUTION_DISABLED:"Native comparison is disabled in this server. Preparation, freezing, and scoring remain available."
};
function showError(error){
  byId("study-error").textContent=errorMessages[error.message]||error.message;
  byId("study-error").classList.remove("hidden");
}
function clearError(){byId("study-error").classList.add("hidden");}
function element(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function status(id,text,tone="neutral"){byId(id).textContent=text;byId(id).className=`pill ${tone}`;}
function syncButtons(){
  const available=Boolean(studyConfig)&&!busy&&!nativeRunning;
  document.querySelectorAll("main input,main textarea,main select").forEach(n=>{n.disabled=busy||nativeRunning;});
  byId("recipe").disabled=!available||!preparationId;
  byId("prepare-target").disabled=!available;
  byId("load-example").disabled=!available;
  byId("freeze-comparison").disabled=!available||!preparationId;
  byId("native-limit").disabled=true;byId("wall-seconds").disabled=true;
  byId("native-consent").disabled=!available||studyConfig?.native_execution_enabled!==true;
  byId("run-comparison").disabled=!available||!frozenId||studyConfig?.native_execution_enabled!==true||!byId("native-consent").checked;
  for(const id of ["score-forecasts","register-calibration"])byId(id).disabled=!available;
  byId("review-calibration").disabled=!available||!registrationId;
  byId("download-summary").disabled=!lastSummary;
}
function retain(summary){lastSummary=summary;syncButtons();}
async function request(operation,value){
  const response=await fetch(`/api/study/${operation}`,{method:"POST",headers:{"Content-Type":"application/json","X-REQLOX-Token":studyConfig.token},body:JSON.stringify(value)});
  const body=await response.json();if(!response.ok)throw Error(body.error||"The input could not be verified.");if(body.id)studyRecordIds[operation]=body.id;return body;
}
async function action(work){
  clearError();busy=true;syncButtons();
  try{await work();await persistStudy();}catch(error){showError(error);}finally{busy=false;syncButtons();}
}
function metricValue(value){return value===null||value===undefined?"Unknown":typeof value==="number"&&!Number.isInteger(value)?value.toFixed(4):String(value);}
function metrics(id,rows){
  byId(id).replaceChildren();
  for(const [label,value,note] of rows){const n=element("div",undefined,"metric");n.append(element("span",label,"label"),element("strong",metricValue(value)),element("span",note||"","unit"));byId(id).append(n);}
}
function reasons(id,values){
  byId(id).replaceChildren();if(!values.length)return;
  const list=element("ul",undefined,"reason-list");for(const value of values)list.append(element("li",value.replaceAll("_"," ").toLowerCase()));byId(id).append(list);
}
function invalidatePreparation(){
  delete studyRecordIds.prepare;delete studyRecordIds.capsule;
  preparationId=undefined;capsuleId=undefined;frozenId=undefined;lastSummary=undefined;
  for(const id of ["prepare-metrics","prepare-reasons"])byId(id).replaceChildren();
  invalidateFreeze();
  byId("recipe").disabled=true;status("prepare-status","Input changed");
  byId("prepare-message").textContent="Inputs changed. Prepare them again before using a documented caller.";
  byId("prepare-binding").textContent="Prepare the edited inputs before using a caller.";
  byId("freeze-message").textContent="Prepare the edited inputs first.";syncButtons();
}
function invalidateFreeze(){
  delete studyRecordIds.freeze;
  frozenId=undefined;lastSummary=undefined;status("compare-status","Inputs not frozen");
  byId("compare-message").textContent="Freeze these inputs before comparing. A previous result is not shown as a result for the current inputs.";
  for(const id of ["compare-metrics","arm-results"])byId(id).replaceChildren();
  byId("freeze-message").textContent="Freeze the current incident text and selected caller before execution.";syncButtons();
}
function invalidateRegistration(){delete studyRecordIds.register;delete studyRecordIds.review;registrationId=undefined;lastSummary=undefined;status("calibration-status","Inputs changed");byId("calibration-message").textContent="Freeze and review the current candidate; the earlier review is no longer displayed.";byId("calibration-scores").replaceChildren();byId("calibration-reasons").replaceChildren();byId("registration-message").textContent="Training or forecasts changed. Freeze a new candidate before review.";syncButtons();}
function invalidateScore(){delete studyRecordIds.score;lastSummary=undefined;status("score-status","Inputs changed");byId("score-metrics").replaceChildren();drawChart([]);syncButtons();}
function readIncident(){
  try{
    const source=parse("source-input"),names=Object.keys(source.documents||{}),selected=byId("incident-document").value;
    byId("incident-type").value=source.source_type||"";byId("incident-url").value=source.url||"";
    byId("incident-document").replaceChildren();
    for(const name of names){const n=element("option",name);n.value=name;byId("incident-document").append(n);}
    if(names.includes(selected))byId("incident-document").value=selected;
    byId("incident-text").value=source.documents?.[byId("incident-document").value]||"";
  }catch(_){byId("incident-text").value="";byId("incident-url").value="";byId("incident-type").value="";byId("incident-document").replaceChildren(element("option","Check the structured Source JSON"));}
}
function writeIncident(){
  invalidateFreeze();
  try{const source=parse("source-input"),key=byId("incident-document").value;
    if(!key||!source.documents||!Object.hasOwn(source.documents,key))throw Error("Add a document in the structured Source input first.");
    source.source_type=byId("incident-type").value;source.url=byId("incident-url").value;source.documents[key]=byId("incident-text").value;byId("source-input").value=pretty(source);
  }catch(error){showError(error instanceof SyntaxError?Error("Correct the structured Source JSON before editing its fields."):error);}
}
function loadExample(){
  if(nativeRunning)return;
  const e=studyConfig.example;
  byId("project").value=e.project;byId("input-mode").value="snapshot";
  for(const [id,value] of [["sources",e.sources],["documents",e.documents],["known-projects",[]],
    ["source-input",e.source],["score-data",e.confirmation],["training-data",e.training],
    ["forecast-data",e.forecasts],["confirmation-data",e.confirmation]])byId(id).value=pretty(value);
  for(const id of ["python-files","wheel-files","score-file"])byId(id).value="";
  readIncident();inputMode();invalidatePreparation();invalidateRegistration();
  status("prepare-status","Not prepared");status("compare-status","Not executed");
  status("score-status","Not scored");status("calibration-status","Not reviewed");
  for(const id of ["prepare-metrics","prepare-reasons","compare-metrics","arm-results","score-metrics","calibration-scores","calibration-reasons"])byId(id).replaceChildren();
  byId("prepare-message").textContent="Owned synthetic input loaded. Prepare it to find supported documented callers.";
  byId("compare-message").textContent="Completion, fault discovery, and repair adoption are separate results.";
  byId("prepare-binding").textContent="";byId("recipe").replaceChildren(element("option","No caller selected"));
  byId("native-consent").checked=false;lastSummary=undefined;drawChart([]);clearError();syncButtons();
}
function inputMode(){const wheels=byId("input-mode").value==="wheels";byId("wheel-inputs").classList.toggle("hidden",!wheels);byId("snapshot-inputs").classList.toggle("hidden",wheels);}
async function wheelInputs(){
  const files=Array.from(byId("wheel-files").files);
  if(!files.length||files.length>8||files.reduce((n,f)=>n+f.size,0)>studyConfig.maximum_wheel_bytes)throw Error("Select 1–8 wheels, with at most 4 MiB in total.");
  const wheels=[];
  for(const file of files){
    const bytes=new Uint8Array(await file.arrayBuffer());let raw="";
    for(let i=0;i<bytes.length;i+=32768)raw+=String.fromCharCode(...bytes.subarray(i,i+32768));
    const hash=new Uint8Array(await crypto.subtle.digest("SHA-256",bytes));
    wheels.push({name:file.name,sha256:Array.from(hash,v=>v.toString(16).padStart(2,"0")).join(""),base64:btoa(raw)});
  }
  return wheels;
}
async function prepare(){
  preparationId=undefined;frozenId=undefined;byId("recipe").disabled=true;
  const payload={project:byId("project").value,documents:parse("documents"),known_projects:parse("known-projects")};
  if(byId("input-mode").value==="wheels"){
    const capsule=await request("capsule",{project:payload.project,wheels:await wheelInputs()});retain(capsule);
    capsuleId=capsule.id;payload.capsule_id=capsuleId;
  }else payload.sources=parse("sources");
  const result=await request("prepare",payload);retain(result);
  status("prepare-status",result.status,result.status==="READY_STATICALLY"?"green":"amber");
  byId("prepare-message").textContent=result.status==="READY_STATICALLY"?"A supported documented caller is ready for a bounded comparison. Native behavior remains unobserved.":"Preparation is held. These inputs do not yet support the comparison.";
  metrics("prepare-metrics",[["Source files",result.source_files],["Documented callers",result.recipes.length],["Target imports",0]]);
  reasons("prepare-reasons",result.reasons);byId("recipe").replaceChildren();
  for(const recipe of result.recipes){const n=element("option",`${recipe.module}.${recipe.symbol}`);n.value=recipe.index;byId("recipe").append(n);}
  if(result.status==="READY_STATICALLY"){preparationId=result.id;byId("recipe").disabled=false;}
  byId("prepare-binding").textContent=`Private preparation ${result.id}. Project history is caller-declared only.`;
  invalidateFreeze();retain(result);
}
async function freeze(){
  frozenId=undefined;
  const result=await request("freeze",{preparation_id:preparationId,source:parse("source-input"),
    recipe_index:Number(byId("recipe").value),budget:Number(byId("discovery-budget").value)});
  frozenId=result.id;retain(result);
  byId("freeze-message").textContent=`Frozen ${result.id} · ${result.discovery_budget_per_arm} discovery campaigns per arm · shared confirmation conditions.`;
}
function displayComparison(result){
  retain(result);status("compare-status",result.status,result.status==="COMPLETE"?"green":result.status==="RUNNING"?"neutral":"amber");
  metrics("compare-metrics",[["Native campaigns",result.native_campaigns],["Additional changes adopted",result.source_added_adoptions,"With incident text compared to without"],["Paid model calls",0]]);
  byId("arm-results").replaceChildren();
  if(result.discovered_faults)for(const [key,label] of [["NO_SOURCE","Without incident text"],["SOURCE","With incident text"]]){
    const row=element("tr");for(const value of [label,result.discovered_faults[key],result.unknown_conditions[key],result.candidate_adopted[key]?"Yes":"No"])row.append(element("td",metricValue(value)));byId("arm-results").append(row);
  }
  byId("compare-message").textContent=result.status==="RUNNING"?"The frozen comparison is running. Detailed receipts remain private.":result.status==="COMPLETE"?"Comparison complete. Compare both searches below. Completion does not imply an adopted change or added value from incident knowledge.":`The comparison is ${result.status.toLowerCase()}. ${result.reason?errorMessages[result.reason]||result.reason:"No successful comparison is claimed."}`;
}
async function watchJob(id){
  nativeRunning=true;syncButtons();byId("comparison-results").setAttribute("aria-busy","true");byId("comparison-busy").classList.remove("hidden");
  try{
    for(let i=0;i<120;i++){
      const response=await fetch(`/api/study/job/${id}`,{headers:{"X-REQLOX-Token":studyConfig.token}});
      const result=await response.json();if(!response.ok)throw Error(result.error||"The job could not be verified.");displayComparison(result);
      if(result.status!=="RUNNING"){sessionStorage.removeItem("reqlox-study-job");return;}
      await delay(2000);
    }
    throw Error("The observation window ended. The private job record remains; this page will not retry execution.");
  }catch(error){showError(error);}finally{
    nativeRunning=false;frozenId=undefined;byId("comparison-busy").classList.add("hidden");byId("comparison-results").setAttribute("aria-busy","false");syncButtons();
  }
}
async function runComparison(){
  const result=await request("compare-run",{freeze_id:frozenId,seconds:Number(byId("wall-seconds").value),
    maximum_campaigns:Number(byId("native-limit").value),execute_isolated_code:byId("native-consent").checked});
  sessionStorage.setItem("reqlox-study-job",result.id);displayComparison(result);watchJob(result.id);
}
function svgNode(tag,attrs,text){const n=document.createElementNS("http://www.w3.org/2000/svg",tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;}
function drawChart(bins){
  const svg=byId("reliability-chart");svg.replaceChildren(svgNode("title",{id:"chart-title"},"Reliability diagnostic for supplied rows"));
  const x=p=>48+p*274,y=p=>205-p*174;
  for(const tick of [0,.5,1]){
    svg.append(svgNode("line",{x1:x(tick),y1:31,x2:x(tick),y2:205,class:"chart-grid"}),svgNode("line",{x1:48,y1:y(tick),x2:322,y2:y(tick),class:"chart-grid"}));
    svg.append(svgNode("text",{x:x(tick),y:224,"text-anchor":"middle",class:"chart-label"},tick),svgNode("text",{x:35,y:y(tick)+4,"text-anchor":"end",class:"chart-label"},tick));
  }
  svg.append(svgNode("line",{x1:48,y1:205,x2:322,y2:31,class:"chart-reference"}));
  const descriptions=[];
  for(const bin of bins.filter(b=>b.count>0)){
    const point=svgNode("circle",{cx:x(bin.mean_pass_probability),cy:y(bin.observed_pass_fraction),r:Math.min(15,4+Math.sqrt(bin.count)*2),class:"chart-point"});
    const description=`${bin.count} scored rows; mean PASS probability ${bin.mean_pass_probability.toFixed(3)}, observed PASS fraction ${bin.observed_pass_fraction.toFixed(3)}`;
    point.append(svgNode("title",{},description));descriptions.push(description);svg.append(point);
  }
  svg.append(svgNode("text",{x:184,y:244,"text-anchor":"middle",class:"chart-label"},"Mean PASS probability"),svgNode("desc",{id:"chart-description"},descriptions.join(". ")||"No scored rows yet."));
}
function renderScore(result){
  status("score-status","Diagnostic","amber");
  const s=result.scores;
  metrics("score-metrics",[["Total rows",s.total_rows],["Scored rows",s.scored_rows],["Unscored rows",s.unknown_rows,"Includes unknown labels or invalid/missing forecasts"],["Binary Brier",s.scalar_binary_brier],["Log loss",s.log_loss_infinite?"Infinite":s.binary_log_loss],["Empirical ECE",s.empirical_ece,"Diagnostic; independence unverified"]]);
  drawChart(s.reliability_bins);
}
async function score(){
  const result=await request("score",{dataset:parse("score-data")});retain(result);status("score-status","Diagnostic","amber");
  renderScore(result);
}
async function register(){
  registrationId=undefined;
  const result=await request("register",{training:parse("training-data"),forecasts:parse("forecast-data")});registrationId=result.id;retain(result);
  byId("registration-message").textContent=`Candidate ${result.id} frozen from ${result.training_rows} training rows and ${result.confirmation_rows} unlabeled forecasts. Serving remains RAW / 0.85.`;
}
function renderReview(result){
  status("calibration-status",result.status,"amber");
  byId("calibration-message").textContent="Review held. Natural forecast and native-label provenance remain unverified. Serving remains RAW / 0.85; this candidate was not activated.";
  const table=element("table"),head=element("thead"),header=element("tr");for(const title of ["Metric","Raw","Candidate"]){const cell=element("th",title);cell.scope="col";header.append(cell);}head.append(header);table.append(head);const body=element("tbody");
  for(const [key,label] of [["scored_rows","Scored rows"],["unknown_rows","Unscored rows"],["scalar_binary_brier","Binary Brier"],["binary_log_loss","Log loss"],["empirical_ece","Empirical ECE"]]){
    const row=element("tr");for(const value of [label,...[result.raw,result.candidate].map(s=>key==="binary_log_loss"&&s.log_loss_infinite?"Infinite":s[key])])row.append(element("td",metricValue(value)));body.append(row);
  }
  table.append(body);byId("calibration-scores").replaceChildren(table);reasons("calibration-reasons",result.reasons);
}
async function review(){
  const result=await request("review",{registration_id:registrationId,confirmation:parse("confirmation-data")});retain(result);status("calibration-status",result.status,"amber");
  renderReview(result);
}
function selectTab(name){
  for(const key of ["prepare","compare","calibration"]){const selected=key===name;byId(`tab-${key}`).setAttribute("aria-selected",String(selected));byId(`tab-${key}`).tabIndex=selected?0:-1;byId(`pane-${key}`).classList.toggle("hidden",!selected);}
}

function studyDraft(){
  const fields={};for(const node of document.querySelectorAll('main input,main textarea,main select'))if(node.id&&node.type!=='file')fields[node.id]=node.type==='checkbox'?node.checked:node.value;
  return {fields,preparationId,capsuleId,frozenId,registrationId,recordIds:studyRecordIds,tab:document.querySelector('[role="tab"][aria-selected="true"]')?.id.replace('tab-','')||'prepare'};
}
async function persistStudy(){await window.reqloxWorkspaceReady;return window.reqloxWorkspace.save('study',studyDraft());}
async function restoreStudy(){
  await window.reqloxWorkspaceReady;const result=await window.reqloxWorkspace.restore('study');if(!result.data)return;
  const d=result.data;for(const [id,value] of Object.entries(d.fields||{})){const n=byId(id);if(n){if(n.type==='checkbox')n.checked=Boolean(value);else n.value=value;}}
  preparationId=d.preparationId;capsuleId=d.capsuleId;frozenId=d.frozenId;registrationId=d.registrationId;studyRecordIds=d.recordIds||{};
  const restored={};for(const [operation,id] of Object.entries(studyRecordIds)){const value=await window.reqloxWorkspace.request('open',{area:'study',id});restored[operation]=value.summary;}
  const p=restored.prepare;if(p){status('prepare-status',p.status,p.status==='READY_STATICALLY'?'green':'amber');metrics('prepare-metrics',[['Source files',p.source_files],['Documented callers',p.recipes.length],['Target imports',0]]);reasons('prepare-reasons',p.reasons);byId('recipe').replaceChildren();for(const recipe of p.recipes){const n=element('option',`${recipe.module}.${recipe.symbol}`);n.value=recipe.index;byId('recipe').append(n);}byId('recipe').value=d.fields.recipe||'0';byId('prepare-message').textContent='Saved static preparation restored. Native behavior was not rerun.';}
  if(restored.freeze){status('compare-status','FROZEN');byId('compare-message').textContent='Saved comparison inputs restored; native comparison was not executed.';}
  if(restored.freeze)byId('freeze-message').textContent=`Saved freeze ${restored.freeze.id} restored. Execution remains disabled; no budget reset.`;
  if(restored.score)renderScore(restored.score);
  if(restored.review){renderReview(restored.review);status('calibration-status',restored.review.status,'amber');byId('calibration-message').textContent=`Saved review restored; serving ${restored.review.serving.mode}. Candidate not activated.`;reasons('calibration-reasons',restored.review.reasons);}
  lastSummary=restored.review||restored.score||restored.freeze||p;
  byId('study-restored-record').textContent=JSON.stringify(restored,null,2);byId('study-restoration').textContent='Private inputs and saved record references restored. No preparation, review or experiment rerun.';
  inputMode();readIncident();selectTab(['prepare','compare','calibration'].includes(d.tab)?d.tab:'prepare');syncButtons();
}

async function initStudy(){
  try{
    const response=await fetch("/api/study/config");if(!response.ok)throw Error("The workspace configuration could not be verified.");studyConfig=await response.json();
    byId("native-availability").textContent=studyConfig.native_execution_enabled===true
      ?"Native comparison is enabled by this server; its execution requires separately authorized limits."
      :"Native comparison is disabled in this server. Prepare and freeze inputs or inspect forecasts without starting experiments.";
    for(const name of ["prepare","compare","calibration"]){
      const tab=byId(`tab-${name}`);tab.addEventListener("click",()=>selectTab(name));
      tab.addEventListener("keydown",event=>{const names=["prepare","compare","calibration"],index=names.indexOf(name);let next;
        if(event.key==="ArrowRight")next=names[(index+1)%3];if(event.key==="ArrowLeft")next=names[(index+2)%3];if(event.key==="Home")next=names[0];if(event.key==="End")next=names[2];
        if(next){event.preventDefault();selectTab(next);byId(`tab-${next}`).focus();}});
    }
    byId("load-example").addEventListener("click",loadExample);
    for(const id of ["project","sources","documents","known-projects"])byId(id).addEventListener("input",invalidatePreparation);
    byId("input-mode").addEventListener("change",()=>{inputMode();invalidatePreparation();});byId("wheel-files").addEventListener("change",invalidatePreparation);
    byId("source-input").addEventListener("input",()=>{readIncident();invalidateFreeze();});
    for(const id of ["discovery-budget","recipe"])byId(id).addEventListener("input",invalidateFreeze);
    for(const id of ["incident-type","incident-url","incident-text"])byId(id).addEventListener(id==="incident-type"?"change":"input",writeIncident);
    byId("incident-document").addEventListener("change",readIncident);
    byId("score-data").addEventListener("input",invalidateScore);
    byId("confirmation-data").addEventListener("input",()=>{lastSummary=undefined;status("calibration-status","Labels changed");byId("calibration-scores").replaceChildren();byId("calibration-reasons").replaceChildren();byId("calibration-message").textContent="Review the current confirmation labels against the frozen candidate.";syncButtons();});
    byId("native-consent").addEventListener("change",syncButtons);
    for(const id of ["training-data","forecast-data"])byId(id).addEventListener("input",invalidateRegistration);
    for(const [id,work] of [["prepare-target",prepare],["freeze-comparison",freeze],["run-comparison",runComparison],["score-forecasts",score],["register-calibration",register],["review-calibration",review]])byId(id).addEventListener("click",()=>action(work));
    byId("python-files").addEventListener("change",()=>action(async()=>{
      const files=Array.from(byId("python-files").files);if(files.length>128||files.reduce((n,f)=>n+f.size,0)>512*1024)throw Error("Python inputs exceed 128 files or 512 KiB.");
      const map={};for(const file of files){const name=file.webkitRelativePath||file.name;if(!name.endsWith(".py")||file.size>262144||Object.hasOwn(map,name))throw Error("Use distinct Python paths within the per-file bound.");map[name]=await file.text();}
      byId("sources").value=pretty(map);invalidatePreparation();
    }));
    byId("score-file").addEventListener("change",()=>action(async()=>{const file=byId("score-file").files[0];if(!file)return;if(file.size>1024*1024)throw Error("The dataset exceeds 1 MiB.");const text=await file.text();JSON.parse(text);byId("score-data").value=text;invalidateScore();}));
    byId("download-summary").addEventListener("click",()=>{if(!lastSummary)return;const url=URL.createObjectURL(new Blob([pretty(lastSummary)+"\n"],{type:"application/json"}));const a=element("a");a.href=url;a.download=`reqlox-${lastSummary.operation}-${lastSummary.id.slice(0,8)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
    loadExample();await restoreStudy();window.reqloxStudyReady=true;
    let saveTimer;for(const n of document.querySelectorAll("main input,main textarea,main select"))if(n.type!=="file")n.addEventListener("input",()=>{clearTimeout(saveTimer);saveTimer=setTimeout(()=>persistStudy().catch(showError),300);});
    for(const n of document.querySelectorAll("[role=tab]"))n.addEventListener("click",()=>persistStudy().catch(showError));
    const pending=sessionStorage.getItem("reqlox-study-job");if(pending){selectTab("compare");watchJob(pending);}
  }catch(error){showError(error);}
}
initStudy();
