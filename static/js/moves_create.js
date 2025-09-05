function tgInit(){
  const tg = window.Telegram?.WebApp;
  if (!tg || !tg.initData) throw new Error("open inside Telegram");
  tg.ready(); return tg.initData;
}
async function post(url,data){ const r=await fetch(url,{method:"POST",headers:{'Content-Type':'application/json'},body:JSON.stringify(data||{})}); if(!r.ok) throw new Error(await r.text()); return r.json(); }

const init = tgInit();
const form = document.getElementById("formNew");

form.addEventListener("submit", async (e)=>{
  e.preventDefault();
  const fd = new FormData(form);
  const route = fd.get("route"); // "озеро-москва" | "москва-озеро"
  const payload = {
    init_data: init,
    part: fd.get("part"),
    articles: fd.get("articles"),
    route
  };
  await post("/api/moves", payload);
  form.reset();
  document.getElementById("r_oz_msk").checked = true;
  window.Telegram?.WebApp?.showAlert("Создано");
});
