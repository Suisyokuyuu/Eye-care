# Performance Analysis

Date: 2026-06-12

This note records the first-pass performance investigation after the frontend fixes.

## Observed Symptoms

- Opening the main UI in the Python/Qt host can push CPU usage to about 8-10%.
- Opening more pages increases total memory usage to about 1.2 GB.
- The current runtime is a Python host with Qt WebEngine, Flask routes, QWebChannel bridge calls, Chart.js, and background sampling services.

## Process Snapshot

A local process check showed the largest memory users were:

| Process | Working Set | Private Memory | Notes |
| --- | ---: | ---: | --- |
| `QtWebEngineProcess` | ~959 MB | ~887 MB | Largest memory consumer |
| `python` | ~398 MB | ~894 MB | Host process, controller, Flask, Qt shell |
| Other WebView/WebEngine processes | tens to hundreds of MB | varies | Additional browser/render processes |

Conclusion: the 1.2 GB footprint is mostly the Qt WebEngine/Chromium process model plus the Python host, not just application data in Python.

## Main Performance Hotspots

### 1. Qt WebEngine Pages

Likely the biggest memory contributor.

Relevant code:

- `eye_care/qt/runtime_shell.py`
- Main UI uses `QWebEngineView`.
- Rest overlays are created per screen in `_ensure_rest_overlays`.
- Notify overlay also creates a WebEngine window.

Impact:

- Each main UI, rest overlay, and notify page can add WebEngine renderer/browser memory.
- Multi-monitor rest overlays can create multiple WebEngine pages.
- Memory can remain high even after pages are hidden if views are reused and not destroyed.

### 2. Notification Polling Every Second

`NotifierService` polls `controller.snapshot_today(mark_prompted=False)` every second.

Relevant code:

- `eye_care/notify/notifier_service.py`
- `eye_care/qt/runtime_shell.py`, where `poll_interval_s=1.0`

Impact:

- This runs continuously even when the main UI is not visible.
- It calls into snapshot/runtime state logic at high frequency.
- It overlaps with the controller tick loop.

### 3. Controller Tick Loop Every Second

The controller loop runs every `sample_interval_s`, defaulting to 1 second.

Relevant code:

- `eye_care/controller/app_controller.py`
- `eye_care/probes/win_idle.py`
- `eye_care/probes/win_foreground.py`

Impact:

- Each active tick queries idle time and foreground app.
- Foreground detection calls Windows APIs and may open/query the foreground process.
- This is expected background work, but it contributes steady CPU.

### 4. Main UI Snapshot Polling and Chart Refresh

The main UI polls snapshots every 15 seconds.

Relevant code:

- `eye_care/ui/web/assets/app.js`
- `SNAPSHOT_POLL_MS = 15000`
- `refreshNow`
- Chart update paths for category/app/timebar charts

Impact:

- Each snapshot crosses the JS-to-Python bridge or HTTP fallback.
- Snapshot application updates DOM and Chart.js instances.
- Chart.js inside Qt WebEngine is heavier than in a normal browser tab.

### 5. Diagnostic Logging

Logs show frequent bridge and UI diagnostics:

- `qt.bridge.get_snapshot`
- `qt.bridge.get_icon_data_url`
- `qt.bridge.rest_overlay_log`
- frontend hard UI logs

Relevant code:

- `eye_care/ui/web/assets/app.js`
- `eye_care/ui/web/rest/rest.js`
- `eye_care/qt/runtime_shell.py`

Impact:

- Rest overlay uses a 250 ms tick and can send logs back to Python.
- Main UI snapshot polling also emits diagnostic logs.
- Logging adds file I/O and JS/Python bridge traffic.

### 6. Icon Loading Through Base64 Data URLs

App icons are loaded via bridge as base64 data URLs when possible.

Relevant code:

- `eye_care/services/config_service.py`
- `eye_care/ui/web/assets/app.js`

Impact:

- Icon PNG files on disk are small, but base64 data URLs are duplicated in JS memory and DOM image attributes.
- Calling many `getIconDataUrl` bridge methods during app list rendering adds bridge overhead.
- Browser-native URL caching via `/api/icon?app=...` would likely be cheaper.

## Priority Optimization Plan

1. Reduce `NotifierService` polling.
   - Change from 1 second to 5-10 seconds, or make it event-driven from controller rest state changes.
   - Prefer a lightweight rest-status method instead of full `snapshot_today`.

2. Pause or slow main UI polling when hidden/minimized.
   - Detect window visibility/minimize state.
   - Keep rest status responsive only when needed.
   - Avoid Chart.js updates while the page is not visible.

3. Gate diagnostic logs behind debug mode.
   - Disable frontend `hardUiLog` and rest overlay logs in normal mode.
   - Keep only warnings/errors and user-action logs.

4. Rework rest/notify WebEngine lifecycle.
   - Create overlays lazily.
   - Consider destroying WebEngine views after rest ends, or keeping only one reusable lightweight page when possible.
   - This is the highest-impact memory area but requires careful UI testing.

5. Serve icons as normal image URLs instead of bridge-returned data URLs.
   - Prefer `<img src="/api/icon?app=...">`.
   - Let Qt WebEngine cache image responses.
   - Avoid storing base64 strings in `window.__EYECARE_APP_ICON_CACHE__`.

6. Cache or split snapshot payloads.
   - Separate fast rest/status polling from heavier stats/chart payloads.
   - Avoid recomputing hourly/category/range data unless the visible view needs it.

## Expected Wins

- CPU: first wins should come from reducing notifier polling and disabling normal-mode diagnostic logging.
- Memory: first meaningful wins should come from WebEngine lifecycle changes and reducing duplicated base64 icon data.
- Responsiveness: pausing Chart.js updates while hidden should reduce UI stalls and background work.

## Initial Recommendation

Start with low-risk changes:

1. Increase `NotifierService` interval or replace it with lightweight rest-state polling.
2. Disable frontend/overlay diagnostic logs unless debug mode is enabled.
3. Stop main UI snapshot polling while the main window is hidden/minimized.

Then tackle WebEngine lifecycle changes after the low-risk CPU fixes are validated.
