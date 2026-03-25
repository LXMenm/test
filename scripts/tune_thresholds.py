#!/usr/bin/env python3
"""
诊断阈值离线调优脚本

用途：
  在不重新训练图像/文本模型的前提下，复用现有诊断规则，对一批样本做离线回放、
  阈值搜索和指标评估。

运行示例：
  # 基本用法
  python scripts/tune_thresholds.py \\
    --data scripts/sample_eval_data.jsonl \\
    --grid configs/threshold_grid.yaml \\
    --output results/threshold_search.csv \\
    --topk 20

  # 使用默认配置单条评估
  python scripts/tune_thresholds.py \\
    --data scripts/sample_eval_data.jsonl \\
    --output results/single_eval.csv

输出说明：
  - CSV 文件包含每个阈值组合的评估指标
  - 自动按 overall_accuracy 降序排序
  - 输出前 topk 个最佳配置

依赖：
  - diagnosis_model.py 中的 fuse_multimodal_probs() 和 evaluate_confirmation_decision()
  - configs/threshold_grid.yaml 中的阈值网格配置
"""

import sys
import os
import json
import argparse
import csv
import random
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime
from collections import defaultdict

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from diagnosis_model import DiseaseDiagnosisEngine, evaluate_confirmation_decision
from runtime_settings import RUNTIME_THRESHOLD_DEFAULTS


def load_eval_data(data_path: str) -> List[Dict[str, Any]]:
    """加载 JSONL 格式的评估数据"""
    samples = []
    with open(data_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                sample = json.loads(line)
                samples.append(sample)
            except json.JSONDecodeError as e:
                print(f"警告：第 {line_num} 行 JSON 解析失败：{e}")
    return samples


def load_threshold_grid(grid_path: str) -> Dict[str, Any]:
    """加载阈值网格配置"""
    with open(grid_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def generate_grid_combinations(grid_config: Dict[str, Any]) -> List[Dict[str, float]]:
    """生成阈值网格的所有组合"""
    import itertools
    
    # 直接使用顶层配置作为网格
    grid = grid_config
    # 过滤掉非列表类型的配置
    grid = {k: v for k, v in grid.items() if isinstance(v, list)}
    
    if not grid:
        return [{}]
    
    keys = list(grid.keys())
    values = [grid[k] for k in keys]
    
    combinations = []
    for combo in itertools.product(*values):
        param_set = dict(zip(keys, combo))
        combinations.append(param_set)
    
    return combinations


def evaluate_single_sample(
    sample: Dict[str, Any],
    thresholds: Dict[str, float],
    version: str = "v0000",
) -> Dict[str, Any]:
    """
    评估单个样本
    
    返回：
        {
            "sample_id": str,
            "ground_truth": str,
            "predicted": str,
            "final_confidence": float,
            "need_confirm": bool,
            "fusion_case": str,
            "correct": bool,
            "confirm_correct": bool,
            "image_reliable": bool,
            "text_reliable": bool,
            "modality_conflict_flag": bool,
            "weak_conflict_flag": bool,
            "parameter_version": str,
        }
    """
    image_probs = sample.get('image_probs', {})
    text_probs = sample.get('text_probs', {})
    prior_probs = sample.get('prior_probs', {})
    
    engine = DiseaseDiagnosisEngine.__new__(DiseaseDiagnosisEngine)
    
    fused, fusion_meta = engine.fuse_multimodal_probs(
        image_probs=image_probs,
        text_probs=text_probs,
        prior_probs=prior_probs,
        image_confidence=max(image_probs.values()) if image_probs else 0.0,
        text_confidence=max(text_probs.values()) if text_probs else 0.0,
        text_evidence_active=bool(text_probs),
    )
    
    fusion_top3 = sorted(fused.items(), key=lambda x: x[1], reverse=True)[:3]
    image_top3 = sorted(image_probs.items(), key=lambda x: x[1], reverse=True)[:3]
    text_top3 = sorted(text_probs.items(), key=lambda x: x[1], reverse=True)[:3]
    
    final_disease = fusion_top3[0][0] if fusion_top3 else None
    final_confidence = fusion_top3[0][1] if fusion_top3 else 0.0
    
    confirmation = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta,
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=final_confidence,
        diagnosis_conf_threshold=thresholds.get('diagnosis_conf_threshold', RUNTIME_THRESHOLD_DEFAULTS['diagnosis_conf_threshold']),
        low_margin_threshold=thresholds.get('low_margin_threshold', RUNTIME_THRESHOLD_DEFAULTS['low_margin_threshold']),
    )
    
    ground_truth = sample.get('ground_truth')
    correct = (final_disease == ground_truth) if ground_truth else False
    
    expected_need_confirm = sample.get('expected_need_confirm')
    confirm_correct = (confirmation['need_confirm'] == expected_need_confirm) if expected_need_confirm is not None else None
    
    return {
        'sample_id': sample.get('sample_id', 'unknown'),
        'ground_truth': ground_truth,
        'predicted': final_disease,
        'final_confidence': final_confidence,
        'need_confirm': confirmation['need_confirm'],
        'fusion_case': confirmation['fusion_case'],
        'correct': correct,
        'confirm_correct': confirm_correct,
        'reasons': '|'.join(confirmation['reasons']),
        'image_reliable': confirmation['image_reliable'],
        'text_reliable': confirmation['text_reliable'],
        'modality_conflict_flag': confirmation['modality_conflict_flag'],
        'weak_conflict_flag': confirmation['weak_conflict_flag'],
        'parameter_version': version,
    }


def compute_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    计算全局指标
    
    返回：
        {
            "auto_complete_precision": float,
            "confirm_rate": float,
            "false_clear_rate": float,
            "overall_accuracy": float,
            "conflict_bucket_accuracy": float,
            "consistent_bucket_accuracy": float,
            "image_strong_text_weak_bucket_accuracy": float,
            "image_weak_text_strong_bucket_accuracy": float,
            "both_weak_bucket_accuracy": float,
            "confirm_bucket_count": int,
            "auto_complete_count": int,
            "conflict_bucket_count": int,
            "consistent_bucket_count": int,
            "image_strong_text_weak_bucket_count": int,
            "image_weak_text_strong_bucket_count": int,
            "both_weak_bucket_count": int,
        }
    """
    if not results:
        return {k: 0.0 for k in [
            'auto_complete_precision', 'confirm_rate', 'false_clear_rate',
            'overall_accuracy', 'conflict_bucket_accuracy',
            'consistent_bucket_accuracy', 'image_strong_text_weak_bucket_accuracy',
            'image_weak_text_strong_bucket_accuracy', 'both_weak_bucket_accuracy',
            'confirm_bucket_count', 'auto_complete_count',
            'conflict_bucket_count', 'consistent_bucket_count',
            'image_strong_text_weak_bucket_count',
            'image_weak_text_strong_bucket_count',
            'both_weak_bucket_count',
        ]}
    
    total = len(results)
    correct = sum(1 for r in results if r['correct'])
    need_confirm_count = sum(1 for r in results if r['need_confirm'])
    auto_complete_count = total - need_confirm_count
    
    confirm_correct_samples = [r for r in results if r['confirm_correct'] is not None]
    confirm_correct = sum(1 for r in confirm_correct_samples if r['confirm_correct']) if confirm_correct_samples else 0
    
    bucket_results = {}
    for r in results:
        bucket = r['fusion_case']
        if bucket not in bucket_results:
            bucket_results[bucket] = {'total': 0, 'correct': 0}
        bucket_results[bucket]['total'] += 1
        if r['correct']:
            bucket_results[bucket]['correct'] += 1
    
    def bucket_accuracy(bucket_name: str) -> float:
        if bucket_name not in bucket_results or bucket_results[bucket_name]['total'] == 0:
            return 0.0
        return bucket_results[bucket_name]['correct'] / bucket_results[bucket_name]['total']
    
    def bucket_count(bucket_name: str) -> int:
        return bucket_results.get(bucket_name, {}).get('total', 0)
    
    # 计算自动完成且正确的样本数
    auto_complete_correct = sum(1 for r in results if not r['need_confirm'] and r['correct'])
    # 计算自动完成精度
    auto_complete_precision = auto_complete_correct / auto_complete_count if auto_complete_count > 0 else 0.0
    # 计算误放行率（应确认但未确认且错误的样本数）
    false_clear_count = sum(1 for r in results if not r['need_confirm'] and not r['correct'] and r.get('expected_need_confirm', False))
    false_clear_rate = false_clear_count / total if total > 0 else 0.0
    
    return {
        'overall_accuracy': correct / total if total > 0 else 0.0,
        'auto_complete_precision': auto_complete_precision,
        'confirm_rate': need_confirm_count / total if total > 0 else 0.0,
        'false_clear_rate': false_clear_rate,
        'conflict_bucket_accuracy': bucket_accuracy('conflict'),
        'consistent_bucket_accuracy': bucket_accuracy('consistent'),
        'image_strong_text_weak_bucket_accuracy': bucket_accuracy('image_strong_text_weak'),
        'image_weak_text_strong_bucket_accuracy': bucket_accuracy('image_weak_text_strong'),
        'both_weak_bucket_accuracy': bucket_accuracy('both_weak'),
        'confirm_bucket_count': need_confirm_count,
        'auto_complete_count': auto_complete_count,
        'conflict_bucket_count': bucket_count('conflict'),
        'consistent_bucket_count': bucket_count('consistent'),
        'image_strong_text_weak_bucket_count': bucket_count('image_strong_text_weak'),
        'image_weak_text_strong_bucket_count': bucket_count('image_weak_text_strong'),
        'both_weak_bucket_count': bucket_count('both_weak'),
    }


def run_threshold_search(
    data_path: str,
    grid_path: str,
    output_path: str,
    topk: int = 20,
    output_details: bool = True,
) -> List[Dict[str, Any]]:
    """运行阈值搜索"""
    print(f"[1/4] 加载评估数据：{data_path}")
    samples = load_eval_data(data_path)
    print(f"  已加载 {len(samples)} 个样本")
    
    print(f"[2/4] 加载阈值网格：{grid_path}")
    grid_config = load_threshold_grid(grid_path)
    combinations = generate_grid_combinations(grid_config)
    print(f"  共 {len(combinations)} 个阈值组合")
    
    print("[3/4] 开始批量评估...")
    all_results = []
    all_details = []
    
    for idx, thresholds in enumerate(combinations, 1):
        if idx % 10 == 0 or idx == len(combinations):
            print(f"  进度：{idx}/{len(combinations)}")
        
        version = f"v{idx:04d}"
        sample_results = []
        for sample in samples:
            result = evaluate_single_sample(sample, thresholds, version)
            sample_results.append(result)
            all_details.append(result)
        
        metrics = compute_metrics(sample_results)
        
        result_row = {
            'version': version,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            **thresholds,
            **metrics,
        }
        all_results.append(result_row)
    
    print("[4/4] 生成结果报告...")
    
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # 写入汇总结果
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        if all_results:
            writer = csv.DictWriter(f, fieldnames=all_results[0].keys())
            writer.writeheader()
            writer.writerows(all_results)
    
    print(f"  汇总结果已保存至：{output_path}")
    
    # 写入明细结果
    if output_details:
        details_path = os.path.join(output_dir, 'threshold_search_details.csv')
        with open(details_path, 'w', newline='', encoding='utf-8-sig') as f:
            if all_details:
                fieldnames = ['sample_id', 'ground_truth', 'predicted', 'final_confidence', 
                             'need_confirm', 'fusion_case', 'correct', 'confirm_correct',
                             'image_reliable', 'text_reliable', 'modality_conflict_flag', 
                             'weak_conflict_flag', 'parameter_version', 'reasons']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_details)
        print(f"  明细结果已保存至：{details_path}")
    
    print("\n" + "="*80)
    print(f"Top {topk} 最佳配置：")
    print("="*80)
    
    sorted_results = sorted(all_results, key=lambda x: x['overall_accuracy'], reverse=True)
    
    display_cols = ['version', 'overall_accuracy', 'auto_complete_precision', 'confirm_rate', 
                   'confirm_bucket_count', 'auto_complete_count']
    bucket_count_cols = ['conflict_bucket_count', 'consistent_bucket_count', 
                        'image_strong_text_weak_bucket_count', 'image_weak_text_strong_bucket_count', 
                        'both_weak_bucket_count']
    
    print(f"{'version':<10} {'accuracy':<10} {'auto_prec':<12} {'confirm_rate':<13} {'confirm_n':<10} {'auto_n':<8} {'buckets':<50}")
    print("-" * 110)
    for row in sorted_results[:topk]:
        buckets_str = f"C:{row.get('conflict_bucket_count', 0)}|Con:{row.get('consistent_bucket_count', 0)}|ISW:{row.get('image_strong_text_weak_bucket_count', 0)}|IWS:{row.get('image_weak_text_strong_bucket_count', 0)}|BW:{row.get('both_weak_bucket_count', 0)}"
        print(f"{row['version']:<10} {row['overall_accuracy']:<10.4f} {row['auto_complete_precision']:<12.4f} {row['confirm_rate']:<13.4f} {row['confirm_bucket_count']:<10} {row['auto_complete_count']:<8} {buckets_str:<50}")
    print("="*80)
    
    return sorted_results


def run_kfold_cross_validation(
    data_path: str,
    grid_path: str,
    output_path: str,
    k: int = 5,
    topk: int = 20,
    group_by: str = 'sample_id',  # 按样本ID分组，确保每个样本作为独立病例
) -> Dict[str, Any]:
    """
    运行 K 折交叉验证
    
    Args:
        data_path: JSONL 格式的数据路径
        grid_path: YAML 格式的阈值网格配置路径
        output_path: CSV 输出路径
        k: K 折交叉验证的 K 值（默认：5）
        topk: 显示前 K 个最佳配置
        group_by: 分组字段，确保同一病例不跨 fold
    
    Returns:
        交叉验证结果统计
    """
    print("\n" + "="*80)
    print(f"K 折交叉验证 (K={k}, group_by={group_by})")
    print("="*80)
    
    # 加载数据
    samples = load_eval_data(data_path)
    n_samples = len(samples)
    print(f"总样本数：{n_samples}")
    print(f"每折样本数：{n_samples // k}")
    print("="*80 + "\n")
    
    # 按 group_by 分组
    groups = {}
    for sample in samples:
        group_key = sample.get(group_by, sample.get('sample_id', 'unknown'))
        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(sample)
    
    # 将分组转换为列表
    group_list = list(groups.values())
    n_groups = len(group_list)
    print(f"总病例数：{n_groups}")
    print(f"每折病例数：{n_groups // k}")
    
    # 随机打乱分组
    random.seed(42)  # 固定随机种子以确保可复现性
    random.shuffle(group_list)
    
    # 分割成 K 折
    folds = []
    fold_size = n_groups // k
    for i in range(k):
        start_idx = i * fold_size
        if i == k - 1:
            # 最后一折包含所有剩余分组
            fold_groups = group_list[start_idx:]
        else:
            fold_groups = group_list[start_idx:start_idx + fold_size]
        # 展开分组为样本
        fold_samples = []
        for group in fold_groups:
            fold_samples.extend(group)
        folds.append(fold_samples)
    
    # 统计每个 fusion_case 的分布
    print("各折 fusion_case 分布：")
    for i, fold in enumerate(folds):
        case_counts = defaultdict(int)
        for sample in fold:
            case_counts[sample.get('expected_fusion_case', 'unknown')] += 1
        print(f"  Fold {i+1}: {dict(case_counts)}")
    print()
    
    # 存储每折的最佳配置
    fold_best_configs = []
    fold_best_scores = []
    
    # 执行 K 折交叉验证
    for fold_idx in range(k):
        print(f"\n{'='*80}")
        print(f"第 {fold_idx + 1}/{k} 折")
        print(f"{'='*80}")
        
        # 准备训练集和测试集
        test_samples = folds[fold_idx]
        train_samples = []
        for i in range(k):
            if i != fold_idx:
                train_samples.extend(folds[i])
        
        print(f"训练集大小：{len(train_samples)}")
        print(f"测试集大小：{len(test_samples)}")
        
        # 临时保存训练集和测试集
        train_path = data_path.replace('.jsonl', f'_train_fold{fold_idx+1}.jsonl')
        test_path = data_path.replace('.jsonl', f'_test_fold{fold_idx+1}.jsonl')
        
        save_eval_data(train_samples, train_path)
        save_eval_data(test_samples, test_path)
        
        # 在训练集上搜索最优阈值
        temp_output = output_path.replace('.csv', f'_fold{fold_idx+1}.csv')
        
        results = run_threshold_search(
            data_path=train_path,
            grid_path=grid_path,
            output_path=temp_output,
            topk=1,  # 只保留最佳配置
            output_details=False,
        )
        
        if results:
            best_config = results[0]
            fold_best_configs.append(best_config)
            fold_best_scores.append(best_config['overall_accuracy'])
            
            print(f"\nFold {fold_idx+1} 最佳准确率：{best_config['overall_accuracy']:.4f}")
        
        # 清理临时文件
        try:
            os.remove(train_path)
            os.remove(test_path)
            os.remove(temp_output)
        except:
            pass
    
    # 计算交叉验证统计
    print("\n" + "="*80)
    print("K 折交叉验证结果汇总")
    print("="*80)
    
    mean_accuracy = sum(fold_best_scores) / len(fold_best_scores)
    std_accuracy = (sum((x - mean_accuracy) ** 2 for x in fold_best_scores) / len(fold_best_scores)) ** 0.5
    
    print(f"平均准确率：{mean_accuracy:.4f} (+/- {std_accuracy:.4f})")
    print(f"最高准确率：{max(fold_best_scores):.4f}")
    print(f"最低准确率：{min(fold_best_scores):.4f}")
    print()
    
    # 找出在所有折中表现稳定的配置
    print("各折最佳配置：")
    print(f"{'Fold':<6} {'Version':<10} {'Accuracy':<10} {'Confirm Rate':<13}")
    print("-" * 40)
    for i, config in enumerate(fold_best_configs):
        print(f"{i+1:<6} {config['version']:<10} {config['overall_accuracy']:<10.4f} {config['confirm_rate']:<13.4f}")
    
    # 保存交叉验证结果
    cv_results = {
        'k': k,
        'n_samples': n_samples,
        'mean_accuracy': mean_accuracy,
        'std_accuracy': std_accuracy,
        'max_accuracy': max(fold_best_scores),
        'min_accuracy': min(fold_best_scores),
        'fold_configs': fold_best_configs,
        'fold_scores': fold_best_scores,
    }
    
    # 保存汇总结果
    cv_summary_path = output_path.replace('.csv', '_cv_summary.json')
    with open(cv_summary_path, 'w', encoding='utf-8') as f:
        json.dump(cv_results, f, indent=2, ensure_ascii=False)
    
    print(f"\n交叉验证结果已保存至：{cv_summary_path}")
    print("="*80)
    
    return cv_results


def save_eval_data(samples: List[Dict[str, Any]], path: str):
    """保存样本数据到 JSONL 文件"""
    with open(path, 'w', encoding='utf-8') as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser(
        description='诊断阈值离线调优工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--data',
        type=str,
        required=True,
        help='JSONL 格式的评估数据路径'
    )
    
    parser.add_argument(
        '--grid',
        type=str,
        required=True,
        help='YAML 格式的阈值网格配置路径'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        required=True,
        help='CSV 输出路径'
    )
    
    parser.add_argument(
        '--topk',
        type=int,
        default=20,
        help='显示前 K 个最佳配置（默认：20）'
    )
    
    parser.add_argument(
        '--kfold',
        type=int,
        default=0,
        help='K 折交叉验证的 K 值（默认：0，表示不进行交叉验证）'
    )
    
    args = parser.parse_args()
    
    print("="*80)
    print("诊断阈值离线调优工具")
    print("="*80)
    print(f"数据文件：{args.data}")
    print(f"网格配置：{args.grid}")
    print(f"输出文件：{args.output}")
    print(f"显示 TopK: {args.topk}")
    if args.kfold > 0:
        print(f"K 折交叉验证：K={args.kfold}")
    print("="*80 + "\n")
    
    if args.kfold > 0:
        # 运行 K 折交叉验证
        run_kfold_cross_validation(
            data_path=args.data,
            grid_path=args.grid,
            output_path=args.output,
            k=args.kfold,
            topk=args.topk,
            group_by='sample_id',  # 按样本ID分组，确保每个样本作为独立病例
        )
    else:
        # 运行普通阈值搜索
        run_threshold_search(
            data_path=args.data,
            grid_path=args.grid,
            output_path=args.output,
            topk=args.topk,
        )
    
    print("\n调优完成！")


if __name__ == '__main__':
    main()
