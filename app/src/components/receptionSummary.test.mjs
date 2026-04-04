import test from 'node:test';
import assert from 'node:assert/strict';

import { resolveReceptionSymptomStats } from './receptionSummary.js';

test('reception summary counts only normalized symptoms', () => {
  const stats = resolveReceptionSymptomStats({
    normalized_symptoms: ['发黄', '卷曲', '叶背白霉', '病斑扩展'],
    symptoms: ['发黄', '卷曲', '叶背白霉', '病斑扩展', '作物类型：番茄'],
    removed_tokens: ['作物类型：番茄'],
  }, 'test.reception');

  assert.equal(stats.symptomCount, 4);
  assert.equal(stats.symptomCountSource, 'outputs.normalized_symptoms');
});

test('removed_tokens are not counted as symptoms', () => {
  const stats = resolveReceptionSymptomStats({
    symptoms: ['发黄', '卷曲', '叶背白霉', '病斑扩展'],
    removed_tokens: ['作物类型：番茄'],
    follow_up_questions: ['请补充叶背是否有霉层？'],
    candidate_diseases: ['晚疫病'],
  }, 'test.reception');

  assert.equal(stats.symptomCount, 4);
  assert.equal(stats.removedNonSymptomCount, 1);
});

test('merged trace outputs do not inflate symptom count', () => {
  const mergedLikeOutputs = {
    normalized_symptoms: ['发黄', '卷曲', '叶背白霉', '病斑扩展'],
    symptoms: ['发黄', '卷曲', '叶背白霉', '病斑扩展'],
    removed_tokens: ['作物类型：番茄'],
    risk_tags: ['high_humidity'],
    missing_profile_fields: ['facility'],
    follow_up_questions: ['请补充叶背是否有霉层？'],
    candidate_diseases: ['晚疫病', '叶霉病'],
  };

  const stats = resolveReceptionSymptomStats(mergedLikeOutputs, 'test.reception');
  assert.equal(stats.symptomCount, 4);
  assert.equal(stats.symptomCountSource, 'outputs.normalized_symptoms');
});

test('confirm stage does not overwrite reception symptom count with empty top-level fields', () => {
  const receptionFinalOutputs = {
    normalized_symptoms: ['发黄', '卷曲', '叶背白霉', '病斑扩展'],
    symptoms: ['发黄', '卷曲', '叶背白霉', '病斑扩展'],
  };
  const confirmTopLevelLike = {
    normalized_symptoms: [],
    symptoms: [],
  };

  const receptionStats = resolveReceptionSymptomStats(receptionFinalOutputs, 'test.reception');
  const confirmStats = resolveReceptionSymptomStats(confirmTopLevelLike, 'test.confirm');

  assert.equal(receptionStats.symptomCount, 4);
  assert.equal(confirmStats.symptomCount, 0);
  assert.equal(receptionStats.symptomCountSource, 'outputs.normalized_symptoms');
});
