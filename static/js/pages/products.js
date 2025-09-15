import {api} from "../core/api.js";
import {initData} from "../core/tg.js";
import {showBusy, hideBusy, singleFlight} from "../core/busy.js";
import {productCard, setHidden, qs} from "../ui.js";

export async function bootProducts() {
    const init = initData();

    // Если открыто в браузере (нет initData) — показываем гостя и убираем спиннер
    if (!init) {
        showGuest();
        document.documentElement.classList.remove('loading');
        document.body.classList.remove('loading');
        return;
    }

    // В Telegram: держим спиннер, пока не выбрали экран
    try {
        await api.validate(init);
        try {
            const me = await api.me(init);
            window.__ME = me;

            if (me.is_blocked) {
                showOnly("blocked");
                document.documentElement.classList.remove('loading');
                document.body.classList.remove('loading');
                return;
            }

            await showMain(init); // снимем loading внутри
        } catch {
            // Зарегистрирован не был — форма регистрации (но не гостя)
            showOnly("reg");
            bindRegistration(init);
            document.documentElement.classList.remove('loading');
            document.body.classList.remove('loading');
        }
    } catch {
        // validate не прошёл; в TG гостя не показываем
        showOnly("reg");
        bindRegistration(init);
        document.documentElement.classList.remove('loading');
        document.body.classList.remove('loading');
    }
}

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

function bindRegistration(init) {
    const form = document.getElementById("regForm");
    form.addEventListener("submit", async ev => {
        ev.preventDefault();
        const fd = new FormData(form);
        showBusy("Регистрирую…");
        try {
            await api.register(init, {
                name: fd.get("name"), city: fd.get("city"),
                phone: fd.get("phone"), role: fd.get("role")
            });
            await showMain(init);
        } catch (e) {
            window.Telegram?.WebApp?.showAlert("Ошибка регистрации: " + (e?.message || "сервер недоступен"));
        } finally {
            hideBusy();
        }
    });
}


async function showMain(init) {
    // экран + снятие спиннера
    showOnly("main");
    document.documentElement.classList.remove('loading');
    document.body.classList.remove('loading');

    const grid = document.getElementById("grid");
    const search = document.getElementById("search");
    const sortSel = document.getElementById("sortSel");
    const dl = document.getElementById("dl");
    const btnSearch = document.getElementById("btnSearch");
    const btnSort = document.getElementById("btnSort");
    const panelSearch = document.getElementById("panelSearch");
    const panelAdmin = document.getElementById("panelAdmin");
    const chips = document.getElementById("chips");

    // админ меню
    try {
        const m = await import("../admin.js");
        if (m?.setupAdmin) await m.setupAdmin(init);
    } catch {
    }

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
                state.bucket = it.key || it.value || it.label;
                resetAndLoad();
            });
            chips.appendChild(b);
        });
        chips.dataset.loaded = "1";
    }

    function params() {
        return {
            q: state.q, sort: state.sort, bucket: state.bucket,
            offset: state.offset, limit: state.limit
        };
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

    // глобальный триггер для принудительного обновления (резерв и т.п.)
    window.__doRefresh = resetAndLoad;

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

    // Скачать прайсы
    dl.addEventListener("click", async (e) => {
        e.preventDefault();
        if (dl.classList.contains("loading")) return;
        dl.classList.add("loading");
        const qs = new URLSearchParams({q: state.q, sort: state.sort, bucket: state.bucket}).toString();
        try {
            try {
                await api.pricesSplit(qs, init);
                window.Telegram?.WebApp?.showAlert("Прайсы отправлены в чат бота.");
            } catch {
                await api.pricesAll(qs, init);
                window.Telegram?.WebApp?.showAlert("Прайс отправлен в чат бота.");
            }
        } catch {
            window.Telegram?.WebApp?.showAlert("Не удалось отправить прайс.");
        } finally {
            dl.classList.remove("loading");
        }
    });

    resetAndLoad();

    // карточка товаров
    grid.addEventListener("click", async (e) => {
        const body = e.target.closest('.body[data-id]');
        if (!body) return;
        const pid = parseInt(body.getAttribute("data-id"), 10);
        if (!pid) return;
        try {
            await openDetail(pid, init);
        } catch {
        }
    });
    grid.addEventListener("keydown", async (e) => {
        if (e.key !== "Enter") return;
        const body = e.target.closest('.body[data-id]');
        if (!body) return;
        const pid = parseInt(body.getAttribute("data-id"), 10);
        if (!pid) return;
        try {
            await openDetail(pid, init);
        } catch {
        }
    });

    // ---- Реалтайм: SSE + фоллбек ----
    let invVersion = 0, es = null, pollT = null;
    const debouncedReload = debounce(() => resetAndLoad(), 300);

    function startPoll() {
        if (pollT) clearInterval(pollT);
        pollT = setInterval(async () => {
            try {
                const v = await api.get("/api/inventory/version");
                const ver = Number(v?.version || 0);
                if (ver && ver !== invVersion) {
                    invVersion = ver;
                    debouncedReload();
                }
            } catch {
            }
        }, 15000);
    }

    function connectSSE() {
        try {
            es = new EventSource("/api/stream");
            es.addEventListener("inventory", (ev) => {
                try {
                    const d = JSON.parse(ev.data || "{}");
                    const ver = Number(d?.version || 0);
                    if (ver && ver !== invVersion) {
                        invVersion = ver;
                        debouncedReload();
                    }
                } catch {
                }
            });
            es.onerror = () => {
                try {
                    es.close();
                } catch {
                }
                startPoll();
            };
        } catch {
            startPoll();
        }
    }

    connectSSE();
}


async function openDetail(pid, init) {
    const data = await api.product(pid);
    const wrap = qs("#detail");
    const root = qs("#detailContent");
    root.innerHTML = renderDetailHTML(data);
    wrap.classList.remove("hidden");

    // Закрытие
    const close = () => {
        wrap.classList.add("hidden");
        window.removeEventListener("keydown", onKey);
    };
    qs("#detailClose").onclick = close;
    wrap.addEventListener("click", (e) => {
        if (e.target.id === "detail") close();
    });

    // ---- Карусель фото ----
    const imgs = (Array.isArray(data.photos) && data.photos.length) ? data.photos.slice() : [""];
    let cur = 0;

    const imgEl = document.getElementById("detailImg");
    const dotsEl = document.getElementById("detailDots");

    function show(i) {
        if (!imgs.length) return;
        cur = (i + imgs.length) % imgs.length;
        imgEl.src = imgs[cur] || "";
        if (dotsEl) {
            dotsEl.querySelectorAll("span").forEach((s, idx) => s.classList.toggle("active", idx === cur));
        }
    }

    // Клик по фото → следующее
    imgEl.addEventListener("click", () => show(cur + 1));

    // Клик по точке
    if (dotsEl) {
        dotsEl.addEventListener("click", (e) => {
            const dot = e.target.closest("span");
            if (!dot) return;
            const idx = Array.from(dotsEl.children).indexOf(dot);
            if (idx >= 0) show(idx);
        });
    }

    // Свайпы
    let sx = 0, sy = 0;
    const touchTarget = imgEl; // можно повесить на .frame, если нужно шире
    touchTarget.addEventListener("touchstart", (e) => {
        const t = e.changedTouches[0];
        sx = t.clientX;
        sy = t.clientY;
    }, {passive: true});
    touchTarget.addEventListener("touchend", (e) => {
        const t = e.changedTouches[0];
        const dx = t.clientX - sx, dy = t.clientY - sy;
        if (Math.abs(dx) > 30 && Math.abs(dx) > Math.abs(dy)) {
            if (dx < 0) show(cur + 1); else show(cur - 1);
        }
    }, {passive: true});

    // Клавиатура
    function onKey(e) {
        if (e.key === "ArrowRight") show(cur + 1);
        if (e.key === "ArrowLeft") show(cur - 1);
        if (e.key === "Escape") close();
    }

    window.addEventListener("keydown", onKey);

    show(0);
    // ---- /Карусель ----

    // Остальные кнопки модалки
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
                    await api.sendPhotos(pid, init);
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
        btnVideo.onclick = (ev) => {
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
                    await api.reserve(pid, init, comment);
                    window.Telegram?.WebApp?.showAlert("Резерв установлен.");
                    qs("#detail")?.classList.add("hidden");
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
    const vol = (r["ОБЪЕМ"] || "").trim(), et = (r["ТИП ДВИГАТЕЛЯ"] || "").trim();
    if (vol || et) rows.push(rowHTML("", esc(`${vol}${vol && et ? " " : ""}${et}`)));
    if (r["КОРОБКА"]) rows.push(rowHTML("", esc(r["КОРОБКА"])));
    if (r["ТИП КУЗОВА"]) rows.push(rowHTML("", esc(r["ТИП КУЗОВА"])));
    if (p.price || p.currency) rows.push(rowHTML("Цена", esc(`${p.price || ""} ${p.currency || ""}`)));
    if (r["ПРИВОД"]) rows.push(rowHTML("", esc(r["ПРИВОД"])));
    if (r["Склад"]) rows.push(rowHTML("", esc(r["Склад"])));
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
        ${isAdmin ? `<a href="#" id="btnReserve" class="btn sm">Резерв</a>` : ""}
      </div>
    </div>
  </div>`;
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
