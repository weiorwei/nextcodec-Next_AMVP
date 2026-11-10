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
// ////////////////////////////////////////////////////////////////////////////////////////////////////////
// 3x3
// ////////////////////////////////////////////////////////////////////////////////////////////////////////
template<typename T> template<int s_h, int s_w> void Conv2D<T>::conv2d_3x3_s_peel(const Tensor<T> &A, const Tensor<T> &kernel)
{
  constexpr int im_nb      = 0;
  const int     shift      = kernel.quantizer + m_q;
  constexpr int ihalf_size = 1;
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  const int     nb_filters{ kernel.dims()[2] };
  constexpr int half_size_h{ ihalf_size };
  constexpr int half_size_w{ ihalf_size };
  const int     top{ m_pads[0] };
  const int     left{ m_pads[1] };
  const int     start_h{ half_size_h - top };
  const int     start_w{ half_size_w - left };
  const int     in_D{ A.dims()[3] };
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif

  for (int filter_nb = 0; filter_nb < nb_filters; ++filter_nb)
  {
    // corners
    {
      int  im_i;
      int  im_j;
      auto loop_with_cond = [&, filter_nb, shift](int i0, int i1, int j0, int j1)
      {
        typename ComputationType<T>::type x = 0;
        for (int filter_i = i0; filter_i <= i1; ++filter_i)
        {
          for (int filter_j = j0; filter_j <= j1; ++filter_j)
          {
            for (int filter_d = 0; filter_d < in_D; ++filter_d)
            {
              int ii = im_i + filter_i;
              int jj = im_j + filter_j;
              int ki = ihalf_size + filter_i;
              int kj = ihalf_size + filter_j;
              x += (typename ComputationType<T>::type) A(im_nb, ii, jj, filter_d) * kernel(ki, kj, filter_nb, filter_d);
              COUNTERS_MAC(kernel(ki, kj, filter_nb, filter_d));
            }
          }
        }
        ComputationType<T>::quantize(x, shift);
        COUNTERS(x);
        SATURATE(x);
        COUNTERS_MAC_NOP(in_D*(3*3-(i1-i0+1)*(j1-j0+1)));
        m_out(im_nb, im_i / s_h, im_j / s_w, filter_nb) = static_cast<T>(x);
      };

      im_j = start_w;
      if (im_j < in_W)
      {   // left side
        im_i = start_h;
        if (im_i < in_H)
        {   // top left corner
          loop_with_cond(-start_h, ihalf_size, -start_w, ihalf_size);
        }
        im_i = ((in_H - ihalf_size - start_h) / s_h) * s_h + start_h;
        if (im_i > 0 && im_i < in_H && im_i != start_h)
        {   // bottom left corner
          const int end_i = (im_i + 1 < in_H) ? 1 : 0;
          loop_with_cond(-ihalf_size, end_i, -start_w, ihalf_size);
        }
      }

      im_j            = ((in_W - ihalf_size - start_w) / s_w) * s_w + start_w;
      const int end_j = (im_j + 1 < in_W) ? 1 : 0;
      if (im_j > 0 && im_j < in_W && im_j != start_w)
      {   // rihgt side
        im_i = start_h;
        if (im_i < in_H)
        {   // top right corner
          loop_with_cond(-start_h, ihalf_size, -ihalf_size, end_j);
        }

        im_i = ((in_H - ihalf_size - start_h) / s_h) * s_h + start_h;
        if (im_i > 0 && im_i < in_H && im_i != start_h)
        {   // bottom right corner
          const int end_i = (im_i + 1 < in_H) ? 1 : 0;
          loop_with_cond(-ihalf_size, end_i, -ihalf_size, end_j);
        }
      }
    }

    // vertical borders
    {
      for (int im_i = start_h + s_h; im_i < in_H - ihalf_size; im_i += s_h)
      {
        int im_j = start_w;   // can be only 0 or 1
        if (im_j < in_W)
        {   // left side
          typename ComputationType<T>::type x = 0;
          for (int filter_i = -ihalf_size; filter_i <= ihalf_size; ++filter_i)
          {
            for (int filter_j = -start_w; filter_j <= ihalf_size; ++filter_j)
            {
              for (int filter_d = 0; filter_d < in_D; ++filter_d)
              {
                int ii = im_i + filter_i;
                int jj = im_j + filter_j;
                int ki = ihalf_size + filter_i;
                int kj = ihalf_size + filter_j;
                x += (typename ComputationType<T>::type) A(im_nb, ii, jj, filter_d) * kernel(ki, kj, filter_nb, filter_d);
                COUNTERS_MAC(kernel(ki, kj, filter_nb, filter_d));
              }
            }
          }
          ComputationType<T>::quantize(x, shift);
          COUNTERS(x);
          SATURATE(x);
          COUNTERS_MAC_NOP(in_D*(3*3-3*(ihalf_size+start_w+1)));
          m_out(im_nb, im_i / s_h, im_j / s_w, filter_nb) = static_cast<T>(x);
        }

        im_j = ((in_W - ihalf_size - start_w) / s_w) * s_w + start_w;
        if (im_j > 0 && im_j < in_W && im_j != start_w)
        {   // rihgt side
          typename ComputationType<T>::type x          = 0;
          const int                         end_filter = (im_j + 1) < in_W ? 1 : 0;
          for (int filter_i = -ihalf_size; filter_i <= ihalf_size; ++filter_i)
          {
            for (int filter_j = -ihalf_size; filter_j <= end_filter; ++filter_j)
            {
              for (int filter_d = 0; filter_d < in_D; ++filter_d)
              {
                int ii = im_i + filter_i;
                int jj = im_j + filter_j;
                int ki = ihalf_size + filter_i;
                int kj = ihalf_size + filter_j;
                x += (typename ComputationType<T>::type) A(im_nb, ii, jj, filter_d) * kernel(ki, kj, filter_nb, filter_d);
                COUNTERS_MAC(kernel(ki, kj, filter_nb, filter_d));
              }
            }
          }
          ComputationType<T>::quantize(x, shift);
          COUNTERS(x);
          SATURATE(x);
          COUNTERS_MAC_NOP(in_D*(3*3-3*(end_filter+ihalf_size+1)));
          m_out(im_nb, im_i / s_h, im_j / s_w, filter_nb) = static_cast<T>(x);
        }
      }
    }
    {
      // horizontal borders
      for (int im_j = s_w + start_w; im_j < in_W - ihalf_size; im_j += s_w)
      {
        int im_i = start_h;   // 0 or 1 -> adapt filter start
        if (im_i < in_H)
        {   // top line
          typename ComputationType<T>::type x = 0;
          for (int filter_i = -start_h; filter_i <= ihalf_size; ++filter_i)
          {
            for (int filter_j = -ihalf_size; filter_j <= ihalf_size; ++filter_j)
            {
              for (int filter_d = 0; filter_d < in_D; ++filter_d)
              {
                int ii = im_i + filter_i;
                int jj = im_j + filter_j;
                int ki = ihalf_size + filter_i;
                int kj = ihalf_size + filter_j;
                x += (typename ComputationType<T>::type) A(im_nb, ii, jj, filter_d) * kernel(ki, kj, filter_nb, filter_d);
                COUNTERS_MAC(kernel(ki, kj, filter_nb, filter_d));
              }
            }
          }

          ComputationType<T>::quantize(x, shift);
          COUNTERS(x);
          SATURATE(x);
          COUNTERS_MAC_NOP(in_D*(3*3-3*(ihalf_size+start_h+1)));
          m_out(im_nb, im_i / s_h, im_j / s_w, filter_nb) = static_cast<T>(x);
        }
        im_i = ((in_H - ihalf_size - start_h) / s_h) * s_h + start_h;
        if (im_i > 0 && im_i < in_H && im_i != start_h)
        {   // bottom line
          typename ComputationType<T>::type x          = 0;
          const int                         end_filter = (im_i + 1) < in_H ? 1 : 0;
          for (int filter_i = -ihalf_size; filter_i <= end_filter; ++filter_i)
          {
            for (int filter_j = -ihalf_size; filter_j <= ihalf_size; ++filter_j)
            {
              for (int filter_d = 0; filter_d < in_D; ++filter_d)
              {
                int ii = im_i + filter_i;
                int jj = im_j + filter_j;
                int ki = ihalf_size + filter_i;
                int kj = ihalf_size + filter_j;
                x += (typename ComputationType<T>::type) A(im_nb, ii, jj, filter_d) * kernel(ki, kj, filter_nb, filter_d);
                COUNTERS_MAC(kernel(ki, kj, filter_nb, filter_d));
              }
            }
          }
          ComputationType<T>::quantize(x, shift);
          COUNTERS(x);
          SATURATE(x);
          COUNTERS_MAC_NOP(in_D*(3*3-3*(end_filter+ihalf_size+1)));
          m_out(im_nb, im_i / s_h, im_j / s_w, filter_nb) = static_cast<T>(x);
        }
      }
    }
  }   // filter_nb
}

template<typename T> template<int s_h, int s_w,int o_i,int o_j> void Conv2D<T>::conv2d_3x3_s_g1_core(const Tensor<T> &A, const Tensor<T> &kernel)
{

//  if (conv2d_core_alongJ<s_h, s_w,o_i,o_j>(A, kernel))
//  {
//    return;
//  }

  const int     nb_filters{ kernel.dims()[2] };
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  const int     in_D{ A.dims()[3] };
  constexpr int ihalf_size = 1;
  constexpr int           start_h{ ihalf_size };
  constexpr int           start_w{ ihalf_size };
  constexpr int im_nb     = 0;
  constexpr int half_size = 1;
  const int     shift     = kernel.quantizer + m_q;
#if DEBUG_SIMD && __AVX2__
  std::cout << "\n[WARN] generic version conv2d_3x3_g1_s_core inD=" << in_D << " outD=" << nb_filters << " s=[" << s_w << ' ' << s_h << "]  " << in_H << 'x' << in_W << " "
            << in_D * kernel.dims()[0] * kernel.dims()[1] * nb_filters * (in_H / s_h) * (in_W / s_w) / 1000 << " kMAC" << std::endl;
#endif
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  //assert(start_h + s_h - half_size_h >= 0);
 // assert(start_w + s_w - half_size_w >= 0);
  for (int im_i = start_h + s_h/2; im_i < in_H - start_h; im_i += s_h)
  {
    for (int im_j = start_w + s_w/2; im_j < in_W - start_w; im_j += s_w)
    {
      for (int filter = 0; filter < nb_filters; ++filter)
      {
        typename ComputationType<T>::type x = 0;
        for (int filter_i = -half_size; filter_i <= half_size; ++filter_i)
        {   // fixed
          for (int filter_j = -half_size; filter_j <= half_size; ++filter_j)
          {   // fixed
            for (int filter_d = 0; filter_d < in_D; ++filter_d)
            {
              int ii = im_i + filter_i;
              int jj = im_j + filter_j;
              int ki = half_size + filter_i;
              int kj = half_size + filter_j;
              x += (typename ComputationType<T>::type) A(im_nb, ii, jj, filter_d) * kernel(ki, kj, filter, filter_d);
              COUNTERS_MAC(kernel(ki, kj, filter, filter_d));
            }
          }
        }
        ComputationType<T>::quantize(x, shift);
        COUNTERS(x);
        SATURATE(x);
        m_out(im_nb, (im_i -o_i)/ s_h, (im_j - o_j )/ s_w , filter) = static_cast<T>(x);
      }
    }
  }
}

template<typename T> template<int s_h, int s_w,int o_i,int o_j> void Conv2D<T>::conv2d_3x3_s_g1_core_dispatch(const Tensor<T> &A, const Tensor<T> &kernel)
{
#if __AVX2__
#define CONV_MOD8   simd8_conv2d_3x3_s_g1_d
#define CONV_MOD16 simd16_conv2d_3x3_s_g1_d
#define CONV_MOD32 simd32_conv2d_3x3_s_g1_d
#else
#define CONV_MOD8 conv2d_3x3_s_g1_d_core
#define CONV_MOD16 conv2d_3x3_s_g1_d_core
#define CONV_MOD32 conv2d_3x3_s_g1_d_core
#endif
  const int in_D{ A.dims()[3] };

  switch (in_D)
  {
  case 1:
    conv2d_3x3_s_g1_d_core<1, s_h, s_w, o_i, o_j>(A, kernel);
    break;
  case 2:
    conv2d_3x3_s_g1_d_core<2, s_h, s_w, o_i, o_j>(A, kernel);
    break;
  case 4:
    conv2d_3x3_s_g1_d_core<4, s_h, s_w, o_i, o_j>(A, kernel);
    break;
  case 6:
    conv2d_3x3_s_g1_d_core<6, s_h, s_w, o_i, o_j>(A, kernel);
    break;
  case 8:
    CONV_MOD8<8, s_h, s_w, o_i, o_j>(A, kernel);
    break;
  case 16:
    CONV_MOD16<16, s_h, s_w, o_i, o_j>(A, kernel);
    break;
  case 24:
    CONV_MOD8<24, s_h, s_w, o_i, o_j>(A, kernel);
    break;
  case 32:
    CONV_MOD32<32, s_h, s_w, o_i, o_j>(A, kernel);
    break;
  case 48:
    CONV_MOD16<48, s_h, s_w, o_i, o_j>(A, kernel);
    break;
  case 64:
    CONV_MOD32<64, s_h, s_w, o_i, o_j>(A, kernel);
    break;
  case 72:
    CONV_MOD8<72, s_h, s_w, o_i, o_j>(A, kernel);   // better do 64 and than 8
    break;
  case 96:
    CONV_MOD32<96, s_h, s_w, o_i, o_j>(A, kernel);
    break;
  case 128:
    CONV_MOD32<128, s_h, s_w, o_i, o_j>(A, kernel);
    break;
  default:
    conv2d_3x3_s_g1_core<s_h, s_w, o_i, o_j>(A, kernel);
    break;
  }
#undef CONV_MOD8
#undef CONV_MOD16
#undef CONV_MOD32
}

template<typename T> template<int in_D, int s_h, int s_w,int o_i,int o_j> void Conv2D<T>::conv2d_3x3_s_g1_d_core(const Tensor<T> &A, const Tensor<T> &kernel)
{
  constexpr int im_nb     = 0;
  constexpr int half_size = 1;
  const int     shift     = kernel.quantizer + m_q;
  const int     nb_filters{ kernel.dims()[2] };
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  constexpr int ihalf_size = 1;
  constexpr int           start_h{  ihalf_size };
  constexpr int           start_w{ ihalf_size };

#if DEBUG_SIMD && __AVX2__
  std::cout << "\n[WARN] generic version conv2d_3x3_s_g1_d_core inD=" << in_D << " outD=" << nb_filters << " s=[" << s_w << ' ' << s_h << "]  " << in_H << 'x' << in_W << " "
            << in_D * kernel.dims()[0] * kernel.dims()[1] * nb_filters * (in_H / s_h) * (in_W / s_w) / 1000 << " kMAC" << std::endl;
#endif
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif

  for (int im_i = start_h + s_h/2; im_i < in_H - start_h; im_i += s_h)
  {
    for (int im_j = start_w + s_w/2; im_j < in_W - start_w; im_j += s_w)
    {
      for (int filter = 0; filter < nb_filters; ++filter)
      {
        typename ComputationType<T>::type x = 0;
        for (int filter_d = 0; filter_d < in_D; ++filter_d)
        {
          for (int filter_i = -half_size; filter_i <= half_size; ++filter_i)
          {   // fixed
            for (int filter_j = -half_size; filter_j <= half_size; ++filter_j)
            {   // fixed
              int ii = im_i + filter_i;
              int jj = im_j + filter_j;
              int ki = half_size + filter_i;
              int kj = half_size + filter_j;
              x += (typename ComputationType<T>::type) A(im_nb, ii, jj, filter_d) * kernel(ki, kj, filter, filter_d);
              COUNTERS_MAC(kernel(ki, kj, filter, filter_d));
            }
          }
        }
        ComputationType<T>::quantize(x, shift);
        COUNTERS(x);
        SATURATE(x);
        m_out(im_nb, (im_i -o_i)/ s_h, (im_j - o_j )/ s_w , filter) = static_cast<T>(x);
      }
    }
  }
}

// ////////////////////////////////////////////////////////////////////////////////////////////////////////
// 3x3
// ////////////////////////////////////////////////////////////////////////////////////////////////////////
///
#if __AVX2__
template<> template<int in_D, int s_h, int s_w,int o_i,int o_j> void Conv2D<float>::simd8_conv2d_3x3_s_g1_d(const Tensor<float> &A, const Tensor<float> &kernel)
{
  static_assert(in_D % 8 == 0, "Should be used with mod8 filters.");
  constexpr int im_nb     = 0;
  constexpr int half_size = 1;
  const int     nb_filters{ kernel.dims()[2] };
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  constexpr int ihalf_size = 1;
  constexpr int           start_h{ ihalf_size };
  constexpr int           start_w{ ihalf_size };

#if DEBUG_SIMD && __AVX512F__
  if (in_D >= 16)
  {
    std::cout << "\n[WARN] suboptimal SIMD8 version conv simd8_conv2d_3x3_s_g1_d inD=" << in_D << " outD=" << nb_filters << " s=[" << s_w << ' ' << s_h << "]  " << in_H << 'x'
              << in_W << " " << in_D * kernel.dims()[0] * kernel.dims()[1] * nb_filters * (in_H / s_h) * (in_W / s_w) / 1000 << " kMAC" << std::endl;
  }
#endif
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  for (int im_i = start_h  + s_h/2 ; im_i < in_H - start_h; im_i += s_h)
  {
    for (int im_j = start_w  + s_w/2 ; im_j < in_W - start_w; im_j += s_w)
    {
      for (int filter = 0; filter < nb_filters; ++filter)
      {
        __m256 s = _mm256_setzero_ps();
        for (int filter_i = -half_size; filter_i <= half_size; ++filter_i)
        {   // fixed
          for (int filter_j = -half_size; filter_j <= half_size; ++filter_j)
          {   // fixed
            const int ii = im_i + filter_i;
            const int jj = im_j + filter_j;
            const int ki = half_size + filter_i;
            const int kj = half_size + filter_j;

            for (int filter_d = 0; filter_d < in_D; filter_d += 8)
            {
              const float *kptr = kernel.addr(ki, kj, filter, filter_d);
              const __m256 k0   = _mm256_load_ps(kptr);
              const float *aptr = A.addr(im_nb, ii, jj, filter_d);
#if __FMA__
              s = _mm256_fmadd_ps(k0, _mm256_load_ps(aptr), s);
#else
              const __m256 m0 = _mm256_mul_ps(k0, _mm256_load_ps(aptr));
              s               = _mm256_add_ps(s, m0);
              ;   // s + m0; // s = _mm256_hadd_ps(s, m0);
#endif
            }
          }
        }
        m_out(im_nb, (im_i -o_i)/ s_h, (im_j - o_j )/ s_w , filter) = sum8_float(s);
      }
    }
  }
}

#if __AVX512F__
template<> template<int in_D, int s_h, int s_w,int o_i,int o_j> inline void Conv2D<float>::simd16_conv2d_3x3_s_g1_d(const Tensor<float> &A, const Tensor<float> &kernel)
{
  static_assert(in_D % 16 == 0, "Should be used with mod16 filters.");
  constexpr int im_nb     = 0;
  constexpr int half_size = 1;
  const int     nb_filters{ kernel.dims()[2] };
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  constexpr int ihalf_size = 1;
  constexpr int           start_h{ ihalf_size };
  constexpr int           start_w{ ihalf_size };
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  for (int im_i = start_h  + s_h/2; im_i < in_H - start_h; im_i += s_h)
  {
    for (int im_j = start_w  + s_w/2; im_j < in_W - start_w; im_j += s_w)
    {
      for (int filter = 0; filter < nb_filters; ++filter)
      {
        __m512 s = _mm512_setzero_ps();
        for (int filter_i = -half_size; filter_i <= half_size; ++filter_i)
        {   // fixed
          for (int filter_j = -half_size; filter_j <= half_size; ++filter_j)
          {   // fixed
            const int ii = im_i + filter_i;
            const int jj = im_j + filter_j;
            const int ki = half_size + filter_i;
            const int kj = half_size + filter_j;

            for (int filter_d = 0; filter_d < in_D; filter_d += 16)
            {
              const float *kptr = kernel.addr(ki, kj, filter, filter_d);
              const __m512 k0   = _mm512_load_ps(kptr);
              const float *aptr = A.addr(im_nb, ii, jj, filter_d);
#if __FMA__
              s = _mm512_fmadd_ps(k0, _mm512_load_ps(aptr), s);
#else
              const __m512 m0 = _mm512_mul_ps(k0, _mm512_load_ps(aptr));
              s               = _mm512_add_ps(s, m0);
#endif
            }
          }
        }
        m_out(im_nb, (im_i -o_i)/ s_h, (im_j - o_j )/ s_w , filter) = sum16_float(s);
      }
    }
  }
}
#endif

template<> template<int in_D, int s_h, int s_w,int o_i,int o_j> void Conv2D<int32_t>::simd8_conv2d_3x3_s_g1_d(const Tensor<int32_t> &A, const Tensor<int32_t> &kernel)
{
#if DEBUG_COUNTERS || SATURATE_RESULT
  using T = int32_t;
#endif
  static_assert(in_D % 8 == 0, "Should be used with mod8 filters.");
  constexpr int im_nb     = 0;
  constexpr int half_size = 1;
  const int     shift     = kernel.quantizer + m_q;
  const int     nb_filters{ kernel.dims()[2] };
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  constexpr int ihalf_size = 1;
  //constexpr int half_size_h{ ihalf_size };
  //constexpr int half_size_w{ ihalf_size };
  //const int     top{ m_pads[0] };
  //const int     left{ m_pads[1] };
  constexpr int           start_h{ ihalf_size };
  constexpr int           start_w{ ihalf_size };

#if DEBUG_SIMD && __AVX512F__
  if (in_D >= 16)
  {
    std::cout << "\n[WARN] suboptimal SIMD8 version conv 3x3 inD=" << in_D << " outD=" << nb_filters << " s=[" << s_w << ' ' << s_h << "]  " << in_H << 'x'
              << in_W << " " << in_D * kernel.dims()[0] * kernel.dims()[1] * nb_filters * (in_H / s_h) * (in_W / s_w) / 1000 << " kMAC" << std::endl;
  }
#endif
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  for (int im_i = start_h  + s_h/2; im_i < in_H - start_h; im_i += s_h)
  {
    for (int im_j = start_w  + s_w/2; im_j < in_W - start_w; im_j += s_w)
    {
      for (int filter = 0; filter < nb_filters; ++filter)
      {
        __m256i s = _mm256_setzero_si256();
        for (int filter_i = -half_size; filter_i <= half_size; ++filter_i)
        {   // fixed
          for (int filter_j = -half_size; filter_j <= half_size; ++filter_j)
          {   // fixed
            for (int filter_d = 0; filter_d < in_D; filter_d += 8)
            {
              const int      ii   = im_i + filter_i;
              const int      jj   = im_j + filter_j;
              const int      ki   = half_size + filter_i;
              const int      kj   = half_size + filter_j;
              const __m256i *kptr = (const __m256i *) kernel.addr(ki, kj, filter, filter_d);
              const __m256i  k0   = _mm256_load_si256(kptr);
              const __m256i *aptr = (const __m256i *) A.addr(im_nb, ii, jj, filter_d);
              const __m256i  v0   = _mm256_load_si256(aptr);
              const __m256i  m0   = _mm256_mul_epi32(k0, v0);

              const __m256i k1 = _mm256_shuffle_epi32(k0, 0b11110101);
              const __m256i v1 = _mm256_shuffle_epi32(v0, 0b11110101);

              s = _mm256_add_epi64(s, m0);

              const __m256i m1 = _mm256_mul_epi32(k1, v1);
              s                = _mm256_add_epi64(s, m1);
            }
          }
        }
        typename ComputationType<T>::type z = (sum64_int32(s) >> shift);
        SATURATE(z);
        m_out(im_nb, (im_i -o_i)/ s_h, (im_j - o_j )/ s_w , filter) = static_cast<int32_t>(z);
      }
    }
  }
}

// actually SSE42
template<> template<int in_D, int s_h, int s_w,int o_i,int o_j> void Conv2D<int16_t>::simd8_conv2d_3x3_s_g1_d(const Tensor<int16_t> &A, const Tensor<int16_t> &kernel)
{
#if DEBUG_COUNTERS || SATURATE_RESULT
  using T = int16_t;
#endif
  static_assert(in_D % 8 == 0, "Should be used with mod8 filters.");
  constexpr int im_nb     = 0;
  constexpr int half_size = 1;
  const int     shift     = kernel.quantizer + m_q;
  const int     nb_filters{ kernel.dims()[2] };
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  constexpr int ihalf_size = 1;
 // constexpr int half_size_h{ ihalf_size };
 // constexpr int half_size_w{ ihalf_size };
 // const int     top{ m_pads[0] };
 // const int     left{ m_pads[1] };
  constexpr int           start_h{ ihalf_size };
  constexpr int           start_w{ ihalf_size };

#if DEBUG_SIMD
  if (in_D >= 8)
  {
    std::cout << "\n[WARN] suboptimal SIMD8 version conv 3x3 inD=" << in_D << " outD=" << nb_filters << " s=[" << s_w << ' ' << s_h << "]  " << in_H << 'x'
              << in_W << " " << in_D * kernel.dims()[0] * kernel.dims()[1] * nb_filters * (in_H / s_h) * (in_W / s_w) / 1000 << " kMAC" << std::endl;
  }
#endif
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  for (int im_i = start_h + s_h/2 ; im_i < in_H - start_h; im_i += s_h)
  {
    for (int im_j = start_w  + s_w/2; im_j < in_W - start_w; im_j += s_w)
    {
      for (int filter = 0; filter < nb_filters; ++filter)
      {
        __m128i s = _mm_setzero_si128();
        for (int filter_i = -half_size; filter_i <= half_size; ++filter_i)
        {   // fixed
          for (int filter_j = -half_size; filter_j <= half_size; ++filter_j)
          {   // fixed
            for (int filter_d = 0; filter_d < in_D; filter_d += 8)
            {
              const int      ii   = im_i + filter_i;
              const int      jj   = im_j + filter_j;
              const int      ki   = half_size + filter_i;
              const int      kj   = half_size + filter_j;
              const __m128i *kptr = (const __m128i *) kernel.addr(ki, kj, filter, filter_d);
              const __m128i  k0   = _mm_load_si128(kptr);   // or loadu ?
              const __m128i *aptr = (const __m128i *) A.addr(im_nb, ii, jj, filter_d);
              const __m128i  v0   = _mm_load_si128(aptr);

              const __m128i mad0 = _mm_madd_epi16(k0, v0);   // res in si32
              s                  = _mm_add_epi32(s, mad0);
            }
          }
        }
        typename ComputationType<T>::type z = (sum32_int16(s) >> shift);
        SATURATE(z);
        m_out(im_nb, (im_i -o_i)/ s_h, (im_j - o_j )/ s_w , filter) = static_cast<int16_t>(z);
      }
    }
  }
}

template<> template<int in_D, int s_h, int s_w,int o_i,int o_j> void Conv2D<int16_t>::simd16_conv2d_3x3_s_g1_d(const Tensor<int16_t> &A, const Tensor<int16_t> &kernel)
{
#if DEBUG_COUNTERS || SATURATE_RESULT
  using T = int16_t;
#endif

  static_assert(in_D % 16 == 0, "Should be used with mod16 filters.");
  constexpr int im_nb     = 0;
  constexpr int half_size = 1;
  const int     shift     = kernel.quantizer + m_q;
  const int     nb_filters{ kernel.dims()[2] };
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  constexpr int ihalf_size = 1;
  constexpr int           start_h{ ihalf_size };
  constexpr int           start_w{ ihalf_size };

#if DEBUG_SIMD && __AVX512BW__
  if (in_D >= 32)
  {
    std::cout << "\n[WARN] suboptimal SIMD16 version conv 3x3 inD=" << in_D << " outD=" << nb_filters << " s=[" << s_w << ' ' << s_h << "]  " << in_H << 'x'
              << in_W << " " << in_D * kernel.dims()[0] * kernel.dims()[1] * nb_filters * (in_H / s_h) * (in_W / s_w) / 1000 << " kMAC" << std::endl;
  }
#endif
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  for (int im_i = start_h  + s_h/2; im_i < in_H - start_h; im_i += s_h)
  {
    for (int im_j = start_w  + s_w/2; im_j < in_W - start_w; im_j += s_w)
    {
      for (int filter = 0; filter < nb_filters; ++filter)
      {
        __m256i s = _mm256_setzero_si256();
        for (int filter_i = -half_size; filter_i <= half_size; ++filter_i)
        {   // fixed
          for (int filter_j = -half_size; filter_j <= half_size; ++filter_j)
          {   // fixed
            for (int filter_d = 0; filter_d < in_D; filter_d += 16)
            {
              const int      ii   = im_i + filter_i;
              const int      jj   = im_j + filter_j;
              const int      ki   = half_size + filter_i;
              const int      kj   = half_size + filter_j;
              const __m256i *kptr = (const __m256i *) kernel.addr(ki, kj, filter, filter_d);
              const __m256i  k0   = _mm256_load_si256(kptr);   // or loadu ?
              const __m256i *aptr = (const __m256i *) A.addr(im_nb, ii, jj, filter_d);
              const __m256i  v0   = _mm256_load_si256(aptr);

              const __m256i mad0 = _mm256_madd_epi16(k0, v0);   // res in si32
              s                  = _mm256_add_epi32(s, mad0);
            }
          }
        }
        typename ComputationType<T>::type z = (sum32_int16(s) >> shift);
        SATURATE(z);
        m_out(im_nb, (im_i -o_i)/ s_h, (im_j - o_j )/ s_w , filter) = static_cast<int16_t>(z);
      }
    }
  }
}

#if __AVX512BW__
template<> template<int in_D, int s_h, int s_w,int o_i,int o_j> void Conv2D<int16_t>::simd32_conv2d_3x3_s_g1_d(const Tensor<int16_t> &A, const Tensor<int16_t> &kernel)
{
  static_assert(in_D % 32 == 0, "Should be used with mod32 filters.");
  using T                 = int16_t;
  constexpr int im_nb     = 0;
  constexpr int half_size = 1;
  const int     shift     = kernel.quantizer + m_q;
  const int     nb_filters{ kernel.dims()[2] };
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  constexpr int ihalf_size = 1;
  constexpr int           start_h{ ihalf_size };
  constexpr int           start_w{ ihalf_size };
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  for (int im_i = start_h  + s_h/2; im_i < in_H - start_h; im_i += s_h)
  {
    for (int im_j = start_w  + s_w/2; im_j < in_W - start_w; im_j += s_w)
    {
      for (int filter = 0; filter < nb_filters; ++filter)
      {
        __m512i s = _mm512_setzero_si512();
        for (int filter_i = -half_size; filter_i <= half_size; ++filter_i)
        {   // fixed
          for (int filter_j = -half_size; filter_j <= half_size; ++filter_j)
          {   // fixed
            for (int filter_d = 0; filter_d < in_D; filter_d += 32)
            {
              const int      ii   = im_i + filter_i;
              const int      jj   = im_j + filter_j;
              const int      ki   = half_size + filter_i;
              const int      kj   = half_size + filter_j;
              const __m512i *kptr = (const __m512i *) kernel.addr(ki, kj, filter, filter_d);
              const __m512i  k0   = _mm512_load_si512(kptr);
              const __m512i *aptr = (const __m512i *) A.addr(im_nb, ii, jj, filter_d);
              const __m512i  v0   = _mm512_load_si512(aptr);

              const __m512i mad0 = _mm512_madd_epi16(k0, v0);   // res in si32
              s                  = _mm512_add_epi32(s, mad0);
            }
          }
        }
        typename ComputationType<T>::type z = (_mm512_reduce_add_epi32(s) >> shift);
        COUNTERS(z);
        SATURATE(z);
        m_out(im_nb, (im_i -o_i)/ s_h, (im_j - o_j )/ s_w , filter) = z;
      }
    }
  }
}
#endif
#endif   // avx2

}   // namespace layers
}   // namespace sadl
