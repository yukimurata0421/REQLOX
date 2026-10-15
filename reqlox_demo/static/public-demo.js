'use strict';
const panels = ['method', 'records', 'boundary'];
const stageNames = ['Input', 'Detection', 'Repair', 'Re-injection', 'Decision'];
let archive, selected = 'integration-caller-v01', stage = 0, panel = 'method';
const el = id => document.getElementById(id);
function paragraph(parent, value, className = '') {
  const p = document.createElement('p'); p.textContent = value; p.className = className; parent.append(p); return p;
}
function route() {
  const h = new URLSearchParams(location.hash.slice(1));
  panel = panels.includes(h.get('view')) ? h.get('view') : 'method';
  selected = archive.records.some(r => r.id === h.get('record')) ? h.get('record') : 'integration-caller-v01';
  stage = /^[0-4]$/.test(h.get('stage') || '') ? Number(h.get('stage')) : 0;
  render();
}
function navigate(view = panel, record = selected, step = stage) {
  location.hash = new URLSearchParams({view, record, stage: step}).toString();
}
function render() {
  panels.forEach(name => { el(name).hidden = name !== panel; });
  document.querySelectorAll('[data-panel]').forEach(b => b.setAttribute('aria-current', String(b.dataset.panel === panel)));
  el('record').value = selected;
  const row = archive.records.find(r => r.id === selected), result = row.steps[stage];
  const target = el('record-stage'); target.replaceChildren();
  paragraph(target, `${stage + 1} / ${stageNames[stage]} · ${row.observed_at_jst} JST`, 'eyebrow');
  const title = document.createElement('h3'); title.textContent = row.title; target.append(title);
  paragraph(target, result.status, 'status'); paragraph(target, result.description);
  paragraph(target, `Decision: ${row.decision}. Originals preserved: ${row.originals_preserved ? 'yes' : 'unknown'}.`);
  if (row.held_atomic_bindings) paragraph(target, `HELD: ${row.held_atomic_bindings} atomic bindings. temppath repair: NOT PERFORMED.`, 'held');
  if (row.historical_raw_evidence_gap) paragraph(target, 'Historical raw evidence gap: UNKNOWN; the missing observations have not been recovered.', 'held');
  paragraph(target, row.limits, 'muted');
  const source = el('source-detail'); source.replaceChildren();
  paragraph(source, `${row.source.title} · ${row.source.binding}`); paragraph(source, row.source.text);
  paragraph(source, `Source summary SHA-256: ${row.source.text_sha256}`, 'hash');
  paragraph(source, `Archive record SHA-256: ${row.archive_record_sha256}`, 'hash');
  row.evidence_refs.forEach(ref => paragraph(source, `Evidence summary: ${ref.id} · ${ref.sha256}`, 'hash'));
  paragraph(source, 'Curated summary only. Raw Source and provider responses are not published. A matching hash does not restore missing raw evidence.', 'muted');
  el('previous').disabled = stage === 0; el('next').disabled = stage === 4;
  document.querySelectorAll('[data-stage]').forEach(b => b.setAttribute('aria-current', String(Number(b.dataset.stage) === stage)));
}
async function start() {
  const response = await fetch('public-demo.json', {credentials: 'omit', cache: 'no-store'});
  if (!response.ok) throw new Error('archive unavailable');
  archive = await response.json();
  const checked = {...archive}; delete checked.publication_sha256;
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(checked)))))
    .map(x => x.toString(16).padStart(2, '0')).join('');
  if (hash !== archive.publication_sha256) throw new Error('publication hash differs');
  const l = archive.ledger;
  if (archive.schema !== 'reqlox.public-readonly-demo.v1' || archive.mode !== 'ARCHIVED_READ_ONLY' ||
      l.campaigns !== 15 || l.campaign_limit !== 15 || l.charged_seconds !== 62 || l.remaining_campaigns !== 0 ||
      archive.new_native_campaigns !== 0 || archive.new_model_calls !== 0) throw new Error('publication boundary differs');
  el('ledger').textContent = `Copied Target scope · ${l.campaigns}/${l.campaign_limit} campaigns · ${l.charged_seconds}/${l.seconds_limit} seconds · CLOSED`;
  el('publication-hash').textContent = archive.publication_sha256;
  archive.records.forEach(r => { const o = document.createElement('option'); o.value = r.id; o.textContent = r.title; el('record').append(o); });
  stageNames.forEach((name, i) => { const b = document.createElement('button'); b.textContent = `${i + 1} · ${name}`; b.dataset.stage = i; b.addEventListener('click', () => navigate('records', selected, i)); el('stages').append(b); });
  el('record').addEventListener('change', e => navigate('records', e.target.value, 0));
  el('previous').addEventListener('click', () => navigate('records', selected, Math.max(0, stage - 1)));
  el('next').addEventListener('click', () => navigate('records', selected, Math.min(4, stage + 1)));
  document.querySelectorAll('[data-panel]').forEach(b => b.addEventListener('click', () => navigate(b.dataset.panel)));
  window.addEventListener('hashchange', route); route(); window.reqloxPublicDemoReady = true;
}
start().catch(() => { panels.forEach(p => { el(p).hidden = true; }); el('error').hidden = false; });
