# -*- coding: utf-8 -*-
"""
六祖坛经 JSON 编辑控制台
直接读写同目录下的 tanjing.json，可随意修改并保存到原文件（文件名不变）。
"""
import json
import os
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

# 与 tanjing.json 同目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TANJING_PATH = os.path.join(SCRIPT_DIR, "tanjing.json")

# 条目字段（与 JSON 一致）
FIELDS = [
    ("tag", "标签 tag"),
    ("scene_category", "场景 scene_category"),
    ("emotion_state", "情绪状态 emotion_state"),
    ("dimension_v", "维度V dimension_v"),
    ("dimension_e", "维度E dimension_e"),
    ("sutra_title", "经文标题 sutra_title"),
    ("sutra_text", "原文 sutra_text"),
    ("ui_translation", "白话直译 ui_translation"),
    ("blind_safe", "盲抽安全 blind_safe"),
    ("match_weights", "权重字典 match_weights"),
    ("ui_mapping", "心智诊断解析 ui_mapping"),
    ("ui_action", "行动指令 ui_action"),
    ("ai_instruction", "AI 判定指令 ai_instruction"),
]

# 短字段用单行，其余用多行
SHORT_FIELDS = {"tag", "scene_category", "dimension_v", "dimension_e", "sutra_title", "blind_safe"}


def load_json():
    path = TANJING_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"未找到文件：{path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data):
    with open(TANJING_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class EditorApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("六祖坛经 JSON 编辑控制台 — tanjing.json")
        self.root.minsize(800, 600)
        self.root.geometry("1000x700")

        self.data = []  # list of dict
        self.current_index = 0
        self.widgets = {}  # field_name -> widget (Entry or Text)
        self.notebook = None
        self.json_text = None  # 整签 JSON 页的文本框

        self._build_ui()
        self._load_file()

    def _build_ui(self):
        # 顶部：导航 + 保存
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill=tk.X)
        ttk.Button(top, text="上一条", command=self._prev).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="下一条", command=self._next).pack(side=tk.LEFT, padx=2)
        self.index_label = ttk.Label(top, text="0 / 0")
        self.index_label.pack(side=tk.LEFT, padx=12)
        ttk.Button(top, text="保存到 tanjing.json", command=self._save).pack(side=tk.LEFT, padx=2)
        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=2)

        # 选项卡：逐条编辑 | 整签 JSON
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # 页1：逐条编辑（表单）
        frame_form = ttk.Frame(self.notebook, padding=4)
        self.notebook.add(frame_form, text="逐条编辑")
        canvas = tk.Canvas(frame_form, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame_form, orient=tk.VERTICAL, command=canvas.yview)
        self.frame = ttk.Frame(canvas)
        self.frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        for key, label in FIELDS:
            row = ttk.Frame(self.frame, padding=4)
            row.pack(fill=tk.X)
            ttk.Label(row, text=label, width=22, anchor="nw").pack(side=tk.LEFT, anchor="nw", padx=(0, 8))
            if key in SHORT_FIELDS:
                w = ttk.Entry(row, width=80)
                w.pack(side=tk.LEFT, fill=tk.X, expand=True)
            else:
                w = ScrolledText(row, height=4, width=80, wrap=tk.WORD, font=("Segoe UI", 10))
                w.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.widgets[key] = w

        # 页2：整签 JSON（当前条目的 {} 整段读写）
        frame_json = ttk.Frame(self.notebook, padding=4)
        self.notebook.add(frame_json, text="整签 JSON")
        ttk.Label(frame_json, text="当前条目的 JSON（可整段编辑、粘贴）", font=("Segoe UI", 10)).pack(anchor="w")
        self.json_text = ScrolledText(
            frame_json, height=30, width=100, wrap=tk.WORD, font=("Consolas", 10)
        )
        self.json_text.pack(fill=tk.BOTH, expand=True, pady=4)
        ttk.Button(frame_json, text="应用当前签", command=self._apply_json_tab).pack(anchor="w", pady=2)

        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
        ttk.Label(
            self.root,
            text=f"文件：{TANJING_PATH}",
            font=("Segoe UI", 9),
            foreground="gray",
        ).pack(anchor="w", padx=6, pady=2)
        self.status = ttk.Label(self.root, text="", font=("Segoe UI", 9), foreground="green")
        self.status.pack(anchor="w", padx=6, pady=2)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Control-s>", lambda e: self._save())
        self.root.bind("<Left>", lambda e: self._prev())
        self.root.bind("<Right>", lambda e: self._next())

    def _on_tab_changed(self, event=None):
        """切换选项卡时同步：整签 JSON 页用 data 刷新文本框，逐条编辑页用 data 刷新表单。"""
        if not self.data:
            return
        try:
            idx = self.notebook.index(self.notebook.select())
            if idx == 0:
                self._show_entry()
            else:
                self._refresh_json_tab()
        except Exception:
            pass

    def _refresh_json_tab(self):
        """用当前条目的 data 刷新「整签 JSON」页的文本框。"""
        entry = self._get_entry()
        if entry is None or self.json_text is None:
            return
        self.json_text.delete("1.0", tk.END)
        self.json_text.insert("1.0", json.dumps(entry, ensure_ascii=False, indent=2))

    def _load_file(self):
        try:
            self.data = load_json()
            if not isinstance(self.data, list):
                messagebox.showerror("错误", "tanjing.json 根节点必须是数组 []")
                self.root.quit()
                return
            self.current_index = 0
            self._refresh_index()
            self._show_entry()
            self.status.config(text=f"已加载 {len(self.data)} 条")
        except FileNotFoundError as e:
            messagebox.showerror("错误", str(e))
            self.root.quit()
        except json.JSONDecodeError as e:
            messagebox.showerror("错误", f"JSON 解析失败：{e}")
            self.root.quit()

    def _refresh_index(self):
        n = len(self.data)
        self.index_label.config(text=f"{self.current_index + 1} / {n}")

    def _get_entry(self):
        if not self.data or self.current_index < 0 or self.current_index >= len(self.data):
            return None
        return self.data[self.current_index]

    def _show_entry(self):
        entry = self._get_entry()
        if entry is None:
            return
        for key, w in self.widgets.items():
            val = entry.get(key, "")
            if isinstance(val, str):
                pass
            else:
                val = str(val) if val is not None else ""
            if key in SHORT_FIELDS:
                w.delete(0, tk.END)
                w.insert(0, val)
            else:
                w.delete("1.0", tk.END)
                w.insert("1.0", val)

    def _read_entry_from_ui(self):
        entry = {}
        for key, w in self.widgets.items():
            if key in SHORT_FIELDS:
                entry[key] = w.get().strip()
            else:
                entry[key] = w.get("1.0", tk.END).strip()
        return entry

    def _apply_json_tab(self):
        """把「整签 JSON」页的文本解析为对象，写回当前条，并刷新表单。"""
        if not self.data or self.json_text is None:
            return
        raw = self.json_text.get("1.0", tk.END).strip()
        try:
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                messagebox.showerror("错误", "JSON 必须是单个对象 {}")
                return
            self.data[self.current_index] = obj
            self._show_entry()
            self.status.config(text="已应用到当前签", foreground="green")
            self.root.after(2000, lambda: self.status.config(text=""))
        except json.JSONDecodeError as e:
            messagebox.showerror("JSON 解析失败", str(e))

    def _sync_current_tab_to_data(self):
        """把当前选项卡的内容写回 self.data[current_index]。"""
        if not self.data:
            return
        try:
            idx = self.notebook.index(self.notebook.select())
            if idx == 0:
                # 表单页：只覆盖已知字段，保留 blind_safe、match_weights 等其他键
                base = self._get_entry() or {}
                updated = dict(base)
                updated.update(self._read_entry_from_ui())
                self.data[self.current_index] = updated
            else:
                raw = self.json_text.get("1.0", tk.END).strip()
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    self.data[self.current_index] = obj
        except Exception:
            pass

    def _save(self):
        if not self.data:
            return
        self._sync_current_tab_to_data()
        try:
            save_json(self.data)
            self.status.config(text="已保存到 tanjing.json", foreground="green")
            self.root.after(2000, lambda: self.status.config(text=""))
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
            self.status.config(text=str(e), foreground="red")

    def _prev(self):
        self._save()
        if self.current_index > 0:
            self.current_index -= 1
            self._refresh_index()
            self._show_entry()
            self._refresh_json_tab()

    def _next(self):
        self._save()
        if self.current_index < len(self.data) - 1:
            self.current_index += 1
            self._refresh_index()
            self._show_entry()
            self._refresh_json_tab()

    def _on_close(self):
        self.root.quit()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    EditorApp().run()
