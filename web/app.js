(function () {
  'use strict';
  var R0 = 0.000825, W0 = 0.001041, LAT0 = 46.64537, FLAECHE_KM2 = 0.0218;
  var COL = { stark: '#2e9e4f', mittel: '#e69a1e', schwach: '#d64545', grau: '#7a8793' };
  var $ = function (id) { return document.getElementById(id); };
  var daten = null, gaps = [], rausch = [], meta = {};
  var map, renderer, ebene = L.layerGroup();
  var gezeichnet = null, timer = null, tippZeit = 0, touch = window.matchMedia('(hover: none)').matches, tipp = L.tooltip({ className: 'tipp', direction: 'top', offset: [0, -6] });

  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
  function fmt(x, n) { return x == null ? '–' : (Math.round(x * 10) / 10).toString().replace('.', ','); }
  function stufe(best, sig) {
    if (!sig || best == null) return 'grau';
    return best >= -5 ? 'stark' : best >= -9 ? 'mittel' : 'schwach';
  }
  function rauschStufe(m) { return m <= -115 ? 'stark' : m <= -108 ? 'mittel' : 'schwach'; }
  var cosLat0 = Math.cos(LAT0 * Math.PI / 180);
  function hex(lat, lon, f) {
    var k = Math.cos(lat * Math.PI / 180) / cosLat0, r = R0 * k * f, w = W0 * f;
    return [[lat - r / 2, lon + w], [lat + r / 2, lon + w], [lat + r, lon], [lat + r / 2, lon - w], [lat - r / 2, lon - w], [lat - r, lon]];
  }
  // Zoomabhaengige Aggregation wie bei CoreScope: Je weiter herausgezoomt, desto groeber das Sechseckraster
  // (Faktor 1, 2, 4, ... auf die 150-m-Zellen); eine grobe Zelle fasst die Zellen darin zusammen.
  var MIN_PX = 14, SQ3 = Math.sqrt(3);
  function grobFaktor() {
    var px = 2 * W0 / 360 * 256 * Math.pow(2, map.getZoom());
    return Math.max(1, Math.pow(2, Math.ceil(Math.log(MIN_PX / px) / Math.LN2)));
  }
  function zellKey(lat, lon, m) {
    if (m === 1) return { key: lat + '_' + lon, lat: lat, lon: lon };
    var R = R0 * m, x = lon * cosLat0, y = lat;
    var q = (SQ3 / 3 * x - y / 3) / R, r = (2 / 3 * y) / R, cx = q, cz = r, cy = -q - r;
    var rx = Math.round(cx), ry = Math.round(cy), rz = Math.round(cz);
    var dx = Math.abs(rx - cx), dy = Math.abs(ry - cy), dz = Math.abs(rz - cz);
    if (dx > dy && dx > dz) rx = -ry - rz; else if (dy > dz) ry = -rx - rz; else rz = -rx - ry;
    return { key: rx + '_' + rz, lat: R * 1.5 * rz, lon: R * SQ3 * (rx + rz / 2) / cosLat0 };
  }
  function hexGrob(lat, lon, m) {
    var r = R0 * m, w = W0 * m;
    return [[lat - r / 2, lon + w], [lat + r / 2, lon + w], [lat + r, lon], [lat + r / 2, lon - w], [lat - r / 2, lon - w], [lat - r, lon]];
  }
  function gruppieren(liste, m, neu, zuf) {
    var map_ = {}, out = [];
    liste.forEach(function (it) {
      var k = zellKey(it.lat, it.lon, m), g = map_[k.key];
      if (!g) { g = map_[k.key] = neu(k); out.push(g); }
      zuf(g, it);
    });
    return out;
  }

  function zustand() {
    return {
      e: document.querySelector('input[name=ebene]:checked').value,
      l: $('luecken').checked ? 1 : 0,
      von: +$('von').value, bis: +$('bis').value,
      k: +$('knoten').value, t: +$('teiln').value,
      s: Array.prototype.filter.call(document.querySelectorAll('.stufe'), function (c) { return c.checked; }).map(function (c) { return c.value; }),
      minrep: Math.max(1, +$('minrep').value || 1), mincnt: Math.max(1, +$('mincnt').value || 1)
    };
  }

  function hashSchreiben() {
    var z = zustand(), p = new URLSearchParams();
    p.set('e', z.e); if (!z.l) p.set('l', '0');
    if (z.von > 0) p.set('von', daten.tage[z.von]);
    if (z.bis < daten.tage.length - 1) p.set('bis', daten.tage[z.bis]);
    if (z.k >= 0) p.set('k', daten.knoten[z.k]);
    if (z.t >= 0) p.set('t', daten.teilnehmer[z.t]);
    if (z.s.length !== 4) p.set('s', z.s.join(','));
    if (z.minrep > 1) p.set('rep', z.minrep); if (z.mincnt > 1) p.set('cnt', z.mincnt);
    var c = map.getCenter(); p.set('lat', c.lat.toFixed(4)); p.set('lon', c.lng.toFixed(4)); p.set('zoom', map.getZoom());
    history.replaceState(null, '', '#' + p.toString());
  }

  function hashLesen() {
    var p = new URLSearchParams(location.hash.replace(/^#/, ''));
    function idx(liste, wert) { var i = liste.indexOf(wert); return i; }
    if (p.get('e') === 'rausch') document.querySelector('input[name=ebene][value=rausch]').checked = true;
    if (p.get('l') === '0') $('luecken').checked = false;
    if (p.get('von')) { var i = idx(daten.tage, p.get('von')); if (i >= 0) $('von').value = i; }
    if (p.get('bis')) { var j = idx(daten.tage, p.get('bis')); if (j >= 0) $('bis').value = j; }
    if (p.get('k')) { var k = idx(daten.knoten, p.get('k')); if (k >= 0) $('knoten').value = k; }
    if (p.get('t')) { var t = idx(daten.teilnehmer, p.get('t')); if (t >= 0) $('teiln').value = t; }
    if (p.get('s') != null) { var s = p.get('s').split(','); document.querySelectorAll('.stufe').forEach(function (c) { c.checked = s.indexOf(c.value) >= 0; }); }
    if (p.get('rep')) $('minrep').value = p.get('rep'); if (p.get('cnt')) $('mincnt').value = p.get('cnt');
    return p.get('lat') && p.get('lon') ? [[+p.get('lat'), +p.get('lon')], +p.get('zoom') || 9] : null;
  }

  function popupSignal(c, z, eff) {
    var knoten = c[6].slice().sort(function (a, b) { return (b[1] == null ? -99 : b[1]) - (a[1] == null ? -99 : a[1]); });
    var h = '<div class="tk">' + knoten.length + (knoten.length === 1 ? ' Knoten hört hier' : ' Knoten hören hier') + '</div>';
    h += '<div class="tz">' + knoten.slice(0, 10).map(function (n) {
      return '<div><span>' + esc(daten.knoten[n[0]]) + '</span><span class="mut">' + (n[1] == null ? 'kein Signal' : fmt(n[1]) + ' dB') + ' · ×' + n[2] + '</span></div>';
    }).join('') + '</div>';
    if (knoten.length > 10) h += '<div class="mut kl">(' + (knoten.length - 10) + ' weitere)</div>';
    h += '<div class="mut kl">gesehen ' + esc(c[4]) + (c[4] !== c[5] ? ' bis ' + esc(c[5]) : '') + ' · ' + c[7].length + (c[7].length === 1 ? ' Tag' : ' Tage') + '</div>';
    if (c[8].length) h += '<div class="mut kl">gemessen von ' + c[8].map(function (i) { return esc(daten.teilnehmer[i]); }).join(', ') + '</div>';
    return h;
  }

  function zeichnen() {
    var z = zustand();
    ebene.clearLayers();
    var stat = { stark: 0, mittel: 0, schwach: 0, grau: 0, luecken: 0 }, n = 0;
    var tageVon = daten.tage[z.von], tageBis = daten.tage[z.bis];
    var zeitAktiv = z.von > 0 || z.bis < daten.tage.length - 1;
    var m = grobFaktor(), sigL = [], gapL = [], noiseL = [];

    function polygon(lat, lon, farbe, opts, html, kurz) {
      var st = Object.assign({ renderer: renderer, color: farbe, weight: 0.8, fillColor: farbe, fillOpacity: 0.55 }, opts || {});
      var p = L.polygon(m === 1 ? hex(lat, lon, 1) : hexGrob(lat, lon, m), st);
      p.on('click', function (e) { tippZeit = Date.now(); tipp.setContent(html()).setLatLng(e.latlng).openOn(map); });
      if (!touch) {
        p.on('mouseover', function (e) {
          e.target.setStyle({ weight: 2, fillOpacity: Math.min(0.9, (st.fillOpacity || 0.55) + 0.3) });
          tipp.setContent(html()).setLatLng(e.latlng).openOn(map);
        });
        p.on('mousemove', function (e) { tipp.setLatLng(e.latlng); });
        p.on('mouseout', function (e) { e.target.setStyle({ weight: st.weight, fillOpacity: st.fillOpacity }); map.closeTooltip(tipp); });
      }
      p.addTo(ebene); n++;
    }

    if (z.e === 'signal') {
      daten.zellen.forEach(function (c) {
        var best = c[2], cnt = c[3], tage = c[7], sig = c[9];
        if (z.t >= 0 && c[8].indexOf(z.t) < 0) return;
        if (z.k >= 0) {
          var hit = c[6].filter(function (x) { return x[0] === z.k; })[0];
          if (!hit) return;
          best = hit[1]; cnt = hit[2]; sig = hit[1] != null;
        }
        if (zeitAktiv) {
          var im = tage.filter(function (d) { return d[0] >= z.von && d[0] <= z.bis; });
          if (!im.length) return;
          if (z.k < 0) {
            best = null; cnt = 0;
            im.forEach(function (d) { if (d[2] != null && (best == null || d[2] > best)) best = d[2]; if (d[1] > cnt) cnt = d[1]; });
          }
        }
        if (cnt < z.mincnt || c[6].length < z.minrep) return;
        var s = stufe(best, sig);
        if (z.s.indexOf(s) < 0) return;
        stat[s]++;
        sigL.push({ lat: c[0], lon: c[1], best: best, cnt: cnt, sig: sig, c: c, s: s });
      });
      if (z.l && z.k < 0 && z.t < 0) {
        gaps.forEach(function (g) {
          if (zeitAktiv && (g[4] < tageVon || g[4] > tageBis)) return;
          stat.luecken++;
          gapL.push({ lat: g[0], lon: g[1], n: g[2], tag: g[4] });
        });
      }
    } else {
      rausch.forEach(function (r) {
        if (zeitAktiv && (r[6] < tageVon || r[6] > tageBis)) return;
        var s = rauschStufe(r[2]);
        if (z.s.indexOf(s) < 0) return;
        stat[s]++;
        noiseL.push({ lat: r[0], lon: r[1], med: r[2], lo: r[3], hi: r[4], n: r[5] });
      });
    }
    renderGrob(z, m, sigL, gapL, noiseL, polygon);
    n = ebene.getLayers().length;
    statistik(z, stat, n);
    kopfSync(z); legende(z);
    $('zaehler').textContent = n.toLocaleString('de-AT') + ' Zellen sichtbar' + (m > 1 ? ' (zusammengefasst, ca. ' + Math.round(150 * m) + ' m)' : '');
    hashSchreiben();
  }

  var DECKKRAFT = { stark: 0.6, mittel: 0.48, schwach: 0.34, grau: 0.22 };
  function renderGrob(z, m, sigL, gapL, noiseL, polygon) {
    var b = map.getBounds().pad(0.6);
    gezeichnet = { m: m, b: b };
    function sichtbar(g) { return b.contains([g.lat, g.lon]); }
    if (sigL.length || z.e === 'signal') {
      var sigKeys = {};
      gruppieren(sigL, m, function (k) {
        return { key: k.key, lat: k.lat, lon: k.lon, best: null, cnt: 0, sig: false, nodes: {}, days: {}, teiln: {}, first: null, last: null, zellen: 0 };
      }, function (g, it) {
        g.zellen++; g.cnt += it.cnt; g.sig = g.sig || !!it.sig;
        if (it.best != null && (g.best == null || it.best > g.best)) g.best = it.best;
        it.c[6].forEach(function (n) { var o = g.nodes[n[0]]; if (!o) g.nodes[n[0]] = [n[0], n[1], n[2]]; else { if (n[1] != null && (o[1] == null || n[1] > o[1])) o[1] = n[1]; o[2] += n[2]; } });
        it.c[7].forEach(function (d) { g.days[d[0]] = 1; }); it.c[8].forEach(function (t) { g.teiln[t] = 1; });
        if (g.first == null || it.c[4] < g.first) g.first = it.c[4];
        if (g.last == null || it.c[5] > g.last) g.last = it.c[5];
      }).forEach(function (g) {
        sigKeys[g.key] = 1;
        if (!sichtbar(g)) return;
        var st = stufe(g.best, g.sig), nodes = Object.keys(g.nodes).map(function (k) { return g.nodes[k]; });
        var c = [g.lat, g.lon, g.best, g.cnt, g.first, g.last, nodes, Object.keys(g.days).map(function (d) { return [+d]; }), Object.keys(g.teiln).map(Number), g.sig];
        polygon(g.lat, g.lon, COL[st], { fillOpacity: DECKKRAFT[st] }, function () {
          return popupSignal(c, z, { best: g.best, cnt: g.cnt }) + (g.zellen > 1 ? '<div class="mut kl">' + g.zellen + ' Zellen zusammengefasst, näher heranzoomen</div>' : '');
        }, function () { return '<b>' + fmt(g.best) + ' dB</b> · ' + g.cnt + (g.cnt === 1 ? ' Empfang' : ' Empfänge') + ' · ' + nodes.length + (nodes.length === 1 ? ' Knoten' : ' Knoten'); });
      });
      gruppieren(gapL, m, function (k) { return { key: k.key, lat: k.lat, lon: k.lon, n: 0, tag: '' }; },
        function (g, it) { g.n += it.n; if (it.tag > g.tag) g.tag = it.tag; }).forEach(function (g) {
        if (sigKeys[g.key] || !sichtbar(g)) return;
        polygon(g.lat, g.lon, '#5b6670', { fillOpacity: g.n >= 4 ? 0.5 : g.n >= 2 ? 0.36 : 0.24, weight: 1, dashArray: '3 3', opacity: 0.9 }, function () {
          return '<b>Befahren, nichts gehört</b><br>' + g.n + (g.n === 1 ? ' Messpunkt' : ' Messpunkte') +
            '<br><span class="hint">zuletzt ' + esc(g.tag) + ' · kein Beweis für fehlenden Empfang</span>';
        }, function () { return 'Befahren, nichts gehört · ' + g.n + ' Messpunkte'; });
      });
    }
    if (noiseL.length) {
      gruppieren(noiseL, m, function (k) { return { lat: k.lat, lon: k.lon, meds: [], lo: 99, hi: -999, n: 0 }; },
        function (g, it) { g.meds.push(it.med); g.lo = Math.min(g.lo, it.lo); g.hi = Math.max(g.hi, it.hi); g.n += it.n; }).forEach(function (g) {
        if (!sichtbar(g)) return;
        g.meds.sort(function (a, c) { return a - c; });
        var med = g.meds[Math.floor(g.meds.length / 2)], st = rauschStufe(med);
        polygon(g.lat, g.lon, COL[st], { fillOpacity: DECKKRAFT[st] }, function () {
          return '<b>Rauschen ' + med + ' dBm</b> (Median)<br>leiseste ' + g.lo + ' · lauteste ' + g.hi + ' dBm<br>' + g.n + ' Messpunkte';
        }, function () { return '<b>' + med + ' dBm</b> Rauschen (Median) · ' + g.n + ' Messpunkte'; });
      });
    }
  }

  function kopfSync(z) {
    document.querySelectorAll('#ebenen button').forEach(function (b) { b.classList.toggle('aktiv', b.dataset.e === z.e); });
    var n = daten.tage.length, von = z.von, aktiv = '0';
    if (z.bis === n - 1) {
      [7, 30, 90].forEach(function (t) { if (von === Math.max(0, n - t)) aktiv = String(t); });
      if (von === 0) aktiv = '0';
    } else aktiv = '';
    document.querySelectorAll('#schnell button').forEach(function (b) { b.classList.toggle('aktiv', b.dataset.tage === aktiv); });
  }

  function legende(z) {
    var t = z.e === 'signal'
      ? [['stark', 'stark ab −5 dB'], ['mittel', 'mittel −9 bis −5 dB'], ['schwach', 'schwach unter −9 dB'], ['grau', 'ohne SNR'], ['luecke', 'befahren, nichts gehört']]
      : [['stark', 'ruhig bis −115 dBm'], ['mittel', 'mittel bis −108 dBm'], ['schwach', 'laut über −108 dBm']];
    $('legende').innerHTML = t.map(function (x) { return '<div><i class="sw ' + x[0] + '"></i>' + x[1] + '</div>'; }).join('');
  }

  function statistik(z, s, n) {
    var tier = z.e === 'signal'
      ? [['stark', 'stark'], ['mittel', 'mittel'], ['schwach', 'schwach'], ['grau', 'ohne SNR']]
      : [['stark', 'ruhig'], ['mittel', 'mittel'], ['schwach', 'laut']];
    var sum = s.stark + s.mittel + s.schwach + s.grau;
    var h = '<b>' + sum.toLocaleString('de-AT') + '</b> Zellen · ' + (sum * FLAECHE_KM2).toLocaleString('de-AT', { maximumFractionDigits: 1 }) + ' km²';
    h += '<table>' + tier.map(function (t) {
      return '<tr><td><i class="sw ' + t[0] + '"></i>' + t[1] + '</td><td>' + s[t[0]] + (sum ? ' (' + Math.round(100 * s[t[0]] / sum) + ' %)' : '') + '</td></tr>';
    }).join('');
    if (z.e === 'signal' && z.l && z.k < 0 && z.t < 0) h += '<tr><td>befahren, nichts gehört</td><td>' + s.luecken + '</td></tr>';
    $('stat').innerHTML = h + '</table>';
  }

  function auswahlFuellen(el, liste, alle) {
    el.innerHTML = '';
    var o = document.createElement('option'); o.value = -1; o.textContent = alle; el.appendChild(o);
    liste.map(function (n, i) { return [n, i]; }).sort(function (a, b) { return String(a[0]).localeCompare(String(b[0]), 'de'); })
      .forEach(function (p) { var op = document.createElement('option'); op.value = p[1]; op.textContent = p[0]; el.appendChild(op); });
  }

  function metaAnzeigen() {
    var alter = meta.letzter_lauf ? (Date.now() - Date.parse(meta.letzter_lauf)) / 3600000 : null;
    var t = 'Archiv seit ' + (meta.archiv_seit || '–') + ', ' + meta.laeufe + ' Läufe. Letzter Lauf: ' +
      (meta.letzter_lauf ? new Date(meta.letzter_lauf).toLocaleString('de-AT') : '–') + '.';
    if (alter != null && alter > 3) t += ' ⚠ Die Daten sind älter als ' + Math.floor(alter) + ' Stunden, der Sammler läuft möglicherweise nicht.';
    if (!meta.letzter_lauf_ok) t += ' ⚠ Der letzte Lauf meldete einen Fehler.';
    if (meta.vor_start_tag) t += ' Alles bis ' + meta.vor_start_tag + ' stammt aus dem 30-Tage-Fenster beim Start.';
    $('meta').textContent = t;
  }

  function laden(url) { return fetch(url, { cache: 'no-cache' }).then(function (r) { if (!r.ok) throw new Error(url + ' ' + r.status); return r.json(); }); }

  function start() {
    Promise.all([laden('data/cells.json'), laden('data/gaps.json'), laden('data/noise.json'), laden('data/meta.json')]).then(function (a) {
      daten = a[0]; gaps = a[1]; rausch = a[2]; meta = a[3];
      var tage = daten.tage;
      ['von', 'bis'].forEach(function (id, k) {
        var el = $(id); el.innerHTML = '';
        tage.forEach(function (d, i) { var o = document.createElement('option'); o.value = i; o.textContent = d.split('-').reverse().join('.'); el.appendChild(o); });
        el.value = k === 0 ? 0 : tage.length - 1;
      });
      auswahlFuellen($('knoten'), daten.knoten, 'alle Knoten');
      auswahlFuellen($('teiln'), daten.teilnehmer, 'alle Teilnehmer');
      var ansicht = hashLesen();
      map = L.map('map', { preferCanvas: true, tap: false, clickTolerance: touch ? 14 : 3 }).setView(ansicht ? ansicht[0] : [46.8, 14.0], ansicht ? ansicht[1] : 9);
      map.attributionControl.setPrefix('<a href="https://kaernten-funkt.at/impressum/" target="_blank" rel="noopener">Impressum</a> · <a href="https://kaernten-funkt.at/datenschutz/" target="_blank" rel="noopener">Datenschutz</a> · <a href="https://leafletjs.com" target="_blank" rel="noopener">Leaflet</a>');
      var hell = L.tileLayer('tiles/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '© OpenStreetMap-Mitwirkende' });
      var istDunkel = true;
      try { istDunkel = localStorage.getItem('rx-karte') !== 'hell'; } catch (e) {}
      function thema(d) {
        istDunkel = d; if (d) { map.removeLayer(hell); dunkel.addTo(map); } else { map.removeLayer(dunkel); hell.addTo(map); }
        $('thema').textContent = d ? 'Dunkel' : 'Hell'; $('thema').setAttribute('aria-pressed', d);
        document.body.classList.toggle('dunkel', d);
        try { localStorage.setItem('rx-karte', d ? 'dunkel' : 'hell'); } catch (e) {}
      }
      var dunkel = L.tileLayer('tiles-dark/{z}/{x}/{y}.png?v=2', { maxZoom: 18, attribution: '© OpenStreetMap-Mitwirkende © CARTO' });
      thema(istDunkel);
      $('thema').addEventListener('click', function () { thema(!istDunkel); });
      renderer = L.canvas({ padding: 0.5, tolerance: touch ? 6 : 0 });
      ebene.addTo(map);
      map.on('moveend', function () {
        hashSchreiben();
        if (gezeichnet && gezeichnet.m === grobFaktor() && gezeichnet.b.contains(map.getBounds())) return;
        clearTimeout(timer); timer = setTimeout(zeichnen, 150);
      });
      document.querySelectorAll('#panel input, #panel select').forEach(function (el) {
        el.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(zeichnen, 120); });
      });
      document.querySelectorAll('input[name=ebene]').forEach(function (el) {
        el.addEventListener('change', function () {
          if (!el.checked) return;
          var r = el.value === 'rausch' && el.checked;
          $('f-signal').hidden = r; $('f-rausch').hidden = !r; $('luecken-zeile').hidden = r;
          $('f-signal').querySelectorAll('.zeile').forEach(function (z) { z.hidden = r; });
        });
      });
      function ebeneSetzen(e) {
        var r = document.querySelector('input[name=ebene][value=' + e + ']'); r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true }));
        clearTimeout(timer); timer = setTimeout(zeichnen, 0);
      }
      document.querySelectorAll('#ebenen button').forEach(function (b) { b.addEventListener('click', function () { ebeneSetzen(b.dataset.e); }); });
      document.querySelectorAll('#schnell button').forEach(function (b) {
        b.addEventListener('click', function () {
          var t = +b.dataset.tage, n = daten.tage.length;
          $('von').value = t ? Math.max(0, n - t) : 0; $('bis').value = n - 1;
          clearTimeout(timer); timer = setTimeout(zeichnen, 0);
        });
      });
      function menue(auf) { document.body.classList.toggle('offen', auf); $('menue').setAttribute('aria-expanded', auf); }
      $('menue').addEventListener('click', function () { menue(!document.body.classList.contains('offen')); });
      $('griff').addEventListener('click', function () { menue(false); });
      map.on('click', function () { menue(false); if (Date.now() - tippZeit > 80) map.closeTooltip(tipp); });
      $('teilen').addEventListener('click', function () {
        var b = $('teilen'); (navigator.clipboard ? navigator.clipboard.writeText(location.href) : Promise.reject()).then(
          function () { b.textContent = 'Link kopiert'; }, function () { b.textContent = 'Link steht in der Adresszeile'; });
        setTimeout(function () { b.textContent = 'Link zu dieser Ansicht kopieren'; }, 2500);
      });
      document.querySelector('input[name=ebene]:checked').dispatchEvent(new Event('change'));
      metaAnzeigen(); zeichnen();
    }).catch(function (e) { $('stat').textContent = 'Daten konnten nicht geladen werden: ' + e.message; });
  }
  start();
})();
