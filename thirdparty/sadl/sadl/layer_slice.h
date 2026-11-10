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
template<typename T> class Slice : public Layer<T>
{
public:
  using Layer<T>::Layer;
  using Layer<T>::m_out;   // to avoid this->
  using Layer<T>::m_initDone;

  virtual bool apply(std::vector<Tensor<T> *> &in) override;
  virtual bool init(const std::vector<Tensor<T> *> &in) override;

protected:
  virtual bool loadInternal(std::istream &file, Version v) override;
  int32_t      m_start_h;
  int32_t      m_end_h;
  int32_t      m_start_w;
  int32_t      m_end_w;
  int32_t      m_start_c;
  int32_t      m_end_c;
  int32_t      m_init[6]={};
  DUMP_MODEL_EXT;
};

template<typename T> bool Slice<T>::apply(std::vector<Tensor<T> *> &in)
{
  assert(in.size() == 1);
  const Tensor<T> &A = *in[0];
  //int              in_H{ A.dims()[1] };
  //int              in_W{ A.dims()[2] };
  //const int        in_D{ A.dims()[3] };
  constexpr int    im_nb   = 0;
  int              end_h = m_end_h;
  int              end_w = m_end_w;
  int              end_c = m_end_c;
  
  m_out.quantizer = A.quantizer;

  if (m_out.dims().size() == 4) {
    for (int im_i = m_start_h; im_i < end_h; im_i++)
    {
      for (int im_j = m_start_w; im_j < end_w; im_j++)
      {
        for (int im_d = m_start_c; im_d < end_c; im_d++)
        {
          m_out(im_nb, im_i - m_start_h, im_j - m_start_w, im_d - m_start_c) = A(im_nb, im_i, im_j, im_d);
        }
      }
    }
  } else if (m_out.dims().size() == 2) {
    for (int im_d = m_start_c; im_d < end_c; im_d++)
      m_out(im_nb, im_d - m_start_c) = A(im_nb, im_d);
  } else {
    return false;
  }
  return true;
}

template<typename T> bool Slice<T>::init(const std::vector<Tensor<T> *> &in)
{
  constexpr int pow2_31 = std::numeric_limits<int>::max();
  if (in.size() != 1)
    return false;
  SADL_DBG(std::cout << " - input Slice " << in[0]->dims() << std::endl);

  Dimensions dim;
  dim.resize(in[0]->dims().size());
  dim[0] = in[0]->dims()[0];

  m_start_h = m_init[0];
  m_start_w = m_init[2];
  m_start_c = m_init[4];
  
  m_end_h = m_init[1];
  m_end_w = m_init[3];
  m_end_c = m_init[5];
  // ONNX is sending 2^31 - 1 as value if end index is last channel
  if (dim.size() == 4) {
    if (m_end_h == pow2_31)
    {
      m_end_h = in[0]->dims()[1];
    } else if ( m_end_h < 0) {
      m_end_h = in[0]->dims()[1]+m_end_h;
    }
    dim[1] = m_end_h - m_start_h;
    if (m_end_w == pow2_31)
    {
      m_end_w = in[0]->dims()[2];
    } else if ( m_end_w < 0 ) {
      m_end_w = in[0]->dims()[2]+m_end_w;
    }
    dim[2] = m_end_w - m_start_w;
    if (m_end_c == pow2_31)
    {
      m_end_c = in[0]->dims()[3];
    } else if (m_end_c<0) {
      m_end_c = in[0]->dims()[3]+m_end_c;
    }
    dim[3] = m_end_c - m_start_c;
  } else if (dim.size() == 2) {
    if (
      m_start_h != 0 || m_end_h != pow2_31 ||
      m_start_w != 0 || m_end_w != pow2_31
    )
      return false;

    if (m_end_c == pow2_31)
    {
      m_end_c = in[0]->dims()[1];
    } else if (m_end_c<0) {
      m_end_c = in[0]->dims()[1]+m_end_c;
    }
    dim[1] = m_end_c - m_start_c;
  } else {
    return false;
  }

  m_out.resize(dim);
  SADL_DBG(std::cout << "  - output Slice: " << m_out.dims() << std::endl);

  m_initDone = true;
  return true;
}

template<typename T> bool Slice<T>::loadInternal(std::istream &file, Version v)
{
  if ((int)v <= (int)Version::sadl03 ) {
	  constexpr int pow2_31 = std::numeric_limits<int>::max();
	  m_init[0]=m_init[2]=m_init[4]=0;
	  m_init[1]=m_init[3]=m_init[5]=pow2_31;

	  file.read((char *) &m_init[0], sizeof(int32_t));
	  SADL_DBG(std::cout << "  - start_c: " << m_init[0] << std::endl);
	  file.read((char *) &m_init[1], sizeof(int32_t));
	  SADL_DBG(std::cout << "  - end_c: " << m_init[1] << std::endl);
	  return true;
  }
  file.read((char *) &m_init[0], sizeof(int32_t));
  SADL_DBG(std::cout << "  - start_h: " << m_init[0] << std::endl);

  file.read((char *) &m_init[1], sizeof(int32_t));
  SADL_DBG(std::cout << "  - end_h: " << m_init[1] << std::endl);

  file.read((char *) &m_init[2], sizeof(int32_t));
  SADL_DBG(std::cout << "  - start_w: " << m_init[2] << std::endl);

  file.read((char *) &m_init[3], sizeof(int32_t));
  SADL_DBG(std::cout << "  - end_w: " << m_init[3] << std::endl);

  file.read((char *) &m_init[4], sizeof(int32_t));
  SADL_DBG(std::cout << "  - start_c: " << m_init[4] << std::endl);

  file.read((char *) &m_init[5], sizeof(int32_t));
  SADL_DBG(std::cout << "  - end_c: " << m_init[5] << std::endl);

  return true;
}

}   // namespace layers
}   // namespace sadl
