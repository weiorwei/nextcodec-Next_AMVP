/* The copyright in this software is being made available under the BSD
 * License, included below. This software may be subject to other third party
 * and contributor rights, including patent rights, and no such rights are
 * granted under this license.
 *
 * Copyright (c) 2010-2024, ITU/ISO/IEC
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 *  * Redistributions of source code must retain the above copyright notice,
 *    this list of conditions and the following disclaimer.
 *  * Redistributions in binary form must reproduce the above copyright notice,
 *    this list of conditions and the following disclaimer in the documentation
 *    and/or other materials provided with the distribution.
 *  * Neither the name of the ITU/ISO/IEC nor the names of its contributors may
 *    be used to endorse or promote products derived from this software without
 *    specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS
 * BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 * CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF
 * THE POSSIBILITY OF SUCH DAMAGE.
 */
#pragma once
#include <memory>
#include <vector>
#include <array>
#include <cstdint>
#include <iostream>
#include <string>
#include "layer.h"
#include "layers.h"
#include "tensor.h"

namespace sadl
{
// input Tensor<T> dims: depth, nb rows, nb col

template<typename T> class Model
{
public:
  struct LayerData
  {
    std::unique_ptr<layers::Layer<T>> layer;
    std::vector<Tensor<T> *>          inputs;
  };
private:
  std::vector<LayerData>                     m_data;
  int32_t                                    m_nb_inputs       = 0;
  static constexpr int                       kMaxInputByLayer = 2;
  static constexpr int                       kMaxLayers       = 8192;
  std::vector<typename layers::Layer<T>::Id> getLayerIdsWithInput(typename layers::Layer<T>::Id id) const;
  void                                       insertCopyLayers();
  void                                       reshapeConv2DFilters();
  void                                       reshapeMatrix();
  Version                                    m_version = Version::unknown;
  std::vector<typename layers::Layer<T>::Id> m_ids_input, m_ids_output;
  bool                                       m_initDone = false;
  bool                                       m_sparsityComputed = false;
  std::string                                m_info;
  void                                       activateLayer(typename layers::Layer<T>::Id id);
public:
  bool             load(std::istream &in);
  bool             init(std::vector<Tensor<T>> &in);
  bool             apply(std::vector<Tensor<T>> &in);   // change input for optiz
  void             activateOutput(const std::vector<char> &output_activated);
  const Tensor<T> &result(int idx_out = 0) const { return getLayer(m_ids_output[idx_out]).layer->output(); }

  // aditionnal info
  std::vector<Tensor<T>>                            getInputsTemplate() const;
  const std::vector<typename layers::Layer<T>::Id> &getIdsOutput() const { return m_ids_output; }
  size_t                                            nbOutputs() const { return m_ids_output.size(); }
  std::vector<typename layers::Layer<T>::Id>        getLayersId() const;
  const LayerData &                                 getLayer(const typename layers::Layer<T>::Id &id) const;
  LayerData &                                       getLayer(const typename layers::Layer<T>::Id &id);
  Version                                           version() const { return m_version; }
  const std::string &                               info() const { return m_info; }

#if SPARSE_SUPPORT
  bool             compute_sparsity(std::vector<Tensor<T>>& in);
  float sparsity_threshold      = kSparsifyThreshold;
  float sparsity_size_threshold = kSparsifySizeThreshold;
#endif
#if DEBUG_COUNTERS
  struct Stat
  {
    uint64_t overflow = 0;
    uint64_t op       = 0;
    uint64_t mac      = 0;
    uint64_t mac_nz   = 0;
  };
  void resetCounters();
  Stat printOverflow(bool printinfo = false) const;
#endif

  DUMP_MODEL_EXT_BASE;
};

template<typename T> std::unique_ptr<layers::Layer<T>> createLayer(int32_t id, layers::OperationType::Type op)
{
  switch (op)
  {
  case layers::OperationType::Copy:
    return std::unique_ptr<layers::Layer<T>>(new layers::Copy<T>{ id, op });
    break;
  case layers::OperationType::Const:
    return std::unique_ptr<layers::Layer<T>>(new layers::Const<T>{ id, op });
    break;
  case layers::OperationType::Placeholder:
    return std::unique_ptr<layers::Layer<T>>(new layers::Placeholder<T>{ id, op });
    break;
  case layers::OperationType::Reshape:
    return std::unique_ptr<layers::Layer<T>>(new layers::Reshape<T>{ id, op });
    break;
  case layers::OperationType::Identity:
    return std::unique_ptr<layers::Layer<T>>(new layers::Identity<T>{ id, op });
    break;
  case layers::OperationType::MatMul:
    return std::unique_ptr<layers::Layer<T>>(new layers::MatMul<T>{ id, op });
    break;
  case layers::OperationType::BiasAdd:
    return std::unique_ptr<layers::Layer<T>>(new layers::BiasAdd<T>{ id, op });
    break;
  case layers::OperationType::Conv2D:
    return std::unique_ptr<layers::Layer<T>>(new layers::Conv2D<T>{ id, op });
    break;
  case layers::OperationType::Conv2DTranspose:
    return std::unique_ptr<layers::Layer<T>>(new layers::Conv2DTranspose<T>{ id, op });
    break;
  case layers::OperationType::Add:
    return std::unique_ptr<layers::Layer<T>>(new layers::Add<T>{ id, op });
    break;
  case layers::OperationType::Relu:
    return std::unique_ptr<layers::Layer<T>>(new layers::Relu<T>{ id, op });
    break;
  case layers::OperationType::MaxPool:
    return std::unique_ptr<layers::Layer<T>>(new layers::MaxPool<T>{ id, op });
    break;
  case layers::OperationType::Mul:
    return std::unique_ptr<layers::Layer<T>>(new layers::Mul<T>{ id, op });
    break;
  case layers::OperationType::Concat:
    return std::unique_ptr<layers::Layer<T>>(new layers::Concat<T>{ id, op });
    break;
  case layers::OperationType::Maximum:
    return std::unique_ptr<layers::Layer<T>>(new layers::Maximum<T>{ id, op });
    break;
  case layers::OperationType::LeakyRelu:
    return std::unique_ptr<layers::Layer<T>>(new layers::LeakyRelu<T>{ id, op });
    break;
  case layers::OperationType::Transpose:
    return std::unique_ptr<layers::Layer<T>>(new layers::Transpose<T>{ id, op });
    break;
  case layers::OperationType::Flatten:
    return std::unique_ptr<layers::Layer<T>>(new layers::Flatten<T>{ id, op });
    break;
  case layers::OperationType::Shape:
    return std::unique_ptr<layers::Layer<T>>(new layers::Shape<T>{ id, op });
    break;
  case layers::OperationType::Expand:
    return std::unique_ptr<layers::Layer<T>>(new layers::Expand<T>{ id, op });
    break;
  case layers::OperationType::Slice:
    return std::unique_ptr<layers::Layer<T>>(new layers::Slice<T>{ id, op });
    break;
  case layers::OperationType::PReLU:
    return std::unique_ptr<layers::Layer<T>>(new layers::PReLU<T>{ id, op });
    break;
  case layers::OperationType::ScatterND:
    return std::unique_ptr<layers::Layer<T>>(new layers::ScatterND<T>{ id, op });
    break;
  case layers::OperationType::GridSample:
    return std::unique_ptr<layers::Layer<T>>(new layers::GridSample<T>{ id, op });
    break;
  case layers::OperationType::Resize:
    return std::unique_ptr<layers::Layer<T>>(new layers::Resize<T>{ id, op });
    break;
  case layers::OperationType::Compare:
    return std::unique_ptr<layers::Layer<T>>(new layers::Compare<T>{ id, op });
    break;
  case layers::OperationType::Where:
    return std::unique_ptr<layers::Layer<T>>(new layers::Where<T>{ id, op });
    break;
  case layers::OperationType::Minimum:
    return std::unique_ptr<layers::Layer<T>>(new layers::Minimum<T>{ id, op });
    break;
  case layers::OperationType::AveragePool:
    return std::unique_ptr<layers::Layer<T>>(new layers::AveragePool<T>{ id, op });
    break;
  case layers::OperationType::ReduceMean:
    return std::unique_ptr<layers::Layer<T>>(new layers::ReduceMean<T>{ id, op });
    break;    
  case layers::OperationType::OperationTypeCount:
    std::cerr << "[ERROR] unknown layer " << op << std::endl;
    exit(-1);
    break;   // no default on purpose
  case layers::OperationType::OperationExperimentalStart:
    std::cerr << "[ERROR] unknown layer " << op << std::endl;
    exit(-1);
    break;   // no default on purpose
  case layers::OperationType::OperationExperimentalEnd:
    std::cerr << "[ERROR] unknown layer " << op << std::endl;
    exit(-1);
    break;   // no default on purpose
  }
  std::cerr << "[ERROR] unknown layer " << op << std::endl;
  exit(-1);
}

template<typename T> bool Model<T>::load(std::istream &file)
{
  if (!file)
  {
    std::cerr << "[ERROR] Pb reading model" << std::endl;
    return false;
  }
  // reset model
  m_info.clear();

  // clear current object
  m_data.clear();
  m_nb_inputs = 0;
  m_version   = Version::unknown;
  m_ids_input.clear();
  m_ids_output.clear();
  m_initDone = false;
#if DEBUG_COUNTERS
  resetCounters();
#endif
  SADL_DBG(std::cout << "[INFO] == start model loading ==" << std::endl);
  char magic[9];
  file.read(magic, 8);
  magic[8] = '\0';
  SADL_DBG(std::cout << "[INFO] read magic " << magic << std::endl);
  std::string magic_s = magic;
  if (magic_s == "SADL0001")
  {
    std::cerr << "[ERROR] please use the converter for v2 of SADL" << std::endl;
    return false;
  }
  else if (magic_s == "SADL0002")
  {
    m_version = Version::sadl02;
#if DEBUG_PRINT
    std::cout << "[WARNING] SADL02 version model, please upgrade to SADL04" << std::endl;
#endif
  }
  else if (magic_s == "SADL0003")
  {
    m_version = Version::sadl03;
#if DEBUG_PRINT
    std::cout << "[WARNING] SADL03 version model, please upgrade to SADL04" << std::endl;
#endif
  }
  else if (magic_s == "SADL0004")
  {
    m_version = Version::sadl04;
#if DEBUG_PRINT
    std::cout << "[WARNING] SADL04 version model, please upgrade to SADL05" << std::endl;
#endif
  }
  else if (magic_s == "SADL0005")
  {
    m_version = Version::sadl05;
  }
  else
  {
    if (!file)
    {
      std::cerr << "[ERROR] Pb reading model" << std::endl;
      return false;
    }
    std::cerr << "[ERROR] Pb reading model: wrong magic " << magic_s << std::endl;
    return false;
  }

  {
    int32_t x = 0;
    file.read((char *) &x, sizeof(int32_t));
    if ((std::is_same<T, float>::value && x != layers::TensorInternalType::Float) || (std::is_same<T, int32_t>::value && x != layers::TensorInternalType::Int32)
        || (std::is_same<T, int16_t>::value && x != layers::TensorInternalType::Int16))
    {
      std::cerr << "[ERROR] wrong model type and Model<T> " << std::endl;
      return false;
    }
    SADL_DBG(std::cout << "[INFO] Model type: " << (int) x << std::endl);
  }

  if (m_version >= Version::sadl05 ) {
    int16_t x = 0;
    file.read((char *) &x, sizeof(int16_t));
    if (x > 0)
    {
      std::vector<char> v;
      v.resize(x + 1);
      v[x] = 0;
      file.read(v.data(), sizeof(char) * x);
      m_info = std::string{ v.data() };
    }
    SADL_DBG(std::cout << "[INFO] Model info: '" << m_info << "'" << std::endl);
  }
  int32_t nb_layers = 0;
  file.read((char *) &nb_layers, sizeof(int32_t));
  SADL_DBG(std::cout << "[INFO] Num layers: " << nb_layers << std::endl);
  if (nb_layers <= 0 || nb_layers > kMaxLayers)
  {
    std::cerr << "[ERROR] Pb reading model: nb layers " << nb_layers << std::endl;
    return false;
  }
  m_data.clear();
  m_data.resize(nb_layers);

  {
    int32_t nb;
    file.read((char *) &nb, sizeof(int32_t));
    m_ids_input.resize(nb);
    file.read((char *) m_ids_input.data(), sizeof(int32_t) * nb);
    file.read((char *) &nb, sizeof(int32_t));
    m_ids_output.resize(nb);
    file.read((char *) m_ids_output.data(), sizeof(int32_t) * nb);
    SADL_DBG(std::cout << "[INFO] input id: ");
    for (auto id: m_ids_input)
    {
      SADL_DBG(std::cout << id << ' ');
      (void) id;
    }
    SADL_DBG(std::cout << std::endl);
    SADL_DBG(std::cout << "[INFO] output id: ");
    for (auto id: m_ids_output)
    {
      SADL_DBG(std::cout << id << ' ');
      (void) id;
    }
    SADL_DBG(std::cout << std::endl);
  }
  if (m_version >= Version::sadl05)
  {
    file.read((char*)&m_sparsityComputed, sizeof(m_sparsityComputed));
  }

  for (int k = 0; k < nb_layers; ++k)
  {
    typename layers::Layer<T>::Id id = 0;
    file.read((char *) &id, sizeof(int32_t));
    int32_t op = 0;
    file.read((char *) &op, sizeof(int32_t));
    if (!(op > 0 && op < layers::OperationType::OperationTypeCount)
        && !(op > layers::OperationType::OperationExperimentalStart && op < layers::OperationType::OperationExperimentalEnd+1)) // +1 to avoid warning
    {
      std::cerr << "[ERROR] Pb reading model: layer op " << op << std::endl;
      return false;
    }
    SADL_DBG(std::cout << "[INFO] id: " << id << " op " << ' ' << layers::opName((layers::OperationType::Type) op) << std::endl);
    if (op > layers::OperationType::OperationExperimentalStart)
    {
      SADL_DBG(std::cout << "[WARN] experimental layer " << std::endl);
    }
    m_data[k].layer = createLayer<T>(id, (layers::OperationType::Type) op);
    m_data[k].inputs.clear();
    if (!m_data[k].layer->load(file, m_version))
    {
      m_data.clear();
      return false;
    }
    }

  if (m_data.empty())
  {
    std::cerr << "[ERROR] Pb reading model: no layer" << std::endl;
    return false;
  }
  SADL_DBG(std::cout << "[INFO] == end model loading ==\n" << std::endl);

  return true;
}

template<typename T> bool Model<T>::init(std::vector<Tensor<T>> &in)
{
  SADL_DBG(std::cout << "[INFO] == start model init ==" << std::endl);

  if (std::is_same<T, float>::value)
  {
    SADL_DBG(std::cout << "[INFO] float mode" << std::endl);
  }
  else if (std::is_same<T, int32_t>::value)
  {
    SADL_DBG(std::cout << "[INFO] int32 mode" << std::endl);
  }
  else if (std::is_same<T, int16_t>::value)
  {
    SADL_DBG(std::cout << "[INFO] int16 mode" << std::endl);
  }
  else
  {
    std::cerr << "[ERROR] unsupported type" << std::endl;
    return false;
  }
#if __AVX2__
  SADL_DBG(std::cout << "[INFO] use SIMD code" << std::endl);
#endif
#if __AVX512F__
  SADL_DBG(std::cout << "[INFO] use SIMD512 code" << std::endl);
#endif
#if __FMA__
  SADL_DBG(std::cout << "[INFO] use FMA" << std::endl);
#endif
  SADL_DBG(std::cout << "[INFO] use swapped tensor" << std::endl);

  if (m_data.empty())
  {
    std::cerr << "[ERROR] Empty model" << std::endl;
    return false;
  }
  m_nb_inputs = (int) in.size();
  if (m_nb_inputs != (int) m_ids_input.size())
  {
    std::cerr << "[ERROR] inconsistent input dimension" << std::endl;
    return false;
  }
  if (m_initDone)
  {
    // reset initdone of layers
    for (auto &L: m_data)
    {
      L.layer->m_initDone = false;
      L.layer->m_torun = true;
    }
  }
  else
  {
    insertCopyLayers();
    reshapeConv2DFilters();
    reshapeMatrix();
  }
  // first solve inputs for placeholders (the inputs)
  bool ok               = true;
  int  placeholders_cnt = 0;
  for (int layer_cnt = 0; layer_cnt < (int) m_data.size() && ok; ++layer_cnt)
  {
    if (m_data[layer_cnt].layer->op() == layers::OperationType::Placeholder)
    {
      if (placeholders_cnt >= (int) in.size())
      {
        std::cerr << "[ERROR] more placeholders than inputs" << std::endl;
        ok = false;
        break;
      }
      if (m_data[layer_cnt].layer->inputsId().size() != 0)
      {
        std::cerr << "[ERROR] placeholders should have only 0 input" << std::endl;
        ok = false;
        break;
      }
      std::vector<Tensor<T> *> v = { &in[placeholders_cnt] };
      ++placeholders_cnt;
      m_data[layer_cnt].layer->init(v);
      SADL_DBG(std::cout << "[INFO] init layer " << m_data[layer_cnt].layer->id() << ' '
                         << layers::opName((layers::OperationType::Type) (m_data[layer_cnt].layer->op())) << ' ' << m_data[layer_cnt].layer->name()
                         << " out=" << m_data[layer_cnt].layer->m_out.dims() << std::endl);
    }
  }
  if (!ok)
    return false;
  if (placeholders_cnt != (int) in.size())
  {
    std::cerr << "[ERROR] less placeholders than inputs" << std::endl;
    return false;
  }

  // then solve inputs of other layers: make the link between id of inputs and tensor ptr
  for (int layer_cnt = 0; layer_cnt < (int) m_data.size() && ok; ++layer_cnt)
  {
    if (m_data[layer_cnt].layer->op() == layers::OperationType::Placeholder)
      continue;
    int nb_inputs = (int) m_data[layer_cnt].layer->inputsId().size();
    m_data[layer_cnt].inputs.resize(nb_inputs);
    std::vector<layers::OperationType::Type> op_type(nb_inputs);
    for (int inputs_cnt = 0; inputs_cnt < nb_inputs; ++inputs_cnt)
    {
      typename layers::Layer<T>::Id id_input = m_data[layer_cnt].layer->inputsId()[inputs_cnt];
      auto &                        L        = getLayer(id_input);
      if (!L.layer->initDone())
      {
        std::cerr << "[ERROR] init not done yet on " << L.layer->id() << " while init of " << m_data[layer_cnt].layer->id() << std::endl;
        return false;
      }

      Tensor<T> *tmp = &(L.layer->output());
#if SPARSE_SUPPORT
      if (!m_sparsityComputed && sparsity_threshold >= 0 && sparsity_threshold <= 1.)
      {
        if (m_data[layer_cnt].layer->op() == layers::OperationType::MatMul && L.layer->op() == layers::OperationType::Const)
        {
          if (!L.layer->output().isDenseDataAvailable())
          {
            L.layer->output().redensifySparseData();
          }
          if (isFullMatrixSparse(L.layer->output(), sparsity_threshold, sparsity_size_threshold))
          {
            SADL_DBG(std::cout << "[INFO] Sparsify layer " << m_data[layer_cnt].layer->id() << " " << m_data[layer_cnt].layer->name() << std::endl);
            int packedSparsitySize = computePackedSparsity(*tmp);
            if (packedSparsitySize > 1)
            {
              SADL_DBG(std::cout << "[INFO] Sparsify with packing " << packedSparsitySize << " layer " << m_data[layer_cnt].layer->id() << " " << m_data[layer_cnt].layer->name() << std::endl);
              sparsifyWithPacking(*tmp, packedSparsitySize);
            }
            else
            {
              sparsify(*tmp);
            }
          }
        }
      }
      else if (m_sparsityComputed && tmp->isSparse())
      {
        SADL_DBG(std::cout << "[INFO] Sparse layer " << m_data[layer_cnt].layer->id() << " " << m_data[layer_cnt].layer->name() << " with block sparsity " << tmp->getPackedSparsitySize() << std::endl;);
        tmp->checkSimdAlignment();
      }
#endif

      m_data[layer_cnt].inputs[inputs_cnt] = tmp;
      op_type[inputs_cnt]                 = L.layer->op();

      // always put data layers first when const layers
      if ((inputs_cnt > 0 && op_type[inputs_cnt - 1] == layers::OperationType::Const && op_type[inputs_cnt] != layers::OperationType::Const) && m_data[layer_cnt].layer->op() != layers::OperationType::Where)
      {
        std::cerr << "[ERROR] data layers should be first" << std::endl;
        return false;
      }
    }
    ok &= m_data[layer_cnt].layer->init(m_data[layer_cnt].inputs);
    SADL_DBG(std::cout << "[INFO] init layer " << m_data[layer_cnt].layer->id() << ' '
                       << layers::opName((layers::OperationType::Type) (m_data[layer_cnt].layer->op())) << ' ' << m_data[layer_cnt].layer->name() << " in=[");
    SADL_DBG(for (auto ii : m_data[layer_cnt].layer->inputsId()) std::cout << ii << ' ');
    SADL_DBG(std::cout << "] out=" << m_data[layer_cnt].layer->m_out.dims() << std::endl);

    if (!ok)
    {
      std::cerr << "[ERROR] init layer " << m_data[layer_cnt].layer->id() << " " << m_data[layer_cnt].layer->name() << std::endl;
      break;
    }
  }
  SADL_DBG(std::cout << "[INFO] == end model init ==\n" << std::endl);

  if (!ok)
    return false;
  m_initDone = true;
  return true;
}
#if SPARSE_SUPPORT
template<typename T> bool Model<T>::compute_sparsity(std::vector<Tensor<T>> &in)
{
  SADL_DBG(std::cout << "[INFO] == start model sparsity computation ==" << std::endl);

  if (m_data.empty())
  {
    std::cerr << "[ERROR] Empty model" << std::endl;
    return false;
  }
  m_nb_inputs = (int) in.size();
  if (m_nb_inputs != (int) m_ids_input.size())
  {
    std::cerr << "[ERROR] inconsistent input dimension" << std::endl;
    return false;
  }

  bool ok               = true;
  if (!m_initDone)
  {
    reshapeMatrix();
  }
  if (sparsity_threshold >= 0 && sparsity_threshold <= 1.)
  {
    // then solve inputs of other layers: make the link between id of inputs and tensor ptr
    for (int layer_cnt = 0; layer_cnt < (int)m_data.size() && ok; ++layer_cnt)
    {
      if (m_data[layer_cnt].layer->op() == layers::OperationType::Placeholder)
        continue;
      int nb_inputs = (int)m_data[layer_cnt].layer->inputsId().size();
      for (int inputs_cnt = 0; inputs_cnt < nb_inputs; ++inputs_cnt)
      {
        typename layers::Layer<T>::Id id_input = m_data[layer_cnt].layer->inputsId()[inputs_cnt];
        auto& L = getLayer(id_input);

        Tensor<T>* tmp = &(L.layer->output());
        if (m_data[layer_cnt].layer->op() == layers::OperationType::MatMul && L.layer->op() == layers::OperationType::Const)
        {
          if (!L.layer->output().isDenseDataAvailable())
          {
            L.layer->output().redensifySparseData();
          }
          if (isFullMatrixSparse(L.layer->output(), sparsity_threshold, sparsity_size_threshold))
          {
            SADL_DBG(std::cout << "[INFO] Sparsify layer " << m_data[layer_cnt].layer->id() << " " << m_data[layer_cnt].layer->name() << std::endl);
            int packedSparsitySize = computePackedSparsity(*tmp);
            if (packedSparsitySize > 1)
            {
              SADL_DBG(std::cout << "[INFO] Sparsify with packing " << packedSparsitySize << " layer " << m_data[layer_cnt].layer->id() << " " << m_data[layer_cnt].layer->name() << std::endl);
              sparsifyWithPacking(*tmp, packedSparsitySize);
            }
            else 
            {
              sparsify(*tmp);
            }
          }
        }
      }
    }
    m_sparsityComputed = true;
  }
  SADL_DBG(std::cout << "[INFO] == end model sparsity computation ==\n" << std::endl);
  if (!ok)
    return false;
  return true;
}
#endif

template<typename T> bool Model<T>::apply(std::vector<Tensor<T>> &in)
{
#if DEBUG_VALUES || DEBUG_MODEL
  std::cout << "[INFO] == start model inference ==" << std::endl;
#endif
  assert(!m_data.empty());
  assert((int) in.size() == m_nb_inputs);
  // should be ok in order (take care of that on python side)
  bool ok               = true;
  int  placeholders_cnt = 0;
  for (int layer_cnt = 0; layer_cnt < (int) m_data.size() && ok; ++layer_cnt)
  {
    if (m_data[layer_cnt].layer->op() == layers::OperationType::Placeholder && m_data[layer_cnt].layer->m_torun )
    {
      std::vector<Tensor<T> *> v = { &in[placeholders_cnt] };
      ++placeholders_cnt;
      ok &= m_data[layer_cnt].layer->apply(v);
#if DEBUG_VALUES || DEBUG_MODEL
      std::cout << "[INFO] " << m_data[layer_cnt].layer->id() << " Placeholder (" << m_data[layer_cnt].layer->name() << "): ";
      if (!std::is_same<T, float>::value)
      {
        std::cout << "q=" << m_data[layer_cnt].layer->m_out.quantizer << " ";
      }
#endif
#if DEBUG_VALUES
      if (std::is_same<T, float>::value)
      {
        for (int k = 0; k < 8 && k < (int) m_data[layer_cnt].layer->m_out.size(); ++k)
          std::cout << m_data[layer_cnt].layer->m_out[k] << ' ';
        std::cout << "]\t";
      }
      else
      {
        float Q = (float) (1 << m_data[layer_cnt].layer->m_out.quantizer);
        for (int k = 0; k < 8 && k < (int) m_data[layer_cnt].layer->m_out.size(); ++k)
          std::cout << m_data[layer_cnt].layer->m_out[k] / Q << ' ';
        std::cout << "]\t";
      }
#endif
#if DEBUG_MODEL
      m_data[layer_cnt].layer->m_computed = true;
      std::cout << (ok ? "OK" : "FAIL") << std::endl;
#endif
#if DEBUG_KEEP_OUTPUT
      m_data[layer_cnt].layer->m_outcopy = m_data[layer_cnt].layer->m_out;
#endif
    }
  }

  for (int layer_cnt = 0; layer_cnt < (int) m_data.size() && ok; ++layer_cnt)
  {
    if (m_data[layer_cnt].layer->op() == layers::OperationType::Placeholder || !m_data[layer_cnt].layer->m_torun)
      continue;
#if DEBUG_MODEL
    for (int kk = 0; kk < (int) m_data[layer_cnt].inputs.size(); ++kk)
    {
      const int   id = m_data[layer_cnt].layer->inputsId()[kk];
      const auto &L  = getLayer(id);
      (void) L;
      assert(L.layer->m_computed);
    }
#endif
#if DEBUG_VALUES || DEBUG_MODEL
    std::cout << "[INFO] " << m_data[layer_cnt].layer->id() << " " << opName(m_data[layer_cnt].layer->op()) << " (" << m_data[layer_cnt].layer->name() << "):\t";
#endif
#if DEBUG_VALUES
    if (m_data[layer_cnt].inputs.size())
    {
      std::cout << "inputs={";
    }
    for (int kk = 0; kk < (int) m_data[layer_cnt].inputs.size(); ++kk)
    {
      const int id = m_data[layer_cnt].layer->m_inputs_id[kk];
      std::cout << id;
      if (!std::is_same<T, float>::value)
      {
        std::cout << "(q=" << m_data[layer_cnt].inputs[kk]->quantizer << ")";
      }
      if (kk != (int) m_data[layer_cnt].inputs.size() - 1)
        std::cout << ", ";
    }
    if (m_data[layer_cnt].inputs.size())
    {
      std::cout << "} ";
    }
#endif

    ok &= m_data[layer_cnt].layer->apply(m_data[layer_cnt].inputs);
#if DEBUG_VALUES
#if SPARSE_SUPPORT
    if (!m_data[layer_cnt].layer->m_out.isSparse())
#endif
    {
      std::cout << "outputs=[";
      if (std::is_same<T, float>::value)
      {
        for (int k = 0; k < 8 && k < (int) m_data[layer_cnt].layer->m_out.size(); ++k)
          std::cout << m_data[layer_cnt].layer->m_out[k] << ' ';
        if (m_data[layer_cnt].layer->m_out.size() > 8)
          std::cout << " ...";
        std::cout << "]\t";
      }
      else
      {
        float Q = (float)(1 << m_data[layer_cnt].layer->m_out.quantizer);
        for (int k = 0; k < 8 && k < (int) m_data[layer_cnt].layer->m_out.size(); ++k)
          std::cout << m_data[layer_cnt].layer->m_out[k] / Q << ' ';
        if (m_data[layer_cnt].layer->m_out.size() > 8)
          std::cout << " ...";
        std::cout << "] q=" << m_data[layer_cnt].layer->m_out.quantizer << "]\t";
      }
    }
#endif
#if DEBUG_MODEL
    m_data[layer_cnt].layer->m_computed = true;
    std::cout << (ok ? "OK" : "FAIL") << std::endl;
#endif
#if DEBUG_KEEP_OUTPUT
    m_data[layer_cnt].layer->m_outcopy = m_data[layer_cnt].layer->m_out;
#endif
  }
#if DEBUG_VALUES || DEBUG_MODEL
  if (ok)
    std::cout << "[INFO] Inference OK" << std::endl;
  else
    std::cout << "[ERROR] Inference failed" << std::endl;
  std::cout << "[INFO] == end model inference ==\n" << std::endl;
#endif
  return ok;
}

#if DEBUG_COUNTERS

template<typename T> typename Model<T>::Stat Model<T>::printOverflow(bool printinfo) const
{
  Stat stat;
  for (int layer_cnt = 0; layer_cnt < (int) m_data.size(); ++layer_cnt)
  {
    stat.overflow += m_data[layer_cnt].layer->cpt_overflow;
    stat.op += m_data[layer_cnt].layer->cpt_op;
    stat.mac += m_data[layer_cnt].layer->cpt_mac;
    stat.mac_nz += m_data[layer_cnt].layer->cpt_mac_nz;
    if (m_data[layer_cnt].layer->cpt_overflow > 0)
    {
      std::cout << "[WARN] layer " << m_data[layer_cnt].layer->id() << ' ' << m_data[layer_cnt].layer->name() << " [" << opName(m_data[layer_cnt].layer->op())
                << "]: overflow: " << m_data[layer_cnt].layer->cpt_overflow << '/' << m_data[layer_cnt].layer->cpt_op << " ("
                << m_data[layer_cnt].layer->cpt_overflow * 100. / m_data[layer_cnt].layer->cpt_op << "%)" << std::endl;
    }
    else {
      if (printinfo && (m_data[layer_cnt].layer->cpt_op > 0 || m_data[layer_cnt].layer->cpt_mac > 0 ) )
      {
        std::cout << "[INFO] layer " << m_data[layer_cnt].layer->id() << ' ' << m_data[layer_cnt].layer->name() << " [" << opName(m_data[layer_cnt].layer->op()) << "]: "
                  << m_data[layer_cnt].layer->cpt_mac << " mac, "
                  << m_data[layer_cnt].layer->cpt_op << " op" << std::endl;
      }
    }
  }
#if DEBUG_COUNTERS && __AVX2__
  std::cout << "[WARN] counters should not be used in SIMD mode, please use scalar mode for reliable results" << std::endl;
  stat.op     = 0;
  stat.mac    = 0;
  stat.mac_nz = 0;
#endif
  return stat;
}

template<typename T> void Model<T>::resetCounters()
{
  for (int layer_cnt = 0; layer_cnt < (int) m_data.size(); ++layer_cnt)
  {
    if (m_data[layer_cnt].layer->op() == layers::OperationType::Placeholder)
      continue;
    m_data[layer_cnt].layer->cpt_overflow = 0;
    m_data[layer_cnt].layer->cpt_op       = 0;
    m_data[layer_cnt].layer->cpt_mac      = 0;
    m_data[layer_cnt].layer->cpt_mac_nz   = 0;
  }
}
#endif

template<typename T> std::vector<typename layers::Layer<T>::Id> Model<T>::getLayerIdsWithInput(typename layers::Layer<T>::Id id) const
{
  std::vector<typename layers::Layer<T>::Id> v;
  for (auto &L: m_data)
  {
    const auto &ids = L.layer->inputsId();
    if (std::find(ids.begin(), ids.end(), id) != ids.end())
      v.push_back(L.layer->id());
  }
  return v;
}

template<typename T> typename Model<T>::LayerData &Model<T>::getLayer(const typename layers::Layer<T>::Id &id)
{
  auto it = std::find_if(m_data.begin(), m_data.end(), [&, id](const LayerData &d) { return d.layer->id() == id; });
  if (it == m_data.end())
  {
    std::cerr << "[ERROR] cannot find input " << id << std::endl;
    assert(false);
    exit(-1);
  }
  return *it;
}

template<typename T> const typename Model<T>::LayerData &Model<T>::getLayer(const typename layers::Layer<T>::Id &id) const
{
  auto it = std::find_if(m_data.begin(), m_data.end(), [&, id](const LayerData &d) { return d.layer->id() == id; });
  if (it == m_data.end())
  {
    std::cerr << "[ERROR] cannot find input " << id << std::endl;
    assert(false);
    exit(-1);
  }
  return *it;
}

template<typename T> std::vector<typename layers::Layer<T>::Id> Model<T>::getLayersId() const
{
  std::vector<typename layers::Layer<T>::Id> ids;
  for (const auto &L: m_data)
    ids.push_back(L.layer->id());
  return ids;
}

template<typename T>
void Model<T>::activateLayer(typename layers::Layer<T>::Id id) {
    auto it = std::find_if(m_data.begin(), m_data.end(), [&, id](const LayerData &d) { return d.layer->id() == id; });
    if (it == m_data.end())
    {
      std::cerr << "[ERROR] cannot find input " << id << std::endl;
      assert(false);
      exit(-1);
    }
    it->layer->m_torun=true;
    for (auto idin: it->layer->m_inputs_id)
    {
        activateLayer(idin);
    }
}

template<typename T>
void Model<T>::activateOutput(const std::vector<char> &output_activated) {
    assert(!m_ids_output.empty());
    if (output_activated.size()!=m_ids_output.size()) {
        std::cerr << "[ERROR] output_activated not compatible with current outputs" << std::endl;
        assert(false);
        exit(-1);
    }
    for (auto &L: m_data) {
        L.layer->m_torun=false;
    }
    for(int idx=0;idx<(int)output_activated.size();++idx) {
        if (output_activated[idx]) {
         activateLayer(m_ids_output[idx])   ;
        }
    }
#if DEBUG_PRINT
    // debug
    int n=0;
    for(const auto &L: m_data) {
        if (L.layer->m_torun) ++n;
    }
    std::cout<<"[INFO] nb activated layers: "<<n<<"/"<<m_data.size()<<std::endl;
#endif
}

// insert copy layer before some layers inputs to deal with mutability of inputs
template<typename T> void Model<T>::insertCopyLayers()
{
  typename layers::Layer<T>::Id cnt_id = -1;   // copy layers have negative id
  // create addtionnal copy layer if needed
  for (int k = 0; k < (int) m_data.size(); ++k)
  {
    auto &                                     current_layer               = *m_data[k].layer;
    auto                                       layer_with_current_as_input = getLayerIdsWithInput(current_layer.id());
    std::vector<typename layers::Layer<T>::Id> layer_with_current_as_mutable_input;
    // remove layers which does not modify their input
    for (auto id: layer_with_current_as_input)
    {
      const auto &L = getLayer(id);
      if (L.layer->mutateInput()) { 
        layer_with_current_as_mutable_input.push_back(id);
      }
    }
    if (layer_with_current_as_input.size()>1 && !layer_with_current_as_mutable_input.empty())
    {                                                           // need copy layer
      // for current layer L, insert copy layers C just after: x x x L C C xxxx
      std::vector<typename layers::Layer<T>::Id> id_copy_layers;
      const int offset=layer_with_current_as_input.size()==layer_with_current_as_mutable_input.size();
      for (int n = 0; n < (int) layer_with_current_as_mutable_input.size() - offset; ++n)
      {
        LayerData copy_layer;
        id_copy_layers.push_back(cnt_id);
        copy_layer.layer = createLayer<T>(cnt_id, layers::OperationType::Copy);
        dynamic_cast<layers::Copy<T> &>(*copy_layer.layer).setInputLayer(current_layer.id());

        SADL_DBG(std::cout << "[INFO] insert copy id=" << cnt_id << " of id=" << current_layer.id() << std::endl);
        --cnt_id;
        m_data.insert(m_data.begin() + k + 1, std::move(copy_layer));
      }
      // now change inputs of the layers to a copy of the output of the current layer (except the first one which keep
      // the output of the current layer)
      for (int n = offset; n < (int) layer_with_current_as_mutable_input.size(); ++n)
      {
        auto &L = getLayer(layer_with_current_as_mutable_input[n]);
        SADL_DBG(std::cout << "[INFO] replace id=" << current_layer.id() << " by id=" << id_copy_layers[n - offset] << " in layer " << L.layer->id() << std::endl);
        L.layer->replaceInputId(current_layer.id(), id_copy_layers[n - offset]);
      }
    }
  }
  SADL_DBG(std::cout << "[INFO] inserted " << (abs(cnt_id) - 1) << " copy layers" << std::endl);
}

template<typename T> void Model<T>::reshapeMatrix()
{
  for (auto &v: m_data)
  {
    if (v.layer->op() == layers::OperationType::MatMul)
    {
      if (v.layer->inputsId().size() != 2)
      {
        std::cerr << "[ERROR] cannot find input 2 for MatMul in reshapeMatrix()" << std::endl;
        assert(false);
        exit(-1);
      }
      auto &L = getLayer(v.layer->inputsId()[1]);
      auto &R = L.layer->output();
      if (R.getTransposed())
      {
        SADL_DBG(std::cout << "[INFO] data already transposed " << L.layer->id() << ' ' << L.layer->name() << " " << R.dims() << std::endl);
      }
      else
      {
        // invert k and l dimensions
        Dimensions d = R.dims();
        if (d.size() == 2)
        {   // only transpose dim 2 for now
          // do not swap dim, just data
          SADL_DBG(std::cout << "[INFO] transpose data " << L.layer->id() << ' ' << L.layer->name() << " " << R.dims() << std::endl);
          Tensor<T> T2(d);
          T2.quantizer = R.quantizer;
          for (int i = 0; i < d[0]; ++i)
            for (int j = 0; j < d[1]; ++j)
              T2[j * d[0] + i] = R(i, j);
          swap(R, T2);
          R.setTransposed(true);
        }
      }
    }
  }
}

template<typename T> void Model<T>::reshapeConv2DFilters()
{
  std::vector<int> diff_conv_ids;
  for (auto &v: m_data)
  {
    if (v.layer->op() == layers::OperationType::Conv2D)   //  || v.layer->op() == layers::OperationType::Conv2DTranspose )
    {
      if (v.layer->inputsId().size() != 2)
      {
        std::cerr << "[ERROR] cannot find input 2 for reshapeConv2DFilters" << std::endl;
        assert(false);
        exit(-1);
      }
      // avoid repeated reshape operations
      if (std::find(diff_conv_ids.begin(), diff_conv_ids.end(), v.layer->inputsId()[1]) == diff_conv_ids.end())
      {
        diff_conv_ids.push_back(v.layer->inputsId()[1]);
      }
      else
      {
        continue;
      }
      auto &L = getLayer(v.layer->inputsId()[1]);
      auto &W = L.layer->output();
      // invert k and l dimensions
      Dimensions d = W.dims();
      if (d.size() != 4)
      {
        std::cerr << "[ERROR] invalid dim in reshapeConv2DFilters" << std::endl;
        assert(false);
        exit(-1);
      }
      auto tmp = d[2];
      d[2]     = d[3];
      d[3]     = tmp;
      SADL_DBG(std::cout << "[INFO] reshape " << L.layer->id() << ' ' << L.layer->name() << " " << W.dims() << " => " << d << std::endl);
      Tensor<T> T2(d);
      T2.quantizer = W.quantizer;
      for (int i = 0; i < d[0]; ++i)
        for (int j = 0; j < d[1]; ++j)
          for (int k = 0; k < d[2]; ++k)
            for (int l = 0; l < d[3]; ++l)
              T2(i, j, k, l) = W(i, j, l, k);
      swap(W, T2);
    }
  }
}

template<typename T> std::vector<Tensor<T>> Model<T>::getInputsTemplate() const
{
  assert(!m_data.empty());
  std::vector<Tensor<T>> v;

  for (auto &id_input: m_ids_input)
  {
    auto &L_tmp = getLayer(id_input);
    if (L_tmp.layer->op() == layers::OperationType::Placeholder)
    {
      const auto &L = dynamic_cast<const layers::Placeholder<T> &>(*L_tmp.layer);
      Tensor<T>   t;
      t.resize(L.dims());
      t.quantizer = L.quantizer();
      v.push_back(t);
    }
  }
  return v;
}

}   // namespace sadl
