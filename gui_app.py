"""
GUI application for A-stock data collection, analysis, and filtering.
Uses tkinter for the interface.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import webbrowser
from pathlib import Path
from datetime import datetime
import pandas as pd

from data_collector import run_pipeline
from data_exporter import (
    filter_stocks, export_to_excel, filter_export, _to_display_df,
    FILTER_REGISTRY, DEFAULT_FILTER_NAME,
)
from cache import StockCache


class StockAnalyzerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("A股数据分析工具")
        self.root.geometry("900x600")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.all_data = None
        self.filtered_data = None
        self.filter_name: str = DEFAULT_FILTER_NAME
        self.custom_params: dict = {}  # Store user-customized parameters
        self.is_collecting: bool = False
        self._shutting_down: bool = False
        self._collect_thread: threading.Thread | None = None

        self._build_ui()

    def _build_ui(self):
        # Top frame for buttons
        btn_frame = ttk.Frame(self.root, padding=10)
        btn_frame.pack(side=tk.TOP, fill=tk.X)

        self.btn_collect = ttk.Button(
            btn_frame, text="收集股票数据", command=self._on_collect
        )
        self.btn_collect.pack(side=tk.LEFT, padx=5)

        # Filter selection
        ttk.Label(btn_frame, text="筛选:").pack(side=tk.LEFT, padx=(15, 3))
        self.filter_var = tk.StringVar(value=DEFAULT_FILTER_NAME)
        self.filter_combo = ttk.Combobox(
            btn_frame,
            textvariable=self.filter_var,
            values=list(FILTER_REGISTRY.keys()),
            state="readonly",
            width=18,
        )
        self.filter_combo.pack(side=tk.LEFT, padx=5)
        self.filter_combo.current(list(FILTER_REGISTRY.keys()).index(DEFAULT_FILTER_NAME))

        self.btn_filter = ttk.Button(
            btn_frame, text="执行筛选", command=self._on_filter, state=tk.DISABLED
        )
        self.btn_filter.pack(side=tk.LEFT, padx=5)

        self.btn_params = ttk.Button(
            btn_frame, text="参数设置", command=self._on_params, state=tk.DISABLED
        )
        self.btn_params.pack(side=tk.LEFT, padx=2)

        self.btn_clear_filter = ttk.Button(
            btn_frame, text="取消筛选", command=self._on_clear_filter, state=tk.DISABLED
        )
        self.btn_clear_filter.pack(side=tk.LEFT, padx=2)

        self.btn_export_all = ttk.Button(
            btn_frame, text="导出全部数据", command=self._on_export_all, state=tk.DISABLED
        )
        self.btn_export_all.pack(side=tk.LEFT, padx=5)

        self.btn_export_filtered = ttk.Button(
            btn_frame, text="导出筛选结果", command=self._on_export_filtered, state=tk.DISABLED
        )
        self.btn_export_filtered.pack(side=tk.LEFT, padx=5)

        # Status label
        self.status_var = tk.StringVar(value="就绪")
        status_label = ttk.Label(btn_frame, textvariable=self.status_var, foreground="blue")
        status_label.pack(side=tk.RIGHT, padx=10)

        # Progress bar
        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(side=tk.TOP, fill=tk.X)

        # Treeview for data display
        tree_frame = ttk.Frame(self.root, padding=10)
        tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_frame, show="headings")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scrollbar.set)

        # Pagination
        pg_frame = ttk.Frame(self.root, padding=(10, 0))
        pg_frame.pack(side=tk.TOP, fill=tk.X)
        self._pg_state = {"offset": 0, "page_size": 200, "df": None}
        self.btn_prev = ttk.Button(pg_frame, text="<< 上一页", command=self._on_prev_page, state=tk.DISABLED)
        self.btn_prev.pack(side=tk.LEFT, padx=5)
        self.pg_label = ttk.Label(pg_frame, text="")
        self.pg_label.pack(side=tk.LEFT, padx=5)
        self.btn_next = ttk.Button(pg_frame, text="下一页 >>", command=self._on_next_page, state=tk.DISABLED)
        self.btn_next.pack(side=tk.LEFT, padx=5)

        # Log frame
        log_frame = ttk.Frame(self.root, padding=10)
        log_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.log_text = tk.Text(log_frame, height=6, state=tk.DISABLED)
        self.log_text.pack(fill=tk.X)

    def _log(self, message):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _set_columns(self, df):
        """Configure treeview columns from DataFrame."""
        self.tree.delete(*self.tree.get_children())
        columns = list(df.columns)
        self.tree["columns"] = columns
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100, anchor=tk.CENTER)

    def _display_df(self, df: pd.DataFrame) -> pd.DataFrame:
        return _to_display_df(df, map_yn=True)

    def _populate_tree(self, df: pd.DataFrame):
        # Filter out index rows for display (keep them in self.all_data for filtering)
        from data_exporter import _is_index_row
        display_df = df[~df.apply(_is_index_row, axis=1)].copy()
        display_df = self._display_df(display_df)
        
        # 诊断MA在显示DataFrame中的状态
        ma_cols = ["5日均价", "20日均价", "60日均价", "120日均价"]
        for col in ma_cols:
            if col in display_df.columns:
                n_valid = display_df[col].notna().sum()
                sample = display_df[col].dropna().head(2).tolist()
                print(f"[GUI DIAG] {col}: 有效={n_valid}/{len(display_df)}, 示例={sample}")
            else:
                print(f"[GUI DIAG] {col}: 列不存在!")
        
        self._pg_state["df"] = display_df
        self._pg_state["offset"] = 0
        self._render_page()

    def _render_page(self):
        df = self._pg_state["df"]
        if df is None:
            return
        offset = self._pg_state["offset"]
        page = df.iloc[offset: offset + self._pg_state["page_size"]]
        self.tree.delete(*self.tree.get_children())
        self._set_columns(df)
        for _, row in page.iterrows():
            values = ["" if pd.isna(v) else v for v in row]
            self.tree.insert("", tk.END, values=values)
        total = len(df)
        end = min(offset + self._pg_state["page_size"], total)
        self.pg_label.configure(text=f"第 {offset+1}-{end} 行 / 共 {total} 行")
        self.btn_prev.configure(state=(tk.NORMAL if offset > 0 else tk.DISABLED))
        self.btn_next.configure(state=(tk.NORMAL if end < total else tk.DISABLED))

    def _on_tree_double_click(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        cols = self.tree["columns"]
        if "代码" not in cols:
            return
        idx = list(cols).index("代码")
        code = str(vals[idx]).strip().zfill(6)
        if not code or code == "000300":
            return
        url = f"https://stockpage.10jqka.com.cn/{code}/"
        self._log(f"打开: {url}")
        webbrowser.open(url)

    def _on_prev_page(self):
        self._pg_state["offset"] = max(0, self._pg_state["offset"] - self._pg_state["page_size"])
        self._render_page()

    def _on_next_page(self):
        df = self._pg_state["df"]
        if df is None:
            return
        new_offset = self._pg_state["offset"] + self._pg_state["page_size"]
        if new_offset < len(df):
            self._pg_state["offset"] = new_offset
            self._render_page()

    def _on_collect(self):
        if self.is_collecting:
            messagebox.showinfo("提示", "数据收集中,请稍候")
            return
        self.is_collecting = True
        self.btn_collect.configure(state=tk.DISABLED)
        self.status_var.set("正在收集数据,请稍候...")
        self.progress.configure(value=0)
        self._log("开始收集 A 股数据...")

        thread = threading.Thread(target=self._collect_task, daemon=True)
        self._collect_thread = thread
        thread.start()

    def _collect_task(self):
        cache = None
        try:
            cache = StockCache(base_dir=Path(__file__).parent / "data_cache")
            _last_log = [""]

            def _progress(done: int, total: int, msg: str):
                if self._shutting_down:
                    return
                pct = min(100, int(done / total * 100)) if total else 0
                self.root.after(0, lambda v=pct: self.progress.configure(value=v))
                self.root.after(0, lambda m=msg: self.status_var.set(m))
                is_stage = total <= 10
                if is_stage or (done % 50 == 0 or done == total):
                    if msg and msg != _last_log[0]:
                        _last_log[0] = msg
                        self.root.after(0, lambda m=msg: self._log(m))

            result = run_pipeline(cache, force_refresh=False, progress_callback=_progress)
            if self._shutting_down:
                return
            self.all_data = result["all_data"]
            self.root.after(0, self._on_collect_done)
        except Exception as e:
            if self._shutting_down:
                return
            self.root.after(0, lambda: self._on_collect_error(str(e)))
        finally:
            if cache is not None:
                try:
                    cache.close()
                except Exception:
                    pass

    def _on_collect_done(self):
        self.is_collecting = False
        self.progress.configure(value=100)
        self.btn_collect.configure(state=tk.NORMAL)
        self.btn_filter.configure(state=tk.NORMAL)
        self.btn_params.configure(state=tk.NORMAL)
        self.btn_export_all.configure(state=tk.NORMAL)
        # Count stocks only (exclude indices)
        from data_exporter import _is_index_row
        stock_count = len(self.all_data[~self.all_data.apply(_is_index_row, axis=1)])
        self.status_var.set(f"数据收集完成,共 {stock_count} 只股票")
        self._log("数据收集完成!")
        self._populate_tree(self.all_data)

    def _on_collect_error(self, error_msg):
        self.is_collecting = False
        self.progress.configure(value=0)
        self.btn_collect.configure(state=tk.NORMAL)
        self.status_var.set("数据收集失败")
        self._log(f"错误: {error_msg}")
        messagebox.showerror("错误", f"数据收集失败:\n{error_msg}")

    def _on_params(self):
        """Show parameter configuration dialog for the selected filter."""
        name = self.filter_var.get()
        ftype, default_criteria = FILTER_REGISTRY.get(name, FILTER_REGISTRY[DEFAULT_FILTER_NAME])
        
        # Create dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"参数设置 - {name}")
        dialog.geometry("400x350")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Get current parameters (custom or default)
        current = self.custom_params.get(name, {}).copy()
        for key, val in default_criteria.items():
            if key not in current and key != "type":
                current[key] = val
        
        # Create parameter inputs
        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)
        
        param_vars = {}
        row = 0
        
        # Filter out 'type' from editable parameters
        editable_params = {k: v for k, v in current.items() if k != "type"}
        
        # Index options for dropdown
        index_options = {
            "沪深300": "csi300",
            "中证500": "csi500",
            "中证1000": "csi1000",
            "上证指数": "sh000001",
            "深证成指": "sz399001",
            "科创50": "star50",
            "创业板指数": "chinext",
        }
        index_display_to_key = {v: k for k, v in index_options.items()}
        
        # Window options for dropdown
        window_options = {
            "5天": 5,
            "10天": 10,
            "20天": 20,
            "30天": 30,
            "60天": 60,
        }
        window_display_to_value = {v: k for k, v in window_options.items()}
        
        # Golden mode options for dropdown
        golden_mode_options = {
            "双金叉": "both",
            "单金叉": "either",
        }
        golden_mode_display_to_value = {v: k for k, v in golden_mode_options.items()}
        
        # Death cross mode options for dropdown
        death_cross_mode_options = {
            "双死叉": "both",
            "单死叉": "either",
            "KDJ死叉": "kdj",
            "MACD死叉": "macd",
        }
        death_cross_mode_display_to_value = {v: k for k, v in death_cross_mode_options.items()}
        
        # Boolean options for dropdown
        bool_options = {
            "是": True,
            "否": False,
        }
        bool_display_to_value = {v: k for k, v in bool_options.items()}
        
        # MA period options for dropdown (only periods we actually calculate)
        ma_period_options = {
            "5天": 5,
            "10天": 10,
            "20天": 20,
            "60天": 60,
            "120天": 120,
        }
        ma_period_display_to_value = {v: k for k, v in ma_period_options.items()}
        
        for key, val in editable_params.items():
            ttk.Label(frame, text=self._param_label(key)).grid(row=row, column=0, sticky=tk.W, pady=5)
            
            if key == "vs_index":
                # Use dropdown for vs_index
                var = tk.StringVar()
                current_display = index_display_to_key.get(val, "沪深300")
                var.set(current_display)
                combo = ttk.Combobox(
                    frame, 
                    textvariable=var, 
                    values=list(index_options.keys()),
                    state="readonly",
                    width=18
                )
                combo.grid(row=row, column=1, pady=5, padx=5)
                param_vars[key] = (var, index_options)
            elif key == "window":
                # Use dropdown for window (includes 30天 for amplitude calculation)
                var = tk.StringVar()
                current_display = window_display_to_value.get(val, "20天")
                var.set(current_display)
                combo = ttk.Combobox(
                    frame, 
                    textvariable=var, 
                    values=list(window_options.keys()),
                    state="readonly",
                    width=18
                )
                combo.grid(row=row, column=1, pady=5, padx=5)
                param_vars[key] = (var, window_options)
            elif key == "ma_window":
                # Use dropdown for ma_window (no 30天, only MA periods we calculate)
                var = tk.StringVar()
                current_display = ma_period_display_to_value.get(val, "20天")
                var.set(current_display)
                combo = ttk.Combobox(
                    frame, 
                    textvariable=var, 
                    values=list(ma_period_options.keys()),
                    state="readonly",
                    width=18
                )
                combo.grid(row=row, column=1, pady=5, padx=5)
                param_vars[key] = (var, ma_period_options)
            elif key == "golden_mode":
                # Use dropdown for golden_mode
                var = tk.StringVar()
                current_display = golden_mode_display_to_value.get(val, "双金叉")
                var.set(current_display)
                combo = ttk.Combobox(
                    frame, 
                    textvariable=var, 
                    values=list(golden_mode_options.keys()),
                    state="readonly",
                    width=18
                )
                combo.grid(row=row, column=1, pady=5, padx=5)
                param_vars[key] = (var, golden_mode_options)
            elif key == "death_cross_mode":
                # Use dropdown for death_cross_mode
                var = tk.StringVar()
                current_display = death_cross_mode_display_to_value.get(val, "单死叉")
                var.set(current_display)
                combo = ttk.Combobox(
                    frame, 
                    textvariable=var, 
                    values=list(death_cross_mode_options.keys()),
                    state="readonly",
                    width=18
                )
                combo.grid(row=row, column=1, pady=5, padx=5)
                param_vars[key] = (var, death_cross_mode_options)
            elif key == "require_downtrend":
                # Use dropdown for boolean
                var = tk.StringVar()
                current_display = bool_display_to_value.get(val, "否")
                var.set(current_display)
                combo = ttk.Combobox(
                    frame, 
                    textvariable=var, 
                    values=list(bool_options.keys()),
                    state="readonly",
                    width=18
                )
                combo.grid(row=row, column=1, pady=5, padx=5)
                param_vars[key] = (var, bool_options)
            elif key in ("ma_short", "ma_medium", "ma_long"):
                # Use dropdown for MA periods
                var = tk.StringVar()
                current_display = ma_period_display_to_value.get(val, "20天")
                var.set(current_display)
                combo = ttk.Combobox(
                    frame, 
                    textvariable=var, 
                    values=list(ma_period_options.keys()),
                    state="readonly",
                    width=18
                )
                combo.grid(row=row, column=1, pady=5, padx=5)
                param_vars[key] = (var, ma_period_options)
            else:
                # Use text entry for numeric parameters
                var = tk.StringVar(value=str(val))
                entry = ttk.Entry(frame, textvariable=var, width=20)
                entry.grid(row=row, column=1, pady=5, padx=5)
                param_vars[key] = var
            row += 1
        
        # Button frame
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=15)
        
        def on_ok():
            # Save custom parameters
            custom = {"type": ftype}
            for key, var_data in param_vars.items():
                if isinstance(var_data, tuple):
                    # Dropdown with mapping
                    var, mapping = var_data
                    display_name = var.get()
                    custom[key] = mapping[display_name]
                else:
                    # Text entry for numeric values
                    val = var_data.get().strip()
                    if not val:
                        messagebox.showwarning(
                            "参数错误",
                            f"参数「{self._param_label(key)}」不能为空",
                        )
                        return
                    try:
                        if "." in val:
                            custom[key] = float(val)
                        else:
                            custom[key] = int(val)
                    except ValueError:
                        messagebox.showwarning(
                            "参数错误",
                            f"参数「{self._param_label(key)}」必须是数字，当前值: {val!r}",
                        )
                        return
            self.custom_params[name] = custom
            self._log(f"已保存 {name} 的参数设置")
            dialog.destroy()
        
        def on_cancel():
            dialog.destroy()
        
        ttk.Button(btn_frame, text="确定", command=on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=on_cancel).pack(side=tk.LEFT, padx=5)
    
    def _param_label(self, key: str) -> str:
        """Convert parameter key to Chinese label."""
        labels = {
            "volume_multiplier": "放量倍数",
            "pe_max": "市盈率上限",
            "window": "时间窗口(天)",
            "ma_window": "均线周期(天)",
            "ma_short": "短期均线(天)",
            "ma_medium": "中期均线(天)",
            "ma_long": "长期均线(天)",
            "vs_index": "对比基准",
            "fluctuation_pct": "波幅上限(%)",
            "volume_ratio": "缩量倍数",
            "golden_mode": "金叉模式",
            "require_downtrend": "要求下跌趋势",
            "death_cross_mode": "死叉模式",
        }
        return labels.get(key, key)

    def _on_filter(self):
        if self.all_data is None:
            messagebox.showwarning("警告", "请先收集数据")
            return

        name = self.filter_var.get()
        ftype, default_criteria = FILTER_REGISTRY.get(name, FILTER_REGISTRY[DEFAULT_FILTER_NAME])
        self.filter_name = name
        
        # Use custom parameters if available, otherwise use default
        if name in self.custom_params:
            criteria = self.custom_params[name]
        else:
            criteria = default_criteria

        self.status_var.set(f"正在筛选: {name}...")
        self._log(f"开始筛选: {name}")
        self.filtered_data = filter_stocks(self.all_data, criteria)
        self._log(f"筛选完成,找到 {len(self.filtered_data)} 只符合条件的股票")
        if not self.filtered_data.empty:
            self.btn_export_filtered.configure(state=tk.NORMAL)
            self.btn_clear_filter.configure(state=tk.NORMAL)
            self._populate_tree(self.filtered_data)
        else:
            self._log("没有股票符合筛选条件")

    def _on_clear_filter(self):
        self.filtered_data = None
        self.btn_export_filtered.configure(state=tk.DISABLED)
        self.btn_clear_filter.configure(state=tk.DISABLED)
        self.status_var.set("已取消筛选")
        self._log("取消筛选")
        if self.all_data is not None:
            self._populate_tree(self.all_data)

    def _on_export_all(self):
        if self.all_data is None:
            return

        # Filter out index rows before export
        from data_exporter import _is_index_row
        stock_data = self.all_data[~self.all_data.apply(_is_index_row, axis=1)].copy()

        filepath = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile=f"stock_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        )
        if filepath:
            export_to_excel(stock_data, filepath)
            self._log(f"全部数据已导出: {filepath}")
            messagebox.showinfo("成功", f"数据已导出到:\n{filepath}")

    def _on_export_filtered(self):
        if self.filtered_data is None or self.filtered_data.empty:
            messagebox.showwarning("警告", "没有筛选数据可导出")
            return
        ftype = FILTER_REGISTRY.get(self.filter_name, FILTER_REGISTRY[DEFAULT_FILTER_NAME])[0]
        filepath = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile=f"filtered_{ftype}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        )
        if filepath:
            filter_export(self.filtered_data, filepath, filter_type=ftype)
            self._log(f"筛选结果已导出: {filepath}")
            messagebox.showinfo("成功", f"筛选结果已导出到:\n{filepath}")

    def _on_close(self):
        """Graceful shutdown: signal background thread, close cache, destroy window."""
        self._shutting_down = True
        try:
            self.root.destroy()
        except Exception:
            pass


def main():
    root = tk.Tk()
    app = StockAnalyzerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
