#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
单轮演示：LLM 写一个场景 → 选标签 → 抽一次签 → LLM 写反馈

用于观察提示词质量与整体效果。依赖 LM Studio 本地服务已启动且已加载模型，
以及 tanjing.json、系统提示词.md。

运行（在项目根目录）：
  python mapping/one_round_demo.py
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

# 将 mapping 目录加入 path，便于从项目根运行 python mapping/one_round_demo.py
_MAPPING_DIR = Path(__file__).resolve().parent
if str(_MAPPING_DIR) not in sys.path:
    sys.path.insert(0, str(_MAPPING_DIR))

from blind_draw_gui import (
    ROOT_DIR,
    SYSTEM_PROMPT_PATH,
    TANJING_PATH,
    blind_draw_once,
    format_result,
    load_system_prompts,
    load_tanjing_items,
)
from lm_studio_smoke_test import (
    chat as lm_chat,
    fetch_models,
    get_base_url,
    get_loaded_llm_key,
    get_flash_llm_key,
    get_qwen_tag_llm_key,
)


# ---------- 36 维路由键列表（供 LLM 选择） ----------
def build_req_keys_text(scenes: dict) -> tuple[list[str], str]:
    """从 load_system_prompts 结果生成合法 req_key 列表与供 LLM 阅读的文本。"""
    valid_keys: list[str] = []
    lines: list[str] = []
    for big, subscenes in scenes.items():
        for sub, opts in subscenes.items():
            for letter in "ABC":
                key = f"{sub}_Option_{letter}"
                valid_keys.append(key)
                phrase = (opts or {}).get(letter, "")
                lines.append(f"{key}  {phrase}")
    return valid_keys, "\n".join(lines)


# ---------- 提示词：生成场景（模板化：由 Python 强制指定类别）----------
PROMPT_SCENE_TEMPLATE = """请随机设定一个具体的用户身份（如：特定年龄段的人、全职妈妈、创业者、自由职业者等），并写一段具体的「用户处境」场景，供后续匹配到正确标签。

【强制指令】
本次生成的场景【必须】且【只能】属于以下特定类别，禁止写成其他类别：
👉 {target_category} 👈

要求：
1. 第一人称，50–150 字，只描述「谁、在什么场合、正在经历什么具体的事」，用具体事件代替抽象比喻。身份设定请包含冷门、跨度极大（避免集中于写程序员、项目经理、销售！请多探索实体店主、基层公务员、蓝领、失业中年、自由职业等群体）。
2. 尽量探索该大类下不同的细分情境，越真实越好。
3. 禁止使用模糊的心理学术语或文学比喻（如「情绪宣泄」「陷入泥沼」），直接白描情境。
4. 只输出这一段场景文字，不要解释，不要加引号或标题，不要出现「这是一个关于xx的场景」等废话。

【最高效率指令：必读！】
请直接凭借第一直觉生成场景！【绝对禁止】在内部思考中构思多个备选方案或进行反复比对！
只要想到一个符合要求的身份和情境，立即停止思考并直接输出最终文本！千万不要过度打磨！"""

# 定义四大类别的具体描述，供 Python 随机抽取
SCENE_CATEGORIES = [
    "职场/生存(樊笼)：不限于加班，重点写向上管理、背锅、裁员危机、职场孤立等。",
    "外物/得失(沉浮)：重点写金钱损失、投资失败、错失良机、与同龄人比较的落差感等。",
    "家庭/关系(尘缘)：重点写伴侣冷暴力、育儿耗竭、朋友背叛、亲情绑架等。",
    "自我/内省(方寸)：纯内心的动摇，重点写意义感缺失、容貌焦虑、对衰老的恐惧、自我怀疑等。",
]


# ---------- 提示词：根据场景选标签（边界重塑 + 思维熔断 + 极速单向决策）----------
def make_prompt_tag(scene_text: str, req_keys_text: str) -> str:
    return f"""你不是分析器！你不是评估器！你不是推理器！
你是一个毫秒级响应的【极速路由执行器】。任务：穿透场景表象，精准捕捉用户【最致命的底层病灶】，并将用户场景映射到【唯一 1 个】最契合的路由键。

【最高执行铁律】
- 做出选择后立即停止。不允许二次比较，不允许重新审视，不允许推翻。
- 优解不是目标，【唯一解】才是目标！
- 绝对禁止横向枚举选项！绝对禁止输出任何思考过程、解释或 reasoning 步骤！

【单向决策协议（严格按顺序执行，不得回头）】

第一步：锁定核心冲突变量（只选其一）
- 变量 A：真金白银的得失、破产、物质匮乏、财富落差 👉 直接锁定大类【沉浮】
- 变量 B：系统压迫、KPI、背锅、边缘化、荒谬规矩 👉 直接锁定大类【樊笼】
- 变量 C：具体他人的背叛、争吵、伴侣/家庭拉扯 👉 直接锁定大类【尘缘】
- 变量 D：向内的自我攻击、意义丧失、容貌/年龄焦虑 👉 直接锁定大类【方寸】

第二步：仅在第一步锁定的大类中，凭第一直觉寻找最匹配的 1 个子场景，无视其他大类。

第三步：A/B/C 后缀秒判
- 只要是“想要更多、匮乏、既要又要、控制欲”，秒选 Option_A (贪)。
- 只要是“愤怒、嫉妒、被冒犯、意难平、想反击”，秒选 Option_B (嗔)。
- 只要是“迷茫、麻木、内耗死循环、不知所措”，秒选 Option_C (痴)。

【大场景判断基准（边界极度重要！）】
- 樊笼(职场/生存)：核心痛点是「系统与任务的压迫」。如打工人加班、KPI、上下级矛盾、职场背锅、同事排挤。
- 沉浮(外物/得失)：核心痛点是「真金白银的得失与对比」。如投资亏损、负债、创业破产、生意失败、同龄人财富比较（如别人买房）。
- 尘缘(家庭/关系)：核心痛点是「亲密关系」。如伴侣、父母、子女、亲友。
- 方寸(自我/内省)：核心痛点是「向内的自我攻击」。如容貌焦虑、年龄恐慌、意义感丧失。

【防混淆特殊护栏（必读）】
1. 区分【樊笼】与【沉浮】：即使场景出现了“公司、发工资、供应商”，只要核心痛点是“亏钱、负债、生意存亡、财富落差”，必须归入👉【沉浮】。只有“被老板骂、工作做不完、被同事孤立”等系统/任务压迫，才归入👉【樊笼】。
2. 区分【尘缘】与【方寸】：如果痛苦源于“具体的他人行为”（如老公不顾家、朋友背叛），归入👉【尘缘】；如果是“向内的自我否定”（如全职妈妈觉得自己失去社会价值、照镜子焦虑变老），即便有家庭背景，也必须归入👉【方寸】。
3. 区分【沉浮】与【方寸】：如果是“别人有钱我没有”的嫉妒与落差，归入👉【沉浮】；如果是“有钱也没意思/我到底为了什么活着”的虚无感，归入👉【方寸】。
4. 选定大类后，请精准捕捉用户的核心情绪（如：是委屈背锅，还是疲惫不堪？是嫉妒，还是绝望？）来选择子场景和 Option。

【用户场景】
{scene_text}

【36 个候选路由键】
{req_keys_text}

【强制输出格式与效率要求】
- 你的内部思考必须极其简短、果断！一旦完成单向决策协议并锁定 1 个路由键，立即停止所有进一步思考。
- 不要输出任何前置分析文字或解释，直接在独立的 JSON 代码块中输出最终结果，格式如下：
```json
{{"req_keys": ["选中的子场景_Option_X"]}}
```
"""


# ---------- 提示词：根据场景+签文写反馈（LLM-as-a-Judge，苛刻打分防通货膨胀）----------
def make_prompt_feedback(scene_text: str, result_text: str) -> str:
    return f"""你现在是一位【极其苛刻且毒舌】的禅宗心理学评审专家。你的打分风格以“极其挑剔、拒绝分数通货膨胀”著称。
请独立评估以下签文的【场景命中度】和【解析质量】。回复有且仅有一行。

【用户场景】
{scene_text}

【抽到的签文内容】
{result_text}

【苛刻评分标准】（极其重要：请把 3 分作为默认基础分！严禁滥给 4 或 5 分！）

1. hit_score (1–5) - 场景命中度：
   - 5分 (一击必杀)：不仅大场景匹配，且【极其精准地刺透了】用户的隐秘病灶（如“讨好型”、“既要又要”、“自证陷阱”等）。
   - 3分 (勉强沾边)：场景大类对上了，但没打中核心痛点，感觉是“放之四海而皆准”的万金油废话。
   - 1–2分 (驴唇不对马嘴)：完全错位。

2. analysis_quality (1–5) - 解析质量与气质：
   *（绝对独立维度：即便 hit_score 是 1，只要签文本身写得极好，此处仍可打高分）*
   - 5分 (降维打击)：彻底脱硅，用词极具冷酷感与禅意张力，逻辑无懈可击，微行动极其反直觉且落地。
   - 3分 (平庸及格)：逻辑通顺，但带有明显的“心理学鸡汤味”、“公众号爹味”，或微行动过于普通（如“去散步/深呼吸”）。
   - 1–2分 (低劣)：废话连篇、火上浇油、出现大量网络违和黑话。

   打分时请重点检查：
   - 是否具有「禅意感」：语言是否有经文感 / 高纬度冷静，而不是普通鸡汤或职场文案。
   - 是否「火上浇油」：严禁煽动报复、激化矛盾或放大情绪，只允许稳住节奏、拉回清醒。
   - 是否「软弱无力」：若只是空泛地说「加油」「会好的」，没有结构化洞察和可执行的行动切口，应判为低分。
   - 是否出现出戏词汇或风格违和：例如大量网络流行语、互联网黑话（如“KPI 决战”“流量密码”“躺平摆烂”等）导致用户从坛经世界观中跳戏，应视为减分项。

3. blind_safe_suggestion (true/false)：这支签文是否适合放入「通用盲抽池」？
   - 如果签文里带有极度尖锐的特定指向（如专门骂人“控制欲”“圣母心”），盲抽易误伤，必须为 false。

4. comment：一句话毒舌点评（重点指出你为什么扣分，或最惊艳的点在哪里）。

【最高效率与格式指令】
- 内部采用“减法打分”：从 5 分开始，发现一次鸡汤味扣 1 分，发现一次痛点没对齐扣 1 分。
- 你的回复【有且仅有一行】，按顺序用英文逗号分隔四个值。绝对禁止输出“好的”或任何分析过程！

示例：
3, 4, false, 场景命中较浅只给3分，解析文笔冷酷给4分，但这篇针对性太强盲抽极易误伤故false。"""


# ---------- 反馈解析：优先「逗号分隔四元组」，其次 JSON ----------
# 反馈需要的键
FEEDBACK_KEYS = ("hit_score", "analysis_quality", "blind_safe_suggestion", "comment")

# 逗号分隔一行：hit_score, analysis_quality, blind_safe_suggestion(true/false), comment
_FEEDBACK_LINE_RE = re.compile(
    r"^\s*([1-5])\s*,\s*([1-5])\s*,\s*(true|false)\s*,\s*(.+)$",
    re.IGNORECASE,
)


def parse_feedback_line(text: str) -> dict | None:
    """从回复中找符合「数字,数字,true|false,comment」的一行或片段，解析为反馈 dict。"""
    if not text or not text.strip():
        return None
    # 先按行匹配（模型只输出一行时）
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('"') and line.endswith('"'):
            line = line[1:-1].strip()
        m = _FEEDBACK_LINE_RE.match(line)
        if m:
            return _feedback_match_to_dict(m)
    # 兜底：整段中首次出现四元组（应对无换行或重复多段）
    m = re.search(
        r"([1-5])\s*,\s*([1-5])\s*,\s*(true|false)\s*,\s*([^\n]+?)(?:\s*$|\s*我将|\s*好的|\s*{\")",
        text,
        re.IGNORECASE,
    )
    if m:
        return _feedback_match_to_dict(m)
    return None


def _feedback_match_to_dict(m: re.Match) -> dict:
    hit = max(1, min(5, int(m.group(1))))
    quality = max(1, min(5, int(m.group(2))))
    suggestion = m.group(3).strip().lower() == "true"
    comment = m.group(4).strip().strip('"').strip()
    return {
        "hit_score": hit,
        "analysis_quality": quality,
        "blind_safe_suggestion": suggestion,
        "comment": comment or "",
    }


# ---------- 从 LLM 回复中抽取 JSON ----------


def _normalize_feedback_value(obj: dict) -> None:
    """修正常见非法值：hit_score/analysis_quality 1–5 整数；blind_safe_suggestion 布尔。"""
    for key in ("hit_score", "analysis_quality"):
        if key not in obj:
            continue
        v = obj[key]
        if isinstance(v, (int, float)):
            obj[key] = max(1, min(5, int(round(v))))
        elif isinstance(v, str):
            v = re.sub(r"\s*\(int\)\s*", "", v).strip()
            try:
                obj[key] = max(1, min(5, int(round(float(v)))))
            except (ValueError, TypeError):
                pass
    if "blind_safe_suggestion" in obj:
        v = obj["blind_safe_suggestion"]
        if v is True or v is False:
            return
        if isinstance(v, str):
            obj["blind_safe_suggestion"] = v.strip().lower() in ("true", "keep", "should_be_blind_safe")
        else:
            obj["blind_safe_suggestion"] = True


def extract_json(reply: str) -> dict | None:
    """从回复中抽取 JSON；若为反馈类，优先返回包含 hit_score 等键且最完整的对象。"""
    raw = reply.strip()
    candidates: list[tuple[int, dict]] = []  # (required_keys_count, obj)

    # 1) 收集所有 ```json ... ``` 块
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", raw):
        block = m.group(1).strip()
        # 去掉块内明显推理尾缀（如 "Final decision."）
        block = re.sub(r",?\s*\.{3}\s*$", "", block)
        try:
            obj = json.loads(block)
            if isinstance(obj, dict):
                required = sum(1 for k in FEEDBACK_KEYS if k in obj)
                _normalize_feedback_value(obj)
                candidates.append((required, obj))
        except json.JSONDecodeError:
            pass

    # 2) 收集所有 {...} 块（避免贪婪匹配到超长）
    for m in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw):
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                required = sum(1 for k in FEEDBACK_KEYS if k in obj)
                _normalize_feedback_value(obj)
                candidates.append((required, obj))
        except json.JSONDecodeError:
            pass

    # 3) 优先返回 required 最多且含 hit_score 的（反馈类）；否则返回第一个合法对象
    if candidates:
        candidates.sort(key=lambda x: (-x[0], -len(str(x[1]))))
        obj = candidates[0][1]
        # 反馈类缺 analysis_quality 时用 hit_score 或 3 兜底
        if "hit_score" in obj and "analysis_quality" not in obj:
            obj["analysis_quality"] = obj.get("hit_score", 3)
        return obj

    # 4) 兜底：整段当 JSON 试一次
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            _normalize_feedback_value(obj)
            return obj
    except json.JSONDecodeError:
        pass
    return None


def main() -> int:
    base_url = get_base_url()
    print("=== 单轮演示：场景 → 选标签 → 抽签 → 反馈 ===\n", flush=True)

    # 0. LM Studio 与模型
    try:
        models = fetch_models(base_url)
    except Exception as e:
        print(f"连接 LM Studio 失败: {e}", file=sys.stderr)
        return 1
    model_key = get_loaded_llm_key(models)
    qwen_tag_model_key = get_qwen_tag_llm_key(models)
    if not model_key:
        print("未发现已加载的主 LLM，请在 LM Studio 中加载模型后再试。", file=sys.stderr)
        return 1
    if not qwen_tag_model_key:
        print("未发现用于选标签的 Qwen 模型（key 中需包含 'qwen'，优先 'qwen2.5-7b-instruct'）。", file=sys.stderr)
        return 1
    print(f"使用主模型: {model_key}", flush=True)
    print(f"使用 Qwen 模型（选标签专用）: {qwen_tag_model_key}\n", flush=True)

    # 加载数据
    scenes = load_system_prompts(SYSTEM_PROMPT_PATH)
    valid_req_keys, req_keys_text = build_req_keys_text(scenes)
    items = load_tanjing_items(TANJING_PATH)

    # ---------- Step 1: LLM 写一个场景（Python 强制随机类别，防分布惰性）----------
    print("--- Step 1: LLM 生成场景 ---", flush=True)
    target_category = random.choice(SCENE_CATEGORIES)
    print(f"[{target_category.split('：')[0]}]", flush=True)
    current_prompt_scene = PROMPT_SCENE_TEMPLATE.format(target_category=target_category)
    scene_reply = lm_chat(base_url, model_key, current_prompt_scene, timeout=400)
    scene_text = (scene_reply or "").strip()
    if not scene_text:
        print("未得到场景内容。", file=sys.stderr)
        return 1
    print(f"场景：\n{scene_text}\n", flush=True)

    # ---------- Step 2: LLM 选 req_key ----------
    print("--- Step 2: LLM 选择标签 ---", flush=True)
    tag_reply = lm_chat(
        base_url,
        qwen_tag_model_key,
        make_prompt_tag(scene_text, req_keys_text),
        timeout=400,
        temperature=0.15,
    )
    tag_obj = extract_json(tag_reply or "{}")
    req_keys = None
    if tag_obj and isinstance(tag_obj.get("req_keys"), list):
        req_keys = [k for k in tag_obj["req_keys"] if k in valid_req_keys]
    if not req_keys:
        print(f"未能解析出合法 req_key。原始回复片段: {(tag_reply or '')[:400]}", file=sys.stderr)
        return 1
    req_key = random.choice(req_keys)
    print(f"选中 req_key: {req_key}\n", flush=True)

    # ---------- Step 3: 盲抽一次 ----------
    print("--- Step 3: 盲抽一次签 ---", flush=True)
    drawn = blind_draw_once(items, req_key)
    if not drawn:
        print("该 req_key 下无候选签文（blind_safe 且 match_weights 无正权重）。", file=sys.stderr)
        return 1
    result_text = format_result(drawn)
    print(result_text, flush=True)
    print("", flush=True)

    # ---------- Step 4: LLM 写反馈 ----------
    print("--- Step 4: LLM 打分反馈 ---", flush=True)
    feedback_reply = lm_chat(
        base_url,
        model_key,
        make_prompt_feedback(scene_text, result_text),
        timeout=400,
    )
    # 优先用「逗号分隔一行」解析，避免模型输出 JSON 时反复纠错导致死循环
    feedback_obj = parse_feedback_line(feedback_reply or "")
    if not feedback_obj:
        feedback_obj = extract_json(feedback_reply or "{}")
    if feedback_obj:
        print(json.dumps(feedback_obj, ensure_ascii=False, indent=2), flush=True)
    else:
        print("未解析出 JSON 反馈，原始回复:", flush=True)
        print(feedback_reply or "(空)", flush=True)

    print("\n=== 单轮演示结束 ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
