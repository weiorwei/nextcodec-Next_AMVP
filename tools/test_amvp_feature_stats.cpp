// Standalone C++17 tests for the observational AMVP feature contract.
#include "../source/Lib/CommonLib/AmvpFeatureStats.h"

#include <cmath>
#include <iostream>
#include <map>
#include <random>
#include <set>
#include <string>
#include <utility>

using namespace AmvpFeatureStats;

namespace
{
int checks = 0;
void require(bool ok, const std::string &message)
{
  ++checks;
  if (!ok) { throw std::runtime_error(message); }
}

Observation observation(Vec mv, int source, int unit = -1, int list = -1, int age = -1)
{
  Observation result;
  result.mv = mv;
  result.source = source;
  result.unit = unit;
  result.sourceList = list;
  result.historyAge = age;
  result.historyIndex = source == HISTORY ? unit : -1;
  return result;
}

Input base()
{
  Input input;
  input.context.width = 16;
  input.context.height = 8;
  input.context.targetList = 0;
  input.p0 = {0, 0};
  input.b1 = {1, 0};
  return input;
}

const Candidate &find(const Prepared &pool, const Vec mv)
{
  for (const auto &candidate : pool.candidates) { if (candidate.mv == mv) { return candidate; } }
  throw std::runtime_error("Expected candidate is absent");
}

// An independent reference uses ordered sets/maps, floating-point mean rounding
// for these small integer evidence sets, and its own length/quantization code.
int referenceBits(int64_t delta)
{
  const uint64_t absolute = delta < 0 ? uint64_t(-delta) : uint64_t(delta);
  uint64_t code = absolute * 2 + 1;
  int bits = 1;
  for (code /= 2; code; code /= 2) { bits += 2; }
  return bits;
}
int referenceRate(const Vec &mv, const Vec &pred)
{
  return referenceBits(int64_t(mv.x) - pred.x) + referenceBits(int64_t(mv.y) - pred.y);
}
int referenceQuantize(int64_t value)
{
  const int sign = value < 0 ? -1 : 1;
  uint64_t absolute = value < 0 ? uint64_t(-(value + 1)) + 1 : uint64_t(value);
  if (absolute < 5) { return sign * int(absolute); }
  int bucket = 3;
  while (absolute > 1) { ++bucket; absolute /= 2; }
  return sign * bucket;
}
bool nearReference(const Vec &a, const Vec &b)
{
  return std::llabs(int64_t(a.x) - b.x) <= 1 && std::llabs(int64_t(a.y) - b.y) <= 1;
}
Vec referenceMedian(const std::vector<Vec> &motions)
{
  if (motions.empty()) { return {}; }
  std::vector<int> xs;
  std::vector<int> ys;
  for (const auto &mv : motions) { xs.push_back(mv.x); ys.push_back(mv.y); }
  const auto middle = (motions.size() - 1) / 2;
  std::nth_element(xs.begin(), xs.begin() + middle, xs.end());
  std::nth_element(ys.begin(), ys.begin() + middle, ys.end());
  return {xs[middle], ys[middle]};
}
int64_t referenceDispersion(const std::vector<Vec> &motions)
{
  if (motions.empty()) { return 0; }
  Vec median = referenceMedian(motions);
  std::vector<int64_t> distances;
  for (const auto &mv : motions)
  {
    distances.push_back(std::llabs(int64_t(mv.x) - median.x) + std::llabs(int64_t(mv.y) - median.y));
  }
  const auto middle = (distances.size() - 1) / 2;
  std::nth_element(distances.begin(), distances.begin() + middle, distances.end());
  return distances[middle];
}
int referenceCoverage(const std::vector<Vec> &motions, const Input &input, const Vec candidate)
{
  if (motions.empty()) { return 0; }
  double improvement = 0;
  for (const auto &mv : motions)
  {
    const int baseBits = std::min(referenceRate(mv, input.p0), referenceRate(mv, input.b1));
    const int trialBits = std::min(referenceRate(mv, input.p0), referenceRate(mv, candidate));
    improvement += baseBits - trialBits;
  }
  return int(std::lround(4.0 * improvement / motions.size()));
}

Prepared independent(const Input &input)
{
  Prepared result;
  Candidate baseline;
  baseline.mv = input.b1;
  result.candidates.push_back(baseline);
  std::set<std::pair<int, int>> inserted = {{input.b1.x, input.b1.y}};
  for (const auto &raw : input.raw)
  {
    if (raw.mv != input.p0 && inserted.emplace(raw.mv.x, raw.mv.y).second)
    {
      Candidate candidate;
      candidate.mv = raw.mv;
      result.candidates.push_back(candidate);
    }
  }
  std::map<int, std::vector<Observation>> spatial;
  std::map<int, std::vector<Observation>> history;
  std::vector<Vec> spatialRepresentatives;
  std::vector<Vec> historyRepresentatives;
  for (const auto &raw : input.raw)
  {
    if (raw.source == LEFT || raw.source == ABOVE)
    {
      if (spatial[raw.unit].empty()) { spatialRepresentatives.push_back(raw.mv); }
      spatial[raw.unit].push_back(raw);
    }
    if (raw.source == HISTORY)
    {
      if (history[raw.unit].empty()) { historyRepresentatives.push_back(raw.mv); }
      history[raw.unit].push_back(raw);
    }
  }
  result.spatialUnits = int(spatial.size());
  result.historyUnits = int(history.size());
  const auto support = [](const auto &units, Vec mv, int list = -1) {
    int count = 0;
    for (const auto &unit : units)
    {
      bool found = false;
      for (const auto &raw : unit.second)
      {
        found |= (list < 0 || raw.sourceList == list) && nearReference(mv, raw.mv);
      }
      count += found;
    }
    return count;
  };

  for (auto &candidate : result.candidates)
  {
    std::set<int> same;
    std::set<int> other;
    int exactSourceLists = 0;
    int historyAge = -1;
    for (const auto &raw : input.raw)
    {
      if (raw.mv != candidate.mv) { continue; }
      candidate.sourceMask |= raw.source;
      if (raw.source == HISTORY || raw.source == LEFT || raw.source == ABOVE)
      {
        exactSourceLists |= raw.sourceList == input.context.targetList ? 1 : 2;
      }
      if (raw.source == HISTORY)
      {
        if (raw.historyAge >= 0 && (historyAge < 0 || raw.historyAge < historyAge)) { historyAge = raw.historyAge; }
        if (raw.sourceList == input.context.targetList)
        {
          same.insert(raw.unit);
          if (raw.historyAge >= 0 && (candidate.historySameAge < 0 || raw.historyAge < candidate.historySameAge))
          {
            candidate.historySameAge = raw.historyAge;
          }
        }
        else
        {
          other.insert(raw.unit);
          if (raw.historyAge >= 0 && (candidate.historyOtherAge < 0 || raw.historyAge < candidate.historyOtherAge))
          {
            candidate.historyOtherAge = raw.historyAge;
          }
        }
      }
    }
    candidate.historySameCount = int(same.size());
    candidate.historyOtherCount = int(other.size());
    candidate.historyListMask = (!same.empty() ? 1 : 0) + (!other.empty() ? 2 : 0);
    candidate.historySameSupport = support(history, candidate.mv, input.context.targetList);
    candidate.historyOtherSupport = support(history, candidate.mv, 1 - input.context.targetList);
    auto &f = candidate.rawFeatures;
    const std::array<Vec, 4> anchors = {input.p0, input.b1, referenceMedian(spatialRepresentatives),
                                       referenceMedian(historyRepresentatives)};
    for (int a = 0; a < 4; ++a)
    {
      if ((a == 2 && spatial.empty()) || (a == 3 && history.empty())) { continue; }
      f[a * 2] = int64_t(candidate.mv.x) - anchors[a].x;
      f[a * 2 + 1] = int64_t(candidate.mv.y) - anchors[a].y;
    }
    f[8] = referenceCoverage(spatialRepresentatives, input, candidate.mv);
    f[9] = referenceCoverage(historyRepresentatives, input, candidate.mv);
    f[10] = support(spatial, candidate.mv);
    f[11] = support(history, candidate.mv);
    f[12] = support(spatial, input.p0);
    f[13] = support(history, input.p0);
    f[14] = referenceDispersion(spatialRepresentatives);
    f[15] = referenceDispersion(historyRepresentatives);
    for (int source = 0; source < 4; ++source) { f[16 + source] = bool(candidate.sourceMask & (1 << source)); }
    f[20] = candidate.mv == Vec{};
    f[21] = historyAge;
    f[22] = exactSourceLists == 2;
    f[23] = input.context.longTerm;
    f[24] = int(std::floor(std::log2(input.context.width)));
    f[25] = int(std::floor(std::log2(input.context.height)));
    f[26] = input.context.imv;
    f[27] = input.context.refPocDelta;
    f[28] = input.context.targetList;
    f[29] = input.context.bSlice;
    f[30] = result.spatialUnits;
    f[31] = result.historyUnits;
    for (int i = 0; i < 32; ++i)
    {
      int64_t value = f[i];
      if (i < 8 || i == 14 || i == 15) { value = referenceQuantize(value); }
      if (i == 27) { value = std::max(int64_t(-32767), std::min(int64_t(32767), value)); }
      value = std::max(int64_t(-32768), std::min(int64_t(32767), value));
      candidate.features[i] = int16_t(value);
    }
  }
  return result;
}

void compare(const Input &input)
{
  const auto actual = prepare(input);
  const auto expected = independent(input);
  require(actual.spatialUnits == expected.spatialUnits, "independent spatial unit count");
  require(actual.historyUnits == expected.historyUnits, "independent history unit count");
  require(actual.candidates.size() == expected.candidates.size(), "independent candidate count");
  for (size_t i = 0; i < actual.candidates.size(); ++i)
  {
    const auto &a = actual.candidates[i];
    const auto &b = expected.candidates[i];
    require(a.mv == b.mv, "stable candidate order");
    require(a.rawFeatures == b.rawFeatures, "independent 32 raw features");
    require(a.features == b.features, "independent 32 quantized features");
    require(a.sourceMask == b.sourceMask && a.historyListMask == b.historyListMask, "source/list masks");
    require(a.historySameCount == b.historySameCount && a.historyOtherCount == b.historyOtherCount, "history counts");
    require(a.historySameAge == b.historySameAge && a.historyOtherAge == b.historyOtherAge, "history ages");
    require(a.historySameSupport == b.historySameSupport && a.historyOtherSupport == b.historyOtherSupport,
            "per-list support counts");
    require((a.rawFeatures[8] == 0 && a.rawFeatures[9] == 0) || i != 0, "baseline coverage gains are zero");
  }
}

void fixedCases()
{
  auto empty = base();
  auto pool = prepare(empty);
  require(pool.candidates.size() == 1 && pool.candidates[0].mv == empty.b1, "empty pool preserves b1");
  const auto &f = pool.candidates[0].rawFeatures;
  require(f[4] == 0 && f[5] == 0 && f[6] == 0 && f[7] == 0, "empty set distances use zero");
  require(f[8] == 0 && f[9] == 0 && f[21] == -1 && f[30] == 0 && f[31] == 0, "empty evidence sentinels");
  compare(empty);

  auto coverage = base();
  coverage.raw = {observation({0, 0}, LEFT, 0, 0), observation({8, 0}, ABOVE, 0, 0),
                  observation({8, 0}, LEFT, 1, 0), observation({8, 0}, HISTORY, 0, 0, 4),
                  observation({8, 0}, HISTORY, 0, 1, 4), observation({1, 0}, HISTORY, 1, 1, 1),
                  observation({8, 0}, HISTORY, 2, 0, 2), observation({9, 0}, HISTORY, 3, 1, 0),
                  observation({8, 0}, TEMPORAL), observation({0, 0}, ZERO)};
  pool = prepare(coverage);
  const auto &eight = find(pool, {8, 0});
  require(pool.spatialUnits == 2 && pool.historyUnits == 4, "independent unit deduplication");
  require(eight.rawFeatures[8] == 12, "manual complementary spatial coverage gain");
  require(eight.rawFeatures[10] == 2, "any sampled MV from the same CU can support once");
  require(eight.historyListMask == 3 && eight.historySameCount == 2 && eight.historyOtherCount == 1,
          "same history record both lists remains one record per direction");
  require(eight.historySameSupport == 2 && eight.historyOtherSupport == 2, "near support is distinct from exact provenance");
  require(eight.historySameAge == 2 && eight.historyOtherAge == 4 && eight.rawFeatures[21] == 2,
          "nearby age-zero history does not overwrite exact-source age");
  require(eight.sourceMask == (ABOVE | LEFT | HISTORY | TEMPORAL), "all raw source masks merged");
  require(eight.rawFeatures[22] == 0 && find(pool, {1, 0}).rawFeatures[22] == 1, "other-list only definition");
  require(eight.rawFeatures[4] == 8, "lower component median and first-per-CU representative");
  compare(coverage);

  auto fallback = coverage;
  fallback.b1 = fallback.p0;
  pool = prepare(fallback);
  require(pool.candidates[0].mv == fallback.p0 && pool.candidates[0].rawFeatures[20] == 1,
          "b1 equal p0 is retained as the zero-motion fallback");
  require(std::count_if(pool.candidates.begin(), pool.candidates.end(), [&](const Candidate &c) { return c.mv == fallback.p0; }) == 1,
          "extra p0 observations do not add duplicates");
  require((pool.candidates[0].sourceMask & ZERO) != 0, "excluded p0 observation still contributes source metadata");
  compare(fallback);

  auto negative = base();
  negative.b1 = {8, 0};
  negative.raw = {observation({8, 0}, LEFT, 0, 0), observation({1, 0}, TEMPORAL)};
  require(find(prepare(negative), {1, 0}).rawFeatures[8] == -24, "negative coverage gain retained");
  compare(negative);

  std::vector<Vec> half(16, {0, 0});
  half.back() = {2, 0};
  require(coverageGainQ2(half, {0, 0}, {1, 0}, {2, 0}) == 1, "positive half-way rounding away from zero");
  require(coverageGainQ2(half, {0, 0}, {2, 0}, {1, 0}) == -1, "negative half-way rounding away from zero");

  for (int v = -10000; v <= 10000; ++v)
  {
    require(quantizeDistance(v) == referenceQuantize(v), "signed distance quantization");
    require(rate({v, -v}, {0, 0}) == referenceRate({v, -v}, {0, 0}), "component length proxy");
  }
  require(quantizeDistance(4) == 4 && quantizeDistance(5) == 5 && quantizeDistance(7) == 5 &&
            quantizeDistance(8) == 6 && quantizeDistance(-16) == -7, "quantization bucket boundaries");
  require(quantizeDistance(INT64_MIN) == -66 && quantizeDistance(INT64_MAX) == 65,
          "full-range quantization has no signed overflow");
  auto extremes = base();
  extremes.p0 = {INT32_MIN, INT32_MAX};
  extremes.b1 = {INT32_MAX, INT32_MIN};
  extremes.context.refPocDelta = INT32_MIN;
  extremes.raw = {observation({0, 0}, ZERO)};
  require(rate(extremes.p0, extremes.b1) == 130, "extreme vector differences have a valid bounded rate");
  require(prepare(extremes).candidates[0].rawFeatures[0] == 4294967295LL, "raw vector subtraction uses 64 bits");
  require(prepare(extremes).candidates[0].features[27] == -32767, "POC clip lower bound");
  compare(extremes);

  for (int imv = 0; imv < 4; ++imv)
  {
    auto input = coverage;
    input.context.imv = imv;
    input.context.refPocDelta = 70000;
    input.context.longTerm = true;
    input.context.bSlice = true;
    input.context.width = 12;
    const auto c = prepare(input).candidates[0];
    require(c.features[24] == 3 && c.features[26] == imv && c.features[27] == 32767,
            "context uses floorLog2, imv and POC clip");
    require(c.rawFeatures[27] == 70000 && c.features[23] == 1 && c.features[29] == 1,
            "uncompressed context and boolean values");
    compare(input);
  }

  auto capacity = base();
  capacity.p0 = {-100, 0};
  capacity.b1 = {-101, 0};
  for (int i = 0; i < 15; ++i) { capacity.raw.push_back(observation({i, 0}, TEMPORAL)); }
  require(prepare(capacity).candidates.size() == 16, "full sixteen-candidate capacity");
  compare(capacity);
  capacity.raw.push_back(observation({99, 0}, TEMPORAL));
  bool rejected = false;
  try { prepare(capacity); } catch (const std::invalid_argument &) { rejected = true; }
  require(rejected, "oversized observations rejected");
  auto invalid = base();
  invalid.raw.push_back(observation({0, 0}, HISTORY));
  rejected = false;
  try { prepare(invalid); } catch (const std::invalid_argument &) { rejected = true; }
  require(rejected, "missing unit/list rejected rather than silently biasing features");
}

void randomizedCases()
{
  std::mt19937 random(0x413256u);
  const auto integer = [&](int minimum, int maximum) {
    return minimum + int(random() % unsigned(maximum - minimum + 1));
  };
  for (int trial = 0; trial < 12000; ++trial)
  {
    auto input = base();
    input.context.imv = integer(0, 3);
    input.context.width = 1 << integer(2, 7);
    input.context.height = 1 << integer(2, 7);
    input.context.refPocDelta = integer(-50000, 50000);
    input.context.targetList = integer(0, 1);
    input.context.longTerm = integer(0, 1);
    input.context.bSlice = integer(0, 1);
    input.p0 = {integer(-20, 20), integer(-20, 20)};
    input.b1 = trial % 7 ? Vec{integer(-20, 20), integer(-20, 20)} : input.p0;
    for (int n = integer(0, 15); n > 0; --n)
    {
      const int source = 1 << integer(0, 4);
      Vec mv = {integer(-20, 20), integer(-20, 20)};
      if (source == ZERO) { mv = {}; }
      const int unit = source == TEMPORAL || source == ZERO ? -1 : integer(0, 4);
      const int list = unit < 0 ? -1 : integer(0, 1);
      input.raw.push_back(observation(mv, source, unit, list, source == HISTORY ? integer(0, 4) : -1));
    }
    compare(input);
  }
}
} // namespace

int main()
{
  try
  {
    fixedCases();
    randomizedCases();
    std::cout << "PASS: 12000 independent randomized cases and boundary cases; " << checks << " checks\n";
    return 0;
  }
  catch (const std::exception &error)
  {
    std::cerr << "FAIL after " << checks << " checks: " << error.what() << '\n';
    return 1;
  }
}
