// Standalone regression test: g++ -std=c++11 -Isource/Lib tools/test_amvp_mode.cpp -o /tmp/test_amvp_mode
#include "CommonLib/AmvpMode.h"

#include <cstdlib>
#include <iostream>
#include <string>

namespace
{
void require(const bool condition, const char *message)
{
  if (!condition)
  {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(EXIT_FAILURE);
  }
}
}

int main()
{
  const int modes[] = { -3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 31, 41, 51, 61 };
  const char *labels[] = { "-3", "-2", "-1", "0", "1", "2", "3", "4", "5", "6", "7", "8",
                          "3.1", "4.1", "5.1", "6.1" };
  for (int i = 0; i < 16; ++i)
  {
    int parsed = -999;
    require(AmvpMode::isSupported(modes[i]), "supported internal mode");
    require(AmvpMode::name(modes[i]) == labels[i], "public label formatting");
    require(AmvpMode::parse(labels[i], parsed) && parsed == modes[i], "public label parsing");
    require(AmvpMode::isReordering(modes[i]) == (modes[i] > 0), "positive-mode reordering");
    require(AmvpMode::isBeforeMe(modes[i]) != AmvpMode::isAfterMe(modes[i]) || modes[i] <= 0,
            "exactly one timing branch for each reordering mode");
    require(AmvpMode::usesTemplate(modes[i]) == (modes[i] >= 1 && modes[i] <= 6),
            "boundary-template use limited to original modes 1..6");
  }
  require(AmvpMode::isTmrLite(3) && AmvpMode::isTmrLite(4) && AmvpMode::isTmrLite(31) &&
          AmvpMode::isTmrLite(41), "Lite modes");
  require(AmvpMode::isTmrFull(5) && AmvpMode::isTmrFull(6) && AmvpMode::isTmrFull(51) &&
          AmvpMode::isTmrFull(61), "Full modes");
  require(AmvpMode::isAfterMe(31) && AmvpMode::isAfterMe(51) && AmvpMode::isBeforeMe(41) &&
          AmvpMode::isBeforeMe(61), "new mode timing");
  for (const char *invalid : { "", " ", "9", "-4", "31", "41", "51", "61", "3.10", "4.0", "3.11",
                               "3.1junk", "3x", "3e0", "+3.1", "-3.1", "+", "3 1",
                               "99999999999999999999999999999" })
  {
    int parsed = 123;
    require(!AmvpMode::parse(invalid, parsed) && parsed == 123, "reject malformed labels without mutation");
  }
  int parsed = -999;
  require(AmvpMode::parse(" \t3.1\r\n", parsed) && parsed == 31, "trim configuration whitespace");
  require(AmvpMode::parse("+3", parsed) && parsed == 3, "legacy positive integer sign");
  require(AmvpMode::parse("0003", parsed) && parsed == 3, "legacy integer leading zeros");
  require(!AmvpMode::isSupported(9) && !AmvpMode::isSupported(32), "reject unsupported internal modes");
  std::cout << "PASS: AMVP mode label parsing, formatting, dispatch and invalid input checks\n";
  return EXIT_SUCCESS;
}
