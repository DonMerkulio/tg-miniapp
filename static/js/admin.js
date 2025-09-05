async function post(url, data) {
    const r = await fetch(url, {
        method: "POST",
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
}

export async function setupAdmin(init) {
    let me;
    try {
        me = await post("/api/me", {init_data: init});
    } catch {
        return;
    }

    const btn = document.getElementById("btnAdmin");
    const panel = document.getElementById("panelAdmin");
    if (!btn || !panel) return;

    if (me.is_admin) {
        btn.classList.remove("hidden");
        if (location.hash === "#admin") {
            document.getElementById("panelSearch")?.classList.add("hidden");
            panel.classList.remove("hidden");
        }
    } else {
        btn.classList.add("hidden");
        panel.classList.add("hidden");
        return;
    }

    btn.addEventListener("click", () => {
        document.getElementById("panelSearch")?.classList.add("hidden");
        panel.classList.toggle("hidden");
    });

    panel.addEventListener("click", async (e) => {
        const b = e.target.closest("button[data-action]");
        if (!b) return;
        const act = b.getAttribute("data-action");
        if (act === "refresh") {
            try {
                await fetch("/api/refresh", {method: "POST"});
            } catch {
            }
            if (window.__doRefresh) window.__doRefresh();
            return;
        }
        if (act === "shipments") {
            location.href = "/admin/shipments";
            return;
        }
        if (act === "moves") {
            location.href = "/admin/moves";
            return;
        }
        if (act === "reserves") {
            location.href = "/admin/reserves";
            return;
        }
        if (act === "users") {
            location.href = "/admin/users";
            return;
        }
        if (act === "price-broadcast") {
            location.href = "/admin/broadcast/prices";
            return;
        }
        if (act === "notify-broadcast") {
            location.href = "/admin/broadcast/notify";
            return;
        }
    });
}

