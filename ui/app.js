(() => {
  'use strict';

  const video = document.getElementById('video');
  const canvas = document.getElementById('tl');
  const timelineEl = document.getElementById('timeline');
  const previewEl = document.getElementById('preview');
  const ctx = canvas.getContext('2d');
  const statusEl = document.getElementById('status');
  const rejectEl = document.getElementById('reject');
  const ov = document.getElementById('ov');       // nakładka Kadrów na podglądzie
  const octx = ov.getContext('2d');

  const C = {
    bg: '#1b1b1f',
    rowBg: '#17171b',
    outside: 'rgba(0,0,0,0.38)',
    beyond: 'rgba(0,0,0,0.5)',
    selection: 'rgba(255,255,255,0.075)',
    current: 'rgba(255,255,255,0.045)',
    axis: '#2c2c33',
    peak: '#4a6cf7',
    rms: '#8aa4ff',
    podFill: 'rgba(74,108,247,0.16)',
    podBorder: 'rgba(138,164,255,0.55)',
    podPeak: '#5aa86a',
    podRms: '#9ad8a4',
    zoomFill: 'rgba(255,140,26,0.16)',
    zoomBorder: 'rgba(255,170,90,0.6)',
    kadr: '#ff8c1a',
    kadrGhost: 'rgba(210,210,220,0.75)',
    kadrNow: 'rgba(255,255,255,0.75)',
    handle: '#c9cbd6',
    handleSel: '#ff8c1a',
    playhead: '#f2f2f5',
    styk: 'rgba(255,255,255,0.35)',
    seam: 'rgba(255,255,255,0.22)',
    gniazdo: 'rgba(255,255,255,0.14)',
    gniazdoHot: 'rgba(255,140,26,0.4)',
    gniazdoBorder: 'rgba(255,255,255,0.45)',
    cutFill: 'rgba(235,64,52,0.30)',
    cutBorder: '#ff5a4e',
    cutHot: '#ffd3cf',
    text: 'rgba(235,235,240,0.85)',
    textDim: 'rgba(200,200,210,0.55)',
    tick: 'rgba(255,255,255,0.14)',
  };
  const TOP = 22;      // pasek etykiet suwaków / playheada
  const VID_H = 68;    // wiersz Sekwencji (waveform)
  const ROW_H = 44;    // wiersz jednego Podkładu
  const ZOOM_H = 30;   // wiersz Zbliżeń
  const KADR_MIN = 0.2; // najmniejszy Kadr: 20 % obrazu (5×)
  const CORNER = 7;    // uchwyt rogu Kadru na podglądzie (px CSS)
  const STRIP_H = 24;  // Gniazdo na nowy Podkład (tylko podczas przeciągania)
  const BOTTOM = 20;   // pasek linijki i etykiety pod kursorem
  const GRIP_W = 12;
  const GRIP_H = 16;
  const HIT = 9;
  const GN_W = 24;     // szerokość Gniazda na Styku
  const SNAP_PX = 8;   // próg Przyciągania (px CSS, więc niezależny od DPI)
  const CUT_MIN_PX = 40; // domyślna szerokość nowego Wycięcia: oba uchwyty do złapania osobno
  const EPS_MAX = 0.001;
  const VOL_LABEL_MS = 1500;
  const UNDO_MAX = 100;
  const CUT_BLOCK = 'Najpierw wytnij (Delete) albo porzuć (Esc)';

  // Dwa czasy (ADR 0002): czas PLIKU (pts Klatek w pliku, którym karmimy <video> i ffmpeg) i czas
  // SEKWENCJI (to, co widać na timeline: plik bez dziur po Wycięciach). Klatki Sekwencji to
  // zachowane Klatki pliku, numerowane od 0 (`S.frames[i]` = pts w pliku, `S.seqs[i]` = czas
  // Sekwencji). Suwaki i Wycięcie to indeksy Klatek; Zbliżenia i zaczep Podkładu (`at`) trzymają
  // pts pliku, bo te nie zmieniają się przy Wycięciu; długości (Rampy, Podkłady) są w sekundach Sekwencji.
  const S = {
    loaded: false,
    gen: 0,
    kind: 'video',
    duration: 0,     // długość Sekwencji (bez dziur)
    fileDuration: 0, // długość pliku
    frameStep: 1 / 30,
    fileFrames: null, // pts wszystkich Klatek pliku ze skanu (null: siatka z fps)
    scanned: false,
    frames: null,    // pts Klatek Sekwencji (zachowanych) w pliku
    seqs: null,      // czas Sekwencji Klatek, N+1 wpisów (ostatni = długość Sekwencji)
    endPts: 0,       // czas pliku tuż za ostatnią Klatką Sekwencji
    headAtZero: true, // pierwsza Klatka Sekwencji to pierwsza Klatka pliku (Ciach od 0, z całym dźwiękiem)
    pieces: [],      // Nagrania jako zakresy indeksów Klatek: {ia, ib} (ib wyłącznie)
    N: 1,
    wave: null,
    waveBin: 0.005,
    waveGain: 1,
    left: 0,
    right: 1,
    // zaznaczenie: null (fokus na wideo) | 'left' | 'right' | {pod: gen, edge: null|'in'|'out'}
    //              | {zoom: id, part: null|'in'|'out'|'rin'|'rout'}
    sel: null,
    width: 0,        // rozmiar obrazu Sekwencji (Kadry są ułamkami tych wymiarów)
    height: 0,
    zooms: [],       // Zbliżenia: {id, at, end, rin, rout, keys:[{t, k:{x,y,s}}]}; at/end/t = pts Klatek
    zoomSeq: 0,
    zKey: false,     // przytrzymane Z: rysowanie Kadru na podglądzie
    pdrag: null,     // przeciąganie na podglądzie: {kind:'draw'|'move'|'resize', ...}
    drag: null,
    view: { start: 0, end: 1 },
    viewFull: true,
    hoverX: null,
    hoverT: null,
    exporting: false,
    playing: false,
    lastT: 0,
    statusTimer: null,
    parts: [],       // Nagrania w Sekwencji: {name, src, start, duration, in, out} (start = kopia w pliku)
    gain: 1,         // Głośność Sekwencji
    pods: [],        // Podkłady: {gen, name, duration, at, segs:[{tin, tout}], gain, wave, waveGain, waveBin, audio}
    cut: null,       // Wycięcie: {pod: gen|null, a, b} — Klatki [a, b) Sekwencji (na Podkładzie: pod nim)
    undo: [],        // Cofnięcie: migawki sprzed wykonanych Wycięć i usunięć Nagrań
    busy: false,     // sklejanie w toku
    dragOver: null,  // {x, y, mp4, mp3} podczas przeciągania pliku z zewnątrz
    pendingShift: null,
    restoreT: null,
    volLabel: null,  // {until, text, pod}
    lastDrop: null,
  };

  // ---------- pomocnicze ----------
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const eps = () => Math.min(EPS_MAX, S.frameStep / 4);
  const extOf = (p) => (String(p).match(/\.[^.\\/]+$/) || [''])[0].toLowerCase();
  const seqExt = () => (S.kind === 'video' ? '.mp4' : '.mp3');

  // ---------- Klatki Sekwencji ----------
  function frameTs(i) {
    if (i >= S.N) return S.endPts;
    if (i <= 0) return S.frames ? S.frames[0] : 0;
    return S.frames[i];
  }

  // Ostatnia Klatka o pts <= t (w dziurze: Klatka sprzed niej); t za końcem → N.
  function frameIndex(t) {
    const F = S.frames;
    if (!F || t <= F[0]) return 0;
    if (t >= S.endPts) return S.N;
    let lo = 0, hi = S.N - 1;
    if (t >= F[hi]) return hi;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (F[mid] <= t + 1e-6) lo = mid; else hi = mid - 1;
    }
    return lo;
  }

  // Czas pliku tuż za Klatką i: następna Klatka pliku (początek dziury, gdy za i jest Wycięcie).
  function frameEnd(i) { return S.frames[i] + (S.seqs[i + 1] - S.seqs[i]); }

  // Najbliższa Klatka dla wartości, która już leżała na Klatce (po remapie sklejania albo skanie
  // Klatek siatka z fps i prawdziwe pts różnią się o ułamek Klatki; „ostatnia ≤ t” myliłaby się o jedną).
  function nearestIdx(t) {
    const i = clamp(frameIndex(t), 0, S.N - 1);
    return i + 1 < S.N && Math.abs(S.frames[i + 1] - t) < Math.abs(S.frames[i] - t) ? i + 1 : i;
  }
  function nearestEndIdx(t) {
    const i = frameIndex(t);
    if (i >= S.N) return S.N;
    const nxt = i + 1 < S.N ? S.frames[i + 1] : S.endPts;
    return Math.abs(nxt - t) < Math.abs(S.frames[i] - t) ? i + 1 : i;
  }

  // Czas pliku → czas Sekwencji (w dziurze: szew).
  function seqOf(t) {
    if (!S.frames) return t;
    const i = frameIndex(t);
    if (i >= S.N) return S.duration;
    return S.seqs[i] + clamp(t - S.frames[i], 0, S.seqs[i + 1] - S.seqs[i]);
  }

  // Ostatnia Klatka o czasie Sekwencji <= s; s za końcem → N.
  function ordAtS(s) {
    const Q = S.seqs;
    if (!Q || s <= 0) return 0;
    if (s >= S.duration) return S.N;
    let lo = 0, hi = S.N - 1;
    if (s >= Q[hi]) return hi;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (Q[mid] <= s + 1e-6) lo = mid; else hi = mid - 1;
    }
    return lo;
  }

  // Czas Sekwencji → czas pliku (na szwie: pierwsza Klatka za dziurą).
  function fileOf(s) {
    if (!S.frames) return s;
    const i = ordAtS(s);
    if (i >= S.N) return S.endPts;
    return S.frames[i] + (s - S.seqs[i]);
  }

  // Najbliższa granica Klatki (dla prawych Krawędzi, wyłącznych).
  function endIndexAtS(s) {
    if (s >= S.duration) return S.N;
    const i = ordAtS(Math.max(0, s));
    return s - S.seqs[i] > (S.seqs[i + 1] - S.seqs[i]) / 2 ? i + 1 : i;
  }

  // Klatki Sekwencji z Nagrań (`S.parts`) i Klatek pliku (skan albo siatka z fps).
  function rebuildKept() {
    let F = S.fileFrames;
    if (!F) {
      const n = Math.max(1, Math.ceil(S.fileDuration / S.frameStep - 1e-6));
      F = new Float64Array(n);
      for (let k = 0; k < n; k++) F[k] = k * S.frameStep;
    }
    const nF = F.length;
    const atOrAfter = (t) => {
      let lo = 0, hi = nF;
      while (lo < hi) { const mid = (lo + hi) >> 1; if (F[mid] < t - 1e-4) lo = mid + 1; else hi = mid; }
      return lo;
    };
    const kept = [], dur = [], pieces = [];
    for (const p of S.parts) {
      const fa = atOrAfter(p.start + p.in), fb = Math.min(nF, atOrAfter(p.start + p.out));
      if (fb <= fa) continue;
      pieces.push({ ia: kept.length, ib: kept.length + (fb - fa), fa, fb });
      for (let k = fa; k < fb; k++) { kept.push(F[k]); dur.push((k + 1 < nF ? F[k + 1] : S.fileDuration) - F[k]); }
    }
    if (!kept.length) {
      pieces.length = 0;
      pieces.push({ ia: 0, ib: nF, fa: 0, fb: nF });
      for (let k = 0; k < nF; k++) { kept.push(F[k]); dur.push((k + 1 < nF ? F[k + 1] : S.fileDuration) - F[k]); }
    }
    // Pierwsza Klatka pliku ma pts ~0,02 (opóźnienie kodera AAC w sklejce): zostaje takie, jakie jest,
    // żeby pozycje na Klatkach przeżywały remap po sklejeniu; Ciach od początku zaczyna mimo to od 0.
    S.headAtZero = pieces[0].fa === 0;
    const N = kept.length;
    S.frames = Float64Array.from(kept);
    const seqs = new Float64Array(N + 1);
    for (let i = 0; i < N; i++) seqs[i + 1] = seqs[i] + Math.max(0, dur[i]);
    S.seqs = seqs;
    S.N = N;
    S.duration = seqs[N];
    const last = pieces[pieces.length - 1];
    S.endPts = last.fb < nF ? F[last.fb] : S.fileDuration;
    S.pieces = pieces.map((p) => ({ ia: p.ia, ib: p.ib }));
  }

  // Dziury (wykonane Wycięcia) w czasie pliku wewnątrz Klatek [a, b): to dostaje ffmpeg.
  function holesIn(a, b) {
    const out = [];
    for (let i = a; i < b; i++) {
      const next = i + 1 < S.N ? S.frames[i + 1] : S.endPts;
      const e = frameEnd(i);
      if (next - e > 1e-6) out.push([e, next]);
    }
    return out;
  }

  function pieceIndexAt(i) {
    for (let k = 0; k < S.pieces.length; k++) if (i < S.pieces[k].ib) return k;
    return S.pieces.length - 1;
  }

  function pad(n, w) { return String(n).padStart(w, '0'); }

  function fmt(t, withMs = true) {
    t = Math.max(0, t);
    const h = Math.floor(t / 3600);
    const m = Math.floor((t % 3600) / 60);
    const s = Math.floor(t % 60);
    const ms = Math.floor((t - Math.floor(t)) * 1000 + 1e-6);
    let out = extent() >= 3600 ? `${h}:${pad(m, 2)}:${pad(s, 2)}` : `${pad(m, 2)}:${pad(s, 2)}`;
    if (withMs) out += '.' + pad(ms, 3);
    return out;
  }
  function fmtKl(n) {
    const d = n % 10, h = n % 100;
    return `${n} ${n === 1 ? 'Klatka' : d >= 2 && d <= 4 && (h < 12 || h > 14) ? 'Klatki' : 'Klatek'}`;
  }

  // ---------- Podkłady: odcinki ----------
  // Podkład gra `segs` (odcinki mp3) po kolei, zaczynając w Klatce `at`; Wycięcie na Podkładzie usuwa
  // kawałek odcinka, a reszta muzyki dosuwa się. Czasy Podkładu na timeline to sekundy Sekwencji.
  function podLen(p) { let L = 0; for (const s of p.segs) L += s.tout - s.tin; return L; }
  function podStart(p) { return seqOf(p.at); }
  function podEnd(p) { return podStart(p) + podLen(p); }
  function podByGen(gen) { return S.pods.find((p) => p.gen === gen) || null; }
  function selPod() { return S.sel && typeof S.sel === 'object' && S.sel.pod != null ? podByGen(S.sel.pod) : null; }
  // Czas w mp3 dla odległości `u` od początku Podkładu (null poza nim).
  function podContent(p, u) {
    if (u < 0) return null;
    for (const s of p.segs) {
      const L = s.tout - s.tin;
      if (u < L) return s.tin + u;
      u -= L;
    }
    return null;
  }
  // Niewykonane Wycięcie na Podkładzie jako odległości od jego początku [ua, ub).
  function cutPodRange(p) {
    const c = S.cut;
    if (!c || c.pod !== p.gen) return null;
    const s0 = podStart(p), L = podLen(p);
    return [clamp(S.seqs[c.a] - s0, 0, L), clamp(S.seqs[c.b] - s0, 0, L)];
  }
  // Odcinki bez [ua, ub) (odległości od początku Podkładu); sąsiednie ciągłe w mp3 łączą się z powrotem.
  function cutSegs(segs, ua, ub) {
    const out = [];
    let off = 0;
    for (const s of segs) {
      const L = s.tout - s.tin;
      const a = Math.max(ua, off), b = Math.min(ub, off + L);
      if (b <= a + 1e-9) out.push({ tin: s.tin, tout: s.tout });
      else {
        if (a > off + 1e-9) out.push({ tin: s.tin, tout: s.tin + (a - off) });
        if (b < off + L - 1e-9) out.push({ tin: s.tin + (b - off), tout: s.tout });
      }
      off += L;
    }
    const merged = [];
    for (const s of out) {
      if (merged.length && Math.abs(merged[merged.length - 1].tout - s.tin) < 1e-6) merged[merged.length - 1].tout = s.tout;
      else merged.push(s);
    }
    return merged;
  }

  // ---------- Zbliżenia: Kadry ----------
  const FULL = { x: 0, y: 0, s: 1 };
  function zoomById(id) { return S.zooms.find((z) => z.id === id) || null; }
  function selZoom() { return S.sel && typeof S.sel === 'object' && S.sel.zoom != null ? zoomById(S.sel.zoom) : null; }
  function zoomLen(z) { return seqOf(z.end) - seqOf(z.at); }
  function zoomAt(t) { return S.zooms.find((z) => t >= z.at - 1e-6 && t < z.end - 1e-6) || null; }
  function sameKadr(a, b) { return Math.abs(a.x - b.x) < 1e-4 && Math.abs(a.y - b.y) < 1e-4 && Math.abs(a.s - b.s) < 1e-4; }
  function lerpKadr(a, b, f) { return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, s: a.s + (b.s - a.s) * f }; }
  function clampKadr(k) {
    k.s = clamp(k.s, KADR_MIN, 1);
    k.x = clamp(k.x, 0, 1 - k.s);
    k.y = clamp(k.y, 0, 1 - k.s);
    return k;
  }
  // Zapamiętane pozycje Kadru `z.keys` (po czasie). Przed pierwszą i za ostatnią Kadr stoi,
  // między dwiema przejeżdża liniowo w czasie Sekwencji. Użytkownik nie widzi „pozycji”, widzi Kadr na każdej Klatce.
  function keyIndex(z, t) {
    let i = 0;
    while (i + 1 < z.keys.length && z.keys[i + 1].t <= t + 1e-6) i++;
    return i;
  }
  function kadrKeys(z, t) {
    const ks = z.keys;
    if (t <= ks[0].t + 1e-6) return { ...ks[0].k };
    const last = ks[ks.length - 1];
    if (t >= last.t - 1e-6) return { ...last.k };
    const i = keyIndex(z, t);
    const a = ks[i], b = ks[i + 1];
    if (Math.abs(a.t - t) < 1e-6) return { ...a.k };
    const span = seqOf(b.t) - seqOf(a.t);
    return lerpKadr(a.k, b.k, span > 1e-9 ? clamp((seqOf(t) - seqOf(a.t)) / span, 0, 1) : 1);
  }
  // Czy w chwili t Kadr stoi (pozycja ustawiona albo trzymana), czy przejeżdża.
  function kadrHolds(z, t) {
    const ks = z.keys;
    if (t <= ks[0].t + 1e-6 || t >= ks[ks.length - 1].t - 1e-6) return true;
    const i = keyIndex(z, t);
    return Math.abs(ks[i].t - t) < 1e-6 || sameKadr(ks[i].k, ks[i + 1].k);
  }
  function rampFactor(z, t) {
    const L = zoomLen(z), u = seqOf(t) - seqOf(z.at);
    if (z.rin > 0 && u < z.rin) return clamp(u / z.rin, 0, 1);
    if (z.rout > 0 && u > L - z.rout) return clamp((L - u) / z.rout, 0, 1);
    return 1;
  }
  // Kadr widziany w chwili t (null = cały obraz): pozycja z Klatki, w Rampie rozciągnięta w stronę całości.
  function kadrAt(z, t) {
    const u = seqOf(t) - seqOf(z.at);
    if (u < -1e-6 || u >= zoomLen(z) - 1e-6) return null;
    const f = rampFactor(z, t);
    const k = kadrKeys(z, t);
    return f >= 1 ? k : lerpKadr(FULL, k, f);
  }
  function kadrNow(t) { const z = zoomAt(t); return z ? kadrAt(z, t) : null; }
  function setKey(z, t, k) {
    t = quantAt(t);
    k = clampKadr({ ...k });
    const i = z.keys.findIndex((q) => Math.abs(q.t - t) < 1e-6);
    if (i >= 0) z.keys[i].k = k; else { z.keys.push({ t, k }); z.keys.sort((p, q) => p.t - q.t); }
  }
  // Po zmianie przedziału: pozycje poza nim przepadają, a na nowej granicy zostaje to, co Kadr tam pokazywał.
  function trimKeys(z) {
    const lastT = frameTs(Math.max(frameIndex(z.at), frameIndex(z.end) - 1));
    const before = z.keys.some((q) => q.t < z.at - 1e-6);
    const after = z.keys.some((q) => q.t > lastT + 1e-6);
    const kA = kadrKeys(z, z.at), kB = kadrKeys(z, lastT);
    z.keys = z.keys.filter((q) => q.t >= z.at - 1e-6 && q.t <= lastT + 1e-6);
    if (before || !z.keys.length) setKey(z, z.at, kA);
    if (after) setKey(z, lastT, kB);
  }
  function fmtFactor(k) { return (1 / k.s).toFixed(1).replace('.', ',') + '×'; }
  function fmtZoomLabel(z) {
    const ks = z.keys, n = ks.length;
    const first = fmtFactor(ks[0].k), last = fmtFactor(ks[n - 1].k);
    let out = n > 1 && !sameKadr(ks[0].k, ks[n - 1].k) ? `${first} → ${last}` : first;
    if (n > 2) {
      const d = n % 10, h = n % 100;
      out += ` · ${n} ${d >= 2 && d <= 4 && (h < 12 || h > 14) ? 'Kadry' : 'Kadrów'}`;
    }
    return out;
  }

  // Zakres timeline'u (czas Sekwencji): Sekwencja albo najdalej wystający Podkład.
  function extent() {
    let e = S.duration;
    for (const p of S.pods) e = Math.max(e, podEnd(p));
    return e;
  }

  function fitView() {
    const ext = extent();
    if (S.viewFull) { S.view = { start: 0, end: ext }; return; }
    const v = S.view;
    let span = Math.min(v.end - v.start, ext);
    let start = clamp(v.start, 0, ext - span);
    if (span >= ext - 1e-9) { S.viewFull = true; start = 0; span = ext; }
    if (start !== v.start || start + span !== v.end) { S.view = { start, end: start + span }; invalidateWave(); }
  }

  function cssWidth() { return canvas.clientWidth || 1; }
  // Piksel ↔ czas Sekwencji (xS/sOf); xOf/tOf przyjmują i zwracają czas pliku.
  function xS(s) { const v = S.view; return (s - v.start) / (v.end - v.start) * cssWidth(); }
  function sOf(x) { const v = S.view; return v.start + x / cssWidth() * (v.end - v.start); }
  function xOf(t) { return xS(seqOf(t)); }
  function tOf(x) { return fileOf(clamp(sOf(x), 0, S.duration)); }

  // Układ pionowy: wiersz Sekwencji, (wiersz Zbliżeń), wiersze Podkładów, (pasek Gniazda), linijka.
  function zoomRowWanted() { return S.kind === 'video' && S.zooms.length > 0; }
  function layout(withStrip) {
    const rows = [];
    let y = TOP + VID_H;
    let zoomRow = null;
    if (zoomRowWanted()) { zoomRow = { top: y, h: ZOOM_H }; y += ZOOM_H; }
    for (const p of S.pods) { rows.push({ gen: p.gen, top: y, h: ROW_H }); y += ROW_H; }
    let stripTop = null;
    if (withStrip) { stripTop = y; y += STRIP_H; }
    return { vidTop: TOP, vidH: VID_H, zoomRow, rows, stripTop, rulerTop: y, H: y + BOTTOM };
  }

  function stripWanted() {
    return !!(S.dragOver && S.dragOver.mp3 && S.loaded);
  }

  function curTime() { return video.currentTime || 0; }

  function seek(t) {
    if (!S.loaded) return;
    const max = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : S.fileDuration;
    try { video.currentTime = clamp(t, 0, max); } catch (e) { /* not ready */ }
    syncPods(true);
  }

  function seekFrame(i) {
    if (i >= S.N) seek(frameTs(S.N - 1) + eps());
    else seek(frameTs(i) + eps());
  }

  function pause() {
    S.playing = false;
    video.pause();
    syncPods(true);
  }

  function play() {
    if (!S.loaded) return;
    const rt = frameTs(S.right);
    if (curTime() >= rt - eps() || video.ended) seekFrame(S.left);
    S.playing = true;
    S.lastT = curTime();
    const p = video.play();
    if (p && p.catch) p.catch(() => { S.playing = false; });
    syncPods(true);
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

  function ensureVisible(s) {
    const v = S.view;
    const span = v.end - v.start;
    const ext = extent();
    if (span >= ext - 1e-9) return;
    if (s < v.start || s > v.end) {
      const start = clamp(s - span / 2, 0, ext - span);
      v.start = start; v.end = start + span;
      invalidateWave();
    }
  }

  // ---------- Podkłady: pozycje, przycinanie, Przyciąganie ----------
  function quantAt(t) {
    return frameTs(clamp(frameIndex(t), 0, S.N - 1));
  }

  // Cele Przyciągania w czasie Sekwencji. `noPlayhead`: przy przeciąganiu Krawędzi Wycięcia
  // Playhead jedzie za Krawędzią, więc nie może być jej celem.
  function snapTargets(except, extra, noPlayhead) {
    const ts = [0, S.duration, S.seqs[S.left], S.seqs[S.right]];
    if (!noPlayhead) ts.push(seqOf(curTime()));
    for (let k = 1; k < S.pieces.length; k++) ts.push(S.seqs[S.pieces[k].ia]);
    for (const p of S.pods) {
      if (p === except) continue;
      ts.push(podStart(p), podEnd(p));
    }
    for (const z of S.zooms) {
      if (z === except) continue;
      ts.push(seqOf(z.at), seqOf(z.end));
    }
    if (extra) ts.push(...extra);
    return ts;
  }

  // Zwraca cel, do którego czas Sekwencji `s` ma się przyciągnąć, albo null.
  function snap(s, targets) {
    let best = null, bestD = SNAP_PX + 1e-9;
    const x = xS(s);
    for (const c of targets) {
      const d = Math.abs(xS(c) - x);
      if (d < bestD) { bestD = d; best = c; }
    }
    return best;
  }

  function clampPod(p) {
    const minLen = S.frameStep;
    for (const s of p.segs) {
      s.tin = clamp(s.tin, 0, p.duration);
      s.tout = clamp(s.tout, s.tin, p.duration);
    }
    p.segs = p.segs.filter((s) => s.tout - s.tin > 1e-9);
    if (!p.segs.length) p.segs = [{ tin: 0, tout: Math.min(p.duration, minLen) }];
    const last = p.segs[p.segs.length - 1];
    if (podLen(p) < minLen) last.tout = clamp(last.tin + minLen, last.tin, p.duration);
    p.at = frameTs(nearestIdx(p.at));
  }

  function movePodTo(p, s, doSnap) {
    let i = clamp(ordAtS(s), 0, S.N - 1);
    if (doSnap) {
      const len = podLen(p);
      const targets = snapTargets(p);
      const sA = S.seqs[i];
      const sL = snap(sA, targets);
      const sR = snap(sA + len, targets);
      const dL = sL == null ? Infinity : Math.abs(xS(sL) - xS(sA));
      const dR = sR == null ? Infinity : Math.abs(xS(sR) - xS(sA + len));
      if (dL <= dR && sL != null) i = ordAtS(sL);
      else if (sR != null) i = ordAtS(sR - len);
    }
    p.at = frameTs(clamp(i, 0, S.N - 1));
    clampPod(p);
  }

  // Lewa Krawędź: treść zostaje na miejscu, zmienia się tylko, od którego miejsca ją słychać.
  function setPodIn(p, s, doSnap) {
    let L = S.seqs[clamp(ordAtS(s), 0, S.N - 1)];
    if (doSnap) { const c = snap(L, snapTargets(p)); if (c != null) L = c; }
    const minLen = S.frameStep;
    const s0 = podStart(p), first = p.segs[0];
    L = clamp(L, s0 - first.tin, s0 + (first.tout - first.tin) - minLen);
    L = Math.max(0, L);
    const delta = L - s0;
    p.at = frameTs(clamp(ordAtS(L), 0, S.N - 1));
    first.tin += delta;
    clampPod(p);
  }

  function setPodOut(p, R, doSnap) {
    if (doSnap) { const c = snap(R, snapTargets(p)); if (c != null) R = c; }
    const minLen = S.frameStep;
    const last = p.segs[p.segs.length - 1];
    const before = podLen(p) - (last.tout - last.tin);
    let len = R - podStart(p);
    len = Math.round(len / S.frameStep) * S.frameStep;
    len = clamp(len, before + minLen, before + (p.duration - last.tin));
    last.tout = last.tin + (len - before);
    clampPod(p);
  }

  // Krok o jedną Klatkę albo o 1 s. Sekunda liczona po czasie Sekwencji, nie po liczbie klatek ze
  // średniego fps: w sklejce 30 + 60 fps średnia nie odpowiada żadnej z części.
  function stepIndex(i, dir, big) {
    if (!big) return i + dir;
    const j = ordAtS(clamp(S.seqs[clamp(i, 0, S.N)] + dir, 0, S.duration));
    return dir > 0 ? Math.max(j, i + 1) : Math.min(j, i - 1);
  }

  function stepPod(p, edge, dir, big) {
    if (edge === 'in') {
      const i = stepIndex(frameIndex(p.at), dir, big);
      setPodIn(p, S.seqs[clamp(i, 0, S.N - 1)], false);
    } else if (edge === 'out') {
      setPodOut(p, podEnd(p) + dir * (big ? 1 : S.frameStep), false);
    } else {
      const i = stepIndex(frameIndex(p.at), dir, big);
      movePodTo(p, S.seqs[clamp(i, 0, S.N - 1)], false);
    }
    fitView();
    ensureVisible(edge === 'out' ? podEnd(p) : podStart(p));
  }

  // ---------- Zbliżenia: pozycje, długość, Rampy ----------
  // Zbliżenie trzyma pts pierwszej Klatki (`at`) i pts Klatki za ostatnią (`end`, wyłącznie), jak Suwaki.
  // Przesuwanie zachowuje liczbę Klatek, nie sekundy: w sklejce 30 + 60 fps to nie to samo.
  function zoomFrames(z) { return frameIndex(z.end) - frameIndex(z.at); }
  function setZoomRange(z, ia, ib) {
    ia = clamp(ia, 0, S.N - 1);
    z.at = frameTs(ia);
    z.end = frameTs(clamp(ib, ia + 1, S.N));
  }
  // Sąsiedzi są twardą granicą: Zbliżenia nie nachodzą na siebie. Zwraca indeksy Klatek.
  function zoomNeighbours(z) {
    let lo = 0, hi = S.N;
    for (const o of S.zooms) {
      if (o === z) continue;
      if (o.end <= z.at + 1e-6) lo = Math.max(lo, frameIndex(o.end));
      else if (o.at >= z.end - 1e-6) hi = Math.min(hi, frameIndex(o.at));
    }
    return { lo, hi };
  }
  function clampRamps(z, side) {
    const L = zoomLen(z);
    z.rin = clamp(z.rin, 0, L);
    z.rout = clamp(z.rout, 0, L);
    if (z.rin + z.rout > L + 1e-9) {
      if (side === 'in') z.rin = Math.max(0, L - z.rout); else z.rout = Math.max(0, L - z.rin);
    }
  }
  function clampZoom(z) {
    setZoomRange(z, nearestIdx(z.at), nearestEndIdx(z.end));
    const seen = new Map();
    for (const q of z.keys) seen.set(frameTs(nearestIdx(q.t)), clampKadr(q.k));
    z.keys = [...seen.entries()].map(([t, k]) => ({ t, k })).sort((p, q) => p.t - q.t);
    trimKeys(z);
    clampRamps(z);
  }
  function moveZoomTo(z, s, doSnap) {
    const n = zoomFrames(z);
    let ia = clamp(ordAtS(s), 0, S.N - 1);
    if (doSnap) {
      const targets = snapTargets(z);
      const tA = S.seqs[ia], tB = S.seqs[Math.min(ia + n, S.N)];
      const sL = snap(tA, targets), sR = snap(tB, targets);
      const dL = sL == null ? Infinity : Math.abs(xS(sL) - xS(tA));
      const dR = sR == null ? Infinity : Math.abs(xS(sR) - xS(tB));
      if (dL <= dR && sL != null) ia = ordAtS(sL);
      else if (sR != null) ia = ordAtS(sR) - n;
    }
    const { lo, hi } = zoomNeighbours(z);
    ia = clamp(ia, lo, hi - n);
    const di = ia - frameIndex(z.at);
    for (const q of z.keys) q.t = frameTs(clamp(frameIndex(q.t) + di, 0, S.N - 1));
    setZoomRange(z, ia, ia + n);
    trimKeys(z);
    clampRamps(z);
  }
  // Krawędź zmienia przedział; pozycje Kadru zostają na swoich Klatkach, te poza przedziałem przepadają.
  function setZoomIn(z, s, doSnap) {
    if (doSnap) { const c = snap(s, snapTargets(z)); if (c != null) s = c; }
    let ia = clamp(ordAtS(s), 0, S.N - 1);
    const { lo } = zoomNeighbours(z);
    ia = clamp(ia, lo, frameIndex(z.end) - 1);
    setZoomRange(z, ia, frameIndex(z.end));
    trimKeys(z);
    clampRamps(z, 'in');
  }
  function setZoomOut(z, s, doSnap) {
    if (doSnap) { const c = snap(s, snapTargets(z)); if (c != null) s = c; }
    const { hi } = zoomNeighbours(z);
    const ib = clamp(endIndexAtS(s), frameIndex(z.at) + 1, hi);
    setZoomRange(z, frameIndex(z.at), ib);
    trimKeys(z);
    clampRamps(z, 'out');
  }
  // Rampy: górne rogi; własne Krawędzie są celem Przyciągania, żeby „prawie zero” było zerem.
  function setRampIn(z, s, doSnap) {
    if (doSnap) { const c = snap(s, snapTargets(z, [seqOf(z.at), seqOf(z.end)])); if (c != null) s = c; }
    z.rin = clamp(S.seqs[clamp(ordAtS(s), 0, S.N)] - seqOf(z.at), 0, zoomLen(z) - z.rout);
  }
  function setRampOut(z, s, doSnap) {
    if (doSnap) { const c = snap(s, snapTargets(z, [seqOf(z.at), seqOf(z.end)])); if (c != null) s = c; }
    z.rout = clamp(seqOf(z.end) - S.seqs[clamp(endIndexAtS(s), 0, S.N)], 0, zoomLen(z) - z.rin);
  }
  function stepZoom(z, part, dir, big) {
    const ia = frameIndex(z.at), ib = frameIndex(z.end);
    if (part === 'in') setZoomIn(z, S.seqs[clamp(stepIndex(ia, dir, big), 0, S.N - 1)], false);
    else if (part === 'out') setZoomOut(z, S.seqs[clamp(stepIndex(ib, dir, big), 1, S.N)], false);
    else if (part === 'rin') setRampIn(z, S.seqs[clamp(stepIndex(ordAtS(seqOf(z.at) + z.rin), dir, big), 0, S.N)], false);
    else if (part === 'rout') setRampOut(z, S.seqs[clamp(stepIndex(endIndexAtS(seqOf(z.end) - z.rout), dir, big), 0, S.N)], false);
    else moveZoomTo(z, S.seqs[clamp(stepIndex(ia, dir, big), 0, S.N - 1)], false);
    ensureVisible(part === 'out' || part === 'rout' ? seqOf(z.end) : seqOf(z.at));
  }
  function removeZoom(id) {
    const i = S.zooms.findIndex((z) => z.id === id);
    if (i < 0) return;
    S.zooms.splice(i, 1);
    if (S.sel && typeof S.sel === 'object' && S.sel.zoom === id) S.sel = null;
    if (S.drag && S.drag.kind === 'zoom' && S.drag.id === id) S.drag = null;
  }
  function cancelPreviewDrag() { S.pdrag = null; }
  // Narysowany Kadr na bieżącej Klatce: poza Zbliżeniami tworzy nowe (jedna Klatka, do wydłużenia
  // Cieniem albo Krawędzią), wewnątrz Zbliżenia rozcina je: stare kończy się tu, nowe zaczyna z tym Kadrem.
  function commitKadr(k) {
    if (!S.loaded || S.kind !== 'video') return false;
    const i = clamp(frameIndex(curTime()), 0, S.N - 1);
    const t = frameTs(i);
    const z = zoomAt(t);
    if (z && Math.abs(z.at - t) < 1e-6) {
      setKey(z, t, k);
      S.sel = { zoom: z.id, part: null };
      return true;
    }
    const nz = { id: ++S.zoomSeq, at: t, end: z ? z.end : frameTs(i + 1), rin: 0, rout: z ? z.rout : 0,
      keys: [{ t, k: clampKadr({ ...k }) }] };
    if (z) { z.end = t; z.rout = 0; trimKeys(z); clampRamps(z); }
    S.zooms.push(nz);
    S.zooms.sort((p, q) => p.at - q.at);
    S.sel = { zoom: nz.id, part: null };
    showStatus(`${z ? 'Zbliżenie rozcięte, nowe' : 'Zbliżenie'} ${fmtZoomLabel(nz)} ✓`, 'done', '', 2000);
    return true;
  }

  function setGain(target, dir, fine) {
    const step = fine ? 0.01 : 0.05;
    const g = clamp(Math.round((target.gain + dir * step) * 100) / 100, 0, 1);
    target.gain = g;
    if (target === S) video.volume = g;
    else if (target.audio) target.audio.volume = g;
    S.volLabel = { until: performance.now() + VOL_LABEL_MS, text: `${Math.round(g * 100)} %`, pod: target === S ? null : target.gen };
  }

  function removePod(gen) {
    const i = S.pods.findIndex((p) => p.gen === gen);
    if (i < 0) return;
    const p = S.pods[i];
    if (p.audio) { try { p.audio.pause(); p.audio.src = ''; } catch (e) { /* */ } }
    S.pods.splice(i, 1);
    if (S.sel && typeof S.sel === 'object' && S.sel.pod === gen) S.sel = null;
    if (S.drag && S.drag.kind === 'pod' && S.drag.gen === gen) S.drag = null;
    if (window.pywebview && window.pywebview.api) window.pywebview.api.remove_podklad(gen).catch(() => {});
    fitView();
    invalidateWave();
  }

  function clearPods() {
    for (const p of S.pods) {
      if (p.audio) { try { p.audio.pause(); p.audio.src = ''; } catch (e) { /* */ } }
    }
    S.pods = [];
  }

  // Odtwarzanie Podkładów: każdy ma własny <audio>, dosuwany do wideo przy play/pauzie/seeku
  // i gdy dryf przekroczy 120 ms (także na szwie odcinków). Eksport liczy ffmpeg, więc drobny dryf
  // w podglądzie nie szkodzi. Niewykonane Wycięcie na Podkładzie jest już pominięte (podgląd wyniku).
  function syncPods(force) {
    const s = seqOf(curTime());
    const playing = S.loaded && S.playing && !video.paused;
    for (const p of S.pods) {
      const a = p.audio;
      if (!a) continue;
      let u = s - podStart(p);
      let len = podLen(p);
      const cr = cutPodRange(p);
      if (cr) { if (u >= cr[0]) u += cr[1] - cr[0]; len -= cr[1] - cr[0]; }
      const want = u >= -1e-3 && u < len + (cr ? cr[1] - cr[0] : 0) ? podContent(p, Math.max(0, u)) : null;
      if (playing && want != null && s - podStart(p) < len) {
        if (a.paused || force || Math.abs(a.currentTime - want) > 0.12) {
          try { a.currentTime = want; } catch (e) { /* */ }
          if (a.paused) { const pr = a.play(); if (pr && pr.catch) pr.catch(() => {}); }
        }
      } else if (!a.paused) {
        a.pause();
      }
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
  function blockedByCut() {
    if (!S.cut) return false;
    showStatus(CUT_BLOCK, 'error', '', 3000);
    return true;
  }

  // ---------- wczytywanie ----------
  function onLoaded(info, reason) {
    const wasLoaded = S.loaded;
    const prevT = wasLoaded ? curTime() : 0;
    S.loaded = true;
    S.gen = info.gen;
    S.kind = info.kind;
    S.fileDuration = info.duration;
    S.frameStep = info.frameStep > 0 ? info.frameStep : 1 / 30;
    S.fileFrames = null;
    S.scanned = false;
    S.wave = null;
    S.waveGain = 1;
    S.waveBin = info.waveBinSec || 0.005;
    S.parts = (info.parts || [{ name: info.name, start: 0, duration: info.duration, src: 0, in: 0, out: info.duration }])
      .map((p) => ({ name: p.name, src: p.src != null ? p.src : 0, start: p.start, duration: p.duration,
        in: p.in != null ? p.in : 0, out: p.out != null ? p.out : p.duration }));
    rebuildKept();
    S.left = 0;
    S.right = S.N;
    S.sel = null;
    S.drag = null;
    S.cut = null;
    S.undo = [];
    S.playing = false;
    S.lastT = 0;
    S.exporting = false;
    S.busy = false;
    S.hoverX = null;
    S.hoverT = null;
    S.restoreT = null;
    S.width = info.width || 0;
    S.height = info.height || 0;
    S.pdrag = null;
    video.style.transform = '';
    if (reason === 'open' || !wasLoaded) {
      clearPods();
      S.zooms = [];
      S.gain = 1;
      S.volLabel = null;
    } else {
      applyShift(prevT);
    }
    S.viewFull = true;
    fitView();
    hideStatus();
    rejectEl.textContent = '';
    document.body.classList.add('loaded');
    document.body.classList.toggle('kind-audio', S.kind === 'audio');
    invalidateWave();
    video.pause();
    video.volume = S.gain;
    video.src = `/media?gen=${S.gen}`;
    video.load();
  }

  // Po sklejeniu Podkłady, Zbliżenia i Playhead jadą razem z obrazem: Python daje `remap`
  // ([[stary początek, stary koniec, przesunięcie], ...] dla każdego dawnego Nagrania w czasie pliku).
  // Zbliżenie rozcięte przez wstawienie wydłuża się (pozycje zostają na swoich Klatkach).
  function applyShift(prevT) {
    const sh = S.pendingShift;
    S.pendingShift = null;
    let t = prevT;
    const rm = sh && sh.remap && sh.remap.length ? sh.remap : null;
    if (rm) {
      const map = (x) => {
        let d = rm[0][2];
        for (const [a, , delta] of rm) if (x >= a - 1e-6) d = delta;
        return x + d;
      };
      for (const p of S.pods) p.at = map(p.at);
      for (const z of S.zooms) { z.at = map(z.at); z.end = map(z.end); for (const q of z.keys) q.t = map(q.t); }
      t = map(t);
    }
    for (const p of S.pods) clampPod(p);
    for (const z of S.zooms) clampZoom(z);
    S.restoreT = clamp(t, 0, S.fileDuration);
  }

  async function fetchFrames(gen) {
    try {
      const r = await fetch(`/api/frames?gen=${gen}`);
      if (!r.ok || r.status === 204 || gen !== S.gen) return;
      const buf = await r.arrayBuffer();
      if (gen !== S.gen || buf.byteLength < 16) return;
      const lt = frameTs(S.left);
      const rt = frameTs(S.right);
      const rightAtEnd = S.right >= S.N;
      S.fileFrames = new Float64Array(buf);
      S.scanned = true;
      rebuildKept();
      S.left = clamp(frameIndex(lt), 0, S.N - 1);
      S.right = rightAtEnd ? S.N : clamp(frameIndex(rt), S.left + 1, S.N);
      for (const p of S.pods) clampPod(p);
      for (const z of S.zooms) clampZoom(z);
      fitView();
      invalidateWave();
    } catch (e) { /* ignoruj */ }
  }

  async function fetchWave(gen) {
    try {
      const target = gen === S.gen ? S : podByGen(gen);
      if (!target) return;
      const r = await fetch(`/api/wave?gen=${gen}`);
      if (!r.ok || r.status === 204) return;
      const buf = await r.arrayBuffer();
      if (target !== S && !podByGen(gen)) return;
      if (target === S && gen !== S.gen) return;
      target.wave = new Uint8Array(buf);
      let mx = 1;
      for (let i = 0; i < target.wave.length; i += 2) if (target.wave[i] > mx) mx = target.wave[i];
      target.waveGain = clamp(230 / mx, 1, 8);
      invalidateWave();
    } catch (e) { /* ignoruj */ }
  }

  function onPodklad(info) {
    if (!S.loaded || S.kind !== 'video') return;
    const a = new Audio(`/media?gen=${info.gen}`);
    a.preload = 'auto';
    const p = {
      gen: info.gen, name: info.name, duration: info.duration,
      at: 0, segs: [{ tin: 0, tout: info.duration }], gain: 1,
      wave: null, waveGain: 1, waveBin: info.waveBinSec || 0.005, audio: a,
    };
    clampPod(p);
    S.pods.push(p);
    S.sel = { pod: p.gen, edge: null };
    fitView();
    invalidateWave();
    showStatus(`Podkład: ${info.name}`, 'done', '', 2000);
  }

  function onJoin(ev) {
    if (ev.state === 'progress') {
      S.busy = true;
      showStatus(`Sklejanie… ${ev.percent}%`, 'progress');
    } else if (ev.state === 'done') {
      S.pendingShift = { remap: ev.remap || null };
      showStatus('Sklejanie… 100%', 'progress');
    } else if (ev.state === 'error') {
      S.busy = false;
      S.pendingShift = null;
      showStatus(ev.message || 'Błąd sklejania ✕', 'error', '', 6000);
    }
  }

  window.ciachEvent = (ev) => {
    switch (ev.type) {
      case 'loaded': onLoaded(ev.info, ev.reason || 'open'); break;
      case 'frames': fetchFrames(ev.gen); break;
      case 'wave': fetchWave(ev.gen); break;
      case 'podklad': onPodklad(ev.info); break;
      case 'join': onJoin(ev); break;
      case 'dropped': dropFiles(ev.paths, ev.x, ev.y); break;
      case 'reject':
        S.busy = false;
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

  function mixSpec() {
    return {
      gain: S.gain,
      podklady: S.pods.map((p) => ({ gen: p.gen, at: p.at, segs: p.segs.map((s) => [s.tin, s.tout]), gain: p.gain })),
      zblizenia: S.zooms.map((z) => ({ at: z.at, end: z.end, rin: z.rin, rout: z.rout,
        keys: z.keys.map((q) => ({ t: q.t, x: q.k.x, y: q.k.y, s: q.k.s })) })),
    };
  }

  function doExport(mode) {
    if (!S.loaded || S.exporting || S.busy) return;
    if (!window.pywebview || !window.pywebview.api) return;
    if (blockedByCut()) return;
    S.exporting = true;
    showStatus(mode === 'small' ? 'Mały ciach… 0%' : 'Ciach… 0%', 'progress');
    const start = S.left === 0 && S.headAtZero ? 0 : frameTs(S.left);
    const end = frameTs(S.right);
    window.pywebview.api.export(start, end, mode || 'full', mixSpec(), holesIn(S.left, S.right)).then((r) => {
      if (r && r.ok === false) {
        S.exporting = false;
        showStatus('Błąd ✕', 'error', r.message || '');
      }
    }).catch((e) => {
      S.exporting = false;
      showStatus('Błąd ✕', 'error', String(e));
    });
  }

  function syncParts() {
    if (!window.pywebview || !window.pywebview.api) return;
    window.pywebview.api.set_parts(S.parts.map((p) => ({ src: p.src, in: p.in, out: p.out }))).catch(() => {});
  }

  // ---------- Wycięcie ----------
  // Wycięcie [a, b) to Klatki Sekwencji do usunięcia (na Podkładzie: Klatki, pod którymi leży
  // usuwany kawałek muzyki). Istnieje najwyżej jedno; dopóki istnieje, edycja poza Suwakami czeka.
  function cutBounds(c) {
    if (c.pod == null) return { lo: 0, hi: S.N };
    const p = podByGen(c.pod);
    return { lo: frameIndex(p.at), hi: clamp(ordAtS(podEnd(p) + 1e-6), 0, S.N) };
  }
  // Musi zostać co najmniej jedna Klatka Sekwencji albo jedna Klatka muzyki Podkładu.
  function enforceCutMin(c, which) {
    if (c.pod == null) {
      if (c.b - c.a > S.N - 1) { if (which === 'a') c.a = c.b - (S.N - 1); else c.b = c.a + S.N - 1; }
    } else {
      const maxLen = podLen(podByGen(c.pod)) - S.frameStep + 1e-6;
      while (S.seqs[c.b] - S.seqs[c.a] > maxLen && c.b - c.a > 1) { if (which === 'a') c.a++; else c.b--; }
    }
  }
  function setCutA(i) { const c = S.cut; c.a = clamp(i, cutBounds(c).lo, c.b - 1); enforceCutMin(c, 'a'); }
  function setCutB(i) { const c = S.cut; c.b = clamp(i, c.a + 1, cutBounds(c).hi); enforceCutMin(c, 'b'); }
  function cutRow(L) {
    const c = S.cut;
    if (c.pod == null) return { top: L.vidTop, h: L.vidH };
    const row = L.rows.find((r) => r.gen === c.pod);
    return row ? { top: row.top, h: row.h } : { top: L.vidTop, h: L.vidH };
  }
  function cutLabel(c) {
    const sa = S.seqs[c.a], sb = S.seqs[c.b];
    return c.pod == null ? `Wycięcie ${fmt(sa)}–${fmt(sb)} · ${fmtKl(c.b - c.a)}` : `Wycięcie Podkładu ${fmt(sa)}–${fmt(sb)}`;
  }

  // C: nowe Wycięcie w Playheadzie (na zaznaczonym Podkładzie: na nim); przy istniejącym dociąga
  // bliższą Krawędź do Playheada (prawa wyłącznie: Klatka pod Playheadem zostaje).
  function startCut() {
    if (!S.loaded || S.busy || S.exporting) return;
    if (!S.scanned) { showStatus('Poczekaj na analizę Klatek', 'error', '', 3000); return; }
    if (S.playing) pause();
    cancelPreviewDrag();
    const i = clamp(frameIndex(curTime()), 0, S.N - 1);
    if (S.cut) {
      const c = S.cut;
      if (i > c.a) setCutB(i); else if (i < c.a) setCutA(i);
      return;
    }
    const sp = selPod();
    const pod = sp ? sp.gen : null;
    if (sp) {
      const s = seqOf(curTime());
      if (s < podStart(sp) - 1e-6 || s >= podEnd(sp) - S.frameStep / 2) { showStatus('Playhead poza Podkładem', 'error', '', 3000); return; }
    } else if (S.N < 2) {
      showStatus('Sekwencja ma tylko jedną Klatkę', 'error', '', 3000);
      return;
    } else if (S.sel) {
      S.sel = null;
    }
    const c = { pod, a: i, b: i + 1 };
    S.cut = c;
    const secs = CUT_MIN_PX * (S.view.end - S.view.start) / cssWidth();
    setCutB(Math.max(i + 1, ordAtS(S.seqs[i] + secs)));
    if (c.b - c.a < 1) { S.cut = null; showStatus('Za mało miejsca na Wycięcie', 'error', '', 3000); return; }
    showStatus('Wycięcie: C dociąga Krawędź do Playheada, Delete wycina, Esc porzuca', '', '', 4000);
  }

  function discardCut() {
    if (!S.cut) return;
    S.cut = null;
    if (S.drag && S.drag.kind === 'cut') S.drag = null;
    showStatus('Wycięcie porzucone', '', '', 1500);
  }

  function pushUndo() {
    S.undo.push({
      parts: S.parts.map((p) => ({ ...p })),
      left: S.left, right: S.right, t: curTime(), sel: S.sel,
      zooms: S.zooms.map((z) => ({ ...z, keys: z.keys.map((q) => ({ t: q.t, k: { ...q.k } })) })),
      pods: S.pods.map((p) => ({ gen: p.gen, at: p.at, segs: p.segs.map((s) => ({ ...s })) })),
    });
    if (S.undo.length > UNDO_MAX) S.undo.shift();
  }

  function undo() {
    if (!S.loaded || S.busy || S.exporting) return;
    const u = S.undo.pop();
    if (!u) { showStatus('Nie ma czego cofnąć', '', '', 1500); return; }
    pause();
    cancelPreviewDrag();
    S.parts = u.parts;
    rebuildKept();
    S.zooms = u.zooms;
    for (const q of u.pods) { const p = podByGen(q.gen); if (p) { p.at = q.at; p.segs = q.segs; } }
    for (const p of S.pods) clampPod(p);
    for (const z of S.zooms) clampZoom(z);
    S.left = clamp(u.left, 0, S.N - 1);
    S.right = clamp(u.right, S.left + 1, S.N);
    S.sel = u.sel && typeof u.sel === 'object' ? (u.sel.pod != null ? (podByGen(u.sel.pod) ? u.sel : null)
      : (zoomById(u.sel.zoom) ? u.sel : null)) : u.sel;
    S.drag = null;
    seek(u.t);
    syncParts();
    fitView();
    invalidateWave();
    showStatus('Cofnięto ✓', 'done', '', 1500);
  }

  // Wykonanie: Klatki [a, b) znikają z Sekwencji. Suwaki i Zbliżenia za nimi jadą z obrazem,
  // Zbliżenia nachodzące są skracane (pozycje wewnątrz przepadają; gdy Kadr przejeżdżał przez
  // Wycięcie, brzegi dostają pozycję, którą tam pokazywał, żeby zachowane Klatki wyglądały jak dotąd),
  // Podkłady trzymają się swojej Klatki (z wyciętej: na szew). Miejsce cięcia jest Stykiem.
  function cutFrames(a, b, msg) {
    pushUndo();
    const n = b - a;
    const oldFrames = S.frames, oldSeqs = S.seqs;
    const oldEnd = (i) => oldFrames[i] + (oldSeqs[i + 1] - oldSeqs[i]);
    const rm = (i) => (i >= b ? i - n : i >= a ? a : i);
    const zooms = [];
    for (const z of S.zooms) {
      const za = frameIndex(z.at), zb = frameIndex(z.end);
      const nza = rm(za), nzb = zb >= b ? zb - n : Math.min(zb, a);
      if (nzb - nza < 1) continue;
      const keys = new Map();
      if (za < a && zb > a && !kadrHolds(z, oldFrames[a - 1])) keys.set(a - 1, kadrKeys(z, oldFrames[a - 1]));
      if (zb > b && za < b && !kadrHolds(z, oldFrames[b])) keys.set(a, kadrKeys(z, oldFrames[b]));
      for (const q of z.keys) { const i = frameIndex(q.t); if (i < a || i >= b) keys.set(rm(i), q.k); }
      if (!keys.size) keys.set(nza, kadrKeys(z, za < a ? oldFrames[za] : oldFrames[b]));
      zooms.push({ z, za: nza, zb: nzb, keys: [...keys.entries()].sort((p, q) => p[0] - q[0]) });
    }
    const pods = S.pods.map((p) => rm(frameIndex(p.at)));
    const left = rm(S.left);
    const right = S.right >= b ? S.right - n : Math.min(S.right, a);
    const play = rm(clamp(frameIndex(curTime()), 0, S.N - 1));
    const parts = [];
    for (let k = 0; k < S.pieces.length; k++) {
      const pc = S.pieces[k], part = S.parts[k];
      if (pc.ib <= a || pc.ia >= b) { parts.push(part); continue; }
      const spans = [];
      if (pc.ia < a) spans.push([pc.ia, Math.min(pc.ib, a)]);
      if (pc.ib > b) spans.push([Math.max(pc.ia, b), pc.ib]);
      for (const [ia, ib] of spans) parts.push({ ...part, in: oldFrames[ia] - part.start, out: oldEnd(ib - 1) - part.start });
    }
    S.parts = parts;
    rebuildKept();
    S.zooms = [];
    for (const q of zooms) {
      const z = q.z;
      setZoomRange(z, q.za, q.zb);
      z.keys = q.keys.map(([i, k]) => ({ t: frameTs(clamp(i, 0, S.N - 1)), k }));
      clampZoom(z);
      S.zooms.push(z);
    }
    if (S.sel && typeof S.sel === 'object' && S.sel.zoom != null && !zoomById(S.sel.zoom)) S.sel = null;
    S.pods.forEach((p, k) => { p.at = frameTs(clamp(pods[k], 0, S.N - 1)); clampPod(p); });
    S.left = clamp(left, 0, S.N - 1);
    S.right = clamp(right, S.left + 1, S.N);
    S.cut = null;
    S.drag = null;
    seekFrame(clamp(play, 0, S.N - 1));
    syncParts();
    fitView();
    invalidateWave();
    showStatus(msg, 'done', '', 2500);
  }

  function executeCut() {
    const c = S.cut;
    if (!c || !S.loaded || S.busy || S.exporting) return;
    pause();
    if (c.pod != null) {
      const p = podByGen(c.pod);
      if (!p) { S.cut = null; return; }
      pushUndo();
      const [ua, ub] = cutPodRange(p);
      S.cut = null;
      p.segs = cutSegs(p.segs, ua, ub);
      clampPod(p);
      fitView();
      invalidateWave();
      syncPods(true);
      showStatus(`Wycięto ${fmt(ub - ua)} z Podkładu ✓`, 'done', '', 2500);
      return;
    }
    cutFrames(c.a, c.b, `Wycięto ${fmtKl(c.b - c.a)} ✓`);
  }

  // ---------- wideo ----------
  video.addEventListener('loadedmetadata', () => {
    try { video.currentTime = S.restoreT != null ? S.restoreT : 0; } catch (e) { /* */ }
    S.restoreT = null;
  });
  video.addEventListener('ended', () => {
    if (S.playing && S.right >= S.N) {
      seekFrame(S.left);
      const p = video.play();
      if (p && p.catch) p.catch(() => { S.playing = false; });
    } else {
      S.playing = false;
      syncPods(true);
    }
  });
  video.addEventListener('pause', () => { if (!video.ended) { S.playing = false; syncPods(true); } });
  video.addEventListener('error', () => {
    if (!S.loaded) return;
    showStatus('Nie da się odtworzyć tego pliku (nieobsługiwany kodek)', 'error', '', 6000);
  });

  // Pętla odtwarzania: koniec Fragmentu → początek; dziura po Wycięciu (i niewykonane Wycięcie
  // Sekwencji) → przeskok do pierwszej Klatki za nią.
  function tick() {
    if (S.loaded && S.playing && !video.paused) {
      const t = curTime();
      const rt = frameTs(S.right);
      if (S.lastT < rt && t >= rt) {
        seekFrame(S.left);
        S.lastT = frameTs(S.left);
      } else {
        const i = frameIndex(t);
        let jump = null;
        if (i < S.N && i + 1 < S.N && t >= frameEnd(i) - 1e-6 && t < S.frames[i + 1]) jump = i + 1;
        if (S.cut && S.cut.pod == null && i >= S.cut.a && i < S.cut.b) jump = S.cut.b;
        if (jump != null) {
          if (jump >= S.right || jump >= S.N) { seekFrame(S.left); S.lastT = frameTs(S.left); }
          else { seekFrame(jump); S.lastT = frameTs(jump); }
        } else {
          S.lastT = t;
        }
      }
      syncPods(false);
    }
    draw();
    drawOverlay();
    requestAnimationFrame(tick);
  }

  // ---------- waveform cache ----------
  let waveCanvas = null;
  let waveKey = '';
  const podCanvases = new Map();
  function invalidateWave() { waveKey = ''; podCanvases.clear(); }

  function renderWave(g, W, Hwave, wave, waveGain, binSec, tAt) {
    // tAt(x) → czas w pliku źródłowym dla piksela x (albo null poza materiałem)
    g.clearRect(0, 0, W, Hwave);
    if (!wave || wave.length < 2) return;
    const nb = wave.length >> 1;
    const mid = Hwave / 2;
    const amp = Hwave / 2 - 2;
    const v = S.view;
    const secPerPx = (v.end - v.start) / W;
    const peakPath = new Path2D();
    const rmsPath = new Path2D();
    for (let x = 0; x < W; x++) {
      const t0 = tAt(x);
      if (t0 == null) continue;
      const t1 = t0 + secPerPx;
      let b0 = Math.floor(t0 / binSec);
      let b1 = Math.floor(t1 / binSec);
      if (b1 < b0) b1 = b0;
      if (b0 < 0) b0 = 0;
      if (b0 >= nb) continue;
      if (b1 >= nb) b1 = nb - 1;
      let pk = 0, rm = 0;
      for (let b = b0; b <= b1; b++) {
        const p = wave[b * 2];
        const r = wave[b * 2 + 1];
        if (p > pk) pk = p;
        if (r > rm) rm = r;
      }
      const hp = Math.min(amp, Math.max(0.5, pk * waveGain / 255 * amp));
      const hr = Math.min(amp, Math.max(0.5, rm * waveGain / 255 * amp));
      peakPath.rect(x, mid - hp, 1, hp * 2);
      rmsPath.rect(x, mid - hr, 1, hr * 2);
    }
    return [peakPath, rmsPath];
  }

  function buildWave(W, Hwave, dpr) {
    const key = `${S.gen}|${S.N}|${S.duration}|${W}|${Hwave}|${dpr}|${S.view.start}|${S.view.end}|${S.wave ? S.wave.length : 0}|${S.waveGain}`;
    if (key === waveKey && waveCanvas) return;
    waveKey = key;
    if (!waveCanvas) waveCanvas = document.createElement('canvas');
    waveCanvas.width = Math.max(1, Math.round(W * dpr));
    waveCanvas.height = Math.max(1, Math.round(Hwave * dpr));
    const g = waveCanvas.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const v = S.view;
    const secPerPx = (v.end - v.start) / W;
    const paths = renderWave(g, W, Hwave, S.wave, S.waveGain, S.waveBin, (x) => {
      const s = v.start + x * secPerPx;
      return s < S.duration ? fileOf(s) : null;
    });
    if (!paths) return;
    g.fillStyle = C.peak; g.fill(paths[0]);
    g.fillStyle = C.rms; g.fill(paths[1]);
  }

  function buildPodWave(p, W, Hwave, dpr) {
    const segKey = p.segs.map((s) => `${s.tin}-${s.tout}`).join(',');
    const key = `${W}|${Hwave}|${dpr}|${S.view.start}|${S.view.end}|${S.N}|${p.at}|${segKey}|${p.wave ? p.wave.length : 0}|${p.gain}`;
    const cached = podCanvases.get(p.gen);
    if (cached && cached.key === key) return cached.canvas;
    const c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(W * dpr));
    c.height = Math.max(1, Math.round(Hwave * dpr));
    const g = c.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const v = S.view;
    const secPerPx = (v.end - v.start) / W;
    const s0 = podStart(p), len = podLen(p);
    const paths = renderWave(g, W, Hwave, p.wave, p.waveGain * p.gain, p.waveBin, (x) => {
      const u = v.start + x * secPerPx - s0;
      if (u < 0 || u >= len) return null;
      return podContent(p, u);
    });
    if (paths) {
      g.fillStyle = C.podPeak; g.fill(paths[0]);
      g.fillStyle = C.podRms; g.fill(paths[1]);
    }
    podCanvases.set(p.gen, { key, canvas: c });
    return c;
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

  // ---------- Gniazda ----------
  function gniazda() {
    // Kolejne indeksy wstawienia: 0 = przed pierwszym Nagraniem, pieces.length = za ostatnim.
    const out = [];
    const n = S.pieces.length;
    for (let i = 0; i <= n; i++) {
      const s = i < n ? S.seqs[S.pieces[i].ia] : S.duration;
      const x = xS(s);
      let x0;
      if (i === 0) x0 = x;
      else if (i === n) x0 = x - GN_W;
      else x0 = x - GN_W / 2;
      out.push({ index: i, x0, x1: x0 + GN_W });
    }
    return out;
  }

  function gniazdoAt(mx, my, L) {
    if (my < L.vidTop - GRIP_H || my >= L.vidTop + L.vidH) return null;
    const W = cssWidth();
    for (const g of gniazda()) {
      if (g.x1 < 0 || g.x0 > W) continue;
      if (mx >= g.x0 && mx <= g.x1) return g;
    }
    return null;
  }

  // ---------- rysowanie ----------
  function draw() {
    const dpr = window.devicePixelRatio || 1;
    const L = layout(stripWanted());
    // #timeline ma border-top: wysokość elementu = wysokość canvasu + ramka
    const want = L.H + (timelineEl.offsetHeight - timelineEl.clientHeight);
    if (timelineEl.offsetHeight !== want) timelineEl.style.height = `${want}px`;
    const W = cssWidth();
    const H = L.H;
    const pw = Math.round(W * dpr), ph = Math.round(H * dpr);
    if (canvas.width !== pw || canvas.height !== ph) {
      canvas.width = pw; canvas.height = ph;
      invalidateWave();
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);
    if (!S.loaded) return;
    // Podczas przeciągania widok stoi w miejscu: gdyby rozciągał się za wystającym
    // Podkładem, skala zmieniałaby się pod kursorem i Podkład uciekałby spod myszy.
    if (!S.drag) fitView();

    const waveTop = L.vidTop;
    const waveH = L.vidH;
    const rowsBottom = L.rulerTop - (L.stripTop != null ? STRIP_H : 0);
    const fullH = rowsBottom - waveTop;  // wiersz Sekwencji + wiersze Podkładów
    const xl = xS(S.seqs[S.left]);
    const xr = xS(S.seqs[S.right]);
    const xe = xS(S.duration);
    const now = performance.now();
    const t = curTime();
    const xp = xOf(t);

    // wiersze Zbliżeń i Podkładów: tło
    const bgRows = L.zoomRow ? [L.zoomRow, ...L.rows] : L.rows;
    for (const row of bgRows) {
      ctx.fillStyle = C.rowBg;
      ctx.fillRect(0, row.top, W, row.h);
      ctx.fillStyle = C.axis;
      ctx.fillRect(0, row.top, W, 1);
    }
    // zaznaczenie (Fragment) przez wszystkie wiersze
    ctx.fillStyle = C.selection;
    ctx.fillRect(clamp(xl, 0, W), waveTop, clamp(xr, 0, W) - clamp(xl, 0, W), fullH);
    // Nagranie pod playheadem (to skasuje Delete) przy fokusie na wideo
    if (S.pieces.length > 1 && !S.sel && !S.cut) {
      const pc = S.pieces[pieceIndexAt(frameIndex(t))];
      const a = clamp(xS(S.seqs[pc.ia]), 0, W), b = clamp(xS(S.seqs[pc.ib]), 0, W);
      ctx.fillStyle = C.current;
      ctx.fillRect(a, waveTop, b - a, waveH);
    }
    // oś
    ctx.fillStyle = C.axis;
    ctx.fillRect(0, waveTop + waveH / 2 - 0.5, W, 1);
    // waveform Sekwencji
    buildWave(W, waveH, dpr);
    if (waveCanvas) ctx.drawImage(waveCanvas, 0, 0, waveCanvas.width, waveCanvas.height, 0, waveTop, W, waveH);
    // za końcem Sekwencji: pusto
    if (xe < W) {
      ctx.fillStyle = C.beyond;
      ctx.fillRect(clamp(xe, 0, W), waveTop, W - clamp(xe, 0, W), waveH);
    }
    // Styki i nazwy Nagrań
    ctx.font = '10px "Segoe UI", system-ui, sans-serif';
    ctx.textBaseline = 'top';
    ctx.textAlign = 'left';
    for (let i = 0; i < S.pieces.length; i++) {
      const pc = S.pieces[i];
      const x = xS(S.seqs[pc.ia]);
      if (i > 0 && x >= 0 && x <= W) {
        ctx.fillStyle = C.styk;
        for (let y = waveTop; y < rowsBottom; y += 6) ctx.fillRect(Math.round(x), y, 1, 3);
      }
      if (S.pieces.length > 1) {
        const x1 = xS(S.seqs[pc.ib]);
        if (x1 > 0 && x < W) {
          ctx.fillStyle = C.textDim;
          ctx.save();
          ctx.beginPath();
          ctx.rect(Math.max(0, x) + 2, waveTop, Math.max(0, Math.min(W, x1) - Math.max(0, x) - 4), 14);
          ctx.clip();
          ctx.fillText(S.parts[i].name, Math.max(0, x) + 4, waveTop + 2);
          ctx.restore();
        }
      }
    }

    // Zbliżenia: pasek z podpisem krotności, Rampy jako ścięte górne rogi
    if (L.zoomRow) {
      const top = L.zoomRow.top, h = L.zoomRow.h;
      const y0 = top + 4, y1 = top + h - 4;
      ctx.textBaseline = 'top';
      for (const z of S.zooms) {
        const sa = seqOf(z.at), sb = seqOf(z.end);
        const a = xS(sa), b = xS(sb);
        if (b < 0 || a > W) continue;
        const ax = clamp(a, -2, W + 2), bx = clamp(b, -2, W + 2);
        const ra = clamp(xS(sa + z.rin), -2, W + 2), rb = clamp(xS(sb - z.rout), -2, W + 2);
        const isSel = S.sel && typeof S.sel === 'object' && S.sel.zoom === z.id;
        const part = isSel ? S.sel.part : undefined;
        ctx.beginPath();
        ctx.moveTo(ax, y1); ctx.lineTo(ra, y0); ctx.lineTo(rb, y0); ctx.lineTo(bx, y1); ctx.closePath();
        ctx.fillStyle = C.zoomFill;
        ctx.fill();
        ctx.lineWidth = isSel && !part ? 2 : 1;
        ctx.strokeStyle = isSel && !part ? C.handleSel : C.zoomBorder;
        ctx.stroke();
        for (const [px, which] of [[ra, 'rin'], [rb, 'rout']]) {
          ctx.fillStyle = part === which ? C.handleSel : C.zoomBorder;
          ctx.fillRect(Math.round(px) - 3, y0 - 2, 6, 6);
        }
        if (part === 'in' || part === 'out') {
          ctx.fillStyle = C.handleSel;
          ctx.fillRect(Math.round(part === 'in' ? a : b) - 1, top + 2, 3, h - 4);
        }
        const lx = Math.max(ax, ra), rx = Math.min(bx, rb);
        ctx.fillStyle = C.text;
        ctx.save();
        ctx.beginPath();
        ctx.rect(lx + 2, top, Math.max(0, rx - lx - 4), h);
        ctx.clip();
        ctx.fillText(fmtZoomLabel(z), lx + 6, top + 9);
        ctx.restore();
      }
    }

    // Podkłady
    ctx.textBaseline = 'top';
    for (const row of L.rows) {
      const p = podByGen(row.gen);
      if (!p) continue;
      const s0 = podStart(p);
      const a = xS(s0), b = xS(podEnd(p));
      if (b < 0 || a > W) continue;
      const ax = clamp(a, -2, W + 2), bx = clamp(b, -2, W + 2);
      const isSel = S.sel && typeof S.sel === 'object' && S.sel.pod === p.gen;
      ctx.fillStyle = C.podFill;
      roundRect(ctx, ax, row.top + 3, bx - ax, row.h - 6, 4);
      ctx.fill();
      const wc = buildPodWave(p, W, row.h - 8, dpr);
      ctx.drawImage(wc, 0, 0, wc.width, wc.height, 0, row.top + 4, W, row.h - 8);
      // szwy odcinków (po Wycięciach na Podkładzie)
      let off = 0;
      for (let k = 0; k + 1 < p.segs.length; k++) {
        off += p.segs[k].tout - p.segs[k].tin;
        const x = xS(s0 + off);
        if (x < 0 || x > W) continue;
        ctx.fillStyle = C.seam;
        for (let y = row.top + 4; y < row.top + row.h - 4; y += 5) ctx.fillRect(Math.round(x), y, 1, 3);
      }
      ctx.lineWidth = isSel && !S.sel.edge ? 2 : 1;
      ctx.strokeStyle = isSel && !S.sel.edge ? C.handleSel : C.podBorder;
      roundRect(ctx, ax + 0.5, row.top + 3.5, bx - ax - 1, row.h - 7, 4);
      ctx.stroke();
      if (isSel && S.sel.edge) {
        ctx.fillStyle = C.handleSel;
        const ex = S.sel.edge === 'in' ? a : b;
        ctx.fillRect(Math.round(ex) - 1, row.top + 2, 3, row.h - 4);
      }
      ctx.fillStyle = C.text;
      ctx.save();
      ctx.beginPath();
      ctx.rect(ax + 2, row.top, Math.max(0, bx - ax - 4), row.h);
      ctx.clip();
      ctx.fillText(p.name, ax + 6, row.top + 5);
      ctx.restore();
      if (S.volLabel && S.volLabel.pod === p.gen && now < S.volLabel.until) {
        drawVolLabel(S.volLabel.text, W, row.top + 4);
      }
    }
    if (S.volLabel && S.volLabel.pod == null && now < S.volLabel.until) drawVolLabel(S.volLabel.text, W, waveTop + 4);

    // przyciemnienie poza Fragmentem: wszystkie wiersze
    ctx.fillStyle = C.outside;
    if (xl > 0) ctx.fillRect(0, waveTop, clamp(xl, 0, W), fullH);
    if (xr < W) ctx.fillRect(clamp(xr, 0, W), waveTop, W - clamp(xr, 0, W), fullH);

    // Wycięcie: czerwony pas z dwiema Krawędziami w wierszu celu (Sekwencja albo Podkład)
    if (S.cut) {
      const c = S.cut;
      const row = cutRow(L);
      const xa = xS(S.seqs[c.a]), xb = xS(S.seqs[c.b]);
      const ax = clamp(xa, -2, W + 2), bx = clamp(xb, -2, W + 2);
      ctx.fillStyle = C.cutFill;
      ctx.fillRect(ax, row.top + 1, bx - ax, row.h - 2);
      const hot = S.drag && S.drag.kind === 'cut' ? S.drag.edge : null;
      for (const [x, edge] of [[xa, 'a'], [xb, 'b']]) {
        if (x < -GRIP_W || x > W + GRIP_W) continue;
        ctx.fillStyle = hot === edge ? C.cutHot : C.cutBorder;
        ctx.fillRect(Math.round(x) - 1, row.top + 1, 2, row.h - 2);
        roundRect(ctx, Math.round(x) - 4, row.top + row.h / 2 - 9, 8, 18, 3);
        ctx.fill();
        ctx.fillStyle = 'rgba(0,0,0,0.35)';
        ctx.fillRect(Math.round(x) - 1, row.top + row.h / 2 - 5, 1, 10);
        ctx.fillRect(Math.round(x) + 1, row.top + row.h / 2 - 5, 1, 10);
      }
    }

    // Gniazda podczas przeciągania
    if (S.dragOver) {
      const rect = canvas.getBoundingClientRect();
      const mx = S.dragOver.x - rect.left, my = S.dragOver.y - rect.top;
      ctx.setLineDash([4, 3]);
      ctx.lineWidth = 1;
      if (S.dragOver[S.kind === 'video' ? 'mp4' : 'mp3']) {
        for (const g of gniazda()) {
          if (g.x1 < 0 || g.x0 > W) continue;
          const hot = my >= waveTop - GRIP_H && my < waveTop + waveH && mx >= g.x0 && mx <= g.x1;
          ctx.fillStyle = hot ? C.gniazdoHot : C.gniazdo;
          roundRect(ctx, g.x0, waveTop + 2, GN_W, waveH - 4, 4);
          ctx.fill();
          ctx.strokeStyle = C.gniazdoBorder;
          ctx.stroke();
        }
      }
      if (L.stripTop != null) {
        const hot = my >= L.stripTop && my < L.stripTop + STRIP_H;
        ctx.fillStyle = hot ? C.gniazdoHot : C.gniazdo;
        roundRect(ctx, 2, L.stripTop + 2, W - 4, STRIP_H - 4, 4);
        ctx.fill();
        ctx.strokeStyle = C.gniazdoBorder;
        ctx.stroke();
        ctx.fillStyle = C.text;
        ctx.font = '11px "Segoe UI", system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(S.kind === 'video' ? 'Podkład' : 'Podkłady działają tylko pod wideo', W / 2, L.stripTop + STRIP_H / 2);
      }
      ctx.setLineDash([]);
    }

    // linijka
    const rulerTop = L.rulerTop;
    const step = rulerStep(W);
    ctx.font = '10px "Segoe UI", system-ui, sans-serif';
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';
    const first = Math.ceil(S.view.start / step - 1e-9);
    const last = Math.floor(S.view.end / step + 1e-9);
    for (let k = first; k <= last; k++) {
      const tt = k * step;
      const x = xS(tt);
      ctx.fillStyle = C.tick;
      ctx.fillRect(Math.round(x), rulerTop - 6, 1, 6);
      ctx.fillStyle = C.textDim;
      ctx.fillText(fmt(tt, step < 1), x, rulerTop + BOTTOM / 2);
    }
    ctx.textAlign = 'right';
    ctx.fillStyle = C.textDim;
    ctx.fillText(fmt(S.duration), W - 4, rulerTop + BOTTOM / 2);

    // suwaki: kreska przez wszystkie wiersze, uchwyt u góry
    for (const kind of ['left', 'right']) {
      const x = kind === 'left' ? xl : xr;
      if (x < -GRIP_W || x > W + GRIP_W) continue;
      const selected = S.sel === kind;
      ctx.fillStyle = selected ? C.handleSel : C.handle;
      ctx.fillRect(Math.round(x) - 1, TOP - 2, 2, rulerTop - TOP + 2);
      const gx = kind === 'left' ? x : x - GRIP_W;
      roundRect(ctx, gx, TOP - GRIP_H + 2, GRIP_W, GRIP_H, 3);
      ctx.fill();
      ctx.fillStyle = 'rgba(0,0,0,0.35)';
      for (let i = 0; i < 2; i++) ctx.fillRect(gx + 4 + i * 3, TOP - GRIP_H + 6, 1, GRIP_H - 8);
    }

    // playhead
    if (xp >= 0 && xp <= W) {
      ctx.fillStyle = C.playhead;
      ctx.fillRect(Math.round(xp), TOP - 2, 1, rulerTop - TOP + 2);
    }

    // etykiety u góry
    ctx.font = '11px "Segoe UI", system-ui, sans-serif';
    const labels = [];
    const active = S.drag && (S.drag.kind === 'left' || S.drag.kind === 'right') ? S.drag.kind
      : (S.sel === 'left' || S.sel === 'right' ? S.sel : null);
    if (active) {
      const i = handleIndex(active);
      const x = active === 'left' ? xl : xr;
      labels.push({ x, text: `${fmt(S.seqs[i])} · kl. ${i}`, col: C.handleSel, prio: 1 });
    }
    if (S.cut) {
      const c = S.cut;
      const x = (xS(S.seqs[c.a]) + xS(S.seqs[c.b])) / 2;
      labels.push({ x, text: cutLabel(c), col: C.cutBorder, prio: 2 });
    }
    const sp = selPod();
    if (sp) {
      const edge = S.sel.edge;
      const tt = edge === 'out' ? podEnd(sp) : podStart(sp);
      const what = edge === 'in' ? 'początek' : edge === 'out' ? 'koniec' : 'Podkład';
      labels.push({ x: xS(tt), text: `${what} ${fmt(tt)}`, col: C.handleSel, prio: 1 });
    }
    const sz = selZoom();
    if (sz) {
      const part = S.sel.part;
      const sa = seqOf(sz.at), sb = seqOf(sz.end);
      const tt = part === 'out' ? sb : part === 'rin' ? sa + sz.rin : part === 'rout' ? sb - sz.rout : sa;
      const ramp = (r) => `Rampa ${r.toFixed(2).replace('.', ',')} s`;
      const what = part === 'in' ? 'początek' : part === 'out' ? 'koniec'
        : part === 'rin' ? ramp(sz.rin) : part === 'rout' ? ramp(sz.rout) : `Zbliżenie ${fmtZoomLabel(sz)}`;
      labels.push({ x: xS(tt), text: `${what} ${fmt(tt)}`, col: C.handleSel, prio: 1 });
    }
    if (xp >= 0 && xp <= W) labels.push({ x: xp, text: fmt(seqOf(t)), col: C.text, prio: 0 });
    const gripBoxes = [];
    for (const kind of ['left', 'right']) {
      const x = kind === 'left' ? xl : xr;
      if (x < -GRIP_W || x > W + GRIP_W) continue;
      gripBoxes.push({ x: kind === 'left' ? x : x - GRIP_W, w: GRIP_W });
    }
    placeLabels(labels, W, gripBoxes);

    // czas pod kursorem
    if (S.hoverX != null && S.hoverT != null && !S.drag && !S.dragOver) {
      const text = fmt(S.hoverT);
      const tw = ctx.measureText(text).width + 8;
      const lx = clamp(S.hoverX - tw / 2, 0, W - tw);
      ctx.fillStyle = 'rgba(20,20,24,0.85)';
      roundRect(ctx, lx, rulerTop + 1, tw, BOTTOM - 2, 3);
      ctx.fill();
      ctx.fillStyle = C.text;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(text, lx + tw / 2, rulerTop + BOTTOM / 2);
    }
  }

  function drawVolLabel(text, W, y) {
    ctx.font = '11px "Segoe UI", system-ui, sans-serif';
    ctx.textBaseline = 'top';
    ctx.textAlign = 'right';
    const tw = ctx.measureText(text).width + 10;
    ctx.fillStyle = 'rgba(20,20,24,0.85)';
    roundRect(ctx, W - tw - 4, y, tw, 16, 3);
    ctx.fill();
    ctx.fillStyle = C.handleSel;
    ctx.fillText(text, W - 9, y + 2);
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
    r = Math.min(r, Math.abs(w) / 2, Math.abs(h) / 2);
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
    const xl = xS(S.seqs[S.left]);
    const xr = xS(S.seqs[S.right]);
    const hl = Math.abs(mx - xl) <= HIT || (mx >= xl && mx <= xl + GRIP_W);
    const hr = Math.abs(mx - xr) <= HIT || (mx <= xr && mx >= xr - GRIP_W);
    if (hl && hr) return mx < (xl + xr) / 2 ? 'left' : 'right';
    if (hl) return 'left';
    if (hr) return 'right';
    return null;
  }

  // Co jest pod kursorem: {kind:'cut', edge} | {kind:'handle', which} | {kind:'pod', gen, edge}
  // | {kind:'zoom', id, part} | {kind:'video'}
  function hitTest(mx, my) {
    const L = layout(stripWanted());
    if (S.cut) {
      const row = cutRow(L);
      if (my >= row.top && my < row.top + row.h) {
        const dA = Math.abs(mx - xS(S.seqs[S.cut.a])), dB = Math.abs(mx - xS(S.seqs[S.cut.b]));
        if (dA <= HIT || dB <= HIT) return { kind: 'cut', edge: dA <= dB ? 'a' : 'b' };
      }
    }
    if (my < L.vidTop + L.vidH) {
      const h = hitHandle(mx);
      return h ? { kind: 'handle', which: h } : { kind: 'video' };
    }
    if (L.zoomRow && my >= L.zoomRow.top && my < L.zoomRow.top + L.zoomRow.h) {
      // górna połowa wiersza przy rogu = Rampa, reszta = Krawędź albo środek
      const upper = my < L.zoomRow.top + L.zoomRow.h / 2;
      for (const z of S.zooms) {
        const sa = seqOf(z.at), sb = seqOf(z.end);
        const a = xS(sa), b = xS(sb);
        const ra = xS(sa + z.rin), rb = xS(sb - z.rout);
        const dRa = Math.abs(mx - ra), dRb = Math.abs(mx - rb);
        if (upper && (dRa <= HIT || dRb <= HIT)) return { kind: 'zoom', id: z.id, part: dRa <= dRb ? 'rin' : 'rout' };
        const dA = Math.abs(mx - a), dB = Math.abs(mx - b);
        if (dA <= HIT || dB <= HIT) return { kind: 'zoom', id: z.id, part: dA <= dB ? 'in' : 'out' };
        if (mx >= a && mx <= b) return { kind: 'zoom', id: z.id, part: null };
      }
      const h = hitHandle(mx);
      return h ? { kind: 'handle', which: h } : { kind: 'video' };
    }
    for (const row of L.rows) {
      if (my < row.top || my >= row.top + row.h) continue;
      const p = podByGen(row.gen);
      if (!p) break;
      const a = xS(podStart(p)), b = xS(podEnd(p));
      const dA = Math.abs(mx - a), dB = Math.abs(mx - b);
      if (dA <= HIT || dB <= HIT) {
        if (dA <= HIT && dB <= HIT) return { kind: 'pod', gen: p.gen, edge: mx < (a + b) / 2 ? 'in' : 'out' };
        return { kind: 'pod', gen: p.gen, edge: dA <= HIT ? 'in' : 'out' };
      }
      if (mx >= a && mx <= b) return { kind: 'pod', gen: p.gen, edge: null };
      const h = hitHandle(mx);
      return h ? { kind: 'handle', which: h } : { kind: 'video' };
    }
    const h = hitHandle(mx);
    return h ? { kind: 'handle', which: h } : { kind: 'video' };
  }

  function handleIndexFromX(kind, mx) {
    const s = sOf(mx);
    if (s >= S.duration) return S.N;
    if (s <= 0) return 0;
    return ordAtS(s);
  }

  // Krawędź Wycięcia pod kursorem (z Przyciąganiem; Playhead pokazuje Klatkę pod Krawędzią).
  function dragCutTo(mx, ctrl) {
    const c = S.cut;
    if (!c) return;
    let s = clamp(sOf(mx), 0, S.duration);
    if (!ctrl) { const t = snap(s, snapTargets(null, null, true)); if (t != null) s = t; }
    if (S.drag.edge === 'a') { setCutA(ordAtS(s)); seekFrame(c.a); }
    else { setCutB(endIndexAtS(s)); seekFrame(Math.min(c.b, S.N - 1)); }
  }

  canvas.addEventListener('pointerdown', (e) => {
    if (!S.loaded || e.button !== 0) return;
    try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* syntetyczne zdarzenia */ }
    const mx = e.offsetX, my = e.offsetY;
    const h = hitTest(mx, my);
    if (h.kind === 'cut') {
      pause();
      S.drag = { kind: 'cut', edge: h.edge };
      dragCutTo(mx, e.ctrlKey);
    } else if (h.kind === 'handle') {
      pause();
      S.sel = h.which;
      S.drag = { kind: h.which };
      moveHandleTo(h.which, handleIndexFromX(h.which, mx));
    } else if (S.cut) {
      // przy Wycięciu zaznaczenie stoi (cel Wycięcia jest stały): klik tylko ustawia Playhead
      S.drag = { kind: 'scrub' };
      seek(tOf(mx));
    } else if (h.kind === 'pod') {
      pause();
      const p = podByGen(h.gen);
      S.sel = { pod: h.gen, edge: h.edge };
      S.drag = { kind: 'pod', gen: h.gen, edge: h.edge, grab: sOf(mx) - podStart(p) };
    } else if (h.kind === 'zoom') {
      pause();
      const z = zoomById(h.id);
      S.sel = { zoom: h.id, part: h.part };
      S.drag = { kind: 'zoom', id: h.id, part: h.part, grab: sOf(mx) - seqOf(z.at) };
    } else {
      S.sel = null;
      S.drag = { kind: 'scrub' };
      seek(tOf(mx));
    }
  });

  canvas.addEventListener('pointermove', (e) => {
    const mx = e.offsetX, my = e.offsetY;
    S.hoverX = mx;
    S.hoverT = S.loaded ? clamp(sOf(mx), 0, extent()) : null;
    if (!S.loaded) return;
    if (S.drag) {
      if (S.drag.kind === 'scrub') {
        seek(tOf(mx));
      } else if (S.drag.kind === 'cut') {
        dragCutTo(mx, e.ctrlKey);
      } else if (S.drag.kind === 'pod') {
        const p = podByGen(S.drag.gen);
        if (p) {
          const doSnap = !e.ctrlKey;
          if (S.drag.edge === 'in') setPodIn(p, sOf(mx), doSnap);
          else if (S.drag.edge === 'out') setPodOut(p, sOf(mx), doSnap);
          else movePodTo(p, sOf(mx) - S.drag.grab, doSnap);
        }
      } else if (S.drag.kind === 'zoom') {
        const z = zoomById(S.drag.id);
        if (z) {
          const doSnap = !e.ctrlKey;
          const s = sOf(mx);
          if (S.drag.part === 'in') setZoomIn(z, s, doSnap);
          else if (S.drag.part === 'out') setZoomOut(z, s, doSnap);
          else if (S.drag.part === 'rin') setRampIn(z, s, doSnap);
          else if (S.drag.part === 'rout') setRampOut(z, s, doSnap);
          else moveZoomTo(z, s - S.drag.grab, doSnap);
        }
      } else {
        moveHandleTo(S.drag.kind, handleIndexFromX(S.drag.kind, mx));
      }
      canvas.style.cursor = 'grabbing';
    } else {
      const h = hitTest(mx, my);
      canvas.style.cursor = h.kind === 'cut' || h.kind === 'handle' || (h.kind === 'pod' && h.edge) || (h.kind === 'zoom' && h.part) ? 'ew-resize'
        : (h.kind === 'pod' || h.kind === 'zoom') && !S.cut ? 'grab' : 'default';
    }
  });

  function endDrag(e) {
    if (S.drag) {
      S.drag = null;
      try { canvas.releasePointerCapture(e.pointerId); } catch (err) { /* */ }
      fitView();
    }
  }
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);
  canvas.addEventListener('pointerleave', () => { S.hoverX = null; S.hoverT = null; });

  canvas.addEventListener('dblclick', () => {
    if (!S.loaded) return;
    S.viewFull = true;
    fitView();
    invalidateWave();
  });

  canvas.addEventListener('wheel', (e) => {
    if (!S.loaded) return;
    e.preventDefault();
    const v = S.view;
    const ext = extent();
    const span = v.end - v.start;
    const delta = e.deltaY !== 0 ? e.deltaY : e.deltaX;
    if (e.shiftKey) {
      const shift = (delta / 100) * span * 0.1;
      const start = clamp(v.start + shift, 0, ext - span);
      S.view = { start, end: start + span };
    } else {
      const minSpan = Math.min(ext, Math.max(20 * S.frameStep, 0.2));
      const f = Math.pow(1.18, -delta / 100);
      const newSpan = clamp(span / f, minSpan, ext);
      const s = sOf(e.offsetX);
      let start = s - (s - v.start) * (newSpan / span);
      start = clamp(start, 0, ext - newSpan);
      S.view = { start, end: start + newSpan };
      S.viewFull = newSpan >= ext - 1e-9;
    }
    invalidateWave();
    S.hoverT = clamp(sOf(e.offsetX), 0, ext);
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

  // Zaznaczone Zbliżenie nie przejmuje strzałek: chodzą po Klatkach jak bez zaznaczenia, żeby dało się
  // ustawiać Kadr klatka po klatce. Samo Zbliżenie przesuwa Ctrl+←/→ (z Shift: 1 s).
  // Przy Wycięciu strzałki ruszają Playhead (żeby dojechać do Krawędzi i dociągnąć ją C) albo Suwak.
  function stepBy(dir, big) {
    if (!S.loaded) return;
    const sp = S.cut ? null : selPod();
    if (sp) { stepPod(sp, S.sel.edge, dir, big); return; }
    if (S.sel === 'left' || S.sel === 'right') {
      const i = stepIndex(handleIndex(S.sel), dir, big);
      moveHandleTo(S.sel, i);
      ensureVisible(S.seqs[handleIndex(S.sel)]);
      return;
    }
    if (S.playing) pause();
    const t = curTime();
    let i = frameIndex(t);
    if (i >= S.N) i = S.N - 1;
    let target;
    if (dir < 0 && t > frameTs(i) + 2 * eps() && !big) target = i;
    else target = stepIndex(i, dir, big);
    target = clamp(target, 0, S.N - 1);
    seekFrame(target);
    ensureVisible(S.seqs[target]);
  }

  function volBy(dir, fine) {
    if (!S.loaded || S.kind !== 'video' || selZoom()) return;
    if (blockedByCut()) return;
    const sp = selPod();
    setGain(sp || S, dir, fine);
  }

  function deleteSelected() {
    if (!S.loaded || S.busy || S.exporting) return;
    if (S.cut) { executeCut(); return; }
    const sz = selZoom();
    if (sz) {
      // Rampa to ustawienie, nie element: Delete ją zeruje, całe Zbliżenie znika przy środku/Krawędzi.
      if (S.sel.part === 'rin') sz.rin = 0;
      else if (S.sel.part === 'rout') sz.rout = 0;
      else removeZoom(sz.id);
      return;
    }
    const sp = selPod();
    if (sp) { removePod(sp.gen); return; }
    if (S.sel) return;  // zaznaczony Suwak: Delete nic nie robi
    // Nagranie pod Playheadem: to Wycięcie pokrywające całe Nagranie (Ctrl+Z cofa)
    if (S.pieces.length < 2) { showStatus('Ostatniego Nagrania nie da się usunąć', 'error', '', 3000); return; }
    cancelPreviewDrag();
    pause();
    const pc = S.pieces[pieceIndexAt(clamp(frameIndex(curTime()), 0, S.N - 1))];
    cutFrames(pc.ia, pc.ib, 'Usunięto Nagranie ✓');
  }

  window.addEventListener('keydown', (e) => {
    if ((e.code === 'Enter' || e.code === 'NumpadEnter') && e.ctrlKey && !e.altKey && !e.metaKey) {
      e.preventDefault();
      if (!e.repeat) doExport('small');
      return;
    }
    if (e.code === 'KeyZ' && e.ctrlKey && !e.altKey && !e.metaKey) {
      e.preventDefault();
      if (e.repeat) return;
      if (S.cut) discardCut(); else undo();
      return;
    }
    if ((e.code === 'ArrowLeft' || e.code === 'ArrowRight') && e.ctrlKey && !e.altKey && !e.metaKey) {
      e.preventDefault();
      if (e.repeat) return;
      const sz = selZoom();
      if (!sz) return;
      if (blockedByCut()) return;
      const dir = e.code === 'ArrowLeft' ? -1 : 1;
      const big = e.shiftKey, part = S.sel.part;
      stepZoom(sz, part, dir, big);
      startRepeat(() => { const z = selZoom(); if (z) stepZoom(z, S.sel.part, dir, big); });
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
      case 'ArrowUp':
      case 'ArrowDown': {
        e.preventDefault();
        if (e.repeat) return;
        const dir = e.code === 'ArrowUp' ? 1 : -1;
        const fine = e.shiftKey;
        volBy(dir, fine);
        if (!S.cut) startRepeat(() => volBy(dir, fine));
        break;
      }
      case 'Enter':
      case 'NumpadEnter':
        e.preventDefault();
        if (!e.repeat) doExport('full');
        break;
      case 'Escape':
        if (S.pdrag) cancelPreviewDrag();
        else if (S.cut) discardCut();
        else S.sel = null;
        break;
      case 'KeyZ':
        if (S.cut) { if (!e.repeat) blockedByCut(); break; }
        S.zKey = true;
        break;
      case 'KeyC':
        if (!e.repeat) startCut();
        break;
      case 'Delete':
      case 'Backspace':
        e.preventDefault();
        if (!e.repeat) deleteSelected();
        break;
      case 'Home': {
        e.preventDefault();
        const sp = S.cut ? null : selPod();
        if (sp) { movePodTo(sp, 0, false); fitView(); ensureVisible(podStart(sp)); }
        else if (S.sel === 'left' || S.sel === 'right') moveHandleTo(S.sel, 0);
        else { pause(); seekFrame(0); }
        break;
      }
      case 'End': {
        e.preventDefault();
        const sp = S.cut ? null : selPod();
        if (sp) { movePodTo(sp, Math.max(0, S.duration - podLen(sp)), false); fitView(); ensureVisible(podEnd(sp)); }
        else if (S.sel === 'left' || S.sel === 'right') moveHandleTo(S.sel, S.N);
        else { pause(); seekFrame(S.N - 1); }
        break;
      }
    }
  });
  window.addEventListener('keyup', (e) => {
    if (e.code.startsWith('Arrow')) stopRepeat();
    if (e.code === 'KeyZ') S.zKey = false;
  });
  window.addEventListener('blur', () => { stopRepeat(); S.zKey = false; });

  // ---------- podgląd: Kadry (nakładka nad wideo) ----------
  // Na pauzie widać cały obraz z obrysami Kadrów A i B Zbliżenia pod Playheadem (albo Kadru A
  // otwartego procesu); w trakcie odtwarzania wideo dostaje transform i wygląda jak w wyniku.
  function videoRect() {
    const pw = previewEl.clientWidth, ph = previewEl.clientHeight;
    if (!S.width || !S.height) return { x: 0, y: 0, w: pw, h: ph };
    const sc = Math.min(pw / S.width, ph / S.height);
    const w = S.width * sc, h = S.height * sc;
    return { x: (pw - w) / 2, y: (ph - h) / 2, w, h };
  }
  function kadrPx(k, R) { return { x: R.x + k.x * R.w, y: R.y + k.y * R.h, w: k.s * R.w, h: k.s * R.h }; }
  function normPt(px, py, R) { return { x: (px - R.x) / R.w, y: (py - R.y) / R.h }; }
  function isPlaying() { return S.loaded && S.playing && !video.paused; }

  // Kadr do pokazania i edycji na pauzie: Zbliżenie pod Playheadem (pozycja z tej Klatki, przerywany,
  // gdy przejeżdża) albo Cień skrajnego Kadru zaznaczonego Zbliżenia w luce obok niego.
  function visibleKadry() {
    if (!S.loaded || S.kind !== 'video') return [];
    const t = quantAt(curTime());
    const z = zoomAt(t);
    if (z) {
      const k = kadrKeys(z, t);
      return [{ k, tag: fmtFactor(k), col: C.kadr, dashed: !kadrHolds(z, t), target: { z, t } }];
    }
    const sz = selZoom();
    if (!sz) return [];
    const { lo, hi } = zoomNeighbours(sz);
    const i = frameIndex(t);
    if (i < frameIndex(sz.at) && i >= lo) {
      return [{ k: { ...sz.keys[0].k }, tag: 'Cień', col: C.kadrGhost, dashed: true, target: { z: sz, t, extend: 'in' } }];
    }
    if (i >= frameIndex(sz.end) && i < hi) {
      return [{ k: { ...sz.keys[sz.keys.length - 1].k }, tag: 'Cień', col: C.kadrGhost, dashed: true, target: { z: sz, t, extend: 'out' } }];
    }
    return [];
  }
  // Edycja na Klatce zapamiętuje pozycję w tej Klatce; złapany Cień najpierw wydłuża przedział.
  function applyKadr(target, k) {
    const z = target.z;
    if (target.extend === 'in') { setZoomRange(z, frameIndex(target.t), frameIndex(z.end)); target.extend = null; }
    else if (target.extend === 'out') { setZoomRange(z, frameIndex(z.at), frameIndex(target.t) + 1); target.extend = null; }
    setKey(z, target.t, k);
    clampRamps(z);
  }
  // Rysowanie: przekątna gestu, dłuższy bok wygrywa, proporcje obrazu, min. KADR_MIN.
  function kadrFromDrag(p0, p1) {
    const dx = p1.x - p0.x, dy = p1.y - p0.y;
    const s_ = clamp(Math.max(Math.abs(dx), Math.abs(dy)), KADR_MIN, 1);
    return clampKadr({ x: dx >= 0 ? p0.x : p0.x - s_, y: dy >= 0 ? p0.y : p0.y - s_, s: s_ });
  }
  // Zmiana wielkości za róg: przeciwległy róg stoi w miejscu, Kadr nie wychodzi poza obraz.
  function resizeKadr(k0, corner, p) {
    const fx = corner.includes('w') ? k0.x + k0.s : k0.x;
    const fy = corner.includes('n') ? k0.y + k0.s : k0.y;
    let s_ = Math.max(Math.abs(p.x - fx), Math.abs(p.y - fy));
    const maxS = Math.min(corner.includes('w') ? fx : 1 - fx, corner.includes('n') ? fy : 1 - fy);
    s_ = clamp(s_, KADR_MIN, Math.max(KADR_MIN, maxS));
    return clampKadr({ x: corner.includes('w') ? fx - s_ : fx, y: corner.includes('n') ? fy - s_ : fy, s: s_ });
  }
  function hitKadr(px, py) {
    const R = videoRect();
    const vis = visibleKadry();
    let best = null, bestD = CORNER + 3;
    for (const v of vis) {
      const r = kadrPx(v.k, R);
      for (const [c, cx, cy] of [['nw', r.x, r.y], ['ne', r.x + r.w, r.y], ['sw', r.x, r.y + r.h], ['se', r.x + r.w, r.y + r.h]]) {
        const d = Math.hypot(px - cx, py - cy);
        if (d < bestD) { bestD = d; best = { kind: 'resize', v, corner: c }; }
      }
    }
    if (best) return best;
    let inside = null;
    for (const v of vis) {
      const r = kadrPx(v.k, R);
      if (px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h && (!inside || v.k.s < inside.k.s)) inside = v;
    }
    return inside ? { kind: 'move', v: inside } : null;
  }

  ov.addEventListener('pointerdown', (e) => {
    if (!S.loaded || S.kind !== 'video' || e.button !== 0) return;
    if (S.cut) { blockedByCut(); return; }
    const R = videoRect();
    const p = normPt(e.offsetX, e.offsetY, R);
    if (S.zKey) {
      pause();
      try { ov.setPointerCapture(e.pointerId); } catch (err) { /* syntetyczne zdarzenia */ }
      S.pdrag = { kind: 'draw', p0: p, px0: e.offsetX, py0: e.offsetY, kadr: null, moved: false };
      return;
    }
    if (isPlaying()) return;
    const h = hitKadr(e.offsetX, e.offsetY);
    if (!h) return;
    try { ov.setPointerCapture(e.pointerId); } catch (err) { /* */ }
    if (h.kind === 'move') S.pdrag = { kind: 'move', target: h.v.target, k0: { ...h.v.k }, grab: { x: p.x - h.v.k.x, y: p.y - h.v.k.y } };
    else S.pdrag = { kind: 'resize', target: h.v.target, k0: { ...h.v.k }, corner: h.corner };
  });
  ov.addEventListener('pointermove', (e) => {
    if (!S.loaded || S.kind !== 'video') return;
    const R = videoRect();
    const p = normPt(e.offsetX, e.offsetY, R);
    const d = S.pdrag;
    if (d) {
      if (d.kind === 'draw') {
        if (Math.hypot(e.offsetX - d.px0, e.offsetY - d.py0) >= 4) d.moved = true;
        if (d.moved) d.kadr = kadrFromDrag(d.p0, p);
      } else if (d.kind === 'move') {
        applyKadr(d.target, { x: p.x - d.grab.x, y: p.y - d.grab.y, s: d.k0.s });
      } else {
        applyKadr(d.target, resizeKadr(d.k0, d.corner, p));
      }
      ov.style.cursor = d.kind === 'draw' ? 'crosshair' : 'grabbing';
      return;
    }
    if (S.zKey) { ov.style.cursor = 'crosshair'; return; }
    const h = isPlaying() || S.cut ? null : hitKadr(e.offsetX, e.offsetY);
    ov.style.cursor = !h ? 'default' : h.kind === 'move' ? 'move'
      : (h.corner === 'nw' || h.corner === 'se') ? 'nwse-resize' : 'nesw-resize';
  });
  function endPreviewDrag(e) {
    const d = S.pdrag;
    if (!d) return;
    S.pdrag = null;
    try { ov.releasePointerCapture(e.pointerId); } catch (err) { /* */ }
    if (d.kind === 'draw' && d.moved && d.kadr) commitKadr(d.kadr);
  }
  ov.addEventListener('pointerup', endPreviewDrag);
  ov.addEventListener('pointercancel', endPreviewDrag);
  ov.addEventListener('pointerleave', () => { if (!S.pdrag) ov.style.cursor = 'default'; });

  function drawKadr(r, tag, col, dashed, handles) {
    octx.setLineDash(dashed ? [6, 4] : []);
    octx.lineWidth = 2;
    octx.strokeStyle = col;
    octx.strokeRect(Math.round(r.x) + 0.5, Math.round(r.y) + 0.5, Math.round(r.w) - 1, Math.round(r.h) - 1);
    octx.setLineDash([]);
    if (handles) {
      octx.fillStyle = col;
      for (const [cx, cy] of [[r.x, r.y], [r.x + r.w, r.y], [r.x, r.y + r.h], [r.x + r.w, r.y + r.h]]) {
        octx.fillRect(Math.round(cx) - CORNER / 2, Math.round(cy) - CORNER / 2, CORNER, CORNER);
      }
    }
    if (tag) {
      octx.font = '12px "Segoe UI", system-ui, sans-serif';
      octx.textBaseline = 'top';
      octx.textAlign = 'left';
      const tw = octx.measureText(tag).width + 10;
      octx.fillStyle = col;
      octx.fillRect(r.x + 6, r.y + 6, tw, 18);
      octx.fillStyle = '#111';
      octx.fillText(tag, r.x + 11, r.y + 8);
    }
  }

  function drawOverlay() {
    const dpr = window.devicePixelRatio || 1;
    const pw = previewEl.clientWidth || 1, ph = previewEl.clientHeight || 1;
    const w = Math.round(pw * dpr), h = Math.round(ph * dpr);
    if (ov.width !== w || ov.height !== h) { ov.width = w; ov.height = h; }
    octx.setTransform(dpr, 0, 0, dpr, 0, 0);
    octx.clearRect(0, 0, pw, ph);
    const playing = isPlaying();
    const k = playing && S.kind === 'video' ? kadrNow(curTime()) : null;
    if (k && (k.s < 1 - 1e-6 || k.x > 1e-6 || k.y > 1e-6)) {
      const R = videoRect();
      const f = 1 / k.s;
      const tx = R.x - (R.x + k.x * R.w) * f, ty = R.y - (R.y + k.y * R.h) * f;
      video.style.transform = `translate(${tx.toFixed(2)}px, ${ty.toFixed(2)}px) scale(${f.toFixed(4)})`;
    } else if (video.style.transform) {
      video.style.transform = '';
    }
    if (!S.loaded || S.kind !== 'video' || playing) return;
    const R = videoRect();
    const vis = visibleKadry();
    for (const v of vis) drawKadr(kadrPx(v.k, R), v.tag, v.col, v.dashed, true);
    // w Rampie obraz jest jeszcze między całością a Kadrem: to, co widać, białą przerywaną linią
    const t = curTime();
    const z = zoomAt(t);
    if (z) {
      const kn = kadrAt(z, t);
      if (kn && !vis.some((v) => sameKadr(v.k, kn))) drawKadr(kadrPx(kn, R), '', C.kadrNow, true, false);
    }
    if (S.pdrag && S.pdrag.kind === 'draw' && S.pdrag.kadr) drawKadr(kadrPx(S.pdrag.kadr, R), '', C.kadr, false, true);
  }

  // ---------- drag & drop ----------
  // Ścieżki plików zna tylko Python (pywebview dokleja je natywnie i wysyła zdarzenie
  // `dropped`), a gdzie upuszczono, wie UI. `dropFiles` to jedyny punkt wejścia routingu:
  // podgląd = podmiana sesji, Gniazdo = wstawienie do Sekwencji, pasek = nowy Podkład.
  let dragDepth = 0;

  function dragKinds(dt) {
    let mp4 = false, mp3 = false, known = false;
    const items = dt && dt.items ? dt.items : [];
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (it.kind !== 'file') continue;
      const ty = String(it.type || '').toLowerCase();
      if (!ty) continue;
      known = true;
      if (ty === 'video/mp4') mp4 = true;
      if (ty === 'audio/mpeg' || ty === 'audio/mp3') mp3 = true;
    }
    if (!known) return { mp4: true, mp3: true };
    return { mp4, mp3 };
  }

  function overPreview(x, y, rect) {
    const r = rect || previewEl.getBoundingClientRect();
    return x >= r.left && x < r.right && y >= r.top && y < r.bottom;
  }

  function updateDragOver(e) {
    const k = dragKinds(e.dataTransfer);
    S.dragOver = { x: e.clientX, y: e.clientY, mp4: k.mp4, mp3: k.mp3 };
    const onPreview = !S.loaded || overPreview(e.clientX, e.clientY);
    document.body.classList.toggle('dragover', onPreview);
  }

  window.addEventListener('dragenter', (e) => {
    e.preventDefault();
    dragDepth++;
    updateDragOver(e);
  });
  window.addEventListener('dragover', (e) => {
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    updateDragOver(e);
  });
  window.addEventListener('dragleave', (e) => {
    e.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) { S.dragOver = null; document.body.classList.remove('dragover'); }
  });
  window.addEventListener('drop', (e) => {
    e.preventDefault();
    dragDepth = 0;
    // Zdjęcie geometrii z chwili upuszczenia: po zniknięciu paska Gniazda canvas się kurczy,
    // a zdarzenie `dropped` z Pythona przychodzi chwilę później.
    S.lastDrop = { x: e.clientX, y: e.clientY, t: performance.now(),
      canvas: canvas.getBoundingClientRect(), preview: previewEl.getBoundingClientRect() };
    S.dragOver = null;
    document.body.classList.remove('dragover');
  });

  function dropFiles(paths, x, y) {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !paths || !paths.length) return 'none';
    paths = paths.slice().sort((a, b) => String(a).localeCompare(String(b), 'pl', { numeric: true }));
    const snap = S.lastDrop && performance.now() - S.lastDrop.t < 3000 ? S.lastDrop : null;
    S.lastDrop = null;
    if (snap && (x == null || y == null)) { x = snap.x; y = snap.y; }
    if (S.loaded && blockedByCut()) return 'cut';
    if (!S.loaded || x == null || y == null) { cancelPreviewDrag(); api.open_path(paths[0]); return 'open'; }
    const prevRect = snap ? snap.preview : previewEl.getBoundingClientRect();
    if (overPreview(x, y, prevRect)) { cancelPreviewDrag(); api.open_path(paths[0]); return 'open'; }
    const rect = snap ? snap.canvas : canvas.getBoundingClientRect();
    const mx = x - rect.left, my = y - rect.top;
    if (mx < 0 || mx > rect.width) return 'none';
    if (S.busy || S.exporting) { showStatus('Poczekaj na zakończenie bieżącej operacji', 'error', '', 3000); return 'busy'; }
    const L = layout(true);
    const g = gniazdoAt(mx, my, L);
    if (g) {
      const same = paths.filter((p) => extOf(p) === seqExt());
      if (!same.length) {
        showStatus(`Do Sekwencji można wstawić tylko ${seqExt().slice(1).toUpperCase()}`, 'error', '', 4000);
        return 'reject';
      }
      cancelPreviewDrag();
      pause();
      S.busy = true;
      showStatus('Sklejanie… 0%', 'progress');
      api.join(same, g.index).catch(() => { S.busy = false; });
      return 'join';
    }
    if (my >= L.stripTop && my < L.stripTop + STRIP_H) {
      if (S.kind !== 'video') { showStatus('Podkłady działają tylko pod Sekwencją wideo', 'error', '', 4000); return 'reject'; }
      const mp3 = paths.filter((p) => extOf(p) === '.mp3');
      if (!mp3.length) { showStatus('Podkładem może być tylko plik MP3', 'error', '', 4000); return 'reject'; }
      for (const p of mp3) api.add_podklad(p).catch(() => {});
      return 'podklad';
    }
    return 'none';
  }

  // ---------- start ----------
  function announceReady() {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.ready().catch(() => {});
    }
  }
  if (window.pywebview && window.pywebview.api) announceReady();
  else window.addEventListener('pywebviewready', announceReady);

  window.__ciach = { S, frameTs, frameIndex, seqOf, fileOf, ordAtS, holesIn, video, dropFiles, layout, extent, podByGen,
    podStart, podEnd, podLen, zoomAt, kadrAt, kadrKeys, commitKadr, visibleKadry, videoRect, ov, startCut, executeCut, undo };
  requestAnimationFrame(tick);
})();
