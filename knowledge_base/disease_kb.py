"""
病害基础知识模块
定义番茄病害的基本类别、症状映射和描述信息
"""

from .kb_store import (
    ensure_kb_files,
    load_diseases,
    load_symptom_map,
    save_diseases,
    save_symptom_map,
)


class DiseaseKnowledge:
    """
    病害基础知识类
    包含病害类别、症状映射和病害描述
    """
    def __init__(self):
        # 病害描述字典（内置默认）
        default_descriptions = {
            "健康": "番茄植株生长正常，无任何病害症状。",
            "早疫病": "早疫病是番茄常见真菌性病害，在叶片上形成同心轮纹状病斑，边缘有黄色晕圈。",
            "晚疫病": "晚疫病会导致番茄果实和叶片快速腐烂，病斑呈水渍状，在潮湿环境下发展迅速。",
            "黄化曲叶病毒病": "由白粉虱传播的病毒病，导致叶片黄化、卷曲、变小，植株生长受阻。",
            "叶霉病": "叶霉病在叶片背面产生灰褐色霉层，正面出现黄色病斑，严重时叶片枯死。",
            "细菌性斑点病": "细菌性病害，在叶片和果实上形成小斑点，逐渐扩大并可能穿孔。",
            "叶斑病": "叶斑病会在叶片上形成褐色或灰褐色病斑，影响光合作用。",
            "花叶病毒病": "花叶病毒病导致叶片出现花叶斑驳、畸形，植株生长受抑。",
            "蜘蛛螨": "蜘蛛螨取食叶片汁液，导致叶片失绿、发黄并出现细小斑点。",
            "靶斑病": "靶斑病在叶片上形成同心轮纹状或靶心状病斑，严重时叶片枯死。"
        }
        default_diseases = {name: {"description": desc} for name, desc in default_descriptions.items()}
        ensure_kb_files()
        data = load_diseases()
        if data.get("diseases"):
            diseases = data["diseases"]
        else:
            diseases = default_diseases
            save_diseases({"diseases": diseases})

        # canonical disease key 仅保留图片10类
        canonical_order = ["健康", "早疫病", "晚疫病", "黄化曲叶病毒病", "叶霉病", "细菌性斑点病", "叶斑病", "蜘蛛螨", "靶斑病", "花叶病毒病"]
        diseases = {name: diseases.get(name, {"description": default_descriptions.get(name, "")}) for name in canonical_order}
        self.disease_classes = list(diseases.keys())
        self.disease_descriptions = {
            name: info.get("description", "") if isinstance(info, dict) else ""
            for name, info in diseases.items()
        }
    
    def get_disease_classes(self):
        """获取所有病害类别"""
        return self.disease_classes
    
    def get_disease_description(self, disease_name):
        """获取指定病害的描述"""
        return self.disease_descriptions.get(disease_name, f"暂无{disease_name}的详细描述")
    
    def get_possible_diseases_by_symptom(self, symptom):
        """根据症状获取可能的病害列表"""
        data = load_symptom_map()
        symptom_map = data.get("symptom_map", {})
        return symptom_map.get(symptom, [])
    
    def is_valid_disease(self, disease_name):
        """检查病害名称是否有效"""
        return disease_name in self.disease_classes
    
    def add_symptom_mapping(self, symptom, diseases):
        """添加症状到病害的映射关系"""
        data = load_symptom_map()
        symptom_map = data.get("symptom_map", {})
        symptom_map[symptom] = diseases
        save_symptom_map({"symptom_map": symptom_map})
    
    def update_disease_description(self, disease_name, description):
        """更新病害描述"""
        if disease_name in self.disease_classes:
            self.disease_descriptions[disease_name] = description
            save_diseases(
                {"diseases": {name: {"description": desc} for name, desc in self.disease_descriptions.items()}}
            )
            return True
        return False

    def list_diseases(self):
        """列出病害与描述"""
        return [{"name": name, "description": self.disease_descriptions.get(name, "")} for name in self.disease_classes]

    def upsert_disease(self, name, description):
        """新增或更新病害"""
        if name not in self.disease_classes:
            self.disease_classes.append(name)
        self.disease_descriptions[name] = description
        save_diseases({"diseases": {n: {"description": d} for n, d in self.disease_descriptions.items()}})

    def delete_disease(self, name):
        """删除病害"""
        if name in self.disease_classes:
            self.disease_classes.remove(name)
            self.disease_descriptions.pop(name, None)
            save_diseases({"diseases": {n: {"description": d} for n, d in self.disease_descriptions.items()}})
            return True
        return False
