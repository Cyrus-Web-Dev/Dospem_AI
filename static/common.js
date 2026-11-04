/* Dospem · utilitas bersama. Dimuat di <head> agar tema terpasang sebelum halaman digambar. */
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const store={get:k=>{try{return localStorage.getItem(k)}catch{return null}},set:(k,v)=>{try{localStorage.setItem(k,v)}catch{}},del:k=>{try{localStorage.removeItem(k)}catch{}}};
(()=>{const t=store.get('theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t})();
function toggleTheme(){const r=document.documentElement,dark=r.dataset.theme?r.dataset.theme==='dark':matchMedia('(prefers-color-scheme:dark)').matches;
  r.dataset.theme=dark?'light':'dark';store.set('theme',r.dataset.theme)}
const H={'Content-Type':'application/json'};if(store.get('tok'))H.Authorization='Bearer '+store.get('tok');
/* prefix mis. '/api' atau '/api/admin'; denied = pesan bila 401/403 */
function mkApi(prefix,denied){return async(p,o={})=>{let r;try{r=await fetch(prefix+p,{headers:H,...o})}catch{const e=new Error('Tidak dapat terhubung ke server. Periksa koneksi lalu coba lagi.');e.status=0;throw e}
  const j=await r.json().catch(()=>({}));if(!r.ok){const e=new Error((r.status===401||r.status===403)&&denied?denied:typeof j.detail==='string'?j.detail:Array.isArray(j.detail)?'Isian belum valid. Periksa kembali.':'Terjadi kesalahan');e.status=r.status;throw e}return j}}
const utc=iso=>new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso)?iso:iso+'Z');
const fmtDate=iso=>utc(iso).toLocaleDateString('id-ID',{day:'numeric',month:'short',year:'numeric'});
const fmtDateTime=iso=>utc(iso).toLocaleString('id-ID',{day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'});
const rp=n=>'Rp '+Number(n||0).toLocaleString('id-ID');
/* ---- komponen analitik (admin & dosen) ---- */
const MON=['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des'];
const dm=s=>`${+s.slice(8,10)} ${MON[+s.slice(5,7)-1]}`;
const pct=x=>x==null?'–':Math.round(x*100)+'%';
function bars(v,l){const m=Math.max(1,...v);return `<div class="chart" role="img" aria-label="Grafik batang ${esc(dm(l[0]))} sampai ${esc(dm(l[l.length-1]))}">${v.map((n,i)=>
  `<div class="col" title="${esc(dm(l[i]))}: ${n}"><span class="val">${n||''}</span><div class="plot"><div class="bar" style="height:${Math.round(n/m*100)}%"></div></div><span class="lab">${+l[i].slice(8,10)}</span></div>`).join('')}</div>
  <div class="axis">${esc(dm(l[0]))} – ${esc(dm(l[l.length-1]))} · total ${v.reduce((a,b)=>a+b,0)}</div>`}
function chTable(cs){return cs.length?`<div class="scroll-x"><table><thead><tr><th>Bab</th><th>Mahasiswa</th><th>Selesai</th><th>Median kata</th><th>Kesalahan/100 kata</th></tr></thead><tbody>${cs.map(c=>`<tr><td>${esc(c.doc_label||c.doc_type)} · ${esc(c.title)}</td><td>${c.students}</td><td>${pct(c.completion_rate)}</td><td>${c.median_words}</td><td>${c.issues_per_100w??'–'}</td></tr>`).join('')}</tbody></table></div>`:'<p class="empty">Belum ada draf.</p>'}
function issueList(r){const m=Math.max(1,...r.top_issues.map(i=>i.count));return r.top_issues.length?r.top_issues.map(i=>`<div class="irow"><span>${esc(i.label)}</span><div class="ibar"><i style="width:${Math.round(i.count/m*100)}%"></i></div><span>${i.count}</span></div>`).join(''):'<p class="empty">Tidak ada temuan ejaan.</p>'}
function statCards(a){return `<div class="stats">${a.map(([k,v])=>`<div class="card stat"><small>${esc(k)}</small><b>${esc(v)}</b></div>`).join('')}</div>`}
function contentCards(r){return (r.hardest?`<div class="card"><h3>Bab paling sulit diselesaikan</h3><small>${esc(r.hardest.doc_label||r.hardest.doc_type)} · ${esc(r.hardest.title)} — hanya ${pct(r.hardest.completion_rate)} dari ${r.hardest.students} mahasiswa yang mencapai status terisi.</small></div>`:'')
  +`<div class="card"><h3>Kemajuan per bab</h3>${chTable(r.chapters)}</div><div class="card"><h3>Kesalahan paling sering</h3>${issueList(r)}</div>`
  +`<div class="card"><h3>Kata tidak baku paling sering</h3>${r.top_words.map(w=>`<div>${esc(w.word)} → ${esc(w.suggestion)} <small class="inl">(${w.count}×)</small></div>`).join('')||'<small>Tidak ada.</small>'}</div>`
  +`<small class="muted">Berdasarkan ${r.sampled.drafts} draf terbaru${r.sampled.capped?' (dibatasi)':''}; ejaan diperiksa pada ${r.sampled.checked} draf.</small>`}
const safeUrl=u=>/^https?:\/\//i.test(u||'')?u:'#';
