// Pure integer, observational AMVP features. All vectors use the current AMVR
// integer grid. This module has no codec state, pixel access, or selection side
// effects; its output must never be used to alter the baseline coding path.
#ifndef AMVP_FEATURE_STATS_H
#define AMVP_FEATURE_STATS_H

#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

namespace AmvpFeatureStats
{
constexpr int numFeatures = 32;
constexpr int maxCandidates = 16;
constexpr int maxObservations = 15;

struct Vec
{
  int x = 0;
  int y = 0;
};

inline bool operator==(const Vec &a, const Vec &b) { return a.x == b.x && a.y == b.y; }
inline bool operator!=(const Vec &a, const Vec &b) { return !(a == b); }

enum Source : int { LEFT = 1, ABOVE = 2, TEMPORAL = 4, HISTORY = 8, ZERO = 16 };

struct Observation
{
  Vec mv;
  int source = 0;
  int unit = -1;
  int sourceList = -1;
  int historyAge = -1;
  int historyIndex = -1;
  int probeIndex = -1; // spatial A0/A1/B0/B1/B2=0..4, temporal C0/C1=0/1
  int x = -1;
  int y = -1;
  int w = 0;
  int h = 0;
};

struct Context
{
  int imv = 0;
  int width = 0;
  int height = 0;
  int refPocDelta = 0;
  int targetList = 0;
  bool longTerm = false;
  bool bSlice = false;
};

struct Input
{
  Vec p0;
  Vec b1;
  Context context;
  std::vector<Observation> raw;
};

struct Candidate
{
  Vec mv;
  std::array<int64_t, numFeatures> rawFeatures{};
  std::array<int16_t, numFeatures> features{};
  int sourceMask = 0;
  int historyListMask = 0;
  int historySameCount = 0;
  int historyOtherCount = 0;
  int historySameAge = -1;
  int historyOtherAge = -1;
  int historySameSupport = 0;
  int historyOtherSupport = 0;
};

struct Prepared
{
  std::vector<Candidate> candidates;
  int spatialUnits = 0;
  int historyUnits = 0;
};

namespace detail
{
inline uint64_t magnitude(const int64_t value)
{
  return value < 0 ? uint64_t(-(value + 1)) + 1 : uint64_t(value);
}

inline int log2Floor(uint64_t value)
{
  if (value == 0) { throw std::invalid_argument("AMVP feature log2 requires a positive value"); }
  int result = 0;
  while (value >>= 1) { ++result; }
  return result;
}

inline bool spatial(const Observation &o) { return (o.source & (LEFT | ABOVE)) != 0; }
inline bool historical(const Observation &o) { return (o.source & HISTORY) != 0; }

inline int64_t distanceL1(const Vec &a, const Vec &b)
{
  return int64_t(magnitude(int64_t(a.x) - b.x) + magnitude(int64_t(a.y) - b.y));
}

inline bool near(const Vec &a, const Vec &b)
{
  return magnitude(int64_t(a.x) - b.x) <= 1 && magnitude(int64_t(a.y) - b.y) <= 1;
}

inline void addUnit(std::vector<int> &units, const int unit)
{
  if (std::find(units.begin(), units.end(), unit) == units.end()) { units.push_back(unit); }
}

struct Representatives
{
  std::vector<int> units;
  std::vector<Vec> motions;
};

inline Representatives representatives(const Input &input, const bool history)
{
  Representatives result;
  for (const auto &o : input.raw)
  {
    if (!(history ? historical(o) : spatial(o))) { continue; }
    if (std::find(result.units.begin(), result.units.end(), o.unit) != result.units.end()) { continue; }
    result.units.push_back(o.unit);
    result.motions.push_back(o.mv);
  }
  return result;
}

inline Vec median(const std::vector<Vec> &motions)
{
  if (motions.empty()) { return {}; }
  std::vector<int> xs;
  std::vector<int> ys;
  for (const auto &mv : motions) { xs.push_back(mv.x); ys.push_back(mv.y); }
  std::sort(xs.begin(), xs.end());
  std::sort(ys.begin(), ys.end());
  const auto middle = (motions.size() - 1) / 2;
  return { xs[middle], ys[middle] };
}

inline int64_t dispersion(const std::vector<Vec> &motions, const Vec &centre)
{
  if (motions.empty()) { return 0; }
  std::vector<int64_t> distances;
  for (const auto &mv : motions) { distances.push_back(distanceL1(mv, centre)); }
  std::sort(distances.begin(), distances.end());
  return distances[(distances.size() - 1) / 2];
}

inline int support(const Input &input, const Vec &mv, const bool history, const int sourceList = -1)
{
  std::vector<int> units;
  for (const auto &o : input.raw)
  {
    if (!(history ? historical(o) : spatial(o)) ||
        (sourceList >= 0 && o.sourceList != sourceList) || !near(o.mv, mv))
    {
      continue;
    }
    addUnit(units, o.unit);
  }
  return int(units.size());
}

inline void updateAge(int &age, const int observationAge)
{
  if (observationAge >= 0 && (age < 0 || observationAge < age)) { age = observationAge; }
}

inline int16_t saturate(const int64_t value)
{
  return int16_t(std::max(int64_t(std::numeric_limits<int16_t>::min()),
                          std::min(int64_t(std::numeric_limits<int16_t>::max()), value)));
}

inline void validate(const Input &input)
{
  const auto &c = input.context;
  if (c.imv < 0 || c.imv > 3 || c.width <= 0 || c.height <= 0 || c.targetList < 0 || c.targetList > 1)
  {
    throw std::invalid_argument("Invalid AMVP feature query context");
  }
  if (input.raw.size() > maxObservations) { throw std::invalid_argument("Too many AMVP observations"); }
  for (const auto &o : input.raw)
  {
    if (o.source <= 0 || (o.source & ~(LEFT | ABOVE | TEMPORAL | HISTORY | ZERO)))
    {
      throw std::invalid_argument("Unknown AMVP observation source");
    }
    if ((spatial(o) || historical(o)) && (o.unit < 0 || o.sourceList < 0 || o.sourceList > 1))
    {
      throw std::invalid_argument("Missing AMVP observation identity or source list");
    }
  }
}
} // namespace detail

// Signed logarithmic distance code: preserve -4..4 exactly. Larger magnitudes
// use 5 + floor(log2(abs(value))) - 2, preserving sign. INT64_MIN is supported.
inline int quantizeDistance(const int64_t value)
{
  const uint64_t absolute = detail::magnitude(value);
  const int quantized = absolute <= 4 ? int(absolute) : 5 + detail::log2Floor(absolute) - 2;
  return value < 0 ? -quantized : quantized;
}

// Exp-Golomb-style MVD length proxy, identical in length for either sign of a
// nonzero component. It is not the actual context-adaptive CABAC bitrate.
inline int rate(const Vec mv, const Vec pred)
{
  const auto bits = [](const int64_t delta) {
    const uint64_t code = 2 * detail::magnitude(delta) + 1;
    return 1 + 2 * detail::log2Floor(code);
  };
  return bits(int64_t(mv.x) - pred.x) + bits(int64_t(mv.y) - pred.y);
}

// Q2 average coverage improvement, with nearest integer rounding and exact
// half-way cases away from zero. Empty evidence sets return zero.
inline int coverageGainQ2(const std::vector<Vec> &motions, const Vec p0, const Vec b1, const Vec candidate)
{
  if (motions.empty()) { return 0; }
  int64_t sum = 0;
  for (const auto &mv : motions)
  {
    sum += std::min(rate(mv, p0), rate(mv, b1)) - std::min(rate(mv, p0), rate(mv, candidate));
  }
  const int64_t numerator = 4 * sum;
  const int64_t rounded = int64_t((detail::magnitude(numerator) + motions.size() / 2) / motions.size());
  return int(numerator < 0 ? -rounded : rounded);
}

inline Prepared prepare(const Input &input)
{
  detail::validate(input);
  Prepared result;
  Candidate baseline;
  baseline.mv = input.b1;
  result.candidates.push_back(baseline);
  for (const auto &o : input.raw)
  {
    if (o.mv == input.p0) { continue; }
    const auto existing = std::find_if(result.candidates.begin(), result.candidates.end(),
                                       [&](const Candidate &c) { return c.mv == o.mv; });
    if (existing == result.candidates.end())
    {
      if (result.candidates.size() >= maxCandidates) { throw std::logic_error("AMVP statistics pool overflow"); }
      Candidate candidate;
      candidate.mv = o.mv;
      result.candidates.push_back(candidate);
    }
  }

  const auto spatial = detail::representatives(input, false);
  const auto history = detail::representatives(input, true);
  result.spatialUnits = int(spatial.units.size());
  result.historyUnits = int(history.units.size());
  const Vec spatialMedian = detail::median(spatial.motions);
  const Vec historyMedian = detail::median(history.motions);
  const int64_t spatialDispersion = detail::dispersion(spatial.motions, spatialMedian);
  const int64_t historyDispersion = detail::dispersion(history.motions, historyMedian);
  const int p0SpatialSupport = detail::support(input, input.p0, false);
  const int p0HistorySupport = detail::support(input, input.p0, true);

  for (auto &candidate : result.candidates)
  {
    bool sameList = false;
    bool otherList = false;
    int newestHistoryAge = -1;
    std::vector<int> sameUnits;
    std::vector<int> otherUnits;
    for (const auto &o : input.raw)
    {
      if (o.mv != candidate.mv) { continue; }
      candidate.sourceMask |= o.source;
      if (detail::spatial(o) || detail::historical(o))
      {
        sameList |= o.sourceList == input.context.targetList;
        otherList |= o.sourceList != input.context.targetList;
      }
      if (detail::historical(o))
      {
        detail::updateAge(newestHistoryAge, o.historyAge);
        if (o.sourceList == input.context.targetList)
        {
          detail::addUnit(sameUnits, o.unit);
          detail::updateAge(candidate.historySameAge, o.historyAge);
        }
        else
        {
          detail::addUnit(otherUnits, o.unit);
          detail::updateAge(candidate.historyOtherAge, o.historyAge);
        }
      }
    }
    candidate.historySameCount = int(sameUnits.size());
    candidate.historyOtherCount = int(otherUnits.size());
    candidate.historyListMask = (sameUnits.empty() ? 0 : 1) | (otherUnits.empty() ? 0 : 2);
    candidate.historySameSupport = detail::support(input, candidate.mv, true, input.context.targetList);
    candidate.historyOtherSupport = detail::support(input, candidate.mv, true, 1 - input.context.targetList);

    auto &f = candidate.rawFeatures;
    f[0] = int64_t(candidate.mv.x) - input.p0.x;
    f[1] = int64_t(candidate.mv.y) - input.p0.y;
    f[2] = int64_t(candidate.mv.x) - input.b1.x;
    f[3] = int64_t(candidate.mv.y) - input.b1.y;
    if (!spatial.motions.empty())
    {
      f[4] = int64_t(candidate.mv.x) - spatialMedian.x;
      f[5] = int64_t(candidate.mv.y) - spatialMedian.y;
    }
    if (!history.motions.empty())
    {
      f[6] = int64_t(candidate.mv.x) - historyMedian.x;
      f[7] = int64_t(candidate.mv.y) - historyMedian.y;
    }
    f[8] = coverageGainQ2(spatial.motions, input.p0, input.b1, candidate.mv);
    f[9] = coverageGainQ2(history.motions, input.p0, input.b1, candidate.mv);
    f[10] = detail::support(input, candidate.mv, false);
    f[11] = detail::support(input, candidate.mv, true);
    f[12] = p0SpatialSupport;
    f[13] = p0HistorySupport;
    f[14] = spatialDispersion;
    f[15] = historyDispersion;
    f[16] = (candidate.sourceMask & LEFT) != 0;
    f[17] = (candidate.sourceMask & ABOVE) != 0;
    f[18] = (candidate.sourceMask & TEMPORAL) != 0;
    f[19] = (candidate.sourceMask & HISTORY) != 0;
    f[20] = candidate.mv == Vec{};
    f[21] = newestHistoryAge;
    f[22] = otherList && !sameList;
    f[23] = input.context.longTerm;
    f[24] = detail::log2Floor(uint64_t(input.context.width));
    f[25] = detail::log2Floor(uint64_t(input.context.height));
    f[26] = input.context.imv;
    f[27] = input.context.refPocDelta;
    f[28] = input.context.targetList;
    f[29] = input.context.bSlice;
    f[30] = result.spatialUnits;
    f[31] = result.historyUnits;
    for (int i = 0; i < numFeatures; ++i)
    {
      if (i < 8 || i == 14 || i == 15) { candidate.features[i] = int16_t(quantizeDistance(f[i])); }
      else if (i == 27) { candidate.features[i] = int16_t(std::max(int64_t(-32767), std::min(int64_t(32767), f[i]))); }
      else { candidate.features[i] = detail::saturate(f[i]); }
    }
  }
  return result;
}
} // namespace AmvpFeatureStats

#endif // AMVP_FEATURE_STATS_H
