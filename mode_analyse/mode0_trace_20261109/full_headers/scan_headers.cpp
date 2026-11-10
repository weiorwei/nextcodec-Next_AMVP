// Exact streaming label/structure census. Does not validate 32-dimensional features.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <regex>
#include <stdexcept>
#include <string>
#include <vector>
namespace fs = std::filesystem;
using I = int64_t;
using U = uint64_t;
using Vec = std::array<I, 2>;

static const char *field(const std::string &line, const char *name)
{
  const std::string key = std::string(" ") + name + "=";
  const auto offset = line.find(key);
  if (offset == std::string::npos) { throw std::runtime_error(std::string("missing_") + name); }
  return line.c_str() + offset + key.size();
}
static I integer(const char *s, const std::string &what)
{
  char *end = nullptr;
  const auto value = std::strtoll(s, &end, 10);
  if (end == s) { throw std::runtime_error("invalid_" + what); }
  return value;
}
static I number(const std::string &line, const char *name) { return integer(field(line, name), name); }
static std::string token(const std::string &line, const char *name)
{
  const auto *begin = field(line, name);
  const auto *end = begin;
  while (*end && *end != ' ' && *end != '\r' && *end != '\n') { ++end; }
  return std::string(begin, end);
}
static Vec vector(const std::string &line, const char *name)
{
  const auto *s = field(line, name);
  if (*s++ != '(') { throw std::runtime_error("invalid_vector"); }
  char *end = nullptr;
  const auto x = std::strtoll(s, &end, 10);
  if (end == s || *end++ != ',') { throw std::runtime_error("invalid_vector"); }
  s = end;
  const auto y = std::strtoll(s, &end, 10);
  if (end == s || *end != ')') { throw std::runtime_error("invalid_vector"); }
  return {x, y};
}
static I bits(I delta)
{
  const U absolute = delta < 0 ? U(-(delta + 1)) + 1 : U(delta);
  if (absolute > (U(1) << 40)) { throw std::runtime_error("unreasonable_mv_difference"); }
  U code = 2 * absolute + 1;
  I log = 0;
  while (code >>= 1) { ++log; }
  return 1 + 2 * log;
}
static I rate(Vec a, Vec b) { return bits(a[0] - b[0]) + bits(a[1] - b[1]); }
static void require(bool condition, const char *why)
{
  if (!condition) { throw std::runtime_error(why); }
}

struct Query
{
  I id = 0, jb = 0, actual = 0, oracle = 0, idx = 0, idx0bits = 0, idx1bits = 0;
  I imv = 0, list = 0, temporal = 0, expectedRaw = 0, expectedCand = 0;
  I raw = 0, cand = 0, computedOracle = 0, rate0 = 0, rate1 = 0, qp = 0;
  Vec p0{}, b1{}, mv{}, predictor{};
  bool ordinary = false, active = false, valid = true;
};
struct Stats
{
  U queries = 0, ordinary = 0, constrained = 0, candidates = 0, raw = 0;
  I jb = 0, actual = 0, oracle = 0, gain = 0, actualMinusJb = 0;
  U oracleImproved = 0, p0EqualB1 = 0, p0Better = 0, tied = 0, b1Better = 0;
  U idx0 = 0, idx1 = 0, actualVsJbMismatch = 0, actualAboveJb = 0, actualBelowJb = 0;
  std::map<I, U> gainHistogram, candidateHistogram;
  void add(const Query &q)
  {
    ++queries;
    if (!q.ordinary) { ++constrained; return; }
    ++ordinary;
    candidates += q.cand;
    raw += q.raw;
    jb += q.jb; actual += q.actual; oracle += q.oracle; gain += q.jb - q.oracle;
    actualMinusJb += q.actual - q.jb;
    oracleImproved += q.oracle < q.jb;
    p0EqualB1 += q.p0 == q.b1;
    p0Better += q.rate0 < q.rate1; tied += q.rate0 == q.rate1; b1Better += q.rate1 < q.rate0;
    idx0 += q.idx == 0; idx1 += q.idx == 1;
    actualVsJbMismatch += q.actual != q.jb;
    actualAboveJb += q.actual > q.jb; actualBelowJb += q.actual < q.jb;
    ++gainHistogram[q.jb - q.oracle];
    ++candidateHistogram[q.expectedCand];
  }
};

static std::string csv(std::string value)
{
  std::string out = "\"";
  for (char c : value) { out += c == '"' ? "\"\"" : std::string(1, c); }
  return out + "\"";
}
int main(int argc, char **argv)
{
  if (argc != 3) { std::cerr << "usage: scan_headers INPUT_DIRECTORY OUTPUT_DIRECTORY\n"; return 1; }
  require(bits(0) == 1 && bits(1) == 3 && bits(-1) == 3 && bits(2) == 5 && bits(4) == 7,
          "selftest_bits");
  const fs::path input(argv[1]), output(argv[2]);
  fs::create_directories(output);
  std::vector<fs::path> files;
  for (const auto &entry : fs::recursive_directory_iterator(input))
  {
    const auto name = entry.path().filename().string();
    if (entry.is_regular_file() && name.size() > 8 && name.substr(name.size() - 8) == "_enc.log")
    { files.push_back(entry.path()); }
  }
  std::sort(files.begin(), files.end());
  std::map<std::pair<std::string, std::string>, Stats> grouped;
  std::map<std::string, U> audit;
  std::ofstream manifest(output / "files.csv");
  manifest << "file,bytes_before,bytes_after,mtime_before,mtime_after,changed,queries_started,queries_accepted,ends,candidate_rows,raw_rows,skip_rows,schemas,audit_events,last_query_id,last_end_id\n";
  U bytesTotal = 0, queriesTotal = 0, endsTotal = 0, candidatesTotal = 0, rawTotal = 0, skipsTotal = 0;
  U changedFiles = 0, schemaTotal = 0, auditTotal = 0;
  const auto started = std::chrono::steady_clock::now();
  const std::regex filenamePattern("^(.*)_([0-9]+)_([0-9]+)_enc\\.log$");
  for (size_t fileNo = 0; fileNo < files.size(); ++fileNo)
  {
    const auto &path = files[fileNo];
    const auto bytesBefore = fs::file_size(path);
    const auto mtimeBefore = fs::last_write_time(path).time_since_epoch().count();
    std::smatch match;
    const auto filename = path.filename().string();
    require(std::regex_match(filename, match, filenamePattern), "filename_not_recognized");
    const auto sequence = match[1].str(), baseQp = match[2].str();
    U queries = 0, accepted = 0, ends = 0, candidates = 0, raw = 0, skips = 0, schemas = 0, errors = 0;
    I lastQuery = 0, lastEnd = 0;
    Query q;
    const auto error = [&](const std::string &why) { ++audit[why]; ++errors; q.valid = false; };
    std::array<char, 1048576> buffer;
    std::ifstream stream;
    stream.rdbuf()->pubsetbuf(buffer.data(), buffer.size());
    stream.open(path);
    require(bool(stream), "cannot_open_input");
    std::string line;
    while (std::getline(stream, line))
    {
      if (line.compare(0, 12, "[AMVP-STATS-") != 0) { continue; }
      try
      {
        if (line.compare(0, 18, "[AMVP-STATS-QUERY]") == 0)
        {
          if (q.active) { error("unterminated_query"); }
          q = Query{}; q.active = true; ++queries;
          q.id = number(line, "QUERY_ID");
          require(q.id == lastQuery + 1, "non_dense_query_id"); lastQuery = q.id;
          require(number(line, "VERSION") == 1 && number(line, "MODE") == 0, "version_or_mode");
          require(token(line, "STAGE") == "FINAL" && token(line, "MV_ORIGIN") == "FINAL_CODED", "not_final");
          require(number(line, "OUTPUT_SAMPLE_PERIOD") == 1 && number(line, "OUTPUT_SAMPLE_SEED") == 0,
                  "unexpected_output_sampling");
          const auto label = token(line, "LABEL_KIND");
          require(label == "ORDINARY" || label == "CONSTRAINED", "unknown_label_kind");
          q.ordinary = label == "ORDINARY";
          q.jb = number(line, "JB_EST"); q.actual = number(line, "ACTUAL_EST");
          q.oracle = number(line, "ORACLE_EST"); q.idx = number(line, "ACTUAL_IDX");
          q.idx0bits = number(line, "IDX0_BITS"); q.idx1bits = number(line, "IDX1_BITS");
          q.imv = number(line, "IMV"); q.temporal = number(line, "TLAYER"); q.qp = number(line, "QP");
          const auto ref = token(line, "REF");
          require(ref.size() >= 5 && ref[0] == 'L' && (ref[1] == '0' || ref[1] == '1'), "invalid_ref");
          q.list = ref[1] - '0';
          q.expectedRaw = number(line, "RAW_COUNT"); q.expectedCand = number(line, "CAND_COUNT");
          require(q.idx >= 0 && q.idx <= 1 && q.imv >= 0 && q.imv <= 3, "invalid_idx_or_imv");
          require(q.expectedRaw >= 1 && q.expectedRaw <= 15 && q.expectedCand >= 1 && q.expectedCand <= 16,
                  "invalid_group_sizes");
          q.p0 = vector(line, "P0"); q.b1 = vector(line, "B1"); q.mv = vector(line, "FINAL_MV");
          q.predictor = vector(line, "ACTUAL_MVP");
          q.rate0 = rate(q.mv, q.p0) + q.idx0bits; q.rate1 = rate(q.mv, q.b1) + q.idx1bits;
          require(q.jb == std::min(q.rate0, q.rate1), "header_baseline_rate_mismatch");
          require(q.actual == rate(q.mv, q.predictor) + (q.idx == 0 ? q.idx0bits : q.idx1bits),
                  "header_actual_rate_mismatch");
          require(q.predictor == (q.idx == 0 ? q.p0 : q.b1), "actual_predictor_not_formal_slot");
          require(q.oracle <= q.jb && q.oracle >= 2, "invalid_oracle_rate");
          q.computedOracle = q.jb;
        }
        else if (line.compare(0, 16, "[AMVP-STATS-RAW]") == 0)
        {
          ++raw;
          require(q.active, "raw_without_query");
          require(number(line, "QUERY_ID") == q.id && number(line, "RID") == q.raw, "raw_id_mismatch");
          ++q.raw;
        }
        else if (line.compare(0, 17, "[AMVP-STATS-CAND]") == 0)
        {
          ++candidates;
          require(q.active, "candidate_without_query");
          require(number(line, "QUERY_ID") == q.id && number(line, "CID") == q.cand, "candidate_id_mismatch");
          const auto candidate = vector(line, "MV");
          if (q.cand == 0) { require(candidate == q.b1, "cid0_not_baseline_b1"); }
          const I jc = std::min(q.rate0, rate(q.mv, candidate) + q.idx1bits);
          require(number(line, "JB_EST") == q.jb && number(line, "JC_EST") == jc &&
                  number(line, "GAIN_EST") == q.jb - jc, "candidate_label_mismatch");
          q.computedOracle = std::min(q.computedOracle, jc);
          ++q.cand;
        }
        else if (line.compare(0, 16, "[AMVP-STATS-END]") == 0)
        {
          ++ends;
          require(q.active, "end_without_query");
          require(number(line, "QUERY_ID") == q.id, "end_id_mismatch");
          lastEnd = q.id;
          require(number(line, "RAW_COUNT") == q.raw && number(line, "CAND_COUNT") == q.cand &&
                  q.raw == q.expectedRaw && q.cand == q.expectedCand, "end_count_mismatch");
          require(q.oracle == q.computedOracle, "oracle_body_min_mismatch");
          if (q.valid)
          {
            ++accepted;
            grouped[{"ALL", "ALL"}].add(q);
            grouped[{"sequence", sequence}].add(q);
            grouped[{"base_qp", baseQp}].add(q);
            grouped[{"imv", std::to_string(q.imv)}].add(q);
            grouped[{"target_list", std::to_string(q.list)}].add(q);
            grouped[{"temporal_layer", std::to_string(q.temporal)}].add(q);
            grouped[{"sequence_base_qp", sequence + "|" + baseQp}].add(q);
          }
          q.active = false;
        }
        else if (line.compare(0, 17, "[AMVP-STATS-SKIP]") == 0) { ++skips; }
        else if (line.compare(0, 19, "[AMVP-STATS-SCHEMA]") == 0)
        {
          ++schemas;
          require(number(line, "VERSION") == 1 && number(line, "FEATURES") == 32 &&
                  token(line, "STAGE") == "FINAL", "unsupported_schema");
        }
      }
      catch (const std::exception &exception) { error(exception.what()); }
    }
    if (q.active) { error("unterminated_query_at_eof"); }
    require(stream.eof(), "input_io_failure");
    const auto bytesAfter = fs::file_size(path);
    const auto mtimeAfter = fs::last_write_time(path).time_since_epoch().count();
    const bool changed = bytesAfter != bytesBefore || mtimeAfter != mtimeBefore;
    changedFiles += changed;
    manifest << csv(path.string()) << ',' << bytesBefore << ',' << bytesAfter << ',' << mtimeBefore << ','
             << mtimeAfter << ',' << changed << ',' << queries << ',' << accepted << ',' << ends << ','
             << candidates << ',' << raw << ',' << skips << ',' << schemas << ',' << errors << ','
             << lastQuery << ',' << lastEnd << '\n';
    manifest.flush();
    bytesTotal += bytesBefore; queriesTotal += queries; endsTotal += ends;
    candidatesTotal += candidates; rawTotal += raw; skipsTotal += skips; schemaTotal += schemas; auditTotal += errors;
    if ((fileNo + 1) % 25 == 0 || fileNo + 1 == files.size())
    {
      std::cerr << "files=" << fileNo + 1 << '/' << files.size() << " bytes=" << bytesTotal
                << " queries=" << queriesTotal << " audit=" << auditTotal << '\n';
    }
  }
  std::ofstream totals(output / "totals.csv");
  totals << "group_kind,group,queries,ordinary,constrained,candidate_rows_ordinary,raw_rows_ordinary,baseline_sum_bits,actual_sum_bits,oracle_sum_bits,gain_sum_bits,oracle_improved,p0_equal_b1,p0_better,tied,b1_better,actual_idx0,actual_idx1,actual_vs_baseline_mismatch,actual_above_baseline,actual_below_baseline,actual_minus_baseline_sum\n";
  std::ofstream histogram(output / "histograms.csv");
  histogram << "group_kind,group,histogram,value,count\n";
  for (const auto &[key, s] : grouped)
  {
    totals << csv(key.first) << ',' << csv(key.second) << ',' << s.queries << ',' << s.ordinary << ','
           << s.constrained << ',' << s.candidates << ',' << s.raw << ',' << s.jb << ',' << s.actual << ','
           << s.oracle << ',' << s.gain << ',' << s.oracleImproved << ',' << s.p0EqualB1 << ','
           << s.p0Better << ',' << s.tied << ',' << s.b1Better << ',' << s.idx0 << ',' << s.idx1 << ','
           << s.actualVsJbMismatch << ',' << s.actualAboveJb << ',' << s.actualBelowJb << ','
           << s.actualMinusJb << '\n';
    for (const auto &[value, count] : s.gainHistogram)
    { histogram << csv(key.first) << ',' << csv(key.second) << ",oracle_gain_bits," << value << ',' << count << '\n'; }
    for (const auto &[value, count] : s.candidateHistogram)
    { histogram << csv(key.first) << ',' << csv(key.second) << ",candidate_count," << value << ',' << count << '\n'; }
  }
  std::ofstream audits(output / "audit.csv");
  audits << "reason,count\n";
  for (const auto &[reason, count] : audit) { audits << csv(reason) << ',' << count << '\n'; }
  std::ofstream scan(output / "scan_summary.json");
  const auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
  scan << "{\n  \"files\": " << files.size() << ",\n  \"bytes\": " << bytesTotal
       << ",\n  \"queries_started\": " << queriesTotal << ",\n  \"ends\": " << endsTotal
       << ",\n  \"candidate_rows\": " << candidatesTotal << ",\n  \"raw_rows\": " << rawTotal
       << ",\n  \"skip_rows\": " << skipsTotal << ",\n  \"schemas\": " << schemaTotal
       << ",\n  \"audit_events\": " << auditTotal << ",\n  \"changed_files\": " << changedFiles
       << ",\n  \"elapsed_seconds\": " << elapsed << "\n}\n";
  return auditTotal || changedFiles ? 2 : 0;
}
