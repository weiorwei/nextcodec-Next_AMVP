// Pixel-free, anchored TMR-Lite selection for affine AMVP. The input order is
// the rank prior: there is no ARMC, template access, or Full pair search here.
#ifndef AFFINE_AMVP_TMR_SELECTOR_H
#define AFFINE_AMVP_TMR_SELECTOR_H

#include "Mv.h"
#include "RdCost.h"

namespace AffineAmvpTmrSelector
{
static constexpr int MAX_NUM_CANDIDATES = 8;

struct Candidate
{
  Mv mv[3];   // LT, RT, LB; LB is not a coded control point in a 4-parameter model.
};

inline bool sameMotion(const Candidate &a, const Candidate &b, const int affineMvCount)
{
  for (int controlPoint = 0; controlPoint < affineMvCount; controlPoint++)
  {
    if (a.mv[controlPoint] != b.mv[controlPoint])
    {
      return false;
    }
  }
  return true;
}

// Mirror InterSearch::xCalcAffineMVBits, including the order of operations.
// CP1/CP2 predict their differential motion relative to CP0; treating all
// control points as independent translational MVDs would overcharge a common
// translation. Form the adjusted predictor in INTERNAL precision, then round
// the hypothesis and predictor separately to affine AMVR code coordinates.
inline uint32_t estimateBits(const Candidate &hypothesis, const Candidate &predictor,
                             const int affineMvCount, const int imv)
{
  CHECK(affineMvCount != 2 && affineMvCount != 3, "Invalid affine control-point count");
  CHECK(imv < 0 || imv > 2, "Invalid affine AMVR precision");

  uint32_t bits = 0;
  for (int controlPoint = 0; controlPoint < affineMvCount; controlPoint++)
  {
    Mv pred = controlPoint == 0
      ? predictor.mv[controlPoint]
      : predictor.mv[controlPoint] + hypothesis.mv[0] - predictor.mv[0];
    pred.changeAffinePrecInternal2Amvr(imv);
    Mv mv = hypothesis.mv[controlPoint];
    mv.changeAffinePrecInternal2Amvr(imv);
    const Mv delta = mv - pred;
    bits += RdCost::xGetExpGolombNumberOfBits(delta.getHor())
            + RdCost::xGetExpGolombNumberOfBits(delta.getVer());
  }
  return bits;
}

// Stable deduplication uses the active INTERNAL control points, before AMVR
// conversion. The original slot 0 is always the first centre; only the second
// centre is optimized. Repeated padding has one vote, including one zero-MV
// hypothesis. Weights follow unique input rank, exactly as in TMR-Lite.
// The complete input is returned as a permutation, so callers may keep top 2
// without losing diagnostics. Optional indices identify original input slots.
inline void reorder(const Candidate *candidates, const int numCandidates,
                    const int affineMvCount, const int imv, Candidate *reordered,
                    int *outputIndices = nullptr)
{
  CHECK(numCandidates <= 0 || numCandidates > MAX_NUM_CANDIDATES, "Invalid affine TMR candidate count");
  CHECK(affineMvCount != 2 && affineMvCount != 3, "Invalid affine control-point count");
  CHECK(imv < 0 || imv > 2, "Invalid affine AMVR precision");

  // Preserve input before writing, including when input/output buffers alias.
  Candidate ranked[MAX_NUM_CANDIDATES];
  int uniqueRankIdx[MAX_NUM_CANDIDATES];
  int numUnique = 0;
  for (int rankIdx = 0; rankIdx < numCandidates; rankIdx++)
  {
    ranked[rankIdx] = candidates[rankIdx];
    bool duplicate = false;
    for (int uniqueIdx = 0; uniqueIdx < numUnique; uniqueIdx++)
    {
      duplicate |= sameMotion(ranked[rankIdx], ranked[uniqueRankIdx[uniqueIdx]], affineMvCount);
    }
    if (!duplicate)
    {
      uniqueRankIdx[numUnique++] = rankIdx;
    }
  }

  int secondRankIdx = numCandidates > 1 ? 1 : 0;
  if (numUnique >= 2)
  {
    static constexpr uint32_t rankWeights[MAX_NUM_CANDIDATES] = { 64, 32, 16, 8, 4, 2, 1, 1 };
    uint32_t rate[MAX_NUM_CANDIDATES][MAX_NUM_CANDIDATES];
    for (int hypothesisIdx = 0; hypothesisIdx < numUnique; hypothesisIdx++)
    {
      for (int predictorIdx = 0; predictorIdx < numUnique; predictorIdx++)
      {
        rate[hypothesisIdx][predictorIdx] =
          estimateBits(ranked[uniqueRankIdx[hypothesisIdx]], ranked[uniqueRankIdx[predictorIdx]],
                       affineMvCount, imv);
      }
    }

    uint64_t bestCoverageCost = std::numeric_limits<uint64_t>::max();
    for (int secondUniqueIdx = 1; secondUniqueIdx < numUnique; secondUniqueIdx++)
    {
      uint64_t coverageCost = 0;
      for (int hypothesisIdx = 0; hypothesisIdx < numUnique; hypothesisIdx++)
      {
        coverageCost += uint64_t(rankWeights[hypothesisIdx])
                        * std::min(rate[hypothesisIdx][0], rate[hypothesisIdx][secondUniqueIdx]);
      }
      // Strict comparison keeps the earliest input-rank candidate on ties.
      if (coverageCost < bestCoverageCost)
      {
        bestCoverageCost = coverageCost;
        secondRankIdx = uniqueRankIdx[secondUniqueIdx];
      }
    }
  }

  int outputIdx = 0;
  auto append = [&](const int rankIdx) {
    reordered[outputIdx] = ranked[rankIdx];
    if (outputIndices)
    {
      outputIndices[outputIdx] = rankIdx;
    }
    outputIdx++;
  };
  append(0);
  if (numCandidates > 1)
  {
    append(secondRankIdx);
  }
  for (int rankIdx = 1; rankIdx < numCandidates; rankIdx++)
  {
    if (rankIdx != secondRankIdx)
    {
      append(rankIdx);
    }
  }
}
}   // namespace AffineAmvpTmrSelector

#endif   // AFFINE_AMVP_TMR_SELECTOR_H
