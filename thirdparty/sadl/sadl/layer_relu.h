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
#include "layer.h"


#if __AVX512BW__ || __AVX2__
#include <immintrin.h>
#endif

namespace sadl
{
namespace layers
{
template<typename T> class Relu : public Layer<T>
{
public:
  using Layer<T>::Layer;
  using Layer<T>::m_out;   // to avoid this->
  using Layer<T>::m_initDone;

  virtual bool apply(std::vector<Tensor<T> *> &in) override;
  virtual bool init(const std::vector<Tensor<T> *> &in) override;
  virtual bool mutateInput() const override { return true; }

protected:
  virtual bool loadInternal(std::istream &file, Version v) override;
};

template<typename T> bool Relu<T>::apply(std::vector<Tensor<T> *> &in)
{
  assert(in.size() == 1);
  assert(in[0]->dims() == m_out.dims());
  swap(*in[0], m_out);
  for (auto &x: m_out)
    x = (x < 0) ? 0 : x;
  return true;
}

template<> inline bool Relu<int16_t>::apply(std::vector<Tensor<int16_t> *> &in)
{
  assert(in.size() == 1);
  assert(in[0]->dims() == m_out.dims());
  swap(*in[0], m_out);
  const int size = static_cast<int>(m_out.size());

#if __AVX512BW__ || __AVX2__
  int16_t* data = m_out.data();
#if __AVX512BW__
  const int simdSize = static_cast<int>(size - (size % 32));  // Process 32 elements per iteration
  __m512i zeros = _mm512_setzero_si512();
  for (int i = 0; i < simdSize; i += 32)
  {
      __m512i x = _mm512_loadu_si512(reinterpret_cast<const __m512i*>(data + i));
      __m512i result = _mm512_max_epi16(x, zeros);
      _mm512_storeu_si512(reinterpret_cast<__m512i*>(data + i), result);
  }
#elif __AVX2__
  const int simdSize = static_cast<int>(size - (size % 16));  // Process 16 elements per iteration
  __m256i zeros = _mm256_setzero_si256();
  for (int i = 0; i < simdSize; i += 16)
  {   
      __m256i x = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(data + i));   
      __m256i result = _mm256_max_epi16(x, zeros);
      _mm256_storeu_si256(reinterpret_cast<__m256i*>(data + i), result);
  }
#endif

  // Handle remaining elements without branching
  for (int i = simdSize; i < size; ++i)
  {
#else
  for (int i = 0; i < size; ++i) 
  {
#endif
    m_out[i] = (m_out[i] < 0) ? 0 : m_out[i];
  }
  return true;
}

template<typename T> bool Relu<T>::init(const std::vector<Tensor<T> *> &in)
{
  if (in.size() != 1)
    return false;
  m_out.resize(in[0]->dims());
  m_initDone = true;
  return true;
}

template<typename T> bool Relu<T>::loadInternal(std::istream &, Version) { return true; }

}   // namespace layers
}   // namespace sadl
