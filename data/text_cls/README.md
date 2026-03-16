# 文本分类训练数据格式

CSV 必填字段：
- `text`: 用户原始文本描述
- `label`: 病害中文标签（必须在 10 类 canonical disease 中）

可选增强字段：
- `symptoms`
- `growth_stage`
- `environment`
- `facility`
- `province`

训练时会将可选字段拼接到最终输入文本，例如：

`症状：斑点 发黄；生育期：FRUIT_SET；环境：高湿；设施：阳台；地区：广东省；原始描述：叶片出现很多小斑点，边缘发黄`
