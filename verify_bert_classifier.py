#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证BERT文本分类器加载
"""

from text_model.infer_text_classifier import BertTextClassifier

if __name__ == "__main__":
    try:
        model_dir = "models/text_cls_bert"
        classifier = BertTextClassifier(model_dir)
        print("✅ BERT文本分类器加载成功")
        
        # 测试预测
        test_symptoms = ["褐色病斑", "黄色晕圈", "轮纹状病斑", "叶片枯萎"]
        probs = classifier.predict_probs(
            symptoms=test_symptoms,
            growth_stage="FLOWERING",
            environment="高湿",
            facility="阳台",
            province="广东省"
        )
        
        if probs:
            print("\n测试预测结果:")
            sorted_probs = sorted(probs.items(), key=lambda x: x[1], reverse=True)[:3]
            for disease, conf in sorted_probs:
                print(f"  - {disease}: {conf*100:.2f}%")
        else:
            print("❌ 预测失败，无结果")
            
    except Exception as e:
        print(f"❌ BERT文本分类器加载失败: {e}")
        import traceback
        traceback.print_exc()
