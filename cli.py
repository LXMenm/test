"""
命令行入口
提供三个能力：
1) 用户与系统问答交互（调用诊断工作流）
2) 对话记录展示（基于 JSONL 日志）
3) 知识库管理（增改病害、症状映射、诊断规则、治疗方案）
"""

import argparse
import json
from typing import List

from workflow import run_diagnosis
from conversation_logger import render_report
from knowledge_base import get_kb_manager
from personalization.profile_store import (
    list_profile_ids,
    load_profile,
    reset_profile,
    save_profile,
    upsert_base,
    update_constraints,
)
from personalization.profile_models import FarmerProfile


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
def cmd_diagnose(args: argparse.Namespace) -> dict:
    """用户问答交互：运行诊断工作流。"""
    query_parts: List[str] = [args.query]
    if args.image:
        query_parts.append(f"图像路径：{args.image}")
    if args.growth_stage:
        query_parts.append(f"生长阶段：{args.growth_stage}")
    query = "，".join(query_parts)

    result = run_diagnosis(query, farmer_id=args.farmer_id, base_id=args.base_id)
    _print_result(result)
    return result


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


# ---------------------
# 个性化档案命令
# ---------------------
def cmd_profile_list(args: argparse.Namespace) -> None:
    ids = list_profile_ids()
    if not ids:
        print("暂无档案。")
        return
    print("现有农户ID列表：")
    for pid in ids:
        print(f"- {pid}")


def cmd_profile_show(args: argparse.Namespace) -> None:
    profile = load_profile(args.farmer_id)
    if not profile:
        print(f"未找到档案：{args.farmer_id}")
        return
    print(json.dumps(profile.model_dump(), ensure_ascii=False, indent=2))


def cmd_profile_edit(args: argparse.Namespace) -> None:
    profile = load_profile(args.farmer_id) or FarmerProfile(farmer_id=args.farmer_id)
    base_id = args.base_id or profile.active_base_id or "B001"
    profile = upsert_base(
        profile,
        base_id,
        name=args.base_name,
        location=args.location,
        province=args.province,
        facility=args.facility,
        environment=args.environment,
        growth_stage=args.growth_stage,
        notes=args.notes,
    )

    banned = None
    if args.banned:
        banned = [item.strip() for item in args.banned.split(",") if item.strip()]
    update_constraints(
        profile,
        banned_ingredients=banned,
        harvest_window_days=args.harvest_window,
        prefer_organic=args.prefer_organic,
    )
    if args.confirm_when_low_confidence is not None:
        profile.confirm_when_low_confidence = args.confirm_when_low_confidence
    if args.active_base or not profile.active_base_id:
        profile.active_base_id = base_id

    path = save_profile(profile)
    print(f"档案已保存：{path}")


def cmd_profile_set_active_base(args: argparse.Namespace) -> None:
    profile = load_profile(args.farmer_id)
    if not profile:
        print(f"未找到档案：{args.farmer_id}")
        return
    if args.base_id not in profile.bases:
        print(f"基地 {args.base_id} 不存在，请先使用 edit 创建。")
        return
    profile.active_base_id = args.base_id
    save_profile(profile)
    print(f"已将 {args.base_id} 设为默认基地。")


def cmd_profile_reset(args: argparse.Namespace) -> None:
    profile = reset_profile(args.farmer_id)
    print(f"档案已重置：{profile.farmer_id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="番茄病害诊疗系统 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # diagnose
    diagnose_parser = subparsers.add_parser("diagnose", help="运行诊断并与系统交互")
    diagnose_parser.add_argument("--query", required=True, help="用户输入的症状/场景描述")
    diagnose_parser.add_argument("--image", help="病害图像路径，可选")
    diagnose_parser.add_argument("--growth-stage", help="生长阶段提示，可选")
    diagnose_parser.add_argument("--farmer-id", help="农户ID，用于加载个性化档案", default=None)
    diagnose_parser.add_argument("--base-id", help="基地ID，用于切换不同基地", default=None)
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

    # profile group
    profile_parser = subparsers.add_parser("profile", help="农户个性设置管理")
    profile_sub = profile_parser.add_subparsers(dest="profile_command", required=True)

    profile_list = profile_sub.add_parser("list", help="列出所有档案")
    profile_list.set_defaults(func=cmd_profile_list)

    profile_show = profile_sub.add_parser("show", help="查看档案详情")
    profile_show.add_argument("--farmer-id", required=True, help="农户ID")
    profile_show.set_defaults(func=cmd_profile_show)

    profile_edit = profile_sub.add_parser("edit", help="创建或更新档案/基地")
    profile_edit.add_argument("--farmer-id", required=True, help="农户ID")
    profile_edit.add_argument("--base-id", help="基地ID，默认使用当前活跃基地", default=None)
    profile_edit.add_argument("--base-name", help="基地名称", default=None)
    profile_edit.add_argument("--location", help="基地位置", default=None)
    profile_edit.add_argument("--province", help="省份/区域", default=None)
    profile_edit.add_argument("--facility", help="设施类型（露地、温室等）", default=None)
    profile_edit.add_argument("--environment", help="近期环境描述", default=None)
    profile_edit.add_argument("--growth-stage", help="默认生育期", default=None)
    profile_edit.add_argument("--notes", help="其他备注", default=None)
    profile_edit.add_argument("--banned", help="禁用成分，逗号分隔", default=None)
    profile_edit.add_argument("--harvest-window", type=int, help="距采收天数", default=None)
    pref_group = profile_edit.add_mutually_exclusive_group()
    pref_group.add_argument("--prefer-organic", dest="prefer_organic", action="store_true", help="偏好有机/低残留")
    pref_group.add_argument("--no-prefer-organic", dest="prefer_organic", action="store_false", help="不强制有机偏好")
    pref_group.set_defaults(prefer_organic=None)
    confirm_group = profile_edit.add_mutually_exclusive_group()
    confirm_group.add_argument(
        "--confirm-when-low-confidence",
        dest="confirm_when_low_confidence",
        action="store_true",
        help="低置信度时要求追问确认",
    )
    confirm_group.add_argument(
        "--no-confirm-when-low-confidence",
        dest="confirm_when_low_confidence",
        action="store_false",
        help="低置信度时不强制追问",
    )
    confirm_group.set_defaults(confirm_when_low_confidence=None)
    profile_edit.add_argument(
        "--active-base", action="store_true", help="将该基地设置为默认基地", default=False
    )
    profile_edit.set_defaults(func=cmd_profile_edit)

    profile_active = profile_sub.add_parser("set-active-base", help="切换默认基地")
    profile_active.add_argument("--farmer-id", required=True, help="农户ID")
    profile_active.add_argument("--base-id", required=True, help="基地ID")
    profile_active.set_defaults(func=cmd_profile_set_active_base)

    profile_reset = profile_sub.add_parser("reset", help="重置档案为默认值")
    profile_reset.add_argument("--farmer-id", required=True, help="农户ID")
    profile_reset.set_defaults(func=cmd_profile_reset)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


# ---------------------# 交互式菜单入口（便于“页面”式体验）# ---------------------

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
        """页面 1：用户与系统问答交互，可按 b 返回主菜单。"""
        while True:
            query = input("\n[问答交互] 请输入症状/场景描述（输入 b 返回主菜单）: ").strip()
            if query.lower() == "b":
                return
            if not query:
                print("描述为空，请重新输入或输入 b 返回。")
                continue
            growth = input("可选：生长阶段 (回车跳过，输入 b 返回): ").strip()
            if growth.lower() == "b":
                return
            image = input("可选：图像路径 (回车跳过，输入 b 返回): ").strip()
            if image.lower() == "b":
                return
            farmer_id = input("可选：农户ID (回车跳过，输入 b 返回): ").strip()
            if farmer_id.lower() == "b":
                return
            base_id = input("可选：基地ID (回车跳过，输入 b 返回): ").strip()
            if base_id.lower() == "b":
                return
            args = argparse.Namespace(
                query=query,
                growth_stage=growth or None,
                image=image or None,
                farmer_id=farmer_id or None,
                base_id=base_id or None,
            )
            result = cmd_diagnose(args)  # 保存诊断结果
            # 询问用户是否需要可视化展示结果
            try:
                from visualization import visualize_diagnosis_result
                user_input = input("\n是否需要图形化展示诊断结果？(y/n): ").strip().lower()
                if user_input == 'y':
                    visualize_diagnosis_result(result)
            except ImportError as e:
                print(f"可视化模块导入失败: {e}")
            except Exception as e:
                print(f"可视化展示出错: {e}")
            back = input("\n按 Enter 继续诊断，输入 b 返回主菜单: ").strip().lower()
            if back == "b":
                return

    def _page_logs():
        """页面 2：对话记录展示，可按 b 返回主菜单。"""
        while True:
            limit_raw = input("\n[对话记录] 显示多少条记录？(默认5，0 为全部，输入 b 返回): ").strip().lower()
            if limit_raw == "b":
                return
            if limit_raw == "":
                limit = 5
            elif limit_raw.isdigit():
                limit = int(limit_raw)
            else:
                print("请输入数字、回车或 b。")
                continue
            args = argparse.Namespace(limit=limit)
            cmd_logs(args)
            back = input("\n按 Enter 继续查看，输入 b 返回主菜单: ").strip().lower()
            if back == "b":
                return

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

    def _page_profile():
        """页面 4：个人设置管理。"""
        while True:
            print("\n[个人设置] 请选择操作：")
            print("1) 列出档案")
            print("2) 查看档案")
            print("3) 编辑/创建档案与基地")
            print("4) 重置档案")
            print("b) 返回上级")
            choice = input("请输入选项: ").strip().lower()
            if choice == "1":
                cmd_profile_list(argparse.Namespace())
            elif choice == "2":
                fid = input("农户ID: ").strip()
                if fid:
                    cmd_profile_show(argparse.Namespace(farmer_id=fid))
            elif choice == "3":
                fid = input("农户ID: ").strip()
                base_id = input("基地ID(留空使用默认): ").strip() or None
                base_name = input("基地名称(可空): ").strip() or None
                location = input("基地位置(可空): ").strip() or None
                province = input("省份/区域(可空): ").strip() or None
                facility = input("设施类型(可空): ").strip() or None
                environment = input("近期环境(可空): ").strip() or None
                growth_stage = input("默认生育期(可空): ").strip() or None
                notes = input("备注(可空): ").strip() or None
                banned = input("禁用成分，逗号分隔(可空): ").strip() or None
                harvest = input("距采收天数(可空): ").strip()
                harvest_window = int(harvest) if harvest.isdigit() else None
                prefer = input("偏好有机/低残留? (y/n/回车跳过): ").strip().lower()
                prefer_organic = True if prefer == "y" else False if prefer == "n" else None
                confirm = input("低置信度要求追问? (y/n/回车跳过): ").strip().lower()
                confirm_flag = True if confirm == "y" else False if confirm == "n" else None
                active = input("将此基地设为默认? (y/n): ").strip().lower() == "y"
                cmd_profile_edit(
                    argparse.Namespace(
                        farmer_id=fid,
                        base_id=base_id,
                        base_name=base_name,
                        location=location,
                        province=province,
                        facility=facility,
                        environment=environment,
                        growth_stage=growth_stage,
                        notes=notes,
                        banned=banned,
                        harvest_window=harvest_window,
                        prefer_organic=prefer_organic,
                        confirm_when_low_confidence=confirm_flag,
                        active_base=active,
                    )
                )
            elif choice == "4":
                fid = input("输入要重置的农户ID: ").strip()
                if fid:
                    cmd_profile_reset(argparse.Namespace(farmer_id=fid))
            elif choice == "b":
                return
            else:
                print("无效选项，请重新输入。")

    while True:
        print("\n===== 番茄病害诊疗 CLI 界面 =====")
        print("1) 用户与系统问答交互")
        print("2) 对话记录展示")
        print("3) 知识库管理")
        print("4) 个人设置")
        print("q) 退出")
        choice = input("请选择页面: ").strip().lower()
        if choice == "1":
            _page_diagnose()
        elif choice == "2":
            _page_logs()
        elif choice == "3":
            _page_kb()
        elif choice == "4":
            _page_profile()
        elif choice == "q":
            print("已退出。")
            break
        else:
            print("无效选项，请重新输入。")


if __name__ == "__main__":
    # 支持两种入口：命令式 (python cli.py diagnose ...) 或交互菜单 (python cli.py)
    import sys
    if len(sys.argv) > 1:
        main()
    else:
        menu()
