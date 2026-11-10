// Standalone tests, from the codebase root:
/* c++ -std=c++17 -O2 -ffunction-sections -fdata-sections -I source/Lib
     -I thirdparty/sadl -I thirdparty tools/test_affine_amvp_tmr.cpp
     source/Lib/CommonLib/Mv.cpp -Wl,--gc-sections -o /tmp/test_affine_amvp_tmr */
#include "CommonLib/AffineAmvpTmrSelector.h"

#include <array>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>

namespace
{
using Candidate = AffineAmvpTmrSelector::Candidate;
using AffinePool = std::array<Candidate, AffineAmvpTmrSelector::MAX_NUM_CANDIDATES>;

void require(const bool condition, const char *message)
{
  if (!condition)
  {
    throw std::runtime_error(message);
  }
}

// Independent scalar rounding, not Mv::changePrecision. Affine precisions
// differ from translation: imv 0/1/2 means 1/4, 1/16, 1 pel.
int referenceCoordinate(const int value, const int imv)
{
  static constexpr int shifts[] = { 2, 0, 4 };
  const int shift = shifts[imv];
  if (shift == 0)
  {
    return value;
  }
  const int magnitude = int((std::abs(int64_t(value)) + (int64_t(1) << (shift - 1)) - 1) >> shift);
  return value < 0 ? -magnitude : magnitude;
}

uint32_t referenceComponentBits(const int value)
{
  uint64_t mapped = value <= 0 ? uint64_t(-int64_t(value)) * 2 + 1 : uint64_t(value) * 2;
  uint32_t bits = 1;
  while ((mapped >>= 1) != 0)
  {
    bits += 2;
  }
  return bits;
}

// Independently express differential control-point prediction in scalar
// coordinates, then quantize each predictor/hypothesis separately.
uint32_t referenceBits(const Candidate &hypothesis, const Candidate &predictor,
                       const int affineMvCount, const int imv)
{
  uint32_t bits = 0;
  for (int p = 0; p < affineMvCount; p++)
  {
    const int adjustmentX = p ? hypothesis.mv[0].hor - predictor.mv[0].hor : 0;
    const int adjustmentY = p ? hypothesis.mv[0].ver - predictor.mv[0].ver : 0;
    const int predictedX = predictor.mv[p].hor + adjustmentX;
    const int predictedY = predictor.mv[p].ver + adjustmentY;
    bits += referenceComponentBits(referenceCoordinate(hypothesis.mv[p].hor, imv)
                                   - referenceCoordinate(predictedX, imv));
    bits += referenceComponentBits(referenceCoordinate(hypothesis.mv[p].ver, imv)
                                   - referenceCoordinate(predictedY, imv));
  }
  return bits;
}

bool equalActive(const Candidate &a, const Candidate &b, const int affineMvCount)
{
  for (int p = 0; p < affineMvCount; p++)
  {
    if (a.mv[p].hor != b.mv[p].hor || a.mv[p].ver != b.mv[p].ver)
    {
      return false;
    }
  }
  return true;
}

bool equalAll(const Candidate &a, const Candidate &b)
{
  return equalActive(a, b, 3);
}

std::vector<int> referenceOrder(const AffinePool &pool, const int size, const int affineMvCount, const int imv)
{
  std::vector<int> unique;
  for (int i = 0; i < size; i++)
  {
    bool duplicate = false;
    for (const int prior : unique)
    {
      duplicate |= equalActive(pool[i], pool[prior], affineMvCount);
    }
    if (!duplicate)
    {
      unique.push_back(i);
    }
  }
  int second = size > 1 ? 1 : 0;
  if (unique.size() > 1)
  {
    static constexpr int weights[] = { 64, 32, 16, 8, 4, 2, 1, 1 };
    uint64_t minimum = std::numeric_limits<uint64_t>::max();
    for (size_t j = 1; j < unique.size(); j++)
    {
      uint64_t score = 0;
      for (size_t k = 0; k < unique.size(); k++)
      {
        const uint32_t anchorBits = referenceBits(pool[unique[k]], pool[0], affineMvCount, imv);
        const uint32_t otherBits = referenceBits(pool[unique[k]], pool[unique[j]], affineMvCount, imv);
        score += uint64_t(weights[k]) * (anchorBits < otherBits ? anchorBits : otherBits);
      }
      if (score < minimum)
      {
        minimum = score;
        second = unique[j];
      }
    }
  }
  std::vector<int> order = { 0 };
  if (size > 1)
  {
    order.push_back(second);
  }
  for (int i = 1; i < size; i++)
  {
    if (i != second)
    {
      order.push_back(i);
    }
  }
  return order;
}

std::array<int, 8> check(const AffinePool &pool, const int size, const int affineMvCount, const int imv)
{
  const std::vector<int> expected = referenceOrder(pool, size, affineMvCount, imv);
  AffinePool result = pool;
  std::array<int, 8> indices;
  indices.fill(-1);
  AffineAmvpTmrSelector::reorder(pool.data(), size, affineMvCount, imv, result.data(), indices.data());
  for (int i = 0; i < size; i++)
  {
    require(indices[i] == expected[i], "Selector differs from independent exhaustive anchored search");
    require(equalAll(result[i], pool[expected[i]]), "Output candidate lost original slot/control-point mapping");
    for (int j = 0; j < size; j++)
    {
      require(AffineAmvpTmrSelector::estimateBits(pool[i], pool[j], affineMvCount, imv)
                == referenceBits(pool[i], pool[j], affineMvCount, imv),
              "Affine rate estimate differs from independent differential-CP reference");
    }
  }
  require(indices[0] == 0 && equalAll(result[0], pool[0]), "Original index-0 anchor moved");
  for (int i = size; i < 8; i++)
  {
    require(indices[i] == -1 && equalAll(result[i], pool[i]), "Output extends beyond the input count");
  }
  AffinePool inPlace = pool;
  std::array<int, 8> inPlaceIndices;
  inPlaceIndices.fill(-1);
  AffineAmvpTmrSelector::reorder(inPlace.data(), size, affineMvCount, imv, inPlace.data(), inPlaceIndices.data());
  require(inPlaceIndices == indices, "In-place index mapping differs");
  AffinePool withoutIndices = pool;
  AffineAmvpTmrSelector::reorder(pool.data(), size, affineMvCount, imv, withoutIndices.data());
  for (int i = 0; i < 8; i++)
  {
    require(equalAll(inPlace[i], result[i]) && equalAll(withoutIndices[i], result[i]),
            "Aliased output or optional diagnostic indices changed the result");
  }
  return indices;
}

Candidate translation(const Mv &mv)
{
  return Candidate{ { mv, mv, mv } };
}
}   // namespace

int main()
{
  try
  {
    const Candidate predictor = { { Mv(16, -8), Mv(32, 4), Mv(4, 24) } };
    Candidate shifted = predictor;
    for (Mv &mv : shifted.mv)
    {
      mv += Mv(64, -32);
    }
    for (const int cpCount : { 2, 3 })
    {
      for (int imv = 0; imv < 3; imv++)
      {
        const int dx = referenceCoordinate(shifted.mv[0].hor, imv) - referenceCoordinate(predictor.mv[0].hor, imv);
        const int dy = referenceCoordinate(shifted.mv[0].ver, imv) - referenceCoordinate(predictor.mv[0].ver, imv);
        const uint32_t expected = referenceComponentBits(dx) + referenceComponentBits(dy) + (cpCount - 1) * 2;
        require(AffineAmvpTmrSelector::estimateBits(shifted, predictor, cpCount, imv) == expected,
                "Common translation was charged independently for secondary control points");
      }
    }

    // Quantize AFTER composing CP1's predictor, not before. For imv=0,
    // Q(-3)=-1, Q(-4)=-1, Q(-6)=-1, but Q(-3)+Q(-3)=-2.
    const Candidate nonGridHypothesis = { { Mv(-3, 0), Mv(-4, 0), Mv() } };
    const Candidate nonGridPredictor = { { Mv(), Mv(-3, 0), Mv() } };
    require(AffineAmvpTmrSelector::estimateBits(nonGridHypothesis, nonGridPredictor, 2, 0) == 6,
            "Negative off-grid predictor composition/rounding order is incorrect");
    // Q(M)-Q(P) is not Q(M-P), including at signed half-way coordinates.
    require(AffineAmvpTmrSelector::estimateBits(translation(Mv(-3, 0)), translation(Mv(-2, 0)), 2, 0) == 6,
            "Rounded the differential instead of each source/predictor coordinate");

    const AffinePool example = { translation(Mv()), translation(Mv(4, 0)), translation(Mv(32, 0)), translation(Mv(36, 0)),
                           translation(Mv()), translation(Mv()), translation(Mv()), translation(Mv()) };
    for (const int cpCount : { 2, 3 })
    {
      const auto indices = check(example, 8, cpCount, 0);
      require(indices[1] == 2, "Lite failed to select the complementary translated affine model");
    }

    AffinePool same;
    same.fill(predictor);
    for (const int cpCount : { 2, 3 })
    {
      for (int imv = 0; imv < 3; imv++)
      {
        const auto indices = check(same, 8, cpCount, imv);
        for (int i = 0; i < 8; i++)
        {
          require(indices[i] == i, "All-duplicate fallback changed input order");
        }
      }
    }

    AffinePool lbOnly{};
    for (int i = 0; i < 8; i++)
    {
      lbOnly[i].mv[2] = Mv(i * 16, -i * 32);
    }
    const auto fourParamLbOrder = check(lbOnly, 8, 2, 0);
    for (int i = 0; i < 8; i++)
    {
      require(fourParamLbOrder[i] == i, "Four-parameter dedup incorrectly used inactive LB");
    }
    require(AffineAmvpTmrSelector::estimateBits(lbOnly[0], lbOnly[7], 2, 0) == 4,
            "Four-parameter rate used inactive LB");
    require(AffineAmvpTmrSelector::estimateBits(lbOnly[0], lbOnly[7], 3, 0) > 6,
            "Six-parameter rate ignored active LB");
    check(lbOnly, 8, 3, 0);

    AffinePool padding{};
    padding[0] = translation(Mv(64, -32));
    padding[1] = padding[0];
    for (const int cpCount : { 2, 3 })
    {
      require(check(padding, 8, cpCount, 0)[1] == 2,
              "Zero padding did not remain a selectable, singly weighted hypothesis");
    }

    // Distinct INTERNAL hypotheses round to the same coded coordinates, so
    // the strict objective tie must preserve the earliest input slot (1).
    AffinePool ties{};
    ties[0] = translation(Mv(1, 0));
    ties[1] = translation(Mv(2, 0));
    for (const int cpCount : { 2, 3 })
    {
      for (const int imv : { 0, 2 })
      {
        require(check(ties, 8, cpCount, imv)[1] == 1,
                "Stable tie or pre-AMVR INTERNAL deduplication semantics changed");
      }
    }

    std::mt19937 generator(32164231);
    int cases = 0;
    for (const int cpCount : { 2, 3 })
    {
      for (int imv = 0; imv < 3; imv++)
      {
        for (int size = 1; size <= 8; size++)
        {
          for (int trial = 0; trial < 500; trial++)
          {
            AffinePool pool{};
            for (int i = 0; i < size; i++)
            {
              const int range = trial % 2 == 0 ? 131072 : 8;
              for (Mv &mv : pool[i].mv)
              {
                mv = Mv(int(generator() % (2 * range)) - range, int(generator() % (2 * range)) - range);
              }
              if (i > 0 && generator() % 3 == 0)
              {
                pool[i] = pool[generator() % i];
                // Inactive LB must not prevent 4-parameter deduplication.
                if (cpCount == 2 && generator() % 2 == 0)
                {
                  pool[i].mv[2] = Mv(i + 1, -i - 1);
                }
              }
            }
            check(pool, size, cpCount, imv);
            cases++;
          }
        }
      }
    }
    std::cout << "PASS: affine 4/6-parameter differential-CP rate, all 3 AMVR precisions, negative rounding, "
                 "anchor/rank/zero-padding, inactive LB, strict ties, in-place mapping and "
              << cases << " independent randomized exhaustive comparisons\n";
  }
  catch (const std::exception &error)
  {
    std::cerr << "FAIL: " << error.what() << '\n';
    return 1;
  }
  return 0;
}
