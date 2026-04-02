from __future__ import annotations

FOLLOW_UP_RULES = {
    "ui_mode_templates": {
        "image": [
            "请补拍叶片正面、背面和病斑特写各1张？",
            "请确保病斑区域清晰、避免逆光和模糊？",
            "请让病斑区域尽量占画面主体，避免距离过远？",
            "如可能，请补拍整株与局部病斑的对照图？",
        ],
        "text": [
            "病斑最先出现在哪个部位（下位老叶/中部叶/顶部新叶）？",
            "病斑颜色变化顺序是怎样的（黄绿→褐色→黑褐）？",
            "病斑边缘是否清晰，是否伴随黄晕或水渍感？",
        ],
        "image_and_text": [
            "请补拍叶片正反面和病斑特写，保证病斑清晰可见？",
            "请补充病斑颜色、边缘、是否有霉层/水渍状表现？",
            "请补充近期棚内湿度、通风和降雨情况？",
        ],
    },
    "confusion_group_questions": {
        "斑点叶斑组": [
            "病斑是很多很小的小点，还是较大的圆斑？",
            "病斑里有没有同心轮纹或靶心样纹路？",
            "叶背是否有白色霉层或橄榄色绒霉？",
            "斑点中心有没有黑色小点？",
            "病斑早期是否有水渍状或油浸样表现？",
            "果实上是否有痂状斑、深凹斑或X形裂纹？",
        ],
        "病毒组": [
            "叶片是整体黄化上卷，还是明暗相间花叶斑驳？",
            "是否有节间缩短、植株矮化丛生？",
            "是否有蕨叶样或线叶样畸形？",
            "新叶是否明显变小、皱缩？",
            "果实是否有斑驳或着色不均？",
        ],
        "蜘蛛螨混淆组": [
            "叶背是否有细网？",
            "叶面是否有密集黄白小点？",
            "叶片是否青铜化或发灰发脏？",
            "最近是否高温干燥？",
            "叶背是否能看到小虫点？",
        ],
    },
    "weak_evidence_priorities": {
        "image_weak": {"prefer": "image", "max_image": 3, "max_text": 1},
        "text_weak": {"prefer": "text", "max_image": 1, "max_text": 3},
        "both_weak": {"prefer": "both", "max_image": 2, "max_text": 2},
        "low_margin": {"prefer": "discriminative", "max_image": 1, "max_text": 3},
        "weak_image_text_conflict": {"prefer": "conflict", "max_image": 2, "max_text": 2},
    },
}
