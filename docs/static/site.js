(function(){
var tb=document.querySelector('.theme-toggle');
if(tb) tb.addEventListener('click',function(){var r=document.documentElement;var cur=r.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');var nx=cur==='dark'?'light':'dark';r.setAttribute('data-theme',nx);try{localStorage.setItem('theme',nx);}catch(e){}});
// search over /search-index.json
var idx=null,loading=null;
function load(){if(idx)return Promise.resolve(idx);if(!loading)loading=fetch('/search-index.json').then(function(r){return r.json()}).then(function(d){idx=d;return d});return loading;}
function norm(s){return (s||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]});}
function score(it,terms){var h=' '+norm(it.t+' '+(it.k||''))+' ';var s=0;for(var i=0;i<terms.length;i++){if(h.indexOf(terms[i])<0)return 0;s+=h.indexOf(' '+terms[i]+' ')>=0?3:1;if(norm(it.t).indexOf(terms[i])===0)s+=2;}return s-it.t.length/1000;}
document.querySelectorAll('.search-input').forEach(function(inp){
 var box=inp.parentNode.querySelector('.search-results'),sel=-1;
 function render(list){sel=-1;if(!list.length){box.innerHTML='<div class="sr-empty">No matches</div>';box.hidden=false;return;}
  box.innerHTML=list.map(function(r){return '<a href="'+r.u+'">'+esc(r.t)+(r.d?'<span>'+esc(r.d)+'</span>':'')+'</a>';}).join('');box.hidden=false;}
 inp.addEventListener('input',function(){var q=norm(inp.value);if(q.length<2){box.hidden=true;return;}
  load().then(function(d){var terms=q.split(' ').filter(function(t){return t&&t!=='vs'&&t!=='in'&&t!=='high'&&t!=='foods'});if(!terms.length){box.hidden=true;return;}var out=[];for(var i=0;i<d.length;i++){var s=score(d[i],terms);if(s>0)out.push([s,d[i]]);}
   out.sort(function(a,b){return b[0]-a[0]});render(out.slice(0,10).map(function(x){return x[1]}));});});
 inp.addEventListener('keydown',function(e){var ls=box.querySelectorAll('a');if(!ls.length)return;
  if(e.key==='ArrowDown'){sel=Math.min(sel+1,ls.length-1);e.preventDefault();}
  else if(e.key==='ArrowUp'){sel=Math.max(sel-1,0);e.preventDefault();}
  else if(e.key==='Enter'){location.href=ls[sel>=0?sel:0].getAttribute('href');e.preventDefault();return;}
  else if(e.key==='Escape'){box.hidden=true;return;}else return;
  ls.forEach(function(a,i){a.classList.toggle('active',i===sel)});});
 document.addEventListener('click',function(e){if(!inp.parentNode.contains(e.target))box.hidden=true;});
 var q=new URLSearchParams(location.search).get('q');if(q&&inp.closest('.hero-search')){inp.value=q;inp.dispatchEvent(new Event('input'));}
});
// sortable tables
document.querySelectorAll('table.sortable').forEach(function(t){
 var ths=t.querySelectorAll('thead th');
 ths.forEach(function(th,col){if(th.dataset.nosort!==undefined)return;th.tabIndex=0;th.setAttribute('aria-sort','none');
  function go(){var asc=th.getAttribute('aria-sort')!=='ascending';ths.forEach(function(o){o.setAttribute('aria-sort','none')});th.setAttribute('aria-sort',asc?'ascending':'descending');
   var num=th.dataset.sort==='num',body=t.tBodies[0],rows=Array.prototype.slice.call(body.rows);
   rows.sort(function(a,b){var x=a.cells[col],y=b.cells[col];var vx=x.dataset.v!==undefined?x.dataset.v:x.textContent.trim(),vy=y.dataset.v!==undefined?y.dataset.v:y.textContent.trim();
    if(num){vx=parseFloat(vx)||0;vy=parseFloat(vy)||0;return asc?vx-vy:vy-vx;}
    return asc?String(vx).localeCompare(vy,undefined,{numeric:true}):String(vy).localeCompare(vx,undefined,{numeric:true});});
   rows.forEach(function(r){body.appendChild(r)});}
  th.addEventListener('click',go);th.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();go();}});});
});
// table filters
function applyFilter(id){var t=document.getElementById(id);if(!t)return;var f=document.querySelector('.table-filter[data-table="'+id+'"]'),c=document.querySelector('.table-cat[data-table="'+id+'"]');
 var q=f?f.value.toLowerCase():'',cat=c?c.value:'';Array.prototype.forEach.call(t.tBodies[0].rows,function(r){var txt=r.textContent.toLowerCase();var ok=(!q||txt.indexOf(q)>=0)&&(!cat||r.dataset.group===cat);r.hidden=!ok;});}
document.querySelectorAll('.table-filter,.table-cat').forEach(function(el){el.addEventListener('input',function(){applyFilter(el.dataset.table)});el.addEventListener('change',function(){applyFilter(el.dataset.table)});});
// serving tabs (pre-rendered panels)
document.querySelectorAll('.tabs').forEach(function(tabs){var btns=tabs.querySelectorAll('button');btns.forEach(function(b){b.addEventListener('click',function(){
 btns.forEach(function(o){o.setAttribute('aria-selected','false')});b.setAttribute('aria-selected','true');
 var grp=tabs.dataset.group;document.querySelectorAll('[data-tabpanel="'+grp+'"]').forEach(function(p){p.hidden=p.dataset.tab!==b.dataset.tab;});});});});
})();
