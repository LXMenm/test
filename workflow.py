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
    verification_agent,
)


def route_next_step(state: CropDiseaseState) -> str:
    """
    路由函数：根据监督智能体的决策，决定下一个要执行的节点
    """
    next_action = state.get("next_action")

    if next_action == "reception":
        return "reception"
    elif next_action == "diagnosis":
        return "diagnosis"
    elif next_action == "kb_retrieval":
        return "kb_retrieval"
    elif next_action == "treatment":
        return "treatment"
    elif next_action == "verification":
        return "verification"
    elif next_action == "await_user_confirmation":
        return END
    elif next_action == "manual_review":
        return END
    elif next_action == "end":
        return END
    else:
        return END


def build_graph() -> StateGraph:
    """
    构建LangGraph工作流

    新流程：
    reception -> supervisor
    diagnosis -> supervisor
    kb_retrieval -> supervisor
    treatment -> supervisor
    verification -> supervisor
    """
    workflow = StateGraph(CropDiseaseState)

    workflow.add_node("supervisor", supervisor_agent)
    workflow.add_node("reception", reception_agent)
    workflow.add_node("diagnosis", diagnosis_agent)
    workflow.add_node("kb_retrieval", kb_retrieval_agent)
    workflow.add_node("treatment", treatment_agent)
    workflow.add_node("verification", verification_agent)

    workflow.set_entry_point("reception")

    workflow.add_conditional_edges(
        "supervisor",
        route_next_step,
        {
            "reception": "reception",
            "diagnosis": "diagnosis",
            "kb_retrieval": "kb_retrieval",
            "treatment": "treatment",
            "verification": "verification",
            "await_user_confirmation": END,
            "manual_review": END,
            END: END
        }
    )

    workflow.add_edge("reception", "supervisor")
    workflow.add_edge("diagnosis", "supervisor")
    workflow.add_edge("kb_retrieval", "supervisor")
    workflow.add_edge("treatment", "supervisor")
    workflow.add_edge("verification", "supervisor")

    app = workflow.compile()
    return app


def run_diagnosis(user_query: str, farmer_id: str | None = None, base_id: str | None = None) -> dict:
    """
    运行农作物病害诊断系统

    """
    print("=" * 80)
    print("农作物病害诊治系统启动")
    print("=" * 80)

    initial_state = create_initial_state(user_query, farmer_id=farmer_id, base_id=base_id)
    app = build_graph()
    final_state = app.invoke(initial_state)

    print("\n" + "=" * 80)
    print("诊断完成")
    print("=" * 80)

    log_conversation(final_state)

    result = {
        "作物类型": final_state.get("crop_type"),
        "生长阶段": final_state.get("crop_growth_stage"),
        "症状": final_state.get("symptoms"),
        "病害类型": final_state.get("disease_type"),
        "诊断置信度": final_state.get("disease_confidence"),
        "病害描述": final_state.get("disease_description"),
        "治疗方案": final_state.get("treatment_plan"),
        "预防建议": final_state.get("prevention_advice"),
        "审查是否通过": final_state.get("verification_passed"),
        "审查风险等级": final_state.get("verification_risk_level"),
        "审查摘要": final_state.get("verification_summary"),
    }

    return result


if __name__ == "__main__":
    test_query = "我的水稻叶子发黄了，现在是苗期"
    result = run_diagnosis(test_query)
    print("\n最终诊断报告：")
    print("-" * 80)
    for key, value in result.items():
        print(f"{key}: {value}")
