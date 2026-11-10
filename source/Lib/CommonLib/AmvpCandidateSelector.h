// Deterministic, pixel-free selection for the experimental AMVP mode 7.
#ifndef AMVP_CANDIDATE_SELECTOR_H
#define AMVP_CANDIDATE_SELECTOR_H

#include "Mv.h"
#include "RdCost.h"

namespace AmvpCandidateSelector
{
// The input pool keeps the existing derivation order. Padding has no vote and
// is not a selectable centre, unless fewer than two real hypotheses exist (in
// which case the original list is retained). The output is a full permutation;
// only its first two entries become the formal AMVP list. No CU/pixel state,
// final MV, actual MVD, template rank, or encoder-only RD state is consulted.
inline void reorderMotionOnly(const Mv *candidates, const bool *validCandidates, const int numCandidates,
                              const int imv, Mv *reordered)
{
  CHECK(numCandidates < AMVP_MAX_NUM_CANDS || numCandidates > AMVP_ARMC_MAX_NUM_CANDS,
        "Invalid motion-only AMVP pool size");
  CHECK(imv < 0 || imv > 3, "Invalid translational AMVR precision");

  Mv original[AMVP_ARMC_MAX_NUM_CANDS];
  Mv coded[AMVP_ARMC_MAX_NUM_CANDS];
  int uniqueIdx[AMVP_ARMC_MAX_NUM_CANDS];
  int numUnique = 0;
  for (int idx = 0; idx < numCandidates; idx++)
  {
    original[idx] = candidates[idx];
    reordered[idx] = candidates[idx];
    if (!validCandidates[idx])
    {
      continue;
    }
    Mv candidate = candidates[idx];
    candidate.changeTransPrecInternal2Amvr(imv);
    bool duplicate = false;
    for (int unique = 0; unique < numUnique; unique++)
    {
      duplicate |= coded[unique] == candidate;
    }
    if (!duplicate)
    {
      uniqueIdx[numUnique] = idx;
      coded[numUnique++] = candidate;
    }
  }
  if (numUnique < AMVP_MAX_NUM_CANDS)
  {
    return;
  }

  // Reuse the ordinary AMVP Exp-Golomb length proxy at the current AMVR
  // code precision. Precompute once, not once per evaluated centre pair.
  uint32_t bits[AMVP_ARMC_MAX_NUM_CANDS][AMVP_ARMC_MAX_NUM_CANDS];
  for (int k = 0; k < numUnique; k++)
  {
    for (int i = 0; i < numUnique; i++)
    {
      const Mv delta = coded[k] - coded[i];
      bits[k][i] = RdCost::xGetExpGolombNumberOfBits(delta.getHor())
                   + RdCost::xGetExpGolombNumberOfBits(delta.getVer());
    }
  }

  int bestFirst = 0;
  int bestSecond = 1;
  uint64_t bestCost = std::numeric_limits<uint64_t>::max();
  for (int i = 0; i < numUnique - 1; i++)
  {
    for (int j = i + 1; j < numUnique; j++)
    {
      uint64_t cost = 0;
      for (int k = 0; k < numUnique; k++)
      {
        // Every distinct, non-padding motion hypothesis has weight one.
        cost += std::min(bits[k][i], bits[k][j]);
      }
      // Strict comparison gives ties to the lexicographically earliest pair
      // in the original pool, also fixing which centre becomes MVP0.
      if (cost < bestCost)
      {
        bestCost = cost;
        bestFirst = i;
        bestSecond = j;
      }
    }
  }

  const int firstIdx = uniqueIdx[bestFirst];
  const int secondIdx = uniqueIdx[bestSecond];
  reordered[0] = original[firstIdx];
  reordered[1] = original[secondIdx];
  int outputIdx = AMVP_MAX_NUM_CANDS;
  for (int idx = 0; idx < numCandidates; idx++)
  {
    if (idx != firstIdx && idx != secondIdx)
    {
      reordered[outputIdx++] = original[idx];
    }
  }
}
}   // namespace AmvpCandidateSelector

#endif   // AMVP_CANDIDATE_SELECTOR_H
