(function() {
            function postDiag(stage, extra) {
                try {
                    var base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
                    if (!base || base === 'null') return;
                    var payload = {
                        msg: 'ui',
                        src: 'main_ui',
                        stage: String(stage || ''),
                        ts: Date.now(),
                        href: (window.location && window.location.href) ? window.location.href : '',
                        extra: extra || null
                    };
                    fetch(base + '/api/diag/log', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-Eyecare-Source': 'main_ui' },
                        body: JSON.stringify(payload),
                        keepalive: true
                    }).catch(function() {});
                } catch (e) {}
            }
            window.postDiag = postDiag;
            window.onerror = function(message, url, line, col, err) {
                postDiag('js_error', {
                    message: message,
                    stack: (err && err.stack) || (url ? url + ':' + line + ':' + col : undefined),
                    url: url,
                    line: line,
                    col: col
                });
                return false;
            };
            window.onunhandledrejection = function(e) {
                var reason = e && e.reason;
                postDiag('promise_rejection', {
                    reason: reason != null ? String(reason) : undefined,
                    stack: (reason && reason.stack) || undefined
                });
            };
        })();

        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        primary: '#3B82F6', // iOS蓝
                        secondary: '#1E40AF',
                        dark: {
                            100: '#1E293B',
                            200: '#0F172A',
                            300: '#0B1120',
                            400: '#070D19'
                        },
                        accent: '#60A5FA',
                        success: '#10B981',
                        warning: '#F59E0B',
                        danger: '#EF4444'
                    },
                    fontFamily: {
                        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif'],
                    },
                    boxShadow: {
                        'inner-light': 'inset 0 2px 4px 0 rgba(255, 255, 255, 0.05)',
                        'glow': '0 0 15px rgba(59, 130, 246, 0.5)',
                        'card': '0 4px 6px -1px rgba(0, 0, 0, 0.2), 0 2px 4px -1px rgba(0, 0, 0, 0.1)'
                    },
                    animation: {
                        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
                        'fade-in': 'fadeIn 0.5s ease-in-out',
                        'slide-up': 'slideUp 0.3s ease-out',
                        'slide-down': 'slideDown 0.3s ease-out',
                        'slide-in-right': 'slideInRight 0.3s ease-out',
                        'slide-in-left': 'slideInLeft 0.3s ease-out'
                    },
                    keyframes: {
                        fadeIn: {
                            '0%': { opacity: '0' },
                            '100%': { opacity: '1' }
                        },
                        slideUp: {
                            '0%': { transform: 'translateY(20px)', opacity: '0' },
                            '100%': { transform: 'translateY(0)', opacity: '1' }
                        },
                        slideDown: {
                            '0%': { transform: 'translateY(-20px)', opacity: '0' },
                            '100%': { transform: 'translateY(0)', opacity: '1' }
                        },
                        slideInRight: {
                            '0%': { transform: 'translateX(20px)', opacity: '0' },
                            '100%': { transform: 'translateX(0)', opacity: '1' }
                        },
                        slideInLeft: {
                            '0%': { transform: 'translateX(-20px)', opacity: '0' },
                            '100%': { transform: 'translateX(0)', opacity: '1' }
                        }
                    }
                }
            }
        }

// 分类视图图表 - 饼图
        function initCategoryChart() {
            const canvas = document.getElementById('categoryChart');
            if (!canvas) return;

            const r = canvas.getBoundingClientRect();
            if (!r || r.width < 2 || r.height < 2) {
                // 隐藏状态不创建 chart，避免 0 几何导致 hover 异常
                window.__categoryChartPendingInit = true;
                hardUiLog('chart_init_skip_hidden', { canvasId: 'categoryChart', rect_w: r ? r.width : null, rect_h: r ? r.height : null });
                return;
            }

            // 用 __lastSnapshot 算初始数据，避免“先动画假数据再 update 真数据”
            var labels = ['办公', '影音', '娱乐', '通讯', '学习', '工具'];
            var data = [45, 35, 20, 15, 25, 10];
            var snap = window.__lastSnapshot;
            if (snap && !snap.error) {
                var rangeKey = snap.range_key || 'day';
                var isRange = (rangeKey === 'week' || rangeKey === 'month' || rangeKey === 'custom');
                var byCat = isRange && snap.range_usage_by_category ? (snap.range_usage_by_category || {}) : (snap.usage_by_category || {});
                var totalSec = 0;
                Object.keys(byCat).forEach(function(k) { totalSec += (byCat[k] || 0); });
                var items = Object.keys(byCat)
                    .map(function(name) {
                        var sec = byCat[name];
                        var pct = totalSec > 0 ? Math.round((100 * sec) / totalSec) : 0;
                        return { name: name, seconds: sec, percent: pct };
                    })
                    .sort(function(a, b) { return b.seconds - a.seconds; });
                if (items.length > 0) {
                    labels = items.map(function(it) { return it.name; });
                    data = items.map(function(it) { return it.percent; });
                }
            }
            var used = [];
            var bg = labels.map(function(lbl) {
                var c = window.colorForKeyInContext ? window.colorForKeyInContext(lbl, 0.8, used) : (window.colorForKey ? window.colorForKey(lbl, 0.8) : 'rgba(59, 130, 246, 0.9)');
                var solid = c.replace(/,\s*[\d.]+\s*\)\s*$/, ',1)');
                used.push(solid);
                return c;
            });
            var borders = used.slice();

            const ctx = canvas.getContext('2d');
            // 创建图表实例（只播一次初始化动画）
            const chart = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            data: data,
                            backgroundColor: bg,
                            borderColor: borders,
                            borderWidth: 1,
                            hoverBorderWidth: 1.2,
                            hoverBorderColor: 'rgba(255,255,255,0.28)',
                            hoverOffset: 18,
                            shadowBlur: 25,
                            shadowColor: 'rgba(0, 0, 0, 0.5)',
                            innerGlow: {
                                color: 'rgba(255, 255, 255, 0.1)',
                                blur: 10
                            }
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '70%', // 调整中间空白区域大小
                    interaction: { mode: 'nearest', intersect: true },
                    hover: { mode: 'nearest', intersect: true },
                    elements: {
                        arc: {
                            borderAlign: 'inner',
                            hoverBorderWidth: 1.2,
                            hoverBorderColor: 'rgba(255,255,255,0.28)'
                        }
                    },
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            backgroundColor: 'rgba(15, 23, 42, 0.9)',
                            titleColor: 'white',
                            bodyColor: 'rgba(255, 255, 255, 0.7)',
                            borderColor: 'rgba(255, 255, 255, 0.1)',
                            borderWidth: 1,
                            padding: 12,
                            boxPadding: 6,
                            usePointStyle: true,
                            callbacks: {
                                label: function(context) {
                                    const label = context.label || '';
                                    const value = context.raw || 0;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = Math.round((value / total) * 100);
                                    return `${label}: ${percentage}%`;
                                }
                            }
                        },
                        // 移除不必要的centerText配置，使用插件处理
                    },
                    animation: {
                        animateRotate: true,
                        animateScale: true,
                        duration: 1000,
                        easing: 'easeOutQuart'
                    }
                },
                // 分类视图饼图：圆环内不绘制文字，总时长已在右侧文案展示
                plugins: []
            });
            window.categoryChartInstance = chart;
            window.__categoryChartPrimed = true;
            window.__needCategoryEnterAnim = false;
            if (window.__lastSnapshot) {
                try { updateCategoryViewFromSnapshot(window.__lastSnapshot); } catch (e) {}
            }
        }

        function ensureCategoryChartReady() {
            const canvas = document.getElementById('categoryChart');
            if (!canvas) return;

            const r = canvas.getBoundingClientRect();
            if (!r || r.width < 2 || r.height < 2) return;

            // 如果之前创建过但尺寸为 0，直接销毁重建（最关键）
            if (window.categoryChartInstance && (window.categoryChartInstance.width === 0 || window.categoryChartInstance.height === 0)) {
                try { window.categoryChartInstance.destroy(); } catch (e) {}
                window.categoryChartInstance = null;
                window.__categoryChartPrimed = false;
            }

            if (!window.categoryChartInstance) {
                window.__categoryChartPendingInit = false;
                initCategoryChart();
            }

            // 显示后强制一次 resize/update
            if (window.categoryChartInstance) {
                try { window.categoryChartInstance.resize(); } catch (e) {}
                try { window.categoryChartInstance.update('none'); } catch (e) {}
            }
        }

        function buildItemsHash(items, totalSec, topN, getKey) {
            if (!getKey) getKey = function(it) { return it.key || it.name || ''; };
            var n = Math.min(typeof topN === 'number' ? topN : items.length, items.length);
            var s = String(Math.round(totalSec || 0)) + '|';
            for (var i = 0; i < n; i++) {
                var it = items[i];
                s += (getKey(it) || '') + ':' + String(Math.round(it.seconds || 0)) + ';';
            }
            return s;
        }

        // 分类视图：由 snapshot 驱动；日视图用当日，周/月用范围聚合
        var CATEGORY_ICONS = { '办公': 'desktop', '影音': 'film', '娱乐': 'gamepad', '通讯': 'comments', '学习': 'book', '工具': 'wrench', '其他': 'circle-o' };
        function updateCategoryViewFromSnapshot(snap, opts) {
            if (!snap || snap.error) return;
            opts = opts || {};
            var noAnim = opts.anim === false;
            var rangeKey = snap.range_key || 'day';
            var isRange = (rangeKey === 'week' || rangeKey === 'month' || rangeKey === 'custom');
            var byCat = isRange && snap.range_usage_by_category
                ? (snap.range_usage_by_category || {})
                : (snap.usage_by_category || {});

            var rangeStart = snap.range_start || '';
            var rangeEnd = snap.range_end || rangeStart;
            var localDate = (snap.vm && snap.vm.local_date) ? snap.vm.local_date : '';

            var dateLabel = localDate;
            if (rangeKey === 'day') dateLabel = (localDate === localTodayStr()) ? '今日' : localDate;
            else if (rangeKey === 'week') {
                // 本周日期范围
                var d = parseYMD(localDate) || new Date();
                var dayOfWeek = (d.getDay() + 6) % 7; // 0=周一
                var weekStart = new Date(d);
                weekStart.setDate(d.getDate() - dayOfWeek);
                var weekEnd = new Date(weekStart);
                weekEnd.setDate(weekStart.getDate() + 6);
                dateLabel = toMD(weekStart) + ' ~ ' + toMD(weekEnd);
            }
            else if (rangeKey === 'month') {
                // 本月日期范围
                var d = parseYMD(localDate) || new Date();
                var monthStart = new Date(d.getFullYear(), d.getMonth(), 1);
                var monthEnd = new Date(d.getFullYear(), d.getMonth() + 1, 0);
                dateLabel = toMD(monthStart) + ' ~ ' + toMD(monthEnd);
            }
            else if (rangeKey === 'custom') {
                // 自定义范围也去掉年份
                var startParts = (rangeStart || '').split('-');
                var endParts = (rangeEnd || '').split('-');
                var startMD = startParts.length >= 3 ? startParts[1] + '-' + startParts[2] : rangeStart;
                var endMD = endParts.length >= 3 ? endParts[1] + '-' + endParts[2] : rangeEnd;
                dateLabel = (rangeStart && rangeEnd) ? (startMD + ' ~ ' + endMD) : localDate;
            }

            var totalSec = 0;
            Object.keys(byCat).forEach(function(k) { totalSec += (byCat[k] || 0); });
            var totalText = formatWorkTime(totalSec);
            var items = Object.keys(byCat)
                .map(function(name) {
                    var sec = byCat[name];
                    var pct = totalSec > 0 ? Math.round((100 * sec) / totalSec) : 0;
                    return { name: name, seconds: sec, percent: pct, duration: formatWorkTime(sec) };
                })
                .sort(function(a, b) { return b.seconds - a.seconds; });

            var titleEl = document.getElementById('categorySummaryTitle');
            var totalEl = document.getElementById('categoryTotalTime');
            var topEl = document.getElementById('categoryTopLines');
            var listEl = document.getElementById('categoryListContainer');
            if (titleEl) titleEl.textContent = (dateLabel ? dateLabel + ' ' : '') + '屏幕使用时间';
            if (totalEl) totalEl.textContent = totalText;
            var catHashTop = buildItemsHash(items, totalSec, 5, function(it) { return it.name; });
            if (topEl && topEl.__hash !== catHashTop) {
                topEl.__hash = catHashTop;
                topEl.className = 'pie-top-lines space-y-1 text-sm';
                var usedCatTop = [];
                topEl.innerHTML = items.slice(0, 5).map(function(it) {
                    var c = window.colorForKeyInContext ? window.colorForKeyInContext(it.name, 1, usedCatTop) : (window.borderForKey ? window.borderForKey(it.name) : 'rgba(255,255,255,0.3)');
                    usedCatTop.push(c);
                    var line = escapeHtml(it.name) + ' - ' + escapeHtml(it.duration) + ' ' + Math.round(it.percent) + '%';
                    return '<div class="pie-top-line"><span class="pie-dot" style="background:' + c + '"></span><span class="pie-line-text">' + line + '</span></div>';
                }).join('') || '<span class="text-gray-500">暂无数据</span>';
            }
            var catHashList = buildItemsHash(items, totalSec, items.length, function(it) { return it.name; });
            if (listEl && listEl.__hash !== catHashList) {
                listEl.__hash = catHashList;
                var usedCatList = [];
                listEl.innerHTML = items.map(function(it) {
                    var color = window.colorForKeyInContext ? window.colorForKeyInContext(it.name, 0.8, usedCatList) : (window.colorForKey ? window.colorForKey(it.name, 0.8) : 'rgba(59,130,246,0.8)');
                    var solid = color.replace(/,\s*[\d.]+\s*\)\s*$/, ',1)');
                    usedCatList.push(solid);
                    var bgDim = color.replace(/,\s*[\d.]+\s*\)\s*$/, ',0.2)');
                    var icon = CATEGORY_ICONS[it.name] || 'circle-o';
                    return '<div class="category-card flex items-center justify-between p-3 panel-inner rounded-lg border border-white/5 cursor-pointer hover:bg-dark-300/80 transition-colors" data-category="' + escapeHtml(it.name) + '">' +
                        '<div class="flex items-center"><div class="w-10 h-10 rounded-lg flex items-center justify-center mr-3" style="background:' + bgDim + '"><i class="fa fa-' + icon + ' text-sm" style="color:' + solid + '"></i></div>' +
                        '<div><h3 class="font-medium">' + escapeHtml(it.name) + '</h3><p class="text-sm text-gray-400">' + it.duration + '</p></div></div>' +
                        '<div class="flex items-center"><div class="w-24 h-2 bg-dark-300 rounded-full overflow-hidden mr-2"><div class="h-full rounded-full" style="width:' + it.percent + '%;background:' + solid + '"></div></div>' +
                        '<span class="text-xs text-gray-400">' + it.percent + '%</span></div></div>';
                }).join('') || '<p class="text-gray-500 text-sm py-4 text-center">暂无使用记录</p>';
            }
            if (window.categoryChartInstance) {
                var chart = window.categoryChartInstance;
                var labels = items.map(function(it) { return it.name; });
                var data = items.map(function(it) { return it.percent; });
                var usedCat = [];
                var bg = items.map(function(it) {
                    var c = window.colorForKeyInContext ? window.colorForKeyInContext(it.name, 0.8, usedCat) : (window.colorForKey ? window.colorForKey(it.name, 0.8) : 'rgba(107, 114, 128, 0.8)');
                    var solid = c.replace(/,\s*[\d.]+\s*\)\s*$/, ',1)');
                    usedCat.push(solid);
                    return c;
                });
                var borders = usedCat.slice();
                if (labels.length === 0) { labels = ['暂无']; data = [100]; bg = ['rgba(107, 114, 128, 0.8)']; borders = ['rgba(107, 114, 128, 1)']; }
                chart.data.labels = labels;
                chart.data.datasets[0].data = data;
                chart.data.datasets[0].backgroundColor = bg;
                chart.data.datasets[0].borderColor = borders;
                if (window.replacePieGradients) window.replacePieGradients(chart);
                if (!window.__categoryChartPrimed) {
                    window.__categoryChartPrimed = true;
                    window.__needCategoryEnterAnim = false;
                    chart.update();
                    return;
                }
                if (!noAnim && window.__needCategoryEnterAnim) {
                    window.__needCategoryEnterAnim = false;
                    try { playRotateScaleOnce(chart, 520); } catch (e) {}
                    return;
                }
                chart.update('none');
            }
        }

        // 应用视图图表 - 环形图（实例存到 window.appChartInstance 便于用 snapshot 更新）
        window.__pendingAppChartData = null;
        window.__needAppEnterAnim = false;
        window.__needCategoryEnterAnim = false;
        window.__appChartPrimed = false;
        window.__categoryChartPrimed = false;

        function playRotateScaleOnce(chart, durationMs) {
            durationMs = durationMs || 520;
            if (!chart) return;
            try {
                if (chart.__rotating) return;
                chart.__rotating = true;

                var oldAnim = chart.options.animation;
                var oldRotation = (chart.options.rotation !== undefined && chart.options.rotation !== null) ? chart.options.rotation : 0;
                var oldCirc = (chart.options.circumference !== undefined && chart.options.circumference !== null) ? chart.options.circumference : 360;
                var oldRadius = chart.options.radius !== undefined && chart.options.radius !== null ? chart.options.radius : '95%';
                var oldCutout = chart.options.cutout !== undefined && chart.options.cutout !== null ? chart.options.cutout : '60%';

                chart.options.animation = {
                    duration: durationMs,
                    easing: 'easeOutQuart',
                    animateRotate: true,
                    animateScale: true
                };

                chart.options.radius = '10%';
                chart.options.cutout = oldCutout;
                chart.update('none');

                requestAnimationFrame(function() {
                    try {
                        chart.options.radius = oldRadius;
                        chart.options.rotation = oldRotation + 360;
                        chart.options.circumference = oldCirc;
                        chart.update();
                    } catch (e) {}
                });

                setTimeout(function() {
                    try {
                        chart.options.animation = oldAnim;
                        chart.options.rotation = oldRotation;
                        chart.options.radius = oldRadius;
                        chart.options.cutout = oldCutout;
                        chart.options.circumference = oldCirc;
                        chart.__rotating = false;
                    } catch (e) {}
                }, durationMs + 80);
            } catch (e) {
                try { chart.__rotating = false; } catch (e2) {}
            }
        }

        function logChartDataOnce(tag, chart) {
            try {
                if (!chart || chart.__loggedOnce) return;
                chart.__loggedOnce = true;

                var labels = chart.data && chart.data.labels ? chart.data.labels : [];
                var data = chart.data && chart.data.datasets && chart.data.datasets[0] ? chart.data.datasets[0].data : [];
                var nums = (data || []).map(function(v) { return Number(v); });
                var bad = nums.map(function(n, i) { return { i: i, v: data[i], n: n, label: labels[i] }; })
                    .filter(function(x) { return !Number.isFinite(x.n) || x.n < 0; });

                var sum = nums.filter(Number.isFinite).reduce(function(a, b) { return a + b; }, 0);
                hardUiLog('chart_first_data', {
                    tag: tag,
                    n: nums.length,
                    sum: sum,
                    bad_cnt: bad.length,
                    bad: bad.slice(0, 5),
                    head: nums.slice(0, 8),
                    head_labels: labels.slice(0, 8)
                });
            } catch (e) {}
        }

        function initAppChart() {
            var pending = window.__pendingAppChartData;
            if (!pending) return;

            var labels = pending.labels || [];
            var values = pending.values || [];
            if (labels.length === 0) {
                labels = ['暂无'];
                values = [1];
            }
            var usedInit = [];
            var bg = labels.map(function(lbl, i) {
                var k = (window.appChartKeys && window.appChartKeys[i]) || lbl;
                var c = window.colorForKeyInContext ? window.colorForKeyInContext(k, 0.8, usedInit) : (window.colorForKey ? window.colorForKey(k, 0.8) : 'rgba(107, 114, 128, 0.8)');
                var solid = c.replace(/,\s*[\d.]+\s*\)\s*$/, ',1)');
                usedInit.push(solid);
                return c;
            });
            var borders = usedInit.slice();

            var canvas = document.getElementById('appChart');
            if (!canvas) return;
            var ctx = canvas.getContext('2d');
            var chart = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            data: values,
                            backgroundColor: bg,
                            borderColor: borders,
                            borderWidth: 1,
                            hoverBorderWidth: 1.2,
                            hoverBorderColor: 'rgba(255,255,255,0.28)',
                            hoverOffset: 18,
                            shadowBlur: 15,
                            shadowColor: 'rgba(0, 0, 0, 0.3)'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '72%',
                    spacing: 2,
                    interaction: { mode: 'nearest', intersect: true },
                    hover: { mode: 'nearest', intersect: true },
                    elements: {
                        arc: {
                            borderAlign: 'inner',
                            hoverBorderWidth: 1.2,
                            hoverBorderColor: 'rgba(255,255,255,0.28)'
                        }
                    },
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            backgroundColor: 'rgba(15, 23, 42, 0.9)',
                            titleColor: 'white',
                            bodyColor: 'rgba(255, 255, 255, 0.7)',
                            borderColor: 'rgba(255, 255, 255, 0.1)',
                            borderWidth: 1,
                            padding: 12,
                            boxPadding: 6,
                            usePointStyle: true,
                            callbacks: {
                                label: function(context) {
                                    const label = context.label || '';
                                    const valueSec = Number(context.raw) || 0;
                                    const totalSec = (context.dataset.data || []).reduce(function(a, b) { return a + (Number(b) || 0); }, 0) || 0;
                                    const percentage = totalSec > 0 ? Math.round(valueSec * 100 / totalSec) : 0;
                                    return `${label}: ${formatWorkTime(valueSec)} (${percentage}%)`;
                                }
                            }
                        }
                    },
                    animation: {
                        animateRotate: true,
                        animateScale: true,
                        duration: 1000,
                        easing: 'easeOutQuart'
                    },
                    onClick: function(ev, elements) {
                        try {
                            if (elements && elements.length && window.appChartKeys) {
                                var idx = elements[0].index;
                                var k = (idx >= 0 && idx < window.appChartKeys.length) ? window.appChartKeys[idx] : null;
                                if (k && typeof focusAppCardByKey === 'function') focusAppCardByKey(k);
                            }
                        } catch(e) {}
                    },
                    onHover: function(evt, activeEls) {
                        var k = null;
                        if (activeEls && activeEls.length && window.appChartKeys) {
                            var idx = activeEls[0].index;
                            k = (idx >= 0 && idx < window.appChartKeys.length) ? window.appChartKeys[idx] : null;
                        }
                        var ck = k ? canonicalKey(k) : null;
                        if (ck !== window.statsHighlightKey) {
                            window.statsHighlightKey = ck;
                            window.__hoverState = ck ? { chart: 'pie', key: ck, ts: Date.now() } : { chart: null, key: null, ts: 0 };
                            if (typeof applyStatsHighlightToTimeBars === 'function') applyStatsHighlightToTimeBars();
                        }
                    }
                }
            });
            window.appChartInstance = chart;
            window.__appChartPrimed = true;
            window.__needAppEnterAnim = false;
            setTimeout(function() {
                try {
                    var meta = window.appChartInstance.getDatasetMeta(0);
                    var n = (meta && meta.data) ? meta.data.length : 0;
                    hardUiLog('chart_meta_init', { canvasId: 'appChart', arc_count: n });
                } catch (e) {}
            }, 0);
        }

        // 无后端或请求失败时，左栏显示提示（避免一直「加载中」）
        function setLeftPanelNoDataOrError(message) {
            const listEl = document.getElementById('appListContainer');
            const totalEl = document.getElementById('appTotalTime');
            const titleEl = document.getElementById('appSummaryTitle');
            if (totalEl) totalEl.textContent = '0分钟';
            if (titleEl) titleEl.textContent = '今日 屏幕使用时间';
            if (listEl) listEl.innerHTML = '<p class="text-gray-500 text-sm py-4 text-center">' + (message || '暂无使用记录') + '</p>';
            if (window.appChartInstance) {
                window.appChartKeys = [];
                window.appChartInstance.data.labels = ['暂无'];
                window.appChartInstance.data.datasets[0].data = [1];
                window.appChartInstance.data.datasets[0].backgroundColor = ['rgba(107, 114, 128, 0.8)'];
                window.appChartInstance.data.datasets[0].borderColor = ['rgba(107, 114, 128, 1)'];
                window.appChartInstance.update('none');
            }
        }

        // 根据 snapshot 更新左侧应用面板（应用视图：饼图 + 总时长 + 列表）；日视图用当日，周/月用范围聚合
        function updateLeftPanelFromSnapshot(snap, opts) {
            opts = opts || {};
            var noAnim = opts.anim === false;
            if (snap && !snap.error) window.__lastSnapshot = snap;
            if (!snap || snap.error) {
                setLeftPanelNoDataOrError(snap && snap.error ? '连接后端失败，请通过 EyE Care 应用启动' : '暂无使用记录');
                return;
            }
            const rangeKey = snap.range_key || 'day';
            const isRange = (rangeKey === 'week' || rangeKey === 'month' || rangeKey === 'custom');
            const usage = isRange && snap.range_daily_usage
                ? (snap.range_daily_usage || {})
                : ((snap.vm && snap.vm.daily_usage) || {});

            const rangeStart = snap.range_start || '';
            const rangeEnd = snap.range_end || rangeStart;
            const localDate = (snap.vm && snap.vm.local_date) ? snap.vm.local_date : '';

            let dateLabel = localDate;
            if (rangeKey === 'day') {
                dateLabel = (localDate === localTodayStr()) ? '今日' : localDate;
            } else if (rangeKey === 'week') {
                // 本周日期范围
                var d = parseYMD(localDate) || new Date();
                var dayOfWeek = (d.getDay() + 6) % 7; // 0=周一
                var weekStart = new Date(d);
                weekStart.setDate(d.getDate() - dayOfWeek);
                var weekEnd = new Date(weekStart);
                weekEnd.setDate(weekStart.getDate() + 6);
                dateLabel = toMD(weekStart) + ' ~ ' + toMD(weekEnd);
            } else if (rangeKey === 'month') {
                // 本月日期范围
                var d = parseYMD(localDate) || new Date();
                var monthStart = new Date(d.getFullYear(), d.getMonth(), 1);
                var monthEnd = new Date(d.getFullYear(), d.getMonth() + 1, 0);
                dateLabel = toMD(monthStart) + ' ~ ' + toMD(monthEnd);
            } else if (rangeKey === 'custom') {
                // 自定义范围也去掉年份
                var startParts = (rangeStart || '').split('-');
                var endParts = (rangeEnd || '').split('-');
                var startMD = startParts.length >= 3 ? startParts[1] + '-' + startParts[2] : rangeStart;
                var endMD = endParts.length >= 3 ? endParts[1] + '-' + endParts[2] : rangeEnd;
                dateLabel = (rangeStart && rangeEnd) ? (startMD + ' ~ ' + endMD) : localDate;
            }

            const appPaths = snap.app_paths || {};
            const displayNames = snap.display_names || {};
            // 后端可能返回字符串数字，必须转成 Number，否则 reduce 会变成字符串拼接、totalSec 错乱，导致百分比算成 0
            let totalSec = Object.keys(usage).reduce(function(sum, key) { return sum + (Number(usage[key]) || 0); }, 0);
            if (rangeKey === 'day' && (snap.today_total_seconds !== undefined && snap.today_total_seconds !== null)) {
                totalSec = Number(snap.today_total_seconds) || 0;
            }
            const totalText = formatWorkTime(totalSec);
            const items = Object.keys(usage)
                .map(function(key) {
                    const sec = Number(usage[key]) || 0;
                    const pct = totalSec > 0 ? (100 * sec) / totalSec : 0;
                    let name = displayNames[key] || key;
                    if (name === key && appPaths[key]) {
                        const p = appPaths[key].replace(/\\/g, '/');
                        name = p.split('/').pop() || key;
                    }
                    if (name && name.toLowerCase().endsWith('.exe')) name = name.slice(0, -4);
                    return { name: name, key: key, seconds: sec, percent: pct, duration: formatWorkTime(sec) };
                })
                .sort(function(a, b) { return b.seconds - a.seconds; });

            const titleEl = document.getElementById('appSummaryTitle');
            const totalEl = document.getElementById('appTotalTime');
            const topLinesEl = document.getElementById('appTopLines');
            const listEl = document.getElementById('appListContainer');
            if (titleEl) titleEl.textContent = (dateLabel ? dateLabel + ' ' : '') + '屏幕使用时间';
            if (totalEl) totalEl.textContent = totalText;
            // 今日屏幕总用时文案已移除（左侧饼图区域）

            var appHashTop = buildItemsHash(items, totalSec, 5, function(it) { return it.key; });
            if (topLinesEl && topLinesEl.__hash !== appHashTop) {
                topLinesEl.__hash = appHashTop;
                topLinesEl.className = 'pie-top-lines space-y-1 text-sm';
                var usedAppTop = [];
                topLinesEl.innerHTML = items.slice(0, 5).map(function(it) {
                    var k = it.key || it.name;
                    var dotColor = window.colorForKeyInContext ? window.colorForKeyInContext(k, 1, usedAppTop) : (window.borderForKey ? window.borderForKey(k) : 'rgba(255,255,255,0.3)');
                    usedAppTop.push(dotColor);
                    var line = escapeHtml(it.name) + ' - ' + escapeHtml(it.duration) + ' ' + Math.round(it.percent) + '%';
                    return '<div class="pie-top-line"><span class="pie-dot" style="background:' + dotColor + '"></span><span class="pie-line-text">' + line + '</span></div>';
                }).join('') || '<span class="text-gray-500">暂无数据</span>';
            }

            var appHashList = buildItemsHash(items, totalSec, 50, function(it) { return it.key; });
            if (listEl && listEl.__hash !== appHashList) {
                listEl.__hash = appHashList;
                const iconBase = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
                var usedAppList = [];
                listEl.innerHTML = items.map(function(it) {
                    var key = it.key || it.name;
                    var color = window.colorForKeyInContext ? window.colorForKeyInContext(key, 0.8, usedAppList) : (window.colorForKey ? window.colorForKey(key, 0.8) : 'rgba(59,130,246,0.8)');
                    var solid = color.replace(/,\s*[\d.]+\s*\)\s*$/, ',1)');
                    usedAppList.push(solid);
                    var bgDim = color.replace(/,\s*[\d.]+\s*\)\s*$/, ',0.2)');
                    var borderColor = solid;
                    var iconUrl = iconBase + '/api/icon?app=' + encodeURIComponent(it.key);
                    return '<div class="app-card flex items-center justify-between py-2 px-2 panel-inner rounded border border-white/5 cursor-pointer hover:bg-dark-300/80 transition-colors" data-app="' + escapeHtml(it.name) + '" data-app-key="' + escapeHtml(it.key) + '">' +
                        '<div class="flex items-center min-w-0">' +
                        '<div class="w-8 h-8 rounded flex items-center justify-center mr-2 flex-shrink-0 overflow-hidden" style="background:' + bgDim + '">' +
                        '<img src="' + escapeHtml(iconUrl) + '" alt="" class="w-5 h-5 object-contain" onerror="this.style.display=\'none\';var n=this.nextElementSibling;if(n)n.style.display=\'inline\';">' +
                        '<i class="fa fa-desktop text-sm app-card-fallback-icon" style="color:' + borderColor + ';display:none;"></i>' +
                        '</div>' +
                        '<div class="min-w-0">' +
                        '<span class="font-medium text-sm block truncate">' + escapeHtml(it.name) + '</span>' +
                        '<span class="text-xs text-gray-400">' + it.duration + '</span>' +
                        '</div>' +
                        '</div>' +
                        '<div class="flex items-center flex-shrink-0 ml-2">' +
                        '<div class="w-16 h-1.5 bg-dark-300 rounded-full overflow-hidden mr-1.5">' +
                        '<div class="h-full rounded-full" style="width:' + it.percent + '%;background:' + borderColor + '"></div>' +
                        '</div>' +
                        '<span class="text-xs text-gray-400 w-7">' + Math.round(it.percent) + '%</span>' +
                        '</div>' +
                        '</div>';
                }).join('') || '<p class="text-gray-500 text-sm py-4 text-center">暂无使用记录</p>';
            }

            // 饼图只画用量 >0 的项，避免 0 导致 hover 时整圈异常
            var chartItems = items.filter(function(it) { return (Number(it.seconds) || 0) > 0; });
            window.appChartKeys = chartItems.map(function(it) { return it.key; });

            var labels = chartItems.map(function(it) { return it.name; });
            var data = chartItems.map(function(it) { return Number(it.seconds) || 0; });
            var usedApp = [];
            var bg = chartItems.map(function(it) {
                var c = window.colorForKeyInContext ? window.colorForKeyInContext(it.key, 0.8, usedApp) : (window.colorForKey ? window.colorForKey(it.key, 0.8) : 'rgba(107, 114, 128, 0.8)');
                var solid = c.replace(/,\s*[\d.]+\s*\)\s*$/, ',1)');
                usedApp.push(solid);
                return c;
            });
            var borders = usedApp.slice();
            if (labels.length === 0) {
                labels = ['暂无'];
                data = [1];
                bg = ['rgba(107, 114, 128, 0.8)'];
                borders = ['rgba(107, 114, 128, 1)'];
            }

            if (!window.appChartInstance) {
                window.__needAppEnterAnim = false;
                window.__pendingAppChartData = { labels: labels, values: data };
                initAppChart();
                stabilizeChart('appChart', function() { return window.appChartInstance; });
                return;
            }
            var chart = window.appChartInstance;
            chart.data.labels = labels;
            chart.data.datasets[0].data = data;
            chart.data.datasets[0].backgroundColor = bg;
            chart.data.datasets[0].borderColor = borders;
            if (window.replacePieGradients) window.replacePieGradients(chart);
            logChartDataOnce('appChart', chart);
            if (!window.__appChartPrimed) {
                window.__appChartPrimed = true;
                window.__needAppEnterAnim = false;
                chart.update();
                return;
            }
            if (!noAnim && window.__needAppEnterAnim) {
                window.__needAppEnterAnim = false;
                playRotateScaleOnce(chart, 520);
                return;
            }
            chart.update('none');
        }

        function escapeHtml(s) {
            if (s == null) return '';
            const div = document.createElement('div');
            div.textContent = s;
            return div.innerHTML;
        }

        function uiConfirm(text) {
            return new Promise(function(resolve) {
                var m = document.getElementById('confirmModal');
                var t = document.getElementById('confirmModalText');
                var ok = document.getElementById('confirmModalOk');
                var cancel = document.getElementById('confirmModalCancel');
                if (!m || !t || !ok || !cancel) return resolve(false);
                t.textContent = text || '';
                m.classList.remove('hidden');
                m.classList.add('flex');
                function cleanup(v) {
                    m.classList.add('hidden');
                    m.classList.remove('flex');
                    ok.removeEventListener('click', onOk);
                    cancel.removeEventListener('click', onCancel);
                    resolve(v);
                }
                function onOk() { cleanup(true); }
                function onCancel() { cleanup(false); }
                ok.addEventListener('click', onOk);
                cancel.addEventListener('click', onCancel);
            });
        }

        // 视图切换功能
        function initViewTabs() {
            // 主视图标签
            const categoryTab = document.getElementById('categoryTab');
            const appTab = document.getElementById('appTab');
            
            // 时间筛选标签
            const dayTab = document.getElementById('dayTab');
            const weekTab = document.getElementById('weekTab');
            const monthTab = document.getElementById('monthTab');
            
            // 防御性检查：确保元素存在
            if (!dayTab || !weekTab || !monthTab) {
                console.error('[ERROR] Time range tabs not found:', { dayTab, weekTab, monthTab });
                return; // 如果元素不存在，直接返回
            }
            
            // 视图元素
            const categoryView = document.getElementById('categoryView');
            const appView = document.getElementById('appView');
            
            // 当前选中的时间范围
            let currentTimeRange = 'day';
            
            // 主视图标签点击事件（分类 chart 延迟到此再 init，避免 display:none 时 0 尺寸初始化）
            categoryTab.addEventListener('click', () => {
                window.uiTransitioning = true;
                setActiveMainTab(categoryTab);
                showMainView(categoryView);
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        if (!window.categoryChartInstance) {
                            initCategoryChart();
                        } else {
                            try { window.categoryChartInstance.destroy(); } catch (e) {}
                            window.categoryChartInstance = null;
                            window.__categoryChartPrimed = false;
                            initCategoryChart();
                        }
                        stabilizeChart('categoryChart', () => window.categoryChartInstance);
                        updateDataByTimeRange(currentTimeRange);
                        requestImmediateRefresh('enter_category_view');
                        setTimeout(function() {
                            window.uiTransitioning = false;
                            if (window.pendingRefresh) {
                                window.pendingRefresh = false;
                                if (window.refreshNow) window.refreshNow('after_transition');
                            }
                        }, 520);
                    });
                });
            });
            
            appTab.addEventListener('click', () => {
                window.uiTransitioning = true;
                setActiveMainTab(appTab);
                showMainView(appView);
                requestAnimationFrame(() => {
                    if (window.appChartInstance) {
                        try { window.appChartInstance.destroy(); } catch (e) {}
                        window.appChartInstance = null;
                        window.__appChartPrimed = false;
                    }
                    var snap = window.__lastSnapshot;
                    if (snap && !snap.error) {
                        var rangeKey = snap.range_key || 'day';
                        var isRange = (rangeKey === 'week' || rangeKey === 'month' || rangeKey === 'custom');
                        var usage = isRange && snap.range_daily_usage ? (snap.range_daily_usage || {}) : ((snap.vm && snap.vm.daily_usage) || {});
                        var totalSec = Object.keys(usage).reduce(function(s, k) { return s + (Number(usage[k]) || 0); }, 0);
                        if (rangeKey === 'day' && snap.today_total_seconds != null) totalSec = Number(snap.today_total_seconds) || 0;
                        var displayNames = snap.display_names || {};
                        var appPaths = snap.app_paths || {};
                        var items = Object.keys(usage).map(function(key) {
                            var sec = Number(usage[key]) || 0;
                            var pct = totalSec > 0 ? (100 * sec) / totalSec : 0;
                            var name = displayNames[key] || key;
                            if (name === key && appPaths[key]) name = (appPaths[key].replace(/\\/g, '/').split('/').pop()) || key;
                            if (name && name.toLowerCase().endsWith('.exe')) name = name.slice(0, -4);
                            return { name: name, key: key, seconds: sec, percent: pct };
                        }).sort(function(a, b) { return b.seconds - a.seconds; });
                        var chartItems = items.filter(function(it) { return (Number(it.seconds) || 0) > 0; });
                        window.appChartKeys = chartItems.map(function(it) { return it.key; });
                        var labels = chartItems.map(function(it) { return it.name; });
                        var data = chartItems.map(function(it) { return Number(it.seconds) || 0; });
                        if (labels.length === 0) { labels = ['暂无']; data = [1]; }
                        window.__pendingAppChartData = { labels: labels, values: data };
                    } else {
                        window.__pendingAppChartData = { labels: ['暂无'], values: [1] };
                        window.appChartKeys = [];
                    }
                    initAppChart();
                    stabilizeChart('appChart', function() { return window.appChartInstance; });
                    updateDataByTimeRange(currentTimeRange);
                    requestImmediateRefresh('enter_app_view');
                    setTimeout(function() {
                        window.uiTransitioning = false;
                        if (window.pendingRefresh) {
                            window.pendingRefresh = false;
                            if (window.refreshNow) window.refreshNow('after_transition');
                        }
                    }, 520);
                });
            });
            
            // 时间筛选标签点击事件：与后端 range=day|week|month 联动
            // 点击日/周/月时强制刷新至本日/本周/本月数据
            dayTab.addEventListener('click', () => {
                setActiveTimeTab(dayTab);
                currentTimeRange = 'day';
                if (window.setViewRangeKey) window.setViewRangeKey('day');
                if (window.requestImmediateRefresh) window.requestImmediateRefresh('time_range_change');
                updateDataByTimeRange(currentTimeRange);
            });
            weekTab.addEventListener('click', () => {
                setActiveTimeTab(weekTab);
                currentTimeRange = 'week';
                if (window.setViewRangeKey) window.setViewRangeKey('week');
                if (window.requestImmediateRefresh) window.requestImmediateRefresh('time_range_change');
                updateDataByTimeRange(currentTimeRange);
            });
            monthTab.addEventListener('click', () => {
                setActiveTimeTab(monthTab);
                currentTimeRange = 'month';
                if (window.setViewRangeKey) window.setViewRangeKey('month');
                if (window.requestImmediateRefresh) window.requestImmediateRefresh('time_range_change');
                updateDataByTimeRange(currentTimeRange);
            });
            
            // 设置活动主视图标签
            function setActiveMainTab(activeTab) {
                const tabs = [categoryTab, appTab];
                tabs.forEach(tab => {
                    tab.classList.remove('tab-active');
                    tab.classList.add('tab-inactive');
                });
                activeTab.classList.remove('tab-inactive');
                activeTab.classList.add('tab-active');
            }
            
            // 设置活动时间筛选标签
            function setActiveTimeTab(activeTab) {
                const tabs = [dayTab, weekTab, monthTab];
                tabs.forEach(tab => {
                    tab.classList.remove('tab-active');
                    tab.classList.add('tab-inactive');
                });
                activeTab.classList.remove('tab-inactive');
                activeTab.classList.add('tab-active');
            }
            
            // 显示主视图
            function showMainView(activeView) {
                const views = [categoryView, appView];
                views.forEach(view => {
                    view.classList.add('hidden');
                    view.classList.remove('block', 'chart-view-enter');
                });
                activeView.classList.remove('hidden');
                activeView.classList.add('block');
                activeView.classList.add('chart-view-enter');
                setTimeout(function() { activeView.classList.remove('chart-view-enter'); }, 420);
            }
            
            // 时间范围切换时数据由 refreshLeftPanelForViewDate -> snapshot 驱动，此处不再写假数据
            function updateDataByTimeRange(timeRange) {
                // 数据已由 snapshot 的 range_daily_usage / range_usage_by_category 提供，无需覆盖
            }
        }
        
        // 日期选择功能
        function initDateSelector() {
            const prevDayBtn = document.getElementById('prevDay');
            const nextDayBtn = document.getElementById('nextDay');
            const currentDateEl = document.getElementById('currentDate');
            const calendarBtn = document.getElementById('calendarBtn');
            
            const today = new Date();
            let currentDate = new Date();

            // 月视图步进：加减 N 月并夹紧日期（如 1/31 +1 月 → 2/28）
            function addMonths(d, delta) {
                var y = d.getFullYear(), m = d.getMonth(), day = d.getDate();
                m += delta;
                while (m > 11) { y++; m -= 12; }
                while (m < 0) { y--; m += 12; }
                var lastDay = new Date(y, m + 1, 0).getDate();
                d.setFullYear(y, m, Math.min(day, lastDay));
            }
            
            // 更新日期显示（仅 day/custom 时用本地 currentDate；week/month 由 snapshot 回调更新）
            function updateDateDisplay() {
                var rk = window.getViewRangeKey ? window.getViewRangeKey() : 'day';
                if (rk === 'custom' && window.getCustomRange) {
                    var r = window.getCustomRange();
                    if (r && currentDateEl) { currentDateEl.textContent = r.start + ' ~ ' + r.end; }
                    return;
                }
                if (rk === 'week' || rk === 'month') return; // 等 snapshot 返回后由 updateTopDateFromSnapshot 更新
                const diffDays = Math.floor((currentDate - today) / (1000 * 60 * 60 * 24));
                if (diffDays === 0) {
                    currentDateEl.textContent = '今天';
                } else if (diffDays === -1) {
                    currentDateEl.textContent = '昨天';
                } else if (diffDays === 1) {
                    currentDateEl.textContent = '明天';
                } else {
                    const options = { month: 'short', day: 'numeric', weekday: 'short' };
                    currentDateEl.textContent = currentDate.toLocaleDateString('zh-CN', options);
                }
            }

            // 用 snapshot 的 range_start/range_end 刷新顶部日期（日/周/月切换后与后端一致）
            window.updateTopDateFromSnapshot = function(snap) {
                if (!snap || !currentDateEl) return;
                var rk = snap.range_key || 'day';
                var start = snap.range_start || (snap.vm && snap.vm.local_date);
                var end = snap.range_end || start;
                if (rk === 'day' && (snap.vm && snap.vm.local_date)) {
                    var d = snap.vm.local_date;
                    var todayStr = typeof localTodayStr === 'function' ? localTodayStr() : '';
                    var yesterday = new Date(); yesterday.setDate(yesterday.getDate() - 1);
                    var yesterdayStr = yesterday.getFullYear() + '-' + (yesterday.getMonth() + 1 < 10 ? '0' : '') + (yesterday.getMonth() + 1) + '-' + (yesterday.getDate() < 10 ? '0' : '') + yesterday.getDate();
                    var tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
                    var tomorrowStr = tomorrow.getFullYear() + '-' + (tomorrow.getMonth() + 1 < 10 ? '0' : '') + (tomorrow.getMonth() + 1) + '-' + (tomorrow.getDate() < 10 ? '0' : '') + tomorrow.getDate();
                    if (d === todayStr) currentDateEl.textContent = '今天';
                    else if (d === yesterdayStr) currentDateEl.textContent = '昨天';
                    else if (d === tomorrowStr) currentDateEl.textContent = '明天';
                    else currentDateEl.textContent = d;
                } else if (start && end) {
                    // 统一显示 YY-MM-DD ~ YY-MM-DD 格式（保持与日视图一致的日期格式）
                    var startParts = start.split('-');
                    var endParts = end.split('-');
                    // 取后两位作为年份 (如 2026 -> 26)
                    var startYY = startParts.length >= 1 && startParts[0].length >= 2 ? startParts[0].slice(-2) : (startParts[0] || '');
                    var endYY = endParts.length >= 1 && endParts[0].length >= 2 ? endParts[0].slice(-2) : (endParts[0] || '');
                var startMD = startParts.length >= 3 ? startParts[1] + '-' + startParts[2] : start;
                    var endMD = endParts.length >= 3 ? endParts[1] + '-' + endParts[2] : end;
                    currentDateEl.textContent = startYY + '-' + startMD + ' ~ ' + endYY + '-' + endMD;
                }
            };
            
            window.getViewDateStr = function() {
                const y = currentDate.getFullYear(), m = currentDate.getMonth() + 1, d = currentDate.getDate();
                return y + '-' + (m < 10 ? '0' : '') + m + '-' + (d < 10 ? '0' : '') + d;
            };
            // 暴露 currentDate 和 updateDateDisplay 到 window 供外部调用（如日周月切换）
            window.currentDate = currentDate;
            window._viewRangeKey = window._viewRangeKey || 'day'; // day/week/month/custom
            window._customRangeStart = null;
            window._customRangeEnd = null;

            function updatePrevNextButtonState() {
                var isCustom = (window.getViewRangeKey ? window.getViewRangeKey() : 'day') === 'custom';
                if (prevDayBtn) prevDayBtn.disabled = isCustom;
                if (nextDayBtn) nextDayBtn.disabled = isCustom;
            }

            window.setViewRangeKey = function(k) {
                window._viewRangeKey = (k === 'week' || k === 'month' || k === 'custom') ? k : 'day';
                updatePrevNextButtonState();
            };
            window.getViewRangeKey = function() { return window._viewRangeKey || 'day'; };

            window.setCustomRange = function(s, e) {
                window._customRangeStart = s || null;
                window._customRangeEnd = e || null;
            };
            window.getCustomRange = function() {
                if (window.getViewRangeKey() !== 'custom') return null;
                if (!window._customRangeStart || !window._customRangeEnd) return null;
                return { start: window._customRangeStart, end: window._customRangeEnd };
            };

            function refreshWithView() {
                if (window.refreshLeftPanelForViewDate) window.refreshLeftPanelForViewDate();
            }

            updateDateDisplay();
            // 暴露 updateDateDisplay 供外部调用
            window.updateDateDisplay = updateDateDisplay;
            updatePrevNextButtonState();

            prevDayBtn.addEventListener('click', () => {
                var rk = window.getViewRangeKey ? window.getViewRangeKey() : 'day';
                if (rk === 'custom') return;
                if (rk === 'day') currentDate.setDate(currentDate.getDate() - 1);
                else if (rk === 'week') currentDate.setDate(currentDate.getDate() - 7);
                else if (rk === 'month') addMonths(currentDate, -1);
                updateDateDisplay();
                refreshWithView();
            });
            nextDayBtn.addEventListener('click', () => {
                var rk = window.getViewRangeKey ? window.getViewRangeKey() : 'day';
                if (rk === 'custom') return;
                if (rk === 'day') currentDate.setDate(currentDate.getDate() + 1);
                else if (rk === 'week') currentDate.setDate(currentDate.getDate() + 7);
                else if (rk === 'month') addMonths(currentDate, 1);
                updateDateDisplay();
                refreshWithView();
            });

            // 双排日历 + 可选范围
            (function() {
                var modal = document.getElementById('calendarModal');
                var calMonth1 = document.getElementById('calMonth1');
                var calMonth2 = document.getElementById('calMonth2');
                var calMonth1Title = document.getElementById('calMonth1Title');
                var calMonth2Title = document.getElementById('calMonth2Title');
                var calPrevMonth = document.getElementById('calPrevMonth');
                var calNextMonth = document.getElementById('calNextMonth');
                var rangeHint = document.getElementById('calendarRangeHint');
                var calStart = null, calEnd = null;
                var calViewYear = 0, calViewMonth = 0; // 左月；右月为同一年下一月

                var monthDataSet = {};      // {"YYYY-MM-DD": true}
                var monthDataCache = {};    // {"YYYY-M": {set:{}, ts:123}}
                var monthReqId = 0;         // 乱序保护

                // 单排：隐藏第二个月盒子（右箭头已移到左月标题行）
                try {
                    var calMonth2Box = document.getElementById('calMonth2Box');
                    if (calMonth2Box) calMonth2Box.style.display = 'none';
                } catch (e) {}

                function _cacheKey(y, m0) { // m0: 0..11
                    return y + "-" + (m0 + 1);
                }
                function fetchMonthData(year, month0) {
                    var key = _cacheKey(year, month0);

                    if (monthDataCache[key] && monthDataCache[key].set) {
                        monthDataSet = monthDataCache[key].set;
                        return Promise.resolve();
                    }

                    monthReqId += 1;
                    var rid = monthReqId;

                    var base = window.location.origin;
                    var url = base + "/api/calendar_month?year=" + year + "&month=" + (month0 + 1);

                    return fetch(url)
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            if (rid !== monthReqId) return; // 乱序：丢弃旧响应

                            var set = {};
                            var arr = (data && data.days_with_data) ? data.days_with_data : [];
                            for (var i = 0; i < arr.length; i++) set[arr[i]] = true;

                            monthDataSet = set;
                            monthDataCache[key] = { set: set, ts: Date.now() };
                        })
                        .catch(function() {
                            if (rid !== monthReqId) return;
                            monthDataSet = {};
                        });
                }

                function toYMD(d) {
                    var y = d.getFullYear(), m = d.getMonth() + 1, day = d.getDate();
                    return y + '-' + (m < 10 ? '0' : '') + m + '-' + (day < 10 ? '0' : '') + day;
                }
                function isSameDay(a, b) {
                    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
                }
                function parseYMD(s) {
                    var parts = (s || '').split('-');
                    if (parts.length !== 3) return null;
                    var d = new Date(parseInt(parts[0],10), parseInt(parts[1],10)-1, parseInt(parts[2],10));
                    return isNaN(d.getTime()) ? null : d;
                }

                function renderMonth(container, year, month, isLeft) {
                    var first = new Date(year, month, 1);
                    var last = new Date(year, month + 1, 0);
                    var startPad = (first.getDay() + 6) % 7;
                    var today = new Date();
                    var html = '<div class="cal-cell wday">一</div><div class="cal-cell wday">二</div><div class="cal-cell wday">三</div><div class="cal-cell wday">四</div><div class="cal-cell wday">五</div><div class="cal-cell wday">六</div><div class="cal-cell wday">日</div>';
                    for (var i = 0; i < startPad; i++) {
                        var prev = new Date(year, month, -startPad + i + 1);
                        var cls = 'cal-cell other-month';
                        var dStr = toYMD(prev);
                        if (calStart && toYMD(calStart) === dStr) cls += ' selected';
                        else if (calStart && calEnd) {
                            var t = prev.getTime();
                            if (t >= Math.min(calStart.getTime(), calEnd.getTime()) && t <= Math.max(calStart.getTime(), calEnd.getTime())) cls += ' in-range';
                        }
                        if (isSameDay(prev, today)) cls += ' today';
                        html += '<div class="' + cls + '" data-date="' + dStr + '">' + prev.getDate() + '</div>';
                    }
                    for (var d = 1; d <= last.getDate(); d++) {
                        var cellDate = new Date(year, month, d);
                        var dStr = toYMD(cellDate);
                        var cls = 'cal-cell';
                        if (cellDate.getMonth() !== month) cls += ' other-month';
                        if (cellDate.getMonth() === month && !monthDataSet[dStr]) cls += ' no-data';
                        if (calStart && toYMD(calStart) === dStr) cls += ' selected';
                        else if (calEnd && toYMD(calEnd) === dStr) cls += ' selected';
                        else if (calStart && calEnd) {
                            var t = cellDate.getTime();
                            if (t >= Math.min(calStart.getTime(), calEnd.getTime()) && t <= Math.max(calStart.getTime(), calEnd.getTime())) cls += ' in-range';
                        }
                        if (isSameDay(cellDate, today)) cls += ' today';
                        html += '<div class="' + cls + '" data-date="' + dStr + '">' + d + '</div>';
                    }
                    var totalCells = 7 * 6;
                    var filled = startPad + last.getDate();
                    for (var i = filled; i < totalCells; i++) {
                        var next = new Date(year, month + 1, i - filled + 1);
                        var dStr = toYMD(next);
                        var cls = 'cal-cell other-month';
                        if (calStart && toYMD(calStart) === dStr) cls += ' selected';
                        else if (calStart && calEnd) {
                            var t = next.getTime();
                            if (t >= Math.min(calStart.getTime(), calEnd.getTime()) && t <= Math.max(calStart.getTime(), calEnd.getTime())) cls += ' in-range';
                        }
                        if (isSameDay(next, today)) cls += ' today';
                        html += '<div class="' + cls + '" data-date="' + dStr + '">' + next.getDate() + '</div>';
                    }
                    container.innerHTML = html;
                }

                function handleCalCellClick(e) {
                    var t = e.target;
                    if (t && t.nodeType !== 1) t = t.parentElement;
                    var el = (t && t.closest) ? t.closest('.cal-cell') : t;
                    if (!el || !el.classList || el.classList.contains('wday')) return;
                    var dStr = el.getAttribute('data-date');
                    if (!dStr) return;
                    var d = parseYMD(dStr);
                    if (!d) return;
                    if (!calStart || (calStart && calEnd)) {
                        calStart = d;
                        calEnd = null;
                        // 已选择单天时显示具体日期，不再显示"已选开始"
                        rangeHint.textContent = '已选择 ' + dStr;
                    } else {
                        calEnd = d;
                        if (calEnd.getTime() < calStart.getTime()) { var t = calStart; calStart = calEnd; calEnd = t; }
                        rangeHint.textContent = '已选范围：' + toYMD(calStart) + ' 至 ' + toYMD(calEnd);
                    }
                    renderMonth(calMonth1, calViewYear, calViewMonth, true);
                    // 选择开始日期后禁用左右箭头（待选结束日期时不能切换月份）
                    calPrevMonth.disabled = !!calStart && !calEnd;
                    calNextMonth.disabled = !!calStart && !calEnd;
                    // 直接设置样式，不依赖 Tailwind 类
                    if (!!calStart && !calEnd) {
                        calPrevMonth.style.opacity = '0.5';
                        calPrevMonth.style.cursor = 'not-allowed';
                        calNextMonth.style.opacity = '0.5';
                        calNextMonth.style.cursor = 'not-allowed';
                    } else {
                        calPrevMonth.style.opacity = '';
                        calPrevMonth.style.cursor = '';
                        calNextMonth.style.opacity = '';
                        calNextMonth.style.cursor = '';
                    }
                }

                function openCalendar() {
                    var viewStr = window.getViewDateStr();
                    var viewDate = parseYMD(viewStr) || new Date();
                    calViewYear = viewDate.getFullYear();
                    calViewMonth = viewDate.getMonth();
                    // 不自动点选日期，等待用户选择
                    calStart = null;
                    calEnd = null;
                    rangeHint.textContent = '选开始→再选结束（同天即单日）';
                    calMonth1Title.textContent = calViewYear + ' 年 ' + (calViewMonth + 1) + ' 月';
                    calMonth2Title.textContent = calViewYear + ' 年 ' + (calViewMonth + 2) + ' 月';
                    if (calViewMonth === 11) calMonth2Title.textContent = (calViewYear + 1) + ' 年 1 月';
                    // 重置箭头按钮状态
                    calPrevMonth.disabled = false;
                    calNextMonth.disabled = false;
                    calPrevMonth.style.opacity = '';
                    calPrevMonth.style.cursor = '';
                    calNextMonth.style.opacity = '';
                    calNextMonth.style.cursor = '';
                    fetchMonthData(calViewYear, calViewMonth).then(function() {
                        renderMonth(calMonth1, calViewYear, calViewMonth, true);
                        renderMonth(calMonth2, calViewYear, calViewMonth + 1, false);
                    });
                    modal.style.display = 'flex';
                }
                function closeCalendar() {
                    modal.style.display = 'none';
                }
                function confirmCalendar() {
                    if (!calStart) { closeCalendar(); return; }

                    // 单日（或起止同日）：保持当前视图（日/周/月），仅以选中日为锚点刷新
                    if (!calEnd || toYMD(calStart) === toYMD(calEnd)) {
                        currentDate.setFullYear(calStart.getFullYear(), calStart.getMonth(), calStart.getDate());
                        updateDateDisplay();
                        if (window.requestImmediateRefresh) window.requestImmediateRefresh('calendar_change');
                        closeCalendar();
                        return;
                    }

                    // 范围
                    var s = toYMD(calStart);
                    var e = toYMD(calEnd);
                    if (e < s) { var t = s; s = e; e = t; }

                    if (window.setViewRangeKey) window.setViewRangeKey('custom');
                    if (window.setCustomRange) window.setCustomRange(s, e);

                    // 锚点给 end，方便“上一天/下一天”逻辑
                    currentDate.setFullYear(calEnd.getFullYear(), calEnd.getMonth(), calEnd.getDate());

                    var el = document.getElementById('currentDate');
                    if (el) el.textContent = s + ' ~ ' + e;

                    if (window.requestImmediateRefresh) window.requestImmediateRefresh('calendar_change');
                    closeCalendar();
                }

                var calendarPanel = document.getElementById('calendarPickerPanel');
                if (calendarPanel) calendarPanel.addEventListener('click', handleCalCellClick);
                calendarBtn.addEventListener('click', openCalendar);
                document.getElementById('calendarModalClose').addEventListener('click', closeCalendar);
                document.getElementById('calendarModalCancel').addEventListener('click', closeCalendar);
                document.getElementById('calendarModalConfirm').addEventListener('click', confirmCalendar);
                calPrevMonth.addEventListener('click', function() {
                    if (calPrevMonth.disabled) return;
                    calViewMonth--;
                    if (calViewMonth < 0) { calViewYear--; calViewMonth = 11; }
                    calMonth1Title.textContent = calViewYear + ' 年 ' + (calViewMonth + 1) + ' 月';
                    calMonth2Title.textContent = calViewYear + ' 年 ' + (calViewMonth + 2) + ' 月';
                    if (calViewMonth === 11) calMonth2Title.textContent = (calViewYear + 1) + ' 年 1 月';
                    fetchMonthData(calViewYear, calViewMonth).then(function() {
                        renderMonth(calMonth1, calViewYear, calViewMonth, true);
                        renderMonth(calMonth2, calViewYear, calViewMonth + 1, false);
                    });
                });
                calNextMonth.addEventListener('click', function() {
                    if (calNextMonth.disabled) return;
                    calViewMonth++;
                    if (calViewMonth > 11) { calViewYear++; calViewMonth = 0; }
                    calMonth1Title.textContent = calViewYear + ' 年 ' + (calViewMonth + 1) + ' 月';
                    calMonth2Title.textContent = calViewYear + ' 年 ' + (calViewMonth + 2) + ' 月';
                    if (calViewMonth === 11) calMonth2Title.textContent = (calViewYear + 1) + ' 年 1 月';
                    fetchMonthData(calViewYear, calViewMonth).then(function() {
                        renderMonth(calMonth1, calViewYear, calViewMonth, true);
                        renderMonth(calMonth2, calViewYear, calViewMonth + 1, false);
                    });
                });
            })();
        }
        
        // 休息提醒模态框功能
        // 勿扰模式按钮：HTTP /api/snapshot 取状态，/api/dnd 设置
        function initDndButton() {
            const btn = document.getElementById('dndBtn');
            if (!btn) return;
            var base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
            function setDndUi(isDnd) {
                btn.setAttribute('data-dnd', isDnd ? 'true' : 'false');
                btn.textContent = isDnd ? '取消勿扰' : '勿扰模式';
            }
            if (typeof window.fetchSnapshot === 'function') {
                window.fetchSnapshot({}).then(function(result) {
                    var s = result && result.data !== undefined ? result.data : result;
                    if (s && !s.error && s.state) setDndUi(!!s.state.is_dnd);
                }).catch(function() {});
            }
            btn.addEventListener('click', function() {
                const isDnd = btn.getAttribute('data-dnd') === 'true';
                const nextDnd = !isDnd;
                fetch(base + '/api/dnd', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ on: nextDnd })
                }).then(function(r) { return r.json(); }).then(function(data) {
                    if (data && !data.error) setDndUi(!!data.dnd);
                    else setDndUi(nextDnd);
                }).catch(function() { setDndUi(nextDnd); });
            });
        }

        // 从当前「休息时长」输入与单位得到秒数（供日志等使用）。后端实际执行时最少 5 秒，此处与之一致。
        function getRestDurationSeconds() {
            const input = document.getElementById('restDurationInput');
            const unit = document.getElementById('restDurationUnit');
            if (!input || !unit) return 20;
            const val = parseInt(input.value, 10) || (unit.value === 'min' ? 1 : 5);
            return unit.value === 'min' ? Math.max(1, val) * 60 : Math.max(5, val);
        }

        // 主界面「立即休息」：仅 /api/rest/start 成功时开遮罩，失败则提示
        function initRestModal() {
            const startRestBtn = document.getElementById('startRestBtn');
            if (!startRestBtn) return;
            function triggerRestOverlay() {
                if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.rest_show_overlay === 'function') {
                    try { window.pywebview.api.rest_show_overlay(); } catch (e) {}
                }
            }
            window.restShowOverlay = triggerRestOverlay;
            function showRestStartFail() {
                try { if (window.console && typeof window.console.warn === 'function') window.console.warn('rest/start failed'); } catch (e) {}
                try { if (window.postDiag) window.postDiag('rest_start_fail', {}); } catch (e) {}
            }
            window.ui = window.ui || {};
            window.ui.restStart = function() {
                var base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
                if (!base || base === 'null') base = (window.location.protocol || 'http:') + '//' + (window.location.host || '');
                fetch(base + '/api/rest/start', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
                    .then(function(r) { return r.json().then(function(data) { return { status: r.status, data: data }; }); })
                    .then(function(res) {
                        if (res.data && res.data.ok && window.restShowOverlay) { window.restShowOverlay(); return; }
                        if (res.status === 409 && res.data && res.data.code === 'rest_locked') return;
                        showRestStartFail();
                    })
                    .catch(function() { showRestStartFail(); });
            };
            startRestBtn.addEventListener('click', () => {
                if (startRestBtn.disabled) return;
                var base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
                if (!base || base === 'null') base = (window.location.protocol || 'http:') + '//' + (window.location.host || '');
                fetch(base + '/api/rest/start', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
                    .then(function(r) {
                        return r.json().then(function(data) { return { status: r.status, data: data }; });
                    })
                    .then(function(res) {
                        if (res.data && res.data.ok) { triggerRestOverlay(); return; }
                        if (res.status === 409 && res.data && res.data.code === 'rest_locked') {
                            var sec = Math.ceil((res.data.unlock_in_ms || 0) / 1000);
                            try { if (window.console && window.console.warn) window.console.warn('rest_locked, unlock in', sec, 's'); } catch (e) {}
                            return;
                        }
                        showRestStartFail();
                    })
                    .catch(function() { showRestStartFail(); });
            });
        }

        // 休息提醒间隔/时长：从后端加载、加减与输入时保存；主界面「每 X 分钟提醒，休息 Y 秒」随配置更新
        function initRestSettings() {
            const base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
            const intervalInput = document.getElementById('restIntervalInput');
            const intervalMinus = document.getElementById('restIntervalMinus');
            const intervalPlus = document.getElementById('restIntervalPlus');
            const durationInput = document.getElementById('restDurationInput');
            const durationUnit = document.getElementById('restDurationUnit');
            const durationMinus = document.getElementById('restDurationMinus');
            const durationPlus = document.getElementById('restDurationPlus');
            const restStatusText = document.getElementById('restStatusText');
            const restDurationText = document.getElementById('restDurationText');

            function applyRestStatusText(workMin, restSec, unit) {
                var restStr = unit === 'min' ? (Math.round(restSec / 60) + ' 分钟') : (restSec + ' 秒');
                if (restStatusText) restStatusText.textContent = '每 ' + workMin + ' 分钟';
                if (restDurationText) restDurationText.textContent = restStr;
            }

            var REST_DURATION_MIN_SEC = 5;
            function loadConfig() {
                fetch(base + '/api/config').then(function(r) { return r.json(); }).then(function(data) {
                    if (data.error) return;
                    const c = data.config || {};
                    var workMin = Math.max(1, parseInt(c.reminder_work_minutes, 10) || 20);
                    var unit = (c.reminder_rest_unit === 'min' || c.reminder_rest_unit === 'sec') ? c.reminder_rest_unit : 'sec';
                    var restSec = parseInt(c.reminder_rest_seconds, 10) || 20;
                    if (unit === 'sec') restSec = Math.max(REST_DURATION_MIN_SEC, restSec);
                    else restSec = Math.max(60, restSec);
                    if (intervalInput) intervalInput.value = workMin;
                    if (durationUnit) durationUnit.value = unit;
                    if (durationInput) {
                        if (unit === 'min') durationInput.value = Math.max(1, Math.min(120, Math.round(restSec / 60)));
                        else durationInput.value = Math.max(REST_DURATION_MIN_SEC, restSec);
                    }
                    if (durationInput && durationUnit) {
                        durationInput.min = unit === 'sec' ? REST_DURATION_MIN_SEC : 1;
                        durationInput.max = unit === 'min' ? 120 : 3600;
                    }
                    applyRestStatusText(workMin, restSec, unit);
                }).catch(function() {});
            }

            function saveConfig(payload) {
                fetch(base + '/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).catch(function() {});
            }

            function applyIntervalDelta(delta) {
                if (!intervalInput) return;
                const v = Math.max(1, Math.min(600, (parseInt(intervalInput.value, 10) || 20) + delta));
                intervalInput.value = v;
                saveConfig({ reminder_work_minutes: v });
                var restSec = durationInput && durationUnit ? (durationUnit.value === 'min' ? (parseInt(durationInput.value, 10) || 1) * 60 : (parseInt(durationInput.value, 10) || 20)) : 20;
                applyRestStatusText(v, restSec, durationUnit ? durationUnit.value : 'sec');
            }
            function applyDurationDelta(delta) {
                if (!durationInput || !durationUnit) return;
                const isMin = durationUnit.value === 'min';
                const minVal = isMin ? 1 : REST_DURATION_MIN_SEC;
                const maxVal = isMin ? 120 : 3600;
                const v = Math.max(minVal, Math.min(maxVal, (parseInt(durationInput.value, 10) || (isMin ? 1 : REST_DURATION_MIN_SEC)) + delta));
                durationInput.value = v;
                durationInput.min = minVal;
                durationInput.max = maxVal;
                const restSec = isMin ? v * 60 : v;
                saveConfig({ reminder_rest_seconds: restSec, reminder_rest_unit: durationUnit.value });
                var workMin = intervalInput ? (parseInt(intervalInput.value, 10) || 20) : 20;
                applyRestStatusText(workMin, restSec, durationUnit.value);
            }

            if (intervalMinus) intervalMinus.addEventListener('click', function() { applyIntervalDelta(-1); });
            if (intervalPlus) intervalPlus.addEventListener('click', function() { applyIntervalDelta(1); });
            if (intervalInput) intervalInput.addEventListener('change', function() {
                const v = Math.max(1, Math.min(600, parseInt(intervalInput.value, 10) || 20));
                intervalInput.value = v;
                saveConfig({ reminder_work_minutes: v });
                var restSec = durationInput && durationUnit ? (durationUnit.value === 'min' ? (parseInt(durationInput.value, 10) || 1) * 60 : (parseInt(durationInput.value, 10) || 20)) : 20;
                applyRestStatusText(v, restSec, durationUnit ? durationUnit.value : 'sec');
            });
            if (durationMinus) durationMinus.addEventListener('click', function() { applyDurationDelta(-1); });
            if (durationPlus) durationPlus.addEventListener('click', function() { applyDurationDelta(1); });
            if (durationInput) durationInput.addEventListener('change', function() {
                if (!durationUnit) return;
                const isMin = durationUnit.value === 'min';
                const minVal = isMin ? 1 : REST_DURATION_MIN_SEC;
                const maxVal = isMin ? 120 : 3600;
                const v = Math.max(minVal, Math.min(maxVal, parseInt(durationInput.value, 10) || (isMin ? 1 : REST_DURATION_MIN_SEC)));
                durationInput.value = v;
                durationInput.min = minVal;
                const restSec = isMin ? v * 60 : v;
                saveConfig({ reminder_rest_seconds: restSec, reminder_rest_unit: durationUnit.value });
                var workMin = intervalInput ? (parseInt(intervalInput.value, 10) || 20) : 20;
                applyRestStatusText(workMin, restSec, durationUnit.value);
            });
            if (durationUnit) durationUnit.addEventListener('change', function() {
                const isMin = durationUnit.value === 'min';
                if (!durationInput) return;
                const cur = parseInt(durationInput.value, 10) || (isMin ? 1 : REST_DURATION_MIN_SEC);
                if (isMin) { durationInput.value = Math.max(1, Math.round(cur / 60)); durationInput.min = 1; durationInput.max = 120; }
                else { durationInput.value = Math.max(REST_DURATION_MIN_SEC, cur * 60); durationInput.min = REST_DURATION_MIN_SEC; durationInput.max = 3600; }
                saveConfig({ reminder_rest_seconds: getRestDurationSeconds(), reminder_rest_unit: durationUnit.value });
                var workMin = intervalInput ? (parseInt(intervalInput.value, 10) || 20) : 20;
                var restSec = getRestDurationSeconds ? getRestDurationSeconds() : 20;
                applyRestStatusText(workMin, restSec, durationUnit.value);
            });

            loadConfig();
            window.refreshRestStatusFromConfig = loadConfig;
        }
        
        // 蓝光过滤（护眼模式已移至设置页，此处保留空实现）
        function initBlueLightToggle() {
            const el = document.getElementById('bluelight');
            if (el) el.addEventListener('change', function() {
                document.body.classList.toggle('blue-light-filter', this.checked);
            });
        }
        
        // 数据/设置导入导出：先弹小窗选择类型，再调对应 API
        function initDataImportExport() {
            const importDataBtn = document.getElementById('importDataBtn');
            const exportDataBtn = document.getElementById('exportDataBtn');
            const choiceModal = document.getElementById('importExportChoiceModal');
            const choiceTitle = document.getElementById('importExportChoiceTitle');
            const choiceBtn1 = document.getElementById('importExportChoiceBtn1');
            const choiceBtn2 = document.getElementById('importExportChoiceBtn2');
            const choiceClose = document.getElementById('importExportChoiceClose');

            function hideChoiceModal() {
                choiceModal.classList.add('hidden');
                choiceModal.classList.remove('flex');
            }

            if (choiceClose) choiceClose.addEventListener('click', hideChoiceModal);

            function showChoiceModal(title, label1, label2, onChoose1, onChoose2) {
                choiceTitle.textContent = title;
                choiceBtn1.textContent = label1;
                choiceBtn2.textContent = label2;
                choiceBtn1.onclick = function() {
                    hideChoiceModal();
                    if (typeof onChoose1 === 'function') onChoose1();
                };
                choiceBtn2.onclick = function() {
                    hideChoiceModal();
                    if (typeof onChoose2 === 'function') onChoose2();
                };
                choiceModal.classList.remove('hidden');
                choiceModal.classList.add('flex');
            }

            exportDataBtn.addEventListener('click', () => {
                showChoiceModal('请选择导出类型', '导出数据', '导出设置', doExportData, doExportSettings);
            });

            importDataBtn.addEventListener('click', () => {
                showChoiceModal('请选择导入类型', '导入数据', '导入设置', doImportData, doImportSettings);
            });

            async function doExportData() {
                try {
                    const r = await window.pywebview.api.export_all();
                    if (!r || r.status === 'cancel') return;
                    if (r.status !== 'ok') {
                        alert('导出失败：' + (r.error || 'unknown'));
                        return;
                    }
                    alert('数据导出成功！\n' + r.path);
                } catch (e) {
                    alert('导出失败：' + (e && e.message ? e.message : String(e)));
                }
            }

            async function doExportSettings() {
                try {
                    const r = await window.pywebview.api.export_settings();
                    if (!r || r.status === 'cancel') return;
                    if (r.status !== 'ok') {
                        alert('导出设置失败：' + (r.error || 'unknown'));
                        return;
                    }
                    alert('设置导出成功！\n' + r.path);
                } catch (e) {
                    alert('导出设置失败：' + (e && e.message ? e.message : String(e)));
                }
            }

            async function doImportData() {
                try {
                    const r = await window.pywebview.api.import_all();
                    if (!r || r.status === 'cancel') return;
                    if (r.status !== 'ok') {
                        alert('导入失败：' + (r.error || 'unknown'));
                        return;
                    }
                    alert('导入完成！\n' + r.path);
                    if (typeof window.refreshNow === 'function') window.refreshNow('import_done');
                } catch (e) {
                    alert('导入失败：' + (e && e.message ? e.message : String(e)));
                }
            }

            async function doImportSettings() {
                try {
                    const r = await window.pywebview.api.import_settings();
                    if (!r || r.status === 'cancel') return;
                    if (r.status !== 'ok') {
                        alert('导入设置失败：' + (r.error || 'unknown'));
                        return;
                    }
                    alert('设置已导入！\n' + r.path);
                } catch (e) {
                    alert('导入设置失败：' + (e && e.message ? e.message : String(e)));
                }
            }
        }
        

        // 图表点击 -> 跳转到对应应用卡片并高亮（柔和高亮，类似 QQ hover）
        function focusAppCardByKey(appKey) {
            try {
                var listEl = document.getElementById('appListContainer');
                if (!listEl) return;
                var card = listEl.querySelector('.app-card[data-app-key="' + CSS.escape(appKey) + '"]');
                if (!card) return;
                // 先滚动到可见区域
                try { card.scrollIntoView({behavior: 'smooth', block: 'center'}); } catch(e) { card.scrollIntoView(true); }
                // 高亮效果
                var prev = listEl.querySelector('.app-card.card-focus');
                if (prev) prev.classList.remove('card-focus');
                card.classList.add('card-focus');
                window.setTimeout(function(){ try { card.classList.remove('card-focus'); } catch(e){} }, 1200);
            } catch(e) {}
        }
        // 应用详情模态框功能
        function initAppDetailModal() {
            const appListContainer = document.getElementById('appListContainer');
            const appDetailModal = document.getElementById('appDetailModal');
            const closeAppDetailModal = document.getElementById('closeAppDetailModal');
            const cancelAppDetail = document.getElementById('cancelAppDetail');
            const saveAppDetail = document.getElementById('saveAppDetail');
            const appDetailTitle = document.getElementById('appDetailTitle');
            
            let currentAppChart = null;
            
            window.__currentAppKeyInDetail = null;
            var appDetailCategoryList = [];
            var baseUrl = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';

            function setAppDetailFormFromJson(json) {
                if (!json) return;
                appDetailTitle.textContent = json.display_name || window.__currentAppKeyInDetail || '';
                var cat = (json.category || '其他').trim() || '其他';
                var catSelect = document.getElementById('appCategorySelect');
                var catLabel = document.getElementById('appCategoryLabel');
                if (catSelect) catSelect.value = cat;
                if (catLabel) catLabel.textContent = cat;
                var dispInput = document.getElementById('appDisplayNameInput');
                if (dispInput) dispInput.value = (json.display_name_override !== undefined ? json.display_name_override : json.display_name || '').trim();
                var autoDnd = document.getElementById('appAutoDndCheckbox');
                if (autoDnd) autoDnd.checked = !!json.auto_dnd_on_focus;
            }

            function renderCategoryOptions() {
                var container = document.getElementById('appCategoryOptions');
                if (!container) return;
                container.innerHTML = appDetailCategoryList.map(function(name) {
                    var canDelete = name !== '其他';
                    return '<div class="flex items-center justify-between px-3 py-2 hover:bg-dark-300/80 cursor-pointer group category-opt" data-name="' + escapeHtml(name) + '">' +
                        '<span>' + escapeHtml(name) + '</span>' +
                        (canDelete ? '<button type="button" class="category-del opacity-0 group-hover:opacity-100 text-red-400 hover:bg-red-500/20 p-1 rounded" data-name="' + escapeHtml(name) + '" title="删除该分类"><i class="fa fa-minus text-xs"></i></button>' : '') +
                        '</div>';
                }).join('');
                container.querySelectorAll('.category-opt').forEach(function(el) {
                    var name = el.getAttribute('data-name');
                    el.addEventListener('click', function(e) {
                        if (e.target.closest('.category-del')) return;
                        document.getElementById('appCategorySelect').value = name;
                        document.getElementById('appCategoryLabel').textContent = name;
                        document.getElementById('appCategoryPanel').classList.add('hidden');
                    });
                });
                container.querySelectorAll('.category-del').forEach(function(btn) {
                    btn.addEventListener('click', async function(e) {
                        e.stopPropagation();
                        var name = btn.getAttribute('data-name');
                        if (!name || !(await uiConfirm('删除该分类后，该分类下的应用将归为「其他」。确定删除？'))) return;
                        fetch(baseUrl + '/api/categories/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name }) })
                            .then(function(r) { return r.json(); })
                            .then(function(res) {
                                if (res && res.error) { alert('删除失败：' + res.error); return; }
                                var sel = document.getElementById('appCategorySelect').value;
                                if (sel === name) {
                                    document.getElementById('appCategorySelect').value = '其他';
                                    document.getElementById('appCategoryLabel').textContent = '其他';
                                }
                                appDetailCategoryList = appDetailCategoryList.filter(function(n) { return n !== name; });
                                if (appDetailCategoryList.indexOf('其他') === -1) appDetailCategoryList.push('其他');
                                renderCategoryOptions();
                            })
                            .catch(function() { alert('删除失败，请重试'); });
                    });
                });
            }

            function ensureCategoryListThenSetForm(json) {
                fetch(baseUrl + '/api/category_names').then(function(r) { return r.json(); }).then(function(data) {
                    appDetailCategoryList = (data && data.categories) ? data.categories.slice() : ['其他'];
                    if (appDetailCategoryList.indexOf('其他') === -1) appDetailCategoryList.push('其他');
                    renderCategoryOptions();
                    setAppDetailFormFromJson(json);
                }).catch(function() {
                    appDetailCategoryList = ['其他'];
                    renderCategoryOptions();
                    setAppDetailFormFromJson(json);
                });
            }

            function setAppDetailPath(appKey) {
                var pathEl = document.getElementById('appDetailPath');
                if (!pathEl) return;
                try {
                    var paths = (window.__lastSnapshot && window.__lastSnapshot.app_paths) ? window.__lastSnapshot.app_paths : {};
                    var raw = paths[appKey] || '';
                    pathEl.textContent = (typeof raw === 'string' ? raw : '').replace(/\\/g, '/');
                    pathEl.title = pathEl.textContent || '';
                } catch (e) { pathEl.textContent = ''; pathEl.title = ''; }
            }
            // 应用卡片点击：事件委托；请求用 app_key（repo key），展示用 data-app（name）
            if (appListContainer) {
                appListContainer.addEventListener('click', (e) => {
                    const card = e.target.closest('.app-card');
                    if (!card) return;
                    const appName = card.getAttribute('data-app');
                    const appKey = card.getAttribute('data-app-key');
                    if (!appName || !appKey) return;
                    window.__currentAppKeyInDetail = appKey;
                    appDetailTitle.textContent = appName;
                    setAppDetailPath(appKey);
                    appDetailModal.classList.remove('hidden');
                    appDetailModal.classList.add('flex');
                    initAppTimeChart(appKey, ensureCategoryListThenSetForm);
                });
            }
            window.openAppDetailByKey = function(appKey, displayName) {
                window.__currentAppKeyInDetail = appKey;
                appDetailTitle.textContent = displayName || appKey;
                setAppDetailPath(appKey);
                appDetailModal.classList.remove('hidden');
                appDetailModal.classList.add('flex');
                initAppTimeChart(appKey, ensureCategoryListThenSetForm);
            };

            var appCategoryTrigger = document.getElementById('appCategoryTrigger');
            var appCategoryPanel = document.getElementById('appCategoryPanel');
            if (appCategoryTrigger && appCategoryPanel) {
                appCategoryTrigger.addEventListener('click', function() {
                    appCategoryPanel.classList.toggle('hidden');
                });
                document.addEventListener('click', function(e) {
                    if (!appCategoryPanel.contains(e.target) && !appCategoryTrigger.contains(e.target)) appCategoryPanel.classList.add('hidden');
                });
            }
            var appCategoryAddBtn = document.getElementById('appCategoryAddBtn');
            var appCategoryNewInput = document.getElementById('appCategoryNewInput');
            if (appCategoryAddBtn && appCategoryNewInput) {
                appCategoryAddBtn.addEventListener('click', function() {
                    var name = (appCategoryNewInput.value || '').trim();
                    if (!name) return;
                    if (appDetailCategoryList.indexOf(name) === -1) appDetailCategoryList.push(name);
                    appDetailCategoryList.sort();
                    renderCategoryOptions();
                    document.getElementById('appCategorySelect').value = name;
                    document.getElementById('appCategoryLabel').textContent = name;
                    appCategoryNewInput.value = '';
                    appCategoryPanel.classList.add('hidden');
                });
            }

            // 关闭模态框
            closeAppDetailModal.addEventListener('click', () => {
                closeModal();
            });
            
            cancelAppDetail.addEventListener('click', () => {
                closeModal();
            });
            
            saveAppDetail.addEventListener('click', () => {
                var appKey = window.__currentAppKeyInDetail;
                if (!appKey) { closeModal(); return; }
                var base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
                var category = document.getElementById('appCategorySelect') ? document.getElementById('appCategorySelect').value : '其他';
                var displayName = document.getElementById('appDisplayNameInput') ? document.getElementById('appDisplayNameInput').value.trim() : '';
                var autoDnd = document.getElementById('appAutoDndCheckbox') ? document.getElementById('appAutoDndCheckbox').checked : false;
                fetch(base + '/api/app_settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ app_short: appKey, category: category, display_name: displayName, auto_dnd_on_focus: autoDnd })
                }).then(function(r) { return r.json();                 }).then(function(data) {
                    if (data && data.error) { alert('保存失败：' + data.error); return; }
                    closeModal();
                    if (typeof window.refreshLeftPanelForViewDate === 'function') window.refreshLeftPanelForViewDate();
                    if (typeof window.refreshCategoryDetailIfOpen === 'function') window.refreshCategoryDetailIfOpen();
                }).catch(function() { alert('保存失败，请重试'); });
            });

            var appExcludeBtn = document.getElementById('appExcludeBtn');
            if (appExcludeBtn) {
                appExcludeBtn.addEventListener('click', async function() {
                    var appKey = window.__currentAppKeyInDetail;
                    if (!appKey) return;
                    var msg = '排除将删除该应用已有全部数据，并且未来不再记录该应用，也不会因该应用触发休息提示。此操作可在黑名单中恢复记录，但历史不会恢复。\n\n确定排除该应用吗？';
                    if (!(await uiConfirm(msg))) return;
                    var base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
                    fetch(base + '/api/app_exclude', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ app_short: appKey })
                    }).then(function(r) { return r.json(); }).then(function(data) {
                        if (data && data.error) { alert('操作失败：' + data.error); return; }
                        closeModal();
                        if (typeof window.refreshLeftPanelForViewDate === 'function') window.refreshLeftPanelForViewDate();
                        if (typeof window.refreshCategoryDetailIfOpen === 'function') window.refreshCategoryDetailIfOpen();
                    }).catch(function() { alert('操作失败，请重试'); });
                });
            }
            
            function closeModal() {
                appDetailModal.classList.add('hidden');
                appDetailModal.classList.remove('flex');
                if (window.requestImmediateRefresh) window.requestImmediateRefresh('return_main');
                // 销毁图表实例
                if (currentAppChart) {
                    currentAppChart.destroy();
                    currentAppChart = null;
                }
            }
        }
        
        // 应用时间段图表（M1：真实数据，/api/app_details，app_key + viewDate）；onLoaded(json) 可选，用于 M4 设置区块预填
        function initAppTimeChart(appKey, onLoaded) {
            const ctx = document.getElementById('appTimeChart');
            if (!ctx) return;
            if (window.currentAppChart) {
                window.currentAppChart.destroy();
                window.currentAppChart = null;
            }
            var viewDate = (typeof window.getViewDateStr === 'function') ? window.getViewDateStr() : (new Date().toISOString().split('T')[0]);
            var base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
            var url = base + '/api/app_details?app=' + encodeURIComponent(appKey) + '&days=7&date=' + encodeURIComponent(viewDate);
            fetch(url).then(function(res) { return res.json(); }).then(function(json) {
                if (json.error) {
                    console.warn('app_details failed', json.error);
                    renderAppChartFallback(ctx, [0, 0, 0, 0, 0, 0, 0], ['日1', '日2', '日3', '日4', '日5', '日6', '日7']);
                    if (typeof onLoaded === 'function') onLoaded(null);
                    return;
                }
                if (typeof onLoaded === 'function') onLoaded(json);
                var daily = json.daily_seconds || {};
                var rangeStart = json.range_start || '';
                var rangeEnd = json.range_end || rangeStart;
                var labels = [];
                var data = [];
                function toYMD(d) {
                    var y = d.getFullYear(), m = d.getMonth() + 1, day = d.getDate();
                    return y + '-' + (m < 10 ? '0' + m : m) + '-' + (day < 10 ? '0' + day : day);
                }
                var cur = new Date(rangeStart + 'T12:00:00');
                var end = new Date(rangeEnd + 'T12:00:00');
                while (cur <= end) {
                    var d = toYMD(cur);
                    labels.push(d.substring(5).replace('-', '/'));
                    data.push(Math.round((daily[d] || 0) / 60));
                    cur.setDate(cur.getDate() + 1);
                }
                renderAppChartFallback(ctx, data, labels);
            }).catch(function(err) {
                console.warn('app_details fetch failed', err);
                renderAppChartFallback(ctx, [0, 0, 0, 0, 0, 0, 0], ['日1', '日2', '日3', '日4', '日5', '日6', '日7']);
                if (typeof onLoaded === 'function') onLoaded(null);
            });
        }
        function renderAppChartFallback(ctx, data, labels) {
            var color = window.colorForKey ? window.colorForKey('fallback', 0.8) : 'rgba(59, 130, 246, 0.8)';
            var borderColor = window.borderForKey ? window.borderForKey('fallback') : 'rgba(59, 130, 246, 1)';
            window.currentAppChart = new Chart(ctx.getContext('2d'), {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: '使用时间（分钟）',
                        data: data,
                        backgroundColor: color,
                        borderColor: borderColor,
                        borderWidth: 1,
                        borderRadius: 4,
                        barPercentage: 0.6,
                        categoryPercentage: 0.7
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    layout: { padding: { left: 4, right: 4, top: 4, bottom: 0 } },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15, 23, 42, 0.9)',
                            titleColor: 'white',
                            bodyColor: 'rgba(255, 255, 255, 0.7)',
                            borderColor: 'rgba(255, 255, 255, 0.1)',
                            borderWidth: 1,
                            padding: 12,
                            callback: function(item) {
                                var s = (item.raw || 0) * 60;
                                var m = Math.floor(s / 60);
                                return m > 0 ? m + ' 分钟' : (s + ' 秒');
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { display: false, drawBorder: false },
                            ticks: { color: 'rgba(255, 255, 255, 0.5)' }
                        },
                        y: {
                            grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false },
                            ticks: {
                                color: 'rgba(255, 255, 255, 0.5)',
                                callback: function(value) { return value + ' 分钟'; }
                            }
                        }
                    }
                }
            });
        }
        
        // 分类详情模态框功能
        function initCategoryDetailModal() {
            const categoryListContainer = document.getElementById('categoryListContainer');
            const categoryDetailModal = document.getElementById('categoryDetailModal');
            const closeCategoryDetailModal = document.getElementById('closeCategoryDetailModal');
            const closeCategoryDetail = document.getElementById('closeCategoryDetail');
            const categoryDetailTitle = document.getElementById('categoryDetailTitle');
            const categoryAppsList = document.getElementById('categoryAppsList');
            const categoryAppsSearch = document.getElementById('categoryAppsSearch');
            const base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
            var currentCategory = '';
            var allApps = [];
            
            if (categoryListContainer) {
                categoryListContainer.addEventListener('click', (e) => {
                    const card = e.target.closest('.category-card');
                    if (!card) return;
                    const categoryName = card.getAttribute('data-category');
                    if (!categoryName) return;
                    currentCategory = categoryName;
                    categoryDetailTitle.textContent = categoryName + '详情';
                    openModal(categoryName);
                });
            }
            
            // 打开模态框并加载应用列表
            function openModal(categoryName) {
                categoryDetailModal.classList.remove('hidden');
                categoryDetailModal.classList.add('flex');
                if (categoryAppsSearch) categoryAppsSearch.value = '';
                categoryAppsList.innerHTML = '<p class="text-gray-500 text-sm">加载中…</p>';
                fetch(base + '/api/apps_list').then(function(r) { return r.json(); }).then(function(data) {
                    allApps = (data && data.apps) || [];
                    renderCategoryAppsList(currentCategory, allApps);
                }).catch(function() {
                    categoryAppsList.innerHTML = '<p class="text-gray-500 text-sm">加载失败，请重试</p>';
                });
            }
            // 若分类详情已打开，重拉 apps_list 并重渲染当前分类（供应用详情保存/排除后调用）
            window.refreshCategoryDetailIfOpen = function() {
                if (categoryDetailModal.classList.contains('hidden')) return;
                categoryAppsList.innerHTML = '<p class="text-gray-500 text-sm">加载中…</p>';
                fetch(base + '/api/apps_list').then(function(r) { return r.json(); }).then(function(data) {
                    allApps = (data && data.apps) || [];
                    renderCategoryAppsList(currentCategory, allApps);
                }).catch(function() {
                    categoryAppsList.innerHTML = '<p class="text-gray-500 text-sm">加载失败，请重试</p>';
                });
            };
            
            // 渲染分类应用列表
            function renderCategoryAppsList(categoryName, apps) {
                // 过滤当前分类的应用
                var filteredApps = apps.filter(function(app) {
                    return app.category === categoryName;
                });
                
                if (filteredApps.length === 0) {
                    categoryAppsList.innerHTML = '<p class="text-gray-500 text-sm">该分类暂无应用</p>';
                    return;
                }
                
                var iconBase = base;
                var usedSettings = [];
                categoryAppsList.innerHTML = filteredApps.map(function(app) {
                    var key = app.app_short || app.display_name || '';
                    var color = window.colorForKeyInContext ? window.colorForKeyInContext(key, 0.8, usedSettings) : (window.colorForKey ? window.colorForKey(key, 0.8) : 'rgba(59,130,246,0.8)');
                    var solid = color.replace(/,\s*[\d.]+\s*\)\s*$/, ',1)');
                    usedSettings.push(solid);
                    var bgDim = color.replace(/,\s*[\d.]+\s*\)\s*$/, ',0.2)');
                    var borderColor = solid;
                    var iconUrl = iconBase + '/api/icon?app=' + encodeURIComponent(app.app_short);
                    var name = (app.display_name || app.app_short || '').trim() || app.app_short;
                    return '<div class="app-card flex items-center justify-between py-2 px-2 panel-inner rounded border border-white/5 cursor-pointer hover:bg-dark-300/80 transition-colors" data-app-key="' + escapeHtml(app.app_short) + '" data-app-name="' + escapeHtml(name) + '">' +
                        '<div class="flex items-center min-w-0">' +
                        '<div class="w-8 h-8 rounded flex items-center justify-center mr-2 flex-shrink-0 overflow-hidden" style="background:' + bgDim + '">' +
                        '<img src="' + escapeHtml(iconUrl) + '" alt="" class="w-5 h-5 object-contain" onerror="this.style.display=\'none\';var n=this.nextElementSibling;if(n)n.style.display=\'inline\';">' +
                        '<i class="fa fa-desktop text-sm app-card-fallback-icon" style="color:' + borderColor + ';display:none;"></i></div>' +
                        '<div class="min-w-0"><span class="font-medium text-sm block truncate">' + escapeHtml(name) + '</span><span class="text-xs text-gray-400">' + escapeHtml(app.category || '') + '</span></div></div></div>';
                }).join('');
            }
            
            // 搜索框事件
            if (categoryAppsSearch) {
                categoryAppsSearch.addEventListener('input', function() {
                    var q = (categoryAppsSearch.value || '').trim().toLowerCase();
                    if (!q) {
                        renderCategoryAppsList(currentCategory, allApps);
                        return;
                    }
                    // 搜索时显示所有匹配的应用（不限当前分类）
                    var filtered = allApps.filter(function(app) {
                        var name = ((app.display_name || app.app_short || '') + ' ' + (app.app_short || '') + ' ' + (app.category || '')).toLowerCase();
                        return name.indexOf(q) !== -1;
                    });
                    // 重新渲染列表（不区分是否当前分类）
                    if (filtered.length === 0) {
                        categoryAppsList.innerHTML = '<p class="text-gray-500 text-sm">暂无匹配应用</p>';
                        return;
                    }
                    var iconBase = base;
                    var usedSettings = [];
                    categoryAppsList.innerHTML = filtered.map(function(app) {
                        var key = app.app_short || app.display_name || '';
                        var color = window.colorForKeyInContext ? window.colorForKeyInContext(key, 0.8, usedSettings) : (window.colorForKey ? window.colorForKey(key, 0.8) : 'rgba(59,130,246,0.8)');
                        var solid = color.replace(/,\s*[\d.]+\s*\)\s*$/, ',1)');
                        usedSettings.push(solid);
                        var bgDim = color.replace(/,\s*[\d.]+\s*\)\s*$/, ',0.2)');
                        var borderColor = solid;
                        var iconUrl = iconBase + '/api/icon?app=' + encodeURIComponent(app.app_short);
                        var name = (app.display_name || app.app_short || '').trim() || app.app_short;
                        return '<div class="app-card flex items-center justify-between py-2 px-2 panel-inner rounded border border-white/5 cursor-pointer hover:bg-dark-300/80 transition-colors" data-app-key="' + escapeHtml(app.app_short) + '" data-app-name="' + escapeHtml(name) + '">' +
                            '<div class="flex items-center min-w-0">' +
                            '<div class="w-8 h-8 rounded flex items-center justify-center mr-2 flex-shrink-0 overflow-hidden" style="background:' + bgDim + '">' +
                            '<img src="' + escapeHtml(iconUrl) + '" alt="" class="w-5 h-5 object-contain" onerror="this.style.display=\'none\';var n=this.nextElementSibling;if(n)n.style.display=\'inline\';">' +
                            '<i class="fa fa-desktop text-sm app-card-fallback-icon" style="color:' + borderColor + ';display:none;"></i></div>' +
                            '<div class="min-w-0"><span class="font-medium text-sm block truncate">' + escapeHtml(name) + '</span><span class="text-xs text-gray-400">' + escapeHtml(app.category || '') + '</span></div></div></div>';
                    }).join('');
                });
            }
            
            // 点击应用卡片跳转到详情（不关闭分类详情，关闭应用详情时会回到分类详情）
            categoryAppsList.addEventListener('click', function(e) {
                var card = e.target.closest('.app-card[data-app-key]');
                if (!card) return;
                var appKey = card.getAttribute('data-app-key');
                var appName = card.getAttribute('data-app-name') || appKey;
                if (!appKey) return;
                if (typeof window.openAppDetailByKey === 'function') window.openAppDetailByKey(appKey, appName);
            });
            
            // 关闭模态框
            closeCategoryDetailModal.addEventListener('click', () => {
                closeModal();
            });
            
            closeCategoryDetail.addEventListener('click', () => {
                closeModal();
            });
            
            function closeModal() {
                categoryDetailModal.classList.add('hidden');
                categoryDetailModal.classList.remove('flex');
                if (window.requestImmediateRefresh) window.requestImmediateRefresh('return_main');
            }
        }
        
        // 右侧「屏幕时间统计」：按时间段堆叠条图（各应用/分类）+ 下方 Top 应用列表（与饼图高亮同步）
        window.statsHighlightKey = null;
        window.__hoverState = { chart: null, key: null, ts: 0 };
        function canonicalKey(s) { return (s || '').trim().toLowerCase().replace(/\\/g, '/'); }
        window.canonicalKey = canonicalKey;
        function initTimeBarsChart() {
            const canvas = document.getElementById('timeBarsChart');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            const chart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: [],
                    datasets: []
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    layout: { padding: { left: 2, right: 4, top: 26, bottom: 0 } },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
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
                    scales: {
                        x: {
                            stacked: true,
                            grid: { display: false },
                            ticks: { color: 'rgba(255,255,255,0.5)', maxRotation: 0 }
                        },
                        y: {
                            stacked: true,
                            grid: { color: 'rgba(255,255,255,0.08)' },
                            ticks: {
                                color: 'rgba(255,255,255,0.5)',
                                maxTicksLimit: 8,
                                callback: function(val) {
                                    if (window.timeBarsUseHours) {
                                        var h = val / 3600;
                                        return h % 1 === 0 ? String(h) : h.toFixed(1);
                                    }
                                    var m = Math.round(val / 60);
                                    return [String(m), '\u5206\u949f'];
                                }
                            },
                            title: { display: false }
                        }
                    },
                    onClick: function(ev, elements) {
                        try {
                            if (elements && elements.length && window.timebarKeys) {
                                var dsIdx = elements[0].datasetIndex;
                                var k = (dsIdx >= 0 && dsIdx < window.timebarKeys.length) ? window.timebarKeys[dsIdx] : null;
                                if (k && typeof focusAppCardByKey === 'function') focusAppCardByKey(k);
                            }
                        } catch(e) {}
                    },
onHover: function(ev, elements) {
                        var key = null;
                        if (elements && elements.length && window.timebarKeys) {
                            var dsIdx = elements[0].datasetIndex;
                            if (dsIdx >= 0 && dsIdx < window.timebarKeys.length) key = window.timebarKeys[dsIdx];
                        }
                        var ck = key ? canonicalKey(key) : null;
                        if (ck !== window.statsHighlightKey) {
                            window.statsHighlightKey = ck;
                            window.__hoverState = ck ? { chart: 'bar', key: ck, ts: Date.now() } : { chart: null, key: null, ts: 0 };
                            applyStatsHighlightToPie();
                            if (window.timeBarsChartInstance) applyStatsHighlightToTimeBars();
                        }
                    }
                },
            });
            window.timeBarsChartInstance = chart;
        }
        function applyStatsHighlightToPie() {
            if (!window.appChartInstance || !window.appChartKeys) return;
            var key = window.statsHighlightKey;
            var idx = -1;
            for (var i = 0; i < window.appChartKeys.length; i++) {
                if (canonicalKey(window.appChartKeys[i]) === key) { idx = i; break; }
            }
            if (idx >= 0) {
                window.appChartInstance.setActiveElements([{ datasetIndex: 0, index: idx }]);
            } else {
                window.appChartInstance.setActiveElements([]);
            }
            window.appChartInstance.update();
        }
        function applyStatsHighlightToPieSilent() {
            if (!window.appChartInstance || !window.appChartKeys) return;
            var key = window.statsHighlightKey;
            var idx = -1;
            for (var i = 0; i < window.appChartKeys.length; i++) {
                if (canonicalKey(window.appChartKeys[i]) === key) { idx = i; break; }
            }
            if (idx >= 0) {
                window.appChartInstance.setActiveElements([{ datasetIndex: 0, index: idx }]);
            } else {
                window.appChartInstance.setActiveElements([]);
            }
            window.appChartInstance.update('none');
        }
        function applyStatsHighlightToTimeBars() {
            var chart = window.timeBarsChartInstance;
            if (!chart || !chart.data.datasets.length || !window.timebarKeys) return;
            var key = window.statsHighlightKey;
            var usedBar = [];
            for (var i = 0; i < chart.data.datasets.length; i++) {
                var k = window.timebarKeys[i];
                var isHighlight = key && canonicalKey(k) === key;
                var solid = window.colorForKeyInContext ? window.colorForKeyInContext(k, 1, usedBar) : (window.colorForKey ? window.colorForKey(k, 1) : 'rgba(59,130,246,1)');
                usedBar.push(solid);
                var dim = solid.replace(/,\s*[\d.]+\s*\)\s*$/, ',0.5)');
                // 旧包方式：用透明度区分高亮，不使用hoverBackgroundColor，让Chart.js默认hover生效
                chart.data.datasets[i].backgroundColor = isHighlight ? solid : dim;
            }
            chart.update();
        }

        // 根据 snapshot 更新右侧：堆叠条图 + 下方 Top 应用/分类列表（与左侧饼图同色）
        function updateRightPanelFromSnapshot(snap) {
            if (!snap || snap.error) return;
            const totalSec = snap.stats_total_seconds != null ? snap.stats_total_seconds : 0;
            const focusSec = snap.stats_longest_focus_seconds != null ? snap.stats_longest_focus_seconds : 0;
            const rate = snap.stats_rest_rate_percent;
            const doneCount = snap.stats_rest_complete_count != null ? snap.stats_rest_complete_count : 0;
            const skipCount = snap.stats_rest_snooze_count != null ? snap.stats_rest_snooze_count : 0;
            const rangeKey = snap.range_key || 'day';
            const rangeStart = snap.range_start || (snap.vm && snap.vm.local_date);
            const rangeEnd = snap.range_end || rangeStart;
            let dateLabel = '—';
            if (rangeKey === 'day' && snap.vm && snap.vm.local_date)
                dateLabel = snap.vm.local_date === localTodayStr() ? '今日' : snap.vm.local_date;
            else if (rangeStart && rangeEnd) {
                // 去掉年份，只显示 MM-DD ~ MM-DD
                var startParts = rangeStart.split('-');
                var endParts = rangeEnd.split('-');
                var startMD = startParts.length >= 3 ? startParts[1] + '-' + startParts[2] : rangeStart;
                var endMD = endParts.length >= 3 ? endParts[1] + '-' + endParts[2] : rangeEnd;
                dateLabel = startMD + ' ~ ' + endMD;
            }
            const elTotal = document.getElementById('statsTotal');
            const elFocus = document.getElementById('statsFocus');
            const elRate = document.getElementById('statsRate');
            const elRange = document.getElementById('statsRangeLabel');
            const elDone = document.getElementById('restDone');
            const elSkip = document.getElementById('restSkip');
            if (elTotal) elTotal.textContent = formatWorkTime(totalSec);
            if (elFocus) elFocus.textContent = formatWorkTime(focusSec);
            if (elRate) elRate.textContent = (rate != null ? rate + '%' : '—');
            if (elRange) elRange.textContent = dateLabel;
            if (elDone) elDone.textContent = doneCount + '次';
            if (elSkip) elSkip.textContent = skipCount + '次';

            const labels = snap.timebar_labels || [];
            let keys = snap.timebar_keys || [];
            let values = snap.timebar_values || [];
            if (!keys.length) keys = ['暂无'];
            if (!values.length) values = labels.map(function() { return [0]; });
            window.timebarKeys = keys;
            if (window.timeBarsChartInstance) {
                const chart = window.timeBarsChartInstance;
                const yScale = chart.options.scales.y;
                // 按柱状图数据最大值决定单位：<3 小时用分钟，避免重复刻度
                var maxSec = 0;
                for (var r = 0; r < values.length; r++) {
                    var row = values[r];
                    if (!row) continue;
                    var sum = 0;
                    for (var k = 0; k < row.length; k++) sum += (Number(row[k]) || 0);
                    if (sum > maxSec) maxSec = sum;
                }
                var USE_HOURS_THRESHOLD_SEC = 3 * 3600;
                window.timeBarsUseHours = maxSec >= USE_HOURS_THRESHOLD_SEC;
                if (window.timeBarsUseHours) {
                    yScale.ticks.callback = function(val) {
                        var h = val / 3600;
                        return h % 1 === 0 ? String(h) : h.toFixed(1);
                    };
                    yScale.ticks.stepSize = undefined;
                    yScale.suggestedMax = undefined;
                } else {
                    var maxMin = Math.ceil(maxSec / 60);
                    var stepMin = (maxMin <= 50) ? 5 : 10;
                    var suggestedMaxSec = Math.ceil(maxMin / stepMin) * stepMin * 60;
                    yScale.suggestedMax = suggestedMaxSec;
                    yScale.ticks.stepSize = stepMin * 60;
                    yScale.ticks.callback = function(val) {
                        var m = Math.round(val / 60);
                        return [String(m), '\u5206\u949f'];
                    };
                }
                yScale.ticks.maxTicksLimit = 8;
                yScale.title.display = false;
                const displayNames = snap.display_names || {};
                const appPathsForBar = snap.app_paths || {};
                function shortNameForKey(k) {
                    var n = displayNames[k];
                    if (n) return n;
                    var p = appPathsForBar[k];
                    if (p) {
                        n = (p.replace(/\\/g, '/').split('/').pop()) || k;
                        if (n && n.toLowerCase().endsWith('.exe')) n = n.slice(0, -4);
                        return n;
                    }
                    if (k && k.toLowerCase().endsWith('.exe')) return k.slice(0, -4);
                    return k;
                }
                var usedBar = [];
                const ds = [];
                for (var i = 0; i < keys.length; i++) {
                    const col = values.map(function(row) { return row && row[i] != null ? row[i] : 0; });
                    const key = keys[i];
                    // 使用 colorForKeyInContext 确保与饼图颜色一致（传入 usedBar 避免冲突）
                    var solid = window.colorForKeyInContext ? window.colorForKeyInContext(key, 1, usedBar) : (window.colorForKey ? window.colorForKey(key, 1) : 'rgba(59,130,246,1)');
                    usedBar.push(solid);
                    var dim = solid.replace(/,\s*[\d.]+\s*\)\s*$/, ',0.5)');
                    ds.push({
                        label: shortNameForKey(key),
                        data: col,
                        backgroundColor: window.statsHighlightKey && canonicalKey(key) === window.statsHighlightKey ? solid : dim,
                        // 不设置hoverBackgroundColor，让Chart.js使用默认hover效果
                        borderColor: 'rgba(255,255,255,0.12)',
                        borderWidth: 0.7,
                        borderRadius: 2,
                        borderSkipped: false,
                        barPercentage: 0.85,
                        categoryPercentage: 0.9
                    });
                }
                var displayLabels = labels;
                if (rangeKey === 'day' && labels.length > 0) {
                    var allNumeric = labels.every(function(l) { return /^\s*\d+\s*$/.test(String(l)); });
                    if (allNumeric) displayLabels = labels.map(function(l) { return String(l).trim() + '\u65f6'; });
                }
                chart.data.labels = displayLabels;
                chart.data.datasets = ds;
                chart.update('none');
            }

            // 下方：Top 4 应用/分类 + 时长（短名：优先 displayNames，否则路径 basename 并去掉 .exe）
            const isRange = (rangeKey === 'week' || rangeKey === 'month' || rangeKey === 'custom');
            const usage = isRange && snap.range_daily_usage ? (snap.range_daily_usage || {}) : ((snap.vm && snap.vm.daily_usage) || {});
            const appPaths = snap.app_paths || {};
            const displayNamesTop = snap.display_names || {};
            function shortNameForTop(k) {
                var n = displayNamesTop[k];
                if (n) return n;
                var p = appPaths[k];
                if (p) {
                    n = (p.replace(/\\/g, '/').split('/').pop()) || k;
                    if (n && n.toLowerCase().endsWith('.exe')) n = n.slice(0, -4);
                    return n;
                }
                if (k && k.toLowerCase().endsWith('.exe')) return k.slice(0, -4);
                return k;
            }
            const topItems = Object.keys(usage)
                .map(function(k) { return { key: k, name: shortNameForTop(k), seconds: usage[k] || 0 }; })
                .sort(function(a, b) { return b.seconds - a.seconds; })
                .slice(0, 4);
            var top4TotalSec = snap.stats_total_seconds != null ? snap.stats_total_seconds : 0;
            var rightHash = buildItemsHash(topItems, top4TotalSec, 4, function(it) { return it.key; });
            var top4Container = document.getElementById('statsTop4Container');
            if (top4Container && top4Container.__hash === rightHash) { /* skip DOM update */ } else {
                if (top4Container) top4Container.__hash = rightHash;
                const elDist1 = document.getElementById('distName1');
                const elDist2 = document.getElementById('distName2');
                const elDist3 = document.getElementById('distName3');
                const elDist4 = document.getElementById('distName4');
                const elVal1 = document.getElementById('distVal1');
                const elVal2 = document.getElementById('distVal2');
                const elVal3 = document.getElementById('distVal3');
                const elVal4 = document.getElementById('distVal4');
                const distNames = [elDist1, elDist2, elDist3, elDist4];
                const distVals = [elVal1, elVal2, elVal3, elVal4];
                var usedTop4 = [];
                for (var i = 0; i < 4; i++) {
                    if (distNames[i]) distNames[i].textContent = topItems[i] ? topItems[i].name : '—';
                    if (distNames[i] && topItems[i]) {
                        var c4 = window.colorForKeyInContext ? window.colorForKeyInContext(topItems[i].key, 1, usedTop4) : (window.borderForKey ? window.borderForKey(topItems[i].key) : '');
                        usedTop4.push(c4);
                        distNames[i].style.color = c4;
                    }
                    if (distVals[i]) distVals[i].textContent = topItems[i] ? formatWorkTime(topItems[i].seconds) : '—';
                }
            }
        }

        // 设置页：自启动、勿扰、主界面、无操作暂停、休息提醒间隔、休息时长
        function initSettingsModal() {
            const btn = document.getElementById('settingsBtn');
            const modal = document.getElementById('settingsModal');
            const closeBtn = document.getElementById('closeSettingsModal');
            const cancelBtn = document.getElementById('settingsCancel');
            const applyBtn = document.getElementById('settingsApply');
            const launchAtLogin = document.getElementById('settingsLaunchAtLogin');
            const startupDnd = document.getElementById('settingsStartupDnd');
            const startupShow = document.getElementById('settingsStartupShow');
            const idleThresholdInput = document.getElementById('settingsIdleThreshold');
            const reminderIntervalInput = document.getElementById('settingsReminderInterval');
            const reminderDurationInput = document.getElementById('settingsReminderDuration');
            const reminderUnitSelect = document.getElementById('settingsReminderUnit');
            const notifyDurationInput = document.getElementById('settingsNotifyDuration');
            const restEndSoundCheckbox = document.getElementById('settingsRestEndSound');
            const base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
            if (!btn || !modal) return;
            function openModal() {
                modal.classList.remove('hidden');
                modal.classList.add('flex');
                fetch(base + '/api/config').then(function(r) { return r.json(); }).then(function(data) {
                    if (data.config) {
                        var c = data.config;
                        if (launchAtLogin) launchAtLogin.checked = !!c.startup_launch_at_login;
                        if (startupDnd) startupDnd.checked = !!c.startup_dnd;
                        if (startupShow) startupShow.checked = c.startup_show_main !== false;
                        var idleSec = Math.max(3, Math.min(300, parseInt(c.idle_threshold_s, 10) || 60));
                        if (idleThresholdInput) { idleThresholdInput.value = idleSec; idleThresholdInput.min = 3; idleThresholdInput.max = 300; }
                        var workMin = Math.max(1, Math.min(600, parseInt(c.reminder_work_minutes, 10) || 20));
                        if (reminderIntervalInput) { reminderIntervalInput.value = workMin; reminderIntervalInput.min = 1; reminderIntervalInput.max = 600; }
                        var unit = (c.reminder_rest_unit === 'min' || c.reminder_rest_unit === 'sec') ? c.reminder_rest_unit : 'sec';
                        var restSec = parseInt(c.reminder_rest_seconds, 10) || 20;
                        if (unit === 'sec') restSec = Math.max(5, restSec);
                        else restSec = Math.max(60, restSec);
                        if (reminderUnitSelect) reminderUnitSelect.value = unit;
                        if (reminderDurationInput) {
                            if (unit === 'min') { reminderDurationInput.value = Math.max(1, Math.min(120, Math.round(restSec / 60))); reminderDurationInput.min = 1; reminderDurationInput.max = 120; }
                            else { reminderDurationInput.value = Math.max(5, Math.min(3600, restSec)); reminderDurationInput.min = 5; reminderDurationInput.max = 3600; }
                        }
                        if (notifyDurationInput) notifyDurationInput.value = String(c.notify_auto_hide_seconds ?? 20);
                        if (restEndSoundCheckbox) restEndSoundCheckbox.checked = c.rest_end_sound_enabled !== false;
                    }
                }).catch(function() {});
            }
            function closeModal() {
                modal.classList.add('hidden');
                modal.classList.remove('flex');
                if (window.requestImmediateRefresh) window.requestImmediateRefresh('return_main');
            }
            function saveAndClose() {
                var idleSec = 60;
                if (idleThresholdInput) {
                    idleSec = Math.max(3, Math.min(300, parseInt(idleThresholdInput.value, 10) || 60));
                    idleThresholdInput.value = idleSec;
                }
                var workMin = 20;
                if (reminderIntervalInput) {
                    workMin = Math.max(1, Math.min(600, parseInt(reminderIntervalInput.value, 10) || 20));
                    reminderIntervalInput.value = workMin;
                }
                var unit = (reminderUnitSelect && reminderUnitSelect.value === 'min') ? 'min' : 'sec';
                var durationVal = reminderDurationInput ? (parseInt(reminderDurationInput.value, 10) || (unit === 'min' ? 1 : 5)) : (unit === 'min' ? 1 : 5);
                var restSec = unit === 'min' ? Math.max(60, Math.min(7200, durationVal * 60)) : Math.max(5, Math.min(3600, durationVal));
                if (reminderDurationInput) reminderDurationInput.value = unit === 'min' ? Math.round(restSec / 60) : restSec;
                var payload = {
                    startup_launch_at_login: launchAtLogin ? launchAtLogin.checked : false,
                    startup_dnd: startupDnd ? startupDnd.checked : false,
                    startup_show_main: startupShow ? startupShow.checked : true,
                    idle_threshold_s: idleSec,
                    reminder_work_minutes: workMin,
                    reminder_rest_seconds: restSec,
                    reminder_rest_unit: unit,
                    rest_end_sound_enabled: restEndSoundCheckbox ? restEndSoundCheckbox.checked : true
                };
                if (notifyDurationInput) {
                    var v = parseInt(notifyDurationInput.value, 10);
                    if (isNaN(v)) v = 20;
                    v = Math.max(0, Math.min(600, v));
                    notifyDurationInput.value = String(v);
                    payload.notify_auto_hide_seconds = v;
                }
                fetch(base + '/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
                    .then(function() {
                        closeModal();
                        if (typeof window.refreshRestStatusFromConfig === 'function') window.refreshRestStatusFromConfig();
                    })
                    .catch(function() {});
            }
            btn.addEventListener('click', openModal);
            if (closeBtn) closeBtn.addEventListener('click', closeModal);
            if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
            if (applyBtn) applyBtn.addEventListener('click', saveAndClose);
            window.ui = window.ui || {};
            window.ui.openSettings = openModal;
            // 检查更新按钮已迁移到主界面按钮栏
            var topCheckUpdateBtn = document.getElementById('checkUpdateBtn');
            if (topCheckUpdateBtn) {
                topCheckUpdateBtn.addEventListener('click', function() {
                    if (window.ui && window.ui.checkUpdate) window.ui.checkUpdate();
                });
            }
        }

        // M5 检查更新：站内 modal 展示结果，禁止 alert/confirm
        function initUpdateCheckModal() {
            var modal = document.getElementById('updateCheckModal');
            var msgEl = document.getElementById('updateCheckMessage');
            var actionsEl = document.getElementById('updateCheckActions');
            var closeOnlyEl = document.getElementById('updateCheckCloseOnly');
            var openUrlBtn = document.getElementById('updateCheckOpenUrlBtn');
            var closeBtn = document.getElementById('updateCheckCloseBtn');
            var closeOnlyBtn = document.getElementById('updateCheckCloseOnlyBtn');
            var closeModalBtn = document.getElementById('closeUpdateCheckModal');
            var base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
            if (!modal || !msgEl) return;
            function hideModal() {
                modal.classList.add('hidden');
                modal.classList.remove('flex');
                if (window.requestImmediateRefresh) window.requestImmediateRefresh('return_main');
            }
            window.ui = window.ui || {};
            window.ui.checkUpdate = function() {
                msgEl.textContent = '正在检查…';
                if (actionsEl) actionsEl.classList.add('hidden');
                if (closeOnlyEl) closeOnlyEl.classList.remove('hidden');
                modal.classList.remove('hidden');
                modal.classList.add('flex');
                fetch(base + '/api/update/check').then(function(r) { return r.json(); }).then(function(data) {
                    if (data.error || !data.ok) {
                        msgEl.textContent = '检查失败：' + (data.error || '未知错误');
                    } else if (data.has_update && data.html_url) {
                        msgEl.textContent = '发现新版本 ' + (data.latest || '') + '，可前往下载。';
                        if (actionsEl) actionsEl.classList.remove('hidden');
                        if (closeOnlyEl) closeOnlyEl.classList.add('hidden');
                        window.__updateCheckHtmlUrl = data.html_url;
                    } else {
                        msgEl.textContent = '当前已是最新版本。';
                    }
                }).catch(function() {
                    msgEl.textContent = '检查失败：网络或请求错误';
                });
            };
            if (closeModalBtn) closeModalBtn.addEventListener('click', hideModal);
            if (closeBtn) closeBtn.addEventListener('click', hideModal);
            if (closeOnlyBtn) closeOnlyBtn.addEventListener('click', hideModal);
            if (openUrlBtn) {
                openUrlBtn.addEventListener('click', function() {
                    if (window.__updateCheckHtmlUrl) {
                        fetch(base + '/api/open_url', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'release_notes' }) }).catch(function() {});
                    }
                    hideModal();
                });
            }
        }

        // M4 应用设置：已记录应用卡片列表，点击进 app_details
        function initAppSettingsBtn() {
            const btn = document.getElementById('appSettingsBtn');
            const modal = document.getElementById('appSettingsModal');
            const listEl = document.getElementById('appSettingsList');
            const searchInput = document.getElementById('appSettingsSearch');
            const closeBtn = document.getElementById('closeAppSettingsModal');
            const cancelBtn = document.getElementById('appSettingsCancel');
            const base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
            if (!btn || !modal || !listEl) return;
            var allApps = [];
            function renderAppSettingsList(apps) {
                if (apps.length === 0) {
                    listEl.innerHTML = '<p class="text-gray-500 text-sm">暂无匹配应用</p>';
                    return;
                }
                var iconBase = base;
                var usedSettings = [];
                listEl.innerHTML = apps.map(function(app) {
                    var key = app.app_short || app.display_name || '';
                    var color = window.colorForKeyInContext ? window.colorForKeyInContext(key, 0.8, usedSettings) : (window.colorForKey ? window.colorForKey(key, 0.8) : 'rgba(59,130,246,0.8)');
                    var solid = color.replace(/,\s*[\d.]+\s*\)\s*$/, ',1)');
                    usedSettings.push(solid);
                    var bgDim = color.replace(/,\s*[\d.]+\s*\)\s*$/, ',0.2)');
                    var borderColor = solid;
                    var iconUrl = iconBase + '/api/icon?app=' + encodeURIComponent(app.app_short);
                    var name = (app.display_name || app.app_short || '').trim() || app.app_short;
                    return '<div class="app-card flex items-center justify-between py-2 px-2 panel-inner rounded border border-white/5 cursor-pointer hover:bg-dark-300/80 transition-colors" data-app-key="' + escapeHtml(app.app_short) + '" data-app-name="' + escapeHtml(name) + '">' +
                        '<div class="flex items-center min-w-0">' +
                        '<div class="w-8 h-8 rounded flex items-center justify-center mr-2 flex-shrink-0 overflow-hidden" style="background:' + bgDim + '">' +
                        '<img src="' + escapeHtml(iconUrl) + '" alt="" class="w-5 h-5 object-contain" onerror="this.style.display=\'none\';var n=this.nextElementSibling;if(n)n.style.display=\'inline\';">' +
                        '<i class="fa fa-desktop text-sm app-card-fallback-icon" style="color:' + borderColor + ';display:none;"></i></div>' +
                        '<div class="min-w-0"><span class="font-medium text-sm block truncate">' + escapeHtml(name) + '</span><span class="text-xs text-gray-400">' + escapeHtml(app.category || '') + '</span></div></div></div>';
                }).join('');
            }
            function openModal() {
                modal.classList.remove('hidden');
                modal.classList.add('flex');
                if (searchInput) searchInput.value = '';
                listEl.innerHTML = '<p class="text-gray-500 text-sm">加载中…</p>';
                fetch(base + '/api/apps_list').then(function(r) { return r.json(); }).then(function(data) {
                    allApps = (data && data.apps) || [];
                    if (allApps.length === 0) {
                        listEl.innerHTML = '<p class="text-gray-500 text-sm">暂无已记录应用</p>';
                        return;
                    }
                    renderAppSettingsList(allApps);
                }).catch(function() {
                    listEl.innerHTML = '<p class="text-gray-500 text-sm">加载失败，请重试</p>';
                });
            }
            if (searchInput) {
                searchInput.addEventListener('input', function() {
                    var q = (searchInput.value || '').trim().toLowerCase();
                    if (!q) {
                        renderAppSettingsList(allApps);
                        return;
                    }
                    var filtered = allApps.filter(function(app) {
                        var name = ((app.display_name || app.app_short || '') + ' ' + (app.app_short || '') + ' ' + (app.category || '')).toLowerCase();
                        return name.indexOf(q) !== -1;
                    });
                    renderAppSettingsList(filtered);
                });
            }
            function closeModal() {
                modal.classList.add('hidden');
                modal.classList.remove('flex');
                if (window.requestImmediateRefresh) window.requestImmediateRefresh('return_main');
            }
            listEl.addEventListener('click', function(e) {
                var card = e.target.closest('.app-card[data-app-key]');
                if (!card) return;
                var appKey = card.getAttribute('data-app-key');
                var appName = card.getAttribute('data-app-name') || appKey;
                if (!appKey) return;
                closeModal();
                if (typeof window.openAppDetailByKey === 'function') window.openAppDetailByKey(appKey, appName);
            });
            btn.addEventListener('click', openModal);
            if (closeBtn) closeBtn.addEventListener('click', closeModal);
            if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
        }

        // M4 黑名单：列表展示，可移除
        function initBlacklistBtn() {
            const btn = document.getElementById('blacklistBtn');
            const modal = document.getElementById('blacklistModal');
            const listEl = document.getElementById('blacklistList');
            const closeBtn = document.getElementById('closeBlacklistModal');
            const cancelBtn = document.getElementById('blacklistCancel');
            const base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
            if (!btn || !modal || !listEl) return;
            function openModal() {
                modal.classList.remove('hidden');
                modal.classList.add('flex');
                listEl.innerHTML = '<p class="text-gray-500 text-sm">加载中…</p>';
                fetch(base + '/api/blacklist').then(function(r) { return r.json(); }).then(function(data) {
                    var apps = (data && data.apps) || [];
                    if (apps.length === 0) {
                        listEl.innerHTML = '<p class="text-gray-500 text-sm">黑名单为空</p>';
                        return;
                    }
                    listEl.innerHTML = apps.map(function(app) {
                        return '<div class="flex items-center justify-between py-2 px-2 panel-inner rounded border border-white/5">' +
                            '<span class="font-medium text-sm">' + escapeHtml(app.display_name || app.app_short) + '</span>' +
                            '<span class="text-xs text-gray-400 mr-2">' + escapeHtml(app.app_short) + '</span>' +
                            '<button type="button" class="blacklist-remove-btn btn-ghost text-sm text-primary" data-app-key="' + escapeHtml(app.app_short) + '">移除</button></div>';
                    }).join('');
                    listEl.querySelectorAll('.blacklist-remove-btn').forEach(function(b) {
                        b.addEventListener('click', async function() {
                            var key = b.getAttribute('data-app-key');
                            var displayName = b.parentElement.querySelector('.font-medium') ? b.parentElement.querySelector('.font-medium').textContent : key;
                            if (!key) return;
                            var msg = '确定从黑名单移除「' + displayName + '」？\n移除后将恢复记录该应用的屏幕时间（历史数据无法恢复）';
                            if (!(await uiConfirm(msg))) return;
                            fetch(base + '/api/blacklist_remove', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ app_short: key }) })
                                .then(function(r) { return r.json(); })
                                .then(function(res) {
                                    if (res && res.error) { alert('操作失败：' + res.error); return; }
                                    openModal();
                                    if (typeof window.refreshLeftPanelForViewDate === 'function') window.refreshLeftPanelForViewDate();
                                })
                                .catch(function() { alert('操作失败，请重试'); });
                        });
                    });
                }).catch(function() {
                    listEl.innerHTML = '<p class="text-gray-500 text-sm">加载失败，请重试</p>';
                });
            }
            function closeModal() {
                modal.classList.add('hidden');
                modal.classList.remove('flex');
            }
            btn.addEventListener('click', openModal);
            if (closeBtn) closeBtn.addEventListener('click', closeModal);
            if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
        }

        // 星空背景：多层、大小不一、带闪烁
        function createStars() {
            const container = document.getElementById('stars');
            if (!container) return;
            // 大星（少、亮）
            for (let i = 0; i < 45; i++) {
                const star = document.createElement('div');
                star.className = 'star';
                const size = Math.random() * 2 + 1.2;
                const x = Math.random() * 100, y = Math.random() * 100;
                const opacity = Math.random() * 0.4 + 0.5;
                star.style.cssText = `position:absolute;width:${size}px;height:${size}px;background:#fff;border-radius:50%;left:${x}%;top:${y}%;opacity:${opacity};box-shadow:0 0 ${size*2}px 1px rgba(255,255,255,0.4);`;
                container.appendChild(star);
            }
            // 中星（多）
            for (let i = 0; i < 180; i++) {
                const star = document.createElement('div');
                star.className = 'star';
                const size = Math.random() * 1.2 + 0.4;
                const x = Math.random() * 100, y = Math.random() * 100;
                const opacity = Math.random() * 0.45 + 0.25;
                star.style.cssText = `position:absolute;width:${size}px;height:${size}px;background:#fff;border-radius:50%;left:${x}%;top:${y}%;opacity:${opacity};`;
                container.appendChild(star);
            }
            // 小星（很多、淡）
            for (let i = 0; i < 320; i++) {
                const star = document.createElement('div');
                star.className = 'star';
                const size = Math.random() * 0.8 + 0.3;
                const x = Math.random() * 100, y = Math.random() * 100;
                const opacity = Math.random() * 0.35 + 0.1;
                star.style.cssText = `position:absolute;width:${size}px;height:${size}px;background:#fff;border-radius:50%;left:${x}%;top:${y}%;opacity:${opacity};`;
                container.appendChild(star);
            }
        }

        // 标题栏窗口控制（pywebview 无边框时显示并绑定 minimize/maximize/close）
        function initWindowControls(retried) {
            var wrap = document.getElementById('electronWindowControls');
            if (!wrap) return;
            var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
            if (api && typeof api.minimize_window === 'function' && typeof api.close_window === 'function') {
                wrap.classList.remove('hidden');
                document.getElementById('electronMinBtn') && document.getElementById('electronMinBtn').addEventListener('click', function() { try { api.minimize_window(); } catch (e) {} });
                document.getElementById('electronMaxBtn') && document.getElementById('electronMaxBtn').addEventListener('click', function() { try { api.maximize_toggle && api.maximize_toggle(); } catch (e) {} });
                document.getElementById('electronCloseBtn') && document.getElementById('electronCloseBtn').addEventListener('click', function() { try { api.close_window(); } catch (e) {} });
                return;
            }
            if (!retried) setTimeout(function() { initWindowControls(true); }, 300);
        }

        // 秒 -> "X小时Y分钟"
        function formatWorkTime(seconds) {
            if (seconds == null || seconds < 0) return '0分钟';
            const s = Math.floor(seconds);
            const h = Math.floor(s / 3600);
            const m = Math.floor((s % 3600) / 60);
            if (h > 0 && m > 0) return h + '小时' + m + '分钟';
            if (h > 0) return h + '小时';
            if (m > 0) return m + '分钟';
            return s + '秒';
        }

        // 已连续用眼展示：满1小时显示「X小时X分钟」，不满1小时只显示「X分钟」；1分钟内不显示秒，显示 0 分钟
        function formatContinuousWorkTime(seconds) {
            if (seconds == null || seconds < 0) return '0 分钟';
            const s = Math.floor(seconds);
            if (s < 60) return '0 分钟';
            const h = Math.floor(s / 3600);
            const m = Math.floor((s % 3600) / 60);
            if (h >= 1) return (m > 0 ? h + '小时' + m + '分钟' : h + '小时');
            return m + '分钟';
        }

        // 仅更新「已连续用眼」等 work 文字 DOM，不触发图表/列表（供 10s 快照 + 1s 补间用）
        function renderWorkTextFromSeconds(sec) {
            try {
                var el = document.getElementById('restContinuousValue');
                if (el) el.textContent = formatContinuousWorkTime(sec);
            } catch (e) {}
        }

        // 本地「今日」YYYY-MM-DD（与后端 local_date 一致，避免 UTC 导致日期错位）
        function localTodayStr() {
            var d = new Date();
            var y = d.getFullYear();
            var m = String(d.getMonth() + 1).padStart(2, '0');
            var day = String(d.getDate()).padStart(2, '0');
            return y + '-' + m + '-' + day;
        }

        // 辅助函数：日期转 YYYY-MM-DD
        function toYMD(d) {
            var y = d.getFullYear(), m = d.getMonth() + 1, day = d.getDate();
            return y + '-' + (m < 10 ? '0' : '') + m + '-' + (day < 10 ? '0' : '') + day;
        }

        // 辅助函数：日期转 MM-DD（去掉年份）
        function toMD(d) {
            var m = d.getMonth() + 1, day = d.getDate();
            return (m < 10 ? '0' : '') + m + '-' + (day < 10 ? '0' : '') + day;
        }

        // 辅助函数：YYYY-MM-DD 转 Date
        function parseYMD(s) {
            var parts = (s || '').split('-');
            if (parts.length !== 3) return null;
            var d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
            return isNaN(d.getTime()) ? null : d;
        }

        // 仅 HTTP：每 10s 拉 /api/snapshot，返回 { status, data } 便于埋点带 http_status
        function fetchSnapshot(params) {
            var base = (typeof window !== 'undefined' && window.location) ? (window.location.origin || '') : '';
            if (!base || base === 'null') {
                var loc = window.location;
                base = (loc.protocol || 'http:') + '//' + (loc.host || '127.0.0.1');
            }
            var q = 'date=' + encodeURIComponent(params.date || '') + '&range=' + encodeURIComponent(params.range || 'day');
            if (params.range_start) q += '&range_start=' + encodeURIComponent(params.range_start);
            if (params.range_end) q += '&range_end=' + encodeURIComponent(params.range_end);
            return fetch(base + '/api/snapshot?' + q).then(function(r) {
                var status = r.status;
                return r.json().then(function(data) { return { status: status, data: data }; });
            });
        }
        window.fetchSnapshot = fetchSnapshot;

        var SNAPSHOT_POLL_MS = 10000;
        var __pollTimer = null;
        var __pollStarted = false;
        var __pollTickSeq = 0;
        var __pollScheduleSeq = 0;
        function buildParamsFromCurrentView() {
            var date = window.getViewDateStr ? window.getViewDateStr() : localTodayStr();
            var range = window.getViewRangeKey ? window.getViewRangeKey() : 'day';
            var params = { date: date, range: range };
            if (range === 'custom' && window.getCustomRange) {
                var r = window.getCustomRange();
                if (r) { params.range_start = r.start; params.range_end = r.end; }
            }
            return params;
        }
        function parseNum(v, def) { var n = parseInt(v, 10); return isNaN(n) ? def : n; }
        function updateRestPanel(snap) {
            if (!snap || snap.error) return;
            var rest = snap.rest || {};
            var state = snap.state || {};
            window.__localWorkS = Math.max(0, parseNum(rest.work_s, 0));
            window.__lastSnapMeta = {
                is_paused: !!(state && state.is_paused),
                is_dnd: !!(state && state.is_dnd),
                is_resting: !!(state && state.is_resting),
                idle_s: parseNum(snap.idle_s, 0)
            };
            renderWorkTextFromSeconds(window.__localWorkS);
            var elDnd = document.getElementById('dndBtn');
            if (elDnd) {
                elDnd.setAttribute('data-dnd', window.__lastSnapMeta.is_dnd ? 'true' : 'false');
                elDnd.textContent = window.__lastSnapMeta.is_dnd ? '取消勿扰' : '勿扰模式';
            }
            // 立即休息按钮：与 /api/rest/start 共用守卫状态，禁用时不可点；冷却结束用定时器立即恢复，不依赖 10s 轮询
            var startRestBtn = document.getElementById('startRestBtn');
            if (startRestBtn) {
                if (window.__restUnlockTimer) {
                    try { clearTimeout(window.__restUnlockTimer); } catch (e) {}
                    window.__restUnlockTimer = null;
                }
                var startEnabled = rest.start_enabled !== false;
                var blockReason = rest.start_block_reason || '';
                var unlockMs = Math.max(0, parseInt(rest.start_unlock_in_ms, 10) || 0);
                startRestBtn.disabled = !startEnabled;
                if (!startEnabled && blockReason === 'rest_cooldown' && unlockMs > 0) {
                    startRestBtn.title = '\u51c9\u5374\u4e2d\uff0c' + Math.ceil(unlockMs / 1000) + '\u79d2\u540e\u53ef\u7528';
                    window.__restUnlockTimer = setTimeout(function() {
                        window.__restUnlockTimer = null;
                        var btn = document.getElementById('startRestBtn');
                        if (btn) {
                            btn.disabled = false;
                            btn.title = '';
                        }
                    }, unlockMs);
                } else if (!startEnabled && blockReason === 'rest_active') {
                    startRestBtn.title = '\u4f11\u606f\u8fdb\u884c\u4e2d';
                } else if (startEnabled) {
                    startRestBtn.title = '';
                } else {
                    startRestBtn.title = '\u6682\u4e0d\u53ef\u7528';
                }
            }
        }

        var __refreshInFlight = false;
        var __refreshPending = false;
        window.uiTransitioning = false;
        window.pendingRefresh = false;

        async function refreshNow(reason, params) {
            if (__refreshInFlight) {
                __refreshPending = true;
                try { if (window.postDiag) window.postDiag('refresh_now_skip', { reason: reason || 'unknown', inflight: true, pending: true }); } catch (e) {}
                return { ok: false };
            }
            __refreshInFlight = true;
            var result = { ok: false };
            try {
                var res = await fetchSnapshot(params || buildParamsFromCurrentView());
                var snap = (res && res.data) !== undefined ? res.data : res;
                window.__lastSnapshot = snap;
                (function() {
                    var usage = (snap && snap.vm && snap.vm.daily_usage) ? snap.vm.daily_usage : (snap && snap.range_daily_usage) ? snap.range_daily_usage : {};
                    var daily_usage_len = typeof usage === 'object' && usage !== null ? Object.keys(usage).length : 0;
                    var total_s = snap && (snap.today_total_seconds !== undefined && snap.today_total_seconds !== null) ? snap.today_total_seconds : (snap && snap.stats_total_seconds !== undefined) ? snap.stats_total_seconds : undefined;
                    try {
                        if (window.postDiag) window.postDiag('snapshot_got', {
                            keys: snap ? Object.keys(snap) : [],
                            daily_usage_len: daily_usage_len,
                            total_s: total_s,
                            snap_error: (snap && snap.error) ? String(snap.error) : undefined
                        });
                    } catch (e) {}
                })();
                (function() {
                    var viewDate = window.getViewDateStr ? window.getViewDateStr() : localTodayStr();
                    var today = localTodayStr();
                    var rangeKey = (snap && snap.range_key) != null ? snap.range_key : undefined;
                    var timeRange = window.getViewRangeKey ? window.getViewRangeKey() : 'day';
                    try { if (window.postDiag) window.postDiag('snapshot_ctx', { viewDate: viewDate, today: today, rangeKey: rangeKey, timeRange: timeRange }); } catch (e) {}
                })();
                if (window.postDiag) window.postDiag('apply_rest_begin', {});
                try {
                    updateRestPanel(snap);
                    if (window.postDiag) window.postDiag('apply_rest_ok', {});
                } catch (e) {
                    if (window.postDiag) window.postDiag('apply_rest_fail', { message: (e && e.message) || String(e), stack: (e && e.stack) || '' });
                }
                var rest = (snap && snap.rest) ? snap.rest : {};
                if (window.uiTransitioning) {
                    if (window.postDiag) window.postDiag('apply_skip', { reason: 'uiTransitioning' });
                    window.pendingRefresh = true;
                    result.ok = true;
                    return result;
                }
                // 视图切换（time_range_change）和日历选择（calendar_change）时强制刷新，忽略日期检查
                var isForcedRefresh = (reason === 'time_range_change' || reason === 'calendar_change');
                var viewDate = window.getViewDateStr ? window.getViewDateStr() : localTodayStr();
                if (!isForcedRefresh && viewDate !== localTodayStr()) {
                    if (window.postDiag) window.postDiag('apply_skip', { reason: 'viewDate_not_today' });
                    result.ok = true;
                    return result;
                }
                var appViewEl = document.getElementById('appView');
                var appVisible = appViewEl && !appViewEl.classList.contains('hidden');
                if (appVisible) {
                    if (window.postDiag) window.postDiag('apply_left_begin', {});
                    try {
                        updateLeftPanelFromSnapshot(snap, { anim: false });
                        if (window.postDiag) window.postDiag('apply_left_ok', {});
                    } catch (e) {
                        if (window.postDiag) window.postDiag('apply_left_fail', { message: (e && e.message) || String(e), stack: (e && e.stack) || '' });
                    }
                    if (window.postDiag) window.postDiag('apply_right_begin', {});
                    try {
                        updateRightPanelFromSnapshot(snap, { anim: false });
                        if (window.postDiag) window.postDiag('apply_right_ok', {});
                    } catch (e) {
                        if (window.postDiag) window.postDiag('apply_right_fail', { message: (e && e.message) || String(e), stack: (e && e.stack) || '' });
                    }
                } else {
                    if (window.postDiag) window.postDiag('apply_category_begin', {});
                    try {
                        updateCategoryViewFromSnapshot(snap, { anim: false });
                        if (window.postDiag) window.postDiag('apply_category_ok', {});
                    } catch (e) {
                        if (window.postDiag) window.postDiag('apply_category_fail', { message: (e && e.message) || String(e), stack: (e && e.stack) || '' });
                    }
                    if (window.postDiag) window.postDiag('apply_right_begin', {});
                    try {
                        updateRightPanelFromSnapshot(snap, { anim: false });
                        if (window.postDiag) window.postDiag('apply_right_ok', {});
                    } catch (e) {
                        if (window.postDiag) window.postDiag('apply_right_fail', { message: (e && e.message) || String(e), stack: (e && e.stack) || '' });
                    }
                }
                (function reapplyHoverStateAfterRefresh() {
                    var hoverState = window.__hoverState || { chart: null, key: null, ts: 0 };
                    if (hoverState.key) {
                        window.statsHighlightKey = hoverState.key;
                        if (typeof applyStatsHighlightToPieSilent === 'function') applyStatsHighlightToPieSilent();
                        if (window.timeBarsChartInstance && typeof applyStatsHighlightToTimeBars === 'function') applyStatsHighlightToTimeBars();
                        if (hoverState.ts && (Date.now() - hoverState.ts < 800) && window.appChartInstance) {
                            window.appChartInstance.update();
                        }
                    }
                })();
                if (typeof window.updateTopDateFromSnapshot === 'function') window.updateTopDateFromSnapshot(snap);
                try { if (window.__eyecareHardUiLog) window.__eyecareHardUiLog('refresh_now_ok', { reason: reason || 'unknown' }); } catch (e) {}
                result.ok = true;
                return result;
            } catch (e) {
                try { if (window.__eyecareHardUiLog) window.__eyecareHardUiLog('refresh_now_fail', { reason: reason || 'unknown', err: String(e && e.message || e) }); } catch (e2) {}
                return result;
            } finally {
                __refreshInFlight = false;
                if (__refreshPending) {
                    __refreshPending = false;
                    refreshNow(reason || 'pending');
                } else {
                    if (reason === 'timer' && window.__scheduleNextPoll) window.__scheduleNextPoll();
                }
            }
        }

        var __immediateTimer = null;
        function requestImmediateRefresh(reason) {
            if (__immediateTimer) clearTimeout(__immediateTimer);
            __immediateTimer = setTimeout(function() {
                __immediateTimer = null;
                refreshNow(reason || 'immediate');
            }, 250);
        }
        window.requestImmediateRefresh = requestImmediateRefresh;
        window.refreshNow = refreshNow;

        function initSnapshotPoll() {
            if (__pollStarted) {
                try { if (window.postDiag) window.postDiag('snapshot_poll_init_skip', { reason: 'already_started' }); } catch (e) {}
                return;
            }
            __pollStarted = true;
            if (__pollTimer != null) { clearTimeout(__pollTimer); __pollTimer = null; }
            try { if (window.__eyecareHardUiLog) window.__eyecareHardUiLog('snapshot_poll_start', {}); } catch (e) {}
            var pollStartTime = Date.now();
            var POLL_GRACE_MS = 2500;
            var POLL_FAIL_THRESHOLD = 3;
            var consecutiveFailCount = 0;

            window.__localWorkS = 0;
            window.__lastSnapMeta = null;

            function showSnapshotFailUi() {
                setLeftPanelNoDataOrError('连接后端失败，请通过 EyE Care 应用启动');
            }

            window.refreshLeftPanelForViewDate = function() {
                var params = buildParamsFromCurrentView();
                fetchSnapshot(params)
                    .then(function(result) {
                        var snap = result && result.data !== undefined ? result.data : result;
                        window.__lastSnapshot = snap;
                        updateRestPanel(snap);
                        updateLeftPanelFromSnapshot(snap, { anim: false });
                        updateCategoryViewFromSnapshot(snap, { anim: false });
                        updateRightPanelFromSnapshot(snap, { anim: false });
                        if (typeof window.updateTopDateFromSnapshot === 'function') window.updateTopDateFromSnapshot(snap);
                    })
                    .catch(function() { showSnapshotFailUi(); });
            };

            function poll() {
                __pollTickSeq += 1;
                try { if (window.__eyecareHardUiLog) window.__eyecareHardUiLog('snapshot_poll_tick', { source: 'timer', tickSeq: __pollTickSeq }); } catch (e) {}
                refreshNow('timer')
                    .then(function(r) {
                        if (r && r.ok) consecutiveFailCount = 0;
                        else {
                            consecutiveFailCount++;
                            var pastGrace = (Date.now() - pollStartTime) >= POLL_GRACE_MS;
                            if (consecutiveFailCount >= POLL_FAIL_THRESHOLD && pastGrace) showSnapshotFailUi();
                        }
                    })
                    .catch(function(err) {
                        var errMsg = (err && (err.message || String(err))) || 'unknown';
                        try { if (window.__eyecareHardUiLog) window.__eyecareHardUiLog('snapshot_poll_fail', { err: errMsg }); } catch (e) {}
                        consecutiveFailCount++;
                        var pastGrace = (Date.now() - pollStartTime) >= POLL_GRACE_MS;
                        if (consecutiveFailCount >= POLL_FAIL_THRESHOLD && pastGrace) showSnapshotFailUi();
                    });
            }
            window.__scheduleNextPoll = function() {
                if (__pollTimer != null) { clearTimeout(__pollTimer); __pollTimer = null; }
                __pollScheduleSeq += 1;
                __pollTimer = setTimeout(function() { __pollTimer = null; poll(); }, SNAPSHOT_POLL_MS);
                try { if (window.postDiag) window.postDiag('snapshot_poll_scheduled', { scheduleSeq: __pollScheduleSeq, delayMs: SNAPSHOT_POLL_MS }); } catch (e) {}
            };
            poll();
            setTimeout(function() { requestImmediateRefresh('init'); }, 100);
        }

        // 页面加载完成后初始化所有功能（日期选择器需在 snapshot 轮询前初始化，以便 getViewDateStr 可用）
        // ----------------------------
        function hardUiLog(stage, extra) {
            try {
                var base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
                if (!base || base === 'null') return;
                var payload = {
                    msg: 'ui',
                    src: 'main_ui',
                    stage: String(stage || ''),
                    ts: Date.now(),
                    href: (window.location && window.location.href) ? window.location.href : '',
                    extra: extra || null
                };
                fetch(base + '/api/diag/log', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Eyecare-Source': 'main_ui' },
                    body: JSON.stringify(payload),
                    keepalive: true
                }).catch(function() {});
            } catch (e) {}
        }
        window.__eyecareHardUiLog = hardUiLog;

        function stabilizeChart(canvasId, getChartFn) {
            try {
                const c = document.getElementById(canvasId);
                if (!c) return;

                const canObserveAndKick = function() {
                    const r = c.getBoundingClientRect();
                    if (!r || r.width < 2 || r.height < 2) return false;

                    const kick = function() {
                        const ch = getChartFn();
                        if (!ch) return;
                        const rr = c.getBoundingClientRect();
                        const w = Math.round(rr.width), h = Math.round(rr.height);
                        const last = ch.__lastKickSize;
                        if (last && last.w === w && last.h === h) return;
                        ch.__lastKickSize = { w: w, h: h };
                        try { ch.resize(); } catch (e) {}
                        try { ch.update('none'); } catch (e) {}
                    };

                    requestAnimationFrame(function() {
                        requestAnimationFrame(function() { kick('kick_raf2'); });
                    });
                    setTimeout(function() { kick('kick_t150'); }, 150);
                    setTimeout(function() { kick('kick_t600'); }, 600);

                    if (!window.__chartResizeObservers) window.__chartResizeObservers = {};
                    if (!window.__chartResizeObservers[canvasId]) {
                        const ro = new ResizeObserver(function() {
                            const rr = c.getBoundingClientRect();
                            if (!rr || rr.width < 2 || rr.height < 2) return;
                            const ch = getChartFn();
                            if (!ch) return;
                            const w = Math.round(rr.width), h = Math.round(rr.height);
                            const last = ch.__lastKickSize;
                            if (last && last.w === w && last.h === h) return;
                            ch.__lastKickSize = { w: w, h: h };
                            try { ch.resize(); } catch (e) {}
                            try { ch.update('none'); } catch (e) {}
                        });
                        ro.observe(c);
                        window.__chartResizeObservers[canvasId] = ro;
                    }
                    return true;
                };

                if (!canObserveAndKick()) {
                    // hidden：先不做任何事，延迟重试（避免生成 0 几何）
                    setTimeout(function() { canObserveAndKick(); }, 300);
                }
            } catch (e) {}
        }

        function applyChartGlobalDefaults() {
            try {
                if (!window.Chart) return;
                // 强制 hover 只命中真正被鼠标“压中”的扇区，避免整圈被判定为 active
                Chart.defaults.interaction = { mode: 'nearest', intersect: true };
                Chart.defaults.hover = { mode: 'nearest', intersect: true };
                Chart.defaults.elements.arc.hoverOffset = 18;
                Chart.defaults.elements.arc.hoverBorderWidth = 1.2;
                Chart.defaults.elements.arc.borderAlign = 'inner';
            } catch (e) {}
        }

        function safeInit(name, fn) {
            try { if (typeof fn === 'function') fn(); } catch (e) { try { if (window.__eyecareHardUiLog) window.__eyecareHardUiLog('init_error', { init: name, err: (e && (e.message || String(e))) || 'unknown' }); } catch (e2) {} }
        }

        document.addEventListener('DOMContentLoaded', () => {
            // 优先初始化视图切换功能
            safeInit('initViewTabs', initViewTabs);
            safeInit('createStars', createStars);
            safeInit('initWindowControls', initWindowControls);
            safeInit('initDateSelector', initDateSelector);
            safeInit('applyChartGlobalDefaults', applyChartGlobalDefaults);
            safeInit('initTimeBarsChart', initTimeBarsChart);

            requestAnimationFrame(function() {
                requestAnimationFrame(function() {
                    try {
                        stabilizeChart('appChart', function() { return window.appChartInstance; });
                        stabilizeChart('timeBarsChart', function() { return window.timeBarsChartInstance; });
                    } catch (e) {}
                });
            });

            safeInit('initRestModal', initRestModal);

            safeInit('initRestSettings', initRestSettings);
            safeInit('initSettingsModal', initSettingsModal);
            safeInit('initUpdateCheckModal', initUpdateCheckModal);
            safeInit('initDndButton', initDndButton);
            safeInit('initBlueLightToggle', initBlueLightToggle);
            safeInit('initAppSettingsBtn', initAppSettingsBtn);
            safeInit('initBlacklistBtn', initBlacklistBtn);
            safeInit('initAppDetailModal', initAppDetailModal);
            safeInit('initCategoryDetailModal', initCategoryDetailModal);
            safeInit('initDataImportExport', initDataImportExport);

            // 轮询必须启动，单独调用并捕获以便日志
            try { initSnapshotPoll(); } catch (e) { try { if (window.__eyecareHardUiLog) window.__eyecareHardUiLog('snapshot_poll_init_error', { err: (e && (e.message || String(e))) || 'unknown' }); } catch (e2) {} }
        });