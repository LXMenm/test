"""
工作流构建模块
使用LangGraph构建多智能体协作的农作物病害诊治系统
"""
from langgraph.graph import StateGraph, END
from state import CropDiseaseState, create_initial_state
from conversation_logger import log_conversation
from agents import (
    reception_agent,
    diagnosis_agent,
    treatment_agent,
    supervisor_agent,
    kb_retrieval_agent,
)


def route_next_step(state: CropDiseaseState) -> str:
    """
    路由函数：根据监督智能体的决策，决定下一个要执行的节点

    Args:
        state: 当前系统状态

    Returns:
        下一个节点的名称
    """
    next_action = state.get("next_action")

    # 根据next_action路由到对应的节点
    if next_action == "reception":
        return "reception"
    elif next_action == "diagnosis":
        return "diagnosis"
    elif next_action == "kb_retrieval":
        return "kb_retrieval"
    elif next_action == "treatment":
        return "treatment"
    elif next_action == "end":
        return END
    else:
        return END


def build_graph() -> StateGraph:
    """
    构建LangGraph工作流

    系统流程：
    1. 监督智能体 -> 接待智能体
    2. 接待智能体 -> 监督智能体
    3. 监督智能体 -> 诊断智能体
    4. 诊断智能体 -> 监督智能体
    5. 监督智能体 -> 知识检索智能体
    6. 知识检索智能体 -> 监督智能体
    7. 监督智能体 -> 治疗方案智能体
    8. 治疗方案智能体 -> 监督智能体
    9. 监督智能体 -> END

    Returns:
        编译后的工作流图
    """
    # 创建StateGraph，指定状态类型
    workflow = StateGraph(CropDiseaseState)

    # 添加节点（各个智能体）
    workflow.add_node("supervisor", supervisor_agent)  # 监督智能体
    workflow.add_node("reception", reception_agent)    # 接待智能体
    workflow.add_node("diagnosis", diagnosis_agent)    # 诊断智能体
    workflow.add_node("kb_retrieval", kb_retrieval_agent)  # 知识检索智能体
    workflow.add_node("treatment", treatment_agent)    # 治疗方案智能体

    # 设置入口点：从监督智能体开始
    workflow.set_entry_point("supervisor")

    # 添加条件边：从监督智能体根据决策路由到不同节点
    workflow.add_conditional_edges(
        "supervisor",           # 源节点
        route_next_step,        # 路由函数
        {
            "reception": "reception",    # 如果返回"reception"，转到reception节点
            "diagnosis": "diagnosis",    # 如果返回"diagnosis"，转到diagnosis节点
            "kb_retrieval": "kb_retrieval",  # 如果返回"kb_retrieval"，转到kb_retrieval节点
            "treatment": "treatment",    # 如果返回"treatment"，转到treatment节点
            END: END                     # 如果返回END，结束流程
        }
    )

    # 添加边：各个智能体执行完后返回监督智能体
    workflow.add_edge("reception", "supervisor")  # 接待智能体 -> 监督智能体
    workflow.add_edge("diagnosis", "supervisor")  # 诊断智能体 -> 监督智能体
    workflow.add_edge("kb_retrieval", "supervisor")  # 知识检索智能体 -> 监督智能体
    workflow.add_edge("treatment", "supervisor")  # 治疗方案智能体 -> 监督智能体

    # 编译工作流
    app = workflow.compile()

    return app


def run_diagnosis(user_query: str, farmer_id: str | None = None, base_id: str | None = None) -> dict:
    """
    运行农作物病害诊断系统

    Args:
        user_query: 用户输入的病害描述
        farmer_id: 农户ID（可选，用于个性化）
        base_id: 基地ID（可选，用于个性化）

    Returns:
        诊断结果字典
    """
    print("=" * 80)
    print("农作物病害诊治系统启动")
    print("=" * 80)

    # 创建初始状态
    initial_state = create_initial_state(user_query, farmer_id=farmer_id, base_id=base_id)

    # 构建工作流
    app = build_graph()

    # 运行工作流
    final_state = app.invoke(initial_state)

    print("\n" + "=" * 80)
    print("诊断完成")
    print("=" * 80)

    # 记录对话与诊疗结果（JSONL 无需数据库）
    log_conversation(final_state)

    # 返回诊断结果
    result = {
        "作物类型": final_state.get("crop_type"),
        "生长阶段": final_state.get("crop_growth_stage"),
        "症状": final_state.get("symptoms"),
        "病害类型": final_state.get("disease_type"),
        "诊断置信度": final_state.get("disease_confidence"),
        "病害描述": final_state.get("disease_description"),
        "治疗方案": final_state.get("treatment_plan"),
        "预防建议": final_state.get("prevention_advice"),
    }

    return result


if __name__ == "__main__":
    # 测试用例
    test_query = "我的水稻叶子发黄了，现在是苗期"

    result = run_diagnosis(test_query)

    # 打印结果
    print("\n最终诊断报告：")
    print("-" * 80)
    for key, value in result.items():
        print(f"{key}: {value}")
