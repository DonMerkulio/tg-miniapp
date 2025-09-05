function tgInit() {
    const tg = window.Telegram?.WebApp;
    if (!tg || !tg.initData) throw new Error("open inside Telegram");
    tg.ready();
    return tg.initData;
}

async function get(url) {
    const r = await fetch(url, {cache: "no-store"});
    if (!r.ok) throw new Error(await r.text());
    return r.json();
}

async function post(url, data) {
    const r = await fetch(url, {
        method: "POST",
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data || {})
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
}

const init = tgInit();
const list = document.getElementById("list");
const form = document.getElementById("formNew");
const detail = document.getElementById("detail");
const detailCard = document.getElementById("detailCard");
document.getElementById("btnBack").onclick = () => history.back();

function el(tag, attrs = {}, ...kids) {
    const n = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
    kids.flat().forEach(k => n.append(k instanceof Node ? k : document.createTextNode(k)));
    return n;
}

function chip(v) {
    const b = el('span', {class: 'tag'}, v);
    return b;
}

function card(sh) {
    const c = el('div', {class: 'ship-card ' + (sh.track_no ? 'green' : 'red'), 'data-id': sh.id});
    const left = el('div', {},
        el('div', {class: 'title'}, `${sh.category} • ${sh.articles}`),
        el('div', {class: 'meta'}, `Склад: ${sh.warehouse} • ТК: ${sh.carrier} • Город: ${sh.city} • Предоплата: ${sh.prepay ? 'Да' : 'Нет'}`),
        el('div', {class: 'meta'}, `Клиент: ${sh.client_info}`),
        sh.track_no ? el('div', {class: 'meta'}, `Трек: ${sh.track_no}`) : el('div', {class: 'meta'}, `Трек: —`)
    );
    const right = el('div', {class: 'actions'},
        el('button', {class: 'btn sm', 'data-act': 'edit', 'data-id': sh.id}, 'Открыть'),
        el('button', {class: 'btn sm', 'data-act': 'sent', 'data-id': sh.id}, 'Отправлено')
    );
    c.append(left, right);
    return c;
}

async function load() {
    const wh = document.querySelector('input[name="wh"]:checked')?.value || "";
    const q = new URLSearchParams({init_data: init});
    if (wh) q.set("warehouse", wh);
    const data = await get("/api/shipments?" + q.toString());
    list.innerHTML = "";
    data.items.forEach(it => list.appendChild(card(it)));
}

form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const payload = {
        init_data: init,
        category: fd.get("category"), articles: fd.get("articles"),
        warehouse: fd.get("warehouse"),
        carrier: fd.get("carrier"), city: fd.get("city"),
        client_info: fd.get("client_info"),
        prepay: fd.get("prepay") === "1",
        track_no: fd.get("track_no") || ""
    };
    await post("/api/shipments", payload);
    form.reset();
    document.getElementById("wh_all").checked = true;
    await load();
    window.Telegram?.WebApp?.showAlert("Создано");
});

document.querySelectorAll('input[name="wh"]').forEach(r => {
    r.addEventListener("change", load);
});

list.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (btn) {
        const id = btn.getAttribute("data-id");
        const act = btn.getAttribute("data-act");
        if (act === "sent") {
            await post(`/api/shipments/${id}/mark_sent`, {init_data: init});
            await load();
            return;
        }
        if (act === "edit") {
            const sh = await get(`/api/shipments/${id}?init_data=${encodeURIComponent(init)}`);
            openDetail(sh);
            return;
        }
    }
});

function openDetail(sh) {
    detailCard.innerHTML = `
  <div class="detail-body">
    <h3 class="detail-title">Заявка #${sh.id}</h3>
    <div class="detail-row"><span class="detail-label">Категория:</span>${esc(sh.category)}</div>
    <div class="detail-row"><span class="detail-label">Артикул(а):</span>${esc(sh.articles)}</div>
    <div class="detail-row"><span class="detail-label">Склад:</span>${esc(sh.warehouse)}</div>
    <div class="detail-row"><span class="detail-label">ТК:</span>${esc(sh.carrier)}</div>
    <div class="detail-row"><span class="detail-label">Город:</span>${esc(sh.city)}</div>
    <div class="detail-row"><span class="detail-label">Клиент:</span>${esc(sh.client_info)}</div>
    <div class="detail-row"><span class="detail-label">Предоплата:</span>${sh.prepay ? 'Да' : 'Нет'}</div>
    <div class="detail-row"><span class="detail-label">Создано:</span>${new Date(sh.created_at).toLocaleString()}</div>
    <div class="detail-row"><span class="detail-label">Трек:</span><input id="fTrack" class="search" value="${escAttr(sh.track_no)}" placeholder="Укажите трек"/></div>
    <div class="detail-row"><span class="detail-label">Отправлено:</span>${sh.is_sent ? 'Да' : 'Нет'}</div>
    <div class="detail-actions">
      <button id="btnSave" class="btn sm">Сохранить</button>
      <button id="btnDel" class="btn sm">Удалить</button>
      <button id="btnClose" class="btn sm">Закрыть</button>
    </div>
  </div>`;
    detail.classList.remove("hidden");

    document.getElementById("btnClose").onclick = () => detail.classList.add("hidden");
    document.getElementById("btnSave").onclick = async () => {
        const track = document.getElementById("fTrack").value.trim();
        await fetch(`/api/shipments/${sh.id}`, {
            method: "PATCH", headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({init_data: init, payload: {track_no: track}})
        }).then(r => r.json());
        await load();
        detail.classList.add("hidden");
    };
    document.getElementById("btnDel").onclick = async () => {
        await fetch(`/api/shipments/${sh.id}`, {
            method: "DELETE", headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({init_data: init})
        });
        await load();
        detail.classList.add("hidden");
    };
}

function esc(s) {
    return (s || "").replace(/[&<>"']/g, c => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\"": "&quot;",
        "'": "&#39;"
    }[c]));
}

function escAttr(s) {
    return esc(s);
}

load().catch(console.error);
