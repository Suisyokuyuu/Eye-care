from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import date, timedelta
from pathlib import Path
from collections import OrderedDict, defaultdict

from eye_care.core.models import CoreConfig
from eye_care.state.controller import AppController
from eye_care.state.utils import seconds_to_hhmmss, app_to_category
from eye_care.ui.top10bars import Top10Bars
from eye_care.ui.rest_overlay import RestOverlay
from eye_care.ui.tooltip import ToolTip
from eye_care.ui.notify import show_toast


class MainWindow:
    def __init__(self, root: tk.Tk, controller: AppController, data_dir: Path):
        self.root = root
        self.controller = controller
        self.data_dir = Path(data_dir)

        self.root.title("EyE Care")
        self.root.geometry("980x650")

        self.date_mode = tk.StringVar(value="today")
        self.group_mode = tk.StringVar(value="category")

        self._rest_overlay = None
        self._last_remind_seq = 0

        self._build_widgets()
        self._schedule_auto_refresh()

    def _config_path(self) -> Path:
        return self.data_dir / "config.json"

    def _load_config(self) -> dict:
        p = self._config_path()
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_config(self, obj: dict) -> None:
        self._config_path().write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_widgets(self) -> None:
        top_frame = ttk.Frame(self.root)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=8)

        row1 = ttk.Frame(top_frame)
        row1.pack(side=tk.TOP, fill=tk.X)

        self.status_label = ttk.Label(row1, text="状态：—")
        self.status_label.pack(side=tk.LEFT, padx=(0, 20))

        date_frame = ttk.Frame(row1)
        date_frame.pack(side=tk.LEFT)
        ttk.Label(date_frame, text="日期范围：").pack(side=tk.LEFT)
        ttk.Radiobutton(date_frame, text="今天", variable=self.date_mode, value="today",
                        command=self.refresh_all).pack(side=tk.LEFT)
        ttk.Radiobutton(date_frame, text="本周", variable=self.date_mode, value="week",
                        command=self.refresh_all).pack(side=tk.LEFT, padx=(5, 0))

        group_frame = ttk.Frame(row1)
        group_frame.pack(side=tk.LEFT, padx=(20, 0))
        ttk.Label(group_frame, text="统计维度：").pack(side=tk.LEFT)
        ttk.Radiobutton(group_frame, text="按类别/应用", variable=self.group_mode, value="category",
                        command=self.refresh_all).pack(side=tk.LEFT)
        ttk.Radiobutton(group_frame, text="按应用短名", variable=self.group_mode, value="app",
                        command=self.refresh_all).pack(side=tk.LEFT, padx=(5, 0))

        row2 = ttk.Frame(top_frame)
        row2.pack(side=tk.TOP, fill=tk.X, pady=(6, 0))

        btn_frame = ttk.Frame(row2)
        btn_frame.pack(side=tk.LEFT)

        b_refresh = ttk.Button(btn_frame, text="刷新", command=self.refresh_all)
        b_refresh.pack(side=tk.LEFT, padx=5)
        ToolTip(b_refresh, "立即刷新主界面数据。")

        b_dnd = ttk.Button(btn_frame, text="勿扰模式", command=self.controller.toggle_dnd)
        b_dnd.pack(side=tk.LEFT, padx=5)
        ToolTip(b_dnd, "勿扰：不弹提醒气泡，浮窗也不提示“该休息”。需要手动退出。")

        b_watch = ttk.Button(btn_frame, text="观影模式", command=self.controller.toggle_watching)
        b_watch.pack(side=tk.LEFT, padx=5)
        ToolTip(b_watch, "观影：不弹提醒气泡，浮窗也不提示“该休息”。需要手动退出。")

        b_rest = ttk.Button(btn_frame, text="马上休息", command=self.rest_now)
        b_rest.pack(side=tk.LEFT, padx=5)
        ToolTip(b_rest, "立刻开始圆环倒计时。ESC 可提前结束。")

        b_set = ttk.Button(btn_frame, text="参数设置", command=self.open_settings)
        b_set.pack(side=tk.LEFT, padx=5)
        ToolTip(b_set, "设置空闲判定、连续工作多久提醒、休息时长。")

        b_save = ttk.Button(btn_frame, text="保存统计", command=self.save_now)
        b_save.pack(side=tk.LEFT, padx=5)
        ToolTip(b_save, "立即将统计写入 data/metrics.json。")

        b_import = ttk.Button(btn_frame, text="导入数据", command=self.import_data)
        b_import.pack(side=tk.LEFT, padx=5)

        b_export = ttk.Button(btn_frame, text="导出数据", command=self.export_data)
        b_export.pack(side=tk.LEFT, padx=5)

        body = ttk.Frame(self.root)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=10)

        left = ttk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        right = ttk.Frame(body)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False)

        ttk.Label(left, text="统计明细", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))

        table_frame = ttk.Frame(left)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        columns = ("name", "time", "pct")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)
        self.tree.heading("name", text="名称")
        self.tree.heading("time", text="时长")
        self.tree.heading("pct", text="占比")
        self.tree.column("name", width=380, anchor=tk.W)
        self.tree.column("time", width=140, anchor=tk.CENTER)
        self.tree.column("pct", width=100, anchor=tk.CENTER)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.top10_panel = Top10Bars(right, title="使用时间概览（Top 10）")
        self.top10_panel.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.refresh_all()

    # ---------------- data ----------------

    def _get_date_range(self):
        today = date.today()
        if self.date_mode.get() == "week":
            monday = today - timedelta(days=today.weekday())
            return monday, today
        return today, today

    def _aggregate_data(self):
        start, end = self._get_date_range()
        raw = self.controller.get_metrics_for_range(start, end)
        if not raw:
            return OrderedDict()

        agg = defaultdict(int)
        mode = self.group_mode.get()
        if mode == "app":
            for app, sec in raw.items():
                agg[app] += sec
        else:
            for app, sec in raw.items():
                agg[app_to_category(app)] += sec

        items = sorted(agg.items(), key=lambda x: x[1], reverse=True)
        return OrderedDict(items)

    # ---------------- refresh ----------------

    def refresh_all(self) -> None:
        self.refresh_status()
        self.refresh_table_and_top10()

    def refresh_status(self) -> None:
        st = self.controller.get_ui_status()
        self.status_label.config(text=f"{st.status_text}  |  {st.work_text}")

    def refresh_table_and_top10(self) -> None:
        data = self._aggregate_data()
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        total = sum(data.values()) or 1
        for name, sec in data.items():
            pct = sec / total * 100.0
            self.tree.insert("", tk.END, values=(name, seconds_to_hhmmss(sec), f"{pct:.1f}%"))

        self.top10_panel.update_data(data)

    # ---------------- save/import/export ----------------

    def save_now(self) -> None:
        try:
            self.controller.repo.save()
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def export_data(self) -> None:
        try:
            payload = self.controller.repo.export_all()
            export_id = payload.get("export_id", "export")
            default_name = f"eye_care_export_{export_id}.json"
            p = filedialog.asksaveasfilename(
                title="导出数据",
                defaultextension=".json",
                initialfile=default_name,
                filetypes=[("JSON", "*.json")],
            )
            if not p:
                return
            Path(p).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    def import_data(self) -> None:
        p = filedialog.askopenfilename(title="导入数据", filetypes=[("JSON", "*.json")])
        if not p:
            return
        try:
            obj = json.loads(Path(p).read_text(encoding="utf-8"))
            ok, reason = self.controller.repo.import_payload(obj)
            if not ok:
                messagebox.showwarning("导入被拒绝", reason or "未知原因")
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("导入失败", str(e))

    # ---------------- rest ----------------

    def rest_now(self) -> None:
        if self._rest_overlay:
            return
        rest_s = int(getattr(self.controller.engine.cfg, "rest_time_s", 300))

        def on_skip():
            # ESC：只是提前结束，不算“本轮完成”
            self._rest_overlay = None

        def on_complete():
            self.controller.complete_rest()
            self._rest_overlay = None

        self._rest_overlay = RestOverlay(self.root, rest_s, on_skip=on_skip, on_complete=on_complete)

    # ---------------- settings ----------------

    def open_settings(self) -> None:
        cfg_file = self._load_config()
        win = tk.Toplevel(self.root)
        win.title("参数设置")
        win.geometry("380x260")
        win.transient(self.root)
        win.grab_set()

        def _row(parent, label, default, tip):
            f = ttk.Frame(parent)
            f.pack(fill=tk.X, padx=12, pady=8)
            l = ttk.Label(f, text=label, width=22)
            l.pack(side=tk.LEFT)
            v = tk.StringVar(value=str(default))
            e = ttk.Entry(f, textvariable=v)
            e.pack(side=tk.RIGHT, fill=tk.X, expand=True)
            ToolTip(l, tip)
            ToolTip(e, tip)
            return v

        idle_s = _row(
            win,
            "空闲判定(秒)",
            cfg_file.get("idle_threshold_s", self.controller.engine.cfg.idle_threshold_s),
            "超过该秒数无输入，则判定为空闲（IDLE）。",
        )
        work_m = _row(
            win,
            "连续工作提醒(分钟)",
            cfg_file.get("work_threshold_min", int(self.controller.engine.cfg.work_threshold_s / 60)),
            "连续工作达到该分钟数：弹一次气泡，浮窗持续提醒；如果你不休息，下一轮时间再弹一次。",
        )
        rest_m = _row(
            win,
            "休息完成(分钟)",
            cfg_file.get("rest_time_min", int(self.controller.engine.cfg.rest_time_s / 60)),
            "IDLE 持续达到该分钟数，视为本轮休息完成并开启新一轮（连续工作归零）。",
        )

        def save_apply():
            try:
                idle = max(5, int(idle_s.get()))
                work = max(1, int(work_m.get()))
                rest = max(1, int(rest_m.get()))
                self._save_config({"idle_threshold_s": idle, "work_threshold_min": work, "rest_time_min": rest})

                self.controller.engine.cfg = CoreConfig(
                    idle_threshold_s=idle,
                    work_threshold_s=work * 60,
                    rest_time_s=rest * 60,
                )
                self.refresh_all()
                win.destroy()
            except Exception as e:
                messagebox.showerror("设置失败", str(e))

        btn = ttk.Frame(win)
        btn.pack(fill=tk.X, padx=12, pady=12)
        ttk.Button(btn, text="保存并应用", command=save_apply).pack(side=tk.RIGHT)

    # ---------------- auto refresh + bubble ----------------

    def _schedule_auto_refresh(self) -> None:
        st = self.controller.get_ui_status()

        # ✅ 气泡触发：主线程检查 remind_seq
        if (st.remind_seq != self._last_remind_seq) and (not st.dnd) and (not st.watching) and st.run_mode != "IDLE":
            self._last_remind_seq = st.remind_seq
            show_toast(self.root, "护眼提醒", "该休息一下了（浮窗右键：马上休息）")
        else:
            self._last_remind_seq = st.remind_seq

        self.refresh_status()
        self.root.after(1000, self._schedule_auto_refresh)
