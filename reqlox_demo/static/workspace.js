"use strict";
// All pages share one server policy. Browser controls are only its presentation.
window.reqloxWorkspace = {
  config:null,
  async request(operation, value) {
    const response=await fetch('/api/workspace/'+operation,{method:'POST',headers:{'Content-Type':'application/json','X-REQLOX-Token':this.config.token},body:JSON.stringify(value)});
    const result=await response.json();if(!response.ok)throw Error(result.error||'Workspace unavailable.');return result;
  },
  save(area,data){return this.request('save-draft',{area,data});},
  restore(area){return this.request('restore-draft',{area});}
};
window.reqloxWorkspaceReady=(async()=>{
  const nav=document.querySelector('nav');
  if(nav&&!nav.querySelector('a[href="/records"]')){const link=document.createElement('a');link.href='/records';link.textContent=document.documentElement.lang==='ja'?'記録・履歴':'Records & history';nav.append(link);}
  if(!document.querySelector('link[href="/workspace.css"]')){const css=document.createElement('link');css.rel='stylesheet';css.href='/workspace.css';document.head.append(css);}
  const banner=document.createElement('aside');banner.id='execution-policy';banner.className='ui-policy';banner.setAttribute('role','status');
  const heading=document.createElement('strong'),note=document.createElement('span'),link=document.createElement('a');link.href='/records';
  const ja=document.documentElement.lang==='ja';heading.textContent=ja?'記録閲覧・ローカル準備モード':'Records and local preparation';link.textContent=ja?'入力から採用判断まで記録を見る →':'Open input → detection → repair → reinjection → decision';
  banner.append(heading,note,link);document.querySelector('header').after(banner);
  try{
    const response=await fetch('/api/workspace/config');if(!response.ok)throw Error('Workspace policy unavailable.');
    const config=await response.json();window.reqloxWorkspace.config=config;
    const p=config.execution_policy;
    note.textContent=ja?`新規注入・モデル呼び出し停止。既存台帳 ${p.cumulative_campaigns}/${p.maximum_campaigns}回・${p.charged_seconds}/${p.maximum_seconds}秒。追加実行可能回数 ${p.remaining_campaigns}。`:`New native/model work disabled. Archived scope: ${p.cumulative_campaigns}/${p.maximum_campaigns} campaigns · ${p.charged_seconds}/${p.maximum_seconds}s charged · ${p.remaining_campaigns} additional campaigns authorized.`;
    for(const id of ['run','target-run','run-comparison','native-consent']){const control=document.getElementById(id);if(control)control.disabled=true;}
    return config;
  }catch(error){note.textContent=error.message;banner.classList.add('error');throw error;}
})();
