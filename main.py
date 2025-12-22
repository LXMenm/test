"""
示例运行脚本
演示如何使用番茄病害诊治系统
"""
from workflow import run_diagnosis
from conversation_logger import render_report


def print_result(result: dict):
    """
    格式化打印诊断结果

    Args:
        result: 诊断结果字典
    """
    print("\n" + "=" * 80)
    print("【番茄病害诊断报告】")
    print("=" * 80)

    print(f"\n📋 基本信息:")
    print(f"  • 作物类型: {result.get('作物类型') or '番茄'}")
    print(f"  • 生长阶段: {result.get('生长阶段') or '未识别'}")
    print(f"  • 症状描述: {', '.join(result.get('症状', []))}")

    print(f"\n🔍 诊断结果:")
    print(f"  • 病害类型: {result.get('病害类型')}")
    confidence = result.get('诊断置信度')
    if confidence:
        print(f"  • 置信度: {confidence:.2%}")
    print(f"  • 病害描述: {result.get('病害描述')}")

    print(f"\n💊 治疗方案:")
    treatment = result.get('治疗方案')
    if treatment:
        print(f"  {treatment}")
    else:
        print("  暂无治疗方案")

    print(f"\n🛡️ 预防建议:")
    prevention = result.get('预防建议')
    if prevention:
        for line in prevention.split('\n'):
            if line.strip():
                print(f"  {line.strip()}")
    else:
        print("  暂无预防建议")

    print("\n" + "=" * 80)


def main():
    """
    主函数：运行多个番茄病害测试案例
    """
    # 测试案例1：番茄早疫病（基于症状）
    print("\n【测试案例1：番茄早疫病（基于症状）】")
    query1 = "我的番茄叶子上有很多斑点，现在是开花期"
    result1 = run_diagnosis(query1)
    print_result(result1)

    # 测试案例2：番茄晚疫病（基于症状）
    print("\n\n【测试案例2：番茄晚疫病（基于症状）】")
    query2 = "番茄果实和叶子开始腐烂，结果期"
    result2 = run_diagnosis(query2)
    print_result(result2)

    # 测试案例3：番茄健康（基于症状）
    print("\n\n【测试案例3：番茄健康（基于症状）】")
    query3 = "我的番茄生长正常，叶子绿色，没有病害症状"
    result3 = run_diagnosis(query3)
    print_result(result3)

    # 测试案例4：番茄黄化曲叶病毒病（基于症状）
    print("\n\n【测试案例4：番茄黄化曲叶病毒病（基于症状）】")
    query4 = "番茄叶子发黄、卷曲，植株生长缓慢"
    result4 = run_diagnosis(query4)
    print_result(result4)
    
    # 测试案例5：番茄病害（基于图像与文字）
    print("\n\n【测试案例5：番茄病害（基于图像与文字）】")
    # 注意：用户需要将image_path替换为实际存在的番茄病害图像路径
    # 支持多种图像路径格式
    query5 = "番茄叶子有病害，现在是结果期，叶子上有斑点。图像路径：./exam.jpg"
    result5 = run_diagnosis(query5)
    print_result(result5)
    
    # 测试案例6：番茄病害（基于纯图像）
    print("\n\n【测试案例6：番茄病害（基于纯图像）】")
    # 只提供图像路径，不提供文字描述
    query6 = "图像路径：./exam.jpg"
    result6 = run_diagnosis(query6)
    print_result(result6)

    # 展示最近的对话记录摘要（默认5条）
    print("\n【最近对话记录摘要】")
    print(render_report(limit=5))
    
    # 询问用户是否需要可视化展示结果
    try:
        from visualization import visualize_diagnosis_result
        user_input = input("\n是否需要图形化展示最后一个测试案例的结果？(y/n): ")
        if user_input.lower() == 'y':
            visualize_diagnosis_result(result6)
    except ImportError as e:
        print(f"可视化模块导入失败: {e}")
    except Exception as e:
        print(f"可视化展示出错: {e}")


if __name__ == "__main__":
    main()
    input("\n按Enter键退出程序...")
