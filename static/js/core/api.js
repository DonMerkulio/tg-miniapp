// HTTP helpers
async function _get(url){
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function _post(url, data){
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type":"application/json" },
    body: JSON.stringify(data||{})
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export const api = {
  get: _get,
  post: _post,
  validate: (init)=> _post("/api/auth/validate", {init_data:init}),
  me:       (init)=> _post("/api/me", {init_data:init}),
  register: (init,p)=> _post("/api/register", {init_data:init, ...p}),
  products: (params)=> _get("/api/products?" + new URLSearchParams(params).toString()),
  parts:    ()=> _get("/api/parts"),
  refresh:  ()=> _post("/api/refresh", {}),
  product:  (id)=> _get(`/api/product/${id}`),
  sendPhotos: (id, init)=> _post(`/api/product/${id}/send_photos`, {init_data:init}),
  reserve:  (id, init, comment)=> _post("/api/reserve", {init_data:init, zap:id, comment}),
  pricesSplit: (qs, init)=> _post("/api/prices_split.xlsx?" + qs, {init_data:init}),
  pricesAll:   (qs, init)=> _post("/api/prices.xlsx?" + qs, {init_data:init}),
};
