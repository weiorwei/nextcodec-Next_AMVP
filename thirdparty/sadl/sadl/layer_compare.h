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
enum class Compare_mode  
{
    LessThan,
    GreaterThan,
    EqualTo
};
template<typename T> class Compare : public Layer<T>
{
public:
  using Layer<T>::Layer;
  using Layer<T>::m_out;   // to avoid this->
  using Layer<T>::m_initDone;

  virtual bool apply(std::vector<Tensor<T> *> &in) override;
  virtual bool init(const std::vector<Tensor<T> *> &in) override;

protected:
  virtual bool loadInternal(std::istream &file, Version) override;
  bool apply_less(std::vector<Tensor<T> *> &in);
  bool apply_greater(std::vector<Tensor<T> *> &in);
  bool apply_equal_to(std::vector<Tensor<T> *> &in);

  Compare_mode m_mode;             
  DUMP_MODEL_EXT;
};

template<typename T> bool Compare<T>::apply(std::vector<Tensor<T> *> &in)
{
  assert(in.size() == 2);
  assert(in[0]->dims() == m_out.dims() || (in[0]->dims().size() == 1 && in[0]->dims()[0] == 1));
  assert(in[1]->dims() == m_out.dims() || (in[1]->dims().size() == 1 && in[1]->dims()[0] == 1));
  if(m_mode == Compare_mode::LessThan)
    return apply_less(in);
  else if(m_mode == Compare_mode::GreaterThan)
    return apply_greater(in);
  else if(m_mode == Compare_mode::EqualTo)
    return apply_equal_to(in);
  else return false;
}

template<typename T> bool Compare<T>::apply_less(std::vector<Tensor<T> *> &in)
{
  const Tensor<T> &A = *in[0];
  const Tensor<T> &B = *in[1];
  const int &A_q = A.quantizer;
  const int &B_q = B.quantizer;
  const int A_shift = std::max(0, B_q - A_q);
  const int B_shift = std::max(0, A_q - B_q);
  m_out.quantizer = 0;// bool tensor
  if(B.dims().size() == 1)
  {
    for (int i = 0; i < m_out.size(); i++)
    {
      T A_i = A[i];
      T B_i = B[0];
      ComputationType<T>::shift_left(A_i, A_shift);//quantization
      ComputationType<T>::shift_left(B_i, B_shift);//quantization
      T z = A_i < B_i;
      COUNTERS(z);
      m_out[i] = z;
    }
  }

  else
  {
    for (int i = 0; i < m_out.size(); i++)
    {
      T A_i = A[i];
      T B_i = B[i];
      ComputationType<T>::shift_left(A_i, A_shift);//quantization
      ComputationType<T>::shift_left(B_i, B_shift);//quantization
      T z = A_i < B_i;
      COUNTERS(z);
      m_out[i] = z;
    }
  }
  return true;
}

template<typename T> bool Compare<T>::apply_greater(std::vector<Tensor<T> *> &in)
{
  const Tensor<T> &A = *in[0];
  const Tensor<T> &B = *in[1];
  const int &A_q = A.quantizer;
  const int &B_q = B.quantizer;
  const int A_shift = std::max(0, B_q - A_q);
  const int B_shift = std::max(0, A_q - B_q);
  m_out.quantizer = 0;// bool tensor
  if(B.dims().size() == 1)
  {
    for (int i = 0; i < m_out.size(); i++)
    {
      T A_i = A[i];
      T B_i = B[0];
      ComputationType<T>::shift_left(A_i, A_shift);//quantization
      ComputationType<T>::shift_left(B_i, B_shift);//quantization
      T z = A_i > B_i;
      COUNTERS(z);
      m_out[i] = z;
    }
  }

  else
  {
    for (int i = 0; i < m_out.size(); i++)
    {
      T A_i = A[i];
      T B_i = B[i];
      ComputationType<T>::shift_left(A_i, A_shift);//quantization
      ComputationType<T>::shift_left(B_i, B_shift);//quantization
      T z = A_i > B_i;
      COUNTERS(z);
      m_out[i] = z;
    }
  }
  return true;
}

template<typename T> bool Compare<T>::apply_equal_to(std::vector<Tensor<T> *> &in)
{
#if DEBUG_MODEL
  if constexpr (std::is_same<T, float>::value)
  {
    static bool once = true;
    if (once)
    {
      std::cout << "[WARNING] using equal layer with float: unexpected results can occur" << std::endl;
    }
  once = false;
  }
#endif
  const Tensor<T> &A = *in[0];
  const Tensor<T> &B = *in[1];
  const int &A_q = A.quantizer;
  const int &B_q = B.quantizer;
  const int A_shift = std::max(0, B_q - A_q);
  const int B_shift = std::max(0, A_q - B_q);
  m_out.quantizer = 0;// bool tensor
  if(B.dims().size() == 1)
  {
    for (int i = 0; i < m_out.size(); i++)
    {
      T A_i = A[i];
      T B_i = B[0];
      ComputationType<T>::shift_left(A_i, A_shift);//quantization
      ComputationType<T>::shift_left(B_i, B_shift);//quantization
      T z = A_i == B_i;
      COUNTERS(z);
      m_out[i] = z;
    }
  }
  else
  {
    for (int i = 0; i < m_out.size(); i++)
    {
      T A_i = A[i];
      T B_i = B[i];
      ComputationType<T>::shift_left(A_i, A_shift);//quantization
      ComputationType<T>::shift_left(B_i, B_shift);//quantization
      T z = A_i == B_i;
      COUNTERS(z);
      m_out[i] = z;
    }
  }
  return true;
}

template<typename T> bool Compare<T>::init(const std::vector<Tensor<T> *> &in)
{
  if (in.size() != 2)
    return false;
  m_out.resize(in[0]->dims());
  m_initDone = true;
  return true;
}

template<typename T> bool Compare<T>::loadInternal(std::istream &file, Version)
{
  int32_t x = 0;
  file.read((char *) &x, sizeof(x));
  if(x == (int32_t) Compare_mode::LessThan)
    m_mode = Compare_mode::LessThan;
  else if(x == (int32_t) Compare_mode::GreaterThan)
    m_mode = Compare_mode::GreaterThan;
  else if(x == (int32_t) Compare_mode::EqualTo)
    m_mode = Compare_mode::EqualTo;
  else
  {
    std::cerr << "[ERROR] invalid mode: " << x << std::endl;
    return false;
  }
  SADL_DBG(std::cout << "  - mode: " << x << std::endl);
  return true;
}

}   // namespace layers
}   // namespace sadl
