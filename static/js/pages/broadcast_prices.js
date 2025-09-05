import {initData} from "../core/tg.js";
import {showBusy, hideBusy} from "../core/busy.js";

const init = initData();

const rcnt = document.getElementById("rcnt");
const btn = document.getElementById("btnGo");
const prog = document.getElementById("prog");
const bar = document.getElementById("barIn");
const lab = document.getElementById("label");

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

function resetUI() {
    prog.classList.add("hidden");
    bar.style.width = "0%";
    lab.textContent = "0 / 0";
    btn.removeAttribute("disabled");
}

async function loadCount() {
    try {
        const q = new URLSearchParams({init_data: init});
        const j = await get("/api/broadcast/prices/recipients?" + q.toString());
        rcnt.textContent = String(j.count ?? 0);
    } catch {
        rcnt.textContent = "0";
    }
}

loadCount();

btn?.addEventListener("click", async () => {
    btn.setAttribute("disabled", "true");
    showBusy("Готовлю файлы…");
    try {
        const {job_id, total} = await post("/api/broadcast/prices/start", {init_data: init});
        hideBusy();
        prog.classList.remove("hidden");
        lab.textContent = `0 / ${total}`;
        bar.style.width = "0%";
        poll(job_id, total);
    } catch {
        hideBusy();
        btn.removeAttribute("disabled");
        window.Telegram?.WebApp?.showAlert("Не удалось запустить рассылку");
    }
});

async function poll(jobId, total) {
    const t = setInterval(async () => {
        try {
            const s = await get("/api/broadcast/prices/status?job_id=" + encodeURIComponent(jobId));
            const done = Number(s.sent || 0), all = Number(s.total || total || 0);
            const pct = all ? Math.round(done * 100 / all) : 0;
            lab.textContent = `${done} / ${all}`;
            bar.style.width = pct + "%";
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
