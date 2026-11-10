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
#include "layer.h"

namespace sadl
{
namespace layers
{
template<typename T> class Where : public Layer<T>
{
public:
  using Layer<T>::Layer;
  using Layer<T>::m_out;   // to avoid this->
  using Layer<T>::m_initDone;

  virtual bool apply(std::vector<Tensor<T> *> &in) override;
  virtual bool init(const std::vector<Tensor<T> *> &in) override;
  virtual bool mutateInput() const override { return true; }

protected:
  virtual bool loadInternal(std::istream &file, Version) override;
  DUMP_MODEL_EXT;
};

template<typename T> bool Where<T>::apply(std::vector<Tensor<T> *> &in)
{
  assert(in.size() == 3);
  if (in[0]->size() != 1)
  {
    assert(in[0]->dims() == m_out.dims());
    assert(in[0]->dims() == in[1]->dims() || (in[1]->dims().size() == 1 && in[1]->dims()[0] == 1));
    assert(in[0]->dims() == in[2]->dims() || (in[2]->dims().size() == 1 && in[2]->dims()[0] == 1));
  }
  else
  {
    assert(in[1]->dims() == m_out.dims());
    assert(in[1]->dims() == in[2]->dims());
  }
  const Tensor<T> &condition = *in[0];
  if (condition.size() == 1)
  {
    if (condition[0])
    {
      swap(*in[1], m_out);
    }
    else
    {
      swap(*in[2], m_out);
    }
  }
  else
  {
    const Tensor<T> &A = *in[1];
    const Tensor<T> &B = *in[2];
    m_out.quantizer = A.quantizer > B.quantizer ? A.quantizer : B.quantizer;
    for (int i = 0; i < m_out.size(); i++)
    {
      const T A_i = (A.dims().size() == 1) ? A[0] : A[i];
      const T B_i = (B.dims().size() == 1) ? B[0] : B[i];
      typename ComputationType<T>::type z = condition[i] ? A_i : B_i;
      const int z_q = condition[i] ? A.quantizer : B.quantizer ;
      ComputationType<T>::shift_left(z, m_out.quantizer - z_q);
      COUNTERS(z);
      m_out[i] = static_cast<T>(z);
    }
  }
  return true;
}


template<typename T> bool Where<T>::init(const std::vector<Tensor<T> *> &in)
{
  if (in.size() != 3)
    return false;
  if (in[0]->size() == 1)//condition dims
    m_out.resize(in[1]->dims());
  else
    m_out.resize(in[0]->dims());
  m_initDone = true;
  return true;
}

template<typename T> bool Where<T>::loadInternal(std::istream &file, Version)
{
  return true;
}

}   // namespace layers
}   // namespace sadl
