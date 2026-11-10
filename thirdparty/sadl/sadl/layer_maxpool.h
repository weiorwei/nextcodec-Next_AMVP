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
template<typename T> class MaxPool : public Layer<T>
{
public:
  using Layer<T>::Layer;
  using Layer<T>::m_out;   // to avoid this->
  using Layer<T>::m_initDone;

  virtual bool apply(std::vector<Tensor<T> *> &in) override;
  virtual bool init(const std::vector<Tensor<T> *> &in) override;

protected:
  virtual bool loadInternal(std::istream &file, Version v) override;
  Dimensions   m_kernel;
  Dimensions   m_strides;
  Dimensions   m_pads;
  DUMP_MODEL_EXT;
};

// assume data in in[0]
// data [batch, in_height, in_width, in_channels]
// kernel [1, kernel_height, kernel_width, 1]
// stride [1, stride_height, stride_width, 1]
template<typename T> bool MaxPool<T>::apply(std::vector<Tensor<T> *> &in)
{
  assert(in.size() == 1);
  assert(in[0]->dims().size() == 4);

  const Tensor<T> &A            = *in[0];
  const int        N            = m_out.dims()[0];
  const int        H            = m_out.dims()[1];
  const int        W            = m_out.dims()[2];
  const int        D            = m_out.dims()[3];
  const int        offset_end   = m_kernel[1] / 2;
  const int        offset_start = m_kernel[1] - 1 - offset_end;
  const int        step         = m_strides[1];

  // currently adhoc start
  int start = offset_start;
  
  m_out.quantizer   = in[0]->quantizer;     // adapt output width to bias

  for (int im_nb = 0; im_nb < N; ++im_nb)
  {
    // loop on out
    for (int im_i = 0; im_i < H; ++im_i)
    {
      for (int im_j = 0; im_j < W; ++im_j)
      {
        for (int im_d = 0; im_d < D; ++im_d)
        {
          T xx = -std::numeric_limits<T>::max();
          for (int filter_i = -offset_start; filter_i <= offset_end; ++filter_i)
          {
            for (int filter_j = -offset_start; filter_j <= offset_end; ++filter_j)
            {
              int ii = im_i * step + filter_i + start;
              int jj = im_j * step + filter_j + start;
              if (A.in(im_nb, ii, jj, im_d))
              {
                T x = A(im_nb, ii, jj, im_d);
                if (xx < x)
                  xx = x;
              }
            }
          }
          m_out(im_nb, im_i, im_j, im_d) = xx;
        }
      }
    }
  }

  return true;
}

// data [batch, in_height, in_width, in_channels]
// kernel [filter_height, filter_width, in_channels, out_channels]
template<typename T> bool MaxPool<T>::init(const std::vector<Tensor<T> *> &in)
{
  if (in.size() != 1)
    return false;
  SADL_DBG(std::cout << "  - input maxpool: " << in[0]->dims() << std::endl);
  SADL_DBG(std::cout << "  - stride: " << m_strides << std::endl);
  SADL_DBG(std::cout << "  - kernel: " << m_kernel << std::endl);
  if (in[0]->dims().size() != 4)
    return false;

  // convervative check
  if (m_kernel.size() != 4)
    return false;
  // no pooling on batch and depth
  if (m_kernel[0] != 1 || m_kernel[3] != 1)
    return false;

  // no stride on batch and depth
  if (m_strides.size() != 4)
    return false;
  if (m_strides[0] != 1 || m_strides[3] != 1)
    return false;

  // square filter
  if (m_kernel[1] != m_kernel[2])
    return false;
  // square stride
  if (m_strides[1] != m_strides[2])
    return false;

  Dimensions dim;

  dim.resize(4);
  dim[0]                   = in[0]->dims()[0];
  constexpr int dilatation = 1;
  dim[1]                   = (int) floor((in[0]->dims()[1] + m_pads[0] + m_pads[2] - ((m_kernel[1] - 1) * dilatation + 1)) / (float) m_strides[1] + 1);
  dim[2]                   = (int) floor((in[0]->dims()[2] + m_pads[1] + m_pads[3] - ((m_kernel[2] - 1) * dilatation + 1)) / (float) m_strides[2] + 1);
  dim[3]                   = in[0]->dims()[3];

  m_out.resize(dim);
  SADL_DBG(std::cout << "  - output: " << m_out.dims() << std::endl);

  m_initDone = true;
  return true;
}

template<typename T> bool MaxPool<T>::loadInternal(std::istream &file, Version v)
{
  // load values
  int32_t x = 0;
  file.read((char *) &x, sizeof(x));
  if (x <= 0 || x > Dimensions::MaxDim)
  {
    std::cerr << "[ERROR] invalid nb of dimensions strides: " << x << std::endl;
    return false;
  }
  m_strides.resize(x);
  for (int k = 0; k < m_strides.size(); ++k)
  {
    file.read((char *) &x, sizeof(x));
    m_strides[k] = x;
  }
  SADL_DBG(std::cout << "  - strides: " << m_strides << std::endl);
  if (m_strides.size() != 4)
  {
    std::cerr << "[ERROR] invalid strides: " << m_strides.size() << std::endl;
    return false;
  }
  if (m_strides[0] != 1)
  {
    std::cerr << "[ERROR] invalid strides[0]: " << m_strides[0] << std::endl;
    return false;
  }
  if (m_strides[3] != 1)
  {
    std::cerr << "[ERROR] invalid strides[3]: " << m_strides[3] << std::endl;
    return false;
  }
  if (m_strides[1] != m_strides[2])
  {
    std::cerr << "[ERROR] invalid stride H Vs: " << m_strides << std::endl;
    return false;
  }

  x = 0;
  file.read((char *) &x, sizeof(x));
  if (x <= 0 || x > Dimensions::MaxDim)
  {
    std::cerr << "[ERROR] invalid nb of dimensions kernel: " << x << std::endl;
    return false;
  }
  m_kernel.resize(x);
  for (int k = 0; k < m_kernel.size(); ++k)
  {
    file.read((char *) &x, sizeof(x));
    m_kernel[k] = x;
  }
  SADL_DBG(std::cout << "  - kernel: " << m_kernel << std::endl);
  if (m_kernel.size() != 4)
  {
    std::cerr << "[ERROR] invalid kernel: " << m_kernel.size() << std::endl;
    return false;
  }
  if (m_kernel[0] != 1)
  {
    std::cerr << "[ERROR] invalid kernel[0]: " << m_kernel[0] << std::endl;
    return false;
  }
  if (m_kernel[3] != 1)
  {
    std::cerr << "[ERROR] invalid kernel[3]: " << m_kernel[3] << std::endl;
    return false;
  }
  if (m_kernel[1] != m_kernel[2])
  {
    std::cerr << "[ERROR] invalid kernel H V: " << m_kernel << std::endl;
    return false;
  }
  file.read((char *) &x, sizeof(x));
  if (x <= 0 || x > Dimensions::MaxDim)
  {
    std::cerr << "[ERROR] invalid nb of dimensions: " << x << std::endl;
    return false;
  }
  m_pads.resize(x);
  for (int k = 0; k < m_pads.size(); ++k)
  {
    file.read((char *) &x, sizeof(x));
    m_pads[k] = x;
  }
  SADL_DBG(std::cout << "  - pads: " << m_pads << std::endl);
  return true;
}

}   // namespace layers
}   // namespace sadl
