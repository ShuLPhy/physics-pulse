
(() => {
"use strict";
const $ = (s, el=document) => el.querySelector(s);
const $$ = (s, el=document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (n) => Number.isFinite(n) ? n.toLocaleString("en-US") : "—";
const DAY = 86400000;
const dataSeed = JSON.parse($("#embedded-data").textContent);
let D = dataSeed;
let drawToken = 0;
let previousFocus = null;
let currentPapers = [];
let paperRequest = 0;
let toastTimer;
let chartSerial = 0;
let resizeTimer;
const paperCache = new Map();
const stored = (key, fallback) => {
  try { const v = localStorage.getItem("pulse."+key); return v === null ? fallback : JSON.parse(v); }
  catch { return fallback; }
};
const save = (key,v) => { try { localStorage.setItem("pulse."+key,JSON.stringify(v)); } catch {} };
const state = {
  group:"cond-mat", month:D.defaultMonthIndex, query:"", view:"map",
  palette:stored("palette",false), watch:new Set(stored("watch",[])),
  range:[12,36,60].includes(stored("chart-range",60))?stored("chart-range",60):60, scale:stored("chart-scale","auto")==="zero"?"zero":"auto", provisional:stored("chart-provisional",false)===true,
  drawer:null, followCurrent:true, interests:stored("interests",""), sort:"newest", paperQuery:"", paperField:"all", paperLimit:25
};
const dateOf = (s) => new Date(s.slice(0,10)+"T00:00:00Z");
const isoDay = d => d.toISOString().slice(0,10);
const dateText = s => s.slice(0,10).replaceAll("-",".");
const shortDate = s => s.slice(5,10).replace("-", "/");
const nextMonth=s=>{const d=dateOf(s);return new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1));};
const endDay=s=>isoDay(new Date(+nextMonth(s)-DAY));
const monthText=s=>s.slice(0,7).replace("-","/");
const monthTitle=s=>`${s.slice(0,4)}年${Number(s.slice(5,7))}月`;
const observationLabel=()=>monthText(D.asOf)===monthText(new Date().toISOString())?"今月":"最新収録月";
const groupOf = id => D.groups.find(g=>g.id===id);
const catOf = id => D.categories.find(c=>c.id===id);
const count = (c,w=state.month) => Number.isFinite(c?.counts?.[w]) ? c.counts[w] : null;
const reference = (c,w=state.month) => w===D.currentMonthIndex ? c.previousComparable : (w>0 ? count(c,w-1) : c.baselinePreviousCount);
const comparable=(c,w=state.month)=>w===D.currentMonthIndex?c.currentComparable:count(c,w);
const comparableTotal=cats=>cats.reduce((n,c)=>n+comparable(c),0);
const change = (n,p) => n===null || p===null || p===undefined ? null : (p===0 ? (n===0 ? 0 : Infinity) : (n-p)/p*100);
const deltaText = x => x===null ? "—" : x===Infinity ? "NEW" : (x>0 ? "+" : x<0 ? "−" : "")+Math.abs(x).toFixed(1)+"%";
const deltaClass = x => x===null || x===0 ? "neutral" : x>0 ? "positive" : "negative";
const deltaHTML = x => `<span class="delta ${deltaClass(x)}">${deltaText(x)}</span>`;
const total = (cats,w=state.month) => cats.reduce((a,c)=>a+(count(c,w)??0),0);
const previousTotal = cats => cats.some(c=>reference(c)===null||reference(c)===undefined) ? null : cats.reduce((a,c)=>a+reference(c),0);
const currentPartial = () => state.month===D.currentMonthIndex;
const contextCats = () => state.group==="all" ? D.categories : state.group==="watch" ? D.categories.filter(c=>state.watch.has(c.id)) : D.categories.filter(c=>c.group===state.group);
const visibleCats = () => {
  const q=state.query.trim().toLowerCase();
  return contextCats().filter(c=>!q || [c.id,c.name,c.shortName,c.ja].some(t=>String(t).toLowerCase().includes(q)));
};
const contextName = () => state.group==="all" ? "Physics overview" : state.group==="watch" ? "Your watchlist" : groupOf(state.group)?.name ?? "Physics";
const chartSeries = cats => {
  return {values:D.monthStarts.map((_,i)=>total(cats,i)),dates:D.monthStarts};
};
function toast(text) {
  clearTimeout(toastTimer); $("#toast").textContent=text; $("#toast").hidden=false;
  toastTimer=setTimeout(()=>$("#toast").hidden=true,3200);
}
function setHash() {
  try { const p=new URLSearchParams({field:state.group,month:D.monthStarts[state.month]}); history.replaceState(null,"","#"+p.toString()); } catch {}
}
function readHash() {
  const p=new URLSearchParams(location.hash.slice(1));
  if(p.has("field") && (["all","watch"].includes(p.get("field")) || groupOf(p.get("field")))) state.group=p.get("field");
  const i=D.monthStarts.indexOf(p.get("month")); if(i>=0){state.month=i;state.followCurrent=false;}
}
function setGroup(id) {
  state.group=id;state.query="";$("#category-search").value="";
  closeSidebar(); hideHover(); render();setHash();
}
function setMonth(index) {
  state.month=Math.max(0,Math.min(D.monthStarts.length-1,index));
  state.followCurrent=state.month===D.currentMonthIndex;
  hideHover();render();setHash();
  if(state.drawer) openDrawer(state.drawer,false);
}
function validateData(d) {
  if(d.schemaVersion!==3 || d.period!=="month" || !["demo","live"].includes(d.mode)) throw Error("Unsupported schema.");
  if(!Array.isArray(d.monthStarts)||d.monthStarts.length<2||d.monthStarts.length>120) throw Error("Invalid month range.");
  if(!Array.isArray(d.categories)||!Array.isArray(d.groups)) throw Error("Invalid categories.");
  if(!Number.isInteger(d.defaultMonthIndex)||d.defaultMonthIndex<0||d.defaultMonthIndex>=d.monthStarts.length) throw Error("Invalid selected month.");
  if(!Number.isInteger(d.currentMonthIndex)||d.currentMonthIndex<0||d.currentMonthIndex>=d.monthStarts.length) throw Error("Invalid current month.");
  if(!Number.isFinite(Date.parse(d.asOf))) throw Error("Invalid observation time.");
  let last = null;const ids=new Set();
  for(const w of d.monthStarts) {
    if(!/^\d{4}-\d{2}-\d{2}$/.test(w)||!Number.isFinite(+dateOf(w))||dateOf(w).getUTCDate()!==1) throw Error("Invalid calendar month.");
    if(last && (+dateOf(w)!==+nextMonth(last))) throw Error("Non-contiguous months.");last=w;
  }
  const groups = new Set(d.groups.map(g=>g.id));
  for(const c of d.categories) {
    if(ids.has(c.id)||!groups.has(c.group)||!Array.isArray(c.counts)||c.counts.length!==d.monthStarts.length) throw Error("Category integrity error.");
    ids.add(c.id);
    if(!c.counts.every(n=>Number.isInteger(n)&&n>=0)) throw Error("Missing or invalid counts.");
    for(const key of ["previousComparable","currentComparable","baselinePreviousCount"])
      if(!Number.isInteger(c[key])||c[key]<0)throw Error("Invalid comparison count.");
    if(c.currentComparable>c.counts[d.currentMonthIndex])throw Error("Comparison exceeds observed count.");
  }
  if(d.currentMonthIndex!==d.monthStarts.length-1||d.latestCompleteMonthIndex!==d.currentMonthIndex-1)throw Error("Invalid month indexes.");
  if(monthText(d.asOf)!==monthText(d.monthStarts.at(-1)))throw Error("Observation-month mismatch.");
  if(d.mode==="live" && d.coverage?.complete!==true) throw Error("Incomplete live harvest. Refusing partial counts.");
  return d;
}
function populateNavigation() {
  $("#group-nav").innerHTML=D.groups.map(g=>`<button class="nav-item" data-group="${esc(g.id)}"><span class="field-dot"></span><span>${esc(g.name)}</span></button>`).join("");
  $$("[data-group]").forEach(b=>b.onclick=()=>setGroup(b.dataset.group));
  $("#month-select").innerHTML=D.monthStarts.map((d,i)=>`<option value="${i}">${monthTitle(d)} · ${shortDate(d)}–${shortDate(endDay(d))}${i===D.currentMonthIndex?" · 速報":""}</option>`).reverse().join("");
  $("#current-month").textContent=observationLabel();
}
function renderStatus() {
  const demo=D.mode==="demo",age=(Date.now()-Date.parse(D.asOf))/DAY;
  const stamp=dateText(D.asOf)+" "+D.asOf.slice(11,16)+" UTC";
  $("#data-status").classList.toggle("live",!demo);
  $("#data-status").innerHTML=`<span class="tiny-dot"></span> ${demo?"DEMO":"UPDATED "+esc(dateText(D.asOf).slice(5))}`;
  $("#data-status").title=demo?"\u64cd\u4f5c\u78ba\u8a8d\u7528\u306e\u5408\u6210\u30c7\u30fc\u30bf":stamp;
  const notice=$("#data-notice"),short=D.monthStarts.length<(D.requestedMonths||60);
  notice.hidden=!demo&&age<=9&&!short;
  notice.classList.toggle("live-notice",!demo);
  if(demo) {
    notice.innerHTML='<span class="notice-label">DEMO</span><span>\u30b5\u30f3\u30d7\u30eb\u30c7\u30fc\u30bf</span><button data-action="method">\u96c6\u8a08\u65b9\u6cd5 \u2197</button>';
    $("#method-data-note").textContent=D.notice||"\u6295\u7a3f\u6570\u30fb\u63a8\u79fb\u30fb\u8ad6\u6587\u306f\u3059\u3079\u3066\u64cd\u4f5c\u78ba\u8a8d\u7528\u306e\u5408\u6210\u30c7\u30fc\u30bf\u3067\u3059\u3002";
  } else {
    notice.innerHTML=`<span class="notice-label">${age>9?"STALE":"COVERAGE"}</span><span>${age>9?"\u66f4\u65b0\u304b\u30899\u65e5\u4ee5\u4e0a\u7d4c\u904e":""}${short?" \u53ce\u9332 "+D.monthStarts.length+" / "+(D.requestedMonths||60)+"\u304b\u6708":""}</span><button data-action="method">\u8a73\u7d30 \u2197</button>`;
    $("#method-data-note").textContent="arXiv OAI-PMH\u306e\u5b9f\u30e1\u30bf\u30c7\u30fc\u30bf\u3002\u53d6\u5f97\u5b8c\u4e86\u3057\u305f\u30b9\u30ca\u30c3\u30d7\u30b7\u30e7\u30c3\u30c8\u3092\u8868\u793a\u3057\u3066\u3044\u307e\u3059\u3002\u53d6\u5f97\u6642\u70b9: "+stamp;
  }
}
function renderStats(cats) {
  const n=total(cats),p=previousTotal(cats),d=change(comparableTotal(cats),p);
  const rising=cats.filter(c=>change(comparable(c),reference(c))>0).length;
  $("#stats-grid").innerHTML=`
   <article class="stat-card"><div class="stat-label">${currentPartial()?"\u4eca\u6708\u306e\u6295\u7a3f\u6570":"\u6295\u7a3f\u6570"}</div><div class="stat-value">${fmt(n)}<span class="unit">papers</span></div></article>
   <article class="stat-card"><div class="stat-label">${currentPartial()?"\u524d\u6708\u540c\u671f\u9593\u6bd4":"\u524d\u6708\u6bd4"}</div><div class="stat-value delta ${deltaClass(d)}">${deltaText(d)}</div></article>
   <article class="stat-card"><div class="stat-label">\u5897\u52a0\u3057\u305f\u9818\u57df</div><div class="stat-value">${rising}<span class="unit">/ ${cats.length}</span></div><span class="breadth-track" aria-hidden="true">${cats.length<=12?cats.map((c,i)=>`<i${i<rising?' class="up"':""}></i>`).join(""):""}</span></article>`;
}
function momentum(cats,scope,end){
  if(end<5)return [];
  const sum=(c,a,b)=>c.counts.slice(a,b+1).reduce((x,y)=>x+y,0);
  const priorTotal=scope.reduce((x,c)=>x+sum(c,end-5,end-3),0);
  const recentTotal=scope.reduce((x,c)=>x+sum(c,end-2,end),0);
  if(!priorTotal||!recentTotal)return [];
  return cats.map(c=>{const prior=sum(c,end-5,end-3),recent=sum(c,end-2,end);return {cat:c,prior,recent,score:100*(recent/recentTotal-prior/priorTotal)};})
    .filter(v=>v.prior>=30&&v.score>0)
    .sort((a,b)=>b.score-a.score||b.recent-a.recent||a.cat.id.localeCompare(b.cat.id));
}
function renderInsights(cats) {
  const end=currentPartial()?D.currentMonthIndex-1:state.month;
  const movers=momentum(cats,contextCats(),end).slice(0,3);
  $("#momentum-period").textContent=end>=5?`${monthText(D.monthStarts[end-2])}\u2013${monthText(D.monthStarts[end])} / ${monthText(D.monthStarts[end-5])}\u2013${monthText(D.monthStarts[end-3])}`:"\u6bd4\u8f03\u671f\u9593\u4e0d\u8db3";
  $("#movers").innerHTML=movers.length?movers.map((v,i)=>`<button class="mover-row" data-cat="${esc(v.cat.id)}" title="${esc(v.cat.name)}"><span class="mover-index">0${i+1}</span><span class="mover-name">${esc(v.cat.shortName)}</span><span class="mover-rate">+${v.score.toFixed(2)}<small>pt</small></span></button>`).join(""):'<div class="watch-empty">\u8a72\u5f53\u306a\u3057</div>';
  $$("#movers [data-cat]").forEach(b=>b.onclick=()=>openDrawer(b.dataset.cat));
  const favorites=D.categories.filter(c=>state.watch.has(c.id));
  $("#watch-count").textContent=favorites.length;
  $("#watchlist-mini").innerHTML=favorites.length?favorites.slice(0,4).map(c=>`<button class="watch-mini-row" data-cat="${esc(c.id)}"><span>${esc(c.shortName)}</span><span class="${deltaClass(change(comparable(c),reference(c)))}">${deltaText(change(comparable(c),reference(c)))}</span></button>`).join(""):'<p class="watch-empty">\u2606 \u3067\u7814\u7a76\u9818\u57df\u3092\u4fdd\u5b58</p>';
  $$("#watchlist-mini [data-cat]").forEach(b=>b.onclick=()=>openDrawer(b.dataset.cat));
}
function squarify(input,x,y,w,h) {
  const valid=input.filter(n=>n.value>0 && Number.isFinite(n.value));
  const sum=valid.reduce((a,b)=>a+b.value,0);
  if(!sum||w<=0||h<=0) return [];
  const queue=valid.map(n=>({...n,area:n.value*w*h/sum})).sort((a,b)=>b.area-a.area);
  const output=[];
  let row=[],i=0;
  const worst=(r,side)=>{
    if(!r.length||side<=0)return Infinity;
    const areas=r.map(v=>v.area),s=areas.reduce((a,b)=>a+b,0);
    return Math.max(side*side*Math.max(...areas)/(s*s),s*s/(side*side*Math.min(...areas)));
  };
  const place=()=>{
    const a=row.reduce((s,n)=>s+n.area,0);
    if(w>=h) {
      const rw=a/h;let yy=y;
      row.forEach(n=>{const rh=n.area/rw;output.push({...n,x,y:yy,w:rw,h:rh});yy+=rh;});
      x+=rw;w=Math.max(0,w-rw);
    } else {
      const rh=a/w;let xx=x;
      row.forEach(n=>{const rw=n.area/rh;output.push({...n,x:xx,y,w:rw,h:rh});xx+=rw;});
      y+=rh;h=Math.max(0,h-rh);
    }
    row=[];
  };
  while(i<queue.length) {
    const n=queue[i],side=Math.min(w,h);
    if(!row.length||worst([...row,n],side)<=worst(row,side)) {row.push(n);i++;}
    else place();
  }
  if(row.length)place();
  return output;
}
function tileColor(delta) {
  const neutral=state.palette?[37,50,62]:[37,50,55];
  const positive=state.palette?[57,114,156]:[42,126,107];
  const negative=state.palette?[147,100,55]:[134,73,77];
  if(delta===null) return "rgb(45,51,62)";
  const t=Math.pow(Math.min(1,Math.abs(delta===Infinity?50:delta)/50),.72);
  const end=delta>=0?positive:negative;
  return "rgb("+neutral.map((n,i)=>Math.round(n+(end[i]-n)*t)).join(",")+")";
}
function makeTile(c,rect,parent) {
  const tile=document.createElement("button");
  const w=Math.max(0,rect.w-3),h=Math.max(0,rect.h-3);
  tile.className="tile"+(w<24||h<18?" micro":h<66?" tiny short":w<96||h<109?" tiny":w<156||h<145?" compact":"");
  tile.style.cssText=`left:${rect.x+1.5}px;top:${rect.y+1.5}px;width:${w}px;height:${h}px;background:${tileColor(change(comparable(c),reference(c)))};`;
  tile.dataset.cat=c.id;
  const d=change(comparable(c),reference(c));
  tile.setAttribute("aria-label",`${c.name}、${fmt(count(c))}本、${currentPartial()?"前月同期間比":"前月比"}${deltaText(d)}。Enterで論文一覧。`);
  tile.innerHTML=`<div><span class="tile-code">${esc(c.id)}</span><span class="tile-name">${esc(c.shortName)}</span></div><div class="tile-meta"><div><span class="tile-value">${fmt(count(c))}<small>papers</small></span><span class="tile-change">${deltaText(d)}</span></div><span class="tile-arrow">↗</span></div>`;
  tile.addEventListener("pointerenter",e=>{if(e.pointerType!=="touch")showHover(c,e);});
  tile.addEventListener("pointermove",e=>{if(!$("#hovercard").hidden)positionHover(e.clientX,e.clientY);});
  tile.addEventListener("pointerleave",hideHover);
  tile.addEventListener("focus",()=>{if(!state.drawer){const r=tile.getBoundingClientRect();showHover(c,{clientX:r.left+r.width/2,clientY:r.top+Math.min(r.height,30)});}});
  tile.addEventListener("blur",hideHover);
  tile.addEventListener("click",()=>openDrawer(c.id));
  parent.appendChild(tile);
}
function renderMap(cats) {
  const el=$("#treemap");el.innerHTML="";
  if(state.view!=="map")return;
  const positive=cats.filter(c=>count(c)>0);
  if(!positive.length) {
    el.innerHTML=`<div class="empty-state"><strong>${state.group==="watch"?"☆":"∅"}</strong><span>${!cats.length?(state.group==="watch"?"ウォッチリストはまだ空です":"一致する研究領域がありません"):"この月の投稿は0本です"}</span><p>${state.group==="watch"?"研究領域の論文パネルで ☆ を押して追加できます。":"検索条件を変えるか、別の月を選んでください。"}</p><button id="reset-map">Physics全体を見る</button></div>`;
    $("#reset-map").onclick=()=>setGroup("all");return;
  }
  const width=el.clientWidth,height=el.clientHeight;
  const gIds=[...new Set(positive.map(c=>c.group))];
  if(gIds.length===1) {
    squarify(positive.map(c=>({id:c.id,value:count(c)})),0,0,width,height).forEach(r=>makeTile(catOf(r.id),r,el));
  } else {
    const gRects=squarify(gIds.map(id=>({id,value:total(positive.filter(c=>c.group===id))})),0,0,width,height);
    gRects.forEach(gr=>{
      const container=document.createElement("div");container.className="map-group";
      const gw=Math.max(1,gr.w-3),gh=Math.max(1,gr.h-3);
      container.style.cssText=`left:${gr.x+1.5}px;top:${gr.y+1.5}px;width:${gw}px;height:${gh}px`;
      const headerH=window.innerWidth<=580?20:23;
      const g=groupOf(gr.id);const button=document.createElement("button");button.className="map-group-header";
      button.setAttribute("aria-label",g.name+"に絞り込む");
      button.innerHTML=`<span>${esc(gw<110?g.abbr:g.name.toUpperCase())}</span><small>${fmt(gr.value)} ↗</small>`;
      button.onclick=()=>setGroup(g.id);container.appendChild(button);el.appendChild(container);
      const groupCats=positive.filter(c=>c.group===gr.id);
      squarify(groupCats.map(c=>({id:c.id,value:count(c)})),1,headerH,gw-2,Math.max(0,gh-headerH-1)).forEach(r=>makeTile(catOf(r.id),r,container));
    });
  }
}
function renderZero(cats) {
  const zeros=cats.filter(c=>count(c)===0);const box=$("#zero-categories");
  box.hidden=!zeros.length;
  box.innerHTML=`<span>0 papers</span>`+zeros.map(c=>`<button data-cat="${esc(c.id)}">${esc(c.id)}</button>`).join("");
  $$("[data-cat]",box).forEach(b=>b.onclick=()=>openDrawer(b.dataset.cat));
}
function renderTable(cats) {
  $("#table-wrap").innerHTML=`<table class="data-table"><thead><tr><th>研究領域</th><th>投稿数</th><th>${currentPartial()?"前月同期間":"前月"}</th><th>${currentPartial()?"同期間比":"前月比"}</th></tr></thead><tbody>${[...cats].sort((a,b)=>count(b)-count(a)).map(c=>`<tr><td><button data-cat="${esc(c.id)}">${esc(c.name)}<small>${esc(c.id)}</small></button></td><td>${fmt(count(c))}</td><td>${fmt(reference(c))}</td><td>${deltaHTML(change(comparable(c),reference(c)))}</td></tr>`).join("")}</tbody></table>`;
  $$("#table-wrap [data-cat]").forEach(b=>b.onclick=()=>openDrawer(b.dataset.cat));
}
function render() {
  ++drawToken;
  const cats=visibleCats();
  $$("[data-group]").forEach(b=>b.classList.toggle("active",b.dataset.group===state.group));
  $("#watch-nav").classList.toggle("active",state.group==="watch");
  $("#crumb-current").textContent=contextName().toUpperCase();
  $("#field-title").textContent=state.group==="all"?"All physics":contextName();
  $("#map-title").textContent="Research map"+(state.query?` / ${cats.length}`:"");
  $("#month-select").value=String(state.month);
  $("#prev-month").disabled=state.month<=0;$("#next-month").disabled=state.month>=D.monthStarts.length-1;
  const selected=D.monthStarts[state.month];
  $("#period-title").textContent=monthTitle(selected);
  $("#period-range").textContent=`${shortDate(selected)}\u2013${shortDate(endDay(selected))} \u00b7 UTC`;
  $("#current-month").classList.toggle("selected",currentPartial());
  $("#complete-month").classList.toggle("selected",state.month===D.latestCompleteMonthIndex);
  $("#current-month").setAttribute("aria-pressed",String(currentPartial()));
  $("#complete-month").setAttribute("aria-pressed",String(state.month===D.latestCompleteMonthIndex));
  $("#month-tag").innerHTML=currentPartial()?"<b>\u901f\u5831</b>":"\u7d42\u4e86\u6708";
  $("#month-tag").title=currentPartial()?`${dateText(D.asOf)} ${D.asOf.slice(11,16)} UTC\u307e\u3067\u3002\u8272\u306f\u524d\u6708\u306e\u540c\u3058\u7d4c\u904e\u671f\u9593\u3068\u6bd4\u8f03\u3002`:"UTC\u66a6\u6708\u3002\u516c\u958b\u9045\u5ef6\u7b49\u306b\u3088\u308a\u5f8c\u65e5\u4fee\u6b63\u306e\u53ef\u80fd\u6027\u3042\u308a\u3002";
  $("#coverage-note").textContent=`${monthText(D.monthStarts[0])}\u2013${monthText(D.monthStarts.at(-1))} / ${D.monthStarts.length}/${D.requestedMonths||60}\u304b\u6708\uff08\u901f\u5831\u6708\u3092\u542b\u3080\uff09`;
  $("#comparison-label").textContent=currentPartial()?"\u524d\u6708\u540c\u671f\u9593\u6bd4":"\u524d\u6708\u6bd4";
  $("#treemap").hidden=state.view!=="map";$("#table-wrap").hidden=state.view!=="table";
  $("#map-view").classList.toggle("selected",state.view==="map");$("#map-view").setAttribute("aria-pressed",state.view==="map");
  $("#table-view").classList.toggle("selected",state.view==="table");$("#table-view").setAttribute("aria-pressed",state.view==="table");
  document.body.classList.toggle("colorblind",state.palette);$("#palette-toggle").setAttribute("aria-pressed",state.palette);
  renderStats(cats);renderInsights(cats);renderZero(cats);renderTable(cats);renderMap(cats);
  $("#history-title").textContent="Monthly trend";
  $("#snapshot-label").textContent=`${D.mode==="demo"?"DEMO / ":""}${dateText(D.asOf)} ${D.asOf.slice(11,16)} UTC`;
  refreshCharts();
}
function refreshCharts() {
  $$("[data-range]").forEach(b=>{const on=+b.dataset.range===state.range;b.classList.toggle("selected",on);b.setAttribute("aria-pressed",String(on));});
  $$("[data-scale]").forEach(b=>{const on=b.dataset.scale===state.scale;b.classList.toggle("selected",on);b.setAttribute("aria-pressed",String(on));});
  $$("[data-provisional]").forEach(b=>b.setAttribute("aria-pressed",String(state.provisional)));
  const series=chartSeries(visibleCats()),model=chartWindow(series.values,series.dates);
  $("#chart-scope").textContent=model.length?`${monthText(model[0].date)}\u2013${monthText(model.at(-1).date)} \u00b7 ${state.provisional?"\u901f\u5831\u542b\u3080":"\u7d42\u4e86\u6708"}`:"\u30c7\u30fc\u30bf\u306a\u3057";
  $("#history-total").textContent=`${model.length} MONTHS / ${fmt(model.reduce((s,p)=>s+p.value,0))} PAPERS`;
  renderChart($("#history-chart"),series.values,series.dates,{interactive:true});
  if(state.drawer){
    const s=chartSeries([catOf(state.drawer)]),model=chartWindow(s.values,s.dates);
    $("#drawer-period").textContent=model.length?`${monthText(model[0].date)}\u2013${monthText(model.at(-1).date)} \u00b7 ${state.provisional?"\u901f\u5831\u542b\u3080":"\u7d42\u4e86\u6708"}`:"";
    renderChart($("#drawer-chart"),s.values,s.dates,{interactive:true});
  }
}
function chartDomain(input,forceZero=false) {
  const values=input.filter(v=>Number.isFinite(v)&&v>=0);
  if(!values.length)return {min:0,max:1,low:null,high:null,ticks:[0,1]};
  const low=Math.min(...values),high=Math.max(...values),span=high-low;
  const pad=span>0?Math.max(1,span*.12):Math.max(2,Math.abs(low)*.04);
  const rawMin=forceZero?0:Math.max(0,low-pad),rawMax=high+pad;
  const rough=(rawMax-rawMin)/5,power=10**Math.floor(Math.log10(Math.max(rough,1e-8)));
  const step=Math.max(1,[1,2,2.5,5,10].filter(v=>v*power<=rough).at(-1)*power);
  const min=forceZero?0:Math.max(0,Math.floor(rawMin/step)*step);
  const max=Math.max(min+step,Math.ceil(rawMax/step)*step);
  const ticks=[];for(let v=min;v<=max+step*.01;v+=step)ticks.push(Number(v.toFixed(8)));
  return {min,max,low,high,ticks};
}
function chartWindow(values,dates) {
  const end=state.provisional?values.length:D.currentMonthIndex;
  const start=Math.max(0,end-state.range);
  return values.slice(start,end).map((value,i)=>({value,index:i+start,date:dates[i+start],partial:i+start===D.currentMonthIndex}));
}
function renderChart(container,values,dates,{interactive=false,mini=false}={}) {
  const points=chartWindow(values,dates);
  if(!points.length){container.innerHTML='<div class="empty-state">\u7d42\u4e86\u6708\u306e\u30c7\u30fc\u30bf\u304c\u3042\u308a\u307e\u305b\u3093</div>';return;}
  const w=Math.max(220,container.clientWidth||350),h=Math.max(150,container.clientHeight||190);
  const averages=points.map((p,j)=>p.index>=2&&!p.partial?{j,value:(values[p.index]+values[p.index-1]+values[p.index-2])/3}:null).filter(Boolean);
  const domain=chartDomain([...points.map(p=>p.value),...averages.map(p=>p.value)],state.scale==="zero");
  const observedMin=Math.min(...points.map(p=>p.value)),observedMax=Math.max(...points.map(p=>p.value));
  const maxDigits=fmt(domain.max).length;
  const m={l:7,r:Math.max(mini?49:55,maxDigits*(mini?6:7)+14),t:mini?32:40,b:47};
  const base=h-m.b,pw=w-m.l-m.r,ph=base-m.t;
  const X=i=>m.l+(points.length===1?.5:i/(points.length-1))*pw;
  const Y=v=>base-(v-domain.min)/(domain.max-domain.min)*ph;
  const completed=points.map((p,j)=>({...p,j})).filter(p=>!p.partial);
  const path=completed.map((p,j)=>`${j?"L":"M"}${X(p.j).toFixed(2)},${Y(p.value).toFixed(2)}`).join(" ");
  const last=points.at(-1),lastY=Y(last.value),uid="pulse-gradient-"+(++chartSerial);
  const gridTicks=domain.ticks.filter((v,i)=>i%Math.ceil(domain.ticks.length/(mini?3:6))===0||i===domain.ticks.length-1);
  const grid=gridTicks.map(v=>`<line class="chart-grid" x1="${m.l}" y1="${Y(v)}" x2="${w-m.r}" y2="${Y(v)}"/>${Math.abs(Y(v)-lastY)>15?`<text class="chart-axis" x="${w-m.r+10}" y="${Y(v)+3}">${fmt(v)}</text>`:""}`).join("");
  const nlabels=mini||w<500?3:6,idx=[...new Set(Array.from({length:nlabels},(_,i)=>Math.round((points.length-1)*i/(nlabels-1))))];
  const labels=idx.map(i=>`<text class="chart-axis" x="${X(i)}" y="${base+20}" text-anchor="${i===0?"start":i===points.length-1?"end":"middle"}">${monthText(points[i].date)}</text>`).join("");
  const averagePath=averages.map((p,i)=>`${i?"L":"M"}${X(p.j).toFixed(2)},${Y(p.value).toFixed(2)}`).join(" ");
  const partial=last.partial&&points.length>1?`<path class="chart-partial" d="M${X(points.length-2)},${Y(points.at(-2).value)} L${X(points.length-1)},${lastY}"/>`:"";
  const selected=points.findIndex(p=>p.index===state.month),initial=selected<0?points.length-1:selected;
  const lowAt=points.findIndex(p=>p.value===observedMin);
  const lineArea=completed.length>1?`<path d="${path} L${X(completed.at(-1).j)},${base} L${X(completed[0].j)},${base} Z" fill="url(#${uid})"/>`:"";
  const pillColor=last.partial?"var(--amber)":"var(--accent)";
  container.innerHTML=`<svg class="chart-interactive" viewBox="0 0 ${w} ${h}" role="img" ${interactive?'tabindex="0"':""} data-y-min="${domain.min}" data-y-max="${domain.max}" data-value-min="${observedMin}" data-value-max="${observedMax}" data-points="${points.length}" aria-label="${points.length}\u304b\u6708\u306e\u6295\u7a3f\u6570\u3002\u7e26\u8ef8 ${domain.min}\u301c${domain.max}\u3002\u6700\u5c0f ${observedMin}\u3001\u6700\u5927 ${observedMax}\u3002${state.provisional?'\u901f\u5831\u6708\u3092\u542b\u307f\u307e\u3059\u3002':'\u7d42\u4e86\u6708\u306e\u307f\u3002'}${interactive?'\u5de6\u53f3\u30ad\u30fc\u3067\u79fb\u52d5\u3001Enter\u3067\u6708\u3092\u9078\u629e\u3002':''}">
   <defs><linearGradient id="${uid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--accent)" stop-opacity=".13"/><stop offset="100%" stop-color="var(--accent)" stop-opacity=".005"/></linearGradient></defs>
   <text class="chart-date" x="${m.l}" y="18"></text><text class="chart-quote" x="${mini?80:92}" y="19"></text><text class="chart-period-badge" x="${w-m.r}" y="18" text-anchor="end"></text>
   ${grid}${lineArea}${averagePath?`<path class="chart-average" d="${averagePath}"/>`:""}<path class="chart-line" d="${path}"/>${partial}
   ${selected>=0?`<line class="selected-guide" x1="${X(selected)}" x2="${X(selected)}" y1="${m.t}" y2="${base}" stroke="var(--accent)" stroke-opacity=".12" stroke-dasharray="2 4"/>`:""}
   <circle class="chart-low" cx="${X(lowAt)}" cy="${Y(observedMin)}" r="2.5" fill="var(--bg)" stroke="var(--accent)"/>
   <circle class="chart-last" cx="${X(points.length-1)}" cy="${lastY}" r="3" fill="${pillColor}"/>
   <rect x="${w-m.r+4}" y="${lastY-10}" width="${m.r-4}" height="20" rx="3" fill="${pillColor}" fill-opacity=".16"/><text x="${w-m.r+9}" y="${lastY+3}" fill="${pillColor}" style="font: ${mini?10:11}px var(--mono)">${fmt(last.value)}</text>
   ${labels}
   <text class="chart-extrema" x="${m.l}" y="${h-5}">LOW <tspan class="value">${fmt(observedMin)}</tspan> / HIGH <tspan class="value">${fmt(observedMax)}</tspan></text><text class="chart-mode" x="${w-2}" y="${h-5}" text-anchor="end">${state.scale==="auto"?"AUTO Y":"ZERO Y"}</text>
   ${points.map((p,j)=>`<circle class="month-point${p.partial?' partial-point':''}" data-index="${p.index}" cx="${X(j)}" cy="${Y(p.value)}" r="7" fill="transparent"><title>${monthText(p.date)} / ${fmt(p.value)}${p.partial?' (\u901f\u5831)':''}</title></circle>`).join("")}
   ${interactive?`<g class="chart-crosshair" style="display:none"><line class="cursor-v" y1="${m.t}" y2="${base}"/><line class="cursor-h" x1="${m.l}" x2="${w-m.r}"/><circle class="cursor-point" r="4"/></g>`:""}
  </svg>`;
  const svg=container.firstElementChild;
  let active=initial;
  const quote=i=>{$(".chart-date",svg).textContent=monthText(points[i].date);$(".chart-quote",svg).textContent=fmt(points[i].value);$(".chart-period-badge",svg).textContent=points[i].partial?"\u901f\u5831":"\u7d42\u4e86\u6708";};
  quote(initial);
  if(!interactive)return;
  const draw=i=>{
    active=Math.max(0,Math.min(points.length-1,i));quote(active);
    const x=X(active),y=Y(points[active].value),g=$(".chart-crosshair",svg);g.style.display="";
    $(".cursor-v",g).setAttribute("x1",x);$(".cursor-v",g).setAttribute("x2",x);
    $(".cursor-h",g).setAttribute("y1",y);$(".cursor-h",g).setAttribute("y2",y);
    $("circle",g).setAttribute("cx",x);$("circle",g).setAttribute("cy",y);
  };
  const at=e=>{const r=svg.getBoundingClientRect();return Math.max(0,Math.min(points.length-1,Math.round(((e.clientX-r.left)/r.width*w-m.l)/pw*(points.length-1))));};
  const reset=()=>{$(".chart-crosshair",svg).style.display="none";quote(initial);};
  svg.onpointermove=e=>{if(e.pointerType!=="touch")draw(at(e));};svg.onpointerleave=reset;
  svg.onclick=e=>setMonth(points[at(e)].index);
  svg.onfocus=()=>draw(active);svg.onblur=reset;
  svg.onkeydown=e=>{
    if(["ArrowLeft","ArrowRight","Home","End"].includes(e.key)){e.preventDefault();draw(e.key==="Home"?0:e.key==="End"?points.length-1:active+(e.key==="ArrowRight"?1:-1));}
    if(["Enter"," "].includes(e.key)){e.preventDefault();setMonth(points[active].index);container.querySelector("svg")?.focus({preventScroll:true});}
  };
}
function showHover(c,e) {
  if(state.drawer)return;
  const tip=$("#hovercard"),n=count(c),d=change(comparable(c),reference(c));
  const s=chartSeries([c]),points=chartWindow(s.values,s.dates);
  tip.innerHTML=`<div class="hover-top"><span>${esc(c.id)}</span>${deltaHTML(d)}</div><h3>${esc(c.shortName)}</h3><div class="hover-stats"><strong>${fmt(n)}</strong><span>papers</span><span class="prev">${monthText(D.monthStarts[state.month])}${currentPartial()?" / \u901f\u5831":""}</span></div><div class="hover-chart"></div><div class="hover-foot"><span>${points.length} MONTHS / ${state.provisional?"\u901f\u5831\u542b\u3080":"\u7d42\u4e86\u6708"}</span><span>${D.mode==="demo"?"DEMO":""}</span></div>`;
  tip.hidden=false;renderChart($(".hover-chart",tip),s.values,s.dates,{mini:true});positionHover(e.clientX,e.clientY);
}
function positionHover(x,y) {
  const tip=$("#hovercard");const r=tip.getBoundingClientRect();
  let left=x+17,top=y+17;
  if(left+r.width>innerWidth-12)left=x-r.width-17;
  if(top+r.height>innerHeight-12)top=y-r.height-17;
  tip.style.left=Math.max(10,Math.min(innerWidth-r.width-10,left))+"px";
  tip.style.top=Math.max(10,Math.min(innerHeight-r.height-10,top))+"px";
}
function hideHover() {$("#hovercard").hidden=true;}
function demoPapers(c,i){
  const n=count(c,i),start=+dateOf(D.monthStarts[i]),end=Math.min(+nextMonth(D.monthStarts[i]),Date.parse(D.asOf));
  const recent=D.titlesSince&&end>Date.parse(D.titlesSince);
  const topics=["Disorder and quantum transport in low-dimensional systems","Learning dynamics in a frustrated neural network","Collective states and topological transitions","Landau-level structure under tunable strain","Scaling laws for nonequilibrium dynamics"];
  return Array.from({length:n},(_,j)=>({id:`DEMO-${i}-${j+1}`,created:Math.floor((start+(end-start)*(n-j)/(n+1))/1000),title:recent?`[DEMO] ${topics[j%topics.length]} 	 ${j+1}`:null,
    authors:recent&&j%5!==4?(j%7===1?Array.from({length:18},(_,k)=>`Researcher ${k+1} (Example Institute ${k+1})`).join(', '):'A. Example, B. Sample and C. Demo'):null,
    abstract:recent&&j%3!==2?'[DEMO] Synthetic abstract for interface testing, not a real paper. We investigate cyclotron resonance and Landau quantization in a tunable model. Quantum transport changes with disorder, while the response is compared across magnetic fields. No scientific result is asserted.':null}));
}
function validId(s){return typeof s==="string"&&/^(?:\d{4}\.\d{4,5}|[a-z][a-z.-]*\/\d{7})$/.test(s);}
async function loadPapers(c,i){
  if(!D.paperIndexEnabled)throw Error("この設定では件数だけを公開しています。論文インデックスは書き出していません。");
  if(D.mode==="demo")return demoPapers(c,i);
  if(count(c,i)===0)return [];
  const month=D.monthStarts[i],key=month+":"+c.id;
  if(!paperCache.has(key)){
    const path=D.paperFiles?.[month]?.[c.id];
    if(typeof path!=="string"||!/^data\/papers\/\d{4}-\d{2}-01\/[a-zA-Z0-9.-]+-[a-f0-9]{12}\.json\.gz$/.test(path))throw Error("Invalid compact index manifest.");
    const response=await fetch(path,{cache:"no-cache"});if(!response.ok)throw Error("論文インデックスを読み込めません。HTTPサーバ経由で開いてください。");
    const bytes=new Uint8Array(await response.arrayBuffer());let payload;
    if(bytes[0]===31&&bytes[1]===139){
      if(typeof DecompressionStream!=="function")throw Error("Use a browser supporting gzip DecompressionStream.");
      payload=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).json();
    }else payload=JSON.parse(new TextDecoder().decode(bytes));
    const lo=+dateOf(month)/1000,hi=Math.min(+nextMonth(month),Date.parse(D.asOf))/1000;
    if(![1,2].includes(payload.schemaVersion)||payload.month!==month||payload.category!==c.id||!Array.isArray(payload.papers)||payload.papers.length!==count(c,i))throw Error("Index/count mismatch.");
    const seen=new Set();
    const rows=payload.papers.map(p=>{
      const sizes=payload.schemaVersion===1?[2,3]:[2,3,4,5];
      if(!Array.isArray(p)||!sizes.includes(p.length)||!validId(p[0])||seen.has(p[0])||!Number.isInteger(p[1])||p[1]<lo||p[1]>=hi||p.slice(2).some(v=>v!==null&&typeof v!=="string")||(payload.schemaVersion===1&&p.length===3&&typeof p[2]!=="string"))throw Error("Invalid compact paper record.");
      seen.add(p[0]);return {id:p[0],created:p[1],title:p[2]??null,authors:p[3]??null,abstract:p[4]??null};
    });
    if(paperCache.size>=12)paperCache.delete(paperCache.keys().next().value);
    paperCache.set(key,rows);
  }
  return paperCache.get(key);
}
function interestTerms(text){return [...new Set(text.normalize("NFKC").toLowerCase().split(/[,;\n、]/).map(t=>t.trim()).filter(Boolean))].slice(0,20);}
function keywordMatches(title,terms){
  if(!title)return [];
  const text=title.normalize("NFKC").toLowerCase();
  return terms.filter(term=>{if(/[\u3040-\u30ff\u3400-\u9fff]/u.test(term))return text.includes(term);
    const q=term.replace(/[.*+?^${}()|[\]\\]/g,"\\$&");
    return new RegExp("(^|[^\\p{L}\\p{N}])"+q+"(?=$|[^\\p{L}\\p{N}])","u").test(text);
  });
}

function normalizeSearch(value){return String(value??"").normalize("NFKC").toLowerCase().replace(/[\u2010-\u2015\u2212]/g,"-").replace(/\s+/g," ").trim();}
function searchTerms(value){
  const tokens=[];for(const m of String(value??"").matchAll(/"([^"]+)"|([^\s,\u3001]+)/gu)){const t=normalizeSearch(m[1]??m[2]);if(t&&!tokens.includes(t))tokens.push(t);if(tokens.length===20)break;}return tokens;
}
function searchable(p){return p._search??(p._search={id:normalizeSearch(p.id),title:normalizeSearch(p.title),authors:normalizeSearch(p.authors),abstract:normalizeSearch(p.abstract)});}
function queryMatches(p,terms,field="all"){
  const f=searchable(p),values=field==="all"?Object.values(f):[f[field]??""];
  return terms.every(term=>values.some(value=>value.includes(term)));
}
function paperKeywordMatches(p,terms){const title=keywordMatches(p.title,terms),abstract=keywordMatches(p.abstract,terms);return terms.filter(t=>title.includes(t)||abstract.includes(t));}
function highlight(text,terms){
  text=String(text??"");if(!terms.length)return esc(text);
  const source=terms.slice().sort((a,b)=>b.length-a.length).map(t=>t.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")).join("|");
  if(!source)return esc(text);
  let out="",last=0;for(const m of text.matchAll(new RegExp(source,"giu"))){out+=esc(text.slice(last,m.index))+"<mark>"+esc(m[0])+"</mark>";last=m.index+m[0].length;}return out+esc(text.slice(last));
}
function authorsHTML(p,terms){
  if(!p.authors)return '<p class="paper-authors missing">\u8457\u8005\u672a\u4fdd\u5b58</p>';
  if(p.authors.length<=180)return `<p class="paper-authors">${highlight(p.authors,terms)}</p>`;
  return `<details class="paper-author-details"><summary><span class="authors-preview">${highlight(p.authors.slice(0,160),terms)}\u2026</span><span class="author-expander"><span class="label-closed">\u5168\u8457\u8005</span><span class="label-open">\u9589\u3058\u308b</span></span></summary><p class="paper-authors">${highlight(p.authors,terms)}</p></details>`;
}
function hitFields(p,terms){
  if(!terms.length)return [];
  const labels={title:"\u30bf\u30a4\u30c8\u30eb",authors:"\u8457\u8005",abstract:"\u8981\u65e8",id:"ID"},fields=searchable(p);
  return Object.keys(labels).filter(k=>(state.paperField==="all"||state.paperField===k)&&terms.some(t=>fields[k].includes(t))).map(k=>labels[k]);
}

async function openDrawer(id,reset=true) {
  const c=catOf(id);if(!c)return;
  if(!state.drawer)previousFocus=document.activeElement;
  state.drawer=id;state.paperLimit=25;currentPapers=[];
  if(reset){state.paperQuery="";state.paperField="all";$("#search-field").value="all";state.sort=interestTerms(state.interests).length?"match":"newest";$("#paper-search").value="";}
  hideHover();
  $("#drawer-backdrop").hidden=false;$("#paper-drawer").hidden=false;
  document.body.style.overflow="hidden";$("#main").inert=true;$("#sidebar").inert=true;
  $("#drawer-breadcrumb").textContent=groupOf(c.group).name.toUpperCase();
  $("#drawer-code").textContent=c.id;
  $("#drawer-title").textContent=c.name;
  $("#drawer-ja").textContent=c.ja;
  const n=count(c),p=reference(c),d=change(comparable(c),p);
  $("#drawer-stats").innerHTML=`<div class="drawer-stat"><small>${currentPartial()?observationLabel()+" · 速報":"選択月の投稿"}</small><strong>${fmt(n)}</strong></div><div class="drawer-stat"><small>${currentPartial()?"前月同期間":"前月の投稿"}</small><strong>${fmt(p)}</strong></div><div class="drawer-stat"><small>${currentPartial()?"同期間比":"前月比"}</small><strong class="delta ${deltaClass(d)}">${deltaText(d)}</strong></div>`;
  $("#drawer-watch").textContent=state.watch.has(c.id)?"★":"☆";
  $("#drawer-watch").setAttribute("aria-label",state.watch.has(c.id)?"ウォッチリストから削除":"ウォッチリストに追加");
  const s=chartSeries([c]);
  $("#drawer-period").textContent=`${monthText(s.dates[0])} — ${monthText(s.dates.at(-1))}`;
  refreshCharts();
  $("#papers-heading").textContent=monthTitle(D.monthStarts[state.month])+"の論文";
  $("#interest-input").value=state.interests;
  $("#papers-count").textContent=`${fmt(n)} papers`;
  $("#papers-list").innerHTML='<div class="empty-state"><span>論文を読み込んでいます…</span></div>';
  $("#ranking-note").hidden=false;$("#ranking-note").textContent="";
  $("#load-more").hidden=true;
  if(reset){$("#paper-drawer").scrollTop=0;$("#drawer-close").focus({preventScroll:true});}
  const token=++paperRequest;
  for(const selector of [".paper-sort",".interest-label",".paper-search-row","#metadata-coverage"]){$(selector).hidden=!D.paperIndexEnabled;}
  if(!D.paperIndexEnabled){
    $("#ranking-note").textContent="件数のみを公開する設定です。論文インデックスは作成していません。";
    $("#papers-list").innerHTML=`<div class="empty-state"><span>論文インデックスは非公開です</span><p>上の投稿数と月次推移はそのまま確認できます。</p><a href="https://arxiv.org/list/${encodeURIComponent(c.id)}/recent" target="_blank" rel="noopener noreferrer">arXivでこの領域の新着を開く ↗</a></div>`;
    return;
  }
  try {
    const papers=await loadPapers(c,state.month);
    if(token!==paperRequest||state.drawer!==id)return;
    currentPapers=papers;
    const observed=papers.length;
    if(observed!==n) throw Error(`集計値${n}本と論文一覧${observed}本が一致しません。スナップショットの整合性を確認してください。`);
    if(!papers.some(p=>p.title||p.abstract)||!interestTerms(state.interests).length)state.sort="newest";
    renderPapers();
  } catch(err) {
    if(token!==paperRequest)return;
    currentPapers=[];
    $("#ranking-note").textContent="取得失敗。架空の論文で補完せず、エラーを表示しています。";
    $("#papers-list").innerHTML=`<div class="empty-state"><strong>!</strong><span>論文一覧を読み込めませんでした</span><p>${esc(err.message)}</p><button id="retry-papers">もう一度読み込む</button></div>`;
    $("#retry-papers").onclick=()=>{paperCache.delete(D.monthStarts[state.month]+":"+state.drawer);openDrawer(id,false);};
  }
}
function renderPapers(){
  const terms=interestTerms(state.interests),query=searchTerms(state.paperQuery);
  const titled=currentPapers.filter(p=>p.title).length,authored=currentPapers.filter(p=>p.authors).length,abstracted=currentPapers.filter(p=>p.abstract).length;
  const canMatch=terms.length>0&&currentPapers.some(p=>p.title||p.abstract);
  if(!canMatch)state.sort="newest";
  $$("[data-sort]").forEach(b=>{b.disabled=b.dataset.sort==="match"&&!canMatch;b.classList.toggle("selected",b.dataset.sort===state.sort);b.setAttribute("aria-pressed",String(b.dataset.sort===state.sort));});
  $("#ranking-note").textContent=(D.mode==="demo"?"DEMO / ":"")+(state.sort==="match"?"\u4fdd\u5b58\u6e08\u307f\u30bf\u30a4\u30c8\u30eb\u30fb\u8981\u65e8\u306e\u4e00\u81f4\u6570\u9806":(!titled?"\u30bf\u30a4\u30c8\u30eb\u672a\u4fdd\u5b58 / arXiv\u3067\u78ba\u8a8d":""));
  $("#ranking-note").hidden=!$("#ranking-note").textContent;
  const total=currentPapers.length;
  $("#metadata-coverage").textContent=`\u8457\u8005 ${fmt(authored)}/${fmt(total)} \u00b7 \u8981\u65e8 ${fmt(abstracted)}/${fmt(total)}`;
  $("#metadata-coverage").title=`\u3053\u306e\u6708\u30fb\u7814\u7a76\u9818\u57df\u306e\u4fdd\u5b58\u4ef6\u6570\uff1a\u30bf\u30a4\u30c8\u30eb ${titled}\u672c\u3001\u8457\u8005 ${authored}\u672c\u3001\u8981\u65e8 ${abstracted}\u672c\u3002\u672a\u4fdd\u5b58\u306e\u6b04\u306f\u691c\u7d22\u5bfe\u8c61\u5916\u3067\u3059\u3002`;
  let papers=currentPapers.filter(p=>queryMatches(p,query,state.paperField)).map(p=>({...p,matches:paperKeywordMatches(p,terms)}));
  const newest=(a,b)=>b.created-a.created||a.id.localeCompare(b.id);
  papers.sort(state.sort==="match"?(a,b)=>b.matches.length-a.matches.length||newest(a,b):newest);
  $("#papers-count").textContent=query.length?`${papers.length} / ${total} papers`:`${total} papers`;
  $("#papers-list").innerHTML=papers.slice(0,state.paperLimit).map((p,i)=>{
    const demo=D.mode==="demo",dt=new Date(p.created*1000).toISOString();
    const href=demo?"https://arxiv.org/list/"+encodeURIComponent(state.drawer)+"/recent":"https://arxiv.org/abs/"+p.id;
    const hits=hitFields(p,query);
    return `<article class="paper-row"><div class="paper-row-top"><span class="paper-rank"><b>${String(i+1).padStart(2,"0")}</b><span>${esc(p.id)}</span>${demo?'<span class="demo-paper-badge">DEMO</span>':""}</span><time datetime="${dt}">${dateText(dt)}</time></div>
      <h4><a class="paper-title-link" href="${esc(href)}" target="_blank" rel="noopener noreferrer">${highlight(p.title||"arXiv:"+p.id,query)}</a></h4>${authorsHTML(p,query)}
      <div class="paper-meta"><span class="paper-tags">${(p.title||p.abstract)&&terms.length?`<span class="match-pill">${p.matches.length} / ${terms.length} \u30ad\u30fc\u30ef\u30fc\u30c9</span>`:""}${hits.length?`<span class="search-hit">${hits.join("\u30fb")}\u306b\u4e00\u81f4</span>`:""}</span><a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${demo?"arXiv / \u65b0\u7740":"arXiv"} \u2197</a></div>
      ${p.matches.length?`<div class="matched-terms">${p.matches.map(t=>`<span>${esc(t)}</span>`).join("")}</div>`:""}
      ${p.abstract?`<details class="paper-abstract"><summary>\u8981\u65e8<span>\u4fdd\u5b58\u6e08\u307f</span></summary><p>${highlight(p.abstract,query)}</p></details>`:""}</article>`;
  }).join("")||`<div class="empty-state"><span>${query.length?"\u4fdd\u5b58\u6e08\u307f\u306e\u60c5\u5831\u306b\u306f\u4e00\u81f4\u306a\u3057":"\u3053\u306e\u6708\u306e\u6295\u7a3f\u306f\u3042\u308a\u307e\u305b\u3093"}</span></div>`;
  $("#load-more").hidden=papers.length<=state.paperLimit;
  $("#load-more").textContent=`\u3055\u3089\u306b\u8868\u793a \u00b7 \u6b8b\u308a ${Math.max(0,papers.length-state.paperLimit)}\u672c`;
}

function closeDrawer() {
  if(!state.drawer)return;
  ++paperRequest;state.drawer=null;
  $("#paper-drawer").hidden=true;$("#drawer-backdrop").hidden=true;
  document.body.style.overflow="";$("#main").inert=false;$("#sidebar").inert=false;
  const target=previousFocus;previousFocus=null;
  if(target?.isConnected)target.focus({preventScroll:true});else $("#category-search").focus({preventScroll:true});
  hideHover();
}
function toggleWatch() {
  const id=state.drawer;if(!id)return;
  const had=state.watch.has(id);if(had)state.watch.delete(id);else state.watch.add(id);
  save("watch",[...state.watch]);$("#drawer-watch").textContent=had?"☆":"★";
  $("#drawer-watch").setAttribute("aria-label",had?"ウォッチリストに追加":"ウォッチリストから削除");
  render();toast(had?"ウォッチリストから外しました":"ウォッチリストに保存しました");
}
function exportCSV() {
  const quote=v=>'"'+String(v??"").replaceAll('"','""')+'"';
  const rows=[["data_mode","month_start_UTC","month_end_inclusive_UTC","as_of_UTC","category","name","papers","current_comparable","previous_comparable","change_percent","comparison"]];
  visibleCats().forEach(c=>{
    const d=change(comparable(c),reference(c));
    rows.push([D.mode,D.monthStarts[state.month],endDay(D.monthStarts[state.month]),D.asOf,c.id,c.name,count(c),comparable(c),reference(c),d===Infinity?"NEW":d===null?"":d.toFixed(4),currentPartial()?"previous_month_same_elapsed_period":"previous_full_month"]);
  });
  const blob=new Blob(["\ufeff"+rows.map(row=>row.map(quote).join(",")).join("\r\n")],{type:"text/csv;charset=utf-8"});
  const url=URL.createObjectURL(blob),a=document.createElement("a");
  a.href=url;a.download=`physics-pulse-lite-${D.mode}-${D.monthStarts[state.month]}-${state.group}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
  toast(D.mode==="demo"?"サンプルデータのCSVを保存しました":"表示中の集計をCSVに保存しました");
}
function closeSidebar() {
  $("#sidebar").classList.remove("open");$("#sidebar-shade").classList.remove("open");
}
function showMethod() {hideHover();$("#method-dialog").showModal();}
function bind() {

  $("#month-select").onchange=e=>setMonth(+e.target.value);
  $$("[data-range]").forEach(b=>b.onclick=()=>{state.range=+b.dataset.range;save("chart-range",state.range);hideHover();refreshCharts();});
  $$("[data-scale]").forEach(b=>b.onclick=()=>{state.scale=b.dataset.scale;save("chart-scale",state.scale);hideHover();refreshCharts();});
  $$("[data-provisional]").forEach(b=>b.onclick=()=>{state.provisional=!state.provisional;save("chart-provisional",state.provisional);hideHover();refreshCharts();});
  $("#current-month").onclick=()=>setMonth(D.currentMonthIndex);
  $("#complete-month").onclick=()=>setMonth(D.latestCompleteMonthIndex);
  $("#interest-input").oninput=e=>{state.interests=e.target.value;save("interests",state.interests);state.sort=interestTerms(state.interests).length?"match":"newest";state.paperLimit=25;renderPapers();};
  $("#prev-month").onclick=()=>setMonth(state.month-1);
  $("#next-month").onclick=()=>setMonth(state.month+1);
  $("#watch-nav").onclick=()=>setGroup("watch");
  $(".brand").onclick=e=>{e.preventDefault();setGroup("all");};
  $("#category-search").oninput=e=>{state.query=e.target.value;render();};
  $("#map-view").onclick=()=>{state.view="map";render();};
  $("#table-view").onclick=()=>{state.view="table";hideHover();render();};
  $("#palette-toggle").onclick=()=>{state.palette=!state.palette;save("palette",state.palette);render();if(state.drawer)openDrawer(state.drawer,false);};
  $("#export-csv").onclick=exportCSV;

  $("#drawer-close").onclick=closeDrawer;$("#drawer-backdrop").onclick=closeDrawer;
  $("#drawer-watch").onclick=toggleWatch;
  $("#search-field").onchange=e=>{state.paperField=e.target.value;state.paperLimit=25;renderPapers();};
  $("#paper-search").oninput=e=>{state.paperQuery=e.target.value;state.paperLimit=25;renderPapers();};
  $$("[data-sort]").forEach(b=>b.onclick=()=>{state.sort=b.dataset.sort;state.paperLimit=25;renderPapers();});
  $("#load-more").onclick=()=>{state.paperLimit+=25;renderPapers();};
  $("#method-close").onclick=()=>$("#method-dialog").close();
  $("#method-dialog").addEventListener("click",e=>{if(e.target===$("#method-dialog")){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
  document.addEventListener("click",e=>{if(e.target.closest('[data-action="method"]'))showMethod();});
  $("#mobile-menu").onclick=()=>{$("#sidebar").classList.add("open");$("#sidebar-shade").classList.add("open");};
  $("#sidebar-shade").onclick=closeSidebar;
  document.addEventListener("keydown",e=>{
    const inInput=/INPUT|TEXTAREA|SELECT/.test(e.target.tagName);
    if(e.key==="Escape") {
      hideHover();
      if($("#method-dialog").open)return;
      if(state.drawer)closeDrawer();else closeSidebar();
    }
    if(e.key==="/"&&!inInput&&!state.drawer&&!$("#method-dialog").open){e.preventDefault();$("#category-search").focus();}
    if(e.key.toLowerCase()==="p"&&!inInput&&!state.drawer&&!$("#method-dialog").open)setGroup("all");
    if(e.key==="Tab"&&state.drawer&&!$("#method-dialog").open) {
      const focusable=$$('button:not([disabled]),a[href],input,select,summary,[tabindex="0"]',$("#paper-drawer")).filter(el=>el.offsetParent!==null);
      const first=focusable[0],last=focusable.at(-1);
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
      if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
    }
  });
  window.addEventListener("resize",()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{hideHover();render();if(state.drawer){const s=chartSeries([catOf(state.drawer)]);renderChart($("#drawer-chart"),s.values,s.dates,{partial:true,interactive:true});}},140);});
}
async function hydrate() {
  if(!/^https?:$/.test(location.protocol))return;
  try {
    const response=await fetch("data/physics.json",{cache:"no-store"});
    if(!response.ok)throw Error("Snapshot not connected.");
    const newData=validateData(await response.json());
    if(JSON.stringify(newData)===JSON.stringify(D))return;
    const oldMonth=D.monthStarts[state.month],wasDemo=D.mode==="demo";
    D=newData;paperCache.clear();
    state.month=((wasDemo&&D.mode==="live")||state.followCurrent)?D.defaultMonthIndex:D.monthStarts.indexOf(oldMonth);
    if(state.month<0||state.month>=D.monthStarts.length)state.month=D.defaultMonthIndex;
    if(!["all","watch"].includes(state.group)&&!groupOf(state.group))state.group="all";
    populateNavigation();renderStatus();render();
    if(state.drawer)openDrawer(state.drawer,false);
  } catch(error) {
    // Keep the last valid embedded snapshot; never convert missing records to zero.
    console.info("Physics Pulse Lite: using the embedded, explicitly labeled snapshot.",error.message);
    if(D.mode==="live") {
      $("#data-notice").hidden=false;$("#data-notice").innerHTML='<span class="notice-label">OFFLINE</span><span>\u4fdd\u5b58\u6e08\u307f\u30b9\u30ca\u30c3\u30d7\u30b7\u30e7\u30c3\u30c8\u3092\u8868\u793a\u4e2d</span>';
    }
  }
}
validateData(D);readHash();populateNavigation();renderStatus();bind();render();hydrate();
window.PulseMath={squarify,change,validateData,momentum,interestTerms,keywordMatches,searchTerms,queryMatches,paperKeywordMatches,normalizeSearch,highlight,chartDomain,chartWindow};
window.PulseTest={getState:()=>({...state,watch:[...state.watch]}),getData:()=>D,setMonth,setGroup,openDrawer,closeDrawer};
})();
