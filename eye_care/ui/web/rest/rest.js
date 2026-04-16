(function(){
  const $ = (id)=>document.getElementById(id);
  const elTime = $('restTime');
  const elHint = $('restHint');
  const btnSnooze = $('btnSnooze');

  let _timer = null;
  let _endMs = 0;
  let _duration = 0;

  // 用于排查"休息界面时间流逝速度"问题
  let _startWallMs = 0;
  let _startPerfMs = 0;
  let _lastTickWallMs = 0;
  let _lastTickPerfMs = 0;
  let _tickN = 0;
  let _lastLogSec = -1;

  function fmt(sec){
    sec = Math.max(0, Math.floor(sec));
    const m = Math.floor(sec/60);
    const s = sec%60;
    return String(m).padStart(2,'0')+':'+String(s).padStart(2,'0');
  }

  // 业务动作通过 HTTP /api/* 发送
  function callBusinessApi(path, method){
    try{
      var base = window.location.origin || '';
      fetch(base + path, {method: method || 'POST', headers:{'Content-Type':'application/json'}}).catch(function(){});
    }catch(e){
      console.error(e);
    }
  }

  // 窗口行为通过 pywebview.api
  async function callWindowApi(fn){
    try{
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api[fn]==='function'){
        return await window.pywebview.api[fn]();
      }
    }catch(e){
      console.error(e);
    }
    return null;
  }

  async function callWindowApiWith(fn, payload){
    try{
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api[fn]==='function'){
        return await window.pywebview.api[fn](payload);
      }
    }catch(e){
      console.error(e);
    }
    return null;
  }

  function hardLog(evt, data){
    try{
      const payload = Object.assign({
        evt,
        wall_ms: Date.now(),
        perf_ms: (typeof performance!=='undefined' && performance.now) ? performance.now() : null,
        duration_s: _duration,
        end_ms: _endMs,
        tick_n: _tickN,
      }, data||{});
      callWindowApiWith('rest_overlay_log', payload);
    }catch(e){
      // ignore
    }
  }

  // ----------------------------
  // style / transparency diagnostics
  // ----------------------------
  function _cssHrefList(){
    try{
      const hs = Array.from(document.styleSheets || []);
      const out = [];
      for(const ss of hs){
        const href = ss && ss.href ? String(ss.href) : null;
        if(href) out.push(href);
      }
      return out.slice(0, 8);
    }catch(e){
      return null;
    }
  }

  function hardStyleSnapshot(tag){
    try{
      const body = document.body;
      const bg = document.querySelector('.rest-bg') || document.getElementById('restBg');
      const card = document.querySelector('.rest-card') || document.querySelector('.card');

      const sb = body ? getComputedStyle(body) : null;
      const sBg = bg ? getComputedStyle(bg) : null;
      const sCard = card ? getComputedStyle(card) : null;

      hardLog('style', {
        tag: tag,
        css_hrefs: _cssHrefList(),
        body_bg: sb ? sb.backgroundColor : null,
        body_img: sb ? sb.backgroundImage : null,
        body_op: sb ? sb.opacity : null,
        bg_bg: sBg ? sBg.backgroundColor : null,
        bg_img: sBg ? sBg.backgroundImage : null,
        bg_op: sBg ? sBg.opacity : null,
        card_bg: sCard ? sCard.backgroundColor : null,
        card_img: sCard ? sCard.backgroundImage : null,
        card_op: sCard ? sCard.opacity : null,
        dpr: window.devicePixelRatio || 1,
        ua: navigator.userAgent || null,
      });
    }catch(e){
      // ignore
    }
  }

  function tick(){
    _tickN++;
    const left = (_endMs - Date.now())/1000;
    elTime.textContent = fmt(left);

    // 记录 tick 间隔与漂移（每 1 秒写一次，避免刷爆日志）
    const nowWall = Date.now();
    const nowPerf = (typeof performance!=='undefined' && performance.now) ? performance.now() : null;
    const elapsedWall = (nowWall - _startWallMs);
    const elapsedPerf = (nowPerf!=null) ? (nowPerf - _startPerfMs) : null;
    const dtWall = _lastTickWallMs ? (nowWall - _lastTickWallMs) : null;
    const dtPerf = (_lastTickPerfMs && nowPerf!=null) ? (nowPerf - _lastTickPerfMs) : null;
    _lastTickWallMs = nowWall;
    _lastTickPerfMs = nowPerf;
    const leftSecInt = Math.max(0, Math.floor(left));
    if (_startWallMs && leftSecInt !== _lastLogSec) {
      _lastLogSec = leftSecInt;
      hardLog('tick', {
        left_s: left,
        left_i: leftSecInt,
        elapsed_wall_ms: elapsedWall,
        elapsed_perf_ms: elapsedPerf,
        dt_wall_ms: dtWall,
        dt_perf_ms: dtPerf,
        drift_ms: (elapsedPerf!=null) ? (elapsedWall - elapsedPerf) : null,
      });
    }
    if (_endMs > 0 && left <= 0){
      if (window.__rest_closing) return;
      clearInterval(_timer);
      _timer = null;
      hardLog('auto_complete', {left_s: left});
      if (window.__rest_end_sound_enabled !== false) {
        try {
          if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.play_rest_end_sound === 'function') {
            Promise.resolve(window.pywebview.api.play_rest_end_sound()).catch(function(){});
          } else {
            var restEndSound = new Audio((window.location.origin || '') + '/assets/rest_end_refresh_soft.wav');
            restEndSound.play().catch(function(){});
          }
        } catch(e) {}
      }
      callBusinessApi('/api/rest/complete');
      callWindowApi('close_rest_overlay');
    }
  }

  async function snooze(){
    // 稍后/跳过：不播放提示音，仅倒计时结束退出时才放 wav
    clearInterval(_timer);
    _timer = null;
    hardLog('click_snooze', {left_s: (_endMs - Date.now())/1000});
    callBusinessApi('/api/rest/snooze');
    await callWindowApi('close_rest_overlay');
  }

  btnSnooze.addEventListener('click', snooze);

  // 拦截除「稍后」按钮外的所有点击/指针操作，防止穿透到后面窗口（pointer-events: auto 时必须由 JS 吃掉）
  function isSnoozeOrInside(el) {
    if (!el || !btnSnooze) return false;
    return el === btnSnooze || btnSnooze.contains(el);
  }
  function blockIfNotSnooze(e) {
    if (isSnoozeOrInside(e.target)) return;
    e.preventDefault();
    e.stopPropagation();
  }
  document.addEventListener('click', blockIfNotSnooze, true);
  document.addEventListener('mousedown', blockIfNotSnooze, true);
  document.addEventListener('contextmenu', blockIfNotSnooze, true);

  window.restFadeIn = function(){
    try {
      var root = document.getElementById('restRoot') || document.querySelector('.rest-root');
      if (root) { root.classList.remove('rest-fade-out'); root.classList.add('rest-visible'); }
    } catch(e) {}
  };
  window.restFadeOut = function(){
    try {
      var root = document.getElementById('restRoot') || document.querySelector('.rest-root');
      if (root) { root.classList.remove('rest-visible'); root.classList.add('rest-fade-out'); }
    } catch(e) {}
  };

  window.EyeCareRest = {
    stop: function(){
      if (_timer) { clearInterval(_timer); _timer = null; }
      window.__rest_closing = true;
    },
    start: function(durationSec){
      window.__rest_closing = false;
      hardStyleSnapshot('start_before');
      _duration = Number(durationSec||20);
      _endMs = Date.now() + _duration*1000;
      if (_timer) clearInterval(_timer);

      _startWallMs = Date.now();
      _startPerfMs = (typeof performance!=='undefined' && performance.now) ? performance.now() : 0;
      _lastTickWallMs = 0;
      _lastTickPerfMs = 0;
      _tickN = 0;
      _lastLogSec = -1;
      hardLog('start', {duration_s: _duration, end_ms: _endMs});

      // 允许首帧/样式加载后再采一帧
      try{ setTimeout(()=>hardStyleSnapshot('start_after_300ms'), 300); }catch(e){}
      try{ setTimeout(()=>hardStyleSnapshot('start_after_1200ms'), 1200); }catch(e){}

      tick();
      _timer = setInterval(tick, 250);
    }
  };

  // DOM ready：通知后端本屏已就绪（bridge 可能稍晚注入，多试几次）
  (function(){
    var params = new URLSearchParams(window.location.search || '');
    var screenIdx = parseInt(params.get('screen') || '0', 10);
    var attempts = 0;
    var readySent = false;
    function markReadySent() {
      readySent = true;
      window.__rest_ready_sent = true;
    }
    function tryReady() {
      if (readySent || window.__rest_ready_sent) return;
      try {
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.rest_ready_for_show === 'function') {
          markReadySent();
          var maybePromise = window.pywebview.api.rest_ready_for_show(screenIdx);
          if (maybePromise && typeof maybePromise.then === 'function') {
            maybePromise.catch(function(){
              readySent = false;
              window.__rest_ready_sent = false;
            });
          }
          return;
        }
      } catch(e) {
        readySent = false;
        window.__rest_ready_sent = false;
      }
      attempts++;
      if (attempts < 20) setTimeout(tryReady, 100);
    }
    tryReady();
    setTimeout(tryReady, 50);
    setTimeout(tryReady, 200);
  })();

  // DOM ready snapshot
  try{ hardStyleSnapshot('dom_ready'); }catch(e){}

  // Keyboard shortcuts
  window.addEventListener('keydown', (e)=>{
    if(e.key==='Escape'){
      e.preventDefault();
      hardLog('key_escape', {left_s: (_endMs - Date.now())/1000});
      snooze();
    }
  });
})();
