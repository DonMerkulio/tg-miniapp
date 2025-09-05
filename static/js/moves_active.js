function tgInit(){
  const tg = window.Telegram?.WebApp;
  if (!tg || !tg.initData) throw new Error("open inside Telegram");
  tg.ready(); return tg.initData;
}
async function get(url){ const r=await fetch(url,{cache:"no-store"}); if(!r.ok) throw new Error(await r.text()); return r.json(); }
async function post(url,data){ const r=await fetch(url,{method:"POST",headers:{'Content-Type':'application/json'},body:JSON.stringify(data||{})}); if(!r.ok) throw new Error(await r.text()); return r.json(); }

const init = tgInit();
const list = document.getElementById("list");
const detail = document.getElementById("detail");
const detailCard = document.getElementById("detailCard");

function el(tag, attrs={}, ...kids){
  const n = document.createElement(tag);
  Object.entries(attrs).forEach(([k,v])=> n.setAttribute(k, v));
  kids.flat().forEach(k=> n.append(k instanceof Node ? k : document.createTextNode(k)));
  return n;
}
function esc(s){ return (s||"").replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); }
function escAttr(s){ return esc(s); }
function capWh(v){ return (v||"").toLowerCase()==="москва"?"Москва":"Озеро"; }
function ageDays(iso){ const d=new Date(iso).getTime(); return Math.floor((Date.now()-d)/86400000); }

function card(m){
  const age = ageDays(m.created_at);
  const cls = age>5 ? 'red' : 'green';
  const c = el('div',{class:'ship-card '+cls, 'data-id': m.id});
  const left = el('div',{},
    el('div',{class:'title'}, `${m.part} • ${m.articles}`),
    el('div',{class:'meta'}, `Маршрут: ${capWh(m.from_wh)} → ${capWh(m.to_wh)} • Создано: ${new Date(m.created_at).toLocaleString()}`),
    el('div',{class:'meta'}, `Возраст: ${age} дн.`)
  );
  const right = el('div',{class:'actions'},
    el('button',{class:'btn sm', title:'Отметить завершено','data-act':'done','data-id': m.id}, '✓')
  );
  c.append(left, right);
  return c;
}

async function load(){
  const to = document.querySelector('input[name="to"]:checked')?.value || "";
  const q = new URLSearchParams({ init_data: init });
  if (to) q.set("to", to);
  const data = await get("/api/moves?"+q.toString());
  list.innerHTML = "";
  data.items.forEach(it=> list.appendChild(card(it)));
}

list.addEventListener("click", async (e)=>{
  const item = e.target.closest(".ship-card[data-id]");
  if (item && !e.target.closest('button[data-act]')){
    const id = item.getAttribute("data-id");
    const m = await get(`/api/moves/${id}?init_data=${encodeURIComponent(init)}`);
    openDetail(m);
    return;
  }
  const doneBtn = e.target.closest('button[data-act="done"]');
  if (doneBtn){
    const id = doneBtn.getAttribute("data-id");
    await post(`/api/moves/${id}/mark_done`, { init_data: init });
    await load();
  }
});

function openDetail(m){
  detailCard.innerHTML = `
  <div class="detail-body">
    <h3 class="detail-title">Перемещение #${m.id}</h3>

    <div class="detail-row"><span class="detail-label">Запчасть:</span><input class="search" id="fPart" value="${escAttr(m.part)}"></div>
    <div class="detail-row"><span class="detail-label">Артикул(а):</span><input class="search" id="fArticles" value="${escAttr(m.articles)}"></div>

    <div class="detail-row"><span class="detail-label">Маршрут:</span>
      <select id="fRoute" class="select">
        <option value="озеро-москва" ${(m.from_wh==='озеро'&&m.to_wh==='москва')?'selected':''}>Озеро → Москва</option>
        <option value="москва-озеро" ${(m.from_wh==='москва'&&m.to_wh==='озеро')?'selected':''}>Москва → Озеро</option>
      </select>
    </div>

    <div class="detail-actions">
      <button id="btnSave" class="btn sm">Сохранить</button>
      <button id="btnDel" class="btn sm">Удалить</button>
      <button id="btnClose" class="btn sm">Закрыть</button>
    </div>
  </div>`;
  detail.classList.remove("hidden");

  document.getElementById("btnClose").onclick = ()=> detail.classList.add("hidden");
  document.getElementById("btnDel").onclick = async ()=>{
    await fetch(`/api/moves/${m.id}`, {method:"DELETE", headers:{'Content-Type':'application/json'}, body: JSON.stringify({ init_data: init })});
    await load(); detail.classList.add("hidden");
  };
  document.getElementById("btnSave").onclick = async ()=>{
    const route = document.getElementById("fRoute").value;
    const payload = {
      part: document.getElementById("fPart").value.trim(),
      articles: document.getElementById("fArticles").value.trim(),
      route
    };
    await fetch(`/api/moves/${m.id}`, {method:"PATCH", headers:{'Content-Type':'application/json'}, body: JSON.stringify({ init_data: init, payload })}).then(r=>r.json());
    await load(); detail.classList.add("hidden");
  };
}

document.querySelectorAll('input[name="to"]').forEach(r=> r.addEventListener("change", load));
load().catch(console.error);
