import {initData} from "/static/js/core/tg.js";
import {showBusy, hideBusy} from "/static/js/core/busy.js";

function qs(s) {
    return document.querySelector(s);
}

function esc(s) {
    return (s || "").replace(/[&<>"']/g, c => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    }[c]));
}

function escAttr(s) {
    return esc(s);
}

function parseDate(s) {
    if (!s) return null;
    s = s.trim();
    const mIso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);         // YYYY-MM-DD
    if (mIso) return new Date(+mIso[1], +mIso[2] - 1, +mIso[3]);
    const mRu = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(s);       // DD.MM.YYYY
    if (mRu) return new Date(+mRu[3], +mRu[2] - 1, +mRu[1]);
    const t = Date.parse(s);
    return Number.isNaN(t) ? null : new Date(t);
}

function mskToday() {
    const now = new Date();
    const ms = now.getTime() + (now.getTimezoneOffset() + 180) * 60000; // UTC→MSK
    const d = new Date(ms);
    return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function parseYMD(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec((s || "").trim());
    return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
}


async function get(url) {
    const r = await fetch(url, {cache: "no-store"});
    if (!r.ok) throw new Error(await r.text());
    return r.json();
}

async function post(url, data, method = "POST") {
    const r = await fetch(url, {
        method, headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data || {})
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
}

const init = initData();
if (!init) {
    alert("Откройте в Telegram");
}

const adminsEl = qs("#admins");
const unknownBtn = qs("#btnUnknown");
const unknownCountEl = qs("#unknownCount");
const listEl = qs("#list");
const listTitle = qs("#listTitle");
const detail = qs("#detail");
const detailCard = qs("#detailCard");

async function loadAdmins() {
    showBusy("Загружаю админов…");
    try {
        const data = await get("/api/reserves/admins");
        adminsEl.innerHTML = "";
        (data.admins || []).forEach(a => {
            const card = document.createElement("div");
            card.className = "admin-card";
            card.innerHTML = `
        <div>
          <div class="title">${esc(a.name)} (${esc(a.tg_id)})</div>
          <div class="meta">Резервов: ${a.count}</div>
        </div>`;
            card.addEventListener("click", () =>
                loadList({admin: a.tg_id, title: `Резервы — ${a.name} (${a.tg_id})`})
            );
            adminsEl.appendChild(card);
        });
        unknownCountEl.textContent = data.unknown ? `Непонятные: ${data.unknown}` : "";
        unknownBtn.onclick = () => loadList({unknown: 1, title: "Резервы — Непонятные"});
    } finally {
        hideBusy();
    }
}


function reserveCard(it) {
    const wrap = document.createElement('div');
    wrap.className = 'res-card';

    const till = parseYMD(it.reserve_till);
    if (till) {
        const daysLeft = Math.floor((till - mskToday()) / 86400000);
        // резерву >3 дней (осталось ≤1 день при сроке 4 дня) → красный
        if (daysLeft <= 1) wrap.classList.add('red');
    }

    wrap.innerHTML = `
    <div class="title">${esc(it.brand)} ${esc(it.model)} • ${esc(it.part)}</div>
    <div class="meta">${esc(it.year || '')}</div>
    <div class="meta">Резерв до: ${it.reserve_till ? esc(it.reserve_till.split(' ')[0]) : '—'}</div>
    <div class="meta">Комментарий: ${it.comment ? esc(it.comment) : '—'}</div>
  `;
    return wrap;
}

async function loadList({admin = null, unknown = null, title = "Список резервов"} = {}) {
    listTitle.textContent = title;
    showBusy("Загружаю резервы…");
    try {
        const qsParams = new URLSearchParams();
        if (unknown) qsParams.set("admin", "_");          // без тега [admin: …]
        else if (admin) qsParams.set("admin", admin);     // tg_id админа
        const data = await get("/api/reserves/list?" + qsParams.toString());
        listEl.innerHTML = "";
        (data.items || []).forEach(it => {
            const card = reserveCard(it);
            card.addEventListener("click", () => openDetail(it));
            listEl.appendChild(card);
        });
    } finally {
        hideBusy();
    }
}


function openDetail(it) {
    // Детальная карточка как у товара (фото сверху), коммент редактируем — только текст без admin-префикса
    const photos = (it.photos && it.photos.length ? it.photos : [""]).map(escAttr);
    const dots = photos.map((_, i) => `<span class="${i === 0 ? 'active' : ''}"></span>`).join("");
    detailCard.innerHTML = `
    <div class="detail-card">
      <div class="detail-photo">
        <div class="frame"><img id="detailImg" src="${photos[0] || ""}" alt=""></div>
        <div class="dots" id="detailDots">${dots}</div>
        <button id="detailClose" class="icon-btn" title="Закрыть" aria-label="Закрыть">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>
      <div class="detail-body">
        <h3 class="detail-title">${esc(it.brand)} ${esc(it.model)}</h3>
        <div class="detail-row"><span class="detail-label">Запчасть:</span>${esc(it.part)}</div>
        <div class="detail-row"><span class="detail-label">Разборочный:</span>${esc(it.articles)}</div>
        
        <div class="detail-row"><span class="detail-label">Год:</span>${esc(it.year)}</div>
        <div class="detail-row"><span class="detail-label">Двигатель:</span>${esc([it.engine_mark].filter(Boolean).join(" "))}${it.razbor ? " • " + esc(it.razbor) : ""}</div>
        <div class="detail-row"><span class="detail-label">Склад:</span>${esc(it.warehouse || "")}</div>
        <div class="detail-row"><span class="detail-label">Резерв до:</span>${esc((it.reserve_till || "").split(" ")[0])}</div>

        <div class="meta">Комментарий: ${it.comment ? esc(it.comment) : '—'}</div>
        <div class="detail-row">
          <textarea id="fComment" rows="3" style="width:100%;padding:10px;border:1px solid var(--line);border-radius:10px;resize:vertical"
            placeholder="Введите комментарий…">${esc(it.comment || "")}</textarea>
        </div>
        <div class="detail-row"><span class="detail-label">Причина удаления:</span></div>
        <div class="detail-row">
          <input id="fReason" class="search" placeholder="Почему удаляем? (необязательно)"/>
        </div>


        <div class="detail-actions">
          <button id="btnSave" class="btn sm">Сохранить</button>
          <button id="btnDel" class="btn sm">Удалить</button>
<!--          <button id="btnClose" class="btn sm">Закрыть</button>-->
        </div>
      </div>
    </div>
  `;
    detail.classList.remove("hidden");

    const img = qs("#detailImg");
    let idx = 0;
    img.parentElement.addEventListener("click", () => {
        if (!it.photos || !it.photos.length) return;
        idx = (idx + 1) % it.photos.length;
        img.src = it.photos[idx] || "";
        const dots = qs("#detailDots")?.querySelectorAll("span") || [];
        dots.forEach((d, i) => d.classList.toggle("active", i === idx));
    });

    qs("#detailClose").onclick = () => detail.classList.add("hidden");
    // qs("#btnClose").onclick = () => detail.classList.add("hidden");

    qs("#btnSave").onclick = async () => {
        const btn = qs("#btnSave");
        const comment = (qs("#fComment").value || "").trim();

        showBusy("Сохраняю комментарий…");     // модальный индикатор
        btn.setAttribute("disabled", "true");

        try {
            await post(`/api/reserves/${it.id}/comment`, {
                init_data: init,
                comment,
                admin_tag: it.admin_tag || null
            }, "PATCH");

            detail.classList.add("hidden");
            window.Telegram?.WebApp?.showAlert("Комментарий сохранён");

            const currentTitle = listTitle.textContent || "Список резервов";
            if (/Непонятные/i.test(currentTitle)) {
                await loadList({unknown: 1, title: currentTitle});
            } else if (it.admin_tg_id) {
                await loadList({admin: it.admin_tg_id, title: currentTitle});
            } else {
                await loadList({title: currentTitle});
            }
        } finally {
            hideBusy();                          // убрать модалку
            btn.removeAttribute("disabled");
        }
    };

    qs("#btnDel").onclick = async () => {
        const reason = (qs("#fReason")?.value || "").trim();
        showBusy("Удаляю…");
        try {
            await post(`/api/reserves/${it.id}`, {init_data: init, reason}, "DELETE");
            detail.classList.add("hidden");
            const currentTitle = listTitle.textContent || "Список резервов";
            if (/Непонятные/i.test(currentTitle)) await loadList({unknown: 1, title: currentTitle});
            else if (it.admin_tag) await loadList({tag: it.admin_tag, title: currentTitle});
            else await loadList({title: currentTitle});
        } finally {
            hideBusy();
        }
    };

}

loadAdmins().catch(console.error);
