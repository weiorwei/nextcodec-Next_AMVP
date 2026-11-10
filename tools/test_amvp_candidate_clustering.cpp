// Standalone tests: no pictures, codec state, or linked codec library required.
// g++ -std=c++17 -O2 -Isource/Lib tools/test_amvp_candidate_clustering.cpp -o /tmp/amvp_cluster_test
#include "CommonLib/AmvpCandidateClustering.h"

#include <array>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>

namespace
{
using MotionPool = std::array<Mv, AMVP_ARMC_MAX_NUM_CANDS>;
using Result = AmvpTraceClustering::Result;

void require(const bool condition, const char *message)
{
  if (!condition)
  {
    throw std::runtime_error(message);
  }
}

template<typename F> void requireInvalid(F operation)
{
  bool rejected = false;
  try
  {
    operation();
  }
  catch (const std::exception &)
  {
    rejected = true;
  }
  require(rejected, "Invalid input was not rejected");
}

int64_t distance(const Mv &a, const Mv &b)
{
  return std::max(std::abs(int64_t(a.hor) - b.hor), std::abs(int64_t(a.ver) - b.ver));
}

// Independent representation: clusters contain ORIGINAL pool slots, including
// duplicates. Re-sort clusters by their minimum slot after every merge.
Result reference(const MotionPool &pool, const int size, const int threshold)
{
  Result result;
  std::vector<int> first;
  std::vector<std::vector<int>> clusters;
  for (int slot = 0; slot < size; slot++)
  {
    int id = 0;
    while (id < int(first.size()) && pool[first[id]] != pool[slot])
    {
      id++;
    }
    if (id == int(first.size()))
    {
      first.push_back(slot);
      clusters.push_back({});
    }
    result.unique[slot] = id;
    clusters[id].push_back(slot);
  }
  result.numUnique = int(first.size());
  for (;;)
  {
    int bestFirst = -1;
    int bestSecond = -1;
    int64_t bestDistance = std::numeric_limits<int64_t>::max();
    for (int i = 0; i < int(clusters.size()); i++)
    {
      for (int j = i + 1; j < int(clusters.size()); j++)
      {
        int64_t d = 0;
        for (const int a : clusters[i])
        {
          for (const int b : clusters[j])
          {
            d = std::max(d, distance(pool[a], pool[b]));
          }
        }
        if (d <= threshold && d < bestDistance)
        {
          bestDistance = d;
          bestFirst = i;
          bestSecond = j;
        }
      }
    }
    if (bestFirst < 0)
    {
      break;
    }
    clusters[bestFirst].insert(clusters[bestFirst].end(), clusters[bestSecond].begin(), clusters[bestSecond].end());
    std::sort(clusters[bestFirst].begin(), clusters[bestFirst].end());
    clusters.erase(clusters.begin() + bestSecond);
    std::sort(clusters.begin(), clusters.end(), [](const std::vector<int> &a, const std::vector<int> &b) {
      return a.front() < b.front();
    });
  }
  result.numClusters = int(clusters.size());
  for (int id = 0; id < result.numClusters; id++)
  {
    for (const int slot : clusters[id])
    {
      result.cluster[slot] = id;
    }
  }
  return result;
}

void equal(const Result &a, const Result &b, const int size)
{
  require(a.numClusters == b.numClusters, "Cluster count differs");
  require(a.numUnique == b.numUnique, "Unique count differs");
  for (int i = 0; i < size; i++)
  {
    require(a.cluster[i] == b.cluster[i], "Stable cluster ID differs");
    require(a.unique[i] == b.unique[i], "Stable unique ID differs");
  }
}

Result check(const MotionPool &pool, const int size, const int threshold)
{
  const Result result = AmvpTraceClustering::clusterCandidates(pool.data(), size, threshold);
  equal(result, reference(pool, size, threshold), size);
  equal(result, AmvpTraceClustering::clusterCandidates(pool.data(), size, threshold), size);
  int lastFirst = -1;
  for (int cluster = 0; cluster < result.numClusters; cluster++)
  {
    int first = size;
    for (int i = 0; i < size; i++)
    {
      if (result.cluster[i] == cluster)
      {
        first = std::min(first, i);
        for (int j = 0; j < size; j++)
        {
          if (result.cluster[j] == cluster)
          {
            require(distance(pool[i], pool[j]) <= threshold, "Cluster exceeds complete-link diameter bound");
          }
        }
      }
    }
    require(first > lastFirst && first < size, "Cluster ordering or contiguous IDs are incorrect");
    lastFirst = first;
  }
  return result;
}
}   // namespace

int main()
{
  try
  {
    const MotionPool zeros{};
    requireInvalid([&] { AmvpTraceClustering::clusterCandidates(nullptr, 8, 16); });
    requireInvalid([&] { AmvpTraceClustering::clusterCandidates(zeros.data(), 0, 16); });
    requireInvalid([&] { AmvpTraceClustering::clusterCandidates(zeros.data(), 9, 16); });
    requireInvalid([&] { AmvpTraceClustering::clusterCandidates(zeros.data(), 8, -1); });
    require(check(zeros, 8, 0).numUnique == 1, "Duplicate zero slots are not deduplicated");
    require(check(zeros, 1, 16).numClusters == 1, "Single-candidate input failed");
    const MotionPool duplicates = { Mv(32, -16), Mv(), Mv(32, -16), Mv(), Mv(160, 16), Mv(), Mv(), Mv() };
    const Result exact = check(duplicates, 8, 0);
    require(exact.numUnique == 3 && exact.numClusters == 3, "Threshold zero must only merge exact duplicates");
    require(exact.unique[0] == 0 && exact.unique[1] == 1 && exact.unique[4] == 2, "Unique IDs are not pool-stable");
    require(exact.cluster[7] == exact.cluster[1], "Padding zero does not share the zero-MV cluster");

    const MotionPool chain = { Mv(0, 0), Mv(16, 0), Mv(32, 0), Mv(), Mv(), Mv(), Mv(), Mv() };
    const Result tied = check(chain, 3, 16);
    require(tied.numClusters == 2 && tied.cluster[0] == tied.cluster[1] && tied.cluster[1] != tied.cluster[2],
            "Complete-link chain or earliest-pair tie handling failed");
    const MotionPool permuted = { Mv(32, 0), Mv(16, 0), Mv(0, 0), Mv(), Mv(), Mv(), Mv(), Mv() };
    require(check(permuted, 3, 16).cluster[0] == check(permuted, 3, 16).cluster[1], "Tie uses MV order, not pool order");
    const MotionPool square = { Mv(0, 0), Mv(16, 16), Mv(-16, -16), Mv(), Mv(), Mv(), Mv(), Mv() };
    require(check(square, 3, 16).numClusters == 2, "L-infinity diagonal distance is wrong");
    require(check(square, 3, 32).numClusters == 1, "Negative MV handling failed");

    MotionPool separated;
    for (int i = 0; i < 8; i++)
    {
      separated[i] = Mv(i * 32, -i * 32);
    }
    require(check(separated, 8, 16).numClusters == 8, "Eight separated points merged");
    require(check(separated, 8, 224).numClusters == 1, "Eight close points did not fully merge");
    const MotionPool extreme = { Mv(std::numeric_limits<int>::min(), 0), Mv(std::numeric_limits<int>::max(), 0),
                           Mv(0, std::numeric_limits<int>::min()), Mv(0, std::numeric_limits<int>::max()),
                           Mv(), Mv(), Mv(), Mv() };
    require(check(extreme, 4, std::numeric_limits<int>::max()).numClusters == 3, "Signed distance overflow");

    std::mt19937 random(20260921);
    const int thresholds[] = { 0, 1, 4, 8, 16, 32, 64, 256 };
    int cases = 0;
    for (int size = 1; size <= 8; size++)
    {
      for (int trial = 0; trial < 1000; trial++)
      {
        MotionPool pool{};
        for (int i = 0; i < size; i++)
        {
          pool[i] = Mv(int(random() % 129) - 64, int(random() % 129) - 64);
          if (i > 0 && random() % 3 == 0)
          {
            pool[i] = pool[random() % i];
          }
        }
        Result previous = check(pool, size, 0);
        for (const int threshold : thresholds)
        {
          const Result current = check(pool, size, threshold);
          require(current.numClusters <= previous.numClusters, "Increasing threshold increased cluster count");
          for (int i = 0; i < size; i++)
          {
            for (int j = 0; j < size; j++)
            {
              if (previous.cluster[i] == previous.cluster[j])
              {
                require(current.cluster[i] == current.cluster[j], "Increasing threshold split an existing cluster");
              }
            }
          }
          previous = current;
          cases++;
        }
      }
    }
    std::cout << "PASS: edge cases and " << cases
              << " randomized clustering comparisons, diameter, determinism, and threshold nesting checks\n";
  }
  catch (const std::exception &error)
  {
    std::cerr << "FAIL: " << error.what() << '\n';
    return 1;
  }
  return 0;
}
