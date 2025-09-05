export function showBusy(msg){
  const b = document.getElementById('busy'); if(!b) return;
  const t = document.getElementById('busyText'); if (t) t.textContent = msg || 'Выполняю…';
  b.classList.add('show');
}
export function hideBusy(){
  document.getElementById('busy')?.classList.remove('show');
}

// защита от дабл-клика
const inflight = new Map();
export async function singleFlight(key, fn){
  if (inflight.get(key)) return;
  inflight.set(key, true);
  try { return await fn(); } finally { inflight.delete(key); }
}
