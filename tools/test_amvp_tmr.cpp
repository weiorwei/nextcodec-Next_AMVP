// Standalone tests for the shared production TMR selector. No pixels, pictures,
// templates, or final encoder MV are needed. Compile from the codebase root:
/* c++ -std=c++17 -O2 -ffunction-sections -fdata-sections -I source/Lib
     -I thirdparty/sadl -I thirdparty tools/test_amvp_tmr.cpp
     source/Lib/CommonLib/Mv.cpp -Wl,--gc-sections -o /tmp/test_amvp_tmr */
#include "CommonLib/AmvpTmrSelector.h"

#include <array>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>

namespace
{
using MotionPool = std::array<Mv, AMVP_ARMC_MAX_NUM_CANDS>;
using Costs = std::array<Distortion, AMVP_ARMC_MAX_NUM_CANDS>;

void require(const bool condition, const char *message)
{
  if (!condition)
  {
    throw std::runtime_error(message);
  }
}

uint32_t referenceBits(const int value)
{
  uint64_t mapped = value <= 0 ? uint64_t(-int64_t(value)) * 2 + 1 : uint64_t(value) * 2;
  uint32_t bits = 1;
  while ((mapped >>= 1) != 0)
  {
    bits += 2;
  }
  return bits;
}

// Independent integer implementation of INTERNAL -> AMVR rounding, including
// the production precision's symmetric half-way rounding toward zero.
int referenceCoordinate(const int value, const int imv)
{
  static constexpr int shifts[] = { 2, 4, 6, 3 };
  const int shift = shifts[imv];
  const int magnitude = int((std::abs(int64_t(value)) + (int64_t(1) << (shift - 1)) - 1) >> shift);
  return value < 0 ? -magnitude : magnitude;
}

std::vector<int> referenceOrder(const MotionPool &pool, const int size, const int imv, const bool full)
{
  // Deliberately deduplicate internal MVs, not the AMVR-rounded coordinates.
  std::vector<int> indices;
  for (int i = 0; i < size; i++)
  {
    bool duplicate = false;
    for (const int previous : indices)
    {
      duplicate = duplicate || pool[i] == pool[previous];
    }
    if (!duplicate)
    {
      indices.push_back(i);
    }
  }
  if (indices.size() < 2)
  {
    std::vector<int> unchanged;
    for (int i = 0; i < size; i++)
    {
      unchanged.push_back(i);
    }
    return unchanged;
  }

  std::vector<std::pair<int, int>> coordinates;
  for (const int index : indices)
  {
    coordinates.emplace_back(referenceCoordinate(pool[index].hor, imv), referenceCoordinate(pool[index].ver, imv));
  }
  auto bits = [&](const size_t point, const size_t centre) {
    return referenceBits(coordinates[point].first - coordinates[centre].first)
           + referenceBits(coordinates[point].second - coordinates[centre].second);
  };
  static constexpr uint32_t liteWeights[] = { 64, 32, 16, 8, 4, 2, 1, 1 };
  static constexpr uint32_t fullWeights[] = { 8, 7, 6, 5, 4, 3, 2, 1 };
  uint64_t best = std::numeric_limits<uint64_t>::max();
  size_t first = 0;
  size_t second = 1;
  for (size_t a = 0; a < (full ? indices.size() - 1 : 1); a++)
  {
    for (size_t b = a + 1; b < indices.size(); b++)
    {
      uint64_t sum = 0;
      for (size_t k = 0; k < indices.size(); k++)
      {
        sum += uint64_t(full ? fullWeights[k] : liteWeights[k]) * std::min(bits(k, a), bits(k, b));
      }
      if (sum < best)
      {
        best = sum;
        first = a;
        second = b;
      }
    }
  }
  std::vector<int> order = { indices[first], indices[second] };
  for (int i = 0; i < size; i++)
  {
    if (i != indices[first] && i != indices[second])
    {
      order.push_back(i);
    }
  }
  return order;
}

MotionPool check(const MotionPool &pool, const int size, const int imv, const bool full)
{
  const std::vector<int> expectedOrder = referenceOrder(pool, size, imv, full);
  MotionPool selected = pool;
  Costs costs{};
  Costs selectedCosts{};
  for (int i = 0; i < size; i++)
  {
    costs[i] = i * 19 + 3;   // Distinguish duplicated input slots as well.
  }
  AmvpTmrSelector::reorder(pool.data(), size, imv, full, selected.data(), costs.data(), selectedCosts.data());
  for (int i = 0; i < size; i++)
  {
    require(selected[i] == pool[expectedOrder[i]], "TMR differs from independent exhaustive pair reference");
    require(selectedCosts[i] == costs[expectedOrder[i]], "Candidate diagnostic costs lost their stable slot mapping");
  }
  for (int i = size; i < AMVP_ARMC_MAX_NUM_CANDS; i++)
  {
    require(selected[i] == pool[i], "TMR overwrote entries outside the input size");
  }
  if (!full)
  {
    require(selected[0] == pool[0], "Lite did not retain the original index-0 anchor");
  }

  MotionPool inPlace = pool;
  Costs inPlaceCosts = costs;
  AmvpTmrSelector::reorder(inPlace.data(), size, imv, full, inPlace.data(), inPlaceCosts.data(), inPlaceCosts.data());
  require(inPlace == selected && inPlaceCosts == selectedCosts, "In-place candidate/cost selection differs");

  MotionPool withoutCosts = pool;
  AmvpTmrSelector::reorder(pool.data(), size, imv, full, withoutCosts.data());
  require(withoutCosts == selected, "Null diagnostic costs changed selection");
  Costs zeroCosts{};
  AmvpTmrSelector::reorder(pool.data(), size, imv, full, withoutCosts.data(), nullptr, zeroCosts.data());
  for (const Distortion cost : zeroCosts)
  {
    require(cost == 0, "Missing input costs must give zero output costs");
  }
  return selected;
}
}   // namespace

int main()
{
  try
  {
    const MotionPool example = { Mv(), Mv(4, 0), Mv(32, 0), Mv(36, 0), Mv(), Mv(), Mv(), Mv() };
    const MotionPool lite = check(example, 8, 0, false);
    require(lite[0] == example[0] && lite[1] == example[2], "Lite complementary-centre example is wrong");

    const MotionPool fullExample = { Mv(200, 0), Mv(), Mv(4, 0), Mv(8, 0),
                                    Mv(400, 0), Mv(404, 0), Mv(408, 0), Mv(412, 0) };
    const MotionPool full = check(fullExample, 8, 0, true);
    require(full[0] != fullExample[0] && full[1] != fullExample[0], "Full unexpectedly fixes the original index-0 anchor");

    const MotionPool allSame = { Mv(32, -16), Mv(32, -16), Mv(32, -16), Mv(32, -16),
                                Mv(32, -16), Mv(32, -16), Mv(32, -16), Mv(32, -16) };
    require(check(allSame, 8, 0, false) == allSame, "Single-unique Lite fallback changed input order");
    require(check(allSame, 8, 0, true) == allSame, "Single-unique Full fallback changed input order");

    // The first synthetic zero is allowed as a centre; all repeated zeros have
    // only one rank weight. No candidate-validity/source mask is consulted.
    const MotionPool padding = { Mv(64, 0), Mv(64, 0), Mv(), Mv(), Mv(), Mv(), Mv(), Mv() };
    const MotionPool padded = check(padding, 8, 0, false);
    require(padded[0] == padding[0] && padded[1] == Mv(), "Unique zero padding stopped participating in TMR");

    // Internal-distinct but coded-equal slots remain distinct hypotheses. The
    // zero coverage tie must choose indices 0/1, unlike AMVR-first deduplication.
    const MotionPool rounding = { Mv(1, 0), Mv(2, 0), Mv(), Mv(), Mv(), Mv(), Mv(), Mv() };
    for (int imv = 0; imv < 4; imv++)
    {
      for (const bool joint : { false, true })
      {
        const MotionPool selected = check(rounding, 8, imv, joint);
        require(selected[0] == rounding[0] && selected[1] == rounding[1], "AMVR rounding changed internal-MV dedup/tie semantics");
      }
    }

    std::mt19937 generator(31415161);
    int cases = 0;
    for (int imv = 0; imv < 4; imv++)
    {
      for (const bool joint : { false, true })
      {
        for (int size = 1; size <= 8; size++)
        {
          for (int trial = 0; trial < 1000; trial++)
          {
            MotionPool pool{};
            for (int i = 0; i < size; i++)
            {
              const int range = trial % 2 == 0 ? 131072 : 8;
              pool[i] = Mv(int(generator() % (2 * range)) - range, int(generator() % (2 * range)) - range);
              if (i > 0 && generator() % 3 == 0)
              {
                pool[i] = pool[generator() % i];
              }
            }
            check(pool, size, imv, joint);
            cases++;
          }
        }
      }
    }
    std::cout << "PASS: Lite/Full anchor, rank-weight, zero-padding, AMVR, stable cost permutation, in-place cases and "
              << cases << " independent randomized exhaustive comparisons\n";
  }
  catch (const std::exception &error)
  {
    std::cerr << "FAIL: " << error.what() << '\n';
    return 1;
  }
  return 0;
}
