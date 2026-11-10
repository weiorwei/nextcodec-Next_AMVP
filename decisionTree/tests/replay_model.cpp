// Independent cross-language test entry point for the deployed integer tree.
// With a file argument, read packed training records and emit one profile byte
// per record. Otherwise, read twelve integer features per line from stdin.
#include "CommonLib/AmvpDecisionTree.h"

#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace
{
int32_t signedLittleEndian32(const unsigned char *bytes)
{
  const uint32_t value = uint32_t(bytes[0]) | uint32_t(bytes[1]) << 8 |
                         uint32_t(bytes[2]) << 16 | uint32_t(bytes[3]) << 24;
  return value < 0x80000000u ? int32_t(value) : int32_t(int64_t(value) - 0x100000000LL);
}
}

int main(int argc, char **argv)
{
  try
  {
    if (argc > 2) { throw std::runtime_error("Usage: replay_model [records.bin|--model-sha]"); }
    if (argc == 2 && std::string(argv[1]) == "--model-sha")
    {
      std::cout << AmvpDecisionTreeModel::modelSha256 << '\n';
      return std::cout ? 0 : 1;
    }
    if (argc == 2)
    {
      std::ifstream input(argv[1], std::ios::binary);
      if (!input) { throw std::runtime_error("Cannot read packed records"); }
      std::array<unsigned char, 76> bytes;
      uint64_t count = 0;
      while (input.read(reinterpret_cast<char *>(bytes.data()), bytes.size()))
      {
        AmvpDecisionTree::Features features;
        for (int i = 0; i < AmvpDecisionTree::numFeatures; ++i)
        {
          features[i] = signedLittleEndian32(bytes.data() + i * 4);
        }
        std::cout.put(char(AmvpDecisionTree::predictProfile(features)));
        ++count;
      }
      if (!input.eof() || input.gcount() != 0)
      {
        throw std::runtime_error("Truncated or unreadable packed record");
      }
      std::cerr << "C++ replayed " << count << " packed records\n";
    }
    else
    {
      AmvpDecisionTree::Features features;
      while (std::cin >> features[0])
      {
        for (int i = 1; i < AmvpDecisionTree::numFeatures; ++i)
        {
          if (!(std::cin >> features[i])) { throw std::runtime_error("Incomplete feature vector"); }
        }
        std::cout << AmvpDecisionTree::predictProfile(features) << '\n';
      }
      if (!std::cin.eof()) { throw std::runtime_error("Malformed feature input"); }
    }
  }
  catch (const std::exception &error)
  {
    std::cerr << "FAIL: " << error.what() << '\n';
    return 1;
  }
  return std::cout ? 0 : 1;
}
