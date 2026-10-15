'use strict';
const element=id=>document.getElementById(id);
const input=id=>JSON.parse(element(id).value);
let token,indexId,planId,example,busy=false,searchResults=[];
function enabled(){
  document.querySelectorAll('.knowledge-action').forEach(button=>{button.disabled=!token||busy;});
  element('knowledge-search').disabled=!token||busy||!indexId;
  element('knowledge-route').disabled=!token||busy||!planId;
  document.querySelectorAll('main input,main textarea').forEach(n=>{n.disabled=busy;});
}
function invalidateIndex(){indexId=undefined;searchResults=[];element('knowledge-results').textContent='Report inputs changed. Rebuild the index before searching.';enabled();}
function invalidatePlan(){planId=undefined;element('knowledge-ir-result').textContent='';element('knowledge-review-summary').textContent='Candidate inputs changed. Freeze new questions before reviewing.';enabled();}
async function post(operation,value){
  const response=await fetch('/api/knowledge/'+operation,{method:'POST',headers:{'Content-Type':'application/json','X-REQLOX-Token':token},body:JSON.stringify(value)});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Operation stopped.');return result;
}
function action(id,work){
  element(id).addEventListener('click',async()=>{
    if(busy||!token)return;busy=true;enabled();element('knowledge-status').textContent='Processing supplied inputs…';
    try{const message=await work();await persistKnowledge();element('knowledge-status').textContent=message||'Completed. Provider calls: 0.';}
    catch(error){element('knowledge-status').textContent=error instanceof SyntaxError?'Check the JSON input.':error.message;}
    finally{busy=false;enabled();}
  });
}
function reportExample(){
  const document=example.documents[0];
  element('knowledge-report-title').value=document.title||'';element('knowledge-report-url').value=document.url||'';element('knowledge-report-text').value=document.text||'';
  element('knowledge-documents').value=JSON.stringify(example.documents,null,2);element('knowledge-use-json').checked=false;
  invalidateIndex();element('knowledge-status').textContent='Included owned example loaded. Build its index to search. No provider calls.';
}
action('knowledge-load-example',async()=>{reportExample();return 'Included report restored. Rebuild the index to search it.';});
action('knowledge-import',async()=>{
  indexId=undefined;
  const documents=element('knowledge-use-json').checked?input('knowledge-documents'):[{url:element('knowledge-report-url').value.trim(),title:element('knowledge-report-title').value.trim(),text:element('knowledge-report-text').value}];
  if(!Array.isArray(documents)||!documents.length)throw Error('Supply at least one report.');
  if(!element('knowledge-use-json').checked&&(!documents[0].url||!documents[0].text.trim()))throw Error('Add the source URL and report text first.');
  const imported=await post('import',{documents});const indexed=await post('index',{corpus_id:imported.id});indexId=indexed.id;
  element('knowledge-results').textContent=`${indexed.documents} report(s) indexed in ${indexed.chunks} searchable passage(s). Search for a condition above.`;
  return 'Search index ready. Supplied reports were indexed; their claims remain unverified. Provider calls: 0.';
});
action('knowledge-search',async()=>{
  const found=await post('search',{index_id:indexId,query:element('knowledge-query').value});
  searchResults=found.results;renderKnowledgeResults(searchResults);
  return `${found.results.length} matching passage(s). Search rank is not a failure probability. Provider calls: 0.`;
});
action('knowledge-prepare',async()=>{
  planId=undefined;element('knowledge-ir-result').textContent='';
  const result=await post('ir-prepare',{candidate:input('knowledge-candidate'),source_texts:input('knowledge-source-texts')});
  planId=result.id;element('knowledge-ir-result').textContent=JSON.stringify(result,null,2);
  element('knowledge-review-summary').textContent=`${result.questions} review questions frozen. No judgment has been verified. Supply answers or retain UNKNOWN.`;
  return 'Quotation binding checked and review questions frozen. No provider calls.';
});
action('knowledge-route',async()=>{
  const result=await post('ir-route',{plan_id:planId,judgments:input('knowledge-judgments')});
  element('knowledge-ir-result').textContent=JSON.stringify(result,null,2);
  element('knowledge-review-summary').textContent='Supplied judgments processed. Missing answers remain UNKNOWN. Read the structured result for each claim; no automatic cause or incident-membership certification.';
  return 'Review processing completed. This is not a verified-incident verdict. Provider calls: 0.';
});
action('knowledge-score',async()=>{
  const result=await post('score',input('knowledge-scores'));element('knowledge-score-result').textContent=JSON.stringify(result,null,2);
  element('knowledge-score-summary').textContent=`${result.scored_rows}/${result.attempted_rows} rows scored · ${result.unknown_labels} unknown label(s) · ${result.unknown_vectors} missing forecast(s). Missing outcomes remain in the full denominator.`;
  return 'Probability diagnostics calculated for supplied rows. Calibration remains unverified. Provider calls: 0.';
});
for(const id of ['knowledge-report-title','knowledge-report-url','knowledge-report-text'])element(id).addEventListener('input',()=>{element('knowledge-use-json').checked=false;invalidateIndex();});
element('knowledge-use-json').addEventListener('change',invalidateIndex);
element('knowledge-documents').addEventListener('input',()=>{element('knowledge-use-json').checked=true;invalidateIndex();});
for(const id of ['knowledge-candidate','knowledge-source-texts'])element(id).addEventListener('input',invalidatePlan);
element('knowledge-judgments').addEventListener('input',()=>{element('knowledge-ir-result').textContent='';element('knowledge-review-summary').textContent='Answers changed. Review these supplied judgments again.';});
element('knowledge-scores').addEventListener('input',()=>{element('knowledge-score-result').textContent='';element('knowledge-score-summary').textContent='Rows changed. Score the current rows again.';});

function renderKnowledgeResults(results){
  const container=element('knowledge-results');container.replaceChildren();
  if(!results.length)container.textContent='No matching passages. Try a condition or symptom mentioned in the report.';
  for(const result of results){
    const article=document.createElement('article');article.className='library-result';
    const title=document.createElement('h3'),quote=document.createElement('blockquote'),button=document.createElement('button');
    title.textContent=result.title||'Supplied report';quote.textContent=result.excerpt||'No excerpt available.';quote.className='quote';
    button.textContent='Use excerpt in a check →';button.type='button';button.className='text-button';button.disabled=!result.excerpt;
    button.addEventListener('click',async()=>{
      button.disabled=true;
      try{
        const bound=await post('excerpt',{index_id:indexId,source_ref:result.source_ref,document_ref:result.document_ref,source_location:result.source_location});
        await persistKnowledge();await window.reqloxWorkspace.save('guided',{sourceId:bound.id,fields:{report:bound.text}});
        location.assign('/#check');
      }catch(error){element('knowledge-status').textContent=error.message;button.disabled=false;}
    });
    article.append(title,quote,button);container.append(article);
  }
}

function knowledgeDraft(){
  const fields={};for(const node of document.querySelectorAll('main input,main textarea'))if(node.id)fields[node.id]=node.type==='checkbox'?node.checked:node.value;
  return {fields,indexId,planId,searchResults,review:element('knowledge-ir-result').textContent,score:element('knowledge-score-result').textContent,reviewMessage:element('knowledge-review-summary').textContent,scoreMessage:element('knowledge-score-summary').textContent};
}
async function persistKnowledge(){await window.reqloxWorkspaceReady;return window.reqloxWorkspace.save('knowledge',knowledgeDraft());}
async function restoreKnowledge(){
  await window.reqloxWorkspaceReady;const result=await window.reqloxWorkspace.restore('knowledge');if(!result.data)return;
  const data=result.data;for(const [id,value] of Object.entries(data.fields||{})){const node=element(id);if(node){if(node.type==='checkbox')node.checked=Boolean(value);else node.value=value;}}
  indexId=data.indexId;planId=data.planId;searchResults=data.searchResults||[];
  if(searchResults.length)renderKnowledgeResults(searchResults);
  element('knowledge-ir-result').textContent=data.review||'';element('knowledge-score-result').textContent=data.score||'';
  if(data.reviewMessage)element('knowledge-review-summary').textContent=data.reviewMessage;if(data.scoreMessage)element('knowledge-score-summary').textContent=data.scoreMessage;
  element('knowledge-status').textContent='Private draft and record references restored. No search, review or experiment was rerun.';enabled();
}

window.reqloxKnowledgeReady=(async()=>{
  try{
    const response=await fetch('/api/knowledge/config');if(!response.ok)throw Error('The incident workspace is unavailable.');
    const config=await response.json();if(!config.dependencies_available)throw Error('The knowledge package is not available in this deployment.');
    token=config.token;example=config.example;
    for(const [id,key] of [['knowledge-candidate','candidate'],['knowledge-source-texts','source_texts'],['knowledge-scores','scores']])element(id).value=JSON.stringify(example[key],null,2);
    reportExample();await restoreKnowledge();enabled();
    let saveTimer;for(const node of document.querySelectorAll('main input,main textarea'))node.addEventListener('input',()=>{clearTimeout(saveTimer);saveTimer=setTimeout(()=>persistKnowledge().catch(error=>{element('knowledge-status').textContent=error.message;}),300);});
  }catch(error){element('knowledge-status').textContent=error.message;}
})();
