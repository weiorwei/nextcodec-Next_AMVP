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
// 1x1
// ////////////////////////////////////////////////////////////////////////////////////////////////////////
template<typename T> template<int s_h, int s_w> void Conv2D<T>::conv2d_1x1_s_dispatch(const Tensor<T> &A, const Tensor<T> &kernel)
{
#if __AVX2__
#define CONV_MOD8 simd8_conv2d_1x1_s_d
#define CONV_MOD16 simd16_conv2d_1x1_s_d
#define CONV_MOD32 simd32_conv2d_1x1_s_d
#else
#define CONV_MOD8 conv2d_1x1_s_d
#define CONV_MOD16 conv2d_1x1_s_d
#define CONV_MOD32 conv2d_1x1_s_d
#endif

  const int in_D{ A.dims()[3] };
  switch (in_D)
  {
  case 1:
    conv2d_1x1_s_d<1, s_h, s_w>(A, kernel);
    break;
  case 2:
    conv2d_1x1_s_d<2, s_h, s_w>(A, kernel);
    break;
  case 4:
    conv2d_1x1_s_d<4, s_h, s_w>(A, kernel);
    break;
  case 6:
    conv2d_1x1_s_d<6, s_h, s_w>(A, kernel);
    break;
  case 34:
    conv2d_1x1_s_d<34, s_h, s_w>(A, kernel);
    break;
  case 8:
    CONV_MOD8<8, s_h, s_w>(A, kernel);
    break;
  case 16:
    CONV_MOD16<16, s_h, s_w>(A, kernel);
    break;
  case 24:
    CONV_MOD8<24, s_h, s_w>(A, kernel);
    break;
  case 32:
    CONV_MOD32<32, s_h, s_w>(A, kernel);
    break;
  case 48:
    CONV_MOD16<48, s_h, s_w>(A, kernel);
    break;
  case 64:
    CONV_MOD32<64, s_h, s_w>(A, kernel);
    break;
  case 72:
    // better do 64 and than 8
    CONV_MOD8<72, s_h, s_w>(A, kernel);
    break;
  case 96:
    CONV_MOD32<96, s_h, s_w>(A, kernel);
    break;
  case 112:
    CONV_MOD16<112, s_h, s_w>(A, kernel);
    break;
  case 128:
    CONV_MOD32<128, s_h, s_w>(A, kernel);
    break;
  case 144:
    CONV_MOD16<144, s_h, s_w>(A, kernel);
    break;
  case 160:
    CONV_MOD32<160, s_h, s_w>(A, kernel);
    break;
  case 176:
    CONV_MOD16<176, s_h, s_w>(A, kernel);
    break;
  case 192:
    CONV_MOD32<192, s_h, s_w>(A, kernel);
    break;
  case 272:
    CONV_MOD16<272, s_h, s_w>(A, kernel);
    break;
  case 288:
    CONV_MOD32<288, s_h, s_w>(A, kernel);
    break;
  case 384:
    CONV_MOD32<384, s_h, s_w>(A, kernel);
    break;
  case 480:
    CONV_MOD32<480, s_h, s_w>(A, kernel);
    break;
  default:
    conv2d_1x1_s<s_h, s_w>(A, kernel);
    break;
  }
#undef CONV_MOD8
#undef CONV_MOD16
#undef CONV_MOD32
}

template<typename T> template<int s_h, int s_w> void Conv2D<T>::conv2d_1x1_s(const Tensor<T> &A, const Tensor<T> &kernel)
{
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  const int     in_D{ A.dims()[3] };
  const int     nb_filters{ kernel.dims()[2] };
  constexpr int half_size_h{ 0 };
  constexpr int half_size_w{ 0 };
  assert(m_pads[0]==0);
  assert(m_pads[1]==0);
  constexpr int     top{ 0 };
  constexpr int     left{ 0 };
  constexpr int     start_h{ half_size_h - top };
  constexpr int     start_w{ half_size_w - left };

#if DEBUG_SIMD && __AVX2__
  std::cout << "\n[WARN] generic version conv2d_1x1_s inD=" << in_D << " outD=" << nb_filters << " s=[" << s_w << ' ' << s_h << "] " << in_H << 'x' << in_W << " "
            << in_D * kernel.dims()[0] * kernel.dims()[1] * nb_filters * (in_H / s_h) * (in_W / s_w) / 1000 << " kMAC" << std::endl;
#endif
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  constexpr int im_nb = 0;
  const int     shift = kernel.quantizer + m_q;
  for (int im_i = start_h; im_i < in_H; im_i += s_h)
  {
    for (int im_j = start_w; im_j < in_W; im_j += s_w)
    {
      for (int filter_nb = 0; filter_nb < nb_filters; ++filter_nb)
      {
        typename ComputationType<T>::type x = 0;
        for (int filter_d = 0; filter_d < in_D; ++filter_d)
        {
          {
            x += (typename ComputationType<T>::type) A(im_nb, im_i, im_j, filter_d) * kernel(0, 0, filter_nb, filter_d);
            COUNTERS_MAC(kernel(0, 0, filter_nb, filter_d));
          }
        }
        ComputationType<T>::quantize(x, shift);
        COUNTERS(x);
        SATURATE(x);
        m_out(im_nb, im_i / s_w, im_j / s_h, filter_nb) = static_cast<T>(x);
      }
    }
  }
}

template<typename T> template<int in_D, int s_h, int s_w> void Conv2D<T>::conv2d_1x1_s_d(const Tensor<T> &A, const Tensor<T> &kernel)
{ 
//  if (conv2d_core_alongJ<s_h, s_w,0,0>(A, kernel))
//  {
//    return;
//  }
  
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  const int     nb_filters{ kernel.dims()[2] };
  constexpr int half_size_h{ 0 };
  constexpr int half_size_w{ 0 };
  assert(m_pads[0]==0);
  assert(m_pads[1]==0);
  constexpr int     top{ 0 };
  constexpr int     left{ 0 };
  constexpr int     start_h{ half_size_h - top };
  constexpr int     start_w{ half_size_w - left };

#if DEBUG_SIMD && __AVX2__
  std::cout << "\n[WARN] generic version conv2d_1x1_s_d inD=" << in_D << " outD=" << nb_filters << " s=[" << s_w << ' ' << s_h << "]  " << in_H << 'x' << in_W << " "
            << in_D * kernel.dims()[0] * kernel.dims()[1] * nb_filters * (in_H / s_h) * (in_W / s_w) / 1000 << " kMAC" << std::endl;
#endif
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  constexpr int im_nb = 0;
  const int     shift = kernel.quantizer + m_q;
  for (int im_i = start_h; im_i < in_H; im_i += s_h)
  {
    for (int im_j = start_w; im_j < in_W; im_j += s_w)
    {
      for (int filter_nb = 0; filter_nb < nb_filters; ++filter_nb)
      {
        typename ComputationType<T>::type x = 0;
        for (int filter_d = 0; filter_d < in_D; ++filter_d)
        {
          x += (typename ComputationType<T>::type) A(im_nb, im_i, im_j, filter_d) * kernel(0, 0, filter_nb, filter_d);
          COUNTERS_MAC(kernel(0, 0, filter_nb, filter_d));
        }
        ComputationType<T>::quantize(x, shift);
        COUNTERS(x);
        SATURATE(x);
        m_out(im_nb, im_i / s_h, im_j / s_w, filter_nb) = static_cast<T>(x);
      }
    }
  }
}


#if __AVX2__
// ////////////////////////////////////////////////////////////////////////////////////////////////////////
// 1x1
// ////////////////////////////////////////////////////////////////////////////////////////////////////////
template<> template<int in_D, int s_h, int s_w> inline void Conv2D<float>::simd8_conv2d_1x1_s_d(const Tensor<float> &A, const Tensor<float> &kernel)
{
  static_assert(in_D % 8 == 0, "Should be used with mod8 filters.");
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  const int     nb_filters{ kernel.dims()[2] };
  constexpr int half_size_h{ 0 };
  constexpr int half_size_w{ 0 };
  assert(m_pads[0]==0);
  assert(m_pads[1]==0);
  constexpr int     top{ 0 };
  constexpr int     left{ 0 };
  constexpr int     start_h{ half_size_h - top };
  constexpr int     start_w{ half_size_w - left };
#if DEBUG_SIMD && __AVX512F__
  if (in_D >= 16)
  {
    std::cout << "\n[WARN] suboptimal SIMD8 version conv 1x1 inD=" << in_D << " outD=" << nb_filters << " s=[" << s_w << ' ' << s_h << "]  " << in_H << 'x'
              << in_W << " " << in_D * kernel.dims()[0] * kernel.dims()[1] * nb_filters * (in_H / s_h) * (in_W / s_w) / 1000 << " kMAC" << std::endl;
  }
#endif
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  constexpr int im_nb = 0;
  for (int im_i = start_h; im_i < in_H; im_i += s_h)
  {
    for (int im_j = start_w; im_j < in_W; im_j += s_w)
    {
      for (int filter = 0; filter < nb_filters; ++filter)
      {
        __m256 s = _mm256_setzero_ps();
        for (int filter_d = 0; filter_d < in_D; filter_d += 8)
        {
          const float *kptr = kernel.addr(0, 0, filter, filter_d);
          const float *aptr = A.addr(im_nb, im_i, im_j, filter_d);
          const __m256 k0   = _mm256_load_ps(kptr);
#if __FMA__
          s = _mm256_fmadd_ps(k0, _mm256_load_ps(aptr), s);
#else
          const __m256 m0 = _mm256_mul_ps(k0, _mm256_load_ps(aptr));
          s               = _mm256_add_ps(s, m0);
          // s + m0; // s = _mm256_hadd_ps(s, m0);
#endif
        }
        m_out(im_nb, im_i / s_h, im_j / s_w, filter) = sum8_float(s);
      }
    }
  }
}

#if __AVX512F__
template<> template<int in_D, int s_h, int s_w> inline void Conv2D<float>::simd16_conv2d_1x1_s_d(const Tensor<float> &A, const Tensor<float> &kernel)
{
  static_assert(in_D % 16 == 0, "Should be used with mod16 filters.");
  constexpr int im_nb = 0;
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  const int     nb_filters{ kernel.dims()[2] };
  constexpr int half_size_h{ 0 };
  constexpr int half_size_w{ 0 };
  assert(m_pads[0]==0);
  assert(m_pads[1]==0);
  constexpr int     top{ 0 };
  constexpr int     left{ 0 };
  constexpr int     start_h{ half_size_h - top };
  constexpr int     start_w{ half_size_w - left };
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  for (int im_i = start_h; im_i < in_H; im_i += s_h)
  {
    for (int im_j = start_w; im_j < in_W; im_j += s_w)
    {
      for (int filter = 0; filter < nb_filters; ++filter)
      {
        __m512 s = _mm512_setzero_ps();
        for (int filter_d = 0; filter_d < in_D; filter_d += 16)
        {
          const float *kptr = kernel.addr(0, 0, filter, filter_d);
          const float *aptr = A.addr(im_nb, im_i, im_j, filter_d);
          const __m512 k0   = _mm512_load_ps(kptr);
#if __FMA__
          s = _mm512_fmadd_ps(k0, _mm512_load_ps(aptr), s);
#else
          const __m512 m0 = _mm512_mul_ps(k0, _mm512_load_ps(aptr));
          s               = _mm512_add_ps(s, m0);
#endif
        }
        m_out(im_nb, im_i / s_h, im_j / s_w, filter) = sum16_float(s);
      }
    }
  }
}
#endif

// int16
template<> template<int in_D, int s_h, int s_w> void Conv2D<int16_t>::simd8_conv2d_1x1_s_d(const Tensor<int16_t> &A, const Tensor<int16_t> &kernel)
{   // should be sse42
#if DEBUG_COUNTERS || SATURATE_RESULT
  using T = int16_t;
#endif
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  const int     nb_filters{ kernel.dims()[2] };
  constexpr int half_size_h{ 0 };
  constexpr int half_size_w{ 0 };
  assert(m_pads[0]==0);
  assert(m_pads[1]==0);
  constexpr int     top{ 0 };
  constexpr int     left{ 0 };
  constexpr int     start_h{ half_size_h - top };
  constexpr int     start_w{ half_size_w - left };
  static_assert(in_D % 8 == 0, "Should be used with mod16 filters.");
#if DEBUG_SIMD && __AVX2__
  if (in_D >= 8)
  {
    std::cout << "\n[WARN] suboptimal SIMD8 version simd8_conv2d_1x1_s_d inD=" << in_D << " outD=" << nb_filters << " s=[" << s_w << ' ' << s_h << "]  " << in_H << 'x'
              << in_W << " " << in_D * kernel.dims()[0] * kernel.dims()[1] * nb_filters * (in_H / s_h) * (in_W / s_w) / 1000 << " kMAC" << std::endl;
  }
#endif
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  constexpr int im_nb = 0;
  const int     shift = kernel.quantizer + m_q;
  for (int im_i = start_h; im_i < in_H; im_i += s_h)
  {
    for (int im_j = start_w; im_j < in_W; im_j += s_w)
    {
      for (int filter = 0; filter < nb_filters; ++filter)
      {
        __m128i s = _mm_setzero_si128();
        for (int filter_d = 0; filter_d < in_D; filter_d += 8)
        {
          const __m128i *kptr = (const __m128i *) kernel.addr(0, 0, filter, filter_d);
          const __m128i  k0   = _mm_load_si128(kptr);   // or loadu ?
          const __m128i *aptr = (const __m128i *) A.addr(im_nb, im_i, im_j, filter_d);
          const __m128i  v0   = _mm_load_si128(aptr);

          const __m128i mad0 = _mm_madd_epi16(k0, v0);   // res in si32
          s                  = _mm_add_epi32(s, mad0);
        }
        typename ComputationType<T>::type z = (sum32_int16(s) >> shift);
        SATURATE(z);
        m_out(im_nb, im_i / s_h, im_j / s_w, filter) = static_cast<int16_t>(z);
      }
    }
  }
}

template<> template<int in_D, int s_h, int s_w> void Conv2D<int16_t>::simd16_conv2d_1x1_s_d(const Tensor<int16_t> &A, const Tensor<int16_t> &kernel)
{
#if DEBUG_COUNTERS || SATURATE_RESULT
  using T = int16_t;
#endif
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  const int     nb_filters{ kernel.dims()[2] };
  constexpr int half_size_h{ 0 };
  constexpr int half_size_w{ 0 };
  assert(m_pads[0]==0);
  assert(m_pads[1]==0);
  constexpr int     top{ 0 };
  constexpr int     left{ 0 };
  constexpr int     start_h{ half_size_h - top };
  constexpr int     start_w{ half_size_w - left };
  static_assert(in_D % 16 == 0, "Should be used with mod16 filters.");
#if DEBUG_SIMD && __AVX512BW__
  if (in_D >= 32)
  {
    std::cout << "\n[WARN] suboptimal SIMD16 version simd16_conv2d_1x1_s_d inD=" << in_D << " outD=" << nb_filters << " s=[" << s_w << ' ' << s_h << "]  " << in_H << 'x'
              << in_W << " " << in_D * kernel.dims()[0] * kernel.dims()[1] * nb_filters * (in_H / s_h) * (in_W / s_w) / 1000 << " kMAC" << std::endl;
  }
#endif
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  constexpr int im_nb = 0;
  const int     shift = kernel.quantizer + m_q;

  for (int im_i = start_h; im_i < in_H; im_i += s_h)
  {
    for (int im_j = start_w; im_j < in_W; im_j += s_w)
    {
      for (int filter = 0; filter < nb_filters; ++filter)
      {
        __m256i s = _mm256_setzero_si256();
        for (int filter_d = 0; filter_d < in_D; filter_d += 16)
        {
          const __m256i *kptr = (const __m256i *) kernel.addr(0, 0, filter, filter_d);
          const __m256i  k0   = _mm256_load_si256(kptr);   // or loadu ?
          const __m256i *aptr = (const __m256i *) A.addr(im_nb, im_i, im_j, filter_d);
          const __m256i  v0   = _mm256_load_si256(aptr);

          const __m256i mad0 = _mm256_madd_epi16(k0, v0);   // res in si32
          s                  = _mm256_add_epi32(s, mad0);
        }
        typename ComputationType<T>::type z = (sum32_int16(s) >> shift);
        SATURATE(z);
        m_out(im_nb, im_i / s_h, im_j / s_w, filter) = static_cast<int16_t>(z);
      }
    }
  }  
}



#if __AVX512BW__
template<> template<int in_D, int s_h, int s_w> void Conv2D<int16_t>::simd32_conv2d_1x1_s_d(const Tensor<int16_t> &A, const Tensor<int16_t> &kernel)
{
  static_assert(in_D % 32 == 0, "Should be used with mod32 filters.");
  using T = int16_t;
  const int     in_H{ A.dims()[1] };
  const int     in_W{ A.dims()[2] };
  const int     nb_filters{ kernel.dims()[2] };
  constexpr int half_size_h{ 0 };
  constexpr int half_size_w{ 0 };
  assert(m_pads[0]==0);
  assert(m_pads[1]==0);
  constexpr int     top{ 0 };
  constexpr int     left{ 0 };
  constexpr int     start_h{ half_size_h - top };
  constexpr int     start_w{ half_size_w - left };
  constexpr int im_nb = 0;
  const int     shift = kernel.quantizer + m_q;
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  for (int im_i = start_h; im_i < in_H; im_i += s_h)
  {
    for (int im_j = start_w; im_j < in_W; im_j += s_w)
    {
      for (int filter = 0; filter < nb_filters; ++filter)
      {
        __m512i s = _mm512_setzero_si512();
        for (int filter_d = 0; filter_d < in_D; filter_d += 32)
        {
          const __m512i *kptr = (const __m512i *) kernel.addr(0, 0, filter, filter_d);
          const __m512i  k0   = _mm512_load_si512(kptr);
          const __m512i *aptr = (const __m512i *) A.addr(im_nb, im_i, im_j, filter_d);
          const __m512i  v0   = _mm512_load_si512(aptr);

          const __m512i mad0 = _mm512_madd_epi16(k0, v0);   // res in si32
          s                  = _mm512_add_epi32(s, mad0);
        }
        typename ComputationType<int32_t>::type z = (_mm512_reduce_add_epi32(s) >> shift);
        COUNTERS(z);
        SATURATE(z);
        m_out(im_nb, im_i / s_h, im_j / s_w, filter) = static_cast<T>(z);
      }
    }
  }
}
#endif
#endif

}   // namespace layers
}   // namespace sadl
