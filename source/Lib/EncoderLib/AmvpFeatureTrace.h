// Encoder-only AMVP observations. Freeze inputs before ME and carry immutable
// handles with winning CUs; by default print only the final coded CUs.
#ifndef AMVP_FEATURE_TRACE_H
#define AMVP_FEATURE_TRACE_H

#include "CommonLib/AmvpFeatureStats.h"
#include "CommonLib/CodingStructure.h"
#include "CommonLib/Picture.h"
#include "CommonLib/UnitTools.h"

#include <atomic>
#include <cstdio>
#include <memory>
#include <mutex>
#include <sstream>
#include <unordered_map>

namespace AmvpFeatureTrace
{
using namespace AmvpFeatureStats;

struct Snapshot
{
  Input input;
  Prepared prepared;
  uint64_t queryId = 0, callId = 0;
  int poc = 0, layer = 0, ctu = 0, x = 0, y = 0;
  int refIdx = 0, refPoc = 0, qp = 0, temporalLayer = 0, bcw = 0, lic = 0;
  int historySize = 0;
  unsigned indexBits[2] = { 1, 1 };
  const char *sourceOrigin = "SEARCHED";
};

inline uint64_t mix(const uint64_t value)
{
  uint64_t result = value + 0x9e3779b97f4a7c15ULL;
  result = (result ^ (result >> 30)) * 0xbf58476d1ce4e5b9ULL;
  result = (result ^ (result >> 27)) * 0x94d049bb133111ebULL;
  return result ^ (result >> 31);
}

// A complete CU is the sample unit: its two BI lists cannot be split. These
// fields are available before ME and remain identical for the final winner.
inline bool sampleCu(const CodingUnit &cu, const int period, const int seed)
{
  if (period <= 1) { return true; }
  uint64_t hash = mix(uint64_t(seed));
  for (const int value : { int(cu.cs->picture->m_layerId), cu.slice->m_poc,
                           cu.lx(), cu.ly(), int(cu.lwidth()), int(cu.lheight()) })
  {
    hash = mix(hash ^ uint64_t(int64_t(value)));
  }
  return hash % uint64_t(period) == 0;
}

inline auto &snapshots()
{
  // Only the current CTU's selected per-trial references are retained. IDs
  // are globally unique, so an expired/foreign-thread ID cannot alias a record.
  static thread_local std::unordered_map<uint64_t, std::unique_ptr<Snapshot>> records;
  return records;
}

inline void reset() { snapshots().clear(); }

inline uint64_t retain(std::unique_ptr<Snapshot> snapshot)
{
  if (!snapshot) { return 0; }
  static std::atomic<uint64_t> next { 0 };
  const uint64_t id = next.fetch_add(1, std::memory_order_relaxed) + 1;
  snapshots().emplace(id, std::move(snapshot));
  return id;
}

inline uint64_t nextCallId()
{
  static std::atomic<uint64_t> counter { 0 };
  return counter.fetch_add(1, std::memory_order_relaxed) + 1;
}

inline Vec toGrid(Mv mv, const int imv)
{
  // Round in the codec's signed rounding convention, then convert units.
  mv.roundTransPrecInternal2Amvr(imv);
  mv.changeTransPrecInternal2Amvr(imv);
  return { mv.getHor(), mv.getVer() };
}

inline std::unique_ptr<Snapshot> capture(CodingUnit &cu, const RefPicList targetList,
                                         const int refIdx, const AMVPInfo &standard,
                                         const uint64_t callId, const bool prepareNow = true)
{
  CHECK(refIdx < 0 || standard.numCand != AMVP_MAX_NUM_CANDS,
        "Feature observation requires the original two AMVP candidates");
  auto result = std::make_unique<Snapshot>();
  auto &out = *result;
  auto &input = out.input;
  const auto &slice = *cu.slice;
  static std::atomic<uint64_t> counter { 0 };
  out.queryId = counter.fetch_add(1, std::memory_order_relaxed) + 1;
  out.callId = callId;
  out.poc = slice.m_poc;
  out.layer = cu.cs->picture->m_layerId;
  out.ctu = int(CU::getCtuAddr(cu));
  out.x = cu.lx();
  out.y = cu.ly();
  out.refIdx = refIdx;
  out.refPoc = slice.getRefPOC(targetList, refIdx);
  out.qp = cu.qp; // trial metadata, never an input feature
  out.temporalLayer = int(slice.m_uiTLayer);
  out.bcw = cu.bcwIdx;
  out.lic = cu.licFlag;
  input.p0 = toGrid(standard.mvCand[0], cu.imv);
  input.b1 = toGrid(standard.mvCand[1], cu.imv);
  input.context.imv = cu.imv;
  input.context.width = cu.lwidth();
  input.context.height = cu.lheight();
  input.context.refPocDelta = slice.m_poc - out.refPoc;
  input.context.targetList = int(targetList);
  input.context.longTerm = slice.getRefPic(targetList, refIdx)->m_longTerm;
  input.context.bSlice = slice.isInterB();
  input.raw.reserve(15);

  const Position lt = cu.Y().topLeft(), rt = cu.Y().topRight(), lb = cu.Y().bottomLeft();
  const Position probes[5] = { lb.offset(-1, 1), lb.offset(-1, 0), rt.offset(1, -1),
                               rt.offset(0, -1), lt.offset(-1, -1) };
  // A spatial probe yields the first matching direction, exactly as
  // PU::addMVPCandUnscaled; retain the source list rather than discarding it.
  std::vector<const CodingUnit *> neighbours;
  for (int probe = 0; probe < 5; ++probe)
  {
    const auto *neighbour = cu.cs->getCURestricted(probes[probe], cu, cu.chType);
    if (!neighbour || !CU::isInter(*neighbour) || !neighbour->getMotionInfo(probes[probe]).isInter)
    {
      continue;
    }
    const auto &motion = neighbour->getMotionInfo(probes[probe]);
    for (int direction = 0; direction < 2; ++direction)
    {
      const auto sourceList = RefPicList(direction == 0 ? int(targetList) : 1 - int(targetList));
      const int sourceRef = motion.refIdx[sourceList];
      if (sourceRef < 0 || slice.getRefPOC(sourceList, sourceRef) != out.refPoc) { continue; }
      int unit = 0;
      while (unit < int(neighbours.size()) &&
             (neighbours[unit]->lx() != neighbour->lx() || neighbours[unit]->ly() != neighbour->ly() ||
              neighbours[unit]->lwidth() != neighbour->lwidth() ||
              neighbours[unit]->lheight() != neighbour->lheight())) { ++unit; }
      if (unit == int(neighbours.size())) { neighbours.push_back(neighbour); }
      Observation observation;
      observation.mv = toGrid(motion.mv[sourceList], cu.imv);
      observation.source = probe < 2 ? LEFT : ABOVE;
      observation.probeIndex = probe;
      observation.unit = unit;
      observation.sourceList = int(sourceList);
      observation.x = neighbour->lx();
      observation.y = neighbour->ly();
      observation.w = neighbour->lwidth();
      observation.h = neighbour->lheight();
      input.raw.push_back(observation);
      break;
    }
  }

  if (cu.cs->picHeader->m_enableTMVPFlag && cu.lwidth() + cu.lheight() > 12)
  {
    const auto &pcv = *cu.cs->pcv;
    const Position rb = cu.Y().bottomRight().offset(-3, -3);
    bool boundary = rb.x + pcv.minCUWidth < pcv.lumaWidth && rb.y + pcv.minCUHeight < pcv.lumaHeight;
    const auto &subPic = slice.m_pps->getSubPicFromPos(cu.lumaPos());
    if (subPic.m_treatedAsPicFlag)
    {
      boundary = rb.x + pcv.minCUWidth <= subPic.m_subPicRight &&
                 rb.y + pcv.minCUHeight <= subPic.m_subPicBottom;
    }
    const bool c0Available = boundary && ((rb.y & pcv.maxCUHeightMask) + 4 < pcv.maxCUHeight);
    Mv temporal;
    int temporalProbe = 0;
    bool temporalAvailable = c0Available &&
      PU::getColocatedMVP(cu, targetList, rb.offset(4, 4), temporal, refIdx, false);
    if (!temporalAvailable)
    {
      temporalProbe = 1;
      temporalAvailable = PU::getColocatedMVP(cu, targetList, cu.Y().center(), temporal, refIdx, false);
    }
    if (temporalAvailable)
    {
      Observation observation;
      observation.mv = toGrid(temporal, cu.imv);
      observation.source = TEMPORAL;
      observation.probeIndex = temporalProbe;
      input.raw.push_back(observation);
    }
  }

  const auto &history = cu.cs->motionLut.lut;
  out.historySize = int(history.size());
  const int allowed = std::min(MAX_NUM_HMVP_AVMPCANDS, int(history.size()));
  // Preserve the original AMVP LUT range and order (not newest-four order).
  for (int index = 0; index < allowed; ++index)
  {
    for (int direction = 0; direction < 2; ++direction)
    {
      const auto sourceList = RefPicList(direction == 0 ? int(targetList) : 1 - int(targetList));
      const int sourceRef = history[index].refIdx[sourceList];
      if (sourceRef < 0 || slice.getRefPOC(sourceList, sourceRef) != out.refPoc) { continue; }
      Observation observation;
      observation.mv = toGrid(history[index].mv[sourceList], cu.imv);
      observation.source = HISTORY;
      observation.unit = index;
      observation.sourceList = int(sourceList);
      observation.historyIndex = index;
      observation.historyAge = int(history.size()) - 1 - index;
      input.raw.push_back(observation);
    }
  }
  Observation zero;
  zero.source = ZERO;
  input.raw.push_back(zero);
  // Final-only output derives features later from exactly this frozen input;
  // never recompute spatial/history observations at the final output point.
  if (prepareNow) { out.prepared = prepare(input); }
  return result;
}

inline const char *sourceName(const int source)
{
  switch (source)
  {
  case LEFT: return "LEFT";
  case ABOVE: return "ABOVE";
  case TEMPORAL: return "TEMPORAL";
  case HISTORY: return "HISTORY";
  case ZERO: return "ZERO";
  default: return "INVALID";
  }
}

inline void vectorText(std::ostream &out, const Vec value) { out << '(' << value.x << ',' << value.y << ')'; }

template<typename Array> inline void featureText(std::ostream &out, const Array &values)
{
  out << '(';
  for (size_t i = 0; i < values.size(); ++i) { if (i) { out << ','; } out << values[i]; }
  out << ')';
}

inline void print(const Snapshot &snapshot, const Mv &finalMv, const Mv &actualMvp,
                  const int actualIdx, const unsigned idx0Bits, const unsigned idx1Bits,
                  const char *origin, const CodingUnit *finalCu = nullptr,
                  const int samplePeriod = 1, const int sampleSeed = 0)
{
  const auto &input = snapshot.input;
  const auto &context = input.context;
  const auto final = toGrid(finalMv, context.imv);
  const auto predictor = toGrid(actualMvp, context.imv);
  Prepared deferred;
  if (snapshot.prepared.candidates.empty()) { deferred = prepare(input); }
  const auto &prepared = snapshot.prepared.candidates.empty() ? deferred : snapshot.prepared;
  // Dense IDs in the OUTPUT domain keep streaming validators bounded even
  // when millions of rejected RDO trials never produce a final output row.
  static std::atomic<uint64_t> nextFinalOutput { 0 };
  const uint64_t queryId = finalCu ? nextFinalOutput.fetch_add(1, std::memory_order_relaxed) + 1 : snapshot.queryId;
  const bool l1Zero = finalCu && context.targetList == 1 && finalCu->interDir == 3 &&
    finalCu->cs->picHeader->m_mvdL1ZeroFlag;
  const bool constrained = finalCu && (finalCu->smvdMode != 0 || l1Zero);
  const int rate0 = rate(final, input.p0) + int(idx0Bits);
  const int baseline = std::min(rate0, rate(final, input.b1) + int(idx1Bits));
  int oracle = baseline;
  for (const auto &candidate : prepared.candidates)
  {
    oracle = std::min(oracle, rate(final, candidate.mv) + int(idx1Bits));
  }
  std::ostringstream out;
  out << "[AMVP-STATS-QUERY] VERSION=1 QUERY_ID=" << queryId << " CALL_ID=" << snapshot.callId
      << " MODE=0 STAGE=" << (finalCu ? "FINAL" : "UNI") << " MV_ORIGIN=" << origin
      << " SOURCE_STAGE=UNI SOURCE_QUERY_ID=" << snapshot.queryId
      << " SOURCE_MV_ORIGIN=" << snapshot.sourceOrigin
      << " FINAL_INTER_DIR=" << (finalCu ? int(finalCu->interDir) : 0)
      << " LABEL_KIND=" << (constrained ? "CONSTRAINED" : "ORDINARY")
      << " IS_SMVD=" << int(finalCu && finalCu->smvdMode != 0)
      << " MVD_L1_ZERO=" << int(l1Zero)
      << " MVD_SIGNALLED=" << int(!(finalCu && context.targetList == 1 && (finalCu->smvdMode == 1 || l1Zero)))
      << " OUTPUT_SAMPLE_PERIOD=" << samplePeriod << " OUTPUT_SAMPLE_SEED=" << sampleSeed << " SAMPLE_UNIT=CU"
      << " POC=" << snapshot.poc << " LAYER=" << snapshot.layer
      << " CTU=" << snapshot.ctu << " CU=(" << snapshot.x << ',' << snapshot.y << ',' << context.width << 'x'
      << context.height << ") REF=L" << context.targetList << '[' << snapshot.refIdx << "] IMV=" << context.imv
      << " BCW=" << (finalCu ? int(finalCu->bcwIdx) : snapshot.bcw)
      << " LIC=" << (finalCu ? int(finalCu->licFlag) : snapshot.lic)
      << " QP=" << (finalCu ? int(finalCu->qp) : snapshot.qp)
      << " CAPTURE_BCW=" << snapshot.bcw << " CAPTURE_LIC=" << snapshot.lic << " CAPTURE_QP=" << snapshot.qp
      << " SLICE_TYPE=" << (context.bSlice ? 'B' : 'P') << " TLAYER=" << snapshot.temporalLayer
      << " REF_POC=" << snapshot.refPoc << " REF_POC_DELTA=" << context.refPocDelta
      << " LONG_TERM=" << int(context.longTerm) << " HISTORY_SIZE=" << snapshot.historySize << " P0=";
  vectorText(out, input.p0);
  out << " B1="; vectorText(out, input.b1);
  out << " FINAL_MV="; vectorText(out, final);
  out << " ACTUAL_MVP="; vectorText(out, predictor);
  out << " ACTUAL_IDX=" << actualIdx << " IDX0_BITS=" << idx0Bits << " IDX1_BITS=" << idx1Bits
      << " RAW_COUNT=" << input.raw.size() << " CAND_COUNT=" << prepared.candidates.size()
      << " JB_EST=" << baseline << " ACTUAL_EST="
      << rate(final, predictor) + int(actualIdx == 0 ? idx0Bits : idx1Bits)
      << " ORACLE_EST=" << oracle << '\n';
  for (size_t index = 0; index < input.raw.size(); ++index)
  {
    const auto &observation = input.raw[index];
    out << "[AMVP-STATS-RAW] QUERY_ID=" << queryId << " RID=" << index
        << " SOURCE=" << sourceName(observation.source) << " UNIT=" << observation.unit
        << " PROBE_INDEX=" << observation.probeIndex
        << " SOURCE_LIST=" << observation.sourceList << " HISTORY_INDEX=" << observation.historyIndex
        << " HISTORY_AGE=" << observation.historyAge << " MV=";
    vectorText(out, observation.mv);
    out << " NEIGHBOR=(" << observation.x << ',' << observation.y << ',' << observation.w << 'x'
        << observation.h << ")\n";
  }
  for (size_t index = 0; index < prepared.candidates.size(); ++index)
  {
    const auto &candidate = prepared.candidates[index];
    const int cost = std::min(rate0, rate(final, candidate.mv) + int(idx1Bits));
    out << "[AMVP-STATS-CAND] QUERY_ID=" << queryId << " CID=" << index << " MV=";
    vectorText(out, candidate.mv);
    out << " SOURCE_MASK=" << candidate.sourceMask << " H_LIST_MASK=" << candidate.historyListMask
        << " H_SAME_COUNT=" << candidate.historySameCount << " H_OTHER_COUNT=" << candidate.historyOtherCount
        << " H_SAME_AGE=" << candidate.historySameAge << " H_OTHER_AGE=" << candidate.historyOtherAge
        << " H_SAME_SUPPORT=" << candidate.historySameSupport << " H_OTHER_SUPPORT=" << candidate.historyOtherSupport
        << " F="; featureText(out, candidate.features);
    out << " RAW_F="; featureText(out, candidate.rawFeatures);
    out << " JB_EST=" << baseline << " JC_EST=" << cost << " GAIN_EST=" << baseline - cost << '\n';
  }
  out << "[AMVP-STATS-END] QUERY_ID=" << queryId << " RAW_COUNT=" << input.raw.size()
      << " CAND_COUNT=" << prepared.candidates.size() << '\n';

  // One stdio write keeps each complete query intact alongside existing trace
  // lines, including threaded encoder runs. Only trace-owned state is changed.
  static std::mutex mutex;
  static bool schemaPrinted = false;
  std::lock_guard<std::mutex> lock(mutex);
  std::string block;
  if (!schemaPrinted)
  {
    block = std::string("[AMVP-STATS-SCHEMA] VERSION=1 FEATURES=32 UNIT=AMVR_GRID GRID_STEPS_INT=(4,16,64,8) ") +
            "SOURCE_BITS=(LEFT:1,ABOVE:2,TEMPORAL:4,HISTORY:8,ZERO:16) QUANT=SIGNED_LOG_V1 "
            "COVERAGE_GAIN_UNIT=1/4-bit LABEL_UNIT=bit LABEL=FIXED_MV_EG STAGE=" + (finalCu ? "FINAL" : "UNI") +
            " HMVP_RANGE=FIRST4 "
            "POC_CLIP=32767 ROUND=NEAREST_TIES_AWAY_FROM_ZERO\n";
    schemaPrinted = true;
  }
  block += out.str();
  const size_t written = std::fwrite(block.data(), 1, block.size(), stdout);
  CHECK(written != block.size(), "Could not write AMVP feature statistics");
}

inline void printFinal(const CodingUnit &cu, const RefPicList refList,
                       const int samplePeriod, const int sampleSeed)
{
  const auto found = snapshots().find(cu.amvpFeatureId[refList]);
  const char *reason = nullptr;
  const Snapshot *snapshot = found == snapshots().end() ? nullptr : found->second.get();
  if (!snapshot) { reason = "PRE_ME_SNAPSHOT_MISSING_OR_EXPIRED"; }
  else
  {
    const auto &c = snapshot->input.context;
    if (snapshot->poc != cu.slice->m_poc || snapshot->layer != cu.cs->picture->m_layerId ||
        snapshot->ctu != int(CU::getCtuAddr(cu)) || snapshot->x != cu.lx() || snapshot->y != cu.ly() ||
        c.width != int(cu.lwidth()) || c.height != int(cu.lheight()) || c.imv != cu.imv ||
        c.targetList != int(refList) || snapshot->refIdx != cu.refIdx[refList])
    {
      reason = "PRE_ME_CONTEXT_MISMATCH";
    }
    else if (cu.mvpIdx[refList] > 1 ||
             toGrid(cu.mv[refList] - cu.mvd[refList], cu.imv) !=
               (cu.mvpIdx[refList] == 0 ? snapshot->input.p0 : snapshot->input.b1))
    {
      reason = "FINAL_PREDICTOR_MISMATCH";
    }
  }
  if (reason)
  {
    std::fprintf(stdout, "[AMVP-STATS-SKIP] VERSION=1 STAGE=FINAL POC=%d LAYER=%d CTU=%u "
                 "CU=(%d,%d,%dx%d) REF=L%d[%d] IMV=%d REASON=%s\n",
                 cu.slice->m_poc, cu.cs->picture->m_layerId, CU::getCtuAddr(cu), cu.lx(), cu.ly(),
                 cu.lwidth(), cu.lheight(), int(refList), cu.refIdx[refList], int(cu.imv), reason);
    return;
  }
  print(*snapshot, cu.mv[refList], cu.mv[refList] - cu.mvd[refList], cu.mvpIdx[refList],
        snapshot->indexBits[0], snapshot->indexBits[1], "FINAL_CODED", &cu, samplePeriod, sampleSeed);
}
} // namespace AmvpFeatureTrace
#endif // AMVP_FEATURE_TRACE_H
