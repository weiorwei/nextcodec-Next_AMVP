/*
 * Encoder-only, observational AMVP candidate clustering diagnostics.
 * No candidate construction, pixel access, or encoder-state updates occur here.
 * The caller holds the existing AMVP stdout mutex for the entire record group.
 */
#ifndef AMVP_CLUSTER_TRACE_H
#define AMVP_CLUSTER_TRACE_H

#include "CommonLib/AmvpCandidateClustering.h"
#include "CommonLib/AmvpMode.h"
#include "CommonLib/CodingStructure.h"
#include "CommonLib/RdCost.h"
#include "CommonLib/Slice.h"
#include "CommonLib/UnitTools.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <limits>

namespace AmvpClusterTrace
{
inline const char *yesNo(const bool value) { return value ? "yes" : "no"; }

// Provenance is a set, not a single-source attribution.  The same MV can be
// independently derivable from spatial, temporal and historical information.
inline unsigned sourceMask(const PU::AmvpTraceSource source)
{
  if (source <= PU::AmvpTraceSource::SPATIAL_ABOVE_LEFT) { return 1; }
  if (source <= PU::AmvpTraceSource::TEMPORAL_C1) { return 2; }
  return source == PU::AmvpTraceSource::HISTORY ? 4 : 0;
}

inline const char *sourceNames(const unsigned mask, const bool derived)
{
  static const char *const names[] = {
    "NONE", "SPATIAL", "TEMPORAL", "SPATIAL|TEMPORAL", "HISTORY",
    "SPATIAL|HISTORY", "TEMPORAL|HISTORY", "SPATIAL|TEMPORAL|HISTORY"
  };
  return mask ? names[mask & 7] : derived ? "STANDARD" : "PADDING";
}

inline int64_t absolute(const int64_t value) { return value < 0 ? -value : value; }
inline int64_t l1(const Mv &a, const Mv &b)
{
  return absolute(int64_t(a.getHor()) - b.getHor()) + absolute(int64_t(a.getVer()) - b.getVer());
}
inline int64_t linf(const Mv &a, const Mv &b)
{
  return std::max(absolute(int64_t(a.getHor()) - b.getHor()), absolute(int64_t(a.getVer()) - b.getVer()));
}

inline bool sameNeighbour(const PU::AmvpTraceCandidate &a, const PU::AmvpTraceCandidate &b)
{
  return a.neighbourX == b.neighbourX && a.neighbourY == b.neighbourY &&
         a.neighbourW == b.neighbourW && a.neighbourH == b.neighbourH;
}

inline int spatialSupport(const PU::AmvpTraceSnapshot &snapshot, const Mv *matchingMv = nullptr)
{
  int count = 0;
  for (int i = 0; i < snapshot.numCandidates; ++i)
  {
    const auto &candidate = snapshot.candidates[i];
    if (sourceMask(candidate.source) != 1 || candidate.neighbourX < 0 || candidate.neighbourY < 0 ||
        candidate.neighbourW <= 0 || candidate.neighbourH <= 0 ||
        (matchingMv && candidate.mv != *matchingMv))
    {
      continue;
    }
    bool duplicate = false;
    for (int j = 0; j < i; ++j)
    {
      const auto &previous = snapshot.candidates[j];
      duplicate |= sourceMask(previous.source) == 1 && sameNeighbour(candidate, previous) &&
                   (!matchingMv || previous.mv == *matchingMv);
    }
    count += !duplicate;
  }
  return count;
}

inline void printKey(const char *tag, const CodingUnit &cu, const unsigned ctuRsAddr,
                     const RefPicList refList, const int refIdx, const PU::AmvpFinalTraceSnapshot &snapshot)
{
  std::fprintf(stdout,
    "[%s] MODE=%s TRACE_ID=%llu LAYER=%d POC=%d CTU=%u CU=(%d,%d,%dx%d) REF=L%d[%d] IMV=%d ",
    tag, AmvpMode::name(snapshot.mode).c_str(), static_cast<unsigned long long>(snapshot.traceId), snapshot.layerId, snapshot.poc,
    ctuRsAddr, cu.lx(), cu.ly(), cu.lwidth(), cu.lheight(), int(refList), refIdx, int(cu.imv));
}

inline void print(const CodingUnit &cu, const unsigned ctuRsAddr, const RefPicList refList, const int refIdx,
                  const PU::AmvpFinalTraceSnapshot &snapshot)
{
  constexpr int poolSize = AMVP_ARMC_MAX_NUM_CANDS;
  constexpr int pelUnit = 1 << MV_FRACTIONAL_BITS_INTERNAL;
  constexpr double toPel = 1.0 / pelUnit;
  const auto &raw = snapshot.candidates;
  const auto clusters = AmvpTraceClustering::clusterCandidates(snapshot.expanded, poolSize, pelUnit);
  const int selectedIdx = snapshot.selectedPoolIdx >= 0 && snapshot.selectedPoolIdx < poolSize
                            ? snapshot.selectedPoolIdx : -1;
  const int selectedCluster = selectedIdx >= 0 ? clusters.cluster[selectedIdx] : -1;
  unsigned masks[poolSize] = {};
  int historyAge[poolSize];
  bool uniqueDerived[poolSize] = {};
  unsigned rateBits[poolSize];
  unsigned bestBits = std::numeric_limits<unsigned>::max();
  Mv codedFinal = snapshot.finalMv;
  codedFinal.changeTransPrecInternal2Amvr(cu.imv);

  for (int i = 0; i < poolSize; ++i)
  {
    historyAge[i] = -1;
    for (int j = 0; j < raw.numCandidates; ++j)
    {
      const auto &candidate = raw.candidates[j];
      if (candidate.mv != snapshot.expanded[i]) { continue; }
      masks[i] |= sourceMask(candidate.source);
      if (candidate.source == PU::AmvpTraceSource::HISTORY && candidate.historyAge >= 0 &&
          (historyAge[i] < 0 || candidate.historyAge < historyAge[i]))
      {
        historyAge[i] = candidate.historyAge;
      }
    }
    uniqueDerived[clusters.unique[i]] |= snapshot.derived[i];
    Mv codedCandidate = snapshot.expanded[i];
    codedCandidate.changeTransPrecInternal2Amvr(cu.imv);
    const Mv delta = codedFinal - codedCandidate;
    rateBits[i] = RdCost::xGetExpGolombNumberOfBits(delta.getHor()) +
                  RdCost::xGetExpGolombNumberOfBits(delta.getVer());
    bestBits = std::min(bestBits, rateBits[i]);
  }

  unsigned bestIdxMask = 0;
  unsigned bestClusterMask = 0;
  int derivedUnique = 0;
  for (int i = 0; i < clusters.numUnique; ++i) { derivedUnique += uniqueDerived[i]; }
  for (int i = 0; i < poolSize; ++i)
  {
    if (rateBits[i] == bestBits)
    {
      bestIdxMask |= 1u << i;
      bestClusterMask |= 1u << clusters.cluster[i];
    }
  }
  Mv codedSelected = snapshot.selectedMvp;
  codedSelected.changeTransPrecInternal2Amvr(cu.imv);
  const Mv selectedDelta = codedFinal - codedSelected;
  const unsigned actualBits = RdCost::xGetExpGolombNumberOfBits(selectedDelta.getHor()) +
                              RdCost::xGetExpGolombNumberOfBits(selectedDelta.getVer());
  const bool l1Zero = refList == RPL1 && cu.interDir == 3 && cu.cs->picHeader->m_mvdL1ZeroFlag;
  const bool constrained = cu.smvdMode != 0 || l1Zero;
  const bool signalled = !(refList == RPL1 && (cu.smvdMode == 1 || l1Zero));
  const char *labelKind = constrained ? "CONSTRAINED" :
                         snapshot.mode < 0 ? "NEGATIVE_MODE_ACTUAL" : "COUNTERFACTUAL";
  const unsigned selectedSources = selectedIdx >= 0 ? masks[selectedIdx] : 0;
  printKey("AMVP-CLUSTER-SET", cu, ctuRsAddr, refList, refIdx, snapshot);
  std::fprintf(stdout,
    "FOUND=yes ALGO=COMPLETE_LINK_LINF THRESH_PEL=1 POOL=%d UNIQUE=%d DERIVED_UNIQUE=%d CLUSTERS=%d "
    "SELECTED_POOL_IDX=%d SIGNALLED_MVP_IDX=%d SELECTED_CLUSTER=%d SELECTED_SOURCE_MASK=%u "
    "SELECTED_SOURCES=%s POOL_MATCH=%s ORACLE_MATCH=%s FORMAL_KNOWN=%s LABEL_KIND=%s IS_SMVD=%s MVD_L1_ZERO=%s "
    "MVD_SIGNALLED=%s ACTUAL_EST_MVD_BITS=%u MIN_EST_MVD_BITS=%u ACTUAL_IS_RATE_BEST=%s "
    "RATE_BEST_IDX_MASK=0x%02x RATE_BEST_CLUSTER_MASK=0x%02x "
    "K_0PEL=%d K_0_5PEL=%d K_2PEL=%d K_4PEL=%d\n",
    poolSize, clusters.numUnique, derivedUnique, clusters.numClusters,
    selectedIdx, snapshot.signalledMvpIdx, selectedCluster, selectedSources,
    selectedIdx < 0 ? "UNKNOWN" : sourceNames(selectedSources, snapshot.derived[selectedIdx]),
    yesNo(selectedIdx >= 0), snapshot.mode < 0 ? yesNo(snapshot.oracleMatch) : "NA",
    yesNo(snapshot.formalKnown), labelKind, yesNo(cu.smvdMode != 0),
    yesNo(l1Zero), yesNo(signalled), actualBits, bestBits, yesNo(actualBits == bestBits),
    bestIdxMask, bestClusterMask,
    AmvpTraceClustering::clusterCandidates(snapshot.expanded, poolSize, 0).numClusters,
    AmvpTraceClustering::clusterCandidates(snapshot.expanded, poolSize, pelUnit / 2).numClusters,
    AmvpTraceClustering::clusterCandidates(snapshot.expanded, poolSize, 2 * pelUnit).numClusters,
    AmvpTraceClustering::clusterCandidates(snapshot.expanded, poolSize, 4 * pelUnit).numClusters);

  for (int i = 0; i < poolSize; ++i)
  {
    const Mv &mv = snapshot.expanded[i];
    printKey("AMVP-POOL-CAND", cu, ctuRsAddr, refList, refIdx, snapshot);
    std::fprintf(stdout,
      "SLOT=%d MV_INT=(%d,%d) MV_PEL=(%.4f,%.4f) UNIQUE=%d CLUSTER=%d SOURCE_MASK=%u SOURCES=%s "
      "DERIVED=%s PADDING_ONLY=%s SELECTED=%s MATCH_SELECTED_MV=%s EST_MVD_BITS=%u RATE_BEST=%s "
      "HMVP_NEWEST_AGE=%d SPATIAL_CU_SUPPORT=%d\n",
      i, mv.getHor(), mv.getVer(), mv.getHor() * toPel, mv.getVer() * toPel,
      clusters.unique[i], clusters.cluster[i], masks[i], sourceNames(masks[i], snapshot.derived[i]),
      yesNo(snapshot.derived[i]), yesNo(!snapshot.derived[i] && !masks[i]), yesNo(i == selectedIdx),
      yesNo(mv == snapshot.selectedMvp), rateBits[i], yesNo(rateBits[i] == bestBits),
      historyAge[i], spatialSupport(raw, &mv));
  }

  int maxClusterUnique = 0;
  for (int group = 0; group < clusters.numClusters; ++group)
  {
    unsigned slotMask = 0;
    unsigned sources = 0;
    bool seenUnique[poolSize] = {};
    int groupUnique = 0;
    int groupDerivedUnique = 0;
    int64_t diameter = 0;
    for (int i = 0; i < poolSize; ++i)
    {
      if (clusters.cluster[i] != group) { continue; }
      slotMask |= 1u << i;
      sources |= masks[i];
      if (!seenUnique[clusters.unique[i]])
      {
        seenUnique[clusters.unique[i]] = true;
        ++groupUnique;
        groupDerivedUnique += uniqueDerived[clusters.unique[i]];
      }
      for (int j = 0; j < i; ++j)
      {
        if (clusters.cluster[j] == group)
        {
          diameter = std::max(diameter, linf(snapshot.expanded[i], snapshot.expanded[j]));
        }
      }
    }
    maxClusterUnique = std::max(maxClusterUnique, groupUnique);
    printKey("AMVP-CLUSTER", cu, ctuRsAddr, refList, refIdx, snapshot);
    std::fprintf(stdout,
      "CLUSTER=%d SLOT_MASK=0x%02x UNIQUE=%d DERIVED_UNIQUE=%d DIAM_LINF_PEL=%.4f "
      "SOURCE_MASK=%u SOURCES=%s SELECTED=%s RATE_BEST=%s\n",
      group, slotMask, groupUnique, groupDerivedUnique, diameter * toPel, sources,
      sourceNames(sources, groupDerivedUnique != 0), yesNo(group == selectedCluster),
      yesNo((bestClusterMask & (1u << group)) != 0));
  }

  // Features below contain only causal candidate/geometry/reference metadata.
  // Final MV, selected index, MVD rate and Oracle labels deliberately remain
  // in other record types so downstream training can separate labels/features.
  int sourceUnique[3] = {};
  int sourcePoolUnique[3] = {};
  int sourcePoolSlots[3] = {};
  int64_t sourceDiameter[3] = { -1, -1, -1 };
  int c0 = -1;
  int c1 = -1;
  int64_t stNearest = -1;
  for (int source = 0; source < 3; ++source)
  {
    const unsigned mask = 1u << source;
    for (int i = 0; i < raw.numCandidates; ++i)
    {
      if (!(sourceMask(raw.candidates[i].source) & mask)) { continue; }
      sourceDiameter[source] = std::max<int64_t>(sourceDiameter[source], 0);
      bool duplicate = false;
      for (int j = 0; j < i; ++j)
      {
        if (!(sourceMask(raw.candidates[j].source) & mask)) { continue; }
        duplicate |= raw.candidates[i].mv == raw.candidates[j].mv;
        sourceDiameter[source] = std::max(sourceDiameter[source], l1(raw.candidates[i].mv, raw.candidates[j].mv));
      }
      sourceUnique[source] += !duplicate;
    }
    bool seenUnique[poolSize] = {};
    for (int i = 0; i < poolSize; ++i)
    {
      if (!(masks[i] & mask)) { continue; }
      ++sourcePoolSlots[source];
      if (!seenUnique[clusters.unique[i]])
      {
        seenUnique[clusters.unique[i]] = true;
        ++sourcePoolUnique[source];
      }
    }
  }
  for (int i = 0; i < raw.numCandidates; ++i)
  {
    if (raw.candidates[i].source == PU::AmvpTraceSource::TEMPORAL_C0) { c0 = i; }
    if (raw.candidates[i].source == PU::AmvpTraceSource::TEMPORAL_C1) { c1 = i; }
    if (sourceMask(raw.candidates[i].source) != 1) { continue; }
    for (int j = 0; j < raw.numCandidates; ++j)
    {
      if (sourceMask(raw.candidates[j].source) != 2) { continue; }
      const int64_t distance = l1(raw.candidates[i].mv, raw.candidates[j].mv);
      if (stNearest < 0 || distance < stNearest) { stNearest = distance; }
    }
  }
  const double c0c1Distance = c0 >= 0 && c1 >= 0 ? l1(raw.candidates[c0].mv, raw.candidates[c1].mv) * toPel : -1.0;
  const char *sliceType = cu.slice->isIntra() ? "I" : cu.slice->isInterP() ? "P" : "B";
  printKey("AMVP-CLUSTER-FEATURE", cu, ctuRsAddr, refList, refIdx, snapshot);
  std::fprintf(stdout,
    "FEATURE_SCOPE=CANDIDATES_ONLY S_RAW_UNIQUE=%d T_RAW_UNIQUE=%d H_RAW_UNIQUE=%d "
    "S_POOL_UNIQUE=%d T_POOL_UNIQUE=%d H_POOL_UNIQUE=%d S_POOL_SLOTS=%d T_POOL_SLOTS=%d H_POOL_SLOTS=%d "
    "SPATIAL_CU_SUPPORT=%d HISTORY_SIZE=%d S_DIAM_L1_PEL=%.4f T_DIAM_L1_PEL=%.4f H_DIAM_L1_PEL=%.4f "
    "C0C1_L1_PEL=%.4f ST_NEAREST_L1_PEL=%.4f POOL01_SAME_CLUSTER=%s "
    "MAX_CLUSTER_UNIQUE_RATIO=%.6f CU_W=%d CU_H=%d REF_POC=%d REF_POC_DELTA=%d "
    "SLICE_TYPE=%s TLAYER=%u LONG_TERM=%s\n",
    sourceUnique[0], sourceUnique[1], sourceUnique[2], sourcePoolUnique[0], sourcePoolUnique[1], sourcePoolUnique[2],
    sourcePoolSlots[0], sourcePoolSlots[1], sourcePoolSlots[2], spatialSupport(raw), raw.historySize,
    sourceDiameter[0] < 0 ? -1.0 : sourceDiameter[0] * toPel,
    sourceDiameter[1] < 0 ? -1.0 : sourceDiameter[1] * toPel,
    sourceDiameter[2] < 0 ? -1.0 : sourceDiameter[2] * toPel, c0c1Distance,
    stNearest < 0 ? -1.0 : stNearest * toPel, yesNo(clusters.cluster[0] == clusters.cluster[1]),
    clusters.numUnique ? double(maxClusterUnique) / clusters.numUnique : 0.0,
    cu.lwidth(), cu.lheight(), cu.slice->getRefPOC(refList, refIdx),
    snapshot.poc - cu.slice->getRefPOC(refList, refIdx), sliceType, unsigned(cu.slice->m_uiTLayer),
    yesNo(cu.slice->m_isUsedAsLongTerm[refList][refIdx]));
}
} // namespace AmvpClusterTrace

#endif // AMVP_CLUSTER_TRACE_H
