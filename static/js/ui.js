export function el(tag, attrs = {}, ...kids){
  const n = document.createElement(tag);
  Object.entries(attrs||{}).forEach(([k,v])=>{
    if(k.startsWith("on") && typeof v==="function") n.addEventListener(k.slice(2), v);
    else if(v!=null) n.setAttribute(k, v);
  });
  kids.flat().forEach(k=> n.append(k instanceof Node ? k : document.createTextNode(k)));
  return n;
}

export function productCard(p){
  const imgs = p.photos && p.photos.length ? p.photos : [""];
  let idx = 0;
  const frame = el('div',{class:'frame','data-id': String(p.id)},
    el('img',{src: imgs[0]||'', alt:'', loading:'lazy', decoding:'async'})
  );
  const dots = el('div',{class:'dots'}, imgs.map((_,i)=> el('span',{class: i===0?'active':''})));
  function show(i){
    idx = (i+imgs.length)%imgs.length;
    const img = frame.querySelector('img');
    img.src = imgs[idx]||'';
    dots.querySelectorAll('span').forEach((d,j)=> d.classList.toggle('active', j===idx));
  }
  frame.addEventListener('click', ()=> show(idx+1));
  const photos = el('div',{class:'photos','data-id': String(p.id)}, frame, dots);

  const r = p.raw || {};
  const title = el('h3',{class:'title'}, `${p.brand} ${p.model}`);
  const part  = el('div',{class:'meta-strong'}, p.part || "");
  const line = [];
  if(p.year) line.push(p.year);
  if(r["КОРОБКА"]) line.push(r["КОРОБКА"]);
  const vol = r["ОБЪЕМ"]||"", et = r["ТИП ДВИГАТЕЛЯ"]||"";
  if(vol || et) line.push(`${vol}${vol&&et?" ":""}${et}`);
  if(r["ТОПЛИВО"]) line.push(r["ТОПЛИВО"]);
  const specs = el('div',{class:'meta'}, line.filter(Boolean).join(" • "));

  const price = el('div',{class:'price'}, `${p.price} ${p.currency||''}`);
  const tags  = el('div',{class:'tags'},
    chip(r["Склад"]),
    chip(r["МАРКИРОВКА ДВИГАТЕЛЯ"]),
    chip([r["ШРОТ"], r["ВХОДНОЙ АРТИКУЛ"]].filter(Boolean).join(" "))
  );
  const row   = el('div',{class:'row-price'}, price, tags);

  const body  = el('div',{class:'body','data-id': String(p.id), tabindex:"0"});
  body.append(title, part, specs, row);

  return el('div',{class:'card product','data-id': String(p.id)}, photos, body);
}

function chip(txt){
  const t = (txt||"").toString().trim();
  if(!t) return el('span');
  return el('span',{class:'tag'}, t);
}

export function setHidden(id, hidden){ document.getElementById(id).classList.toggle('hidden', hidden); }
export function qs(s){ return document.querySelector(s); }
export function qsa(s){ return [...document.querySelectorAll(s)]; }
