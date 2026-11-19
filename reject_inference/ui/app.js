(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var C = { good: '#34d399', goodbad: '#0f7a55', well: '#4f9dff', poor: '#ff5c5c', grey: '#5b6472', hi: '#f5c542' };
  var RULE_COL = { R1: '#b07cff', R2: '#ff5c5c', R3: '#ff9f43', R4: '#f5c542', R5: '#4fd1c5', OV: '#34d399', '': '#5b6472' };
  var S = { P: null, n: 0, vis: { BK: true, ANB: true, DEC: true, NOBUR: true }, color: 'obs', tool: 'pick',
    zoom: 1, panx: 0, pany: 0, sel: -1, twins: null, members: null, lasso: null, poly: null,
    rule: null, rules: [], frontierPts: [], data: null };

  // ───────── helpers ─────────
  function pct(v, d) { return v == null ? '–' : (v * 100).toFixed(d == null ? 1 : d) + '%'; }
  function num(v) { return v == null ? '–' : Math.round(v).toLocaleString('en-US'); }
  function money(v) { return v == null ? '–' : (v < 0 ? '-$' : '$') + Math.abs(Math.round(v)).toLocaleString('en-US'); }
  function val(v) { if (v == null) return '–'; return Math.abs(v - Math.round(v)) < 1e-9 ? String(Math.round(v)) : Number(v).toFixed(1); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function econ() { return { margin: +$('rx-margin').value || 0, loss: +$('rx-loss').value || 1 }; }
  function be() { var e = econ(); return e.margin / (e.margin + e.loss); }
  function cls(adj) { return adj == null ? 'm' : (adj <= be() ? 'g' : 'b'); }
  function toast(msg, ok) {
    var t = $('rx-toast'); t.textContent = msg; t.className = 'rx-toast' + (ok ? ' ok' : ''); t.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(function () { t.hidden = true; }, ok ? 5000 : 9000);
  }
  function post(path, body) {
    var b = Object.assign({}, econ(), body || {});
    return fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
      .then(function (r) { return r.json(); })
      .then(function (j) { if (!j.ok) { console.error(j.trace); throw new Error(j.error || 'Backend error'); } return j; });
  }
  function busy(btn, on) { if (btn) { btn.disabled = on; btn.dataset.t = btn.dataset.t || btn.textContent; btn.textContent = on ? 'Working…' : btn.dataset.t; } }

  // ───────── map ─────────
  var cv = $('rx-canvas'), ctx = cv.getContext('2d'), W = 0, H = 0, base = { k: 1, cx: 0, cy: 0 };
  function fit() {
    var r = cv.parentNode.getBoundingClientRect(), d = window.devicePixelRatio || 1;
    W = r.width; H = r.height; cv.width = W * d; cv.height = H * d; ctx.setTransform(d, 0, 0, d, 0, 0);
    if (S.P) {
      var x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (var i = 0; i < S.n; i++) { x0 = Math.min(x0, S.P.x[i]); x1 = Math.max(x1, S.P.x[i]); y0 = Math.min(y0, S.P.y[i]); y1 = Math.max(y1, S.P.y[i]); }
      base.k = Math.min((W - 60) / (x1 - x0 || 1), (H - 70) / (y1 - y0 || 1)); base.cx = (x0 + x1) / 2; base.cy = (y0 + y1) / 2;
    }
    draw();
  }
  function sx(i) { return (S.P.x[i] - base.cx) * base.k * S.zoom + W / 2 + S.panx; }
  function sy(i) { return (S.P.y[i] - base.cy) * base.k * S.zoom + H / 2 + S.pany + 8; }
  function known(i) { return S.P.bad[i] != null; }
  function shown(i) {
    var s = S.P.seg[i];
    if (!S.vis[s]) return false;
    if (s !== 'BK' && !known(i) && !S.vis.NOBUR) return false;
    return true;
  }
  function ramp(p) {           // blue (low risk) -> red (high risk)
    var t = Math.max(0, Math.min(1, p / 0.45));
    return 'rgb(' + Math.round(79 + 176 * t) + ',' + Math.round(157 - 65 * t) + ',' + Math.round(255 - 163 * t) + ')';
  }
  function colour(i) {
    var P = S.P, s = P.seg[i], m = S.color;
    if (m === 'kgb') return ramp(P.p_kgb ? P.p_kgb[i] : 0);
    if (m === 'rule') return s === 'DEC' ? (RULE_COL[P.rule[i]] || C.grey) : (s === 'BK' ? C.good : C.grey);
    if (s === 'BK') return P.bad[i] === 1 ? C.goodbad : C.good;
    if (m === 'hc' && P.bad_hc) return P.bad_hc[i] >= 0.5 ? C.poor : C.well;
    if (m === 'pcl' && P.bad_pcl) return P.bad_pcl[i] >= 0.5 ? C.poor : C.well;
    if (m === 'fz' && P.bad_fz) return ramp(P.bad_fz[i]);
    return P.bad[i] == null ? C.grey : (P.bad[i] === 1 ? C.poor : C.well);
  }
  function shape(x, y, s, r, small) {
    ctx.beginPath();
    if (small) ctx.arc(x, y, 1.4, 0, 6.2832);
    else if (s === 'BK') ctx.arc(x, y, r, 0, 6.2832);
    else if (s === 'ANB') { ctx.moveTo(x, y - r * 1.35); ctx.lineTo(x + r * 1.35, y); ctx.lineTo(x, y + r * 1.35); ctx.lineTo(x - r * 1.35, y); ctx.closePath(); }
    else { ctx.moveTo(x, y - r * 1.3); ctx.lineTo(x + r * 1.25, y + r); ctx.lineTo(x - r * 1.25, y + r); ctx.closePath(); }
  }
  function draw() {
    ctx.clearRect(0, 0, W, H);
    if (!S.P) return;
    var P = S.P, mem = S.members, r = Math.max(2.4, Math.min(4.5, 2.6 * Math.sqrt(S.zoom))), i, pass;
    var inferred = (S.color === 'hc' || S.color === 'pcl' || S.color === 'fz' || S.color === 'kgb' || S.color === 'rule');
    for (pass = 0; pass < 3; pass++) {
      for (i = 0; i < S.n; i++) {
        if (!shown(i)) continue;
        var s = P.seg[i], small = s !== 'BK' && !known(i) && !inferred;
        var layer = small ? 0 : (s === 'BK' ? 1 : 2);
        if (layer !== pass) continue;
        var x = sx(i), y = sy(i);
        if (x < -8 || y < -8 || x > W + 8 || y > H + 8) continue;
        ctx.globalAlpha = mem ? (mem[i] ? 1 : 0.12) : (s === 'BK' ? 0.55 : 0.9);
        ctx.fillStyle = colour(i);
        var isMem = mem && mem[i];
        shape(x, y, s, isMem ? r * 1.25 : r, small && !isMem); ctx.fill();
        if (isMem) { ctx.strokeStyle = C.hi; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(x, y, r * 1.25 + 3.5, 0, 6.2832); ctx.stroke(); }
      }
    }
    ctx.globalAlpha = 1;
    if (S.twins && S.sel >= 0) {
      ctx.strokeStyle = 'rgba(245,197,66,.75)'; ctx.lineWidth = 1;
      S.twins.forEach(function (t) {
        if (t < 0) return;
        ctx.beginPath(); ctx.moveTo(sx(S.sel), sy(S.sel)); ctx.lineTo(sx(t), sy(t)); ctx.stroke();
        ctx.beginPath(); ctx.arc(sx(t), sy(t), r + 3, 0, 6.2832); ctx.stroke();
      });
    }
    if (S.sel >= 0) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(sx(S.sel), sy(S.sel), r + 4, 0, 6.2832); ctx.stroke(); }
    if (S.poly && S.poly.length > 1) {
      ctx.strokeStyle = C.hi; ctx.fillStyle = 'rgba(245,197,66,.08)'; ctx.lineWidth = 1.5; ctx.beginPath();
      S.poly.forEach(function (p, j) { if (j) ctx.lineTo(p[0], p[1]); else ctx.moveTo(p[0], p[1]); });
      ctx.closePath(); ctx.fill(); ctx.stroke();
    }
  }
  function hit(mx, my) {
    var bestI = -1, bestD = 64;
    for (var i = 0; i < S.n; i++) {
      if (!shown(i)) continue;
      var dx = sx(i) - mx, dy = sy(i) - my, d = dx * dx + dy * dy;
      if (d < bestD) { bestD = d; bestI = i; }
    }
    return bestI;
  }
  function segName(s) { return s === 'BK' ? 'Booked' : (s === 'ANB' ? 'Approved, not booked' : 'Declined'); }
  function outcome(s, bad) {
    if (bad == null) return '<span class="m">no bureau trade</span>';
    if (s === 'BK') return bad === 1 ? '<span class="b">bad with us</span>' : '<span class="g">good with us</span>';
    return bad === 1 ? '<span class="b">bad elsewhere</span>' : '<span class="w">good elsewhere</span>';
  }
  var drag = null;
  cv.addEventListener('mousedown', function (e) {
    var r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    if (S.tool === 'lasso') { S.poly = [[x, y]]; drag = { lasso: true }; }
    else drag = { x: x, y: y, px: S.panx, py: S.pany, moved: false };
  });
  window.addEventListener('mousemove', function (e) {
    var r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, tip = $('rx-tip');
    if (drag && drag.lasso) { S.poly.push([x, y]); draw(); return; }
    if (drag) {
      if (Math.abs(x - drag.x) + Math.abs(y - drag.y) > 4) drag.moved = true;
      if (drag.moved) { S.panx = drag.px + x - drag.x; S.pany = drag.py + y - drag.y; draw(); }
      return;
    }
    if (!S.P || x < 0 || y < 0 || x > W || y > H) { tip.style.display = 'none'; return; }
    var i = hit(x, y);
    if (i < 0) { tip.style.display = 'none'; return; }
    var P = S.P;
    tip.innerHTML = '<b>' + segName(P.seg[i]) + '</b> · ' + outcome(P.seg[i], P.bad[i]) +
      (P.rule[i] ? '<br>Declined by <b>' + esc(P.rule[i]) + '</b>' : '') +
      '<br>Bureau score ' + val(P.bureau_score[i]) + ' · DTI ' + val(P.dti_pct[i]) + '%' +
      (P.p_kgb ? '<br>KGB p(bad) ' + pct(P.p_kgb[i]) : '');
    tip.style.display = 'block';
    tip.style.left = Math.min(x + 14, W - 250) + 'px'; tip.style.top = Math.min(y + 14, H - 80) + 'px';
  });
  window.addEventListener('mouseup', function (e) {
    if (!drag) return;
    var d = drag; drag = null;
    var r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    if (d.lasso) { finishLasso(); return; }
    if (!d.moved) { var i = hit(x, y); if (i >= 0) pick(i); }
  });
  cv.addEventListener('wheel', function (e) {
    e.preventDefault();
    var r = cv.getBoundingClientRect(), x = e.clientX - r.left - W / 2, y = e.clientY - r.top - H / 2 - 8;
    var f = e.deltaY < 0 ? 1.15 : 1 / 1.15, z = Math.max(0.6, Math.min(14, S.zoom * f)); f = z / S.zoom;
    S.panx = x - (x - S.panx) * f; S.pany = y - (y - S.pany) * f; S.zoom = z; draw();
  }, { passive: false });
  function inPoly(x, y, poly) {
    var c = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      var a = poly[i], b = poly[j];
      if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) c = !c;
    }
    return c;
  }
  function finishLasso() {
    var ids = [];
    if (S.poly && S.poly.length > 3) for (var i = 0; i < S.n; i++) if (shown(i) && inPoly(sx(i), sy(i), S.poly)) ids.push(i);
    S.lasso = ids.length ? ids : null;
    $('rx-lasso-go').disabled = !S.lasso;
    $('rx-toolhint').textContent = S.lasso ? ids.length + ' points selected. Press "Lasso → rule" in the Rules tab.' : 'Draw a closed shape around a cluster.';
    draw();
    if (S.lasso) { tab('rules'); runLasso(); }
  }

  // ───────── legend ─────────
  function sw(s, col, small) {
    var p = small ? '<circle cx="8" cy="8" r="2" fill="' + col + '"/>' :
      s === 'BK' ? '<circle cx="8" cy="8" r="4.5" fill="' + col + '"/>' :
      s === 'ANB' ? '<path d="M8 2 L14 8 L8 14 L2 8 Z" fill="' + col + '"/>' : '<path d="M8 2.5 L14 13 L2 13 Z" fill="' + col + '"/>';
    return '<svg width="16" height="16">' + p + '</svg>';
  }
  function legend() {
    var m = S.color, h = '';
    function row(s, col, t, small) { h += '<div>' + sw(s, col, small) + esc(t) + '</div>'; }
    if (m === 'kgb') { row('BK', ramp(0.02), 'Low p(bad)'); row('BK', ramp(0.22), 'Medium'); row('BK', ramp(0.45), 'High p(bad)'); }
    else if (m === 'rule') {
      row('BK', C.good, 'Booked'); row('DEC', RULE_COL.R1, 'R1 bankruptcy'); row('DEC', RULE_COL.R2, 'R2 Bureau score < 660');
      row('DEC', RULE_COL.R3, 'R3 DTI > 45'); row('DEC', RULE_COL.R4, 'R4 delinquencies ≥ 2'); row('DEC', RULE_COL.R5, 'R5 inquiries ≥ 6');
    } else {
      row('BK', C.good, 'Booked, good'); row('BK', C.goodbad, 'Booked, bad');
      var a = m === 'obs' ? 'did well elsewhere' : 'inferred good', b = m === 'obs' ? 'went bad elsewhere' : 'inferred bad';
      row('ANB', C.well, 'Approved not booked, ' + a); row('ANB', C.poor, 'Approved not booked, ' + b);
      row('DEC', C.well, 'Declined, ' + a); row('DEC', C.poor, 'Declined, ' + b);
      if (m === 'obs') row('DEC', C.grey, 'Not booked, no bureau trade', true);
    }
    h += '<div><svg width="16" height="16"><circle cx="8" cy="8" r="5" fill="none" stroke="' + C.hi + '" stroke-width="1.5"/></svg>In the active rule / twin</div>';
    $('rx-legend').innerHTML = h;
  }

  // ───────── tabs ─────────
  function tab(name) {
    document.querySelectorAll('.rx-tab').forEach(function (b) { b.classList.toggle('rx-on', b.dataset.tab === name); });
    ['overview', 'twins', 'rules', 'frontier', 'methods'].forEach(function (t) { $('rx-pane-' + t).hidden = t !== name; });
    if (name === 'frontier') renderFrontier();
  }
  document.querySelectorAll('.rx-tab').forEach(function (b) { b.onclick = function () { tab(b.dataset.tab); }; });

  // ───────── overview ─────────
  function renderOverview(o) {
    var h = '<div class="rx-kpis">' +
      '<div class="rx-kpi"><span>Applications</span><b>' + num(o.N) + '</b></div>' +
      '<div class="rx-kpi"><span>Champion approval</span><b>' + pct(o.champion.approval) + '</b></div>' +
      '<div class="rx-kpi"><span>Champion bad rate</span><b>' + pct(o.champion.bad) + '</b></div>' +
      '<div class="rx-kpi"><span>Break-even bad rate</span><b class="h">' + pct(o.breakeven) + '</b></div>' +
      '<div class="rx-kpi"><span>Off-us → on-us factor</span><b>' + o.cal.toFixed(2) + '×</b></div>' +
      '<div class="rx-kpi"><span>Take-up of approvals</span><b>' + pct(o.take_up, 0) + '</b></div></div>';
    h += '<div class="rx-sub">Populations</div><table><tr><th>Population</th><th>Applicants</th><th>With outcome</th><th>Bad rate</th></tr>';
    o.segments.forEach(function (s) {
      h += '<tr><td>' + esc(s.label) + '</td><td>' + num(s.n) + '</td><td>' + num(s.seg === 'BK' ? s.n : s.n_bur) + '</td><td>' + pct(s.bad) +
        (s.seg === 'BK' ? ' <span class="m">internal</span>' : ' <span class="m">bureau</span>') + '</td></tr>';
    });
    h += '</table><div class="rx-sub">What each decline rule is costing</div>' +
      '<table><tr><th>Rule that declined</th><th>Declined</th><th>Bureau bad</th><th>On-us equiv.</th><th>If approved</th></tr>';
    o.rules.forEach(function (r) {
      h += '<tr><td>' + esc(r.rule + ' ' + r.label) + '</td><td>' + num(r.n) + '</td><td>' + pct(r.bad_bur) + '</td><td class="' + cls(r.bad_adj) + '">' +
        pct(r.bad_adj) + '</td><td class="' + (r.profit > 0 ? 'g' : 'b') + '">' + money(r.profit) + '</td></tr>';
    });
    h += '</table><p class="rx-note">Bureau bad rate is measured on declined applicants who opened a trade elsewhere. "On-us equivalent" multiplies it by the off-us → on-us factor, ' +
      'which comes from approved-not-booked applicants: they passed the same policy as booked customers, so the gap between the two is the off-us effect. ' +
      'Green means the group as a whole clears break-even; the Rules tab finds the profitable part of the red groups.</p>';
    $('rx-pane-overview').innerHTML = h;
    $('rx-be').textContent = pct(o.breakeven);
  }

  // ───────── twins ─────────
  function pick(i) {
    S.sel = i; S.twins = null; draw(); tab('twins');
    $('rx-pane-twins').innerHTML = '<div class="rx-empty">Finding twins…</div>';
    post('/api/twins', { row: S.P.row[i], k: 10 }).then(function (t) {
      S.twins = t.twins.map(function (x) { return x.map_pos; }); draw(); renderTwins(t);
    }).catch(function (e) { toast(e.message); });
  }
  function renderTwins(t) {
    var me = t.me, isBk = me.seg === 'BK';
    var h = '<div class="rx-me"><b>' + esc(me.app_id) + '</b> · ' + segName(me.seg) + ' · ' + outcome(me.seg, me.bad) +
      (me.decline_rule ? '<br>Declined by <b>' + esc(me.decline_rule) + '</b>' : '') +
      '<br><span class="m">Bureau score ' + val(me.values.bureau_score) + ' · DTI ' + val(me.values.dti_pct) + '% · utilization ' + val(me.values.util_pct) +
      '% · KGB p(bad) ' + pct(me.p_kgb) + '</span></div>';
    var tot = t.n_known || 0;
    h += '<div class="rx-sub">' + (isBk ? '10 closest not-booked applicants (with bureau performance)' : '10 closest booked customers') + '</div>';
    if (tot) {
      h += '<div><b class="' + (isBk ? 'w' : 'g') + '">' + t.n_good + ' of ' + tot + '</b> twins ' + (isBk ? 'did well at another lender' : 'performed well with us') +
        '</div><div class="rx-bar"><i style="width:' + (100 * t.n_good / tot) + '%"></i></div>';
    }
    var rk = Object.keys(t.rules || {});
    if (rk.length) h += '<p class="rx-note">Rules that kept these twins out: ' + rk.map(function (k) { return '<b>' + esc(k) + '</b> ×' + t.rules[k]; }).join(', ') + '</p>';
    h += '<div class="rx-sub">Where the twins differ most</div><table><tr><th>Attribute</th><th>This applicant</th><th>Twins (avg)</th><th>Gap (σ)</th></tr>';
    t.diffs.forEach(function (d) {
      h += '<tr><td>' + esc(d.label) + '</td><td>' + val(d.me) + '</td><td>' + val(d.twins) + '</td><td class="' + (Math.abs(d.z) > 0.5 ? 'h' : 'm') + '">' +
        (d.z > 0 ? '+' : '') + d.z.toFixed(2) + '</td></tr>';
    });
    h += '</table><div class="rx-sub">Twins</div><table><tr><th>Applicant</th><th>Outcome</th><th>Score</th><th>DTI</th><th>Util</th><th>Dist</th></tr>';
    t.twins.forEach(function (x) {
      h += '<tr class="rx-click" data-pos="' + x.map_pos + '"><td>' + esc(x.app_id) + (x.decline_rule ? ' <span class="m">' + esc(x.decline_rule.slice(0, 2)) + '</span>' : (x.seg === 'ANB' ? ' <span class="m">ANB</span>' : '')) +
        '</td><td>' + outcome(x.seg, x.bad) + '</td><td>' + val(x.values.bureau_score) + '</td><td>' + val(x.values.dti_pct) + '</td><td>' + val(x.values.util_pct) +
        '</td><td class="m">' + (x.dist == null ? '' : x.dist.toFixed(2)) + '</td></tr>';
    });
    h += '</table><p class="rx-note">Distance is Euclidean on all 22 standardised bureau and application attributes. Click a twin that is on the map to jump to it.</p>';
    var pane = $('rx-pane-twins'); pane.innerHTML = h;
    pane.querySelectorAll('tr.rx-click').forEach(function (tr) { tr.onclick = function () { var p = +tr.dataset.pos; if (p >= 0) pick(p); else toast('That twin is not in the map sample.'); }; });
  }

  // ───────── rules ─────────
  function neg(op) { return { '<': '>=', '>': '<=', '>=': '<', '<=': '>' }[op]; }
  function sweepConds(rule, cut) {
    var c = [];
    S.data.policy.forEach(function (p) {
      if (p.rule === 'R1') return;
      if (p.rule === rule.rule) { c.push({ f: p.column, op: p.op, v: p.thr }); c.push({ f: p.column, op: neg(p.op), v: cut }); }
      else c.push({ f: p.column, op: neg(p.op), v: p.thr });
    });
    return c;
  }
  function setRule(ev, title) {
    S.rule = ev; S.rule.title = title || 'Candidate rule';
    var mem = new Uint8Array(S.n); (ev.members || []).forEach(function (p) { mem[p] = 1; });
    S.members = mem; draw();
    $('rx-active').textContent = 'Highlighted: ' + ev.text;
    var hold = ev.holdout || {};
    var h = '<div class="rx-card"><b>' + esc(S.rule.title) + '</b> <span class="rx-pill ' + cls(ev.bad_adj) + '">' + (ev.beats_breakeven ? 'clears break-even' : 'below break-even') + '</span>' +
      '<code>IF ' + esc(ev.text).replace(/ and /g, '\n   AND ') + '\nTHEN approve (swap-in)</code>' +
      '<div class="rx-kpis">' +
      '<div class="rx-kpi"><span>Extra approvals</span><b>' + num(ev.n) + '</b></div>' +
      '<div class="rx-kpi"><span>Bureau bad rate</span><b>' + pct(ev.bad_bur) + '</b></div>' +
      '<div class="rx-kpi"><span>On-us equivalent</span><b class="' + cls(ev.bad_adj) + '">' + pct(ev.bad_adj) + '</b></div>' +
      '<div class="rx-kpi"><span>Approval rate</span><b>' + pct(ev.champion.approval) + ' → ' + pct(ev.challenger.approval) + '</b></div>' +
      '<div class="rx-kpi"><span>Portfolio bad rate</span><b>' + pct(ev.champion.bad, 2) + ' → ' + pct(ev.challenger.bad, 2) + '</b></div>' +
      '<div class="rx-kpi"><span>Est. profit</span><b class="' + (ev.profit > 0 ? 'g' : 'b') + '">' + money(ev.profit) + '</b></div></div>' +
      '<div class="m">Measured on ' + num(ev.n_bur) + ' with bureau performance (' + num(ev.good_bur) + ' good). Holdout 30%: ' + num(hold.n_bur) + ' applicants, bureau bad ' + pct(hold.bad_bur) + '.' +
      (ev.precision != null ? ' The rule covers ' + pct(ev.recall, 0) + ' of your selection; ' + pct(ev.precision, 0) + ' of what it captures on the map was selected.' : '') + '</div>';
    if (ev.by_rule && ev.by_rule.length) {
      h += '<table style="margin-top:8px"><tr><th>Currently declined by</th><th>Applicants</th><th>Bureau bad</th></tr>';
      ev.by_rule.forEach(function (r) { h += '<tr><td>' + esc(r.rule + ' ' + r.label) + '</td><td>' + num(r.n) + '</td><td>' + pct(r.bad_bur) + '</td></tr>'; });
      h += '</table>';
    }
    h += '<div class="rx-exp"><input class="rx-input" id="rx-expname" value="CHALLENGER_1"><button class="rx-btn rx-btn-go" id="rx-export">Send to Strategy Tree</button>' +
      '<button class="rx-btn" id="rx-clear">Clear</button></div></div>';
    $('rx-rulecard').innerHTML = h;
    $('rx-export').onclick = function () {
      var b = this; busy(b, true);
      post('/api/export', { name: $('rx-expname').value, conds: ev.conds }).then(function (r) {
        toast('Saved challenger tree ' + r.name + ' as strategies' + r.path + '.', true);
      }).catch(function (e) { toast(e.message); }).then(function () { busy(b, false); });
    };
    $('rx-clear').onclick = function () { S.rule = null; S.members = null; $('rx-rulecard').innerHTML = ''; $('rx-active').textContent = ''; draw(); };
    var fp = { label: S.rule.title, approval: ev.challenger.approval, bad: ev.challenger.bad };
    S.frontierPts = S.frontierPts.filter(function (p) { return p.label !== fp.label; }); S.frontierPts.push(fp);
  }
  function evalRule(conds, title) {
    return post('/api/rule', { conds: conds }).then(function (ev) { setRule(ev, title); }).catch(function (e) { toast(e.message); });
  }
  $('rx-sweep').onclick = function () {
    var b = this; busy(b, true);
    post('/api/sweep').then(function (r) {
      var h = '';
      r.rules.forEach(function (ru, ri) {
        h += '<div class="rx-sub">' + esc(ru.rule + ' · ' + ru.label) + ' <span class="m">· ' + num(ru.only_this_rule) + ' declined by this rule alone</span></div>' +
          '<table><tr><th>Move cut to</th><th>Come in</th><th>Marginal bad</th><th>Cumulative bad</th><th>Est. profit</th></tr>';
        ru.steps.forEach(function (s, si) {
          var rec = ru.recommended === s.cut;
          h += '<tr class="rx-click" data-r="' + ri + '" data-s="' + si + '"><td>' + esc(ru.column + ' ' + ru.op + ' ' + val(s.cut)) + (rec ? ' <span class="rx-pill g">suggested</span>' : '') +
            '</td><td>' + num(s.cum.n) + '</td><td class="' + cls(s.marginal.bad_adj) + '">' + pct(s.marginal.bad_adj) + '</td><td class="' + cls(s.cum.bad_adj) + '">' +
            pct(s.cum.bad_adj) + '</td><td class="' + (s.cum.profit > 0 ? 'g' : 'b') + '">' + money(s.cum.profit) + '</td></tr>';
        });
        h += '</table>';
        if (ru.recommended == null) h += '<p class="rx-note">No relaxation of this cut clears break-even on its own.</p>';
      });
      h += '<p class="rx-note">Bad rates are on-us equivalents; break-even is ' + pct(r.breakeven) + '. "Marginal" is the slice added by that step alone, which is the number to compare with break-even. Click a row to see who it brings in.</p>';
      $('rx-rulelist').innerHTML = h;
      $('rx-rulelist').querySelectorAll('tr.rx-click').forEach(function (tr) {
        tr.onclick = function () {
          var ru = r.rules[+tr.dataset.r], s = ru.steps[+tr.dataset.s];
          mark(tr); evalRule(sweepConds(ru, s.cut), 'Relax ' + ru.rule + ' to ' + ru.column + ' ' + ru.op + ' ' + val(s.cut));
        };
      });
    }).catch(function (e) { toast(e.message); }).then(function () { busy(b, false); });
  };
  function mark(tr) { $('rx-rulelist').querySelectorAll('tr.rx-sel').forEach(function (x) { x.classList.remove('rx-sel'); }); tr.classList.add('rx-sel'); }
  $('rx-bump').onclick = function () {
    var b = this; busy(b, true);
    post('/api/bump').then(function (r) {
      S.bump = r.steps.map(function (s) { return { approval: s.challenger.approval, bad: s.challenger.bad }; });
      var h = '<div class="rx-sub">Bump hunting on declined applicants <span class="m">· all declined: ' + num(r.base.n) + ', bureau bad ' + pct(r.base.bad_bur) + '</span></div>' +
        '<table><tr><th>#</th><th>Conditions</th><th>Applicants</th><th>On-us bad</th><th>Holdout bad</th><th>Est. profit</th></tr>';
      r.steps.forEach(function (s, i) {
        h += '<tr class="rx-click" data-i="' + i + '"><td>' + (i + 1) + (r.best === i ? ' <span class="rx-pill g">best</span>' : '') + '</td><td>' + s.conds.length + '</td><td>' + num(s.n) +
          '</td><td class="' + cls(s.bad_adj) + '">' + pct(s.bad_adj) + '</td><td class="m">' + pct(s.holdout.bad_adj) + '</td><td class="' + (s.profit > 0 ? 'g' : 'b') + '">' + money(s.profit) + '</td></tr>';
      });
      h += '</table><p class="rx-note">Each row peels one more edge off the box: fewer applicants, higher share of good performers. The row marked best has the highest estimated profit. ' +
        'Rules are found on 70% of the declined applicants with bureau performance and checked on the other 30%. Click a row to read the rule and see it on the map.</p>';
      $('rx-rulelist').innerHTML = h;
      $('rx-rulelist').querySelectorAll('tr.rx-click').forEach(function (tr) {
        tr.onclick = function () { var i = +tr.dataset.i; mark(tr); evalRule(r.steps[i].conds, 'Bump-hunting box #' + (i + 1)); };
      });
      if (r.best != null) { var best = $('rx-rulelist').querySelector('tr[data-i="' + r.best + '"]'); if (best) best.click(); }
    }).catch(function (e) { toast(e.message); }).then(function () { busy(b, false); });
  };
  function runLasso() {
    if (!S.lasso) return;
    var b = $('rx-lasso-go'); busy(b, true);
    post('/api/lasso', { positions: S.lasso }).then(function (ev) {
      setRule(ev, 'Rule from lasso (' + ev.selected + ' points)');
      S.poly = null; draw();
    }).catch(function (e) { toast(e.message); }).then(function () { busy(b, false); b.disabled = !S.lasso; });
  }
  $('rx-lasso-go').onclick = runLasso;

  // ───────── frontier ─────────
  function renderFrontier() {
    if (!S.data) return;
    var f = S.data.frontier, w = 410, h = 300, L = 46, R = 12, T = 12, B = 34;
    var cols = { KGB: '#8a94a3', HC: '#ff9f43', PCL: '#b07cff', FZ: '#4fd1c5' };
    var all = []; f.curves.forEach(function (c) { c.points.forEach(function (p) { all.push(p); }); });
    var pts = [{ label: 'Champion policy', approval: f.champion.approval, bad: f.champion.bad, champ: true }].concat(S.frontierPts);
    pts.forEach(function (p) { if (p.bad != null) all.push([p.approval, p.bad]); });
    (S.bump || []).forEach(function (p) { if (p.bad != null) all.push([p.approval, p.bad]); });
    var x0 = 0.3, x1 = 0.95, y1 = Math.max.apply(null, all.map(function (p) { return p[1]; })) * 1.08, y0 = 0;
    function X(v) { return L + (v - x0) / (x1 - x0) * (w - L - R); }
    function Y(v) { return h - B - (v - y0) / (y1 - y0) * (h - T - B); }
    var s = '<svg width="' + w + '" height="' + h + '">';
    for (var gx = 0.3; gx <= 0.91; gx += 0.1) s += '<line x1="' + X(gx) + '" x2="' + X(gx) + '" y1="' + T + '" y2="' + (h - B) + '" stroke="#1d242d"/><text x="' + X(gx) + '" y="' + (h - B + 14) + '" text-anchor="middle">' + Math.round(gx * 100) + '%</text>';
    for (var k = 0; k <= 4; k++) { var gy = y1 * k / 4; s += '<line x1="' + L + '" x2="' + (w - R) + '" y1="' + Y(gy) + '" y2="' + Y(gy) + '" stroke="#1d242d"/><text x="' + (L - 6) + '" y="' + (Y(gy) + 3) + '" text-anchor="end">' + (gy * 100).toFixed(1) + '%</text>'; }
    s += '<line x1="' + L + '" x2="' + (w - R) + '" y1="' + Y(be()) + '" y2="' + Y(be()) + '" stroke="' + C.hi + '" stroke-dasharray="4 4" opacity=".6"/>';
    f.curves.forEach(function (c) {
      s += '<path fill="none" stroke="' + cols[c.key] + '" stroke-width="1.8" d="' + c.points.map(function (p, i) { return (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1); }).join(' ') + '"/>';
    });
    (S.bump || []).forEach(function (p) { if (p.bad != null) s += '<circle cx="' + X(p.approval) + '" cy="' + Y(p.bad) + '" r="2.2" fill="' + C.hi + '" opacity=".55"/>'; });
    pts.forEach(function (p) {
      if (p.bad == null) return;
      s += p.champ ? '<rect x="' + (X(p.approval) - 5) + '" y="' + (Y(p.bad) - 5) + '" width="10" height="10" fill="#fff"/>' :
        '<circle cx="' + X(p.approval) + '" cy="' + Y(p.bad) + '" r="5" fill="' + C.hi + '" stroke="#000"/>';
    });
    s += '<text x="' + ((L + w - R) / 2) + '" y="' + (h - 4) + '" text-anchor="middle">approval rate</text><text x="12" y="' + ((T + h - B) / 2) + '" text-anchor="middle" transform="rotate(-90 12 ' + ((T + h - B) / 2) + ')">bad rate (on-us equivalent)</text></svg>';
    var hml = '<div class="rx-sub">Approval rate against bad rate</div>' + s + '<div class="rx-legend">' +
      f.curves.map(function (c) { return '<div><svg width="16" height="16"><line x1="1" x2="15" y1="8" y2="8" stroke="' + cols[c.key] + '" stroke-width="2"/></svg>' +
        ({ KGB: 'KGB model (booked only)', HC: 'Final model, hard cutoff', PCL: 'Final model, parceling', FZ: 'Final model, fuzzy' })[c.key] + ' used alone to rank everyone</div>'; }).join('') +
      '<div><svg width="16" height="16"><rect x="3" y="3" width="10" height="10" fill="#fff"/></svg>Champion policy today</div>' +
      '<div><svg width="16" height="16"><circle cx="8" cy="8" r="5" fill="' + C.hi + '"/></svg>Champion plus a candidate rule</div>' +
      '<div><svg width="16" height="16"><circle cx="8" cy="8" r="2.5" fill="' + C.hi + '" opacity=".6"/></svg>Bump-hunting trajectory</div></div>' +
      '<table style="margin-top:10px"><tr><th>Strategy</th><th>Approval</th><th>Bad rate</th></tr>' +
      pts.map(function (p) { return '<tr><td>' + esc(p.label) + '</td><td>' + pct(p.approval) + '</td><td>' + pct(p.bad, 2) + '</td></tr>'; }).join('') + '</table>' +
      '<p class="rx-note">Bad rate uses every observed outcome: internal for booked, bureau (scaled to on-us) for not-booked with a trade elsewhere. A point below and to the right of the champion approves more at a lower bad rate. The dashed line is break-even.</p>';
    $('rx-pane-frontier').innerHTML = hml;
  }

  // ───────── methods ─────────
  function renderMethods(m) {
    var h = '<div class="rx-sub">Inferred flags against bureau truth <span class="m">· ' + num(m.n) + ' not-booked with a bureau trade, actual bad ' + pct(m.actual_bad) + '</span></div>' +
      '<table><tr><th>Method</th><th>Inferred bad</th><th>Actual bad</th><th>Accuracy</th><th>Caught bads</th><th>False bads</th></tr>';
    m.flags.forEach(function (f) {
      h += '<tr><td>' + esc(f.key + ' · ' + f.name) + '</td><td>' + pct(f.inferred_bad) + '</td><td>' + pct(m.actual_bad) + '</td><td>' + (f.accuracy == null ? '<span class="m">weights</span>' : pct(f.accuracy)) +
        '</td><td>' + (f.tp == null ? '–' : num(f.tp) + ' / ' + num(f.tp + f.fn)) + '</td><td>' + (f.fp == null ? '–' : num(f.fp)) + '</td></tr>';
    });
    h += '</table><p class="rx-note">Hard cutoff calls everyone above the score cut bad. Parceling assigns bads at random in proportion to each score band\'s booked bad rate times a multiplier. Fuzzy keeps every not-booked applicant as part good, part bad, so it has no single flag to score.</p>' +
      '<div class="rx-sub">Applicants with no bureau trade (inference is the only evidence)</div><table><tr><th>Method</th><th>Inferred bad rate</th></tr>';
    m.flags.forEach(function (f) { h += '<tr><td>' + esc(f.key) + '</td><td>' + pct(f.inferred_bad_nobur) + '</td></tr>'; });
    h += '</table><div class="rx-sub">Final models</div><table><tr><th>Model</th><th>AUC booked</th><th>AUC not-bkd</th><th>Declined pred.</th><th>Declined actual</th></tr>';
    m.models.forEach(function (x) {
      h += '<tr><td>' + esc(x.key) + '</td><td>' + (x.auc_booked == null ? '–' : x.auc_booked.toFixed(3)) + '</td><td>' + (x.auc_notbooked == null ? '–' : x.auc_notbooked.toFixed(3)) +
        '</td><td>' + pct(x.pred_dec) + '</td><td>' + pct(x.actual_dec) + '</td></tr>';
    });
    h += '</table><p class="rx-note">KGB is the logistic regression trained on booked accounts only. HC, PCL and FZ are retrained on the augmented population. "AUC not-booked" scores each model against bureau performance it never saw; ' +
      '"Declined: predicted vs actual" shows how well each model\'s level matches what declined applicants did elsewhere.</p>';
    $('rx-pane-methods').innerHTML = h;
  }

  // ───────── controls / boot ─────────
  $('rx-color').onchange = function () { S.color = this.value; legend(); draw(); };
  document.querySelectorAll('[data-vis]').forEach(function (c) { c.onchange = function () { S.vis[c.dataset.vis] = c.checked; draw(); }; });
  document.querySelectorAll('[data-tool]').forEach(function (b) {
    b.onclick = function () {
      S.tool = b.dataset.tool; S.poly = null;
      document.querySelectorAll('[data-tool]').forEach(function (x) { x.classList.toggle('rx-on', x === b); });
      $('rx-toolhint').textContent = S.tool === 'lasso' ? 'Draw a closed shape around a cluster, for example blue triangles inside the green cloud.' : 'Click a point to find its counterfactual twins. Drag to pan, scroll to zoom.';
      cv.style.cursor = S.tool === 'lasso' ? 'cell' : 'crosshair'; draw();
    };
  });
  ['rx-margin', 'rx-loss'].forEach(function (id) {
    $(id).onchange = function () {
      $('rx-be').textContent = pct(be());
      post('/api/overview').then(renderOverview).catch(function (e) { toast(e.message); });
      if (S.rule) evalRule(S.rule.conds, S.rule.title);
    };
  });
  function boot(reload) {
    $('rx-status').textContent = 'loading…';
    post('/api/init', { reload: !!reload }).then(function (d) {
      S.data = d; S.P = d.points; S.n = d.points.row.length; S.sel = -1; S.twins = null; S.members = null;
      $('rx-npts').textContent = num(S.n);
      $('rx-status').textContent = (d.dataset || '') + (d.dataset_type ? ' (' + d.dataset_type + ')' : '') + ' · ' + num(d.overview.N) + ' applications · ' + num(S.n) + ' on map';
      renderOverview(d.overview); renderMethods(d.methods); legend(); fit();
      if (!S.n) toast('data/ri_map.csv is empty or missing: run python -m reject_inference.pipeline');
    }).catch(function (e) { $('rx-status').textContent = 'error'; toast('Could not load: ' + e.message); });
  }
  $('rx-reload').onclick = function () { boot(true); };
  window.addEventListener('resize', fit);
  boot(false);
})();
