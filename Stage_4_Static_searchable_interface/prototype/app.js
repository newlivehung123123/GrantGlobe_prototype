'use strict';
/* GrantGlobe concept — functional app on live data (dark-space + glass design) */

const LS_PROFILE='gg_profile_v1', LS_AFFINITY='gg_affinity_v1';
const state={all:[],filtered:[],sort:'recommended',profile:null,affinity:null,shown:0,view:'grid'};
const BATCH=60;

const STAGE_OPTIONS=[
  {v:'student',label:'Student / PhD'},{v:'early',label:'Postdoc / Early-career'},
  {v:'established',label:'Established researcher'},{v:'nonprofit',label:'Non-profit / NGO'},
  {v:'industry',label:'Industry / Startup'}];
const STAGE_KW={
  student:['phd','doctoral','studentship','scholarship','student','master','graduate','fellowship','early career','early-career'],
  early:['postdoc','post-doctoral','postdoctoral','early career','early-career','fellowship','junior','new investigator','first grant'],
  established:['research grant','project grant','programme','program grant','investigator','senior','consolidator','advanced','professor']};
const FX={USD:1,EUR:1.08,GBP:1.27,CHF:1.1,CAD:.73,AUD:.66,NZD:.61,JPY:.0067,CNY:.14,HKD:.128,SGD:.74,KRW:.00073,INR:.012,SEK:.095,NOK:.094,DKK:.145,PLN:.25,CZK:.043,ZAR:.054,BRL:.18,MXN:.058,ILS:.27,AED:.27,SAR:.27,TWD:.031};

const $=s=>document.querySelector(s);
const el=(t,c)=>{const e=document.createElement(t);if(c)e.className=c;return e;};

document.addEventListener('DOMContentLoaded',()=>{
  fetch('../data/grants.json').then(r=>{if(!r.ok)throw new Error(r.status);return r.json();})
    .then(p=>init(p.grants||[])).catch(err=>{$('#count').textContent='Could not load data ('+err+')';});

  ['f-status','f-region','f-sector','f-org'].forEach(id=>$('#'+id).addEventListener('change',()=>{state.shown=BATCH;applyAll();}));
  $('#sort').addEventListener('change',e=>{state.sort=e.target.value;state.shown=BATCH;applyAll();});
  let t=null;$('#search').addEventListener('input',()=>{clearTimeout(t);t=setTimeout(()=>{state.shown=BATCH;applyAll();},200);});
  $('#pToggle').addEventListener('click',()=>{const p=$('#panel');const o=p.classList.toggle('open');$('#pToggle').classList.toggle('on',o);});
  $('#pSave').addEventListener('click',()=>{saveProfile();$('#panel').classList.remove('open');$('#pToggle').classList.remove('on');state.sort='recommended';$('#sort').value='recommended';state.shown=BATCH;applyAll();});
  $('#pClear').addEventListener('click',()=>{state.profile=null;try{localStorage.removeItem(LS_PROFILE)}catch(e){}syncChips();updatePersonaliseBtn();state.shown=BATCH;applyAll();});
  $('#showmore').addEventListener('click',()=>{state.shown+=BATCH;render();});
  // view toggle (grid / list / table / grouped)
  state.view=(localStorage.getItem('gg_view')||'grid');
  syncViewButtons();
  document.querySelectorAll('#viewtoggle button').forEach(b=>{
    b.addEventListener('click',()=>{state.view=b.dataset.view;try{localStorage.setItem('gg_view',state.view)}catch(e){}syncViewButtons();state.shown=BATCH;render();});
  });
  $('#overlay').addEventListener('click',e=>{if(e.target===$('#overlay'))closeModal();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
});

function init(grants){
  state.all=grants; state.profile=loadProfile(); state.affinity=loadAffinity();
  buildFilters(grants); buildPanel(grants); syncChips(); updatePersonaliseBtn();
  state.shown=BATCH; applyAll();
}

/* ---------- filters & panel ---------- */
function uniq(grants,getter){const s=new Set();grants.forEach(g=>(getter(g)||[]).forEach(v=>v&&s.add(v)));return [...s].sort();}
function buildFilters(grants){
  fill('#f-status',[...new Set(grants.map(g=>g.current_status).filter(Boolean))].sort());
  fill('#f-region',uniq(grants,g=>[...(g.applicant_base_regions||[]),...(g.geographic_focus_regions||[])]));
  fill('#f-sector',uniq(grants,g=>g.thematic_sectors));
  const indOpt=el('option');indOpt.value='__individuals__';indOpt.textContent='Individuals';$('#f-org').appendChild(indOpt);
  fill('#f-org',uniq(grants,g=>g.organisation_types));
}
function isForIndividuals(g){if((g.individual_eligibility||[]).length)return true;return (g.organisation_types||[]).some(o=>/individual/i.test(o));}
function indTier(g){
  // tier 0 = a GENUINE individual signal (named individual eligibility, e.g.
  // "Early Career Researcher" — fellowships/individual schemes). tier 1 =
  // possibly-individual (eligibility unspecified, OR funder lists "Individuals"
  // among many eligible org types — a broad catch-all on grants.gov programmes).
  // tier 2 = explicitly organisation-only.
  if((g.individual_eligibility||[]).length)return 0;
  const ot=g.organisation_types||[];
  if(!ot.length||ot.some(o=>/individual/i.test(o)))return 1;
  return 2;
}
function fill(sel,vals){const s=$(sel);vals.forEach(v=>{const o=el('option');o.value=v;o.textContent=v;s.appendChild(o);});}
function buildPanel(grants){
  chips('#c-stage',STAGE_OPTIONS.map(o=>({v:o.v,label:o.label})),'single');
  const sc={};grants.forEach(g=>(g.thematic_sectors||[]).forEach(s=>s&&(sc[s]=(sc[s]||0)+1)));
  const top=Object.entries(sc).sort((a,b)=>b[1]-a[1]).slice(0,14).map(([s])=>({v:s,label:s}));
  chips('#c-fields',top,'multi');
  const regs=uniq(grants,g=>[...(g.applicant_base_regions||[]),...(g.geographic_focus_regions||[])]);
  chips('#c-region',[{v:'any',label:'Anywhere'},...regs.map(r=>({v:r,label:r}))],'single');
}
function chips(sel,opts,mode){const c=$(sel);c.innerHTML='';c.dataset.mode=mode;
  opts.forEach(o=>{const b=el('button','chip');b.dataset.v=o.v;b.textContent=o.label;
    b.addEventListener('click',()=>{if(mode==='single'){const was=b.classList.contains('sel');c.querySelectorAll('.chip').forEach(x=>x.classList.remove('sel'));if(!was)b.classList.add('sel');}else b.classList.toggle('sel');});
    c.appendChild(b);});}
function selVals(sel){return [...$(sel).querySelectorAll('.chip.sel')].map(b=>b.dataset.v);}
function setChips(sel,vals){$(sel).querySelectorAll('.chip').forEach(b=>b.classList.toggle('sel',vals.includes(b.dataset.v)));}
function syncChips(){const p=state.profile;setChips('#c-stage',p&&p.stage?[p.stage]:[]);setChips('#c-fields',p&&p.fields?p.fields:[]);setChips('#c-region',p&&p.region?[p.region]:[]);}
function saveProfile(){state.profile={stage:selVals('#c-stage')[0]||'',fields:selVals('#c-fields'),region:selVals('#c-region')[0]||''};try{localStorage.setItem(LS_PROFILE,JSON.stringify(state.profile))}catch(e){}updatePersonaliseBtn();}
function loadProfile(){try{const r=localStorage.getItem(LS_PROFILE);if(r)return JSON.parse(r);}catch(e){}return null;}
function loadAffinity(){try{const r=localStorage.getItem(LS_AFFINITY);if(r)return JSON.parse(r);}catch(e){}return {sectors:{},funders:{}};}
function hasProfile(p){return !!(p&&(p.stage||(p.fields&&p.fields.length)||(p.region&&p.region!=='any')));}
function hasAffinity(a){return !!(a&&a.sectors&&Object.keys(a.sectors).length);}
function updatePersonaliseBtn(){$('#pToggle').classList.toggle('on',hasProfile(state.profile)&&!$('#panel').classList.contains('open'));}

/* ---------- filter + search + order ---------- */
function applyAll(){
  const q=$('#search').value.trim(), st=$('#f-status').value, rg=$('#f-region').value, sc=$('#f-sector').value, ot=$('#f-org').value;
  let r=state.all.filter(g=>{
    if(st&&g.current_status!==st)return false;
    if(rg){const a=[...(g.applicant_base_regions||[]),...(g.geographic_focus_regions||[])];if(!a.includes(rg))return false;}
    if(sc&&!(g.thematic_sectors||[]).includes(sc))return false;
    if(ot){if(ot==='__individuals__'){if(!isForIndividuals(g))return false;}else if(!(g.organisation_types||[]).includes(ot))return false;}
    return true;});
  if(q.length>0){
    const fuse=new Fuse(r,{keys:[{name:'grant_title',weight:.4},{name:'funder_name',weight:.3},{name:'description',weight:.15},{name:'thematic_sectors',weight:.15}],threshold:.35,ignoreLocation:true,minMatchCharLength:2});
    r=fuse.search(q).map(x=>x.item);r.forEach(g=>g._forYou=false);
  } else r=order(r);
  // Individual-first default: when not scoped to a specific organisation type
  // (and not on an explicit deadline/funding sort), float opportunities open to
  // individuals to the top — clearly-individual first, then unspecified, then
  // organisation-only last. Stable, so ranking/relevance is preserved within tier.
  if(!ot && state.sort!=='deadline' && state.sort!=='funding') r=r.slice().sort((a,b)=>indTier(a)-indTier(b));
  state.filtered=r; render();
}
function globalPrior(g){return typeof g._rank_score==='number'?g._rank_score:.6;}
function fundingUsd(g){const a=g.funding_amount_max||g.funding_amount_min;return a?Number(a)*(FX[(g.currency||'USD').toUpperCase()]||1):-1;}
function deadlineKey(g){if(!g.application_deadline)return 8.64e15;const t=Date.parse(g.application_deadline+'T00:00:00');return isNaN(t)?8.64e15:t;}
function stageMatch(g,stage){const ot=(g.organisation_types||[]).join(' ').toLowerCase();
  if(stage==='nonprofit')return /non.?profit|ngo|charit|civil society|foundation|community/.test(ot)?1:.45;
  if(stage==='industry'){const h=ot+' '+(g.grant_types||[]).join(' ').toLowerCase();return /sme|business|compan|startup|start-up|industr|for.?profit|enterprise|innovation|commerc/.test(h)?1:.4;}
  const hay=[...(g.grant_types||[]),...(g.individual_eligibility||[]),...(g.organisation_types||[]),g.grant_title||''].join(' ').toLowerCase();
  const hits=(STAGE_KW[stage]||[]).filter(k=>hay.includes(k)).length;return hits>=2?1:hits===1?.75:.45;}
function affinityBoost(g,a){if(!hasAffinity(a))return .4;const sw=a.sectors||{},fw=a.funders||{};const ss=Object.values(sw).reduce((x,y)=>x+y,0)||1;let s=0;(g.thematic_sectors||[]).forEach(x=>{if(sw[x])s+=sw[x]/ss;});s=Math.min(1,s);const fs=Object.values(fw).reduce((x,y)=>x+y,0)||1;const f=g.funder_name&&fw[g.funder_name]?Math.min(1,fw[g.funder_name]/fs):0;return Math.max(.3,.7*s+.3*f);}
function personalMatch(g,p,a){const pp=hasProfile(p),ap=hasAffinity(a);if(!pp&&!ap)return null;let pm=null;
  if(pp){let fs=.5;if(p.fields&&p.fields.length){const hit=(g.thematic_sectors||[]).filter(s=>p.fields.includes(s)).length;fs=hit>0?Math.min(1,.65+.18*hit):.2;}
    let rs=.5;if(p.region&&p.region!=='any'){const regs=[...(g.applicant_base_regions||[]),...(g.geographic_focus_regions||[])];rs=regs.includes(p.region)?1:(!regs.length||regs.includes('Global')?.6:.25);}
    const ss=p.stage?stageMatch(g,p.stage):.5;pm=.42*fs+.3*ss+.28*rs;}
  const ab=affinityBoost(g,a);if(pp&&ap)return .8*pm+.2*ab;if(pp)return pm;return ab;}
function order(list){const arr=list.slice();
  if(state.sort==='deadline'){arr.forEach(g=>g._forYou=false);return arr.sort((a,b)=>deadlineKey(a)-deadlineKey(b));}
  if(state.sort==='funding'){arr.forEach(g=>g._forYou=false);return arr.sort((a,b)=>fundingUsd(b)-fundingUsd(a));}
  if(state.sort==='toprated'){arr.forEach(g=>g._forYou=false);return arr.sort((a,b)=>globalPrior(b)-globalPrior(a));}
  const personalised=hasProfile(state.profile)||hasAffinity(state.affinity);
  arr.forEach(g=>{const pm=personalMatch(g,state.profile,state.affinity);if(pm==null){g._score=globalPrior(g);g._forYou=false;}else{g._score=.45*globalPrior(g)+.55*pm;g._forYou=personalised&&pm>=.78;}});
  return arr.sort((a,b)=>b._score-a._score);}

/* ---------- format helpers ---------- */
function fmtDate(iso){if(!iso)return null;const d=new Date(String(iso).slice(0,10)+'T00:00:00');return isNaN(d)?null:d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});}
function deadlineText(g){if(g.application_deadline_raw&&/rolling/i.test(g.application_deadline_raw))return 'Rolling';if(g.application_deadline){const f=fmtDate(g.application_deadline);return f?'Closes '+f:'Deadline TBC';}if(g.current_status==='Rolling')return 'Rolling';return 'Deadline TBC';}
function sym(c){return c==='GBP'?'£':c==='EUR'?'€':c==='USD'?'$':(c?c+' ':'');}
function abbr(n){n=Number(n);if(n>=1e9)return (n/1e9).toFixed(n>=1e10?0:1).replace(/\.0$/,'')+'B';if(n>=1e6)return (n/1e6).toFixed(n>=1e7?0:1).replace(/\.0$/,'')+'M';if(n>=1e3)return Math.round(n/1e3)+'K';return Math.round(n).toLocaleString();}
function amountShort(g){const mx=g.funding_amount_max||g.funding_amount_min;return mx?sym(g.currency)+abbr(mx):'—';}
function amountFull(g){const s=sym(g.currency),lo=g.funding_amount_min,hi=g.funding_amount_max;if(lo&&hi&&lo!==hi)return s+Number(lo).toLocaleString('en-GB')+' – '+s+Number(hi).toLocaleString('en-GB');if(hi)return 'Up to '+s+Number(hi).toLocaleString('en-GB');if(lo)return 'From '+s+Number(lo).toLocaleString('en-GB');return 'Not specified by funder';}
function esc(v){return v==null?'':String(v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}

/* ---------- render ---------- */
function syncViewButtons(){document.querySelectorAll('#viewtoggle button').forEach(x=>x.classList.toggle('on',x.dataset.view===state.view));}
function viewMode(){let v=state.view;if(window.matchMedia('(max-width:768px)').matches&&(v==='table'||v==='grouped'))v='grid';return v;}
function render(){
  const grid=$('#grid');const total=state.filtered.length;const v=viewMode();
  $('#count').textContent=total?(total.toLocaleString()+' opportunit'+(total===1?'y':'ies')):'No grants match your search';
  grid.className='grid'+(v==='list'?' list':v==='table'?' table':v==='grouped'?' grouped':'');
  grid.innerHTML='';$('#showmore').style.display='none';
  if(!total){const e=el('div','empty');e.textContent='No grants match — try clearing a filter.';grid.appendChild(e);return;}
  if(v==='table'){renderTable(grid,total);return;}
  if(v==='grouped'){renderGrouped(grid);return;}
  const frag=document.createDocumentFragment();
  state.filtered.slice(0,state.shown).forEach(g=>frag.appendChild(card(g)));
  grid.appendChild(frag);
  if(state.shown<total){const sm=$('#showmore');sm.style.display='block';sm.textContent='Show more · '+(total-state.shown).toLocaleString()+' remaining';}
}
function renderTable(grid,total){
  const t=el('table','gtable');
  t.innerHTML='<thead><tr><th>Status</th><th>Opportunity</th><th>Funder</th><th>Sector</th><th>Deadline</th><th class="r">Amount</th></tr></thead>';
  const tb=el('tbody');
  state.filtered.slice(0,state.shown).forEach(g=>{
    const tr=el('tr');
    tr.innerHTML=`<td><span class="status ${statusClass(g.current_status)}">${esc(g.current_status||'')}</span></td>`+
      `<td class="ttl">${esc(g.grant_title)}</td><td class="fn">${esc(g.funder_name)}</td>`+
      `<td class="sec">${esc((g.thematic_sectors||['—'])[0])}</td>`+
      `<td>${esc(deadlineText(g).replace('Closes ',''))}</td><td class="r amt">${esc(amountShort(g))}</td>`;
    tr.addEventListener('click',()=>openModal(g));tb.appendChild(tr);
  });
  t.appendChild(tb);grid.appendChild(t);
  if(state.shown<total){const sm=$('#showmore');sm.style.display='block';sm.textContent='Show more · '+(total-state.shown).toLocaleString()+' remaining';}
}
function renderGrouped(grid){
  const groups={};
  state.filtered.forEach(g=>{const r=((g.geographic_focus_regions&&g.geographic_focus_regions[0])||(g.applicant_base_regions&&g.applicant_base_regions[0])||'Other');(groups[r]=groups[r]||[]).push(g);});
  Object.entries(groups).sort((a,b)=>b[1].length-a[1].length).forEach(([region,arr])=>{
    const sec=el('div','gsection');
    sec.innerHTML=`<div class="ghead"><span class="gname">${esc(region)}</span><span class="gcount">${arr.length.toLocaleString()} opportunit${arr.length===1?'y':'ies'}</span></div>`;
    const row=el('div','grow');
    arr.slice(0,6).forEach(g=>row.appendChild(card(g)));
    sec.appendChild(row);
    if(arr.length>6){const b=el('button','gmore');b.textContent='View all '+arr.length.toLocaleString()+' in '+region+' →';
      b.addEventListener('click',()=>{$('#f-region').value=region;state.view='grid';try{localStorage.setItem('gg_view','grid')}catch(e){}syncViewButtons();state.shown=BATCH;applyAll();window.scrollTo({top:0,behavior:'smooth'});});sec.appendChild(b);}
    grid.appendChild(sec);
  });
}
function statusClass(s){return (s||'').toLowerCase().replace(/\s+/g,'-');}
function card(g){
  const c=el('div','card');c.dataset.id=g.id;
  const lead=g._forYou?'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/></svg><span class="pt">For you</span>':'<span class="pt">'+esc((g.thematic_sectors||['Research'])[0])+'</span>';
  c.innerHTML=`<div class="row"><span class="pill">${lead}</span><span class="status ${statusClass(g.current_status)}">${esc(g.current_status||'')}</span></div>
    <h3>${esc(g.grant_title)}</h3><div class="funder">${esc(g.funder_name)}</div>
    <div class="meta"><span>${esc(deadlineText(g))}</span><span class="amount">${esc(amountShort(g))}</span></div>`;
  c.addEventListener('click',()=>openModal(g));
  c.addEventListener('pointermove',e=>{if(state.view!=='grid')return;const r=c.getBoundingClientRect();const px=(e.clientX-r.left)/r.width-.5,py=(e.clientY-r.top)/r.height-.5;
    c.style.transform=`translateY(-8px) perspective(1100px) rotateX(${(-py*5).toFixed(2)}deg) rotateY(${(px*5).toFixed(2)}deg)`;});
  c.addEventListener('pointerleave',()=>{c.style.transform='';});
  return c;
}
function tagList(arr){return (arr&&arr.length?arr:['Not specified']).map(t=>`<span class="pill">${esc(t)}</span>`).join('');}
function openModal(g){
  recordAffinity(g);
  const geo=[...(g.geographic_focus_regions||[]),...(g.geographic_focus_countries||[]),...(g.applicant_base_regions||[])];
  const elig=[...(g.organisation_types||[]),...(g.individual_eligibility||[])];
  const url=g.application_portal_url||g.source_url;
  const lv=fmtDate(g.last_verified);
  $('#sheet-body').innerHTML=`
    <div class="top"><div><h2>${esc(g.grant_title)}</h2><p class="funder">${esc(g.funder_name)}</p></div>
      <button class="close" id="mClose" aria-label="Close">✕</button></div>
    <div class="tags"><span class="pill">${esc(g.current_status||'')}</span><span class="pill">${esc(deadlineText(g))}</span><span class="pill">${esc(amountFull(g))}</span></div>
    <div class="seclabel">About</div><p class="desc">${esc(g.description||'No description provided by the funder.')}</p>
    <div class="seclabel">Eligibility</div><div class="tags">${tagList([...new Set(elig)])}</div>
    <div class="seclabel">Geographic focus</div><div class="tags">${tagList([...new Set(geo)])}</div>
    <div class="seclabel">Thematic sectors</div><div class="tags">${tagList(g.thematic_sectors)}</div>
    ${lv?`<div class="verified"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 12l4 4L19 6"/></svg>Verified against funder · ${esc(lv)}</div>`:''}
    ${url?`<a class="apply" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Apply / view grant <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M7 17 17 7M9 7h8v8"/></svg></a>`:''}`;
  $('#mClose').addEventListener('click',closeModal);
  $('#overlay').classList.add('show');
}
function closeModal(){$('#overlay').classList.remove('show');}
function recordAffinity(g){const a=state.affinity||{sectors:{},funders:{}};a.sectors=a.sectors||{};a.funders=a.funders||{};
  (g.thematic_sectors||[]).slice(0,4).forEach(s=>{if(s)a.sectors[s]=(a.sectors[s]||0)+1;});
  if(g.funder_name)a.funders[g.funder_name]=(a.funders[g.funder_name]||0)+1;
  state.affinity=a;try{localStorage.setItem(LS_AFFINITY,JSON.stringify(a))}catch(e){}}
