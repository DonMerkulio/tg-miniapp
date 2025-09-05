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

function card(sh){
  const c = el('div',{class:'ship-card '+(sh.track_no ? 'green':'red'), 'data-id': sh.id});
  const left = el('div',{},
    el('div',{class:'title'}, `${sh.category} • ${sh.articles}`),
    el('div',{class:'meta'}, `Склад: ${sh.warehouse} • ТК: ${sh.carrier} • Город: ${sh.city} • На клиента: ${sh.prepay?'Да':'Нет'}`),
    sh.track_no ? el('div',{class:'meta'}, `Трек: ${esc(sh.track_no)}`) : el('div',{class:'meta'}, `Трек: —`)
  );
  const right = el('div',{class:'actions'},
    el('button',{class:'btn sm', title:'Пометить отправлено', 'data-act':'sent', 'data-id': sh.id}, '✓')
  );
  c.append(left, right);
  return c;
}

async function load(){
  const wh = document.querySelector('input[name="wh"]:checked')?.value || "";
  const q = new URLSearchParams({ init_data: init });
  if (wh) q.set("warehouse", wh);
  const data = await get("/api/shipments?"+q.toString());
  list.innerHTML = "";
  data.items.forEach(it=> list.appendChild(card(it)));
}

list.addEventListener("click", async (e)=>{
  const item = e.target.closest(".ship-card[data-id]");
  if (item && !e.target.closest('button[data-act]')){
    const id = item.getAttribute("data-id");
    const sh = await get(`/api/shipments/${id}?init_data=${encodeURIComponent(init)}`);
    openDetail(sh);
    return;
  }
  const sentBtn = e.target.closest('button[data-act="sent"]');
  if (sentBtn){
    const id = sentBtn.getAttribute("data-id");
    await post(`/api/shipments/${id}/mark_sent`, { init_data: init });
    await load();
  }
});

function openDetail(sh){
  detailCard.innerHTML = `
  <div class="detail-body">
    <h3 class="detail-title">Заявка #${sh.id}</h3>

    <div class="detail-row"><span class="detail-label">Категория:</span><input class="search" id="fCategory" value="${escAttr(sh.category)}"></div>
    <div class="detail-row"><span class="detail-label">Артикул(а):</span><input class="search" id="fArticles" value="${escAttr(sh.articles)}"></div>
    <div class="detail-row"><span class="detail-label">Склад:</span>
      <select id="fWarehouse" class="select">
        <option value="москва" ${sh.warehouse==='москва'?'selected':''}>Москва</option>
        <option value="озеро" ${sh.warehouse==='озеро'?'selected':''}>Озеро</option>
      </select>
    </div>
    <div class="detail-row"><span class="detail-label">ТК:</span><input class="search" id="fCarrier" value="${escAttr(sh.carrier)}"></div>
    <div class="detail-row"><span class="detail-label">Город:</span><input class="search" id="fCity" value="${escAttr(sh.city)}"></div>
    <div class="detail-row"><span class="detail-label">Клиент:</span><input class="search" id="fClient" value="${escAttr(sh.client_info)}"></div>

    <div class="detail-row"><span class="detail-label">Отправка на клиента:</span>
      <label class="switch"><input type="checkbox" id="fPrepay" ${sh.prepay?'checked':''}><span class="track"></span><span class="knob"></span></label>
    </div>

    <div class="detail-row"><span class="detail-label">Трек:</span><input class="search" id="fTrack" value="${escAttr(sh.track_no)}" placeholder="Укажите трек"/></div>

    <div class="detail-actions">
      <button id="btnSave" class="btn sm">Сохранить</button>
      <button id="btnDel" class="btn sm">Удалить</button>
      <button id="btnClose" class="btn sm">Закрыть</button>
    </div>
  </div>`;
  detail.classList.remove("hidden");

  document.getElementById("btnClose").onclick = ()=> detail.classList.add("hidden");
  document.getElementById("btnDel").onclick = async ()=>{
    await fetch(`/api/shipments/${sh.id}`, {method:"DELETE", headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ init_data: init })
    });
    await load(); detail.classList.add("hidden");
  };

  document.getElementById("btnSave").onclick = async ()=>{
    const payload = {
      category: document.getElementById("fCategory").value.trim(),
      articles: document.getElementById("fArticles").value.trim(),
      warehouse: document.getElementById("fWarehouse").value,
      carrier: document.getElementById("fCarrier").value.trim(),
      city: document.getElementById("fCity").value.trim(),
      client_info: document.getElementById("fClient").value.trim(),
      prepay: document.getElementById("fPrepay").checked,
      track_no: document.getElementById("fTrack").value.trim(),
    };
    const before = sh;
    const res = await fetch(`/api/shipments/${sh.id}`, {method:"PATCH", headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ init_data: init, payload })
    }).then(r=>r.json());
    if (res && res.item) sh = res.item;
    await load(); detail.classList.add("hidden");
  };
}

document.querySelectorAll('input[name="wh"]').forEach(r=> r.addEventListener("change", load));
load().catch(console.error);
