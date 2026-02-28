#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
盲抽模拟器（仅标签权重，不含向量/大模型）

功能概述：
- 三层选择：大场景 -> 子场景 -> 36 维短句（Option A/B/C）。
- 根据选择构造路由键 req_key，如 "樊笼-疲于奔命_Option_B"。
- 从 tanjing.json 中筛选 blind_safe == true 且 match_weights[req_key] > 0 的签文。
- 在候选集合上按权重做轮盘赌，每次只返回 1 条签文，并打印关键字段。

依赖：
- 标准库：json, os, pathlib, random, re, sys
- 数据文件：
  - ../tanjing.json
  - ../系统提示词.md
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Any

ROOT_DIR = Path(__file__).resolve().parent.parent
MAPPING_DIR = ROOT_DIR / "mapping"
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
    # 例如：樊笼-形如槁木：
    subscene_pattern = re.compile(r"^([^\s]+-[^：]+)：")
    # 例如：Option_A（贪）：仰高不及，颓卧尘埃。
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
                # 确保前缀与当前大场景一致，例如 "樊笼-形如槁木" 以 "樊笼-" 开头
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


def choose_from_menu(title: str, options: List[str]) -> int:
    """
    在命令行中展示一个简单菜单，让用户选择 1..N，返回索引（0-based）。
    """
    if not options:
        raise ValueError(f"{title} 选项为空。")

    while True:
        print(f"\n{title}")
        for i, opt in enumerate(options, start=1):
            print(f"{i}. {opt}")
        choice = input("请输入序号（数字）：").strip()
        if not choice.isdigit():
            print("输入无效，请输入数字序号。")
            continue
        idx = int(choice) - 1
        if 0 <= idx < len(options):
            return idx
        print("序号超出范围，请重新输入。")


def build_req_key(
    scenes: Dict[str, Dict[str, Dict[str, str]]]
) -> Tuple[str, str, str]:
    """
    引导用户进行三层选择，并返回 (scene_name, subscene_name, req_key)。
    """
    # 固定大场景顺序，若某一项在解析结果中不存在则自动跳过
    scene_order = ["樊笼", "沉浮", "尘缘", "方寸"]
    available_scenes = [s for s in scene_order if s in scenes]
    scene_idx = choose_from_menu("请选择大场景：", available_scenes)
    scene_name = available_scenes[scene_idx]

    subscene_map = scenes[scene_name]
    subscene_names = list(subscene_map.keys())
    # 为展示更友好，可去掉前缀中的大场景名，仅展示后半部分
    display_subscenes = [
        name.split("-", 1)[1] if "-" in name else name for name in subscene_names
    ]
    sub_idx = choose_from_menu(
        f"【{scene_name}】下的子场景（12 基础标签的一部分）：", display_subscenes
    )
    subscene_name = subscene_names[sub_idx]

    options = subscene_map[subscene_name]
    # 保证按 A/B/C 顺序展示
    option_letters = ["A", "B", "C"]
    option_labels = []
    for letter in option_letters:
        phrase = options.get(letter, "").strip()
        label = f"{letter}：{phrase}" if phrase else letter
        option_labels.append(label)

    opt_idx = choose_from_menu(
        f"【{subscene_name}】下的 3 个心理维度短句（对应 Option A/B/C）：", option_labels
    )
    selected_letter = option_letters[opt_idx]
    req_key = f"{subscene_name}_Option_{selected_letter}"

    return scene_name, subscene_name, req_key


def weighted_random_choice(
    items_with_weight: List[Tuple[Dict[str, Any], float]]
) -> Dict[str, Any]:
    """
    在 (item, weight) 列表上执行一次权重轮盘赌，返回选中的 item。
    要求所有 weight > 0。
    """
    total = sum(w for _, w in items_with_weight)
    if total <= 0:
        raise ValueError("权重总和必须大于 0。")
    r = random.uniform(0, total)
    cumulative = 0.0
    for item, w in items_with_weight:
        cumulative += w
        if cumulative > r:
            return item
    # 理论上不会走到这里，但为了安全，返回最后一个
    return items_with_weight[-1][0]


def blind_draw_once(
    items: List[Dict[str, Any]], req_key: str
) -> Dict[str, Any] | None:
    """
    依据盲抽规则，在给定 req_key 上执行一次抽取：
    - 仅使用 blind_safe == true 且 match_weights[req_key] > 0 的签文。
    - 使用权重轮盘赌，返回 1 条；若无候选，则返回 None。
    """
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


def print_result(item: Dict[str, Any]) -> None:
    """
    打印签文的关键字段，便于在命令行中阅读。
    """
    title = item.get("sutra_title", "")
    text = item.get("sutra_text", "")
    translation = item.get("ui_translation", "")
    ui_mapping = item.get("ui_mapping", "")
    ui_action = item.get("ui_action", "")
    index = item.get("index", "")

    print("\n=== 抽签结果 ===")
    print(f"index：{index}")
    print(f"标题：{title}")
    print(f"内容：\n{text}")
    print(f"\n翻译：\n{translation}")
    print(f"\nuimapping：\n{ui_mapping}")
    print(f"\n微行动：\n{ui_action}")
    print("================\n")


def main() -> None:
    print("盲抽模拟器（仅标签权重，不含向量语义）")
    print(f"数据文件：{TANJING_PATH}")
    print(f"系统提示词：{SYSTEM_PROMPT_PATH}")

    try:
        scenes = load_system_prompts(SYSTEM_PROMPT_PATH)
    except Exception as e:
        print(f"解析系统提示词失败：{e}", file=sys.stderr)
        sys.exit(1)

    try:
        items = load_tanjing_items(TANJING_PATH)
    except Exception as e:
        print(f"加载 tanjing.json 失败：{e}", file=sys.stderr)
        sys.exit(1)

    while True:
        scene_name, subscene_name, req_key = build_req_key(scenes)
        print(f"\n当前路由键：{req_key}")

        result = blind_draw_once(items, req_key)
        if result is None:
            print("在该键上未找到任何 blind_safe 且权重 > 0 的签文。")
        else:
            print_result(result)

        again = input("是否继续抽取？(Y/n)：").strip().lower()
        if again and again not in ("y", "yes", "是"):
            break


if __name__ == "__main__":
    # 确保当前工作目录不影响相对路径解析
    os.chdir(ROOT_DIR)
    main()

