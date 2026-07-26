/* ObsidianExchange — ambient-слой (обсидиановый пак): matrix-дождь + частицы.
   Progressive enhancement: полностью изолирован, pointer-events:none, при ошибке
   или отключении сайт работает и выглядит нормально. Учитывает prefers-reduced-motion
   (живая подписка), паузу на невидимой вкладке, DPR/FPS-бюджет и мобильную деградацию. */
(function () {
  'use strict';
  if (window.__oeAmbient) return;            // защита от двойной инициализации
  window.__oeAmbient = true;

  var host = document.querySelector('.oe-bg') || document.querySelector('.matrix-bg');
  if (!host) return;
  // если нашли только старый .matrix-bg — используем его как контейнер
  if (!host.classList.contains('oe-bg')) {
    var wrap = document.createElement('div');
    wrap.className = 'oe-bg';
    wrap.setAttribute('aria-hidden', 'true');
    host.parentNode.insertBefore(wrap, host);
    wrap.appendChild(host);
    host = wrap;
  }

  var rm = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  var small = window.matchMedia ? window.matchMedia('(max-width: 600px)') : { matches: false };

  var DPR = Math.min(window.devicePixelRatio || 1, 1.5);
  var FRAME_MS = 1000 / 30;                   // потолок 30 fps

  var mCanvas = null, pCanvas = null, mCtx = null, pCtx = null;
  var m = null, p = null;                     // состояния matrix / particles
  var W = 0, H = 0;
  var raf = 0, last = 0, running = false;

  function makeCanvas(id) {
    var c = document.createElement('canvas');
    c.id = id;
    c.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block;pointer-events:none';
    host.appendChild(c);
    return c;
  }

  function sizeCanvas(c) {
    var r = host.getBoundingClientRect();
    W = Math.max(1, Math.floor(r.width));
    H = Math.max(1, Math.floor(r.height));
    c.width = Math.max(1, Math.floor(W * DPR));
    c.height = Math.max(1, Math.floor(H * DPR));
    var x = c.getContext('2d');
    x.setTransform(DPR, 0, 0, DPR, 0, 0);
    return x;
  }

  var CHARS = '01BTCUSDTLTC<>/[]{}▓▒░∆Ξ$';
  function glyph(s) {
    var f = (Math.sin(s) * 10000 % 1 + 1) % 1;
    return CHARS[Math.floor(f * CHARS.length)] || '0';
  }

  function initMatrix() {
    if (!mCanvas) mCanvas = makeCanvas('oe-matrix');
    mCtx = sizeCanvas(mCanvas);
    var fs = 14, cols = Math.ceil(W / fs);
    var drops = [];
    for (var i = 0; i < cols; i++) {
      drops.push({ y: Math.random() * -H, speed: 1.0 + Math.random() * 1.7,
                   alpha: 0.06 + Math.random() * 0.10, seed: Math.random() * 1000 });
    }
    mCtx.font = '700 ' + fs + 'px monospace';
    mCtx.textBaseline = 'top';
    m = { fs: fs, drops: drops };
  }

  function initParticles() {
    if (small.matches) { p = null; if (pCanvas) { pCanvas.remove(); pCanvas = null; } return; }
    if (!pCanvas) pCanvas = makeCanvas('oe-particles');
    pCtx = sizeCanvas(pCanvas);
    var count = Math.min(110, Math.max(40, Math.floor((W * H) / 16000)));
    var items = [];
    for (var i = 0; i < count; i++) {
      items.push({ x: Math.random() * W, y: Math.random() * H, r: 0.7 + Math.random() * 2.0,
                   vx: -0.06 + Math.random() * 0.12, vy: -0.05 + Math.random() * 0.12,
                   phase: Math.random() * Math.PI * 2, alpha: 0.12 + Math.random() * 0.45 });
    }
    p = { items: items };
  }

  function drawMatrix(t) {
    if (!m || !mCtx) return;
    mCtx.clearRect(0, 0, W, H);
    mCtx.fillStyle = 'rgba(5,0,8,0.12)';
    mCtx.fillRect(0, 0, W, H);
    var d, x, y, trail = 8, j, yy, a;
    for (var i = 0; i < m.drops.length; i++) {
      d = m.drops[i]; x = i * m.fs; y = d.y;
      for (j = 0; j < trail; j++) {
        yy = y - j * (m.fs + 2);
        if (yy < -m.fs || yy > H + m.fs) continue;
        a = Math.max(0, d.alpha * (1 - j / trail));
        mCtx.fillStyle = 'rgba(186,125,255,' + a + ')';
        mCtx.fillText(glyph(d.seed + j * 7 + t * 0.002), x, yy);
      }
      d.y += d.speed;
      if (d.y > H + 60) { d.y = -Math.random() * 180; d.speed = 1.0 + Math.random() * 1.7;
        d.alpha = 0.06 + Math.random() * 0.10; d.seed = Math.random() * 1000; }
    }
  }

  function drawParticles(t) {
    if (!p || !pCtx) return;
    pCtx.clearRect(0, 0, W, H);
    var o, g;
    for (var i = 0; i < p.items.length; i++) {
      o = p.items[i];
      o.x += o.vx + Math.sin(t * 0.0012 + o.phase) * 0.10;
      o.y += o.vy + Math.cos(t * 0.001 + o.phase) * 0.07;
      if (o.x < -10) o.x = W + 10; if (o.x > W + 10) o.x = -10;
      if (o.y < -10) o.y = H + 10; if (o.y > H + 10) o.y = -10;
      g = 0.65 + 0.35 * Math.sin(t * 0.002 + o.phase);
      pCtx.beginPath();
      pCtx.arc(o.x, o.y, o.r * (0.9 + g * 0.5), 0, Math.PI * 2);
      pCtx.fillStyle = 'rgba(205,155,255,' + (o.alpha * g) + ')';
      pCtx.fill();
    }
  }

  function loop(t) {
    if (!running) return;
    if (t - last < FRAME_MS) { raf = requestAnimationFrame(loop); return; }  // FPS-бюджет
    last = t;
    try {
      drawMatrix(t);
      drawParticles(t);
    } catch (e) {                            // сбой отрисовки — гасим слой, страница живёт
      teardown();
      return;
    }
    raf = requestAnimationFrame(loop);
  }

  function start() {
    if (running) return;
    if (rm && rm.matches) return;            // reduced-motion — не запускаем
    try {
      initMatrix();
      initParticles();
    } catch (e) {                            // сбой canvas — тихо отключаемся, сайт работает
      teardown();
      return;
    }
    running = true; last = 0;
    raf = requestAnimationFrame(loop);
  }

  function stop() {
    running = false;
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }

  function teardown() {
    stop();
    if (mCanvas) { mCanvas.remove(); mCanvas = null; }
    if (pCanvas) { pCanvas.remove(); pCanvas = null; }
    m = p = mCtx = pCtx = null;
  }

  // resize (debounce) — пересобираем плотность/размеры
  var rt = 0;
  function onResize() {
    clearTimeout(rt);
    rt = setTimeout(function () {
      if (!running) return;
      try {
        initMatrix();
        initParticles();
      } catch (e) { teardown(); }            // сбой пере-инициализации — тихо отключаемся
    }, 220);
  }

  // пауза на невидимой вкладке (экономия батареи/CPU)
  function onVisibility() {
    if (document.hidden) stop();
    else if (!(rm && rm.matches)) { running = false; start(); }
  }

  // живая реакция на смену prefers-reduced-motion
  function onRMChange() {
    if (rm.matches) teardown();
    else start();
  }

  window.addEventListener('resize', onResize, { passive: true });
  document.addEventListener('visibilitychange', onVisibility);
  if (rm) { (rm.addEventListener ? rm.addEventListener('change', onRMChange)
                                 : rm.addListener && rm.addListener(onRMChange)); }

  start();
})();
