// Standalone tests for the production mode-7 selector (no pictures or codec state).
#include "CommonLib/AmvpCandidateSelector.h"

#include <array>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>

namespace
{
using MotionPool = std::array<Mv, AMVP_ARMC_MAX_NUM_CANDS>;
using Mask = std::array<bool, AMVP_ARMC_MAX_NUM_CANDS>;

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

MotionPool reference(const MotionPool &pool, const Mask &valid, const int size, const int imv)
{
  std::vector<int> indices;
  std::vector<Mv> coded;
  for (int i = 0; i < size; i++)
  {
    if (!valid[i])
    {
      continue;
    }
    Mv mv = pool[i];
    mv.changeTransPrecInternal2Amvr(imv);
    if (std::find(coded.begin(), coded.end(), mv) == coded.end())
    {
      indices.push_back(i);
      coded.push_back(mv);
    }
  }
  MotionPool result = pool;
  if (coded.size() < 2)
  {
    return result;
  }
  auto distance = [](const Mv &a, const Mv &b) {
    return referenceBits(a.hor - b.hor) + referenceBits(a.ver - b.ver);
  };
  uint64_t bestCost = std::numeric_limits<uint64_t>::max();
  int first = -1;
  int second = -1;
  for (size_t i = 0; i < coded.size(); i++)
  {
    for (size_t j = i + 1; j < coded.size(); j++)
    {
      uint64_t cost = 0;
      for (const Mv &motion : coded)
      {
        cost += std::min(distance(motion, coded[i]), distance(motion, coded[j]));
      }
      if (cost < bestCost)
      {
        bestCost = cost;
        first = indices[i];
        second = indices[j];
      }
    }
  }
  result[0] = pool[first];
  result[1] = pool[second];
  int output = 2;
  for (int i = 0; i < size; i++)
  {
    if (i != first && i != second)
    {
      result[output++] = pool[i];
    }
  }
  return result;
}

MotionPool check(const MotionPool &pool, const Mask &valid, const int size, const int imv)
{
  MotionPool selected = pool;
  AmvpCandidateSelector::reorderMotionOnly(pool.data(), valid.data(), size, imv, selected.data());
  require(selected == reference(pool, valid, size, imv), "Selector differs from independent exhaustive reference");
  MotionPool inPlace = pool;
  AmvpCandidateSelector::reorderMotionOnly(inPlace.data(), valid.data(), size, imv, inPlace.data());
  require(inPlace == selected, "In-place selection differs");
  return selected;
}
}   // namespace

int main()
{
  try
  {
    const Mask all = { true, true, true, true, true, true, true, true };
    const Mask four = { true, true, true, true, false, false, false, false };
    MotionPool clustered = { Mv(0, 0), Mv(4, 0), Mv(80, 0), Mv(84, 0), Mv(), Mv(), Mv(), Mv() };
    const MotionPool result = check(clustered, four, 8, 0);
    require(result[0] == Mv(0, 0) && result[1] == Mv(80, 0), "Two-cluster selection/tie break is wrong");
    clustered[4] = clustered[5] = clustered[6] = clustered[7] = clustered[1];
    const MotionPool duplicates = check(clustered, all, 8, 0);
    require(duplicates[0] == result[0] && duplicates[1] == result[1], "Duplicates changed uniform weights");

    const MotionPool padded = { Mv(), Mv(64, 0), Mv(128, 0), Mv(), Mv(), Mv(), Mv(), Mv() };
    const Mask two = { false, true, true, false, false, false, false, false };
    const MotionPool noPadding = check(padded, two, 8, 0);
    require(noPadding[0] == padded[1] && noPadding[1] == padded[2], "Synthetic zero padding became a centre");
    const Mask realZero = { true, true, false, false, false, false, false, false };
    require(check(padded, realZero, 8, 0)[0] == Mv(), "A real zero candidate was dropped");
    require(check(padded, Mask{}, 8, 0) == padded, "Empty-pool fallback changed the original list");
    const Mask one = { false, true, false, false, false, false, false, false };
    require(check(padded, one, 8, 0) == padded, "One-hypothesis fallback changed the original list");

    const MotionPool precision = { Mv(1, 0), Mv(2, 0), Mv(128, -64), Mv(), Mv(), Mv(), Mv(), Mv() };
    const Mask three = { true, true, true, false, false, false, false, false };
    for (int imv = 0; imv < 4; imv++)
    {
      const MotionPool rounded = check(precision, three, 8, imv);
      require(rounded[0] == precision[0] && rounded[1] == precision[2], "AMVR-equivalent hypotheses were not merged");
    }

    std::mt19937 generator(7);
    int cases = 0;
    for (int imv = 0; imv < 4; imv++)
    {
      for (int size = 2; size <= 8; size++)
      {
        for (int trial = 0; trial < 1000; trial++)
        {
          MotionPool pool;
          Mask valid{};
          for (int i = 0; i < size; i++)
          {
            const int range = trial % 2 == 0 ? 131072 : 8;
            pool[i] = Mv(int(generator() % (2 * range)) - range, int(generator() % (2 * range)) - range);
            if (i > 0 && generator() % 3 == 0)
            {
              pool[i] = pool[generator() % i];
            }
            valid[i] = generator() % 4 != 0;
          }
          check(pool, valid, size, imv);
          cases++;
        }
      }
    }
    std::cout << "PASS: fixed edge cases and " << cases << " randomized mode-7 comparisons, including in-place output\n";
  }
  catch (const std::exception &error)
  {
    std::cerr << "FAIL: " << error.what() << '\n';
    return 1;
  }
  return 0;
}
