// Pixel-free, integer-only AMVP mode-8 rule selection shared by both codecs.
#ifndef AMVP_DECISION_TREE_H
#define AMVP_DECISION_TREE_H

#include "Mv.h"
#include "RdCost.h"
#include "AmvpDecisionTreeModel.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>

namespace AmvpDecisionTree
{
constexpr int numFeatures = 12;
constexpr int numProfiles = 5;
using Features = std::array<int64_t, numFeatures>;

// spatialCuSupport is already aggregated over all independent neighbouring
// CUs with this AMVR-coded MV, not a count of spatial probe positions.
struct CandidateMetadata
{
  bool     derived = false;
  unsigned sourceMask = 0; // spatial=1, temporal=2, history=4; may overlap
  int      spatialCuSupport = 0;
  int      historyAge = -1; // newest matching HMVP entry has age zero
};

struct Context
{
  int imv;
  int width;
  int height;
  int refPocDelta;
};

struct PreparedPool
{
  int numUnique = 0;
  int slot[AMVP_ARMC_MAX_NUM_CANDS] = {};
  Mv coded[AMVP_ARMC_MAX_NUM_CANDS];
  Mv internal[AMVP_ARMC_MAX_NUM_CANDS];
  CandidateMetadata metadata[AMVP_ARMC_MAX_NUM_CANDS];
};

struct Pair
{
  int first = 0;
  int second = 1;
};

inline int64_t absolute(const int64_t value) { return value < 0 ? -value : value; }
inline int64_t l1(const Mv &a, const Mv &b)
{
  return absolute(int64_t(a.getHor()) - b.getHor()) + absolute(int64_t(a.getVer()) - b.getVer());
}

inline PreparedPool preparePool(const Mv *candidates, const CandidateMetadata *metadata,
                                const int numCandidates, const int imv)
{
  CHECK(!candidates || !metadata, "Missing decision-tree AMVP inputs");
  CHECK(numCandidates < AMVP_MAX_NUM_CANDS || numCandidates > AMVP_ARMC_MAX_NUM_CANDS,
        "Invalid decision-tree AMVP pool size");
  CHECK(imv < 0 || imv > 3, "Invalid translational AMVR precision");
  PreparedPool pool;
  for (int i = 0; i < numCandidates; ++i)
  {
    if (!metadata[i].derived) { continue; }
    Mv coded = candidates[i];
    coded.changeTransPrecInternal2Amvr(imv);
    int unique = 0;
    while (unique < pool.numUnique && pool.coded[unique] != coded) { ++unique; }
    if (unique == pool.numUnique)
    {
      pool.slot[unique] = i;
      pool.coded[unique] = coded;
      pool.internal[unique] = coded;
      pool.internal[unique].changeTransPrecAmvr2Internal(imv);
      pool.metadata[unique] = metadata[i];
      ++pool.numUnique;
    }
    else
    {
      auto &combined = pool.metadata[unique];
      combined.sourceMask |= metadata[i].sourceMask;
      // The caller aggregates support by coded MV before this deduplication,
      // so equal coded MVs carry the same independent-CU support set.
      combined.spatialCuSupport = std::max(combined.spatialCuSupport, metadata[i].spatialCuSupport);
      if (metadata[i].historyAge >= 0 &&
          (combined.historyAge < 0 || metadata[i].historyAge < combined.historyAge))
      {
        combined.historyAge = metadata[i].historyAge;
      }
    }
  }
  return pool;
}

// Feature order is a trained-model ABI. Distances use internal MV units
// (1/16 pel), independent of IMV; unavailable spatial distances are -1.
inline Features extractFeatures(const PreparedPool &pool, const Context &context)
{
  CHECK(context.width <= 0 || context.height <= 0, "Invalid decision-tree CU dimensions");
  Features features = { context.imv, floorLog2(context.width), floorLog2(context.height), pool.numUnique,
                        0, 0, 0, -1, -1, 0, 0, absolute(int64_t(context.refPocDelta)) };
  int64_t diameter = -1;
  int64_t nearest = std::numeric_limits<int64_t>::max();
  for (int i = 0; i < pool.numUnique; ++i)
  {
    const auto &metadata = pool.metadata[i];
    features[4] += (metadata.sourceMask & 1) != 0;
    features[5] += (metadata.sourceMask & 2) != 0;
    features[6] += (metadata.sourceMask & 4) != 0;
    features[9] = std::max(features[9], int64_t(metadata.spatialCuSupport));
    features[10] |= metadata.historyAge == 0;
    if (metadata.sourceMask & 1)
    {
      diameter = std::max(diameter, int64_t(0));
      for (int j = 0; j < pool.numUnique; ++j)
      {
        const int64_t distance = l1(pool.internal[i], pool.internal[j]);
        if (pool.metadata[j].sourceMask & 1) { diameter = std::max(diameter, distance); }
        if (pool.metadata[j].sourceMask & 2) { nearest = std::min(nearest, distance); }
      }
    }
  }
  features[7] = diameter;
  features[8] = nearest == std::numeric_limits<int64_t>::max() ? -1 : nearest;
  return features;
}

inline int profileWeight(const CandidateMetadata &metadata, const int profile)
{
  CHECK(profile < 0 || profile >= numProfiles, "Invalid AMVP weight profile");
  switch (profile)
  {
  case 1: return metadata.spatialCuSupport >= 2 ? 4 : 1;
  case 2:
  {
    const unsigned mask = metadata.sourceMask & 7;
    return mask && (mask & (mask - 1)) ? 4 : 1;
  }
  case 3: return metadata.historyAge == 0 ? 2 : 1;
  case 4: return metadata.sourceMask & 2 ? 4 : metadata.sourceMask & 1 ? 2 : 1;
  default: return 1;
  }
}

// Strict comparison and original slot order give the same deterministic
// tie handling as mode 7. The returned centres are original pool indices.
inline Pair selectProfile(const PreparedPool &pool, const int profile)
{
  Pair pair;
  if (pool.numUnique < AMVP_MAX_NUM_CANDS) { return pair; }
  uint32_t bits[AMVP_ARMC_MAX_NUM_CANDS][AMVP_ARMC_MAX_NUM_CANDS];
  int weights[AMVP_ARMC_MAX_NUM_CANDS];
  for (int k = 0; k < pool.numUnique; ++k)
  {
    weights[k] = profileWeight(pool.metadata[k], profile);
    for (int i = 0; i < pool.numUnique; ++i)
    {
      const Mv delta = pool.coded[k] - pool.coded[i];
      bits[k][i] = RdCost::xGetExpGolombNumberOfBits(delta.getHor())
                   + RdCost::xGetExpGolombNumberOfBits(delta.getVer());
    }
  }
  uint64_t bestCost = std::numeric_limits<uint64_t>::max();
  for (int i = 0; i < pool.numUnique - 1; ++i)
  {
    for (int j = i + 1; j < pool.numUnique; ++j)
    {
      uint64_t cost = 0;
      for (int k = 0; k < pool.numUnique; ++k)
      {
        cost += uint64_t(weights[k]) * std::min(bits[k][i], bits[k][j]);
      }
      if (cost < bestCost)
      {
        bestCost = cost;
        pair.first = pool.slot[i];
        pair.second = pool.slot[j];
      }
    }
  }
  return pair;
}

inline int predictProfile(const Features &features)
{
  int index = 0;
  for (int visited = 0; visited < AmvpDecisionTreeModel::nodeCount; ++visited)
  {
    CHECK(index < 0 || index >= AmvpDecisionTreeModel::nodeCount, "Invalid AMVP tree node index");
    const auto &node = AmvpDecisionTreeModel::nodes[index];
    if (node.feature < 0)
    {
      CHECK(node.profile < 0 || node.profile >= numProfiles, "Invalid AMVP tree leaf profile");
      return node.profile;
    }
    CHECK(node.feature >= numFeatures, "Invalid AMVP tree feature index");
    index = features[node.feature] <= node.threshold ? node.left : node.right;
  }
  THROW("AMVP decision tree contains a cycle");
}

inline void reorder(const Mv *candidates, const CandidateMetadata *metadata, const int numCandidates,
                     const Context &context, Mv *reordered)
{
  CHECK(!reordered, "Missing AMVP decision-tree output");
  const PreparedPool pool = preparePool(candidates, metadata, numCandidates, context.imv);
  Mv original[AMVP_ARMC_MAX_NUM_CANDS];
  for (int i = 0; i < numCandidates; ++i) { original[i] = candidates[i]; }
  const Pair pair = selectProfile(pool, predictProfile(extractFeatures(pool, context)));
  reordered[0] = original[pair.first];
  reordered[1] = original[pair.second];
  int output = AMVP_MAX_NUM_CANDS;
  for (int i = 0; i < numCandidates; ++i)
  {
    if (i != pair.first && i != pair.second) { reordered[output++] = original[i]; }
  }
}
} // namespace AmvpDecisionTree

#endif // AMVP_DECISION_TREE_H
