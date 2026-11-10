// Deterministic motion-only clustering for AMVP trace diagnostics.
#ifndef AMVP_CANDIDATE_CLUSTERING_H
#define AMVP_CANDIDATE_CLUSTERING_H

#include "Mv.h"

#include <algorithm>
#include <cstdint>
#include <limits>

namespace AmvpTraceClustering
{
struct Result
{
  int numClusters = 0;
  int numUnique = 0;
  int cluster[AMVP_ARMC_MAX_NUM_CANDS] = {};
  int unique[AMVP_ARMC_MAX_NUM_CANDS] = {};
};

// All input slots participate, including zero padding. Exact MV duplicates
// share one stable unique ID; no AMVR conversion or pixel access is performed.
// thresholdInternal is an L-infinity diameter in internal MV units (normally
// 1/16 pel). Complete-link merging prevents a chain of nearby points from
// making a cluster whose end points are farther apart than the threshold.
// Equal merge distances are resolved by the earliest original pool-slot pair.
// Final cluster IDs are ordered by each cluster's earliest original pool slot.
inline Result clusterCandidates(const Mv *candidates, const int numCandidates, const int thresholdInternal)
{
  CHECK(!candidates, "Null AMVP clustering candidate pool");
  CHECK(numCandidates < 1 || numCandidates > AMVP_ARMC_MAX_NUM_CANDS, "Invalid AMVP clustering pool size");
  CHECK(thresholdInternal < 0, "Negative AMVP clustering threshold");

  Result result;
  Mv uniqueMv[AMVP_ARMC_MAX_NUM_CANDS];
  for (int slot = 0; slot < numCandidates; slot++)
  {
    int unique = 0;
    while (unique < result.numUnique && uniqueMv[unique] != candidates[slot])
    {
      unique++;
    }
    if (unique == result.numUnique)
    {
      uniqueMv[result.numUnique++] = candidates[slot];
    }
    result.unique[slot] = unique;
  }

  int64_t distance[AMVP_ARMC_MAX_NUM_CANDS][AMVP_ARMC_MAX_NUM_CANDS] = {};
  unsigned members[AMVP_ARMC_MAX_NUM_CANDS] = {};
  for (int i = 0; i < result.numUnique; i++)
  {
    members[i] = 1U << i;
    for (int j = i + 1; j < result.numUnique; j++)
    {
      // Widen before subtracting, including for extreme signed int inputs.
      const int64_t dx = int64_t(uniqueMv[i].getHor()) - uniqueMv[j].getHor();
      const int64_t dy = int64_t(uniqueMv[i].getVer()) - uniqueMv[j].getVer();
      const int64_t absX = dx < 0 ? -dx : dx;
      const int64_t absY = dy < 0 ? -dy : dy;
      distance[i][j] = distance[j][i] = std::max(absX, absY);
    }
  }

  for (;;)
  {
    int bestFirst = -1;
    int bestSecond = -1;
    int64_t bestDistance = std::numeric_limits<int64_t>::max();
    for (int i = 0; i < result.numUnique; i++)
    {
      if (!members[i])
      {
        continue;
      }
      for (int j = i + 1; j < result.numUnique; j++)
      {
        if (!members[j])
        {
          continue;
        }
        int64_t completeDistance = 0;
        for (int a = 0; a < result.numUnique; a++)
        {
          if (!(members[i] & (1U << a)))
          {
            continue;
          }
          for (int b = 0; b < result.numUnique; b++)
          {
            if (members[j] & (1U << b))
            {
              completeDistance = std::max(completeDistance, distance[a][b]);
            }
          }
        }
        // i/j remain ordered by the earliest member after every merge.
        // Strict improvement therefore gives stable lexicographic ties.
        if (completeDistance <= thresholdInternal && completeDistance < bestDistance)
        {
          bestDistance = completeDistance;
          bestFirst = i;
          bestSecond = j;
        }
      }
    }
    if (bestFirst < 0)
    {
      break;
    }
    members[bestFirst] |= members[bestSecond];
    members[bestSecond] = 0;
  }

  int uniqueCluster[AMVP_ARMC_MAX_NUM_CANDS] = {};
  for (int i = 0; i < result.numUnique; i++)
  {
    if (!members[i])
    {
      continue;
    }
    for (int unique = 0; unique < result.numUnique; unique++)
    {
      if (members[i] & (1U << unique))
      {
        uniqueCluster[unique] = result.numClusters;
      }
    }
    result.numClusters++;
  }
  for (int slot = 0; slot < numCandidates; slot++)
  {
    result.cluster[slot] = uniqueCluster[result.unique[slot]];
  }
  return result;
}
}   // namespace AmvpTraceClustering

#endif   // AMVP_CANDIDATE_CLUSTERING_H
