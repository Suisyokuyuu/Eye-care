/**
 * API 鉴权：为首屏及所有写请求自动附加 X-EYECare-Token。
 * 必须作为第一个脚本加载，在其它 fetch 调用前 patch 完成。
 */
(function() {
  var origFetch = typeof window !== 'undefined' ? window.fetch : null;
  if (!origFetch) return;

  var token = null;
  var tokenPromise = null;

  function getToken() {
    if (token) return Promise.resolve(token);
    if (!tokenPromise) {
      var base = (window.location && window.location.origin) || '';
      tokenPromise = origFetch(base + '/api/auth/token')
        .then(function(r) { return r.json(); })
        .then(function(d) { token = (d && d.token) || null; return token; })
        .catch(function() { return null; });
    }
    return tokenPromise;
  }

  window.fetch = function(url, opts) {
    opts = opts || {};
    var method = (opts.method || 'GET').toUpperCase();
    var urlStr = String(url || '');
    var isWrite = method !== 'GET' && method !== 'HEAD' && urlStr.indexOf('/api/') >= 0 && urlStr.indexOf('/api/auth/') < 0;
    if (!isWrite) return origFetch.apply(this, arguments);

    return getToken().then(function(t) {
      opts.headers = opts.headers || {};
      if (typeof opts.headers === 'object' && !Array.isArray(opts.headers) && opts.headers !== null) {
        opts.headers['X-EYECare-Token'] = t || '';
      }
      return origFetch.call(window, url, opts);
    });
  };
})();
