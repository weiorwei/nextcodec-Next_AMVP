#include "CommonLib/AffineAmvpMode.h"
#include "CommonLib/AmvpMode.h"

#include <iostream>
#include <stdexcept>
#include <string>

namespace
{
void require(const bool condition, const char *message)
{
  if (!condition) { throw std::runtime_error(message); }
}
}

int main()
{
  using namespace AffineAmvpMode;
  try
  {
    const int values[] = { DISABLED, TMR_LITE_BEFORE_ME, TMR_LITE_AFTER_ME };
    const std::string names[] = { "0", "3.2", "4.2" };
    for (int idx = 0; idx < 3; ++idx)
    {
      int parsed = -999;
      require(isSupported(values[idx]), "Public affine mode not supported");
      require(name(values[idx]) == names[idx], "Wrong affine mode label");
      require(parse(names[idx], parsed) && parsed == values[idx], "Affine mode roundtrip failed");
      require(parse(" \t" + names[idx] + "\r\n", parsed) && parsed == values[idx], "Whitespace trim failed");
      require(isBeforeMe(parsed) == (idx == 1), "Wrong before-ME predicate");
      require(isAfterMe(parsed) == (idx == 2), "Wrong after-ME predicate");
    }

    const std::string invalid[] = {
      "", " ", "\t\r\n", "3", "4", "32", "42", "03.2", "3.20", "4.20", "3.1", "4.1",
      "-1", "-0", "+0", "00", "0.0", "NaN", "nan", "inf", "3.2junk", "3.2 4.2", "3 .2",
      "99999999999999999999999999999999999999999999999999999999999999999999"
    };
    for (const auto &value : invalid)
    {
      int parsed = -999;
      require(!parse(value, parsed), "Invalid affine mode accepted");
      require(parsed == -999, "Rejected affine mode changed configuration");
    }
    for (int value = -100; value <= 100; ++value)
    {
      require(isSupported(value) == (value == DISABLED || value == TMR_LITE_BEFORE_ME || value == TMR_LITE_AFTER_ME),
              "Unexpected supported internal affine mode");
    }

    // The translational experiment parser must remain independent: the new
    // affine labels cannot silently turn into ordinary modes 3 or 4.
    int translation = 0;
    require(!AmvpMode::parse("3.2", translation), "Affine 3.2 leaked into translational parser");
    require(!AmvpMode::parse("4.2", translation), "Affine 4.2 leaked into translational parser");
    require(AmvpMode::parse("3.1", translation) && translation == AmvpMode::TMR_LITE_AFTER_NO_ARMC,
            "Translational decimal parser changed");
    require(AmvpMode::parse("-3", translation) && translation == -3, "Translational oracle parser changed");
    std::cout << "AffineAmvpMode parse/name/predicate/independence tests passed\n";
    return 0;
  }
  catch (const std::exception &error)
  {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
