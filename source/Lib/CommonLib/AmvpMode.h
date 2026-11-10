// Shared external AMVP experiment identifiers. Decimal labels are never
// represented as floating point or signalled in the bitstream.
#ifndef AMVP_MODE_H
#define AMVP_MODE_H

#include <string>

namespace AmvpMode
{
constexpr int TMR_LITE_AFTER_NO_ARMC  = 31; // external label 3.1
constexpr int TMR_LITE_BEFORE_NO_ARMC = 41; // external label 4.1
constexpr int TMR_FULL_AFTER_NO_ARMC  = 51; // external label 5.1
constexpr int TMR_FULL_BEFORE_NO_ARMC = 61; // external label 6.1

inline bool isTmrWithoutArmc(const int mode)
{
  return mode == TMR_LITE_AFTER_NO_ARMC || mode == TMR_LITE_BEFORE_NO_ARMC ||
         mode == TMR_FULL_AFTER_NO_ARMC || mode == TMR_FULL_BEFORE_NO_ARMC;
}

inline bool isSupported(const int mode) { return (mode >= -3 && mode <= 8) || isTmrWithoutArmc(mode); }
inline bool isReordering(const int mode) { return (mode >= 1 && mode <= 8) || isTmrWithoutArmc(mode); }
inline bool isBeforeMe(const int mode)
{
  return mode == 2 || mode == 4 || mode == 6 ||
         mode == TMR_LITE_BEFORE_NO_ARMC || mode == TMR_FULL_BEFORE_NO_ARMC;
}
inline bool isAfterMe(const int mode)
{
  return mode == 1 || mode == 3 || mode == 5 || mode == 7 || mode == 8 ||
         mode == TMR_LITE_AFTER_NO_ARMC || mode == TMR_FULL_AFTER_NO_ARMC;
}
inline bool isTmrLite(const int mode)
{
  return mode == 3 || mode == 4 || mode == TMR_LITE_AFTER_NO_ARMC || mode == TMR_LITE_BEFORE_NO_ARMC;
}
inline bool isTmrFull(const int mode)
{
  return mode == 5 || mode == 6 || mode == TMR_FULL_AFTER_NO_ARMC || mode == TMR_FULL_BEFORE_NO_ARMC;
}
// Whether candidate reordering uses ARMC's reconstructed boundary templates.
// Ordinary encoder ME preselection is separate and is not controlled here.
inline bool usesTemplate(const int mode) { return mode >= 1 && mode <= 6; }

inline std::string name(const int mode)
{
  switch (mode)
  {
  case TMR_LITE_AFTER_NO_ARMC:  return "3.1";
  case TMR_LITE_BEFORE_NO_ARMC: return "4.1";
  case TMR_FULL_AFTER_NO_ARMC:  return "5.1";
  case TMR_FULL_BEFORE_NO_ARMC: return "6.1";
  default: return std::to_string(mode);
  }
}

// Strictly parse public labels: never truncate 3.1 to 3, and never accept the
// private 31/41/51/61 values as alternative user-facing mode numbers.
inline bool parse(const std::string &text, int &mode)
{
  const auto first = text.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) { return false; }
  const auto last = text.find_last_not_of(" \t\r\n");
  const std::string value = text.substr(first, last - first + 1);
  if (value == "3.1") { mode = TMR_LITE_AFTER_NO_ARMC; return true; }
  if (value == "4.1") { mode = TMR_LITE_BEFORE_NO_ARMC; return true; }
  if (value == "5.1") { mode = TMR_FULL_AFTER_NO_ARMC; return true; }
  if (value == "6.1") { mode = TMR_FULL_BEFORE_NO_ARMC; return true; }

  std::string::size_type idx = 0;
  int sign = 1;
  if (value[idx] == '-' || value[idx] == '+')
  {
    sign = value[idx++] == '-' ? -1 : 1;
  }
  if (idx == value.size()) { return false; }
  int number = 0;
  for (; idx < value.size(); ++idx)
  {
    if (value[idx] < '0' || value[idx] > '9' || number > 8) { return false; }
    number = number * 10 + value[idx] - '0';
  }
  number *= sign;
  if (number < -3 || number > 8) { return false; }
  mode = number;
  return true;
}

inline const char *supportedLabels() { return "-3, -2, -1, 0, 1, 2, 3, 3.1, 4, 4.1, 5, 5.1, 6, 6.1, 7 or 8"; }
} // namespace AmvpMode

#endif // AMVP_MODE_H
