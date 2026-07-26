/* ObsidianExchange — v5 runtime: ambient (matrix+частицы), reveal, Lucide, мобильное меню.
   Ambient взят из пака v5, но усилен прод-гардами: DPR≤1.5, потолок FPS, пауза на
   невидимой вкладке, prefers-reduced-motion (живая подписка), try/catch → тихий teardown.
   При любой ошибке страница полностью работает — это необязательный слой. */
(function () {
  'use strict';

  // ── мобильное меню (замена Alpine x-data) ──
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-nav-toggle]');
    if (t) { var l = document.querySelector('.navlinks'); if (l) l.classList.toggle('open'); return; }
    if (!e.target.closest('.navlinks') && !e.target.closest('[data-nav-toggle]')) {
      var lk = document.querySelector('.navlinks.open'); if (lk) lk.classList.remove('open');
    }
  });

  // ── reveal-анимация секций ──
  try {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
    }, { threshold: .12 });
    document.querySelectorAll('.reveal').forEach(function (e) { io.observe(e); });
  } catch (e) {}

  // ── Lucide иконки ──
  function icons() { try { if (window.lucide) window.lucide.createIcons(); } catch (e) {} }
  if (document.readyState !== 'loading') icons();
  else document.addEventListener('DOMContentLoaded', icons);
  window.addEventListener('load', icons);

  // ── Ambient (matrix + particles) ──
  var matrix = document.getElementById('matrix'), particles = document.getElementById('particles');
  if (!matrix && !particles) return;

  var rm = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
  var small = window.matchMedia ? window.matchMedia('(max-width: 600px)') : { matches: false };
  var DPR = Math.min(window.devicePixelRatio || 1, 1.5);
  var FRAME_MS = 1000 / 30;
  var W = 0, H = 0, mctx = null, pctx = null, drops = [], parts = [];
  var raf = 0, last = 0, running = false;

  function fit() {
    W = window.innerWidth; H = window.innerHeight;
    [matrix, particles].forEach(function (c) {
      if (!c) return;
      c.width = Math.floor(W * DPR); c.height = Math.floor(H * DPR);
      c.style.width = W + 'px'; c.style.height = H + 'px';
      var x = c.getContext('2d'); x.setTransform(DPR, 0, 0, DPR, 0, 0);
      if (c === matrix) mctx = x; else pctx = x;
    });
    drops = [];
    var cols = Math.ceil(W / 17);
    for (var i = 0; i < cols; i++) drops.push({ y: Math.random() * -H, s: 1.6 + Math.random() * 2.0, a: .09 + Math.random() * .17, q: Math.random() * 9000 });
    parts = [];
    var pn = small.matches ? 0 : Math.min(120, Math.max(70, Math.floor(W / 12)));
    for (var j = 0; j < pn; j++) parts.push({ x: Math.random() * W, y: Math.random() * H, r: .7 + Math.random() * 1.9, vx: -.10 + Math.random() * .20, vy: -.07 + Math.random() * .14, p: Math.random() * 6.28, a: .12 + Math.random() * .40 });
  }

  var CH = '0101BTCUSDTLTC<>/[]{}░▒▓+-';
  function glyph(s) { return CH[Math.floor((Math.sin(s) * 10000 % 1 + 1) % 1 * CH.length)] || '0'; }

  function dm(t) {
    if (!mctx) return;
    mctx.clearRect(0, 0, W, H);
    mctx.fillStyle = 'rgba(5,3,10,.10)'; mctx.fillRect(0, 0, W, H);
    mctx.font = '700 15px monospace';
    for (var i = 0; i < drops.length; i++) {
      var d = drops[i], x = i * 17;
      for (var k = 0; k < 10; k++) {
        var y = d.y - k * 20; if (y < -30 || y > H + 30) continue;
        mctx.fillStyle = 'rgba(196,140,255,' + Math.max(0, d.a * (1 - k / 10)) + ')';
        mctx.fillText(glyph(d.q + k * 7 + t * .002), x, y);
      }
      d.y += d.s;
      if (d.y > H + 60) { d.y = -Math.random() * 180; d.s = 1.6 + Math.random() * 2.0; d.a = .09 + Math.random() * .17; }
    }
  }
  function dp(t) {
    if (!pctx) return;
    pctx.clearRect(0, 0, W, H);
    for (var i = 0; i < parts.length; i++) {
      var o = parts[i];
      o.x += o.vx + Math.sin(t * .0012 + o.p) * .12;
      o.y += o.vy + Math.cos(t * .001 + o.p) * .08;
      if (o.x < -20) o.x = W + 20; if (o.x > W + 20) o.x = -20;
      if (o.y < -20) o.y = H + 20; if (o.y > H + 20) o.y = -20;
      var g = .6 + .4 * Math.sin(t * .002 + o.p);
      pctx.beginPath(); pctx.arc(o.x, o.y, o.r * (.9 + g * .4), 0, 6.28);
      pctx.fillStyle = 'rgba(220,184,255,' + (o.a * g) + ')'; pctx.fill();
    }
  }

  function loop(t) {
    if (!running) return;
    if (t - last < FRAME_MS) { raf = requestAnimationFrame(loop); return; }
    last = t;
    try { dm(t); dp(t); } catch (e) { teardown(); return; }
    raf = requestAnimationFrame(loop);
  }
  function start() {
    if (running || (rm && rm.matches)) return;
    try { fit(); } catch (e) { teardown(); return; }
    running = true; last = 0; raf = requestAnimationFrame(loop);
  }
  function stop() { running = false; if (raf) cancelAnimationFrame(raf); raf = 0; }
  function teardown() { stop(); mctx = pctx = null; }

  var rt = 0;
  window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(function () { if (running) { try { fit(); } catch (e) { teardown(); } } }, 220); }, { passive: true });
  document.addEventListener('visibilitychange', function () { if (document.hidden) stop(); else if (!(rm && rm.matches)) { running = false; start(); } });
  window.addEventListener('pagehide', teardown);
  if (rm && rm.addEventListener) rm.addEventListener('change', function () { if (rm.matches) teardown(); else start(); });

  start();
})();
