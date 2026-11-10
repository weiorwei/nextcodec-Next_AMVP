// Streaming, read-only extraction of cost-sensitive labels from mode 7 logs.
// Feature extraction and all profile selections call the production C++ code.
#include "CommonLib/AmvpDecisionTree.h"
#include "CommonLib/AmvpCandidateSelector.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
#include <algorithm>

namespace fs = std::filesystem;
const std::vector<std::string> sequences = {
  "BasketballDrive", "BQTerrace", "Cactus", "MarketPlace", "RitualDance",
  "BasketballDrill", "BQMall", "PartyScene", "RaceHorsesC", "BasketballPass",
  "BQSquare", "BlowingBubbles", "RaceHorses"
};
std::string field(const std::string &s, const std::string &key)
{
  auto p = s.find(" " + key + "=");
  if (p == std::string::npos) return "";
  p += key.size() + 2;
  auto e = s.find(' ', p);
  return s.substr(p, e - p);
}
int integer(const std::string &s, const std::string &key)
{
  auto v = field(s, key);
  return v.empty() ? -999 : std::stoi(v);
}
Mv motion(const std::string &s, const std::string &key)
{
  int x, y;
  if (std::sscanf(field(s, key).c_str(), "(%d,%d)", &x, &y) != 2)
    throw std::runtime_error("Missing or malformed " + key);
  return Mv(x, y);
}
bool sameKey(const std::string &a, const std::string &b)
{
  for (const auto &key : { "POC", "CTU", "CU", "REF" })
    if (field(a, key).empty() || field(a, key) != field(b, key)) return false;
  return true;
}
unsigned rate(const Mv &mv, const Mv &mvp, int imv)
{
  Mv a = mv, b = mvp;
  a.changeTransPrecInternal2Amvr(imv);
  b.changeTransPrecInternal2Amvr(imv);
  const auto d = a - b;
  return RdCost::xGetExpGolombNumberOfBits(d.getHor()) +
         RdCost::xGetExpGolombNumberOfBits(d.getVer());
}
// Explicitly packed 76-byte little-endian records, matched in dataset.py.
#pragma pack(push, 1)
struct OutputRecord
{
  int32_t features[12];
  uint16_t profileBits[5];
  uint16_t oracleBits;
  uint8_t sequence;
  uint8_t qp;
  uint16_t segment;
  int32_t poc;
  uint64_t traceId;
};
#pragma pack(pop)
static_assert(sizeof(OutputRecord) == 76, "Unexpected dataset record layout");

struct Record
{
  std::string set, mvd, formal;
  Mv candidates[8];
  AmvpDecisionTree::CandidateMetadata metadata[8];
  unsigned loggedBits[8] = {};
  unsigned seen = 0;
};
std::map<std::string, uint64_t> totals;
std::map<std::string, uint64_t> current;
void count(const std::string &key) { ++totals[key]; ++current[key]; }
void process(const Record &r, const std::string &featureLine, int seq, int qp, int segment,
             std::ofstream &binary)
{
  count("cluster_records");
  if (field(r.set, "MODE") != "7" || field(r.set, "FOUND") != "yes" ||
      field(r.set, "IS_SMVD") != "no" || field(r.set, "MVD_L1_ZERO") != "no" ||
      field(r.set, "MVD_SIGNALLED") != "yes")
  { count("excluded_constrained_or_missing"); return; }
  if (segment > 0 && integer(r.set, "POC") == 0)
  { count("excluded_duplicate_segment_poc0"); return; }
  if (r.seen != 255 || !sameKey(r.set, r.mvd) || !sameKey(r.set, r.formal) ||
      !sameKey(r.set, featureLine) || field(r.set,"TRACE_ID") != field(featureLine,"TRACE_ID"))
  { count("excluded_incomplete_or_key_mismatch"); return; }
  if (field(r.set,"POOL_MATCH") != "yes" || field(r.set,"FORMAL_KNOWN") != "yes" ||
      field(r.formal,"FOUND") != "yes")
  { count("excluded_unknown_pool_or_formal"); return; }
  const int imv = integer(r.set,"IMV");
  if (imv < 0 || imv > 3) { count("excluded_invalid_imv"); return; }
  const auto mv = motion(r.mvd,"MV_INT");
  const auto mvp = motion(r.mvd,"MVP_INT");
  if (mv != motion(r.formal,"FINAL_MV_INT"))
  { count("excluded_final_mv_mismatch"); return; }
  unsigned bits[8];
  for (int k = 0; k < 8; ++k)
  {
    bits[k] = rate(mv,r.candidates[k],imv);
    if (bits[k] != r.loggedBits[k])
    { count("excluded_candidate_rate_mismatch"); return; }
  }
  const unsigned actualBits = rate(mv,mvp,imv);
  if (actualBits != static_cast<unsigned>(integer(r.set,"ACTUAL_EST_MVD_BITS")))
  { count("excluded_actual_rate_mismatch"); return; }
  Mv legacy[8]; bool valid[8];
  for(int k=0;k<8;++k) valid[k]=r.metadata[k].derived;
  AmvpCandidateSelector::reorderMotionOnly(r.candidates,valid,8,imv,legacy);
  if (legacy[0] != motion(r.formal,"STD0_INT") || legacy[1] != motion(r.formal,"STD1_INT"))
  { count("excluded_formal_pair_replay_mismatch"); return; }
  if (mvp != legacy[0] && mvp != legacy[1])
  { count("excluded_actual_mvp_outside_pair"); return; }
  const int selected = integer(r.set,"SELECTED_POOL_IDX");
  if (selected < 0 || selected >= 8 || r.candidates[selected] != mvp)
  { count("excluded_selected_pool_mismatch"); return; }
  if (actualBits != std::min(rate(mv,legacy[0],imv),rate(mv,legacy[1],imv)))
  { count("excluded_actual_not_pair_rate_best"); return; }
  const auto prepared = AmvpDecisionTree::preparePool(r.candidates,r.metadata,8,imv);
  if (prepared.numUnique < 2)
  { count("excluded_fallback_fewer_than_two_unique"); return; }
  AmvpDecisionTree::Context context;
  context.imv = imv;
  context.width = integer(featureLine,"CU_W");
  context.height = integer(featureLine,"CU_H");
  context.refPocDelta = integer(featureLine,"REF_POC_DELTA");
  if (context.width < 1 || context.height < 1 || context.refPocDelta == -999)
  { count("excluded_missing_context"); return; }
  const auto features = AmvpDecisionTree::extractFeatures(prepared,context);
  OutputRecord output{};
  for (int k=0;k<12;++k)
  {
    if (features[k] < INT32_MIN || features[k] > INT32_MAX)
      throw std::runtime_error("Feature overflow");
    output.features[k] = static_cast<int32_t>(features[k]);
  }
  unsigned oracle = UINT16_MAX;
  for (int k=0;k<8;++k) if(r.metadata[k].derived) oracle=std::min(oracle,bits[k]);
  output.oracleBits = static_cast<uint16_t>(oracle);
  for (int p=0;p<5;++p)
  {
    const auto pair = AmvpDecisionTree::selectProfile(prepared,p);
    const unsigned selectedBits=std::min(bits[pair.first],bits[pair.second]);
    if(selectedBits > UINT16_MAX || selectedBits < oracle)
      throw std::runtime_error("Invalid profile rate");
    output.profileBits[p]=static_cast<uint16_t>(selectedBits);
    if(p==0 && (r.candidates[pair.first]!=legacy[0] || r.candidates[pair.second]!=legacy[1]))
      throw std::runtime_error("Shared P0 differs from production mode 7");
  }
  output.sequence=static_cast<uint8_t>(seq);
  output.qp=static_cast<uint8_t>(qp);
  output.segment=static_cast<uint16_t>(segment);
  output.poc=integer(r.set,"POC");
  output.traceId=std::stoull(field(r.set,"TRACE_ID"));
  binary.write(reinterpret_cast<const char*>(&output),sizeof(output));
  if(!binary) throw std::runtime_error("Dataset write failed");
  count("accepted");
}
int main(int argc,char **argv)
{
  if(argc < 3 || argc > 4)
  { std::cerr<<"Usage: extract LOG_ROOT OUTPUT_DIR [MAX_FILES]\n";return 2; }
  const int maxFiles=argc==4?std::stoi(argv[3]):0;
  fs::create_directories(argv[2]);
  const auto outroot=fs::path(argv[2]);
  std::ofstream binary(outroot/"records.bin",std::ios::binary);
  std::ofstream manifest(outroot/"input_manifest.csv");
  manifest<<"sequence,qp,segment,path,bytes,cluster_records,accepted\n";
  std::ofstream audit(outroot/"filter_by_file.csv");
  audit<<"sequence,qp,segment,reason,count\n";
  struct Input { fs::path path; int seq,qp,segment; };
  std::vector<Input> inputs;
  for(const auto &entry:fs::directory_iterator(argv[1]))
  {
    const auto name=entry.path().filename().string();
    if(name.size()<9 || name.substr(name.size()-8)!="_enc.log")continue;
    const auto stem=name.substr(0,name.size()-8);
    auto p=stem.rfind('_'); if(p==std::string::npos)continue;
    int segment=std::stoi(stem.substr(p+1));
    auto q=stem.rfind('_',p-1);if(q==std::string::npos)continue;
    int qp=std::stoi(stem.substr(q+1,p-q-1));
    if(qp!=22 && qp!=27 && qp!=32 && qp!=37)continue;
    const auto seqname=stem.substr(0,q);
    auto it=std::find(sequences.begin(),sequences.end(),seqname);
    if(it==sequences.end())continue;
    inputs.push_back({entry.path(),int(it-sequences.begin()),qp,segment});
  }
  std::sort(inputs.begin(),inputs.end(),[](const Input&a,const Input&b){
    return std::tie(a.seq,a.qp,a.segment)<std::tie(b.seq,b.qp,b.segment); });
  int files=0;
  for(const auto &input:inputs)
  {
    if(maxFiles && files>=maxFiles)break;
    current.clear();
    std::ifstream in(input.path);
    if(!in)throw std::runtime_error("Cannot open input "+input.path.string());
    std::string line,lastMvd,lastFormal;
    Record record; bool have=false;
    while(std::getline(in,line))
    {
      if(line.compare(0,10,"[AMVP-MVD]")==0){lastMvd=line;have=false;}
      else if(line.compare(0,15,"[AMVP-CAND-SET]")==0)lastFormal=line;
      else if(line.compare(0,18,"[AMVP-CLUSTER-SET]")==0)
      {
        record=Record();record.set=line;record.mvd=lastMvd;record.formal=lastFormal;have=true;
      }
      else if(have && line.compare(0,16,"[AMVP-POOL-CAND]")==0)
      {
        if(!sameKey(record.set,line)||field(record.set,"TRACE_ID")!=field(line,"TRACE_ID"))
          throw std::runtime_error("Pool key mismatch");
        const int slot=integer(line,"SLOT");
        if(slot<0||slot>=8||(record.seen&(1u<<slot)))throw std::runtime_error("Invalid pool slot");
        record.seen|=1u<<slot;
        record.candidates[slot]=motion(line,"MV_INT");
        auto &meta=record.metadata[slot];
        meta.derived=field(line,"DERIVED")=="yes";
        meta.sourceMask=static_cast<unsigned>(integer(line,"SOURCE_MASK"));
        meta.spatialCuSupport=integer(line,"SPATIAL_CU_SUPPORT");
        meta.historyAge=integer(line,"HMVP_NEWEST_AGE");
        record.loggedBits[slot]=static_cast<unsigned>(integer(line,"EST_MVD_BITS"));
      }
      else if(have && line.compare(0,22,"[AMVP-CLUSTER-FEATURE]")==0)
      { process(record,line,input.seq,input.qp,input.segment,binary);have=false; }
    }
    ++files;
    manifest<<sequences[input.seq]<<','<<input.qp<<','<<input.segment<<','<<input.path.string()<<','
            <<fs::file_size(input.path)<<','<<current["cluster_records"]<<','<<current["accepted"]<<'\n';
    for(const auto &entry:current)
      audit<<sequences[input.seq]<<','<<input.qp<<','<<input.segment<<','<<entry.first<<','<<entry.second<<'\n';
    std::cerr<<"files="<<files<<"/"<<inputs.size()<<" accepted="<<totals["accepted"]<<" "<<input.path.filename().string()<<'\n';
  }
  std::ofstream summary(outroot/"filter_summary.csv");
  summary<<"reason,count\n";
  for(const auto &entry:totals)summary<<entry.first<<','<<entry.second<<'\n';
  std::cerr<<"Done files="<<files<<" accepted="<<totals["accepted"]<<'\n';
}
