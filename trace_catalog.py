"""Real agents catalog and node mapping for workflow visualization."""

from __future__ import annotations

AGENTS_CATALOG = [
    {"id": "parse_input", "name": "输入解析节点", "description": "解析上传请求与参数"},
    {"id": "reception", "name": "接待智能体", "description": "提取作物阶段与症状信息"},
    {"id": "diagnosis", "name": "诊断智能体", "description": "图像/症状诊断并计算置信度"},
    {"id": "confidence_gate", "name": "置信度门控节点", "description": "评估低置信度与回退策略"},
    {"id": "kb_retrieval", "name": "知识检索智能体", "description": "检索知识库与候选条目"},
    {"id": "personalization", "name": "个性化智能体", "description": "按档案约束过滤方案"},
    {"id": "treatment", "name": "治疗方案智能体", "description": "生成治疗与预防建议"},
    {"id": "prescription", "name": "处方生成节点", "description": "生成处置建议输出"},
    {"id": "validator", "name": "校验节点", "description": "校验结果完整性"},
    {"id": "persist", "name": "落盘节点", "description": "写入事件日志"},
    {"id": "supervisor", "name": "监督智能体", "description": "决定下一步路由动作"},
    {"id": "confirm_input", "name": "确认输入节点", "description": "接收二次确认输入"},
    {"id": "final", "name": "结束节点", "description": "输出最终诊断结果"},
]

NODE_TO_AGENT = {
    # Workflow nodes
    "supervisor": "supervisor",
    "reception": "reception",
    "diagnosis": "diagnosis",
    "kb_retrieval": "kb_retrieval",
    "treatment": "treatment",
    "confirm_input": "confirm_input",
    # SSE/Emit nodes
    "ParseInput": "parse_input",
    "DiagnosisAgent": "diagnosis",
    "ConfidenceGate": "confidence_gate",
    "KBRetrievalAgent": "kb_retrieval",
    "PersonalizationAgent": "personalization",
    "PrescriptionAgent": "prescription",
    "ValidatorAgent": "validator",
    "Persist": "persist",
    "Final": "final",
}
