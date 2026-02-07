"""
治疗方案知识模块
定义番茄病害的治疗方案和预防措施
"""

from .kb_store import ensure_kb_files, load_treatments, save_treatments


class TreatmentKnowledge:
    """
    治疗方案知识类
    包含病害的治疗方法和预防措施
    """
    def __init__(self):
        # 治疗方案知识库（内置默认）
        default_plans = {
            "健康": {
                "treatment": "番茄目前健康，无需特殊治疗。",
                "prevention": "1. 继续保持良好的栽培管理 2. 定期巡查，及时发现问题 3. 注意环境控制，避免病害发生"
            },
            "早疫病": {
                "treatment": "1. 发病初期：使用百菌清、代森锰锌或嘧菌酯喷雾，每7-10天一次，连续2-3次。 2. 发病严重时：使用肟菌·戊唑醇或苯甲·嘧菌酯，每5-7天一次。",
                "prevention": "1. 轮作倒茬，避免连作 2. 加强栽培管理，合理密植 3. 摘除底部老叶，增加通风 4. 避免浇水过多，保持叶片干燥"
            },
            "晚疫病": {
                "treatment": "1. 发病初期：使用烯酰吗啉、霜脲氰或氟吡菌胺喷雾，每5-7天一次，连续2-3次。 2. 发病严重时：使用霜霉威盐酸盐+氟吡菌胺复配剂。",
                "prevention": "1. 选用抗病品种 2. 避免密植，增加通风透光 3. 雨后及时排水，降低湿度 4. 摘除病果病叶，集中销毁"
            },
            "黄化曲叶病毒病": {
                "treatment": "1. 病毒病无特效药，重点是防治传播媒介白粉虱。 2. 使用吡虫啉、噻虫嗪或螺虫乙酯防治白粉虱。 3. 发病严重的植株建议拔除销毁。",
                "prevention": "1. 使用防虫网隔离 2. 及时清除田间及周边杂草 3. 悬挂黄板监测和诱杀白粉虱 4. 加强田间管理，提高植株抗性"
            },
            "叶霉病": {
                "treatment": "1. 发病初期：使用春雷霉素、多抗霉素或氟硅唑喷雾。 2. 发病严重时：使用苯甲·嘧菌酯或肟菌·戊唑醇。",
                "prevention": "1. 选用抗病品种 2. 合理密植，加强通风 3. 控制浇水，降低湿度 4. 及时摘除病叶，集中销毁"
            },
            "白粉病": {
                "treatment": "1. 发病初期：使用三唑酮、戊唑醇或氟硅唑喷雾。 2. 发病严重时：使用苯甲·丙环唑或吡唑醚菌酯。",
                "prevention": "1. 选用抗病品种 2. 合理施肥，避免偏施氮肥 3. 加强通风，降低湿度 4. 及时清除病残体"
            },
            "细菌性斑点病": {
                "treatment": "1. 发病初期：使用春雷霉素、中生菌素或噻菌铜喷雾。 2. 发病严重时：使用氢氧化铜或硫酸铜钙。",
                "prevention": "1. 选用无病种子或种子消毒 2. 轮作倒茬 3. 避免叶片结露和高湿环境 4. 及时清除病叶病果"
            },
            "灰霉病": {
                "treatment": "1. 发病初期：使用腐霉利、异菌脲或嘧霉胺喷雾。 2. 发病严重时：使用啶酰菌胺或氟唑菌酰胺。",
                "prevention": "1. 加强通风，降低湿度 2. 避免浇水过多 3. 及时摘除病花病果 4. 合理密植，增加光照"
            },
            "未知病害": {
                "treatment": "建议咨询当地番茄病害防治专家，根据实际情况制定具体治疗方案。",
                "prevention": "1. 加强田间管理，保持植株健康 2. 定期巡查，及时发现问题 3. 注意环境控制，避免病害发生 4. 选用抗病品种"
            }
        }
        ensure_kb_files()
        data = load_treatments()
        if data.get("treatments"):
            self.treatment_plans = data["treatments"]
        else:
            self.treatment_plans = default_plans
            save_treatments({"treatments": self.treatment_plans})
    
    def get_treatment_plan(self, disease_type):
        """获取指定病害的治疗方案"""
        return self.treatment_plans.get(
            disease_type,
            {
                "treatment": "暂无方案，请完善知识库",
                "prevention": "暂无预防建议",
            },
        )
    
    def get_treatment(self, disease_type):
        """获取指定病害的治疗方法"""
        return self.get_treatment_plan(disease_type)["treatment"]
    
    def get_prevention(self, disease_type):
        """获取指定病害的预防措施"""
        return self.get_treatment_plan(disease_type)["prevention"]
    
    def add_treatment_plan(self, disease_type, treatment, prevention):
        """添加治疗方案"""
        self.treatment_plans[disease_type] = {
            "treatment": treatment,
            "prevention": prevention
        }
        save_treatments({"treatments": self.treatment_plans})
    
    def update_treatment_plan(self, disease_type, treatment=None, prevention=None):
        """更新治疗方案"""
        if disease_type in self.treatment_plans:
            if treatment is not None:
                self.treatment_plans[disease_type]["treatment"] = treatment
            
            if prevention is not None:
                self.treatment_plans[disease_type]["prevention"] = prevention
            save_treatments({"treatments": self.treatment_plans})
            return True
        return False

    def upsert_treatment_plan(self, disease_type, treatment, prevention):
        """新增或更新治疗方案"""
        self.treatment_plans[disease_type] = {
            "treatment": treatment,
            "prevention": prevention,
        }
        save_treatments({"treatments": self.treatment_plans})

    def delete_treatment_plan(self, disease_type):
        """删除治疗方案"""
        if disease_type in self.treatment_plans:
            self.treatment_plans.pop(disease_type, None)
            save_treatments({"treatments": self.treatment_plans})
            return True
        return False

    def list_treatments(self):
        """列出治疗方案"""
        items = []
        for disease, plan in self.treatment_plans.items():
            if isinstance(plan, dict):
                items.append(
                    {
                        "disease": disease,
                        "treatment": plan.get("treatment", ""),
                        "prevention": plan.get("prevention", ""),
                    }
                )
        return items
