(() => {
  'use strict';

  const video = document.getElementById('video');
  const canvas = document.getElementById('tl');
  const ctx = canvas.getContext('2d');
  const statusEl = document.getElementById('status');
  const rejectEl = document.getElementById('reject');

  const C = {
    bg: '#1b1b1f',
    outside: 'rgba(0,0,0,0.38)',
    selection: 'rgba(255,255,255,0.075)',
    axis: '#2c2c33',
    peak: '#4a6cf7',
    rms: '#8aa4ff',
    handle: '#c9cbd6',
    handleSel: '#ff8c1a',
    playhead: '#f2f2f5',
    text: 'rgba(235,235,240,0.85)',
    textDim: 'rgba(200,200,210,0.55)',
    tick: 'rgba(255,255,255,0.14)',
  };
  const TOP = 22;      // pasek etykiet suwaków / playheada
  const BOTTOM = 20;   // pasek linijki i etykiety pod kursorem
  const GRIP_W = 12;
  const GRIP_H = 16;
  const HIT = 9;
  const EPS_MAX = 0.001;

  const S = {
    loaded: false,
    gen: 0,
    kind: 'video',
    duration: 0,
    frameStep: 1 / 30,
    frames: null,
    N: 1,
    wave: null,
    waveBin: 0.005,
    waveGain: 1,
    left: 0,
    right: 1,
    sel: null,
    drag: null,
    view: { start: 0, end: 1 },
    hoverX: null,
    hoverT: null,
    exporting: false,
    playing: false,
    lastT: 0,
    statusTimer: null,
  };

  // ---------- pomocnicze ----------
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const eps = () => Math.min(EPS_MAX, S.frameStep / 4);

  function frameTs(i) {
    if (i >= S.N) return S.duration;
    if (i <= 0) return 0;
    return S.frames ? S.frames[i] : i * S.frameStep;
  }

  function frameIndex(t) {
    if (t <= 0) return 0;
    if (t >= S.duration) return S.N;
    if (S.frames) {
      let lo = 0, hi = S.frames.length - 1;
      if (t >= S.frames[hi]) return hi;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (S.frames[mid] <= t + 1e-6) lo = mid; else hi = mid - 1;
      }
      return lo;
    }
    return clamp(Math.floor(t / S.frameStep + 1e-6), 0, S.N - 1);
  }

  function pad(n, w) { return String(n).padStart(w, '0'); }

  function fmt(t, withMs = true) {
    t = Math.max(0, t);
    const h = Math.floor(t / 3600);
    const m = Math.floor((t % 3600) / 60);
    const s = Math.floor(t % 60);
    const ms = Math.floor((t - Math.floor(t)) * 1000 + 1e-6);
    let out = S.duration >= 3600 ? `${h}:${pad(m, 2)}:${pad(s, 2)}` : `${pad(m, 2)}:${pad(s, 2)}`;
    if (withMs) out += '.' + pad(ms, 3);
    return out;
  }

  function cssWidth() { return canvas.clientWidth || 1; }
  function cssHeight() { return canvas.clientHeight || 110; }
  function xOf(t) { const v = S.view; return (t - v.start) / (v.end - v.start) * cssWidth(); }
  function tOf(x) { const v = S.view; return v.start + x / cssWidth() * (v.end - v.start); }

  function curTime() { return video.currentTime || 0; }

  function seek(t) {
    if (!S.loaded) return;
    const max = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : S.duration;
    try { video.currentTime = clamp(t, 0, max); } catch (e) { /* not ready */ }
  }

  function seekFrame(i) {
    if (i >= S.N) seek(S.duration);
    else seek(frameTs(i) + eps());
  }

  function pause() {
    S.playing = false;
    video.pause();
  }

  function play() {
    if (!S.loaded) return;
    const rt = frameTs(S.right);
    if (curTime() >= rt - eps() || video.ended) seekFrame(S.left);
    S.playing = true;
    S.lastT = curTime();
    const p = video.play();
    if (p && p.catch) p.catch(() => { S.playing = false; });
  }

  function togglePlay() {
    if (!S.loaded) return;
    if (S.playing && !video.paused) pause(); else play();
  }

  function setLeft(i) { S.left = clamp(i, 0, S.right - 1); }
  function setRight(i) { S.right = clamp(i, S.left + 1, S.N); }
  function handleIndex(kind) { return kind === 'left' ? S.left : S.right; }

  function moveHandleTo(kind, i, doSeek = true) {
    if (kind === 'left') setLeft(i); else setRight(i);
    if (doSeek) seekFrame(handleIndex(kind));
  }

  function ensureVisible(t) {
    const v = S.view;
    const span = v.end - v.start;
    if (span >= S.duration - 1e-9) return;
    if (t < v.start || t > v.end) {
      let start = clamp(t - span / 2, 0, S.duration - span);
      v.start = start; v.end = start + span;
      invalidateWave();
    }
  }

  // ---------- status w rogu ----------
  function showStatus(text, cls, ttl, hideAfter) {
    clearTimeout(S.statusTimer);
    statusEl.textContent = text;
    statusEl.className = cls || '';
    statusEl.title = ttl || '';
    statusEl.hidden = false;
    if (hideAfter) S.statusTimer = setTimeout(() => { statusEl.hidden = true; }, hideAfter);
  }
  function hideStatus() { clearTimeout(S.statusTimer); statusEl.hidden = true; }

  // ---------- wczytywanie ----------
  function onLoaded(info) {
    S.loaded = true;
    S.gen = info.gen;
    S.kind = info.kind;
    S.duration = info.duration;
    S.frameStep = info.frameStep > 0 ? info.frameStep : 1 / 30;
    S.frames = null;
    S.N = Math.max(1, Math.ceil(S.duration / S.frameStep - 1e-6));
    S.wave = null;
    S.waveGain = 1;
    S.waveBin = info.waveBinSec || 0.005;
    S.left = 0;
    S.right = S.N;
    S.sel = null;
    S.drag = null;
    S.view = { start: 0, end: S.duration };
    S.playing = false;
    S.lastT = 0;
    S.exporting = false;
    S.hoverX = null;
    S.hoverT = null;
    hideStatus();
    rejectEl.textContent = '';
    document.body.classList.add('loaded');
    document.body.classList.toggle('kind-audio', S.kind === 'audio');
    invalidateWave();
    video.pause();
    video.src = `/media?gen=${S.gen}`;
    video.load();
  }

  async function fetchFrames(gen) {
    try {
      const r = await fetch(`/api/frames?gen=${gen}`);
      if (!r.ok || r.status === 204 || gen !== S.gen) return;
      const buf = await r.arrayBuffer();
      if (gen !== S.gen || buf.byteLength < 16) return;
      const arr = new Float64Array(buf);
      const lt = frameTs(S.left);
      const rt = frameTs(S.right);
      const rightAtEnd = S.right >= S.N;
      S.frames = arr;
      S.N = arr.length;
      S.left = clamp(frameIndex(lt), 0, S.N - 1);
      S.right = rightAtEnd ? S.N : clamp(frameIndex(rt), S.left + 1, S.N);
    } catch (e) { /* ignoruj */ }
  }

  async function fetchWave(gen) {
    try {
      const r = await fetch(`/api/wave?gen=${gen}`);
      if (!r.ok || r.status === 204 || gen !== S.gen) return;
      const buf = await r.arrayBuffer();
      if (gen !== S.gen) return;
      S.wave = new Uint8Array(buf);
      let mx = 1;
      for (let i = 0; i < S.wave.length; i += 2) if (S.wave[i] > mx) mx = S.wave[i];
      S.waveGain = clamp(230 / mx, 1, 8);
      invalidateWave();
    } catch (e) { /* ignoruj */ }
  }

  window.ciachEvent = (ev) => {
    switch (ev.type) {
      case 'loaded': onLoaded(ev.info); break;
      case 'frames': fetchFrames(ev.gen); break;
      case 'wave': fetchWave(ev.gen); break;
      case 'reject':
        if (S.loaded) showStatus(ev.message, 'error', '', 4000);
        else rejectEl.textContent = ev.message;
        break;
      case 'export': onExport(ev); break;
    }
  };

  function fmtMB(bytes) {
    return (bytes / 1e6).toFixed(1).replace('.', ',') + ' MB';
  }

  function onExport(ev) {
    const small = ev.mode === 'small';
    const label = small ? 'Mały ciach' : 'Ciach';
    if (ev.state === 'progress') {
      S.exporting = true;
      const attempt = small && ev.attempt > 1 ? ` · próba ${ev.attempt}` : '';
      showStatus(`${label}… ${ev.percent}%${attempt}`, 'progress');
    } else if (ev.state === 'done') {
      S.exporting = false;
      const size = small && ev.size ? ` (${fmtMB(ev.size)})` : '';
      showStatus(`Gotowe ✓ ${ev.file}${size}`, 'done', '', 3000);
    } else if (ev.state === 'toobig') {
      S.exporting = false;
      showStatus(`Za duży ✕ ${fmtMB(ev.size)}`, 'error', `Zapisano ${ev.file}, ale plik przekracza limit 25 MB.`);
    } else if (ev.state === 'toolong') {
      S.exporting = false;
      showStatus('Za długi ✕', 'error', 'Fragment nie mieści się w 25 MB nawet przy 64 kbit/s.');
    } else if (ev.state === 'error') {
      S.exporting = false;
      showStatus('Błąd ✕', 'error', ev.message || '');
    }
  }

  function doExport(mode) {
    if (!S.loaded || S.exporting) return;
    if (!window.pywebview || !window.pywebview.api) return;
    S.exporting = true;
    showStatus(mode === 'small' ? 'Mały ciach… 0%' : 'Ciach… 0%', 'progress');
    const start = frameTs(S.left);
    const end = frameTs(S.right);
    window.pywebview.api.export(start, end, mode || 'full').then((r) => {
      if (r && r.ok === false) {
        S.exporting = false;
        showStatus('Błąd ✕', 'error', r.message || '');
      }
    }).catch((e) => {
      S.exporting = false;
      showStatus('Błąd ✕', 'error', String(e));
    });
  }

  // ---------- wideo ----------
  video.addEventListener('loadedmetadata', () => {
    try { video.currentTime = 0; } catch (e) { /* */ }
  });
  video.addEventListener('ended', () => {
    if (S.playing && S.right >= S.N) {
      seekFrame(S.left);
      const p = video.play();
      if (p && p.catch) p.catch(() => { S.playing = false; });
    } else {
      S.playing = false;
    }
  });
  video.addEventListener('pause', () => { if (!video.ended) S.playing = false; });
  video.addEventListener('error', () => {
    if (!S.loaded) return;
    showStatus('Nie da się odtworzyć tego pliku (nieobsługiwany kodek)', 'error', '');
  });

  function tick() {
    if (S.loaded && S.playing && !video.paused) {
      const t = curTime();
      const rt = frameTs(S.right);
      if (S.lastT < rt && t >= rt) {
        seekFrame(S.left);
        S.lastT = frameTs(S.left);
      } else {
        S.lastT = t;
      }
    }
    draw();
    requestAnimationFrame(tick);
  }

  // ---------- waveform cache ----------
  let waveCanvas = null;
  let waveKey = '';
  function invalidateWave() { waveKey = ''; }

  function buildWave(W, Hwave, dpr) {
    const key = `${S.gen}|${W}|${Hwave}|${dpr}|${S.view.start}|${S.view.end}|${S.wave ? S.wave.length : 0}|${S.waveGain}`;
    if (key === waveKey && waveCanvas) return;
    waveKey = key;
    if (!waveCanvas) waveCanvas = document.createElement('canvas');
    waveCanvas.width = Math.max(1, Math.round(W * dpr));
    waveCanvas.height = Math.max(1, Math.round(Hwave * dpr));
    const g = waveCanvas.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, Hwave);
    if (!S.wave || S.wave.length < 2) return;
    const nb = S.wave.length >> 1;
    const mid = Hwave / 2;
    const amp = Hwave / 2 - 2;
    const binSec = S.waveBin;
    const v = S.view;
    const secPerPx = (v.end - v.start) / W;
    const peakPath = new Path2D();
    const rmsPath = new Path2D();
    for (let x = 0; x < W; x++) {
      const t0 = v.start + x * secPerPx;
      const t1 = t0 + secPerPx;
      let b0 = Math.floor(t0 / binSec);
      let b1 = Math.floor(t1 / binSec);
      if (b1 < b0) b1 = b0;
      if (b0 < 0) b0 = 0;
      if (b0 >= nb) continue;
      if (b1 >= nb) b1 = nb - 1;
      let pk = 0, rm = 0;
      for (let b = b0; b <= b1; b++) {
        const p = S.wave[b * 2];
        const r = S.wave[b * 2 + 1];
        if (p > pk) pk = p;
        if (r > rm) rm = r;
      }
      const hp = Math.min(amp, Math.max(0.5, pk * S.waveGain / 255 * amp));
      const hr = Math.min(amp, Math.max(0.5, rm * S.waveGain / 255 * amp));
      peakPath.rect(x, mid - hp, 1, hp * 2);
      rmsPath.rect(x, mid - hr, 1, hr * 2);
    }
    g.fillStyle = C.peak;
    g.fill(peakPath);
    g.fillStyle = C.rms;
    g.fill(rmsPath);
  }

  // ---------- linijka ----------
  const STEPS = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200];
  function rulerStep(W) {
    const span = S.view.end - S.view.start;
    for (const s of STEPS) {
      if (s / span * W >= 90) return s;
    }
    return STEPS[STEPS.length - 1];
  }

  // ---------- rysowanie ----------
  function draw() {
    const dpr = window.devicePixelRatio || 1;
    const W = cssWidth();
    const H = cssHeight();
    const pw = Math.round(W * dpr), ph = Math.round(H * dpr);
    if (canvas.width !== pw || canvas.height !== ph) {
      canvas.width = pw; canvas.height = ph;
      invalidateWave();
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);
    if (!S.loaded) return;

    const waveTop = TOP;
    const waveH = H - TOP - BOTTOM;
    const waveBottom = waveTop + waveH;
    const xl = xOf(frameTs(S.left));
    const xr = xOf(frameTs(S.right));

    // zaznaczenie / poza zaznaczeniem
    ctx.fillStyle = C.selection;
    ctx.fillRect(clamp(xl, 0, W), waveTop, clamp(xr, 0, W) - clamp(xl, 0, W), waveH);
    // oś
    ctx.fillStyle = C.axis;
    ctx.fillRect(0, waveTop + waveH / 2 - 0.5, W, 1);
    // waveform
    buildWave(W, waveH, dpr);
    if (waveCanvas) ctx.drawImage(waveCanvas, 0, 0, waveCanvas.width, waveCanvas.height, 0, waveTop, W, waveH);
    // przyciemnienie poza zaznaczeniem
    ctx.fillStyle = C.outside;
    if (xl > 0) ctx.fillRect(0, waveTop, clamp(xl, 0, W), waveH);
    if (xr < W) ctx.fillRect(clamp(xr, 0, W), waveTop, W - clamp(xr, 0, W), waveH);

    // linijka
    const step = rulerStep(W);
    ctx.font = '10px "Segoe UI", system-ui, sans-serif';
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';
    const first = Math.ceil(S.view.start / step - 1e-9);
    const last = Math.floor(S.view.end / step + 1e-9);
    for (let k = first; k <= last; k++) {
      const t = k * step;
      const x = xOf(t);
      ctx.fillStyle = C.tick;
      ctx.fillRect(Math.round(x), waveBottom - 6, 1, 6);
      ctx.fillStyle = C.textDim;
      ctx.fillText(fmt(t, step < 1), x, waveBottom + BOTTOM / 2);
    }
    // długość całości (prawy dolny róg)
    ctx.textAlign = 'right';
    ctx.fillStyle = C.textDim;
    ctx.fillText(fmt(S.duration), W - 4, waveBottom + BOTTOM / 2);

    // suwaki
    for (const kind of ['left', 'right']) {
      const x = kind === 'left' ? xl : xr;
      if (x < -GRIP_W || x > W + GRIP_W) continue;
      const selected = S.sel === kind;
      const col = selected ? C.handleSel : C.handle;
      ctx.fillStyle = col;
      ctx.fillRect(Math.round(x) - 1, TOP - 2, 2, waveH + 2);
      const gx = kind === 'left' ? x : x - GRIP_W;
      roundRect(ctx, gx, TOP - GRIP_H + 2, GRIP_W, GRIP_H, 3);
      ctx.fill();
      ctx.fillStyle = 'rgba(0,0,0,0.35)';
      for (let i = 0; i < 2; i++) ctx.fillRect(gx + 4 + i * 3, TOP - GRIP_H + 6, 1, GRIP_H - 8);
    }

    // playhead
    const t = curTime();
    const xp = xOf(t);
    if (xp >= 0 && xp <= W) {
      ctx.fillStyle = C.playhead;
      ctx.fillRect(Math.round(xp), TOP - 2, 1, waveH + 2);
    }

    // etykiety u góry
    ctx.font = '11px "Segoe UI", system-ui, sans-serif';
    const labels = [];
    const active = S.drag && S.drag.kind !== 'scrub' ? S.drag.kind : S.sel;
    if (active) {
      const i = handleIndex(active);
      const x = active === 'left' ? xl : xr;
      labels.push({ x, text: `${fmt(frameTs(i))} · kl. ${i}`, col: C.handleSel, prio: 1 });
    }
    if (xp >= 0 && xp <= W) labels.push({ x: xp, text: fmt(t), col: C.text, prio: 0 });
    const gripBoxes = [];
    for (const kind of ['left', 'right']) {
      const x = kind === 'left' ? xl : xr;
      if (x < -GRIP_W || x > W + GRIP_W) continue;
      gripBoxes.push({ x: kind === 'left' ? x : x - GRIP_W, w: GRIP_W });
    }
    placeLabels(labels, W, gripBoxes);

    // czas pod kursorem
    if (S.hoverX != null && S.hoverT != null && !S.drag) {
      const text = fmt(S.hoverT);
      const tw = ctx.measureText(text).width + 8;
      const lx = clamp(S.hoverX - tw / 2, 0, W - tw);
      ctx.fillStyle = 'rgba(20,20,24,0.85)';
      roundRect(ctx, lx, waveBottom + 1, tw, BOTTOM - 2, 3);
      ctx.fill();
      ctx.fillStyle = C.text;
      ctx.textAlign = 'center';
      ctx.fillText(text, lx + tw / 2, waveBottom + BOTTOM / 2);
    }
  }

  function placeLabels(labels, W, reserved) {
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    const boxes = (reserved || []).map((b) => ({ x: b.x, w: b.w }));
    labels.sort((a, b) => b.prio - a.prio);
    for (const l of labels) {
      const tw = ctx.measureText(l.text).width + 8;
      let lx = clamp(l.x - tw / 2, 0, W - tw);
      for (let pass = 0; pass < 3; pass++) {
        let moved = false;
        for (const b of boxes) {
          if (lx < b.x + b.w + 2 && lx + tw > b.x - 2) {
            const goLeft = (l.x < b.x + b.w / 2) && (b.x - tw - 4 >= 0);
            lx = goLeft ? b.x - tw - 4 : b.x + b.w + 4;
            lx = clamp(lx, 0, W - tw);
            moved = true;
          }
        }
        if (!moved) break;
      }
      boxes.push({ x: lx, w: tw });
      ctx.fillStyle = 'rgba(20,20,24,0.85)';
      roundRect(ctx, lx, 2, tw, TOP - 5, 3);
      ctx.fill();
      ctx.fillStyle = l.col;
      ctx.fillText(l.text, lx + 4, 2 + (TOP - 5) / 2);
    }
  }

  function roundRect(g, x, y, w, h, r) {
    g.beginPath();
    g.moveTo(x + r, y);
    g.lineTo(x + w - r, y);
    g.quadraticCurveTo(x + w, y, x + w, y + r);
    g.lineTo(x + w, y + h - r);
    g.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    g.lineTo(x + r, y + h);
    g.quadraticCurveTo(x, y + h, x, y + h - r);
    g.lineTo(x, y + r);
    g.quadraticCurveTo(x, y, x + r, y);
    g.closePath();
  }

  // ---------- mysz ----------
  function hitHandle(mx) {
    const xl = xOf(frameTs(S.left));
    const xr = xOf(frameTs(S.right));
    const hl = Math.abs(mx - xl) <= HIT || (mx >= xl && mx <= xl + GRIP_W);
    const hr = Math.abs(mx - xr) <= HIT || (mx <= xr && mx >= xr - GRIP_W);
    if (hl && hr) return mx < (xl + xr) / 2 ? 'left' : 'right';
    if (hl) return 'left';
    if (hr) return 'right';
    return null;
  }

  function handleIndexFromX(kind, mx) {
    const t = tOf(mx);
    if (t >= S.duration) return S.N;
    if (t <= 0) return 0;
    return frameIndex(t);
  }

  canvas.addEventListener('pointerdown', (e) => {
    if (!S.loaded || e.button !== 0) return;
    try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* syntetyczne zdarzenia */ }
    const mx = e.offsetX;
    const h = hitHandle(mx);
    if (h) {
      pause();
      S.sel = h;
      S.drag = { kind: h };
      moveHandleTo(h, handleIndexFromX(h, mx));
    } else {
      S.sel = null;
      S.drag = { kind: 'scrub' };
      seek(clamp(tOf(mx), 0, S.duration));
    }
  });

  canvas.addEventListener('pointermove', (e) => {
    const mx = e.offsetX;
    S.hoverX = mx;
    S.hoverT = S.loaded ? clamp(tOf(mx), 0, S.duration) : null;
    if (!S.loaded) return;
    if (S.drag) {
      if (S.drag.kind === 'scrub') {
        seek(clamp(tOf(mx), 0, S.duration));
      } else {
        moveHandleTo(S.drag.kind, handleIndexFromX(S.drag.kind, mx));
      }
      canvas.style.cursor = 'grabbing';
    } else {
      canvas.style.cursor = hitHandle(mx) ? 'ew-resize' : 'default';
    }
  });

  function endDrag(e) {
    if (S.drag) {
      S.drag = null;
      try { canvas.releasePointerCapture(e.pointerId); } catch (err) { /* */ }
    }
  }
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);
  canvas.addEventListener('pointerleave', () => { S.hoverX = null; S.hoverT = null; });

  canvas.addEventListener('dblclick', () => {
    if (!S.loaded) return;
    S.view = { start: 0, end: S.duration };
    invalidateWave();
  });

  canvas.addEventListener('wheel', (e) => {
    if (!S.loaded) return;
    e.preventDefault();
    const v = S.view;
    const span = v.end - v.start;
    const delta = e.deltaY !== 0 ? e.deltaY : e.deltaX;
    if (e.shiftKey) {
      const shift = (delta / 100) * span * 0.1;
      const start = clamp(v.start + shift, 0, S.duration - span);
      S.view = { start, end: start + span };
    } else {
      const minSpan = Math.min(S.duration, Math.max(20 * S.frameStep, 0.2));
      const f = Math.pow(1.18, -delta / 100);
      const newSpan = clamp(span / f, minSpan, S.duration);
      const t = tOf(e.offsetX);
      let start = t - (t - v.start) * (newSpan / span);
      start = clamp(start, 0, S.duration - newSpan);
      S.view = { start, end: start + newSpan };
    }
    invalidateWave();
    S.hoverT = clamp(tOf(e.offsetX), 0, S.duration);
  }, { passive: false });

  window.addEventListener('resize', () => invalidateWave());
  document.addEventListener('contextmenu', (e) => e.preventDefault());

  // ---------- klawiatura ----------
  const rep = { timer: null, fn: null };
  function stopRepeat() {
    if (rep.timer) clearTimeout(rep.timer);
    rep.timer = null; rep.fn = null;
  }
  function startRepeat(fn) {
    stopRepeat();
    rep.fn = fn;
    let delay = 120;
    const loop = () => {
      if (rep.fn !== fn) return;
      fn();
      delay = Math.max(16, delay * 0.85);
      rep.timer = setTimeout(loop, delay);
    };
    rep.timer = setTimeout(loop, 500);
  }

  function stepBy(dir, big) {
    if (!S.loaded) return;
    const n = big ? Math.max(1, Math.round(1 / S.frameStep)) : 1;
    if (S.sel) {
      const i = handleIndex(S.sel) + dir * n;
      moveHandleTo(S.sel, i);
      ensureVisible(frameTs(handleIndex(S.sel)));
      return;
    }
    if (S.playing) pause();
    const t = curTime();
    let i = frameIndex(t);
    if (i >= S.N) i = S.N - 1;
    let target;
    if (dir < 0 && t > frameTs(i) + 2 * eps() && !big) target = i;
    else target = i + dir * n;
    target = clamp(target, 0, S.N - 1);
    seekFrame(target);
    ensureVisible(frameTs(target));
  }

  window.addEventListener('keydown', (e) => {
    if ((e.code === 'Enter' || e.code === 'NumpadEnter') && e.ctrlKey && !e.altKey && !e.metaKey) {
      e.preventDefault();
      if (!e.repeat) doExport('small');
      return;
    }
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    switch (e.code) {
      case 'Space':
        e.preventDefault();
        if (!e.repeat) togglePlay();
        break;
      case 'ArrowLeft':
      case 'ArrowRight': {
        e.preventDefault();
        if (e.repeat) return;
        const dir = e.code === 'ArrowLeft' ? -1 : 1;
        const big = e.shiftKey;
        stepBy(dir, big);
        startRepeat(() => stepBy(dir, big));
        break;
      }
      case 'Enter':
      case 'NumpadEnter':
        e.preventDefault();
        if (!e.repeat) doExport('full');
        break;
      case 'Escape':
        S.sel = null;
        break;
      case 'Home':
        e.preventDefault();
        if (S.sel) moveHandleTo(S.sel, 0); else { pause(); seekFrame(0); }
        break;
      case 'End':
        e.preventDefault();
        if (S.sel) moveHandleTo(S.sel, S.N); else { pause(); seekFrame(S.N - 1); }
        break;
    }
  });
  window.addEventListener('keyup', (e) => {
    if (e.code === 'ArrowLeft' || e.code === 'ArrowRight') stopRepeat();
  });
  window.addEventListener('blur', stopRepeat);

  // ---------- drag & drop ----------
  let dragDepth = 0;
  window.addEventListener('dragenter', (e) => {
    e.preventDefault();
    dragDepth++;
    document.body.classList.add('dragover');
  });
  window.addEventListener('dragover', (e) => {
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
  });
  window.addEventListener('dragleave', (e) => {
    e.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) document.body.classList.remove('dragover');
  });
  window.addEventListener('drop', (e) => {
    e.preventDefault();
    dragDepth = 0;
    document.body.classList.remove('dragover');
  });

  // ---------- start ----------
  function announceReady() {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.ready().catch(() => {});
    }
  }
  if (window.pywebview && window.pywebview.api) announceReady();
  else window.addEventListener('pywebviewready', announceReady);

  window.__ciach = { S, frameTs, frameIndex, video };
  requestAnimationFrame(tick);
})();
