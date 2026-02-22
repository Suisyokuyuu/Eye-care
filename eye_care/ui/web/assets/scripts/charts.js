// 图表模块 - 负责所有图表的初始化和更新（全文件 ES5-safe）

// ==== ColorManager：使用旧包配色 ====
var HUE_DISTANCE_MIN = 18;
var PICK_AVOID_MAX_RETRIES = 8;

// 彩虹七色 + 备用色
var BASE_PALETTE = [
  [59, 130, 246],   // 蓝
  [249, 115, 22],   // 橙
  [20, 184, 166],   // 青
  [239, 68, 68],    // 红
  [34, 197, 94],    // 绿
  [139, 92, 246],   // 紫
  [234, 179, 8],    // 黄（备用）
  [107, 114, 128]   // 灰（备用）
];

function _hash32(str) {
  if (str === null || str === undefined) str = '';
  str = String(str);
  var h = 2166136261;
  for (var i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = (h * 16777619) | 0;
  }
  return (h >>> 0);
}

function _rgbToHsl(r, g, b) {
  r = r / 255; g = g / 255; b = b / 255;
  var max = Math.max(r, g, b), min = Math.min(r, g, b);
  var l = (max + min) / 2;
  var s = 0, h = 0;
  if (max !== min) {
    var d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
    else if (max === g) h = ((b - r) / d + 2) / 6;
    else h = ((r - g) / d + 4) / 6;
  }
  h = Math.round(h * 360);
  s = Math.round(s * 100);
  l = Math.round(l * 100);
  return { h: h, s: s, l: l };
}

function _hslToRgb(h, s, l) {
  s = s / 100; l = l / 100;
  var k = function(n) { return (n + h / 30) % 12; };
  var a = s * Math.min(l, 1 - l);
  var f = function(n) {
    return l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  };
  return [Math.round(255 * f(0)), Math.round(255 * f(8)), Math.round(255 * f(4))];
}

function _hueDistance(h1, h2) {
  var d = Math.abs(h1 - h2) % 360;
  return d > 180 ? 360 - d : d;
}

function _rgbaToHue(rgbaStr) {
  if (!rgbaStr || typeof rgbaStr !== 'string') return 0;
  var m = rgbaStr.match(/rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  if (!m) return 0;
  var hsl = _rgbToHsl(parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10));
  return hsl.h;
}

function pickColorAvoidingNear(colorsUsed, baseColor) {
  var baseRgb = baseColor;
  if (typeof baseColor === 'string') {
    var match = baseColor.match(/rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    if (match) baseRgb = [parseInt(match[1], 10), parseInt(match[2], 10), parseInt(match[3], 10)];
    else baseRgb = [64, 156, 255];
  }
  var baseHsl = _rgbToHsl(baseRgb[0], baseRgb[1], baseRgb[2]);
  var usedHues = [];
  for (var u = 0; u < (colorsUsed && colorsUsed.length ? colorsUsed.length : 0); u++) {
    usedHues.push(_rgbaToHue(colorsUsed[u]));
  }
  function tooClose(hue) {
    for (var i = 0; i < usedHues.length; i++) {
      if (_hueDistance(hue, usedHues[i]) < HUE_DISTANCE_MIN) return true;
    }
    return false;
  }
  var s = baseHsl.s, l = baseHsl.l;
  if (!tooClose(baseHsl.h)) {
    return 'rgba(' + baseRgb[0] + ',' + baseRgb[1] + ',' + baseRgb[2] + ',1)';
  }
  for (var retry = 0; retry < PICK_AVOID_MAX_RETRIES; retry++) {
    var shift = HUE_DISTANCE_MIN * (retry + 1);
    var candidateH = (baseHsl.h + shift) % 360;
    if (candidateH < 0) candidateH += 360;
    if (!tooClose(candidateH)) {
      var rgb = _hslToRgb(candidateH, s, l);
      return 'rgba(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ',1)';
    }
  }
  return 'rgba(' + baseRgb[0] + ',' + baseRgb[1] + ',' + baseRgb[2] + ',1)';
}

function colorForKey(key, alpha) {
  if (alpha === null || alpha === undefined) alpha = 0.8;
  var idx = _hash32(key) % BASE_PALETTE.length;
  var rgb = BASE_PALETTE[idx];
  return 'rgba(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ',' + alpha + ')';
}

function borderForKey(key) {
  return colorForKey(key, 1);
}

// 全局颜色缓存，确保同一 key 在所有图表中使用相同颜色
var keyColorCache = {};

function colorForKeyInContext(key, alpha, usedColors) {
  if (alpha === null || alpha === undefined) alpha = 0.8;
  // 如果已经有缓存的颜色，直接使用（确保同一 key 在所有图表中颜色一致）
  if (keyColorCache[key]) {
    return keyColorCache[key].replace(',1)', ',' + alpha + ')');
  }
  // 首次分配：基于 key 的 hash 固定分配颜色
  var idx = _hash32(key) % BASE_PALETTE.length;
  var baseRgb = BASE_PALETTE[idx];
  var solid = 'rgba(' + baseRgb[0] + ',' + baseRgb[1] + ',' + baseRgb[2] + ',1)';
  // 如果有 usedColors，进行颜色冲突避免
  if (usedColors && usedColors.length > 0) {
    solid = pickColorAvoidingNear(usedColors, baseRgb);
  }
  // 缓存该 key 的颜色
  keyColorCache[key] = solid;
  return solid.replace(',1)', ',' + alpha + ')');
}

window.colorForKey = colorForKey;
window.borderForKey = borderForKey;
window.colorForKeyInContext = colorForKeyInContext;
window.pickColorAvoidingNear = pickColorAvoidingNear;

var CHART_COLORS = BASE_PALETTE.map(function(rgb) {
  return 'rgba(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ',0.8)';
});
var CHART_BORDERS = BASE_PALETTE.map(function(rgb) {
  return 'rgba(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ',1)';
});
window.CHART_COLORS = CHART_COLORS;
window.CHART_BORDERS = CHART_BORDERS;
// ==== end ColorManager ====

// ==== 渐变 + hover 质感（ES5-safe） ====
function parseRgba(str) {
  if (!str || typeof str !== 'string') return { r: 64, g: 156, b: 255, a: 0.8 };
  var m = str.match(/rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)/);
  if (!m) return { r: 64, g: 156, b: 255, a: 0.8 };
  var a = m[4] != null ? parseFloat(m[4]) : 1;
  if (a > 1) a = 1;
  if (a < 0) a = 0;
  return { r: parseInt(m[1], 10), g: parseInt(m[2], 10), b: parseInt(m[3], 10), a: a };
}

function makeRadialGradient(ctx, baseRgba, cx, cy, rOuter) {
  var rgb = parseRgba(baseRgba);
  if (cx == null) cx = 0;
  if (cy == null) cy = 0;
  if (rOuter == null || rOuter <= 0) rOuter = 140;
  var rInner = Math.max(1, rOuter * 0.07);
  var g = ctx.createRadialGradient(cx, cy, rInner, cx, cy, rOuter);
  g.addColorStop(0, 'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',0.95)');
  g.addColorStop(0.7, 'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',' + rgb.a + ')');
  g.addColorStop(1, 'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',0.55)');
  return g;
}

function makeVerticalGradient(ctx, area, baseRgba) {
  var rgb = parseRgba(baseRgba);
  if (!area) area = { top: 0, bottom: 100 };
  var g = ctx.createLinearGradient(0, area.top, 0, area.bottom);
  g.addColorStop(0, 'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',0.95)');
  g.addColorStop(0.55, 'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',' + rgb.a + ')');
  g.addColorStop(1, 'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',0.55)');
  return g;
}

function replacePieGradients(chart) {
  if (!chart || !chart.ctx || !chart.data.datasets) return;
  var type = chart.config && chart.config.type ? chart.config.type : (chart.options && chart.options.type);
  if (type !== 'doughnut' && type !== 'pie') return;
  var area = chart.chartArea;
  var cx = area ? (area.left + area.right) / 2 : 0;
  var cy = area ? (area.top + area.bottom) / 2 : 0;
  var rOuter = area ? Math.min(area.right - area.left, area.bottom - area.top) / 2 : 140;
  var ds = chart.data.datasets[0];
  if (!ds || !ds.backgroundColor) return;
  var arr = ds.backgroundColor;
  var out = [];
  for (var i = 0; i < arr.length; i++) {
    var c = arr[i];
    if (typeof c === 'string') out.push(makeRadialGradient(chart.ctx, c, cx, cy, rOuter));
    else out.push(c);
  }
  ds.backgroundColor = out;
}

function replaceBarGradients(chart) {
  if (!chart || !chart.ctx || !chart.data.datasets) return;
  var area = chart.chartArea;
  for (var i = 0; i < chart.data.datasets.length; i++) {
    var ds = chart.data.datasets[i];
    var c = ds.backgroundColor;
    if (typeof c === 'string') ds.backgroundColor = makeVerticalGradient(chart.ctx, area, c);
    // 同时处理 hover 背景色，避免 hover 时颜色异常
    var h = ds.hoverBackgroundColor;
    if (typeof h === 'string') ds.hoverBackgroundColor = makeVerticalGradient(chart.ctx, area, h);
  }
}

window.parseRgba = parseRgba;
window.makeRadialGradient = makeRadialGradient;
window.makeVerticalGradient = makeVerticalGradient;
window.replacePieGradients = replacePieGradients;
window.replaceBarGradients = replaceBarGradients;

(function registerHoverGlowPlugin() {
  if (typeof Chart === 'undefined') return;
  var id = 'hoverGlow';
  if (Chart.registry && Chart.registry.getPlugin(id)) return;
  function roundRectPath(ctx, x, y, w, h, r) {
    if (r <= 0) { ctx.rect(x, y, w, h); return; }
    var pi = Math.PI;
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.arc(x + w - r, y + r, r, -pi / 2, 0);
    ctx.lineTo(x + w, y + h - r);
    ctx.arc(x + w - r, y + h - r, r, 0, pi / 2);
    ctx.lineTo(x + r, y + h);
    ctx.arc(x + r, y + h - r, r, pi / 2, pi);
    ctx.lineTo(x, y + r);
    ctx.arc(x + r, y + r, r, pi, pi * 1.5);
  }
  Chart.register({
    id: id,
    afterDatasetsDraw: function(chart) {
      var tooltip = chart.tooltip;
      if (!tooltip || !tooltip._active || !tooltip._active.length) return;
      var ctx = chart.ctx;
      var barIndices = [];
      for (var i = 0; i < tooltip._active.length; i++) {
        var el = tooltip._active[i].element;
        if (!el) continue;
        var oR = el.outerRadius;
        if (el.getProps && typeof el.getProps === 'function') {
          var p = el.getProps(['outerRadius'], true);
          if (p) oR = p.outerRadius;
        }
        if (oR != null && oR > 0) {
          var x = el.x, y = el.y, start = el.startAngle, end = el.endAngle, iR = el.innerRadius;
          if (el.getProps && typeof el.getProps === 'function') {
            var p2 = el.getProps(['x', 'y', 'startAngle', 'endAngle', 'innerRadius'], true);
            if (p2) { x = p2.x; y = p2.y; start = p2.startAngle; end = p2.endAngle; iR = p2.innerRadius; }
          }
          ctx.save();
          ctx.shadowBlur = 10;
          ctx.shadowColor = 'rgba(255,255,255,0.22)';
          ctx.strokeStyle = 'rgba(255,255,255,0.28)';
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(x, y, oR, start, end);
          if (iR != null && iR > 0) { ctx.arc(x, y, iR, end, start, true); }
          ctx.closePath();
          ctx.stroke();
          ctx.restore();
        } else {
          var idx = tooltip._active[i].index;
          if (idx !== undefined && barIndices.indexOf(idx) === -1) barIndices.push(idx);
        }
      }
      for (var bi = 0; bi < barIndices.length; bi++) {
        var idx = barIndices[bi];
        var topY = Infinity, baseY = -Infinity, left = 0, width = 0;
        for (var d = 0; d < chart.data.datasets.length; d++) {
          var meta = chart.getDatasetMeta(d);
          if (!meta || !meta.data || !meta.data[idx]) continue;
          var raw = chart.data.datasets[d] && chart.data.datasets[d].data && chart.data.datasets[d].data[idx];
          if (raw == null || Number(raw) <= 0) continue;
          var seg = meta.data[idx];
          var sy = seg.y, sbase = seg.base;
          topY = Math.min(topY, sy, sbase);
          baseY = Math.max(baseY, sy, sbase);
          if (width === 0 && seg.width != null) { left = seg.x - seg.width / 2; width = seg.width; }
        }
        if (topY === Infinity || baseY === -Infinity || width <= 0) continue;
        var barH = Math.abs(baseY - topY);
        if (barH < 6) {
          ctx.save();
          ctx.shadowBlur = 0;
          ctx.strokeStyle = 'rgba(255,255,255,0.12)';
          ctx.lineWidth = 1;
          ctx.strokeRect(left, topY, width, barH);
          ctx.restore();
        } else {
          ctx.save();
          ctx.shadowBlur = 10;
          ctx.shadowColor = 'rgba(255,255,255,0.22)';
          ctx.strokeStyle = 'rgba(255,255,255,0.28)';
          ctx.lineWidth = 2;
          ctx.strokeRect(left, topY, width, barH);
          ctx.restore();
        }
      }
    }
  });
})();
// ==== end 渐变 + hover ====

var CATEGORY_ICONS = {
  '办公': 'desktop', '影音': 'film', '娱乐': 'gamepad',
  '通讯': 'comments', '学习': 'book', '工具': 'wrench', '其他': 'circle-o'
};

function initCategoryChart() {
  var el = document.getElementById('categoryChart');
  var ctx = el ? el.getContext('2d') : null;
  if (!ctx) return;
  var chart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['办公', '影音', '娱乐', '通讯', '学习', '工具'],
      datasets: [{
        data: [45, 35, 20, 15, 25, 10],
        backgroundColor: CHART_COLORS,
        borderColor: Array(6).fill('rgba(255, 255, 255, 0.3)'),
        borderWidth: 1,
        hoverBorderWidth: 1.2,
        hoverBorderColor: 'rgba(255,255,255,0.28)',
        hoverOffset: 18
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '72%',
      spacing: 2,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(15, 23, 42, 0.9)',
          titleColor: 'white',
          bodyColor: 'rgba(255, 255, 255, 0.7)',
          borderColor: 'rgba(255, 255, 255, 0.1)',
          borderWidth: 1,
          padding: 12,
          callbacks: {
            label: function(context) {
              var data = context.dataset.data;
              var total = 0;
              for (var i = 0; i < data.length; i++) total += data[i];
              var pct = total > 0 ? Math.round((context.raw / total) * 100) : 0;
              return context.label + ': ' + pct + '%';
            }
          }
        }
      },
      animation: {
        animateRotate: true,
        animateScale: true,
        duration: 200,
        easing: 'easeOutCubic'
      }
    }
  });
  window.categoryChartInstance = chart;
}

function initAppChart() {
  var el = document.getElementById('appChart');
  var ctx = el ? el.getContext('2d') : null;
  if (!ctx) return;
  var chart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['暂无'],
      datasets: [{
        data: [100],
        backgroundColor: ['rgba(107, 114, 128, 0.8)'],
        borderColor: ['rgba(107, 114, 128, 1)'],
        borderWidth: 1,
        hoverBorderWidth: 1.2,
        hoverBorderColor: 'rgba(255,255,255,0.28)',
        hoverOffset: 18
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '72%',
      spacing: 2,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(15, 23, 42, 0.9)',
          titleColor: 'white',
          bodyColor: 'rgba(255, 255, 255, 0.7)',
          callbacks: {
            label: function(context) {
              var data = context.dataset.data;
              var total = 0;
              for (var i = 0; i < data.length; i++) total += data[i];
              var pct = total > 0 ? Math.round((context.raw / total) * 100) : 0;
              return context.label + ': ' + pct + '%';
            }
          }
        }
      },
      animation: { duration: 200, easing: 'easeOutCubic' },
      onClick: function(ev, elements) {
        try {
          if (elements && elements.length && window.appChartKeys) {
            var idx = elements[0].index;
            var k = window.appChartKeys[idx];
            if (k && typeof focusAppCardByKey === 'function') focusAppCardByKey(k);
          }
        } catch (e) {}
      }
    }
  });
  window.appChartInstance = chart;
}

window.statsHighlightKey = null;

function initTimeBarsChart() {
  var canvas = document.getElementById('timeBarsChart');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');
  var chart = new Chart(ctx, {
    type: 'bar',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 220 },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(15, 23, 42, 0.9)',
          callbacks: {
            label: function(ctx) {
              var v = ctx.raw;
              if (v <= 0) return '';
              var m = Math.round(v / 60);
              return (ctx.dataset.label || '') + ': ' + (m > 0 ? m + ' 分钟' : v + ' 秒');
            }
          }
        }
      },
      interaction: {
        mode: 'nearest',
        axis: 'x',
        intersect: false
      },
      scales: {
        x: {
          stacked: true,
          grid: { display: false },
          ticks: { color: 'rgba(255,255,255,0.5)', maxRotation: 0 }
        },
        y: {
          stacked: true,
          grid: { color: 'rgba(255,255,255,0.08)' },
          ticks: { color: 'rgba(255,255,255,0.5)' }
        }
      }
    }
  });
  window.timeBarsChartInstance = chart;
}
