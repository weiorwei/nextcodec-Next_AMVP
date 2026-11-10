/* The copyright in this software is being made available under the BSD
 * License, included below. This software may be subject to other third party
 * and contributor rights, including patent rights, and no such rights are
 * granted under this license.
 *
 * Copyright (c) 2010-2023, ITU/ISO/IEC
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
#include <cmath>

#include "layer.h"

namespace sadl
{
namespace layers
{
template<typename T> class Const : public Layer<T>
{
public:
  using Layer<T>::Layer;
  using Layer<T>::m_out;   // to avoid this->
  using Layer<T>::m_initDone;

  virtual bool apply(std::vector<Tensor<T> *> &in) override;
  virtual bool init(const std::vector<Tensor<T> *> &in) override;

protected:
  virtual bool              loadInternal(std::istream &file, Version v) override;
  template<typename U> void readTensor(std::istream &file, Tensor<T> &out
    , const int32_t sizeSparse, const int32_t packedSparsitySize, Version v);
  DUMP_MODEL_EXT;
};

template<typename T> bool Const<T>::apply(std::vector<Tensor<T> *> &in)
{
  assert(in.size() == 0);
  (void) in;
  // assert(ptr==ptr)
  return true;
}

template<typename T> bool Const<T>::init(const std::vector<Tensor<T> *> &in)
{
  if (in.size() != 0)
    return false;
  m_initDone = true;
  return true;
}

template<typename T> template<typename U> void Const<T>::readTensor(std::istream &file, Tensor<T> &out, 
  const int32_t sizeSparse, const int32_t packedSparsitySize, Version v)
{
#if SPARSE_SUPPORT
  std::vector<T> &dataSparse = out.getDataSparse();
  std::vector<uint16_t> &indices = out.getIndices();
  std::vector<uint16_t> &nbNonzerosCol = out.getNbNonzerosCol();
#else
  std::vector<T> dataSparse;
  std::vector<uint16_t> indices;
  std::vector<uint16_t> nbNonzerosCol;
#endif
  if (sizeSparse > 0)
  {
#if !SPARSE_SUPPORT
    dataSparse.resize(sizeSparse);
    indices.resize(sizeSparse / packedSparsitySize);
    nbNonzerosCol.resize(out.dims()[1]);
#endif
    file.read((char*)nbNonzerosCol.data(), sizeof(uint16_t) * nbNonzerosCol.size());
    file.read((char*)indices.data(), sizeof(uint16_t) * indices.size());
    SADL_DBG(std::cout << "\t\t\t\t read sparse " << sizeof(U) * dataSparse.size() << ", " << sizeof(uint16_t) * indices.size() << ", " << nbNonzerosCol.size() * sizeof(uint16_t) << " sparsity packing: " << packedSparsitySize << std::endl);
  }
  T *dstData = (sizeSparse > 0) ? dataSparse.data() : out.data();
  size_t sizeData = (sizeSparse > 0) ? dataSparse.size(): out.size();
  if (std::is_same<T, U>::value)
  {
    file.read((char *) dstData, sizeof(T) * sizeData);
  }
  else
  {
    std::vector<U> data(sizeData);
    file.read((char *) data.data(), sizeof(U) * sizeData);
    for (int k = 0; k < (int) data.size(); ++k)
      dstData[k] = static_cast<T>(data[k]);
  }
#if !SPARSE_SUPPORT
  if (sizeSparse > 0)
  {
    out.redensifySparseData(dataSparse, nbNonzerosCol, packedSparsitySize, indices);
  }
#endif
}

template<typename T> bool Const<T>::loadInternal(std::istream &file, Version v)
{
  // load values
  int32_t x = 0;
  file.read((char *) &x, sizeof(x));
  if (x <= 0 || x > Dimensions::MaxDim)
  {
    std::cerr << "[ERROR] invalid nb of dimensions: " << x << std::endl;
    return false;
  }
  Dimensions d;
  d.resize(x);
  for (int k = 0; k < d.size(); ++k)
  {
    file.read((char *) &x, sizeof(x));
    d[k] = x;
  }

  if (d.nbElements() >= Tensor<T>::kMaxSize)
  {
    std::cerr << "[ERROR] tensor too large? " << d.nbElements() << std::endl;
    return false;
  }
  uint8_t isSparse = 0;
  int32_t sizeSparse = 0;
  int16_t packedSparsitySize = 1;
  if (v >= Version::sadl05)
  {
    file.read((char*)&isSparse, sizeof(uint8_t));
    if (isSparse != 0)
    {
      file.read((char*)&sizeSparse, sizeof(int32_t));
      file.read((char *)&packedSparsitySize, sizeof(packedSparsitySize));
    }
    bool transposed = false;
    file.read((char*)&transposed, sizeof(transposed));
    m_out.setTransposed(transposed);
  }
#if SPARSE_SUPPORT
  if (sizeSparse > 0) {
      m_out.resizeSparse(d, sizeSparse, packedSparsitySize);
  } else
#endif
  {
      m_out.resize(d);
  }
  SADL_DBG(std::cout << "  - tensor: " << m_out.dims() << std::endl);

  file.read((char *) &x, sizeof(x));

  // cannot check internal type because tensor also used by reshape etc.
  switch (x)
  {
  case TensorInternalType::Int32:
    // assert((std::is_same<T,int32_t>::value));
    file.read((char *) &m_out.quantizer, sizeof(m_out.quantizer));
    readTensor<int32_t>(file, m_out, sizeSparse, packedSparsitySize, v);
    break;
  case TensorInternalType::Float:
    // assert((std::is_same<T, float>::value));
    readTensor<float>(file, m_out, sizeSparse, packedSparsitySize, v);
    break;
  case TensorInternalType::Int16:
    // assert((std::is_same<T, int16_t>::value));
    file.read((char *) &m_out.quantizer, sizeof(m_out.quantizer));
    readTensor<int16_t>(file, m_out, sizeSparse, packedSparsitySize, v);
    break;
  default:
    std::cerr << "[ERROR] unknown internal type " << x << std::endl;
    return false;
  }

  SADL_DBG(std::cout << "  - data: "; for (int k = 0; k < 4 && k < m_out.size(); ++k) std::cout << m_out[k] << ' '; std::cout << " ...\n");
  SADL_DBG(std::cout << "  - quantizer: " << m_out.quantizer << std::endl);
  // SADL_DBG(std::cout<<m_out<<std::endl;)
  return true;
}

}   // namespace layers
}   // namespace sadl
