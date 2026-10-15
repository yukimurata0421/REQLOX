"use strict";
const recordElement=id=>document.getElementById(id);
let recordConfig,currentRecord,recordStep=0;
const stageLabels={input:'Input',detection:'Detection',repair:'Repair',reinjection:'Reinjection / confirmation',decision:'Adoption decision'};
function item(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}
function renderRecord(){
  const row=currentRecord,stage=row.steps[recordStep];
  recordElement('record-title').textContent=row.title;recordElement('record-date').textContent=`Observed: ${row.observed_at_jst} JST · ${row.id} · archived record`;
  recordElement('record-stage-title').textContent=`${recordStep+1}. ${stageLabels[stage.stage]}`;recordElement('record-stage-status').textContent=stage.status;recordElement('record-stage-description').textContent=stage.description;
  recordElement('record-steps').replaceChildren();row.steps.forEach((s,index)=>{const li=document.createElement('li'),button=item('button',`${index+1}. ${stageLabels[s.stage]}`);button.type='button';button.setAttribute('aria-current',index===recordStep?'step':'false');button.addEventListener('click',()=>selectStep(index));li.append(button);recordElement('record-steps').append(li);});
  recordElement('record-previous').disabled=recordStep===0;recordElement('record-next').disabled=recordStep===row.steps.length-1;
  recordElement('record-decision').textContent=`Recorded decision: ${row.decision}`;recordElement('record-held').textContent=`Atomic bindings HELD: ${row.held_atomic_bindings}. ${row.temppath_repair_performed===false?'Temppath repair not performed in the copied-Target scope.':'Earlier demonstration; separate from the copied-Target scope.'} Originals preserved.`;
  recordElement('record-limits').textContent=row.limits+(row.historical_raw_evidence_gap?' Historical missing raw evidence remains unrecovered.':'');
  recordElement('record-source-title').textContent=row.source.title;recordElement('record-source-kind').textContent=row.source.kind;recordElement('record-source-text').textContent=row.source.text;
  recordElement('record-source-boundary').textContent='This is a curated input summary. Exact original source text is not distributed here; this summary does not certify the original quotation or a natural incident.';
  const identity=recordElement('record-source-identity');identity.replaceChildren();for(const [key,value] of [['Source summary ID',row.source.id],['Summary text SHA-256',row.source.text_sha256],['Archived record SHA-256',row.record_sha256]])identity.append(item('dt',key),item('dd',value));
  recordElement('record-evidence').replaceChildren();for(const ref of row.evidence_refs)recordElement('record-evidence').append(item('li',`${ref.id} · ${ref.sha256}`));
  recordElement('record-status').textContent=`Stage ${recordStep+1}/${row.steps.length}. Saved observations only; new native campaigns 0; model calls 0.`;
  const url=new URL(location.href);url.searchParams.set('record',row.id);url.searchParams.set('step',String(recordStep));history.replaceState(null,'',url);
}
async function retainRecord(){await window.reqloxWorkspace.save('records',{id:currentRecord.id,step:recordStep});}
async function selectStep(index){recordStep=index;try{await retainRecord();renderRecord();}catch(error){recordElement('record-status').textContent=error.message;}}
async function selectRecord(id,index=0){
  currentRecord=await window.reqloxWorkspace.request('open',{id});recordStep=Number.isInteger(index)?Math.max(0,Math.min(index,currentRecord.steps.length-1)):0;recordElement('record-choice').value=id;await retainRecord();renderRecord();
}
async function renderHistory(){
  const value=await window.reqloxWorkspace.request('history',{});const container=recordElement('workspace-history');container.replaceChildren();
  if(!value.records.length)container.append(item('p','No private preparation or review records yet. Archived experiment records are available above.'));
  for(const row of value.records){const block=document.createElement('div');block.className='history-row';const button=item('button',`${row.area} · ${row.operation} · ${row.status}`);button.className='text-button';button.type='button';
    button.addEventListener('click',async()=>{try{const value=await window.reqloxWorkspace.request('open',{id:row.id,area:row.area});recordElement('history-detail').textContent=JSON.stringify(value,null,2);recordElement('history-error').textContent='Saved summary opened; no new execution.';}catch(error){recordElement('history-error').textContent=error.message;}});
    const link=item('a','Return to restored workspace →');link.href='/'+row.area;link.className='text-link';block.append(button,item('span',row.id),link);container.append(block);
  }
}
window.reqloxRecordsReady=false;
(async()=>{
  try{
    recordConfig=await window.reqloxWorkspaceReady;for(const row of recordConfig.archive){const option=item('option',row.title);option.value=row.id;recordElement('record-choice').append(option);}
    const draft=await window.reqloxWorkspace.restore('records'),params=new URLSearchParams(location.search),id=params.get('record')||draft.data?.id||'integration-caller-v01';
    await selectRecord(id,Number(params.get('step')??draft.data?.step??0));await renderHistory();
    recordElement('record-choice').addEventListener('change',()=>selectRecord(recordElement('record-choice').value).catch(error=>{recordElement('record-status').textContent=error.message;}));
    recordElement('record-previous').addEventListener('click',()=>selectStep(recordStep-1));recordElement('record-next').addEventListener('click',()=>selectStep(recordStep+1));
    recordElement('refresh-history').addEventListener('click',()=>renderHistory().catch(error=>{recordElement('history-error').textContent=error.message;}));
    window.reqloxRecordsReady=true;return true;
  }catch(error){recordElement('record-status').textContent=error.message;return false;}
})();
