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
#if __AVX2__
#include <immintrin.h>
#endif

namespace sadl
{
namespace layers
{
template<typename T> template<int s_h, int s_w> void Conv2D<T>::conv2d_5x5_s(const Tensor<T> &A, const Tensor<T> &kernel)
{
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  const int     in_D{ A.dims()[3] };
  const int     nb_filters{ kernel.dims()[2] };
  constexpr int half_size_i{ 5 / 2 };
  constexpr int half_size_j{ 5 / 2 };
  assert(half_size_i == m_pads[0]);
  assert(half_size_j == m_pads[1]);
  constexpr int start_h{ 0 };
  constexpr int start_w{ 0 };
#if DEBUG_SIMD && __AVX2__
  std::cout << "\n[WARN] no SIMD version conv inD=" << in_D << " outD=" << nb_filters << " s=[" << s_w << ' ' << s_h << "] " << in_H << 'x' << in_W
            << " groups=" << m_groups << " " << in_D * kernel.dims()[0] * kernel.dims()[1] * nb_filters * (in_H / s_h) * (in_W / s_w) / 1000 << " kMAC"
            << std::endl;
#endif
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  constexpr int im_nb     = 0;
  const int     shift     = kernel.quantizer + m_q;
  const int     cout_by_g = nb_filters / m_groups;
  const int     cin_by_g  = in_D / m_groups;
  for (int filter = 0; filter < nb_filters; ++filter)
  {
    int offset = (filter / cout_by_g) * cin_by_g;
    for (int im_i = start_h; im_i < in_H; im_i += s_h)
    {
      for (int im_j = start_w; im_j < in_W; im_j += s_w)
      {
        typename ComputationType<T>::type x = 0;
        for (int filter_i = -half_size_i; filter_i <= half_size_i; ++filter_i)
        {
          // fixed
          for (int filter_j = -half_size_j; filter_j <= half_size_j; ++filter_j)
          {
            // fixed
            for (int filter_d = 0; filter_d < in_D / m_groups; ++filter_d)
            {
              int ii = im_i + filter_i;
              int jj = im_j + filter_j;
              int ki = half_size_i + filter_i;
              int kj = half_size_j + filter_j;
              if (A.in(im_nb, ii, jj, offset + filter_d))
              {
                x += (typename ComputationType<T>::type) A(im_nb, ii, jj, offset + filter_d) * kernel(ki, kj, filter, filter_d);
                COUNTERS_MAC(kernel(ki, kj, filter, filter_d));
              } else {
                COUNTERS_MAC_NOP(1);
              }
            }
          }
        }
        ComputationType<T>::quantize(x, shift);
        COUNTERS(x);
        SATURATE(x);
        m_out(im_nb, im_i / s_h, im_j / s_w, filter) = static_cast<T>(x);
      }
    }
  }
}

// NO SIMD yet
}   // namespace layers
}   // namespace sadl
