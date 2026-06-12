"""
HTML injection scripts for bridge and drag region.
"""
import re


def inject_bridge_script(html: str) -> str:
    """在 </head> 前注入脚本，定义 window.electronAPI（沿用既有前端接口命名）。"""
    bridge = r"""
<script>
(function() {
  // 注意：UI 与 API 在同一个 Flask 端口上，所以 origin 就是 API 基址
  var base = window.location.origin;
  function api(method, path, body) {
    var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
    if (body && (method === 'POST' || method === 'PUT')) opts.body = JSON.stringify(body);
    return fetch(base + path, opts).then(function(r) { return r.json(); });
  }
  window.electronAPI = {
    isElectron: true,
    close: function() {
      if (window.__EYECARE_QT_CALL__) return window.__EYECARE_QT_CALL__('closeWindow', []);
      if (window.pywebview && window.pywebview.api) return window.pywebview.api.close_window();
    },
    minimize: function() {
      if (window.__EYECARE_QT_CALL__) return window.__EYECARE_QT_CALL__('minimizeWindow', []);
      if (window.pywebview && window.pywebview.api) return window.pywebview.api.minimize_window();
    },
    maximizeToggle: function() {
      if (window.__EYECARE_QT_CALL__) return window.__EYECARE_QT_CALL__('maximizeToggle', []);
      if (window.pywebview && window.pywebview.api) return window.pywebview.api.maximize_toggle();
    },

    getSnapshot: function(params) {
      var q = '';
      if (params && params.date) q += '?date=' + encodeURIComponent(params.date);
      if (params && params.range) q += (q ? '&' : '?') + 'range=' + encodeURIComponent(params.range);

      if (params && params.range === 'custom') {
        if (params.range_start) q += (q ? '&' : '?') + 'range_start=' + encodeURIComponent(params.range_start);
        if (params.range_end) q += (q ? '&' : '?') + 'range_end=' + encodeURIComponent(params.range_end);
      }

      return api('GET', '/api/snapshot' + (q || ''));
    },

    getCalendarMonth: function(year, month) {
      return api('GET', '/api/calendar_month?year=' + encodeURIComponent(year) + '&month=' + encodeURIComponent(month));
    },

    restStart: function() { return api('POST', '/api/rest/start'); },
    restComplete: function() { return api('POST', '/api/rest/complete'); },
    restSnooze: function() { return api('POST', '/api/rest/snooze'); },
    restShowOverlay: function() {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.rest_show_overlay === 'function')
        return window.pywebview.api.rest_show_overlay();
      return Promise.reject(new Error('rest_show_overlay not available'));
    },
    dndSet: function(on) { return api('POST', '/api/dnd', { on: !!on }); },

    // 导入/导出：走 pywebview 的文件对话框 + 复用 transfer 逻辑
    exportAll: function() {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.export_all)
        return Promise.resolve(window.pywebview.api.export_all());
      return Promise.reject(new Error('not available'));
    },
    importAll: function() {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.import_all)
        return Promise.resolve(window.pywebview.api.import_all());
      return Promise.reject(new Error('not available'));
    }
  };

  // 供 UI 自检：如果用户双击打开 HTML，会缺失这个注入对象
  window.__EYECARE_BRIDGED__ = true;
})();
</script>
"""
    if "</head>" in html:
        out = html.replace("</head>", bridge + "\n</head>", 1)
    else:
        out = bridge + html
    from eye_care.version import APP_VERSION
    return out.replace("{{APP_VERSION}}", " " + (APP_VERSION or ""))


def inject_drag_region(html: str) -> str:
    """为无边框窗口可拖拽：给标题栏加上 pywebview-drag-region。

    按完整 class 字符串匹配在 UI 调整后容易失效。
    这里改为：只要命中 <header ... class="... app-titlebar ..."> 就插入拖拽类。
    """
    if "pywebview-drag-region" in html:
        return html

    # 命中形如：<header ... class="app-titlebar ...">
    def _add(m):
        cls = m.group(1)
        # 只插入一次：紧跟在 app-titlebar 之后
        print_cls = cls.replace("app-titlebar", "app-titlebar pywebview-drag-region", 1)
        return f'class="{print_cls}"'

    return re.sub(r'class="([^"]*\bapp-titlebar\b[^"]*)"', _add, html, count=1)
