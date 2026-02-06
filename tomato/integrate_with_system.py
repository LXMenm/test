# -*- coding: utf-8 -*-
"""
将训练好的DenseNet121番茄病害模型整合到农作物病害诊治系统
"""

import os
import shutil
import json
import re

# 配置参数
SYSTEM_PATH = '..'  # 系统根目录
TRAINED_MODEL_PATH = 'densenet121_tomato_disease_model_fine_tuned.h5'
CLASSES_PATH = 'tomato_disease_classes.txt'
MODEL_DEST_PATH = os.path.join(SYSTEM_PATH, 'models', 'tomato_dense121_model.h5')
CONFIG_PATH = os.path.join(SYSTEM_PATH, 'config.py')

# 加载类别名称
def load_class_names():
    if os.path.exists(CLASSES_PATH):
        with open(CLASSES_PATH, 'r') as f:
            class_names = [line.strip() for line in f.readlines()]
        return class_names
    else:
        # 默认类别名称
        return [
            'Tomato_Bacterial_spot',
            'Tomato_Early_blight',
            'Tomato_healthy',
            'Tomato_Late_blight',
            'Tomato_Leaf_Mold',
            'Tomato_Septoria_leaf_spot',
            'Tomato_Spider_mites_Two_spotted_spider_mite',
            'Tomato_Target_Spot',
            'Tomato_Tomato_mosaic_virus',
            'Tomato_Tomato_Yellow_Leaf_Curl_Virus'
        ]

# 转换类别名称为中文
def convert_to_chinese(class_names):
    # 中英文映射字典
    name_map = {
        'Tomato_Bacterial_spot': '细菌性斑点病',
        'Tomato_Early_blight': '早疫病',
        'Tomato_healthy': '健康',
        'Tomato_Late_blight': '晚疫病',
        'Tomato_Leaf_Mold': '叶霉病',
        'Tomato_Septoria_leaf_spot': '叶斑病',
        'Tomato_Spider_mites_Two_spotted_spider_mite': '蜘蛛螨',
        'Tomato_Target_Spot': '靶斑病',
        'Tomato_Tomato_mosaic_virus': '花叶病毒病',
        'Tomato_Tomato_Yellow_Leaf_Curl_Virus': '黄化曲叶病毒病'
    }
    
    chinese_names = []
    for name in class_names:
        if name in name_map:
            chinese_names.append(name_map[name])
        else:
            # 如果没有映射，使用原始名称
            chinese_names.append(name.replace('Tomato_', '').replace('_', ' '))
    
    return chinese_names

# 复制模型到系统目录
def copy_model_to_system():
    # 创建models目录（如果不存在）
    models_dir = os.path.join(SYSTEM_PATH, 'models')
    if not os.path.exists(models_dir):
        os.makedirs(models_dir)
        print(f"创建目录: {models_dir}")
    
    # 复制模型文件
    if os.path.exists(TRAINED_MODEL_PATH):
        shutil.copy2(TRAINED_MODEL_PATH, MODEL_DEST_PATH)
        print(f"模型已复制到: {MODEL_DEST_PATH}")
        return True
    else:
        print(f"训练好的模型不存在: {TRAINED_MODEL_PATH}")
        print("请先运行train_densenet121.py进行模型训练")
        return False

# 更新系统配置
def update_system_config():
    # 读取当前配置
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config_content = f.read()
    
    # 更新模型路径
    if "DIAGNOSIS_MODEL_PATH" in config_content:
        new_config = config_content.replace(
            "DIAGNOSIS_MODEL_PATH = os.getenv(\"DIAGNOSIS_MODEL_PATH\", \"models/diagnosis_model.pth\")",
            f"DIAGNOSIS_MODEL_PATH = os.getenv(\"DIAGNOSIS_MODEL_PATH\", \"models/tomato_dense121_model.h5\")"
        )
    else:
        # 如果没有找到，添加配置
        new_config = config_content + "\nDIAGNOSIS_MODEL_PATH = os.getenv(\"DIAGNOSIS_MODEL_PATH\", \"models/tomato_dense121_model.h5\")\n"
    
    # 写入更新后的配置
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(new_config)
    
    print(f"已更新配置文件: {CONFIG_PATH}")

# 更新诊断模型中的类别
def update_diagnosis_model_classes():
    # 读取当前的知识库病害类别
    kb_path = os.path.join(SYSTEM_PATH, 'knowledge_base', 'disease_kb.py')
    with open(kb_path, 'r', encoding='utf-8') as f:
        kb_content = f.read()
    
    # 加载并转换类别名称
    class_names = load_class_names()
    chinese_names = convert_to_chinese(class_names)
    
    # 更新病害类别列表
    entries = ",\n".join(f"            \"{name}\"" for name in chinese_names)
    classes_str = f"[\n{entries}\n        ]"
    updated_content, replacements = re.subn(
        r"(self\.disease_classes\s*=\s*)\[[\s\S]*?\]",
        rf"\1{classes_str}",
        kb_content,
        count=1
    )
    if replacements == 0:
        raise ValueError(f"未能在知识库中找到病害类别列表: {kb_path}")
    
    # 写入更新后的内容
    with open(kb_path, 'w', encoding='utf-8') as f:
        f.write(updated_content)
    
    print(f"已更新知识库病害类别: {kb_path}")
    print(f"新的病害类别: {chinese_names}")

# 主函数
def main():
    print("开始整合DenseNet121番茄病害模型到系统...")
    
    # 检查模型是否存在
    if not os.path.exists(TRAINED_MODEL_PATH):
        print("错误: 训练好的模型不存在!")
        print("请先运行 train_densenet121.py 进行模型训练")
        return False
    
    # 1. 复制模型到系统目录
    if not copy_model_to_system():
        return False
    
    # 2. 更新系统配置
    update_system_config()
    
    # 3. 更新诊断模型中的类别
    update_diagnosis_model_classes()
    
    print("\n整合完成!")
    print("\n使用说明:")
    print("1. 训练好的DenseNet121模型已复制到系统的models目录")
    print("2. 系统配置已更新为使用新模型")
    print("3. 病害类别已更新为您训练的10种番茄病害")
    print("\n现在您可以运行主系统测试图像诊断功能:")
    print("python main.py")
    print("\n或在查询中指定番茄病害图像路径:")
    print("query = \"番茄叶子有病害，图像路径：path/to/your/tomato_image.jpg\"\nresult = run_diagnosis(query)")
    
    return True

if __name__ == "__main__":
    main()
