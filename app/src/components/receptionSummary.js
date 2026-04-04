const asList = (value) => {
  if (!Array.isArray(value)) return [];
  const out = [];
  value.forEach((item) => {
    const text = String(item ?? '').trim();
    if (text) out.push(text);
  });
  return out;
};

export const resolveReceptionSymptomStats = (outputs, debugLabel = 'reception-card') => {
  const symptoms = asList(outputs?.symptoms);
  const normalizedSymptoms = asList(outputs?.normalized_symptoms);
  const profile = (outputs?.symptom_evidence_profile && typeof outputs.symptom_evidence_profile === 'object')
    ? outputs.symptom_evidence_profile
    : {};
  const profileRawTokens = asList(profile.raw_tokens);
  const profileNormalizedTokens = asList(profile.normalized_tokens);
  const removedTokens = asList(outputs?.removed_tokens);

  let source = 'outputs.symptoms';
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
