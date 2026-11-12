(() => {
  const tg=window.Telegram?.WebApp;
  if(tg){tg.ready();tg.expand();try{tg.setHeaderColor('#090a0f');tg.setBackgroundColor('#090a0f');}catch(_){}}
  const pages=[...document.querySelectorAll('.page')];
  function showPage(id){
    const target=document.getElementById(id)||document.getElementById('home');
    pages.forEach(p=>p.classList.toggle('active',p===target));
    document.querySelectorAll('#nav a').forEach(a=>a.classList.toggle('active',a.getAttribute('href')==='#'+target.id));
    if(location.hash!=='#'+target.id)history.replaceState(null,'','#'+target.id);
    window.scrollTo({top:0,behavior:'smooth'});
    if(target.id==='tops')loadTops(document.querySelector('[data-top].selected')?.dataset.top||'level');
  }
  document.querySelectorAll('a[href^="#"]').forEach(a=>a.addEventListener('click',e=>{const id=a.getAttribute('href').slice(1);if(document.getElementById(id)){e.preventDefault();showPage(id);}}));
  document.getElementById('profileBtn').addEventListener('click',()=>showPage('profile'));
  async function api(path){const r=await fetch(path,{headers:{'X-Telegram-Init-Data':tg?.initData||''}});if(!r.ok)throw new Error('API '+r.status);return r.json();}
  async function loadProfile(){
    if(!tg?.initData){document.getElementById('profileHint').textContent='Открой Mini App через Telegram, чтобы подтвердить профиль.';return;}
    try{const data=await api('/api/miniapp/me');const u=data.user||{};const name=u.nick||u.first_name||'Игрок FENIX';document.getElementById('profileName').textContent=name;document.getElementById('playerName').textContent=name;document.getElementById('playerInfo').textContent='Telegram ID: '+u.id;document.getElementById('profileHint').textContent='Профиль Telegram подключён.';document.getElementById('avatar').textContent=(name[0]||'F').toUpperCase();}
    catch(e){document.getElementById('profileHint').textContent='Не удалось загрузить профиль. Открой Mini App из бота.';}
  }
  function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  async function loadTops(type){
    const root=document.getElementById('leaderboard');root.innerHTML='<div class="empty-card">Загружаем рейтинг…</div>';
    try{const data=await api('/api/miniapp/tops?type='+encodeURIComponent(type));if(!data.items?.length){root.innerHTML='<div class="empty-card">Пока в рейтинге нет игроков. Топ появится после добавления игровых никнеймов.</div>';return;}
      root.innerHTML=data.items.map((p,i)=>'<div class="feature-card" style="margin:8px 0;padding:16px"><div class="avatar">'+(i+1)+'</div><div><h3>'+escapeHtml(p.nickname)+'</h3><p>'+escapeHtml(p.subtitle||'Игрок FENIX ONLINE')+'</p></div><div class="balance"><b>'+Number(p.value||0).toLocaleString('ru-RU')+'</b><small>'+escapeHtml(p.unit||'')+'</small></div></div>').join('');
    }catch(e){root.innerHTML='<div class="empty-card">Рейтинг пока недоступен. Попробуй позже.</div>';}
  }
  document.querySelectorAll('[data-top]').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('[data-top]').forEach(x=>x.classList.toggle('selected',x===b));loadTops(b.dataset.top);}));
  const initial=(location.hash||'#home').slice(1);showPage(initial);loadProfile();
  fetch('/launcher/FenixOnline.exe',{method:'HEAD'}).then(r=>{if(r.ok)document.getElementById('launcherState').textContent='Лаунчер доступен для загрузки';else throw new Error();}).catch(()=>{document.getElementById('launcherState').textContent='Лаунчер будет добавлен владельцем проекта';document.getElementById('downloadBtn').addEventListener('click',e=>{e.preventDefault();if(tg?.showAlert)tg.showAlert('Лаунчер пока не загружен.');else alert('Лаунчер пока не загружен.');});});
})();

// Live SA-MP status for BLACK server
async function refreshLiveServer(){
  const value=document.getElementById('livePlayers');
  const label=document.getElementById('livePlayersLabel');
  if(!value) return;
  try{
    const response=await fetch('/api/server-status',{cache:'no-store'});
    const data=await response.json();
    if(data.online){value.textContent=String(data.players); if(label) label.textContent='ИГРОКОВ ОНЛАЙН';}
    else {value.textContent='—'; if(label) label.textContent='СЕРВЕР НЕ ОТВЕЧАЕТ';}
  }catch(e){value.textContent='—'; if(label) label.textContent='НЕТ СВЯЗИ С СЕРВЕРОМ';}
}
refreshLiveServer(); setInterval(refreshLiveServer,15000);
