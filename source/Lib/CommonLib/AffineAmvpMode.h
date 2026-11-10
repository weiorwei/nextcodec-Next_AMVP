// Independent external affine-AMVP experiment identifiers. Decimal labels are
// parsed as text, never stored as floating point or signalled in the bitstream.
#ifndef AFFINE_AMVP_MODE_H
#define AFFINE_AMVP_MODE_H

#include <string>

namespace AffineAmvpMode
{
constexpr int DISABLED          = 0;
constexpr int TMR_LITE_BEFORE_ME = 32; // external label 3.2
constexpr int TMR_LITE_AFTER_ME  = 42; // external label 4.2

inline bool isSupported(const int mode)
{
  return mode == DISABLED || mode == TMR_LITE_BEFORE_ME || mode == TMR_LITE_AFTER_ME;
}

inline bool isBeforeMe(const int mode) { return mode == TMR_LITE_BEFORE_ME; }
inline bool isAfterMe(const int mode) { return mode == TMR_LITE_AFTER_ME; }

inline std::string name(const int mode)
{
  switch (mode)
  {
  case TMR_LITE_BEFORE_ME: return "3.2";
  case TMR_LITE_AFTER_ME:  return "4.2";
  default: return std::to_string(mode);
  }
}

// Accept only the public spellings, apart from surrounding configuration-file
// whitespace. In particular, reject private integer IDs and truncated labels.
inline bool parse(const std::string &text, int &mode)
{
  const auto first = text.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) { return false; }
  const auto last = text.find_last_not_of(" \t\r\n");
  const std::string value = text.substr(first, last - first + 1);
  if (value == "0")   { mode = DISABLED; return true; }
  if (value == "3.2") { mode = TMR_LITE_BEFORE_ME; return true; }
  if (value == "4.2") { mode = TMR_LITE_AFTER_ME; return true; }
  return false;
}

inline const char *supportedLabels() { return "0, 3.2 or 4.2"; }
} // namespace AffineAmvpMode

#endif // AFFINE_AMVP_MODE_H
