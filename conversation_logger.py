"""
对话记录模块
负责在原型阶段记录并展示番茄病害诊疗的用户与系统交互，无需使用 SQL 数据库。
日志采用 JSON Lines 形式存储，便于追加与后续分析。
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List


DEFAULT_LOG_DIR = "logs"
DEFAULT_LOG_FILE = "conversations.jsonl"


def _ensure_log_dir(log_dir: str = DEFAULT_LOG_DIR) -> str:
    """确保日志目录存在并返回日志文件路径。"""
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, DEFAULT_LOG_FILE)


def log_conversation(state: Dict[str, Any], log_dir: str = DEFAULT_LOG_DIR) -> str:
    """将一次诊疗对话记录为 JSON 行。

    记录内容聚焦于番茄病害诊疗的输入、流程消息与最终诊断结果。

    Args:
        state: 最终的系统状态（通常来自 workflow.run_diagnosis 的输出状态）。
        log_dir: 日志目录，默认为 "logs"。

    Returns:
        写入的日志文件路径。
    """

    log_path = _ensure_log_dir(log_dir)

    entry = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "user_query": state.get("user_query"),
        "crop_type": state.get("crop_type"),
        "crop_growth_stage": state.get("crop_growth_stage"),
        "location": state.get("location"),
        "province": state.get("province"),
        "facility": state.get("facility"),
        "symptoms": state.get("symptoms", []),
        "image_path": state.get("image_path"),
        "disease_type": state.get("disease_type"),
        "disease_confidence": state.get("disease_confidence"),
        "disease_description": state.get("disease_description"),
        "treatment_plan": state.get("treatment_plan"),
        "prevention_advice": state.get("prevention_advice"),
        "messages": state.get("messages", []),
        "history": [list(item) for item in state.get("history", [])],
        "farmer_id": state.get("farmer_id"),
        "base_id": state.get("base_id"),
        "profile_schema_version": state.get("personalization_flags", {}).get("profile_schema_version"),
        "profile_updated_at": state.get("personalization_flags", {}).get("profile_updated_at"),
        "profile_hash": state.get("personalization_flags", {}).get("profile_hash"),
    }

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return log_path


def load_conversations(log_dir: str = DEFAULT_LOG_DIR) -> List[Dict[str, Any]]:
    """读取全部对话记录。

    Args:
        log_dir: 日志目录，默认为 "logs"。

    Returns:
        日志条目列表，按写入顺序排列。
    """

    log_path = os.path.join(log_dir, DEFAULT_LOG_FILE)
    if not os.path.exists(log_path):
        return []

    entries: List[Dict[str, Any]] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                # 忽略异常行，保持原型阶段的鲁棒性
                continue

    return entries


def render_report(limit: int = 5, log_dir: str = DEFAULT_LOG_DIR) -> str:
    """生成最近若干条对话记录的可读报告文本。"""

    entries = load_conversations(log_dir)
    if not entries:
        return "暂无对话记录。"

    selected = entries[-limit:] if limit else entries
    lines: List[str] = []

    for idx, entry in enumerate(selected, start=1):
        lines.append(f"#{idx} 记录时间: {entry.get('created_at')}")
        lines.append(f"- 用户描述: {entry.get('user_query')}")
        lines.append(f"- 作物类型/生长阶段: {entry.get('crop_type')} / {entry.get('crop_growth_stage')}")
        lines.append(f"- 诊断结果: {entry.get('disease_type')} (置信度: {entry.get('disease_confidence')})")
        lines.append(f"- 治疗方案: {entry.get('treatment_plan') or '无'}")
        prevention_advice = entry.get("prevention_advice") or ""
        prevention_first_line = prevention_advice.split("\n")[0] if prevention_advice else "无"
        lines.append(f"- 预防建议: {prevention_first_line}")
        lines.append(f"- 消息摘要: {entry.get('messages')[-1] if entry.get('messages') else '无'}")
        lines.append("")

    return "\n".join(lines)
