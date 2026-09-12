// Theme explorer shares only formatters and paper-index readers with the map.
// No classification is done in the browser; frozen server tags drive the UI.
const TS={active:false,basis:'title',facet:'all',query:'',sort:'momentum',all:false,
  selected:null,intersection:'',range:60,scale:'auto',metric:'count',partial:false,
  papers:[],records:[],search:'',field:'all',limit:25,request:0,hoverIndex:null};
const themeFiles=new Map();
const themeData=()=>D.themes;
const themeBasis=()=>themeData()?.basis[TS.basis];
const definition=id=>themeData()?.definitions.find(t=>t.id===id);
const ratio=(a,b)=>b?a/b:null;
const number1=n=>Number.isFinite(n)?n.toLocaleString('en-US',{maximumFractionDigits:1,minimumFractionDigits:1}):'\u2014';
function themeStats(id,i=state.month){
  const b=themeBasis(),all=themeData().totals[i],e=b.eligible[i],n=id==='unmatched'?b.unmatched[i]:b.hits[id][i];
  return {n:e?n:null,eligible:e,total:all,coverage:ratio(e,all),rate:e?n/e*100:null};
}
function themeMomentum(id){
  const end=Math.min(state.month,D.latestCompleteMonthIndex),b=themeBasis(),policy=themeData().policy;
  if(end<5)return {value:null,reason:'\u5c65\u6b74\u4e0d\u8db3'};
  const earlier=[end-5,end-4,end-3],later=[end-2,end-1,end];
  const series=id==='unmatched'?b.unmatched:b.hits[id];
  const agg=idx=>({n:idx.reduce((s,i)=>s+series[i],0),e:idx.reduce((s,i)=>s+b.eligible[i],0),all:idx.reduce((s,i)=>s+themeData().totals[i],0)});
  const a=agg(earlier),c=agg(later),coverageOk=[...earlier,...later].every(i=>themeData().totals[i]>0&&b.eligible[i]/themeData().totals[i]>=policy.minMonthlyCoverage);
  const period=monthText(D.monthStarts[end-2])+'\u2013'+monthText(D.monthStarts[end])+' vs '+monthText(D.monthStarts[end-5])+'\u2013'+monthText(D.monthStarts[end-3]);
  if(!coverageOk||Math.abs(a.e/a.all-c.e/c.all)>policy.maxCoverageDrift)return {value:null,reason:'\u5224\u5b9a\u7387\u4e0d\u8db3',period};
  if(a.n<policy.minPeriodHits||c.n<policy.minPeriodHits)return {value:null,reason:a.n===0&&c.n>=5?'\u65b0\u8208\u5019\u88dc':'\u5c11\u6570',period,previous:a.n,current:c.n};
  return {value:(c.n/c.e-a.n/a.e)*100,previous:a.n,current:c.n,period};
}
function changePoints(v){return Number.isFinite(v)?(v>0?'+':v<0?'\u2212':'')+Math.abs(v).toFixed(2)+' pp':'\u2014';}
function themeValues(id,metric='count'){
  const b=themeBasis(),raw=id==='unmatched'?b.unmatched:b.hits[id];
  return raw.map((n,i)=>b.eligible[i]>0&&b.eligible[i]/themeData().totals[i]>=themeData().policy.minMonthlyCoverage?(metric==='rate'?n/b.eligible[i]*100:n):null);
}
function segments(points){const out=[];let cur=[];for(const p of points){if(p!==null)cur.push(p);else if(cur.length){out.push(cur);cur=[];}}if(cur.length)out.push(cur);return out;}
function sparkline(id){
  const a=themeValues(id).slice(Math.max(0,D.currentMonthIndex-36),D.currentMonthIndex),valid=a.filter(Number.isFinite);
  if(!valid.length)return '<span class="theme-spark-empty">\u5224\u5b9a\u7387 90% \u4ee5\u4e0a\u306e\u6708\u304b\u3089\u8868\u793a</span>';
  const lo=Math.min(...valid),hi=Math.max(...valid),span=Math.max(1,hi-lo),p=a.map((v,i)=>Number.isFinite(v)?[i/Math.max(1,a.length-1)*240,42-(v-lo)/span*31]:null);
  return `<svg viewBox="0 0 240 48" preserveAspectRatio="none" aria-hidden="true">${segments(p).map(s=>`<path d="${s.map((v,j)=>(j?'L':'M')+v.join(',')).join(' ')}"/>${s.length===1?`<circle cx="${s[0][0]}" cy="${s[0][1]}" r="2"/>`:''}`).join('')}</svg>`;
}
function renderThemes(){
  const available=state.group==='cond-mat';$('#lens-bar').hidden=!available;
  if(!available)TS.active=false;
  document.body.classList.toggle('theme-mode',TS.active);
  $('#themes-panel').hidden=!TS.active;
  $('#lens-areas').classList.toggle('active',!TS.active);$('#lens-areas').setAttribute('aria-pressed',String(!TS.active));
  $('#lens-themes').classList.toggle('active',TS.active);$('#lens-themes').setAttribute('aria-pressed',String(TS.active));
  if(!TS.active)return;
  if(!themeData()){$('#themes-panel').innerHTML='<div class="theme-empty"><h2>Theme index not built yet.</h2><p>\u66f4\u65b0\u5f8c\u306e\u521d\u56de\u516c\u958b\u51e6\u7406\u3067\u3001\u4fdd\u5b58\u6e08\u307f\u60c5\u5831\u3092\u5206\u985e\u3057\u307e\u3059\u3002\u518d\u53d6\u5f97\u306f\u884c\u3044\u307e\u305b\u3093\u3002</p></div>';return;}
  const b=themeBasis(),i=state.month,e=b.eligible[i],all=themeData().totals[i],u=b.unmatched[i],cv=all?e/all*100:null;
  $('#themes-panel').innerHTML=`<div class="theme-toolbar"><div><span class="eyebrow">BEYOND THE CATEGORIES</span><h2>Research themes<span class="theme-count">${themeData().definitions.length}</span></h2></div><label class="theme-basis-label"><span>\u5224\u5b9a\u5165\u529b</span><select id="theme-basis" aria-label="Theme input"><option value="title">\u30bf\u30a4\u30c8\u30eb</option><option value="title_abstract">\u30bf\u30a4\u30c8\u30eb\uff0b\u8981\u65e8</option></select></label></div>
    <div class="theme-metrics"><div><span>CONDENSED MATTER${currentPartial()?' / \u901f\u5831':''}</span><strong>${fmt(all)}<small>papers</small></strong></div><div><span>\u5224\u5b9a\u53ef\u80fd</span><strong>${number1(cv)}<small>%</small></strong><span>${fmt(e)} / ${fmt(all)}</span></div><button id="theme-unmatched" title="Evaluated papers with no dictionary match"><span>\u8f9e\u66f8\u306b\u4e00\u81f4\u306a\u3057</span><strong>${e?fmt(u):'\u2014'}<small>papers \u2197</small></strong></button></div>
    <div class="theme-controls"><div class="theme-facets" role="group" aria-label="Theme facet"><button data-facet="all">\u3059\u3079\u3066</button>${themeData().facets.map(f=>`<button data-facet="${esc(f.id)}">${esc(f.name)}</button>`).join('')}</div><div class="theme-filter-tools"><input type="search" id="theme-search" placeholder="\u30c6\u30fc\u30de\u3092\u691c\u7d22" aria-label="Search themes"><select id="theme-sort" aria-label="Theme order"><option value="momentum">3M \u51fa\u73fe\u7387\u5dee</option><option value="count">\u691c\u51fa\u6570</option><option value="name">A\u2013Z</option></select></div></div>
    <div class="theme-context"><span id="theme-context-text">${cv!==null&&cv<90?'\u5224\u5b9a\u7387\u304c\u4f4e\u3044\u305f\u3081\u3001\u63a8\u79fb\u30fb\u5897\u6e1b\u306e\u5f37\u8abf\u3092\u5236\u9650':'\u51fa\u73fe\u7387\uff1d\u5224\u5b9a\u5bfe\u8c61\u5185\u306e\u5272\u5408'} \u00b7 \u30bf\u30b0\u306f\u91cd\u8907\u3042\u308a</span><button data-action="method">${esc(themeData().ruleVersion)} \u24d8</button></div>
    <div class="theme-cards" id="theme-cards"></div><button class="theme-show-all" id="theme-show-all"></button>`;
  $('#theme-basis').value=TS.basis;$('#theme-sort').value=TS.sort;$('#theme-search').value=TS.query;
  $('#theme-basis').onchange=e=>{TS.basis=e.target.value;themeFiles.clear();renderThemes();};
  $('#theme-sort').onchange=e=>{TS.sort=e.target.value;renderThemeCards();};
  $('#theme-search').oninput=e=>{TS.query=e.target.value;renderThemeCards();};
  $$('[data-facet]',$('#themes-panel')).forEach(b=>b.onclick=()=>{TS.facet=b.dataset.facet;TS.all=false;renderThemeCards();});
  $('#theme-show-all').onclick=()=>{TS.all=!TS.all;renderThemeCards();};
  $('#theme-unmatched').onclick=()=>openTheme('unmatched');
  renderThemeCards();
  if($('#theme-dialog').open&&TS.selected)openTheme(TS.selected,false);
}
function renderThemeCards(){
  let defs=themeData().definitions.filter(t=>(TS.facet==='all'||t.facet===TS.facet)&&(!TS.query||[t.name,t.ja,...t.aliases].some(v=>normalizeSearch(v).includes(normalizeSearch(TS.query)))));
  defs.sort((a,b)=>TS.sort==='name'?a.name.localeCompare(b.name):TS.sort==='count'?(themeStats(b.id).n??-1)-(themeStats(a.id).n??-1):((themeMomentum(b.id).value??-Infinity)-(themeMomentum(a.id).value??-Infinity)||((themeStats(b.id).n??-1)-(themeStats(a.id).n??-1))));
  $$('[data-facet]').forEach(b=>{b.classList.toggle('selected',b.dataset.facet===TS.facet);b.setAttribute('aria-pressed',String(b.dataset.facet===TS.facet));});
  $('#theme-show-all').hidden=defs.length<=12;$('#theme-show-all').textContent=TS.all?'\u6298\u308a\u305f\u305f\u3080':'\u3059\u3079\u3066\u8868\u793a ('+defs.length+')';
  $('#theme-cards').innerHTML=(TS.all?defs:defs.slice(0,12)).map(t=>{const s=themeStats(t.id),m=themeMomentum(t.id),facet=themeData().facets.find(f=>f.id===t.facet).name;
    return `<button class="theme-card" data-theme="${esc(t.id)}"><div class="theme-card-top"><span>${esc(facet)}${t.parent?' / '+esc(definition(t.parent).name):''}</span><span class="${Number.isFinite(m.value)?deltaClass(m.value):'theme-muted'}" title="${esc(m.period||'')}">${Number.isFinite(m.value)?changePoints(m.value):esc(m.reason)}</span></div><h3>${esc(t.name)}</h3><p>${esc(t.ja)}</p><div class="theme-card-value"><strong>${fmt(s.n)}</strong><span>\u691c\u51fa / ${number1(s.rate)}%</span></div><div class="theme-spark">${sparkline(t.id)}</div><span class="theme-card-arrow">\u2197</span></button>`;
  }).join('')||'<div class="theme-empty">\u4e00\u81f4\u3059\u308b\u30c6\u30fc\u30de\u306f\u3042\u308a\u307e\u305b\u3093</div>';
  $$('[data-theme]').forEach(b=>b.onclick=()=>openTheme(b.dataset.theme));
}
async function themeDemoRecords(){
  if(D.mode!=='demo'||!D.themeDemoPacked)return null;
  const encoded=D.themeDemoPacked[D.monthStarts[state.month]];
  if(!encoded)return [];
  const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
  const rows=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).json();
  return rows.map(r=>{const t=D.themeDemoTemplates[r[3]],basis={title:t.basis.title};if(r[4])basis.title_abstract=t.basis.title_abstract;
    return {id:r[0],category:r[1],basis,paper:{id:r[0],created:r[2],title:t.title,authors:'A. Sample; B. Example',abstract:r[4]&&r[5]?t.abstract:null}};});
}
async function loadThemeRecords(){
  const demo=await themeDemoRecords();if(demo)return demo;
  if(!D.paperIndexEnabled)throw Error('\u8ad6\u6587\u4e00\u89a7\u306f\u7121\u52b9\u306e\u8a2d\u5b9a\u3067\u3059\u3002');
  const month=D.monthStarts[state.month],path=themeData().files[month],key=themeData().ruleKey+':'+D.asOf+':'+month;
  if(!themeFiles.has(key)){
    if(typeof path!=='string'||!/^data\/themes\/\d{4}-\d{2}-01-[a-f0-9]{12}\.json\.gz$/.test(path))throw Error('Theme index missing.');
    const response=await fetch(path,{cache:'no-cache'});if(!response.ok)throw Error('\u30c6\u30fc\u30de\u4e00\u89a7\u3092\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093\u3002\u518d\u8aad\u8fbc\u3057\u3066\u304f\u3060\u3055\u3044\u3002');
    const bytes=new Uint8Array(await response.arrayBuffer());
    const data=bytes[0]===31&&bytes[1]===139?await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).json():JSON.parse(new TextDecoder().decode(bytes));
    if(data.month!==month||data.ruleKey!==themeData().ruleKey||data.schemaVersion!==1||!Array.isArray(data.records))throw Error('Theme index version mismatch.');
    const seen=new Set(),ids=new Set(themeData().definitions.map(t=>t.id));
    for(const r of data.records){if(!validId(r.id)||seen.has(r.id)||catOf(r.category)?.group!=='cond-mat'||!r.basis)throw Error('Invalid theme record.');seen.add(r.id);for(const [basis,hits] of Object.entries(r.basis)){if(!['title','title_abstract'].includes(basis)||Object.keys(hits).some(t=>!ids.has(t)))throw Error('Invalid theme membership.');}}
    if(themeFiles.size>=3)themeFiles.delete(themeFiles.keys().next().value);themeFiles.set(key,data.records);
  }
  return themeFiles.get(key);
}
function isThemeHit(row,id){const h=row.basis[TS.basis];return !!h&&(id==='unmatched'?Object.keys(h).length===0:Object.hasOwn(h,id));}
async function openTheme(id,reset=true){
  TS.selected=id;TS.hoverIndex=null;if(reset){TS.intersection='';TS.search='';TS.limit=25;TS.field='all';}
  const t=id==='unmatched'?{id,name:'No dictionary match',ja:'\u8f9e\u66f8\u306b\u4e00\u81f4\u306a\u3057',aliases:[]}:definition(id);if(!t)return;
  const s=themeStats(id),m=themeMomentum(id),dialog=$('#theme-dialog');TS.records=[];TS.papers=[];
  $('#theme-dialog-body').innerHTML=`<div class="theme-dialog-head"><div><span class="eyebrow">CONDENSED MATTER / ${esc(themeData().ruleVersion)}</span><h2 id="theme-dialog-title">${esc(t.name)}</h2><p>${esc(t.ja)} \u00b7 ${TS.basis==='title'?'\u30bf\u30a4\u30c8\u30eb':'\u30bf\u30a4\u30c8\u30eb\uff0b\u8981\u65e8'}</p></div><button class="icon-btn" id="theme-close" aria-label="Close theme">\u00d7</button></div>
    <div class="theme-detail-metrics"><div><span>${monthText(D.monthStarts[state.month])}${currentPartial()?' / \u901f\u5831':''}</span><strong>${fmt(s.n)}<small>\u691c\u51fa</small></strong></div><div><span>\u5224\u5b9a\u5bfe\u8c61\u5185</span><strong>${number1(s.rate)}<small>%</small></strong></div><div><span title="${esc(m.period||'')}">3M \u51fa\u73fe\u7387\u5dee</span><strong class="${Number.isFinite(m.value)?deltaClass(m.value):'theme-muted'}">${Number.isFinite(m.value)?changePoints(m.value):'\u2014'}</strong></div></div>
    <div class="theme-detail-controls"><div class="segmented"><button data-tmetric="count">\u691c\u51fa\u6570</button><button data-tmetric="rate">\u51fa\u73fe\u7387</button></div><div class="segmented"><button data-trange="12">1Y</button><button data-trange="36">3Y</button><button data-trange="60">5Y</button></div><div class="segmented"><button data-tscale="auto">AUTO</button><button data-tscale="zero">0</button></div><button id="theme-partial" class="provisional-switch">\u901f\u5831</button></div>
    <div id="theme-detail-chart" class="theme-detail-chart"></div><div class="theme-chart-foot"><span id="theme-chart-quote"></span><span>\u5224\u5b9a\u7387 ${number1(s.coverage===null?null:s.coverage*100)}%</span></div>
    <details class="theme-rule-details"><summary>\u5224\u5b9a\u8a9e\u30fb\u6bd4\u8f03\u671f\u9593</summary><p>${esc(t.aliases.join(', ')||'\u5224\u5b9a\u5165\u529b\u306f\u3042\u308b\u304c\u8f9e\u66f8\u8a9e\u306b\u4e00\u81f4\u3057\u306a\u3044\u8ad6\u6587\u3002\u5206\u985e\u4e0d\u80fd\u306a\u8ad6\u6587\u3068\u306f\u5225\u3067\u3059\u3002')}</p><p>${esc(m.period||m.reason)}${m.reason?' / '+esc(m.reason):''}</p><p>\u691c\u51fa\u6570\u306f\u8a00\u53ca\u8a9e\u306e\u4e00\u81f4\u3002\u8ad6\u6587\u306e\u4e3b\u984c\u306e\u78ba\u5b9a\u3067\u306f\u3042\u308a\u307e\u305b\u3093\u3002\u5224\u5b9a\u738790%\u672a\u6e80\u306e\u6708\u306f\u7dda\u3092\u3064\u306a\u304e\u307e\u305b\u3093\u3002\u51fa\u73fe\u7387\u306e\u5206\u6bcd\u306f\u9078\u629e\u3057\u305f\u5165\u529b\u306e\u3042\u308b\u8ad6\u6587\u3067\u3059\u3002</p>${t.source?`<a href="${esc(t.source)}" target="_blank" rel="noopener noreferrer">\u53c2\u8003\u6982\u5ff5 \u2197</a>`:''}</details>
    <div class="theme-paper-toolbar"><h3>Matching papers <span id="theme-paper-count"></span></h3><select id="theme-intersection" aria-label="Intersect with another theme"><option value="">\u7d5e\u308a\u8fbc\u307f\u306a\u3057</option>${id==='unmatched'?'':themeData().definitions.filter(x=>x.id!==id).map(x=>`<option value="${esc(x.id)}">\u2229 ${esc(x.name)}</option>`).join('')}</select></div><p class="theme-filter-note" id="theme-filter-note" hidden>\u4e0a\u306e\u63a8\u79fb\u306f\u5358\u4e00\u30c6\u30fc\u30de\u3002\u4ee5\u4e0b\u306e\u8ad6\u6587\u4e00\u89a7\u3060\u3051\u3092\u7d5e\u308a\u8fbc\u3093\u3067\u3044\u307e\u3059\u3002</p>
    <div class="theme-paper-search"><input id="theme-paper-query" type="search" placeholder="\u30bf\u30a4\u30c8\u30eb\u30fb\u8457\u8005\u30fb\u4fdd\u5b58\u6e08\u307f\u8981\u65e8" aria-label="Search theme papers"><select id="theme-paper-field" aria-label="Theme paper search field"><option value="all">\u3059\u3079\u3066</option><option value="title">\u30bf\u30a4\u30c8\u30eb</option><option value="authors">\u8457\u8005</option><option value="abstract">\u8981\u65e8</option><option value="id">ID</option></select></div>
    <div id="theme-papers" aria-live="polite"><p class="theme-loading">Loading papers\u2026</p></div><button id="theme-more" class="load-more" hidden>\u3055\u3089\u306b\u8868\u793a</button>`;
  $('#theme-close').onclick=()=>dialog.close();
  if(!dialog.open)dialog.showModal();
  $$('[data-trange]',dialog).forEach(b=>b.onclick=()=>{TS.range=+b.dataset.trange;renderThemeChart();});
  $$('[data-tscale]',dialog).forEach(b=>b.onclick=()=>{TS.scale=b.dataset.tscale;renderThemeChart();});
  $$('[data-tmetric]',dialog).forEach(b=>b.onclick=()=>{TS.metric=b.dataset.tmetric;renderThemeChart();});
  $('#theme-partial').onclick=()=>{TS.partial=!TS.partial;renderThemeChart();};
  $('#theme-paper-query').value=TS.search;$('#theme-intersection').value=TS.intersection;$('#theme-paper-field').value=TS.field;
  $('#theme-paper-query').oninput=e=>{TS.search=e.target.value;TS.limit=25;renderThemePapers();};
  $('#theme-intersection').onchange=e=>{TS.intersection=e.target.value;TS.limit=25;renderThemePapers();};
  $('#theme-paper-field').onchange=e=>{TS.field=e.target.value;TS.limit=25;renderThemePapers();};
  $('#theme-more').onclick=()=>{TS.limit+=25;renderThemePapers();};
  renderThemeChart();
  const ticket=++TS.request,mi=state.month;
  try{
    const records=await loadThemeRecords();if(ticket!==TS.request)return;
    const selected=records.filter(r=>isThemeHit(r,id));
    if(selected.length!==(s.n??0))throw Error('Theme count/index mismatch.');
    let papers;
    if(D.mode==='demo')papers=selected.map(r=>({...r.paper,id:r.id,category:r.category,themeRecord:r}));
    else{
      const cats=[...new Set(selected.map(r=>r.category))],lookup=new Map();
      // Sequential requests avoid a burst when a theme spans many categories.
      for(const cat of cats){const rows=await loadPapers(catOf(cat),mi);if(ticket!==TS.request)return;rows.forEach(p=>lookup.set(p.id,{...p,category:cat}));}
      papers=selected.map(r=>{const p=lookup.get(r.id);if(!p)throw Error('Theme paper missing from category index.');return {...p,themeRecord:r};});
    }
    if(ticket!==TS.request)return;TS.records=selected;TS.papers=papers.sort((a,b)=>b.created-a.created||b.id.localeCompare(a.id));renderThemePapers();
  }catch(e){if(ticket===TS.request){$('#theme-papers').innerHTML=`<div class="theme-empty">${esc(e.message)}</div>`;$('#theme-paper-count').textContent='';}}
}
function renderThemePapers(){
  const terms=searchTerms(TS.search),rows=TS.papers.filter(p=>(!TS.intersection||isThemeHit(p.themeRecord,TS.intersection))&&queryMatches(p,terms,TS.field));
  $('#theme-paper-count').textContent=fmt(rows.length)+' / '+fmt(TS.papers.length);
  $('#theme-filter-note').hidden=!TS.intersection&&!TS.search;
  $('#theme-more').hidden=rows.length<=TS.limit;
  $('#theme-papers').innerHTML=rows.slice(0,TS.limit).map(p=>{
    const hits=p.themeRecord.basis[TS.basis],evidence=hits[TS.selected]||[],a=p.abstract;
    return `<article class="paper-item theme-paper-item"><div class="paper-meta"><span>${esc(p.category)}</span><span>${dateText(new Date(p.created*1000).toISOString())}</span></div><h4>${D.mode==='demo'?esc(p.title||p.id):`<a href="https://arxiv.org/abs/${encodeURI(p.id)}" target="_blank" rel="noopener noreferrer">${highlight(p.title||p.id,terms)} \u2197</a>`}</h4>${authorsHTML(p,terms)}<div class="theme-paper-tags">${Object.keys(hits).map(t=>`<span>${esc(definition(t).name)}</span>`).join('')}</div>${evidence.length?`<p class="theme-evidence">${esc([...new Set(evidence.map(e=>(e.field==='title'?'\u984c\u540d':'\u8981\u65e8')+': '+e.phrase))].join(' / '))}</p>`:''}${a?`<details class="theme-abstract"><summary>Abstract</summary><p>${highlight(a,terms)}</p></details>`:TS.basis==='title_abstract'?'<p class="theme-evidence">\u8981\u65e8\u306f\u5224\u5b9a\u5f8c\u306b\u7834\u68c4\u3002\u4e00\u81f4\u8a9e\u3060\u3051\u3092\u4fdd\u5b58\u3002</p>':''}</article>`;
  }).join('')||'<div class="theme-empty">\u8a72\u5f53\u3059\u308b\u4fdd\u5b58\u6e08\u307f\u8ad6\u6587\u306f\u3042\u308a\u307e\u305b\u3093</div>';
}
function renderThemeChart(){
  const box=$('#theme-detail-chart');if(!box)return;
  const values=themeValues(TS.selected,TS.metric),end=TS.partial?values.length:D.currentMonthIndex,start=Math.max(0,end-TS.range),v=values.slice(start,end);
  const valid=v.filter(Number.isFinite),w=Math.max(300,box.clientWidth||640),h=250,l=10,r=60,top=24,bottom=210,pw=w-l-r;
  $$('[data-trange]').forEach(b=>b.classList.toggle('selected',+b.dataset.trange===TS.range));$$('[data-tscale]').forEach(b=>b.classList.toggle('selected',b.dataset.tscale===TS.scale));$$('[data-tmetric]').forEach(b=>b.classList.toggle('selected',b.dataset.tmetric===TS.metric));$('#theme-partial').setAttribute('aria-pressed',String(TS.partial));
  const avg=v.map((_,j)=>{const i=j+start;return i>=2&&i!==D.currentMonthIndex&&values.slice(i-2,i+1).every(Number.isFinite)?(values[i]+values[i-1]+values[i-2])/3:null;});
  const all=[...valid,...avg.filter(Number.isFinite)],low=valid.length?Math.min(...valid):0,high=valid.length?Math.max(...valid):1;
  let lo=0,hi=1;if(all.length){const a=Math.min(...all),b=Math.max(...all),pad=Math.max(TS.metric==='rate'?.2:1,(b-a)*.15,b*.02);lo=TS.scale==='zero'?0:Math.max(0,a-pad);hi=Math.max(lo+(TS.metric==='rate'?.5:1),b+pad);}
  const X=j=>l+j/Math.max(1,v.length-1)*pw,Y=n=>bottom-(n-lo)/(hi-lo)*(bottom-top),text=n=>TS.metric==='rate'?number1(n)+'%':fmt(Math.round(n));
  const pathFor=a=>segments(a.map((n,j)=>Number.isFinite(n)&&start+j!==D.currentMonthIndex?[X(j),Y(n)]:null)).map(seg=>`<path d="${seg.map((p,i)=>(i?'L':'M')+p.join(',')).join(' ')}"/>${seg.length===1?`<circle cx="${seg[0][0]}" cy="${seg[0][1]}" r="2.5"/>`:''}`).join('');
  const grid=Array.from({length:5},(_,i)=>lo+(hi-lo)*i/4).map(n=>`<line x1="${l}" x2="${w-r}" y1="${Y(n)}" y2="${Y(n)}"/><text x="${w-r+8}" y="${Y(n)+4}">${text(n)}</text>`).join('');
  const dates=[...new Set([0,Math.floor((v.length-1)/2),v.length-1])].filter(j=>j>=0).map(j=>`<text x="${X(j)}" y="235" text-anchor="${j===0?'start':j===v.length-1?'end':'middle'}">${monthText(D.monthStarts[j+start])}</text>`).join('');
  const partial=TS.partial&&v.length>1&&Number.isFinite(v.at(-1))&&Number.isFinite(v.at(-2))?`<path class="theme-partial-line" d="M${X(v.length-2)},${Y(v.at(-2))} L${X(v.length-1)},${Y(v.at(-1))}"/>`:'';
  box.innerHTML=`<svg viewBox="0 0 ${w} ${h}" tabindex="0" role="img" aria-label="Theme trend. Arrow keys and Enter select a month." data-y-min="${lo}" data-y-max="${hi}" data-valid-points="${valid.length}" data-gap-count="${v.length-valid.length}"><g class="theme-chart-grid">${grid}${dates}</g><g class="theme-chart-average">${pathFor(avg)}</g><g class="theme-chart-line">${pathFor(v)}</g>${partial}<line id="theme-crosshair" y1="${top}" y2="${bottom}"/><text class="theme-low-high" x="${l}" y="14">${valid.length?'LOW '+text(low)+' / HIGH '+text(high):'\u5224\u5b9a\u7387 90% \u4ee5\u4e0a\u306e\u6708\u304c\u3042\u308a\u307e\u305b\u3093'}</text><rect x="0" y="0" width="${w}" height="${h}" fill="transparent"/></svg>`;
  let pos=Math.max(0,Math.min(v.length-1,state.month-start));const svg=$('svg',box);
  const show=j=>{pos=j;const i=start+j,s=themeStats(TS.selected,i),n=TS.metric==='rate'?s.rate:s.n;$('#theme-chart-quote').textContent=monthText(D.monthStarts[i])+' / '+(Number.isFinite(n)?text(n):'\u672a\u5224\u5b9a')+' / \u5224\u5b9a\u7387 '+number1(s.coverage===null?null:s.coverage*100)+'%'+(i===D.currentMonthIndex?' / \u901f\u5831':'');const line=$('#theme-crosshair');line.setAttribute('x1',X(j));line.setAttribute('x2',X(j));};show(pos);
  svg.onpointermove=e=>{const rect=svg.getBoundingClientRect();show(Math.max(0,Math.min(v.length-1,Math.round(((e.clientX-rect.left)*w/rect.width-l)/pw*(v.length-1)))));};
  const select=()=>{state.month=start+pos;state.followCurrent=state.month===D.currentMonthIndex;setHash();render();};
  svg.onclick=select;svg.onkeydown=e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();show(Math.max(0,Math.min(v.length-1,pos+(e.key==='ArrowLeft'?-1:1))));}else if(e.key==='Enter'){e.preventDefault();select();}};
}
function bindThemes(){
  $('#lens-areas').onclick=()=>{TS.active=false;render();};$('#lens-themes').onclick=()=>{TS.active=true;render();};
  $('#theme-dialog').addEventListener('close',()=>{TS.request++;TS.selected=null;});
  $('#theme-dialog').addEventListener('click',e=>{if(e.target===$('#theme-dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
  window.addEventListener('resize',()=>{if($('#theme-dialog').open)renderThemeChart();});
  window.PulseThemes={openTheme,themeStats,themeMomentum,themeValues,getState:()=>TS,segments};
}
