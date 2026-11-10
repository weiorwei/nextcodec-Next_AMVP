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

namespace sadl
{
namespace layers
{
template<typename T> class ScatterND : public Layer<T>
{
public:
  using Layer<T>::Layer;
  using Layer<T>::m_out;   // to avoid this->
  using Layer<T>::m_initDone;

  virtual bool apply(std::vector<Tensor<T> *> &in) override;
  virtual bool init(const std::vector<Tensor<T> *> &in) override;

protected:
  virtual bool loadInternal(std::istream &file, Version v) override;
};

template<typename T> bool ScatterND<T>::apply(std::vector<Tensor<T> *> &in)
{
  assert(in.size() == 3);
  const Tensor<T> &data    = *in[0];
  const Tensor<T> &updates = *in[1];
  const Tensor<T> &indices = *in[2];
  assert(indices.dims().size() == 4);
  const int dim_H{ indices.dims()[0] };
  const int dim_W{ indices.dims()[1] };
  const int dim_C{ indices.dims()[2] };

  std::copy(data.begin(), data.end(), m_out.begin());
  m_out.quantizer = data.quantizer;

  int index_C, index_H, index_W;
  for (int h = 0; h < dim_H; h++)
  {
    for (int w = 0; w < dim_W; w++)
    {
      for (int c = 0; c < dim_C; c++)
      {
        index_H                             = (int)indices(h, w, c, 1);
        index_W                             = (int)indices(h, w, c, 2);
        index_C                             = (int)indices(h, w, c, 3);
        m_out(0, index_H, index_W, index_C) = updates(0, h, w, c);   // n==1
      }
    }
  }

  return true;
}

template<typename T> bool ScatterND<T>::init(const std::vector<Tensor<T> *> &in)
{
  if (in.size() != 3)
  {
    std::cerr << "[ERROR] The input size must be 3 in the ScatterND." << std::endl;
    return false;
  }
  m_out.resize(in[0]->dims());   // data
  m_initDone = true;

  return true;
}

template<typename T> bool ScatterND<T>::loadInternal(std::istream &file, sadl::Version v) { return true; }
}   // namespace layers
}   // namespace sadl