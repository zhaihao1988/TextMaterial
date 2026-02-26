import argparse
import json
import os
from typing import List, Any


def load_json(path: str) -> List[Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到文件: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: List[Any]) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def input_multiline(prompt: str) -> str:
    print(prompt)
    print("（多行输入，以空行结束）")
    lines: List[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "":
            break
        lines.append(line)
    return "\n".join(lines)


def edit_batch(
    data: List[Any],
    start_index_1_based: int,
    batch_size: int,
) -> bool:
    """
    读取一批（默认 5 条），允许在命令行中粘贴修改后的 JSON，
    批内修改只保存在内存里。函数返回值表示是否在调用方应继续下一批。
    """
    n = len(data)
    start_idx = max(start_index_1_based - 1, 0)
    if start_idx >= n:
        print(f"起始编号 {start_index_1_based} 已超出当前数据长度 {n}，不再处理。")
        return False

    end_idx = min(start_idx + batch_size, n)
    print(f"本批处理范围：第 {start_idx + 1} 条 ～ 第 {end_idx} 条（共 {end_idx - start_idx} 条）")
    print("-" * 60)

    for i in range(start_idx, end_idx):
        print(f"\n====== 第 {i + 1} 条（当前内容预览） ======")
        try:
            print(json.dumps(data[i], ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"无法格式化显示该条内容：{e}")
            print(repr(data[i]))

        choice = input("是否要替换这一整条 JSON 内容？(y/N): ").strip().lower()
        if choice != "y":
            continue

        raw = input_multiline(
            "请粘贴【这一条】完整的 JSON 对象（例如以 { 开头、以 } 结尾）："
        )
        if not raw.strip():
            print("未输入内容，保持原样。")
            continue

        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"解析 JSON 失败，保持原内容不变。错误: {e}")
            continue

        if not isinstance(obj, dict):
            print("粘贴内容不是 JSON 对象（dict），保持原内容不变。")
            continue

        data[i] = obj
        print(f"第 {i + 1} 条已在内存中更新。")

    print("\n本批条目处理结束。")
    while True:
        cont = input("是否保存本批修改并继续处理下一批？(y/N): ").strip().lower()
        if cont in ("y", "n", ""):
            break
    return cont == "y"


def main():
    parser = argparse.ArgumentParser(
        description="按批次（默认每批 5 条）编辑 tanjing.json 指定区间的签文内容。"
    )
    parser.add_argument(
        "--file",
        default="tanjing.json",
        help="JSON 文件路径（默认：tanjing.json）",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=43,
        help="从第几条开始（1 基数，默认：43，对应从第 43 条开始处理）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="每批处理多少条记录（默认：5）",
    )
    args = parser.parse_args()

    json_path = args.file
    data = load_json(json_path)

    current_start = args.start
    while True:
        should_continue = edit_batch(
            data=data,
            start_index_1_based=current_start,
            batch_size=args.batch_size,
        )

        if not should_continue:
            print("用户选择不继续，未写回当前未保存的修改（如有）。流程结束。")
            break

        # 用户同意继续：先保存，再推进到下一批
        save_json(json_path, data)
        print(f"已保存到文件：{json_path}")

        current_start += args.batch_size
        if current_start > len(data):
            print("已处理完所有条目。")
            break


if __name__ == "__main__":
    main()

