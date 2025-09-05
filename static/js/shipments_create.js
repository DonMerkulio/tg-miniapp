function tgInit(){
  const tg = window.Telegram?.WebApp;
  if (!tg || !tg.initData) throw new Error("open inside Telegram");
  tg.ready(); return tg.initData;
}
async function get(url){ const r=await fetch(url,{cache:"no-store"}); if(!r.ok) throw new Error(await r.text()); return r.json(); }
async function post(url,data){ const r=await fetch(url,{method:"POST",headers:{'Content-Type':'application/json'},body:JSON.stringify(data||{})}); if(!r.ok) throw new Error(await r.text()); return r.json(); }

const init = tgInit();
const form = document.getElementById("formNew");
const sw = document.getElementById("prepay_sw");

form.addEventListener("submit", async (e)=>{
  e.preventDefault();
  const fd = new FormData(form);
  const payload = {
    init_data: init,
    category: fd.get("category"),
    articles: fd.get("articles"),
    warehouse: fd.get("warehouse"),
    carrier: fd.get("carrier"),
    city: fd.get("city"),
    client_info: fd.get("client_info"),
    prepay: !!sw.checked,
    track_no: fd.get("track_no")||""
  };
  await post("/api/shipments", payload);
  form.reset(); sw.checked = false;
  window.Telegram?.WebApp?.showAlert("Создано");
});
