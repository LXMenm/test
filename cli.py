"""
命令行入口
提供三个能力：
1) 用户与系统问答交互（调用诊断工作流）
2) 对话记录展示（基于 JSONL 日志）
3) 知识库管理（增改病害、症状映射、诊断规则、治疗方案）
"""

import argparse
from typing import List

from workflow import run_diagnosis
from conversation_logger import render_report
from knowledge_base import get_kb_manager


def _print_result(result: dict) -> None:
    """打印诊断结果。"""
    print("\n" + "=" * 60)
    print("【番茄病害诊断报告】")
    print("=" * 60)
    print(f"作物类型: {result.get('作物类型') or '番茄'}")
    print(f"生长阶段: {result.get('生长阶段') or '未识别'}")
    print(f"症状: {', '.join(result.get('症状', []))}")
    print(f"病害类型: {result.get('病害类型')}")
    confidence = result.get("诊断置信度")
    if confidence is not None:
        print(f"诊断置信度: {confidence:.2%}")
    print(f"病害描述: {result.get('病害描述')}")
    print(f"治疗方案: {result.get('治疗方案') or '暂无'}")
    print(f"预防建议: {result.get('预防建议') or '暂无'}")
    print("=" * 60)


# ---------------------
# 诊断命令
# ---------------------
def cmd_diagnose(args: argparse.Namespace) -> None:
    """用户问答交互：运行诊断工作流。"""
    query_parts: List[str] = [args.query]
    if args.image:
        query_parts.append(f"图像路径：{args.image}")
    if args.growth_stage:
        query_parts.append(f"生长阶段：{args.growth_stage}")
    query = "，".join(query_parts)

    result = run_diagnosis(query)
    _print_result(result)


# ---------------------
# 日志查看命令
# ---------------------
def cmd_logs(args: argparse.Namespace) -> None:
    """展示最近对话记录摘要。"""
    print(render_report(limit=args.limit))


# ---------------------
# 知识库管理命令
# ---------------------
def cmd_kb_list(args: argparse.Namespace) -> None:
    """列出病害及描述。"""
    kb = get_kb_manager()
    diseases = kb.get_disease_classes()
    print("当前病害列表（附描述）：")
    for name in diseases:
        desc = kb.get_disease_description(name)
        print(f"- {name}: {desc}")


def cmd_kb_add_disease(args: argparse.Namespace) -> None:
    """新增病害及描述。"""
    kb = get_kb_manager()
    ok = kb.add_disease(args.name, args.description)
    if ok:
        print(f"已添加病害：{args.name}")
    else:
        print(f"添加失败，病害已存在：{args.name}")


def cmd_kb_update_treatment(args: argparse.Namespace) -> None:
    """更新治疗方案/预防措施。"""
    if not args.treatment and not args.prevention:
        print("请至少提供 --treatment 或 --prevention 之一")
        return
    kb = get_kb_manager()
    ok = kb.update_treatment(args.name, treatment=args.treatment, prevention=args.prevention)
    if ok:
        print(f"已更新治疗方案/预防措施：{args.name}")
    else:
        print(f"更新失败，可能不存在该病害：{args.name}")


def cmd_kb_add_rule(args: argparse.Namespace) -> None:
    """添加诊断规则。"""
    kb = get_kb_manager()
    ok = kb.add_diagnosis_rule(
        crop_type=args.crop,
        symptom=args.symptom,
        disease_type=args.disease,
        confidence=args.confidence,
        explanation=args.explanation,
    )
    if ok:
        print("诊断规则已添加")
    else:
        print("添加失败，请确认病害名称已存在")


def cmd_kb_add_symptom_map(args: argparse.Namespace) -> None:
    """维护症状到病害的映射。"""
    kb = get_kb_manager()
    diseases = [d.strip() for d in args.diseases.split(",") if d.strip()]
    if not diseases:
        print("请提供至少一个病害名称，使用逗号分隔")
        return
    ok = kb.add_symptom_mapping(args.symptom, diseases)
    if ok:
        print(f"已更新症状映射：{args.symptom} -> {', '.join(diseases)}")
    else:
        print("更新失败，请确认所有病害名称已存在")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="番茄病害诊疗系统 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # diagnose
    diagnose_parser = subparsers.add_parser("diagnose", help="运行诊断并与系统交互")
    diagnose_parser.add_argument("--query", required=True, help="用户输入的症状/场景描述")
    diagnose_parser.add_argument("--image", help="病害图像路径，可选")
    diagnose_parser.add_argument("--growth-stage", help="生长阶段提示，可选")
    diagnose_parser.set_defaults(func=cmd_diagnose)

    # logs
    logs_parser = subparsers.add_parser("logs", help="查看最近对话记录")
    logs_parser.add_argument("--limit", type=int, default=5, help="显示的记录条数，0 表示全部")
    logs_parser.set_defaults(func=cmd_logs)

    # kb group
    kb_parser = subparsers.add_parser("kb", help="知识库管理")
    kb_sub = kb_parser.add_subparsers(dest="kb_command", required=True)

    kb_list = kb_sub.add_parser("list", help="列出病害及描述")
    kb_list.set_defaults(func=cmd_kb_list)

    kb_add = kb_sub.add_parser("add-disease", help="新增病害")
    kb_add.add_argument("--name", required=True, help="病害名称")
    kb_add.add_argument("--description", required=True, help="病害描述")
    kb_add.set_defaults(func=cmd_kb_add_disease)

    kb_update = kb_sub.add_parser("update-treatment", help="更新治疗方案/预防措施")
    kb_update.add_argument("--name", required=True, help="病害名称")
    kb_update.add_argument("--treatment", help="治疗方案文本")
    kb_update.add_argument("--prevention", help="预防措施文本")
    kb_update.set_defaults(func=cmd_kb_update_treatment)

    kb_rule = kb_sub.add_parser("add-rule", help="添加诊断规则")
    kb_rule.add_argument("--crop", required=True, help="作物类型，例如 番茄")
    kb_rule.add_argument("--symptom", required=True, help="症状关键词")
    kb_rule.add_argument("--disease", required=True, help="病害名称")
    kb_rule.add_argument("--confidence", required=True, type=float, help="置信度 0-1")
    kb_rule.add_argument("--explanation", required=True, help="诊断依据")
    kb_rule.set_defaults(func=cmd_kb_add_rule)

    kb_symptom = kb_sub.add_parser("add-symptom-map", help="添加/更新症状到病害映射")
    kb_symptom.add_argument("--symptom", required=True, help="症状名称")
    kb_symptom.add_argument(
        "--diseases",
        required=True,
        help="病害列表，使用逗号分隔，例如：早疫病,晚疫病",
    )
    kb_symptom.set_defaults(func=cmd_kb_add_symptom_map)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    # 支持两种入口：命令式 (python cli.py diagnose ...) 或交互菜单 (python cli.py)
    import sys
    if len(sys.argv) > 1:
        main()
    else:
        menu()


# ---------------------
# 交互式菜单入口（便于“页面”式体验）
# ---------------------


# ---------------------
# 交互式菜单入口（便于“页面”式体验）
# ---------------------

def menu() -> None:
    """
    简易 CLI 界面，模拟“页面”选择：
    1) 用户与系统问答交互
    2) 对话记录展示
    3) 知识库管理
    输入 q 退出。
    """
    kb = get_kb_manager()

    def _page_diagnose():
        query = input("请输入症状/场景描述: ").strip()
        if not query:
            print("描述为空，已返回菜单。")
            return
        growth = input("可选：生长阶段 (直接回车跳过): ").strip()
        image = input("可选：图像路径 (直接回车跳过): ").strip()
        args = argparse.Namespace(query=query, growth_stage=growth or None, image=image or None)
        cmd_diagnose(args)

    def _page_logs():
        limit_raw = input("显示多少条记录？(默认5，0 为全部): ").strip()
        limit = int(limit_raw) if limit_raw.isdigit() else 5
        args = argparse.Namespace(limit=limit)
        cmd_logs(args)

    def _page_kb():
        while True:
            print("\n[知识库管理] 请选择操作：")
            print("1) 列出病害及描述")
            print("2) 新增病害")
            print("3) 更新治疗/预防")
            print("4) 添加诊断规则")
            print("5) 维护症状到病害映射")
            print("b) 返回上级")
            choice = input("请输入选项: ").strip().lower()
            if choice == "1":
                cmd_kb_list(argparse.Namespace())
            elif choice == "2":
                name = input("病害名称: ").strip()
                desc = input("病害描述: ").strip()
                if name and desc:
                    cmd_kb_add_disease(argparse.Namespace(name=name, description=desc))
                else:
                    print("名称或描述为空，操作取消。")
            elif choice == "3":
                name = input("病害名称: ").strip()
                treatment = input("治疗方案(可空): ").strip()
                prevention = input("预防措施(可空): ").strip()
                cmd_kb_update_treatment(
                    argparse.Namespace(name=name, treatment=treatment or None, prevention=prevention or None)
                )
            elif choice == "4":
                crop = input("作物类型: ").strip()
                symptom = input("症状关键词: ").strip()
                disease = input("病害名称: ").strip()
                conf = input("置信度(0-1): ").strip()
                explanation = input("诊断依据: ").strip()
                try:
                    confidence = float(conf)
                except ValueError:
                    print("置信度格式错误。")
                    continue
                cmd_kb_add_rule(
                    argparse.Namespace(
                        crop=crop, symptom=symptom, disease=disease, confidence=confidence, explanation=explanation
                    )
                )
            elif choice == "5":
                symptom = input("症状名称: ").strip()
                diseases = input("病害列表（逗号分隔）: ").strip()
                cmd_kb_add_symptom_map(argparse.Namespace(symptom=symptom, diseases=diseases))
            elif choice == "b":
                return
            else:
                print("无效选项，请重新输入。")

    while True:
        print("\n===== 番茄病害诊疗 CLI 界面 =====")
        print("1) 用户与系统问答交互")
        print("2) 对话记录展示")
        print("3) 知识库管理")
        print("q) 退出")
        choice = input("请选择页面: ").strip().lower()
        if choice == "1":
            _page_diagnose()
        elif choice == "2":
            _page_logs()
        elif choice == "3":
            _page_kb()
        elif choice == "q":
            print("已退出。")
            break
        else:
            print("无效选项，请重新输入。")
