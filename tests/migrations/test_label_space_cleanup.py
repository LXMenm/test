import json

from knowledge_base import get_kb_manager
from diagnosis_model import DiseaseDiagnosisEngine

FORBIDDEN = {"白粉病", "灰霉病"}
TEN = {
    "健康", "早疫病", "晚疫病", "黄化曲叶病毒病", "叶霉病",
    "细菌性斑点病", "叶斑病", "蜘蛛螨", "靶斑病", "花叶病毒病",
}


def test_kb_files_do_not_contain_forbidden_diseases():
    for path in [
        "data/kb/diseases.json",
        "data/kb/rules.json",
        "data/kb/symptom_map.json",
        "data/kb/treatments.json",
    ]:
        text = open(path, "r", encoding="utf-8").read()
        for disease in FORBIDDEN:
            assert disease not in text


def test_kb_manager_classes_are_exactly_ten():
    kb = get_kb_manager()
    classes = set(kb.get_disease_classes())
    assert classes == TEN


def test_probs_keys_stay_in_ten_classes():
    kb = get_kb_manager()
    probs = kb.score_diseases_from_text("番茄", ["发黄", "卷曲", "生长缓慢"], growth_stage="SEEDLING")
    assert set(probs.keys()).issubset(TEN)

    prior = DiseaseDiagnosisEngine.build_prior_proba(None, growth_stage="FLOWERING", facility="温室")
    assert set(prior.keys()).issubset(TEN)
