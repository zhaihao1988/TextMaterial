#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
盲抽模拟器 - 图形界面版（tkinter）

功能特性：
- 三层选择（大场景 -> 子场景 -> 36 维短句 A/B/C），数据源来自《系统提示词.md》。
- 根据选择构造路由键 req_key，例如 "樊笼-疲于奔命_Option_B"。
- 从 tanjing.json 中筛选 blind_safe == true 且 match_weights[req_key] > 0 的签文。
- 在候选集合上按权重做轮盘赌，每次只返回 1 条签文，并在界面中展示关键字段。

依赖：
- 标准库：json, os, pathlib, random, re
- GUI：tkinter（Python 自带，无需额外安装）
- 数据文件：
  - ../tanjing.json
  - ../系统提示词.md
"""

from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import tkinter as tk
from tkinter import ttk, messagebox


ROOT_DIR = Path(__file__).resolve().parent.parent
TANJING_PATH = ROOT_DIR / "tanjing.json"
SYSTEM_PROMPT_PATH = ROOT_DIR / "系统提示词.md"


def load_system_prompts(path: Path) -> Dict[str, Dict[str, Dict[str, str]]]:
    """
    解析《系统提示词.md》，提取 4 大场景 / 12 子场景 / 36 个 Option 文案。

    返回结构：
    {
        "樊笼": {
            "樊笼-形如槁木": {"A": "仰高不及，颓卧尘埃。", "B": "...", "C": "..."},
            "樊笼-戾气横生": {...},
            ...
        },
        "沉浮": {...},
        "尘缘": {...},
        "方寸": {...},
    }
    """
    scenes: Dict[str, Dict[str, Dict[str, str]]] = {}
    current_scene: str | None = None
    current_subscene: str | None = None

    if not path.is_file():
        raise FileNotFoundError(f"未找到系统提示词文件：{path}")

    big_scene_pattern = re.compile(r"^\d+\.\s*【(.+?)】")
    subscene_pattern = re.compile(r"^([^\s]+-[^：]+)：")
    option_pattern = re.compile(r"^Option_([ABC])[（(].*?[）)][:：]\s*(.+)$")

    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            m_big = big_scene_pattern.match(line)
            if m_big:
                current_scene = m_big.group(1)
                scenes.setdefault(current_scene, {})
                current_subscene = None
                continue

            m_sub = subscene_pattern.match(line)
            if m_sub and current_scene:
                candidate = m_sub.group(1)
                if candidate.startswith(current_scene + "-"):
                    current_subscene = candidate
                    scenes[current_scene].setdefault(current_subscene, {})
                continue

            m_opt = option_pattern.match(line)
            if m_opt and current_scene and current_subscene:
                letter = m_opt.group(1)
                phrase = m_opt.group(2).strip()
                scenes[current_scene][current_subscene][letter] = phrase

    return scenes


def load_tanjing_items(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"未找到数据文件：{path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("tanjing.json 顶层结构应为列表。")

    return data


def weighted_random_choice(
    items_with_weight: List[Tuple[Dict[str, Any], float]]
) -> Dict[str, Any]:
    total = sum(w for _, w in items_with_weight)
    if total <= 0:
        raise ValueError("权重总和必须大于 0。")
    r = random.uniform(0, total)
    cumulative = 0.0
    for item, w in items_with_weight:
        cumulative += w
        if cumulative > r:
            return item
    return items_with_weight[-1][0]


def blind_draw_once(
    items: List[Dict[str, Any]], req_key: str
) -> Dict[str, Any] | None:
    candidates: List[Tuple[Dict[str, Any], float]] = []

    for item in items:
        if not item.get("blind_safe", False):
            continue
        match_weights = item.get("match_weights") or {}
        if not isinstance(match_weights, dict):
            continue
        weight = match_weights.get(req_key, 0)
        try:
            weight_value = float(weight)
        except (TypeError, ValueError):
            continue
        if weight_value <= 0:
            continue
        candidates.append((item, weight_value))

    if not candidates:
        return None

    return weighted_random_choice(candidates)


def format_result(item: Dict[str, Any]) -> str:
    title = item.get("sutra_title", "")
    text = item.get("sutra_text", "")
    translation = item.get("ui_translation", "")
    ui_mapping = item.get("ui_mapping", "")
    ui_action = item.get("ui_action", "")
    index = item.get("index", "")

    lines = [
        f"index：{index}",
        f"标题：{title}",
        "",
        "内容：",
        text or "",
        "",
        "翻译：",
        translation or "",
        "",
        "uimapping：",
        ui_mapping or "",
        "",
        "微行动：",
        ui_action or "",
    ]
    return "\n".join(lines)


class BlindDrawApp(tk.Tk):
    def __init__(
        self,
        scenes: Dict[str, Dict[str, Dict[str, str]]],
        items: List[Dict[str, Any]],
    ) -> None:
        super().__init__()
        self.title("盲抽模拟器（标签权重版）")
        self.geometry("900x700")

        self.scenes = scenes
        self.items = items

        self.scene_order = [s for s in ["樊笼", "沉浮", "尘缘", "方寸"] if s in scenes]

        self.var_scene = tk.StringVar()
        self.var_subscene = tk.StringVar()
        self.var_option = tk.StringVar()  # "A" / "B" / "C"
        self.var_req_key = tk.StringVar()

        self._build_widgets()
        if self.scene_order:
            self.var_scene.set(self.scene_order[0])
            self._on_scene_changed()

    def _build_widgets(self) -> None:
        top_frame = ttk.Frame(self, padding=10)
        top_frame.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top_frame, text="大场景：").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.scene_combo = ttk.Combobox(
            top_frame, textvariable=self.var_scene, values=self.scene_order, state="readonly"
        )
        self.scene_combo.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        self.scene_combo.bind("<<ComboboxSelected>>", lambda e: self._on_scene_changed())

        ttk.Label(top_frame, text="子场景：").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.subscene_combo = ttk.Combobox(
            top_frame, textvariable=self.var_subscene, state="readonly"
        )
        self.subscene_combo.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        self.subscene_combo.bind("<<ComboboxSelected>>", lambda e: self._on_subscene_changed())

        option_frame = ttk.LabelFrame(top_frame, text="36 维短句（Option A/B/C）", padding=10)
        option_frame.grid(row=0, column=2, rowspan=2, sticky=tk.W + tk.E + tk.N, padx=10, pady=5)

        self.option_buttons: Dict[str, tk.Radiobutton] = {}
        for i, letter in enumerate(["A", "B", "C"]):
            rb = tk.Radiobutton(
                option_frame,
                text=f"{letter}",
                variable=self.var_option,
                value=letter,
                anchor="w",
                justify="left",
            )
            rb.grid(row=i, column=0, sticky="w", pady=2)
            self.option_buttons[letter] = rb

        action_frame = ttk.Frame(self, padding=10)
        action_frame.pack(side=tk.TOP, fill=tk.X)

        self.req_key_label = ttk.Label(action_frame, text="当前路由键：")
        self.req_key_label.pack(side=tk.LEFT, padx=5)

        draw_button = ttk.Button(action_frame, text="抽一签", command=self.on_draw_clicked)
        draw_button.pack(side=tk.RIGHT, padx=5)

        result_frame = ttk.Frame(self, padding=10)
        result_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        ttk.Label(result_frame, text="抽签结果：").pack(anchor="w")
        self.text_result = tk.Text(result_frame, wrap="word", height=25)
        self.text_result.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(result_frame, command=self.text_result.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_result.configure(yscrollcommand=scrollbar.set)

    def _on_scene_changed(self) -> None:
        scene = self.var_scene.get()
        subscene_map = self.scenes.get(scene, {})
        subscene_names = list(subscene_map.keys())
        display_names = [
            name.split("-", 1)[1] if "-" in name else name for name in subscene_names
        ]
        self.subscene_internal_names = subscene_names
        self.subscene_display_to_internal = {
            disp: internal for disp, internal in zip(display_names, subscene_names)
        }
        self.subscene_combo["values"] = display_names
        if display_names:
            self.var_subscene.set(display_names[0])
            self._on_subscene_changed()

    def _on_subscene_changed(self) -> None:
        scene = self.var_scene.get()
        display_name = self.var_subscene.get()
        internal_name = self.subscene_display_to_internal.get(display_name)
        if not internal_name:
            return
        options = self.scenes.get(scene, {}).get(internal_name, {})
        for letter in ["A", "B", "C"]:
            phrase = options.get(letter, "").strip()
            text = f"{letter}：{phrase}" if phrase else letter
            self.option_buttons[letter].configure(text=text)
        if not self.var_option.get():
            self.var_option.set("A")
        self._update_req_key()

    def _update_req_key(self) -> None:
        scene = self.var_scene.get()
        display_name = self.var_subscene.get()
        internal_name = self.subscene_display_to_internal.get(display_name)
        letter = self.var_option.get()
        if scene and internal_name and letter:
            req_key = f"{internal_name}_Option_{letter}"
        else:
            req_key = ""
        self.var_req_key.set(req_key)
        self.req_key_label.configure(text=f"当前路由键：{req_key}" if req_key else "当前路由键：")

    def on_draw_clicked(self) -> None:
        self._update_req_key()
        req_key = self.var_req_key.get()
        if not req_key:
            messagebox.showwarning("提示", "请选择完整的大场景、子场景和短句（A/B/C）。")
            return
        result = blind_draw_once(self.items, req_key)
        if result is None:
            messagebox.showinfo(
                "无可用签文",
                "在该路由键上未找到任何 blind_safe 且权重 > 0 的签文。",
            )
            return
        formatted = format_result(result)
        self.text_result.delete("1.0", tk.END)
        self.text_result.insert(tk.END, formatted)


def main() -> None:
    try:
        scenes = load_system_prompts(SYSTEM_PROMPT_PATH)
    except Exception as e:
        messagebox.showerror("错误", f"解析系统提示词失败：{e}")
        return

    try:
        items = load_tanjing_items(TANJING_PATH)
    except Exception as e:
        messagebox.showerror("错误", f"加载 tanjing.json 失败：{e}")
        return

    app = BlindDrawApp(scenes, items)
    app.mainloop()


if __name__ == "__main__":
    os.chdir(ROOT_DIR)
    main()

