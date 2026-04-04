export type ReceptionSymptomStats = {
  symptomCount: number;
  symptomCountSource: 'outputs.normalized_symptoms' | 'outputs.symptom_evidence_profile.normalized_tokens' | 'outputs.symptoms';
  removedNonSymptomCount: number;
  symptoms: string[];
  normalizedSymptoms: string[];
  profileRawTokens: string[];
  profileNormalizedTokens: string[];
  removedTokens: string[];
};

const asList = (value: unknown): string[] => {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  value.forEach((item) => {
    const text = String(item ?? '').trim();
    if (text) out.push(text);
  });
  return out;
};

export const resolveReceptionSymptomStats = (outputs: Record<string, unknown>, debugLabel = 'reception-card'): ReceptionSymptomStats => {
  const symptoms = asList(outputs?.symptoms);
  const normalizedSymptoms = asList(outputs?.normalized_symptoms);
  const profile = (outputs?.symptom_evidence_profile && typeof outputs.symptom_evidence_profile === 'object')
    ? outputs.symptom_evidence_profile as Record<string, unknown>
    : {};
  const profileRawTokens = asList(profile.raw_tokens);
  const profileNormalizedTokens = asList(profile.normalized_tokens);
  const removedTokens = asList(outputs?.removed_tokens);

  let source: ReceptionSymptomStats['symptomCountSource'] = 'outputs.symptoms';
  let count = symptoms.length;
  if (normalizedSymptoms.length) {
    source = 'outputs.normalized_symptoms';
    count = normalizedSymptoms.length;
  } else if (profileNormalizedTokens.length) {
    source = 'outputs.symptom_evidence_profile.normalized_tokens';
    count = profileNormalizedTokens.length;
  }

  console.debug(`[${debugLabel}] symptom count debug`, {
    symptoms,
    normalized_symptoms: normalizedSymptoms,
    symptom_evidence_profile_raw_tokens: profileRawTokens,
    symptom_evidence_profile_normalized_tokens: profileNormalizedTokens,
    removed_tokens: removedTokens,
    symptom_count_source: source,
    symptom_count: count,
  });

  return {
    symptomCount: count,
    symptomCountSource: source,
    removedNonSymptomCount: removedTokens.length,
    symptoms,
    normalizedSymptoms,
    profileRawTokens,
    profileNormalizedTokens,
    removedTokens,
  };
};
