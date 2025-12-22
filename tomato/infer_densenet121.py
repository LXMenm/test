# -*- coding: utf-8 -*-
"""
基于DenseNet121的番茄病害识别模型推理脚本
"""

import os
import numpy as np
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing.image import load_img, img_to_array
import matplotlib.pyplot as plt

# 配置参数
IMAGE_SIZE = 224  # 与训练时一致
MODEL_PATH = 'densenet121_tomato_disease_model_fine_tuned.h5'  # 微调后的模型
CLASS_NAMES_PATH = 'tomato_disease_classes.txt'

# 加载类别名称
def load_class_names():
    if os.path.exists(CLASS_NAMES_PATH):
        with open(CLASS_NAMES_PATH, 'r') as f:
            class_names = [line.strip() for line in f.readlines()]
        return class_names
    else:
        # 如果没有类别文件，使用默认的番茄病害类别
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

# 加载模型
def load_trained_model():
    if os.path.exists(MODEL_PATH):
        model = load_model(MODEL_PATH)
        print(f"已加载模型: {MODEL_PATH}")
        return model
    else:
        raise FileNotFoundError(f"模型文件不存在: {MODEL_PATH}")

# 图像预处理
def preprocess_image(image_path):
    img = load_img(image_path, target_size=(IMAGE_SIZE, IMAGE_SIZE))
    img_array = img_to_array(img)
    img_array = np.expand_dims(img_array, axis=0)
    img_array /= 255.0  # 归一化
    return img, img_array

# 预测图像
def predict_image(model, image_path, class_names):
    # 预处理图像
    img, img_array = preprocess_image(image_path)
    
    # 进行预测
    predictions = model.predict(img_array)
    predicted_class = np.argmax(predictions[0])
    confidence = predictions[0][predicted_class]
    
    # 获取病害名称
    disease_name = class_names[predicted_class]
    
    # 格式化病害名称
    formatted_name = disease_name.replace('Tomato_', '').replace('_', ' ')
    
    return img, formatted_name, confidence, predictions

# 显示结果
def display_result(img, disease_name, confidence, image_path):
    plt.figure(figsize=(8, 6))
    plt.imshow(img)
    plt.title(f"预测结果: {disease_name}\n置信度: {confidence * 100:.2f}%")
    plt.axis('off')
    plt.tight_layout()
    plt.show()
    
    print(f"图像路径: {image_path}")
    print(f"预测病害: {disease_name}")
    print(f"置信度: {confidence * 100:.2f}%")

# 批量预测
def batch_predict(model, image_dir, class_names):
    results = []
    for filename in os.listdir(image_dir):
        if filename.endswith(('.jpg', '.jpeg', '.png')):
            image_path = os.path.join(image_dir, filename)
            try:
                _, formatted_name, confidence, _ = predict_image(model, image_path, class_names)
                results.append((filename, formatted_name, confidence))
                print(f"{filename}: {formatted_name} ({confidence * 100:.2f}%)")
            except Exception as e:
                print(f"处理 {filename} 时出错: {e}")
    return results

# 主函数
if __name__ == "__main__":
    # 加载类别和模型
    class_names = load_class_names()
    model = load_trained_model()
    
    print("番茄病害识别模型已加载完成!")
    print(f"支持的病害类别: {class_names}")
    
    # 示例：预测单个图像
    example_image = "val/Tomato_healthy/0a67179b-303a-417a-bd8c-993769e37300___RS_HL 0500.JPG"
    if os.path.exists(example_image):
        print(f"\n预测示例图像: {example_image}")
        img, disease_name, confidence, _ = predict_image(model, example_image, class_names)
        display_result(img, disease_name, confidence, example_image)
    
    # 或者预测一个指定的图像
    # image_path = "path/to/your/image.jpg"
    # img, disease_name, confidence, predictions = predict_image(model, image_path, class_names)
    # display_result(img, disease_name, confidence, image_path)
    
    # 或者批量预测一个目录下的所有图像
    # test_dir = "val/Tomato_Bacterial_spot"
    # if os.path.exists(test_dir):
    #     print(f"\n批量预测目录: {test_dir}")
    #     batch_results = batch_predict(model, test_dir, class_names)
