(function () {
  'use strict';

  ['assert', 'group', 'groupEnd'].forEach(function (m) {
    if (typeof console[m] !== 'function') console[m] = function () {};
  });

  if (typeof OpenSeadragon === 'undefined') {
    document.body.innerHTML =
      '<div style="padding:24px;color:#ff6b6b;font-family:monospace">' +
      'OpenSeadragon was not found.<br>Place a build at ' +
      '<b>static/vendor/openseadragon/openseadragon.min.js</b> — see README.md.</div>';
    return;
  }

  var $ = function (id) { return document.getElementById(id); };
  var SLOTS = ['A', 'B', 'C', 'D', 'E'];          // up to 5 slides at once
  var slides = {};                                 // slot -> {item,name,slot,angle,x,y,width,opacity}

  function status(t) { $('status').textContent = t; }
  function msg(t) {
    var m = $('msg');
    if (!t) { m.style.display = 'none'; return; }
    m.textContent = t; m.style.display = 'block';
  }
  function busy(on, text) {
    if (text) $('busyText').textContent = text;
    $('busy').classList.toggle('show', !!on);
  }
  function hasApi(fn) { return window.pywebview && window.pywebview.api && window.pywebview.api[fn]; }

  function loadedSlots() { return SLOTS.filter(function (s) { return slides[s]; }); }
  function nextFreeSlot() {
    for (var i = 0; i < SLOTS.length; i++) if (!slides[SLOTS[i]]) return SLOTS[i];
    return null;
  }
  function activeSlot() { var v = $('active').value; return slides[v] ? v : null; }

  var viewer = OpenSeadragon({
    id: 'osd',
    showNavigationControl: false,
    drawer: 'canvas',
    visibilityRatio: 0.05,
    minZoomImageRatio: 0.02,
    maxZoomPixelRatio: 32,
    smoothTileEdgesMinZoom: 0,
    immediateRender: true,
    placeholderFillStyle: '#f0f0f0',
    animationTime: 0.3
  });
  viewer.addHandler('zoom', updateMag);
  viewer.addHandler('animation', updateMag);
  viewer.addHandler('open', updateMag);
  viewer.addHandler('add-item', updateMag);

  // drag the active slide to reposition it
  viewer.addHandler('canvas-drag', function (ev) {
    var t = activeSlot(); if (!t) return;
    ev.preventDefaultAction = true;
    var d = viewer.viewport.deltaPointsFromPixels(new OpenSeadragon.Point(ev.delta.x, ev.delta.y));
    var s = slides[t];
    s.x += d.x; s.y += d.y;
    s.item.setPosition(new OpenSeadragon.Point(s.x, s.y), true);
  });
  // scroll-wheel resizes the active slide
  viewer.addHandler('canvas-scroll', function (ev) {
    var t = activeSlot(); if (!t) return;
    ev.preventDefaultAction = true;
    scaleSlide(t, ev.scroll > 0 ? 1.06 : 1 / 1.06);
  });

  // -------------------------------------------------------------- open / remove
  async function openSlide() {
    var slot = nextFreeSlot();
    if (!slot) { msg('You can open up to ' + SLOTS.length + ' slides at once. Remove one first.'); return; }

    var path = null;
    try { if (hasApi('open_vmic')) path = await window.pywebview.api.open_vmic(); } catch (e) {}
    if (!path) path = window.prompt('Full path to the .vmic file:');
    if (!path) return;

    status('opening ' + path + ' …');
    var meta;
    try {
      var res = await fetch('/api/open', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slot: slot, path: path })
      });
      meta = await res.json();
    } catch (e) { msg('open failed: ' + e); status('error'); return; }
    if (meta.error) { msg('open failed: ' + meta.error); status('error'); return; }
    addSlide(slot, meta);
  }

  function addSlide(slot, meta) {
    var first = loadedSlots().length === 0;
    var opacity = first ? 1.0 : 0.5;
    viewer.addTiledImage({
      tileSource: meta.dzi,
      x: 0, y: 0, width: 1,
      opacity: opacity,
      success: function (ev) {
        slides[slot] = { item: ev.item, name: meta.name, slot: slot, angle: 0, x: 0, y: 0, width: 1, opacity: opacity };
        if (first) viewer.viewport.goHome(true);
        rebuildSlotUI();
        $('active').value = slot;        // make the newly opened slide active
        syncControls();
        updateStatus();
        updateMag();
      },
      error: function (ev) { msg('viewer could not load slide ' + slot + ': ' + (ev.message || '')); }
    });
  }

  function removeActive() {
    var t = activeSlot(); if (!t) return;
    if (slides[t] && slides[t].item) viewer.world.removeItem(slides[t].item);
    delete slides[t];
    $('active').value = 'view';
    rebuildSlotUI();
    syncControls();
    updateStatus();
    updateMag();
  }

  function updateStatus() {
    var ls = loadedSlots();
    status(ls.length ? ls.map(function (s) { return s + ': ' + slides[s].name; }).join('   ') : 'no slide loaded');
  }

  // rebuild the Active dropdown and the per-slide Save buttons
  function rebuildSlotUI() {
    var sel = $('active'), cur = sel.value;
    sel.innerHTML = '<option value="view">View (pan / zoom)</option>';
    loadedSlots().forEach(function (s) {
      var o = document.createElement('option');
      o.value = s; o.textContent = 'Slide ' + s;
      sel.appendChild(o);
    });
    sel.value = slides[cur] ? cur : 'view';

    var sb = $('saveButtons'); sb.innerHTML = '';
    loadedSlots().forEach(function (s) {
      var b = document.createElement('button');
      b.textContent = s;
      b.title = 'Save slide ' + s + ' rotated, as a new VMIC';
      b.onclick = function () { saveRotated(s); };
      sb.appendChild(b);
    });
  }

  // ------------------------------- zoom magnification (relative to first view)
  function homeZoom() { try { return viewer.viewport.getHomeZoom(); } catch (e) { return null; } }
  function factorNow() {
    var hz = homeZoom();
    if (!hz || !viewer.world.getItemCount()) return null;
    return viewer.viewport.getZoom(true) / hz;
  }
  function fmt(m) {
    if (m >= 10) return String(Math.round(m));
    if (m >= 1) return String(Math.round(m * 10) / 10);
    return String(Math.round(m * 100) / 100);
  }
  function updateMag() {
    var f = factorNow();
    if (f === null) return;
    var inp = $('magInput');
    if (document.activeElement !== inp) inp.value = fmt(f);
  }
  function applyMag() {
    var hz = homeZoom();
    if (!hz) return;
    var tgt = parseFloat($('magInput').value);
    if (!isFinite(tgt) || tgt <= 0) return;
    viewer.viewport.zoomTo(tgt * hz);
    viewer.viewport.applyConstraints();
  }

  // -------------------------------------------- controls bound to active slide
  function syncControls() {
    var t = activeSlot(), on = !!t;
    ['sizePct', 'rot', 'rotnum', 'op', 'removeBtn'].forEach(function (id) { $(id).disabled = !on; });
    if (on) {
      var s = slides[t];
      $('sizePct').value = Math.round(s.width * 1000) / 10;
      $('rot').value = s.angle; $('rotnum').value = s.angle;
      $('op').value = s.opacity;
    }
  }
  function setRot(deg) {
    var t = activeSlot(); if (!t) return;
    deg = parseFloat(deg) || 0;
    var s = slides[t];
    if (s.item.setRotation) { s.item.setRotation(deg); s.angle = deg; }
    $('rot').value = deg; $('rotnum').value = deg;
  }
  function nudge(dx, dy) {
    var t = activeSlot();
    if (!t) { msg('Pick a slide in the Active menu first.'); return; }
    var s = slides[t];
    s.x += dx; s.y += dy;
    s.item.setPosition(new OpenSeadragon.Point(s.x, s.y), true);
  }
  function scaleSlide(slot, factor) {
    var s = slides[slot]; if (!s || !s.item) return;
    var cs = s.item.getContentSize();
    var aspect = cs.y / cs.x;
    var w0 = s.width, w1 = w0 * factor;
    var h0 = w0 * aspect, h1 = w1 * aspect;
    s.x -= (w1 - w0) / 2;
    s.y -= (h1 - h0) / 2;
    s.width = w1;
    s.item.setPosition(new OpenSeadragon.Point(s.x, s.y), true);
    s.item.setWidth(w1, true);
    if (activeSlot() === slot) $('sizePct').value = Math.round(s.width * 1000) / 10;
  }
  function setSizeAbsolute(slot, widthFraction) {
    var s = slides[slot];
    if (!s || !(widthFraction > 0)) return;
    scaleSlide(slot, widthFraction / s.width);
  }
  function setOpacity(v) {
    var t = activeSlot(); if (!t) return;
    var s = slides[t]; s.opacity = v; s.item.setOpacity(v);
  }

  // -------------------------------------- screenshot: each viewed region -> TIFF
  async function screenshot() {
    var present = loadedSlots();
    if (!present.length) { msg('no slide to capture'); return; }

    var outdir = null;
    if (hasApi('pick_dir')) {
      try { outdir = await window.pywebview.api.pick_dir(); } catch (e) { outdir = null; }
      if (!outdir) { status('export cancelled'); return; }
    }

    var b = viewer.viewport.getBounds(true);
    var vp = [
      new OpenSeadragon.Point(b.x, b.y),
      new OpenSeadragon.Point(b.x + b.width, b.y),
      new OpenSeadragon.Point(b.x + b.width, b.y + b.height),
      new OpenSeadragon.Point(b.x, b.y + b.height)
    ];
    var shots = present.map(function (slot) {
      var item = slides[slot].item;
      var corners = vp.map(function (p) {
        var ip = item.viewportToImageCoordinates(p);
        return { x: ip.x, y: ip.y };
      });
      return { slot: slot, name: slides[slot].name.replace(/\.vmic$/i, '') + '_region', corners: corners };
    });

    busy(true, 'Converting the viewed region to TIFF…\nReading from the source tiles (' +
               present.length + ' slide' + (present.length > 1 ? 's' : '') + ').');
    try {
      var res = await fetch('/api/screenshot', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shots: shots, outdir: outdir })
      });
      var out = await res.json();
      if (out.error) { msg('screenshot failed: ' + out.error); }
      else { msg('Saved TIFF:\n' + out.saved.join('\n')); status('region(s) saved'); }
    } catch (e) { msg('screenshot failed: ' + e); }
    finally { busy(false); }
  }

  // --------------------------------------------------- save rotated as VMIC
  async function saveRotated(slot) {
    var s = slides[slot];
    if (!s) { msg('no slide in slot ' + slot); return; }

    var outPath = null;
    if (hasApi('pick_save_vmic')) {
      try {
        outPath = await window.pywebview.api.pick_save_vmic(
          s.name.replace(/\.vmic$/i, '') + '_rotated.vmic');
      } catch (e) { outPath = null; }
      if (!outPath) { status('save cancelled'); return; }   // user cancelled the dialog
    }

    busy(true, 'Rendering slide ' + slot + ' rotated ' + s.angle + '° and re-tiling.\n' +
               'Re-builds the whole pyramid — large slides can take minutes.');
    status('saving rotated VMIC (slide ' + slot + ') …');
    try {
      var res = await fetch('/api/save_rotated', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slot: slot, angle: s.angle, outPath: outPath })
      });
      var out = await res.json();
      if (out.error) { msg('save failed: ' + out.error); status('error'); }
      else { msg('Saved new VMIC:\n' + out.saved); status('rotated VMIC saved'); }
    } catch (e) { msg('save failed: ' + e); }
    finally { busy(false); }
  }

  // -------------------------------------------------------------- wire UI
  $('openBtn').onclick = openSlide;

  $('magInput').addEventListener('change', applyMag);
  $('magInput').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { applyMag(); e.target.blur(); }
  });

  $('active').addEventListener('change', syncControls);
  $('removeBtn').onclick = removeActive;

  $('sizePct').addEventListener('change', function (e) {
    var t = activeSlot();
    if (t) setSizeAbsolute(t, (parseFloat(e.target.value) || 100) / 100);
  });
  $('rot').addEventListener('input', function (e) { setRot(e.target.value); });
  $('rotnum').addEventListener('change', function (e) { setRot(e.target.value); });
  $('op').addEventListener('input', function (e) { setOpacity(parseFloat(e.target.value)); });

  Array.prototype.forEach.call(document.querySelectorAll('[data-nudge]'), function (btn) {
    btn.onclick = function () {
      var d = 0.01, k = btn.getAttribute('data-nudge');
      if (k === 'x-') nudge(-d, 0);
      if (k === 'x+') nudge(d, 0);
      if (k === 'y-') nudge(0, -d);
      if (k === 'y+') nudge(0, d);
    };
  });
  Array.prototype.forEach.call(document.querySelectorAll('[data-scale]'), function (btn) {
    btn.onclick = function () {
      var t = activeSlot();
      if (!t) { msg('Pick a slide in the Active menu first.'); return; }
      scaleSlide(t, btn.getAttribute('data-scale') === '+' ? 1.05 : 1 / 1.05);
    };
  });

  $('shot').onclick = screenshot;

  rebuildSlotUI();
  syncControls();
})();
