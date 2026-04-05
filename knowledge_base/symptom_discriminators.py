from __future__ import annotations

from typing import Any

GENERIC_SYMPTOMS = {
    "斑点",
    "叶斑",
    "发黄",
    "枯萎",
    "卷曲",
    "生长缓慢",
    "花叶",
}

SYMPTOM_ALIASES: dict[str, str] = {
    "一圈一圈的病斑": "同心轮纹",
    "像年轮一样": "年轮样病斑",
    "叶背有白毛": "叶背白霉",
    "白色霉层": "叶背白霉",
    "灰白霉层": "叶背白霉",
    "叶背有霉": "叶背霉层",
    "叶背霉层": "叶背霉层",
    "有霉层": "叶背霉层",
    "霉层明显": "叶背霉层",
    "叶背有橄榄色霉层": "叶背橄榄绒霉",
    "橄榄色霉层": "叶背橄榄绒霉",
    "斑里有黑点": "黑色小点",
    "叶片有小孔": "叶片穿孔",
    "叶背有细网": "叶背结网",
    "像靶子一样": "靶心状病斑",
    "果面裂成X": "X形裂纹",
    "嫩叶变小": "新叶变小",
    "叶子往上卷": "叶片上卷",
    "叶子皱巴巴": "叶片皱缩",
    "叶片一块深一块浅": "明暗相间花叶",
    "像马赛克一样": "斑驳镶嵌",
}

SYMPTOM_DISCRIMINATOR_GROUPS: dict[str, list[str]] = {
    "同心轮纹": ["斑点叶斑组"],
    "叶背白霉": ["斑点叶斑组"],
    "叶背霉层": ["斑点叶斑组"],
    "叶背橄榄绒霉": ["斑点叶斑组"],
    "黑色小点": ["斑点叶斑组"],
    "水渍状快速扩展": ["斑点叶斑组"],
    "靶心状病斑": ["斑点叶斑组", "蜘蛛螨混淆组"],
    "叶背结网": ["蜘蛛螨混淆组"],
    "青铜化": ["蜘蛛螨混淆组"],
    "节间缩短": ["病毒组"],
    "明暗相间花叶": ["病毒组"],
}

CONFUSION_GROUPS: dict[str, list[str]] = {
    "斑点叶斑组": ["细菌性斑点病", "早疫病", "晚疫病", "叶霉病", "叶斑病", "靶斑病"],
    "病毒组": ["黄化曲叶病毒病", "花叶病毒病"],
    "蜘蛛螨混淆组": ["蜘蛛螨", "细菌性斑点病", "早疫病", "叶斑病", "靶斑病"],
}

FOLLOW_UP_HINTS: dict[str, list[str]] = {
    "斑点叶斑组": [
        "有没有同心轮纹？",
        "叶背有没有白色霉层？",
        "叶背有没有橄榄色绒霉？",
        "斑点中间有没有黑色小点？",
        "病斑早期是不是水渍状？",
        "果实有没有痂状斑、深凹斑、X形裂纹？",
    ],
    "病毒组": [
        "是整体黄化上卷，还是明暗相间花叶斑驳？",
        "是否有节间缩短、矮化丛生？",
        "是否有蕨叶样或线叶样？",
        "果实是否斑驳或着色不均？",
    ],
    "蜘蛛螨混淆组": [
        "叶背是否有细网？",
        "叶面是否有密集黄白小点？",
        "叶片是否青铜化？",
        "最近是否高温干燥？",
    ],
}

NEGATIVE_CUES: dict[str, list[str]] = {
    "病毒组": ["叶背白霉", "叶背橄榄绒霉", "叶背结网"],
}

DISCRIMINATIVE_SYMPTOM_DISEASES: dict[str, list[str]] = {
    "同心轮纹": ["早疫病"],
    "年轮样病斑": ["早疫病"],
    "叶背白霉": ["晚疫病"],
    "叶背霉层": ["晚疫病", "叶霉病"],
    "叶背橄榄绒霉": ["叶霉病"],
    "黑色小点": ["叶斑病"],
    "叶背结网": ["蜘蛛螨"],
    "X形裂纹": ["靶斑病"],
    "节间缩短": ["黄化曲叶病毒病"],
    "明暗相间花叶": ["花叶病毒病"],
}


def build_default_symptom_payload() -> dict[str, Any]:
    symptom_tiers = {symptom: "generic" for symptom in GENERIC_SYMPTOMS}
    for symptom in DISCRIMINATIVE_SYMPTOM_DISEASES.keys():
        symptom_tiers[symptom] = "discriminative"
    for symptom in SYMPTOM_DISCRIMINATOR_GROUPS.keys():
        symptom_tiers.setdefault(symptom, "discriminative")
    return {
        "symptom_tiers": symptom_tiers,
        "symptom_discriminator_groups": SYMPTOM_DISCRIMINATOR_GROUPS,
        "follow_up_hints": FOLLOW_UP_HINTS,
        "negative_cues": NEGATIVE_CUES,
    }
