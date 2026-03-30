export type DiagnoseReviewViewInput = {
  status?: string;
  expert_review_recommended?: boolean;
  expert_review_status?: string;
};

export type DiagnoseReviewViewFlags = {
  expertReviewRecommended: boolean;
  expertReviewPending: boolean;
  expertReviewCompleted: boolean;
  shouldShowExpertReviewDecision: boolean;
  shouldHideTreatment: boolean;
};

export function deriveDiagnoseReviewViewFlags(
  result: DiagnoseReviewViewInput | null | undefined,
  shouldShowSupplementSection: boolean,
): DiagnoseReviewViewFlags {
  const expertReviewRecommended = result?.expert_review_recommended === true;
  const expertReviewPending = result?.status === 'pending_expert_review' || result?.expert_review_status === 'PENDING';
  const expertReviewCompleted = result?.expert_review_status === 'COMPLETED';
  const shouldShowExpertReviewDecision = result?.status === 'waiting_for_expert_decision'
    && expertReviewRecommended
    && !expertReviewPending;
  const shouldHideTreatment = shouldShowSupplementSection || shouldShowExpertReviewDecision || expertReviewPending;
  return {
    expertReviewRecommended,
    expertReviewPending,
    expertReviewCompleted,
    shouldShowExpertReviewDecision,
    shouldHideTreatment,
  };
}
