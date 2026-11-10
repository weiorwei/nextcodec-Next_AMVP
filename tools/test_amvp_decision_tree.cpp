// Standalone tests of production mode-8 features and weighted selection.
#include "CommonLib/AmvpCandidateSelector.h"
#include "CommonLib/AmvpDecisionTree.h"

#include <array>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>

namespace
{
using MotionPool = std::array<Mv, AMVP_ARMC_MAX_NUM_CANDS>;
using Metadata = std::array<AmvpDecisionTree::CandidateMetadata, AMVP_ARMC_MAX_NUM_CANDS>;

void require(const bool condition, const char *message)
{
  if (!condition) { throw std::runtime_error(message); }
}

uint32_t referenceBits(const int value)
{
  uint64_t mapped = value <= 0 ? uint64_t(-int64_t(value)) * 2 + 1 : uint64_t(value) * 2;
  uint32_t bits = 1;
  while ((mapped >>= 1) != 0) { bits += 2; }
  return bits;
}

int referenceWeight(const AmvpDecisionTree::CandidateMetadata &metadata, const int profile)
{
  if (profile == 1 && metadata.spatialCuSupport >= 2) { return 4; }
  const int families = !!(metadata.sourceMask & 1) + !!(metadata.sourceMask & 2) + !!(metadata.sourceMask & 4);
  if (profile == 2 && families >= 2) { return 4; }
  if (profile == 3 && metadata.historyAge == 0) { return 2; }
  if (profile == 4) { return metadata.sourceMask & 2 ? 4 : metadata.sourceMask & 1 ? 2 : 1; }
  return 1;
}

AmvpDecisionTree::Pair referencePair(const MotionPool &motion, const Metadata &metadata, const int size,
                                    const int imv, const int profile)
{
  std::vector<Mv> coded;
  std::vector<int> slots;
  std::vector<AmvpDecisionTree::CandidateMetadata> merged;
  for (int slot = 0; slot < size; ++slot)
  {
    if (!metadata[slot].derived) { continue; }
    Mv candidate = motion[slot];
    candidate.changeTransPrecInternal2Amvr(imv);
    const auto found = std::find(coded.begin(), coded.end(), candidate);
    if (found == coded.end())
    {
      coded.push_back(candidate);
      slots.push_back(slot);
      merged.push_back(metadata[slot]);
    }
    else
    {
      auto &entry = merged[size_t(found - coded.begin())];
      entry.sourceMask |= metadata[slot].sourceMask;
      entry.spatialCuSupport = std::max(entry.spatialCuSupport, metadata[slot].spatialCuSupport);
      if (metadata[slot].historyAge >= 0 &&
          (entry.historyAge < 0 || metadata[slot].historyAge < entry.historyAge))
      {
        entry.historyAge = metadata[slot].historyAge;
      }
    }
  }
  AmvpDecisionTree::Pair pair;
  if (coded.size() < 2) { return pair; }
  uint64_t best = std::numeric_limits<uint64_t>::max();
  auto distance = [](const Mv &a, const Mv &b) {
    return referenceBits(a.getHor() - b.getHor()) + referenceBits(a.getVer() - b.getVer());
  };
  for (size_t i = 0; i < coded.size(); ++i)
  {
    for (size_t j = i + 1; j < coded.size(); ++j)
    {
      uint64_t cost = 0;
      for (size_t k = 0; k < coded.size(); ++k)
      {
        cost += uint64_t(referenceWeight(merged[k], profile)) *
                std::min(distance(coded[k], coded[i]), distance(coded[k], coded[j]));
      }
      if (cost < best)
      {
        best = cost;
        pair.first = slots[i];
        pair.second = slots[j];
      }
    }
  }
  return pair;
}

void check(const MotionPool &motion, const Metadata &metadata, const int size,
           const AmvpDecisionTree::Context &context)
{
  const auto prepared = AmvpDecisionTree::preparePool(motion.data(), metadata.data(), size, context.imv);
  const auto features = AmvpDecisionTree::extractFeatures(prepared, context);
  for (int profile = 0; profile < AmvpDecisionTree::numProfiles; ++profile)
  {
    const auto expected = referencePair(motion, metadata, size, context.imv, profile);
    const auto actual = AmvpDecisionTree::selectProfile(prepared, profile);
    require(actual.first == expected.first && actual.second == expected.second,
            "Weighted selector differs from independent exhaustive reference");
    if (profile == 0)
    {
      std::array<bool, AMVP_ARMC_MAX_NUM_CANDS> valid{};
      for (int i = 0; i < size; ++i) { valid[i] = metadata[i].derived; }
      MotionPool mode7 = motion;
      AmvpCandidateSelector::reorderMotionOnly(motion.data(), valid.data(), size, context.imv, mode7.data());
      require(mode7[0] == motion[actual.first] && mode7[1] == motion[actual.second],
              "Uniform profile changed existing mode-7 top-2");
    }
  }
  const int selectedProfile = AmvpDecisionTree::predictProfile(features);
  const auto pair = referencePair(motion, metadata, size, context.imv, selectedProfile);
  MotionPool result = motion;
  AmvpDecisionTree::reorder(motion.data(), metadata.data(), size, context, result.data());
  require(result[0] == motion[pair.first] && result[1] == motion[pair.second],
          "Model-selected profile gives an incorrect candidate pair");
  MotionPool inPlace = motion;
  AmvpDecisionTree::reorder(inPlace.data(), metadata.data(), size, context, inPlace.data());
  require(result == inPlace, "In-place decision-tree reordering differs");
  std::vector<Mv> expectedTail;
  for (int i = 0; i < size; ++i)
  {
    if (i != pair.first && i != pair.second) { expectedTail.push_back(motion[i]); }
  }
  for (size_t i = 0; i < expectedTail.size(); ++i)
  {
    require(result[i + 2] == expectedTail[i], "Full candidate permutation lost original tail order");
  }
}
} // namespace

int main()
{
  try
  {
    MotionPool motion = { Mv(0, 0), Mv(16, 0), Mv(64, 0), Mv(16, 0), Mv(), Mv(), Mv(), Mv() };
    Metadata metadata{};
    metadata[0] = { true, 1, 2, -1 };
    metadata[1] = { true, 5, 1, 0 };
    metadata[2] = { true, 2, 0, -1 };
    metadata[3] = { true, 2, 1, -1 };
    const AmvpDecisionTree::Context context = { 0, 32, 16, -3 };
    const auto prepared = AmvpDecisionTree::preparePool(motion.data(), metadata.data(), 8, 0);
    const AmvpDecisionTree::Features expected = { 0, 5, 4, 3, 2, 2, 1, 16, 0, 2, 1, 3 };
    require(AmvpDecisionTree::extractFeatures(prepared, context) == expected,
            "Feature ABI or metadata merging changed");
    require(prepared.metadata[1].sourceMask == 7, "Duplicate MV lost overlapping source families");
    check(motion, metadata, 8, context);
    check(motion, Metadata{}, 8, context);
    metadata[1].derived = metadata[2].derived = metadata[3].derived = false;
    check(motion, metadata, 8, context);
    const auto realZero = AmvpDecisionTree::preparePool(motion.data(), metadata.data(), 8, 0);
    require(realZero.numUnique == 1 && realZero.slot[0] == 0, "Legitimate zero MV was removed");
    metadata[0].derived = false;
    metadata[1] = { true, 1, 1, -1 };
    metadata[2] = { true, 4, 0, 0 };
    const auto noPadding = AmvpDecisionTree::preparePool(motion.data(), metadata.data(), 8, 0);
    require(noPadding.numUnique == 2 && noPadding.slot[0] == 1 && noPadding.slot[1] == 2,
            "Padding-only zero became a selectable centre");
    check(motion, metadata, 8, context);

    std::mt19937 generator(8);
    int cases = 0;
    for (int imv = 0; imv < 4; ++imv)
    {
      for (int size = 2; size <= 8; ++size)
      {
        for (int trial = 0; trial < 1000; ++trial)
        {
          MotionPool randomMotion{};
          Metadata randomMetadata{};
          for (int slot = 0; slot < size; ++slot)
          {
            const int range = trial % 2 == 0 ? 131072 : 16;
            randomMotion[slot] = Mv(int(generator() % (2 * range)) - range,
                                    int(generator() % (2 * range)) - range);
            if (slot && generator() % 3 == 0) { randomMotion[slot] = randomMotion[generator() % slot]; }
            randomMetadata[slot] = { generator() % 4 != 0, unsigned(generator() % 8), int(generator() % 6),
                                     int(generator() % 7) - 1 };
          }
          check(randomMotion, randomMetadata, size, { imv, 4 << (generator() % 5),
                                                      4 << (generator() % 5), int(generator() % 33) - 16 });
          ++cases;
        }
      }
    }
    std::cout << "PASS: feature/metadata/fallback/padding tests and " << cases
              << " randomized cases across all five profiles, including mode-7 parity and in-place output\n";
  }
  catch (const std::exception &error)
  {
    std::cerr << "FAIL: " << error.what() << '\n';
    return 1;
  }
  return 0;
}
