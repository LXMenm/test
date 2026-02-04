"""
病害基础知识模块
定义番茄病害的基本类别、症状映射和描述信息
"""


class DiseaseKnowledge:
    """
    病害基础知识类
    包含病害类别、症状映射和病害描述
    """
    def __init__(self):
        # 病害类别列表
        self.disease_classes = [
            "健康", "早疫病", "晚疫病", "黄化曲叶病毒病", 
            "叶霉病", "白粉病", "细菌性斑点病", "灰霉病",
            "叶斑病", "花叶病毒病", "蜘蛛螨", "靶斑病"
        ]
        
        # 症状到病害的映射字典
        self.symptom_to_disease = {
            "斑点": ["早疫病", "晚疫病", "细菌性斑点病"],
            "发黄": ["黄化曲叶病毒病", "早疫病", "晚疫病"],
            "腐烂": ["晚疫病", "灰霉病"],
            "白粉": ["白粉病", "叶霉病"],
            "卷曲": ["黄化曲叶病毒病"],
            "枯萎": ["早疫病", "晚疫病"],
            "霉斑": ["叶霉病", "灰霉病"],
            "虫洞": [],
            "变色": ["细菌性斑点病"],
            "生长缓慢": ["黄化曲叶病毒病"],
            "叶斑": ["叶斑病"],
            "花叶": ["花叶病毒病"],
            "螨虫": ["蜘蛛螨"],
            "虫害": ["蜘蛛螨"],
            "靶斑": ["靶斑病"]
        }
        
        # 病害描述字典
        self.disease_descriptions = {
            "健康": "番茄植株生长正常，无任何病害症状。",
            "早疫病": "早疫病是番茄常见真菌性病害，在叶片上形成同心轮纹状病斑，边缘有黄色晕圈。",
            "晚疫病": "晚疫病会导致番茄果实和叶片快速腐烂，病斑呈水渍状，在潮湿环境下发展迅速。",
            "黄化曲叶病毒病": "由白粉虱传播的病毒病，导致叶片黄化、卷曲、变小，植株生长受阻。",
            "叶霉病": "叶霉病在叶片背面产生灰褐色霉层，正面出现黄色病斑，严重时叶片枯死。",
            "白粉病": "白粉病在叶片表面形成白色粉状物，影响光合作用，导致叶片早衰。",
            "细菌性斑点病": "细菌性病害，在叶片和果实上形成小斑点，逐渐扩大并可能穿孔。",
            "灰霉病": "灰霉病在潮湿环境下发生，导致果实和叶片腐烂，表面产生灰色霉层。",
            "叶斑病": "叶斑病会在叶片上形成褐色或灰褐色病斑，影响光合作用。",
            "花叶病毒病": "花叶病毒病导致叶片出现花叶斑驳、畸形，植株生长受抑。",
            "蜘蛛螨": "蜘蛛螨取食叶片汁液，导致叶片失绿、发黄并出现细小斑点。",
            "靶斑病": "靶斑病在叶片上形成同心轮纹状或靶心状病斑，严重时叶片枯死。"
        }
    
    def get_disease_classes(self):
        """获取所有病害类别"""
        return self.disease_classes
    
    def get_disease_description(self, disease_name):
        """获取指定病害的描述"""
        return self.disease_descriptions.get(disease_name, f"暂无{disease_name}的详细描述")
    
    def get_possible_diseases_by_symptom(self, symptom):
        """根据症状获取可能的病害列表"""
        return self.symptom_to_disease.get(symptom, [])
    
    def is_valid_disease(self, disease_name):
        """检查病害名称是否有效"""
        return disease_name in self.disease_classes
    
    def add_symptom_mapping(self, symptom, diseases):
        """添加症状到病害的映射关系"""
        self.symptom_to_disease[symptom] = diseases
    
    def update_disease_description(self, disease_name, description):
        """更新病害描述"""
        if disease_name in self.disease_classes:
            self.disease_descriptions[disease_name] = description
            return True
        return False
