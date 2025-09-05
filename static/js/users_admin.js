function tgInit(){ const tg = window.Telegram?.WebApp; if(!tg||!tg.initData) throw new Error("open inside Telegram"); tg.ready(); return tg.initData; }
async function get(url){ const r=await fetch(url,{cache:"no-store"}); if(!r.ok) throw new Error(await r.text()); return r.json(); }
async function post(url,data){ const r=await fetch(url,{method:"POST",headers:{'Content-Type':'application/json'},body:JSON.stringify(data||{})}); if(!r.ok) throw new Error(await r.text()); return r.json(); }
function showBusy(msg){ const b=document.getElementById('busy'); if(!b) return; const t=document.getElementById('busyText'); if(t) t.textContent=msg||'Загружаю…'; b.classList.add('show'); }
function hideBusy(){ document.getElementById('busy')?.classList.remove('show'); }
function esc(s){ return (s||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); }
function escAttr(s){ return esc(s); }

const init = tgInit();
const list = document.getElementById("usersList");
const detail = document.getElementById("detail");
const detailCard = document.getElementById("detailCard");
const qInput = document.getElementById("q");

function chip(label, on, kind){
  const span = document.createElement('span');
  span.className = 'chip bool ' + (kind==='red' ? 'red' : (on ? 'on':'off'));
  span.textContent = label + (on===true||on===false ? (on?'':'') : '');
  return span;
}

function card(u){
  const c = document.createElement('div');
  c.className = 'user-card'; c.setAttribute('data-id', String(u.id));
  const title = document.createElement('div'); title.className='title'; title.textContent = u.name || ('id:'+u.tg_id);
  const meta1 = document.createElement('div'); meta1.className='meta'; meta1.textContent = [u.phone,u.city,u.role].filter(Boolean).join(' • ');
  const meta2 = document.createElement('div'); meta2.className='meta'; meta2.textContent = 'Зарегистрирован: ' + new Date(u.created_at).toLocaleString();
  const chips = document.createElement('div'); chips.className='chips';
  chips.append(chip('Админ', !!u.is_admin), chip('Уведомления', !!u.notifications), chip('Заблокирован', !!u.is_blocked, u.is_blocked?'red':null));
  c.append(title, meta1, meta2, chips);
  return c;
}

async function load(){
  showBusy("Загружаю пользователей…");
  try{
    const qs = new URLSearchParams({ init_data: init });
    const q = (qInput.value||"").trim(); if (q) qs.set("q", q);
    const data = await get("/api/users?"+qs.toString());
    list.innerHTML = "";
    data.items.forEach(u=> list.appendChild(card(u)));
  }finally{ hideBusy(); }
}

list.addEventListener("click", async (e)=>{
  const item = e.target.closest(".user-card[data-id]");
  if (!item) return;
  const id = item.getAttribute("data-id");
  const u = await get(`/api/users/${id}?init_data=${encodeURIComponent(init)}`);
  openDetail(u);
});

function openDetail(u){
  detailCard.innerHTML = `
  <div class="detail-body">
    <h3 class="detail-title">Пользователь #${u.id}</h3>

    <div class="detail-row"><span class="detail-label">Имя:</span><input class="search" id="fName" value="${escAttr(u.name||"")}"></div>
    <div class="detail-row"><span class="detail-label">Город:</span><input class="search" id="fCity" value="${escAttr(u.city||"")}"></div>
    <div class="detail-row"><span class="detail-label">Телефон:</span><input class="search" id="fPhone" value="${escAttr(u.phone||"")}"></div>
    <div class="detail-row"><span class="detail-label">Роль:</span>
      <select id="fRole" class="select">
        <option value="СТО" ${u.role==='СТО'?'selected':''}>СТО</option>
        <option value="Авторазбор" ${u.role==='Авторазбор'?'selected':''}>Авторазбор</option>
        <option value="Частный клиент" ${u.role==='Частный клиент'?'selected':''}>Частный клиент</option>
        <option value="${escAttr(u.role||'')}" ${u.role&&['СТО','Авторазбор','Частный клиент'].indexOf(u.role)===-1?'selected':''}>${esc(u.role||'Другое')}</option>
      </select>
    </div>

    <div class="detail-row"><span class="detail-label">TG:</span>
      <a class="btn sm" href="tg://user?id=${encodeURIComponent(u.tg_id)}" target="_blank" rel="noopener">Открыть чат</a>
      <span class="meta" style="margin-left:8px;color:#6e6e73">id: ${esc(u.tg_id)}</span>
    </div>

    <div class="detail-row"><span class="detail-label">Уведомления:</span>
      <label class="switch"><input type="checkbox" id="fNotif" ${u.notifications?'checked':''}><span class="track"></span><span class="knob"></span></label>
    </div>
    <div class="detail-row"><span class="detail-label">Админ:</span>
      <label class="switch"><input type="checkbox" id="fAdmin" ${u.is_admin?'checked':''}><span class="track"></span><span class="knob"></span></label>
    </div>
    <div class="detail-row"><span class="detail-label">Заблокирован:</span>
      <label class="switch"><input type="checkbox" id="fBlocked" ${u.is_blocked?'checked':''}><span class="track"></span><span class="knob"></span></label>
    </div>

    <div class="detail-actions">
      <button id="btnSave" class="btn sm">Сохранить</button>
      <button id="btnClose" class="btn sm">Закрыть</button>
    </div>
  </div>`;
  detail.classList.remove("hidden");
  document.getElementById("btnClose").onclick = ()=> detail.classList.add("hidden");
  document.getElementById("btnSave").onclick = async ()=>{
    const payload = {
      name: document.getElementById("fName").value.trim(),
      city: document.getElementById("fCity").value.trim(),
      phone: document.getElementById("fPhone").value.trim(),
      role: document.getElementById("fRole").value,
      notifications: document.getElementById("fNotif").checked,
      is_admin: document.getElementById("fAdmin").checked,
      is_blocked: document.getElementById("fBlocked").checked,
    };
    showBusy("Сохраняю…");
    try{
      await fetch(`/api/users/${u.id}`, {method:"PATCH", headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ init_data: init, payload })
      }).then(r=>r.json());
      await load();
      detail.classList.add("hidden");
    }finally{ hideBusy(); }
  };
}

function debounce(fn,ms){ let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a),ms); }; }
qInput.addEventListener("input", debounce(load, 250));

load().catch(e=>{ console.error(e); });
