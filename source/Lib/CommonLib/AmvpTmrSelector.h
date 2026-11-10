// Pure rank-weighted MVD-rate coverage selector shared by TMR and TMR without
// ARMC. The caller supplies the rank: no pictures, templates, or final MV are
// accessed here.
#ifndef AMVP_TMR_SELECTOR_H
#define AMVP_TMR_SELECTOR_H

#include "Mv.h"
#include "RdCost.h"

namespace AmvpTmrSelector
{
// Stable internal-MV deduplication intentionally precedes AMVR conversion,
// matching the original TMR implementation. Distinct internal MVs that round
// to the same AMVR code coordinate therefore remain separate hypotheses.
// Synthetic zero padding is not filtered: repeated zero has only one vote,
// but its first occurrence is a selectable hypothesis, as in original TMR.
inline void reorder(const Mv *candidates, const int numCandidates, const int imv,
                    const bool fullPairSearch, Mv *reordered,
                    const Distortion *rankedCosts = nullptr, Distortion *outputCosts = nullptr)
{
  CHECK(numCandidates <= 0 || numCandidates > AMVP_ARMC_MAX_NUM_CANDS, "Invalid TMR candidate count");
  CHECK(imv < 0 || imv > 3, "Invalid translational AMVR precision");

  // Keep an input copy so candidate/cost output is safe when aliased with input.
  Mv ranked[AMVP_ARMC_MAX_NUM_CANDS];
  Distortion costs[AMVP_ARMC_MAX_NUM_CANDS];
  for (int idx = 0; idx < numCandidates; idx++)
  {
    ranked[idx] = candidates[idx];
    costs[idx] = rankedCosts ? rankedCosts[idx] : 0;
  }

  int uniqueRankIdx[AMVP_ARMC_MAX_NUM_CANDS];
  int numUnique = 0;
  for (int rankIdx = 0; rankIdx < numCandidates; rankIdx++)
  {
    bool duplicate = false;
    for (int uniqueIdx = 0; uniqueIdx < numUnique; uniqueIdx++)
    {
      duplicate |= ranked[rankIdx] == ranked[uniqueRankIdx[uniqueIdx]];
    }
    if (!duplicate)
    {
      uniqueRankIdx[numUnique++] = rankIdx;
    }
  }
  if (numUnique < 2)
  {
    for (int idx = 0; idx < numCandidates; idx++)
    {
      reordered[idx] = ranked[idx];
      if (outputCosts)
      {
        outputCosts[idx] = costs[idx];
      }
    }
    return;
  }

  Mv codedCandidates[AMVP_ARMC_MAX_NUM_CANDS];
  for (int uniqueIdx = 0; uniqueIdx < numUnique; uniqueIdx++)
  {
    codedCandidates[uniqueIdx] = ranked[uniqueRankIdx[uniqueIdx]];
    codedCandidates[uniqueIdx].changeTransPrecInternal2Amvr(imv);
  }

  static constexpr uint32_t liteRankWeights[AMVP_ARMC_MAX_NUM_CANDS] = { 64, 32, 16, 8, 4, 2, 1, 1 };
  // Lite's dominant rank-0 weight makes a joint Full search degenerate to
  // the anchored solution. Retain original Full's softer linear profile.
  static constexpr uint32_t fullRankWeights[AMVP_ARMC_MAX_NUM_CANDS] = { 8, 7, 6, 5, 4, 3, 2, 1 };
  const uint32_t *const rankWeights = fullPairSearch ? fullRankWeights : liteRankWeights;
  auto estimateMvdBits = [&](const int hypothesisIdx, const int predictorIdx) -> uint32_t {
    const Mv mvd = codedCandidates[hypothesisIdx] - codedCandidates[predictorIdx];
    return RdCost::xGetExpGolombNumberOfBits(mvd.getHor())
           + RdCost::xGetExpGolombNumberOfBits(mvd.getVer());
  };

  int bestFirstUniqueIdx = 0;
  int bestSecondUniqueIdx = 1;
  uint64_t bestCoverageCost = std::numeric_limits<uint64_t>::max();
  const int firstSearchEnd = fullPairSearch ? numUnique - 1 : 1;
  for (int firstUniqueIdx = 0; firstUniqueIdx < firstSearchEnd; firstUniqueIdx++)
  {
    for (int secondUniqueIdx = firstUniqueIdx + 1; secondUniqueIdx < numUnique; secondUniqueIdx++)
    {
      uint64_t coverageCost = 0;
      for (int hypothesisIdx = 0; hypothesisIdx < numUnique; hypothesisIdx++)
      {
        const uint32_t bitsFromFirst = estimateMvdBits(hypothesisIdx, firstUniqueIdx);
        const uint32_t bitsFromSecond = estimateMvdBits(hypothesisIdx, secondUniqueIdx);
        coverageCost += uint64_t(rankWeights[hypothesisIdx]) * std::min(bitsFromFirst, bitsFromSecond);
      }
      // Stable, lexicographically earliest pair in unique input-rank order.
      if (coverageCost < bestCoverageCost)
      {
        bestCoverageCost = coverageCost;
        bestFirstUniqueIdx = firstUniqueIdx;
        bestSecondUniqueIdx = secondUniqueIdx;
      }
    }
  }

  bool usedRankIdx[AMVP_ARMC_MAX_NUM_CANDS] = {};
  int outputIdx = 0;
  auto appendCandidate = [&](const int rankIdx) {
    reordered[outputIdx] = ranked[rankIdx];
    if (outputCosts)
    {
      outputCosts[outputIdx] = costs[rankIdx];
    }
    usedRankIdx[rankIdx] = true;
    outputIdx++;
  };
  appendCandidate(uniqueRankIdx[bestFirstUniqueIdx]);
  appendCandidate(uniqueRankIdx[bestSecondUniqueIdx]);
  for (int rankIdx = 0; rankIdx < numCandidates; rankIdx++)
  {
    if (!usedRankIdx[rankIdx])
    {
      appendCandidate(rankIdx);
    }
  }
}
}   // namespace AmvpTmrSelector

#endif   // AMVP_TMR_SELECTOR_H
