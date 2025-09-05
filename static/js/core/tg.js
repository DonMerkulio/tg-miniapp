export function initData(){
  const tg = window.Telegram?.WebApp;
  if (!tg) return null;
  if (!tg.initData) {
    console.warn("In Telegram but initData empty");
    return null;
  }
  tg.ready();
  return tg.initData;
}
