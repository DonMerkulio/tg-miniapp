import {initData} from "../core/tg.js";
import {showBusy, hideBusy} from "../core/busy.js";

const init = initData();

const msg = document.getElementById("msg");
const photos = document.getElementById("photos");
const files = document.getElementById("files");
const pcount = document.getElementById("pcount");
const fcount = document.getElementById("fcount");

const rcnt = document.getElementById("rcnt");
const btnPreview = document.getElementById("btnPreview");
const btnSend = document.getElementById("btnSend");

const prog = document.getElementById("prog");
const bar = document.getElementById("barIn");
const lab = document.getElementById("label");
const failsBox = document.getElementById("failsBox");
const failsList = document.getElementById("failsList");

let lastRenderedFailIds = new Set();

function escapeHtml(s) {
    return (s || "").replace(/[&<>"']/g, c => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    }[c]));
}

async function get(url) {
    const r = await fetch(url, {cache: "no-store"});
    if (!r.ok) throw new Error(await r.text());
    return r.json();
}

async function loadCount() {
    try {
        const q = new URLSearchParams({init_data: init});
        const j = await get("/api/broadcast/notify/recipients?" + q.toString());
        rcnt.textContent = String(j.count ?? 0);
    } catch {
        rcnt.textContent = "0";
    }
}

loadCount();

function clampFiles() {
    if (photos.files.length > 10) window.Telegram?.WebApp?.showAlert("Можно выбрать до 10 фото");
    if (files.files.length > 5) window.Telegram?.WebApp?.showAlert("Можно выбрать до 5 файлов/видео");
    pcount.textContent = Math.min(10, photos.files.length);
    fcount.textContent = Math.min(5, files.files.length);
}

photos.addEventListener("change", clampFiles);
files.addEventListener("change", clampFiles);

function buildFD() {
    const fd = new FormData();
    fd.append("init_data", init || "");
    fd.append("text", (msg.value || "").trim());
    [...photos.files].slice(0, 10).forEach(f => fd.append("photos", f));
    [...files.files].slice(0, 5).forEach(f => fd.append("files", f));
    return fd;
}

function resetUI() {
    // поля
    msg.value = "";
    photos.value = "";
    files.value = "";
    pcount.textContent = "0";
    fcount.textContent = "0";
    // прогресс
    prog.classList.add("hidden");
    bar.style.width = "0%";
    lab.textContent = "0 / 0 (успешно: 0, не доставлено: 0)";
    // ошибки
    failsBox.classList.add("hidden");
    failsList.innerHTML = "";
    lastRenderedFailIds.clear();
    // кнопки
    btnSend.removeAttribute("disabled");
    btnPreview.removeAttribute("disabled");
}

btnPreview?.addEventListener("click", async () => {
    btnPreview.setAttribute("disabled", "true");
    showBusy("Отправляю себе…");
    try {
        const fd = buildFD();
        const r = await fetch("/api/broadcast/notify/preview", {method: "POST", body: fd});
        if (!r.ok) throw new Error(await r.text());
        window.Telegram?.WebApp?.showAlert("Предпросмотр отправлен себе в чат.");
    } catch {
        window.Telegram?.WebApp?.showAlert("Не удалось отправить предпросмотр");
    } finally {
        hideBusy();
        btnPreview.removeAttribute("disabled");
    }
});

btnSend?.addEventListener("click", async () => {
    btnSend.setAttribute("disabled", "true");
    showBusy("Готовлю вложения…");
    try {
        const fd = buildFD();
        const r = await fetch("/api/broadcast/notify/start", {method: "POST", body: fd});
        if (!r.ok) throw new Error(await r.text());
        const {job_id, total} = await r.json();

        hideBusy();
        prog.classList.remove("hidden");
        failsBox.classList.add("hidden");
        failsList.innerHTML = "";
        lastRenderedFailIds.clear();
        lab.textContent = `0 / ${total} (успешно: 0, не доставлено: 0)`;
        bar.style.width = "0%";

        poll(job_id, total);
    } catch {
        hideBusy();
        btnSend.removeAttribute("disabled");
        window.Telegram?.WebApp?.showAlert("Не удалось запустить рассылку");
    }
});

function renderFails(fails) {
    if (!Array.isArray(fails) || !fails.length) return;
    failsBox.classList.remove("hidden");
    for (const f of fails) {
        const key = String(f.tg_id || "");
        if (lastRenderedFailIds.has(key)) continue;
        lastRenderedFailIds.add(key);
        const name = (f.name || "").trim() || "—";
        const phone = (f.phone || "").trim() || "—";
        const reason = (f.reason || "").trim() || "ошибка доставки";
        const row = document.createElement("div");
        row.style.display = "grid";
        row.style.gap = "2px";
        row.innerHTML = `
      <div style="font-weight:600">${escapeHtml(name)} <span style="color:var(--muted)">• ${escapeHtml(phone)}</span></div>
      <div style="font-size:13px;color:#d70015">Причина: ${escapeHtml(reason)}. Уведомления отключены, пользователь заблокирован в приложении.</div>
    `;
        failsList.appendChild(row);
    }
}

async function poll(jobId, total) {
    const t = setInterval(async () => {
        try {
            const s = await get("/api/broadcast/notify/status?job_id=" + encodeURIComponent(jobId));
            const all = Number(s.total || total || 0);
            const sent = Number(s.sent || 0);
            const failedCnt = Number(s.failed_count || 0);
            const processed = Number(s.processed || (sent + (s.failed?.length || 0)));
            const pct = all ? Math.round(processed * 100 / all) : 0;

            lab.textContent = `${processed} / ${all} (успешно: ${sent}, не доставлено: ${failedCnt})`;
            bar.style.width = pct + "%";

            if (Array.isArray(s.failed)) renderFails(s.failed);

            if (s.done) {
                clearInterval(t);
                window.Telegram?.WebApp?.showAlert("Рассылка завершена");
                loadCount();
                resetUI();
            }
        } catch {/* ignore */
        }
    }, 1000);
}
