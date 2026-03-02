#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
跑批脚本：按场景列表批量「选标签 → 每场景抽 20 次签 → LLM 打分」，并追加到 mapping/feedback_log.jsonl。

流程（与训练集自动生成方案一致）：
  1. 从 mapping/scenarios.jsonl 读取场景列表（每行 {"scene_id": N, "scene_text": "..."}）。
  2. 对每个场景：LLM 选 req_key（策略 A：多选则随机一个）→ 用该 req_key 盲抽 20 次。
  3. 每次抽签后：LLM 对「场景 + 签文」打分 → 写入一条记录到 feedback_log.jsonl（含 scene_id, scene_text, draw_round 等扩展字段）。

使用前：
  - LM Studio 本地服务已启动且已加载模型。
  - 准备场景列表：可手动编写 mapping/scenarios.jsonl，或先运行 --gen-scenarios 生成。

运行（在项目根目录）：
  # 生成 200 条场景到 mapping/scenarios.jsonl（可选，只需跑一次）
  python mapping/batch_feedback.py --gen-scenarios 200

  # 跑批：处理所有场景，每场景 20 次抽签并写 feedback_log.jsonl
  python mapping/batch_feedback.py

  # 仅处理前 2 个场景（试跑）
  python mapping/batch_feedback.py --limit 2

  # 指定场景文件
  python mapping/batch_feedback.py --scenarios my_scenes.jsonl

报错与重跑（如 timeout）：
  - 断点续传：启动时读取 feedback_log.jsonl 中已出现的 scene_id，直接跳过，从第一个未完成场景继续。
  - 一个场景没搞定就下一个：选标签或打分失败时跳过当前场景/当次抽签，继续后续场景，无需彻底重头来。
  - feedback_log.jsonl 只追加不覆盖；每条仅在构造完整 record 后写入一行，避免半截 JSON。若因进程中断等出现不完整的一行，删掉该行即可。
  - LLM 调用失败时指数退避重试（等 1s、2s…），再失败则跳过当条并继续。
  - 每场景仅对 20 条不重复签文打分（同一 index 不重复评估），防算力浪费。
  - --overwrite-scenarios：仅当需要「清空并重新生成」场景文件时与 --gen-scenarios 同用，非报错后的必选操作。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_MAPPING_DIR = Path(__file__).resolve().parent
if str(_MAPPING_DIR) not in sys.path:
    sys.path.insert(0, str(_MAPPING_DIR))

from blind_draw_gui import (
    FEEDBACK_LOG_PATH,
    ROOT_DIR,
    SYSTEM_PROMPT_PATH,
    TANJING_PATH,
    blind_draw_once,
    format_result,
    get_next_feedback_id,
    load_system_prompts,
    load_tanjing_items,
)
from lm_studio_smoke_test import (
    chat as lm_chat,
    fetch_models,
    get_base_url,
    get_loaded_llm_key,
)
from one_round_demo import (
    PROMPT_SCENE_TEMPLATE,
    SCENE_CATEGORIES,
    build_req_keys_text,
    extract_json,
    make_prompt_feedback,
    make_prompt_tag,
    parse_feedback_line,
)

DEFAULT_SCENARIOS_PATH = _MAPPING_DIR / "scenarios.jsonl"
CHAT_TIMEOUT = 400
LM_MAX_ATTEMPTS = 2  # 单次调用最多尝试次数（含 timeout 等报错后重试 1 次）


def _lm_chat_with_retry(base_url: str, model_key: str, prompt: str, timeout: int = CHAT_TIMEOUT) -> str | None:
    """调用 LM 一次；失败则指数退避后重试（防雪崩）。"""
    last_err = None
    for attempt in range(LM_MAX_ATTEMPTS):
        try:
            return lm_chat(base_url, model_key, prompt, timeout=timeout)
        except Exception as e:
            last_err = e
            if attempt + 1 < LM_MAX_ATTEMPTS:
                sleep_time = 2**attempt
                print(f"  [重试 {attempt + 1}/{LM_MAX_ATTEMPTS}] {e}，等待 {sleep_time}s 后重试...", flush=True)
                time.sleep(sleep_time)
    if last_err is not None:
        raise last_err
    return None


def _to_blind_safe_bool(value) -> bool:
    """将 blind_safe_suggestion 规范为 bool。true/keep/should_be_blind_safe -> True，其余 -> False。"""
    if value is True:
        return True
    if value is False:
        return False
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "keep", "should_be_blind_safe"):
            return True
        if v in ("false", "should_not_be_blind_safe"):
            return False
    return True


def load_scenarios(path: Path) -> list[dict]:
    """读取场景列表，每行一个 JSON：scene_id, scene_text。"""
    if not path.is_file():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and "scene_text" in obj:
                    out.append(obj)
            except json.JSONDecodeError:
                print(f"警告：无法解析 JSONL 第 {line_num} 行，已跳过。", flush=True)
    return out


def generate_scenarios(
    count: int, base_url: str, model_key: str, out_path: Path, overwrite: bool = False
) -> int:
    """生成 count 条场景并写入 out_path（JSONL）。每条约定由 Python 随机指定类别。返回成功条数。
    overwrite=True 时先清空文件再生成（用于报错后「重新开始写场景」）。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite and out_path.exists():
        out_path.write_text("", encoding="utf-8")
    written = 0
    for i in range(count):
        try:
            target_category = random.choice(SCENE_CATEGORIES)
            prompt = PROMPT_SCENE_TEMPLATE.format(target_category=target_category)
            reply = _lm_chat_with_retry(base_url, model_key, prompt, CHAT_TIMEOUT)
            text = (reply or "").strip()
            if not text:
                print(f"  [gen {i+1}/{count}] 空回复，跳过", flush=True)
                continue
            category_short = target_category.split("：")[0]
            record = {"scene_id": i + 1, "scene_text": text, "target_category": category_short}
            with out_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1
            if (i + 1) % 10 == 0:
                print(f"  已生成 {i+1}/{count} 条场景", flush=True)
        except Exception as e:
            print(f"  [gen {i+1}/{count}] 异常: {e}", flush=True)
    return written


def run_batch(
    scenarios_path: Path,
    limit: int | None,
    base_url: str,
    model_key: str,
    valid_req_keys: list[str],
    req_keys_text: str,
    items: list,
) -> tuple[int, int]:
    """处理场景列表：每场景选 req_key、抽 20 次（去重）、打分并追加到 feedback_log。支持断点续传。返回 (成功场景数, 成功记录数)。"""
    scenarios = load_scenarios(scenarios_path)
    if not scenarios:
        return 0, 0
    if limit is not None:
        scenarios = scenarios[:limit]

    # 断点续传：已出现在 feedback_log 中的 scene_id 直接跳过
    processed_scene_ids = set()
    if FEEDBACK_LOG_PATH.exists():
        with FEEDBACK_LOG_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    if "scene_id" in obj:
                        processed_scene_ids.add(obj["scene_id"])
                except json.JSONDecodeError:
                    pass
    if processed_scene_ids:
        print(f"断点续传：已跳过 {len(processed_scene_ids)} 个已有反馈的场景", flush=True)

    total_records = 0
    ok_scenes = 0
    for s_idx, scen in enumerate(scenarios):
        scene_id = scen.get("scene_id", s_idx + 1)
        if scene_id in processed_scene_ids:
            print(f"[场景 {scene_id}] 已在日志中，跳过（断点续传）", flush=True)
            continue
        scene_text = (scen.get("scene_text") or "").strip()
        target_category = scen.get("target_category", "")
        if not scene_text:
            print(f"[场景 {scene_id}] scene_text 为空，跳过", flush=True)
            continue
        print(f"\n--- 场景 {scene_id} / {len(scenarios)} ---", flush=True)
        # 1) LLM 选 req_key（失败自动重试 1 次）
        try:
            tag_reply = _lm_chat_with_retry(
                base_url,
                model_key,
                make_prompt_tag(scene_text, req_keys_text),
                CHAT_TIMEOUT,
            )
            tag_obj = extract_json(tag_reply or "{}")
            req_keys = []
            if tag_obj and isinstance(tag_obj.get("req_keys"), list):
                req_keys = [k for k in tag_obj["req_keys"] if k in valid_req_keys]
            if not req_keys:
                print(f"  未能解析出合法 req_key，跳过该场景", flush=True)
                continue
            req_key = random.choice(req_keys)
            print(f"  req_key: {req_key}", flush=True)
        except Exception as e:
            print(f"  选标签异常: {e}，跳过该场景", flush=True)
            continue
        ok_scenes += 1
        # 2) 抽 20 条不重复签文，每条打分并写入 feedback_log（去重防算力浪费）
        seen_indexes = set()
        written_this_scene = 0
        max_attempts = 100
        attempts = 0
        while written_this_scene < 20 and attempts < max_attempts:
            attempts += 1
            drawn = blind_draw_once(items, req_key)
            if not drawn:
                print(f"  无更多候选签文，结束该场景抽签", flush=True)
                break
            item_index = drawn.get("index")
            if item_index in seen_indexes:
                continue
            seen_indexes.add(item_index)

            result_text = format_result(drawn)
            try:
                feedback_reply = _lm_chat_with_retry(
                    base_url,
                    model_key,
                    make_prompt_feedback(scene_text, result_text),
                    CHAT_TIMEOUT,
                )
                feedback_obj = parse_feedback_line(feedback_reply or "")
                if not feedback_obj:
                    feedback_obj = extract_json(feedback_reply or "{}")
            except Exception as e:
                print(f"  第 {written_this_scene + 1} 条: 打分异常 {e}，跳过", flush=True)
                seen_indexes.discard(item_index)
                continue
            if not feedback_obj:
                seen_indexes.discard(item_index)
                continue
            feedback_id = get_next_feedback_id()
            source = drawn.get("source", "liuzutanjing")
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            angle = drawn.get("angle")
            hit_score = feedback_obj.get("hit_score")
            analysis_quality = feedback_obj.get("analysis_quality")
            blind_safe_suggestion = _to_blind_safe_bool(feedback_obj.get("blind_safe_suggestion"))
            comment = feedback_obj.get("comment", "")
            draw_round = written_this_scene + 1
            # 完整故事闭环：便于复盘 Step1/2、审查多样性、沉淀黄金测试集
            record = {
                "feedback_id": feedback_id,
                "timestamp": ts,
                "target_category": target_category,
                "scene_text": scene_text,
                "selected_req_key": req_key,
                "drawn_item": {
                    "index": drawn.get("index"),
                    "title": drawn.get("sutra_title", ""),
                    "angle": angle,
                },
                "eval_feedback": {
                    "hit_score": hit_score,
                    "analysis_quality": analysis_quality,
                    "blind_safe_suggestion": blind_safe_suggestion,
                    "comment": comment,
                },
                # 以下保留扁平字段，便于既有脚本与统计
                "source": source,
                "index": drawn.get("index"),
                "angle": angle,
                "req_key": req_key,
                "scene_id": scene_id,
                "draw_round": draw_round,
                "hit_score": hit_score,
                "analysis_quality": analysis_quality,
                "blind_safe_suggestion": blind_safe_suggestion,
                "comment": comment,
            }
            record["sutra_title"] = drawn.get("sutra_title", "")
            record["ui_mapping"] = drawn.get("ui_mapping", "")
            record["ui_action"] = drawn.get("ui_action", "")
            line = json.dumps(record, ensure_ascii=False) + "\n"
            try:
                FEEDBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                with FEEDBACK_LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(line)
            except Exception as e:
                print(f"  第 {draw_round} 条: 写入 feedback_log 失败 {e}，跳过本条（若文件末尾多出半行请手动删除）", flush=True)
                seen_indexes.discard(item_index)
                continue
            written_this_scene += 1
            total_records += 1
            if written_this_scene % 5 == 0:
                print(f"  已写 {written_this_scene}/20 条", flush=True)
        if attempts >= max_attempts and written_this_scene < 20:
            print(f"  达到最大尝试次数 {max_attempts}，已收集 {written_this_scene} 条不重复签文，结束该场景", flush=True)
    return ok_scenes, total_records


def main() -> int:
    parser = argparse.ArgumentParser(description="批量生成反馈并追加到 feedback_log.jsonl")
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=DEFAULT_SCENARIOS_PATH,
        help="场景列表 JSONL 路径（默认 mapping/scenarios.jsonl）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅处理前 N 个场景（试跑用）",
    )
    parser.add_argument(
        "--gen-scenarios",
        type=int,
        metavar="N",
        default=None,
        help="生成 N 条场景并写入 --scenarios 路径，然后退出（不跑批）",
    )
    parser.add_argument(
        "--overwrite-scenarios",
        action="store_true",
        help="与 --gen-scenarios 同用：生成前先清空场景文件，用于报错后重新开始写场景",
    )
    args = parser.parse_args()

    base_url = get_base_url()
    try:
        models = fetch_models(base_url)
    except Exception as e:
        print(f"连接 LM Studio 失败: {e}", file=sys.stderr)
        return 1
    model_key = get_loaded_llm_key(models)
    if not model_key:
        print("未发现已加载的 LLM，请在 LM Studio 中加载模型。", file=sys.stderr)
        return 1
    print(f"使用模型: {model_key}", flush=True)

    if args.gen_scenarios is not None:
        n = args.gen_scenarios
        overwrite = args.overwrite_scenarios
        if overwrite:
            print(f"已开启 --overwrite-scenarios，将先清空再生成 {n} 条场景到 {args.scenarios} ...", flush=True)
        else:
            print(f"生成 {n} 条场景到 {args.scenarios}（追加）...", flush=True)
        written = generate_scenarios(n, base_url, model_key, args.scenarios, overwrite=overwrite)
        print(f"已写入 {written} 条。跑批请执行: python mapping/batch_feedback.py", flush=True)
        return 0

    scenarios_list = load_scenarios(args.scenarios)
    if not scenarios_list:
        print(f"未找到场景列表或文件为空: {args.scenarios}", file=sys.stderr)
        print("可先运行: python mapping/batch_feedback.py --gen-scenarios 200", file=sys.stderr)
        return 1
    limit_msg = f"（仅前 {args.limit} 个）" if args.limit else ""
    print(f"加载 {len(scenarios_list)} 条场景 {limit_msg}，开始跑批 ...", flush=True)

    scenes = load_system_prompts(SYSTEM_PROMPT_PATH)
    valid_req_keys, req_keys_text = build_req_keys_text(scenes)
    items = load_tanjing_items(TANJING_PATH)
    ok_scenes, total_records = run_batch(
        args.scenarios,
        args.limit,
        base_url,
        model_key,
        valid_req_keys,
        req_keys_text,
        items,
    )
    print(f"\n完成: 成功处理 {ok_scenes} 个场景，共写入 {total_records} 条到 {FEEDBACK_LOG_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
