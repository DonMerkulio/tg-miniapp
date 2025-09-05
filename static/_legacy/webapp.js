import {productCard, setHidden, qs} from "../js/ui.js";
import {setupAdmin} from "../js/admin.js";

console.log("webapp.js start");

// ---- API ----
const api = {
    validate: (init) => post("/api/auth/validate", {init_data: init}),
    me: (init) => post("/api/me", {init_data: init}),
    register: (init, payload) => post("/api/register", {init_data: init, ...payload}),
    products: (params) => get("/api/products?" + new URLSearchParams(params).toString()),
    parts: () => get("/api/parts"),
    refresh: () => post("/api/refresh", {}),
};

// ---- fetch helpers ----
async function get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
}

async function post(url, data) {
    const r = await fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data)
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
}

// ---- Busy helpers ----
function showBusy(msg) {
    const b = qs('#busy');
    if (!b) return;
    const t = qs('#busyText');
    if (t) t.textContent = msg || 'Выполняю…';
    b.classList.add('show');
}

function hideBusy() {
    qs('#busy')?.classList.remove('show');
}

const inflight = new Map();

async function singleFlight(key, fn) {
    if (inflight.get(key)) return;
    inflight.set(key, true);
    try {
        return await fn();
    } finally {
        inflight.delete(key);
    }
}

// ---- Telegram init ----
function initData() {
    const tg = window.Telegram?.WebApp;
    if (!tg) return null;
    if (!tg.initData) {
        console.warn("In Telegram but initData empty");
        return null;
    }
    tg.ready();
    return tg.initData;
}

// ---- Boot ----
async function boot() {
    const init = initData();
    if (!init) {
        document.body.classList.remove('loading');
        showGuest();
        return;
    }
    try {
        await api.validate(init);
        try {
            const me = await api.me(init);
            window.__ME = me;
            if (me.is_blocked) {
                document.body.classList.remove('loading');
                showOnly("blocked");
                return;
            }
            document.body.classList.remove('loading'); // скрыть гостя окончательно
            await showMain(init);
        } catch {
            document.body.classList.remove('loading');
            showOnly("reg");
            bindRegistration(init);
        }
    } catch {
        document.body.classList.remove('loading');
        document.body.classList.remove('in-tg');
        showGuest();
    }
}

// ---- UI helpers ----
function showOnly(id) {
    ["guest", "reg", "blocked", "main"].forEach(x => setHidden(x, x !== id));
}

function showGuest() {
    setHidden("guest", false);
    setHidden("reg", true);
    setHidden("blocked", true);
    setHidden("main", true);
}

function debounce(fn, ms) {
    let t;
    return (...a) => {
        clearTimeout(t);
        t = setTimeout(() => fn(...a), ms);
    };
}

// ---- Registration ----
function bindRegistration(init) {
    const form = document.getElementById("regForm");
    form.addEventListener("submit", async ev => {
        ev.preventDefault();
        const fd = new FormData(form);
        await api.register(init, {
            name: fd.get("name"), city: fd.get("city"),
            phone: fd.get("phone"), role: fd.get("role")
        });
        await showMain(init);
    });
}

// ---- Main page ----
async function showMain(init) {
    showOnly("main");

    const grid = document.getElementById("grid");
    const search = document.getElementById("search");
    const sortSel = document.getElementById("sortSel");
    const dl = document.getElementById("dl");
    const btnSearch = document.getElementById("btnSearch");
    const btnSort = document.getElementById("btnSort");
    const panelSearch = document.getElementById("panelSearch");
    const panelAdmin = document.getElementById("panelAdmin");
    const chips = document.getElementById("chips");

    await setupAdmin(init);

    // Пагинация
    let state = {q: "", sort: "", bucket: "", offset: 0, limit: 20, loading: false, done: false};
    const sentinel = document.createElement("div");
    sentinel.id = "sentinel";
    sentinel.style.height = "1px";

    btnSearch.addEventListener("click", async () => {
        panelSearch.classList.toggle("hidden");
        panelAdmin.classList.add("hidden");
        if (!panelSearch.classList.contains("hidden")) {
            search.focus();
            await loadParts();
        }
    });

    btnSort.addEventListener("click", () => {
        if (sortSel.showPicker) sortSel.showPicker(); else sortSel.focus();
    });

    async function loadParts() {
        if (chips.dataset.loaded) return;
        const j = await api.parts();
        chips.innerHTML = "";
        const all = document.createElement("button");
        all.className = "chip active";
        all.textContent = "Все";
        all.addEventListener("click", () => {
            chips.querySelectorAll(".chip").forEach(x => x.classList.remove("active"));
            all.classList.add("active");
            state.bucket = "";
            resetAndLoad();
        });
        chips.appendChild(all);
        j.items.forEach(it => {
            const b = document.createElement("button");
            b.className = "chip";
            b.textContent = it.label;
            b.title = it.label;
            b.addEventListener("click", () => {
                chips.querySelectorAll(".chip").forEach(x => x.classList.remove("active"));
                b.classList.add("active");
                state.bucket = it.key;
                resetAndLoad();
            });
            chips.appendChild(b);
        });
        chips.dataset.loaded = "1";
    }

    function params() {
        return {q: state.q, sort: state.sort, bucket: state.bucket, offset: state.offset, limit: state.limit};
    }

    async function loadMore() {
        if (state.loading || state.done) return;
        state.loading = true;
        try {
            const data = await api.products(params());
            if (sentinel.parentNode) sentinel.remove();
            data.items.forEach(p => grid.appendChild(productCard(p)));
            grid.appendChild(sentinel);
            state.offset += state.limit;
            state.done = !data.has_more;
            if (state.done && sentinel.parentNode) sentinel.remove();
        } finally {
            state.loading = false;
        }
    }

    function resetAndLoad() {
        state.offset = 0;
        state.done = false;
        grid.innerHTML = "";
        grid.appendChild(sentinel);
        loadMore();
    }

    search.addEventListener("input", debounce(() => {
        state.q = search.value.trim();
        resetAndLoad();
    }, 250));
    sortSel.addEventListener("change", () => {
        state.sort = sortSel.value || "";
        resetAndLoad();
    });
    sortSel.addEventListener("input", () => {
        state.sort = sortSel.value || "";
        resetAndLoad();
    });

    const io = ("IntersectionObserver" in window)
        ? new IntersectionObserver((entries) => {
            if (entries.some(e => e.isIntersecting)) loadMore();
        }, {rootMargin: "600px"})
        : null;
    if (io) io.observe(sentinel);

    dl.onclick = async (e) => {
        e.preventDefault();
        await post("/api/prices_split.xlsx?" + new URLSearchParams({
            q: state.q,
            sort: state.sort,
            bucket: state.bucket
        }).toString(),
            {init_data: init});
        window.Telegram?.WebApp?.showAlert("Прайсы отправлены в чат бота.");
    };

    document.addEventListener("visibilitychange", async () => {
        if (document.visibilityState === "visible") {
            try {
                await api.refresh();
            } catch (e) {
            }
            resetAndLoad();
        }
    });

    resetAndLoad();

    // Открытие карточки — только по описанию
    grid.addEventListener("click", (e) => {
        const body = e.target.closest('.body[data-id]');
        if (!body) return;
        const pid = parseInt(body.getAttribute("data-id"), 10);
        if (pid) openDetail(pid, init);
    });
    grid.addEventListener("keydown", (e) => {
        if (e.key !== "Enter") return;
        const body = e.target.closest('.body[data-id]');
        if (!body) return;
        const pid = parseInt(body.getAttribute("data-id"), 10);
        if (pid) openDetail(pid, init);
    });

    window.__doRefresh = async () => {
        try {
            await api.refresh();
        } catch (e) {
        }
        resetAndLoad();
    };
}

// ---- start ----
(function start() {
    const run = () => boot().catch(e => {
        console.error("boot failed:", e);
        document.body.classList.remove('loading');
        document.body.classList.remove('in-tg');
        showGuest();
    });
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run); else run();
})();

// ---- no-zoom UX ----
document.addEventListener('dblclick', e => e.preventDefault(), {passive: false});
document.addEventListener('gesturestart', e => e.preventDefault());

/* =========================
   Детальная карточка
   ========================= */
async function openDetail(pid, init) {
    const data = await get(`/api/product/${pid}`);
    const wrap = qs("#detail");
    const root = qs("#detailContent");
    root.innerHTML = renderDetailHTML(data);
    wrap.classList.remove("hidden");

    qs("#detailClose").onclick = () => wrap.classList.add("hidden");
    wrap.addEventListener("click", e => {
        if (e.target.id === "detail") wrap.classList.add("hidden");
    });

    const btnPhotos = qs("#btnDetailPhotos");
    const btnVideo = qs("#btnDetailVideo");
    const btnReserve = qs("#btnReserve");

    if (btnPhotos) {
        btnPhotos.onclick = async ev => {
            ev.preventDefault();
            await singleFlight(`photos:${pid}`, async () => {
                btnPhotos.setAttribute("disabled", "true");
                showBusy("Отправляю фото…");
                try {
                    await post(`/api/product/${pid}/send_photos`, {init_data: init});
                    window.Telegram?.WebApp?.showAlert("Фото отправлены в чат бота.");
                } catch {
                    window.Telegram?.WebApp?.showAlert("Не удалось отправить фото.");
                } finally {
                    hideBusy();
                    btnPhotos.removeAttribute("disabled");
                }
            });
        };
    }
    if (btnVideo) {
        btnVideo.onclick = ev => {
            ev.preventDefault();
            const href = btnVideo.getAttribute("data-href");
            if (href) window.open(href, "_blank");
        };
    }
    if (btnReserve) {
        btnReserve.onclick = async ev => {
            ev.preventDefault();
            await singleFlight(`reserve:${pid}`, async () => {
                const comment = (qs("#reserveComment")?.value || "").trim();
                btnReserve.setAttribute("disabled", "true");
                showBusy("Ставлю резерв…");
                try {
                    await post("/api/reserve", {init_data: init, zap: pid, comment});
                    window.Telegram?.WebApp?.showAlert("Резерв установлен.");
                    qs("#detail")?.classList.add("hidden");
                    try {
                        await api.refresh();
                    } catch (e) {
                    }
                    if (window.__doRefresh) window.__doRefresh();
                } catch {
                    window.Telegram?.WebApp?.showAlert("Нет соединения с базой.");
                } finally {
                    hideBusy();
                    btnReserve.removeAttribute("disabled");
                }
            });
        };
    }

    initDetailCarousel(data);
}

function renderDetailHTML(p) {
    const r = p.raw || {};
    const rows = [];
    const razb = [r["ШРОТ"], r["ВХОДНОЙ АРТИКУЛ"]].filter(Boolean).join(" ").trim();
    if (razb) rows.push(rowHTML("разборочный", `<span class="bold">${esc(razb)}</span>`));
    const mm = [p.brand, p.model].filter(Boolean).join(" ").trim();
    if (mm) rows.push(rowHTML("Марка/Модель", esc(mm)));
    if (p.year) rows.push(rowHTML("Год", esc(p.year)));
    if (p.part) rows.push(rowHTML("Запчасть", esc(p.part)));
    if (r["ТОПЛИВО"]) rows.push(rowHTML("Топливо", esc(r["ТОПЛИВО"])));
    if (r["ОБЪЕМ"]) rows.push(rowHTML("Объем", esc(r["ОБЪЕМ"])));
    if (r["КОРОБКА"]) rows.push(rowHTML("Коробка", esc(r["КОРОБКА"])));
    if (r["ТИП КУЗОВА"]) rows.push(rowHTML("Кузов", esc(r["ТИП КУЗОВА"])));
    if (p.price || p.currency) rows.push(rowHTML("Цена", esc(`${p.price || ""} ${p.currency || ""}`)));
    if (r["ПРИВОД"]) rows.push(rowHTML("Привод", esc(r["ПРИВОД"])));
    if (r["Склад"]) rows.push(rowHTML("На складе", esc(r["Склад"])));
    if (r["VIN"]) rows.push(rowHTML("VIN", esc(r["VIN"])));
    if (r["VRN"]) rows.push(rowHTML("VRN", esc(r["VRN"])));

    const photos = (p.photos && p.photos.length ? p.photos : [""]).map(escAttr);
    const dots = photos.map((_, i) => `<span class="${i === 0 ? "active" : ""}"></span>`).join("");

    const isAdmin = !!(window.__ME && window.__ME.is_admin);

    return `
  <div class="detail-card">
    <div class="detail-photo">
      <div class="frame"><img id="detailImg" src="${photos[0] || ""}" alt="" loading="lazy" decoding="async"></div>
      <div class="dots" id="detailDots">${dots}</div>
      <button id="detailClose" class="icon-btn" aria-label="Закрыть" title="Закрыть">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>
    <div class="detail-body">
      <h3 class="detail-title">${esc(`${p.brand || ""} ${p.model || ""}`.trim())}</h3>
      ${rows.join("")}
      ${isAdmin ? `
        <div class="detail-row"><span class="detail-label">Комментарий:</span></div>
        <div class="detail-row"><textarea id="reserveComment" rows="2" style="width:100%;padding:10px;border:1px solid var(--line);border-radius:10px;resize:vertical" placeholder="Введите комментарий для резерва"></textarea></div>` : ``}
      <div class="detail-actions">
        ${p.photos && p.photos.length ? `<a href="#" id="btnDetailPhotos" class="btn sm">Фото</a>` : ""}
        ${(p.videos && p.videos[0]) ? `<a href="#" id="btnDetailVideo" data-href="${escAttr(p.videos[0])}" class="btn sm">Видео</a>` : ""}
        ${isAdmin ? `<a href="#" id="btnReserve" class="btn sm push-right">Резерв</a>` : ""}
      </div>
    </div>
  </div>`;
}

function initDetailCarousel(p) {
    const photos = p.photos && p.photos.length ? p.photos : [""];
    let idx = 0;
    const img = document.getElementById("detailImg");
    const dots = document.getElementById("detailDots")?.querySelectorAll("span") || [];

    function show(i) {
        idx = (i + photos.length) % photos.length;
        img.src = photos[idx] || "";
        dots.forEach((d, j) => d.classList.toggle("active", j === idx));
    }

    img.parentElement.addEventListener("click", () => show(idx + 1));
}

function rowHTML(label, valueHTML) {
    if (!valueHTML) return "";
    if (label) return `<div class="detail-row"><span class="detail-label">${esc(label)}:</span>${valueHTML}</div>`;
    return `<div class="detail-row">${valueHTML}</div>`;
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
