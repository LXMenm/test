# DenseNet121番茄病害识别模型使用指南

本指南将帮助您使用DenseNet121模型对番茄病害进行识别和分类。

## 数据集结构

```
tomato/
├── train/             # 训练数据集
│   ├── Tomato_Bacterial_spot/          # 细菌性斑点病
│   ├── Tomato_Early_blight/            # 早疫病
│   ├── Tomato_healthy/                 # 健康
│   ├── Tomato_Late_blight/             # 晚疫病
│   ├── Tomato_Leaf_Mold/               # 叶霉病
│   ├── Tomato_Septoria_leaf_spot/      # 叶斑病
│   ├── Tomato_Spider_mites_Two_spotted_spider_mite/  # 蜘蛛螨
│   ├── Tomato_Target_Spot/             # 靶斑病
│   ├── Tomato_Tomato_mosaic_virus/     # 花叶病毒病
│   └── Tomato_Tomato_Yellow_Leaf_Curl_Virus/  # 黄化曲叶病毒病
├── val/               # 验证数据集
│   └── [与train相同的类别结构]
├── train_densenet121.py     # DenseNet121训练脚本
├── infer_densenet121.py     # 模型推理脚本
├── integrate_with_system.py # 系统整合脚本
├── cnn_train.py             # 原始CNN训练脚本
└── README.md                # 本使用指南
```

## 安装依赖

```bash
# 安装TensorFlow（推荐使用GPU版本）
pip install tensorflow-gpu  # GPU版本
# 或 CPU版本
# pip install tensorflow

# 安装其他依赖
pip install numpy matplotlib pillow
```

## 使用步骤

### 1. 训练DenseNet121模型

运行训练脚本：

```bash
cd c:\test\tomato
python train_densenet121.py
```

**训练配置**（可在脚本中修改）：
- `IMAGE_SIZE = 224`：输入图像大小
- `BATCH_SIZE = 32`：批次大小
- `EPOCHS = 50`：训练轮数
- `LEARNING_RATE = 1e-4`：学习率
- `trainable = False/True`：是否冻结基础模型层

**训练过程**：
1. 使用预训练的DenseNet121模型（ImageNet权重）
2. 冻结基础模型层，仅训练自定义顶层
3. 训练完成后自动进行微调（解冻最后24层）
4. 保存训练好的模型：
   - `densenet121_tomato_disease_model.h5`（基础模型）
   - `densenet121_tomato_disease_model_fine_tuned.h5`（微调后模型）

### 2. 模型推理

运行推理脚本对新图像进行预测：

```bash
python infer_densenet121.py
```

**推理配置**（可在脚本中修改）：
- `MODEL_PATH`：训练好的模型路径
- `IMAGE_SIZE`：输入图像大小（需与训练时一致）

**使用方法**：
1. 修改脚本中的`example_image`为您要预测的图像路径
2. 或取消注释`image_path`行，指定您的图像路径
3. 或取消注释`test_dir`行，批量预测一个目录下的所有图像

### 3. 整合到农作物病害诊治系统

将训练好的模型整合到现有的系统中：

```bash
python integrate_with_system.py
```

**整合内容**：
1. 复制训练好的模型到系统的models目录
2. 更新系统配置文件（config.py）
3. 更新诊断模型中的病害类别（diagnosis_model.py）

**注意事项**：
- 整合前请确保已经成功训练了模型
- 整合后，系统将默认使用新训练的DenseNet121模型

## 模型评估

训练完成后，您可以在推理脚本中查看模型的准确率：

```bash
python infer_densenet121.py
```

或直接在训练脚本的输出中查看验证集准确率。

## 示例使用

### 示例1：训练模型

```bash
cd c:\test\tomato
python train_densenet121.py
```

### 示例2：预测单张图像

```python
# 在infer_densenet121.py中修改
image_path = "val/Tomato_healthy/0a67179b-303a-417a-bd8c-993769e37300___RS_HL 0500.JPG"
img, disease_name, confidence, _ = predict_image(model, image_path, class_names)
display_result(img, disease_name, confidence, image_path)
```

### 示例3：批量预测

```python
# 在infer_densenet121.py中修改
test_dir = "val/Tomato_Bacterial_spot"
batch_results = batch_predict(model, test_dir, class_names)
```

## 常见问题

1. **CUDA错误**：如果遇到CUDA相关错误，请检查NVIDIA驱动和CUDA版本是否与TensorFlow兼容。

2. **内存不足**：如果遇到内存不足错误，可以尝试减小`BATCH_SIZE`或`IMAGE_SIZE`。

3. **模型加载失败**：请确保模型文件路径正确，且已经成功训练了模型。

4. **预测结果不准确**：
   - 增加训练轮数
   - 调整学习率
   - 尝试不同的数据增强策略
   - 确保输入图像与训练时的预处理一致

## 性能比较

- **原始CNN模型**：简单的3层卷积网络，准确率约85%-90%
- **DenseNet121模型**：预训练的深度卷积网络，准确率可达95%-99%

## 扩展建议

1. **增加更多作物**：可以收集其他作物的病害图像，扩展模型的识别范围。

2. **模型优化**：
   - 尝试不同的预训练模型（ResNet、Inception等）
   - 调整模型架构和超参数
   - 使用迁移学习和微调技术

3. **部署应用**：
   - 将模型部署为Web服务
   - 开发移动端应用
   - 集成到农业物联网系统中

## 联系方式

如有问题或建议，请联系系统管理员。
