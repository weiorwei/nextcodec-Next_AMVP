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

#include <string.h>
#include "tensor.h"

#if __AVX2__
#include <immintrin.h>
#include <emmintrin.h>
#endif

namespace sadl
{
namespace layers
{
#if DEBUG_COUNTERS
#define BILINEAR_COUNTERS(data, coeffs)                                                                                                                        \
  int C = data.dims()[3];                                                                                                                                      \
  for (int im_c = 0; im_c < C; im_c++)                                                                                                                         \
  {                                                                                                                                                            \
    COUNTERS_MAC(coeffs[0]);                                                                                                                                   \
    COUNTERS_MAC(coeffs[1]);                                                                                                                                   \
    COUNTERS_MAC(coeffs[2]);                                                                                                                                   \
    COUNTERS_MAC(coeffs[3]);                                                                                                                                   \
    COUNTERS(0);                                                                                                                                               \
  }
#else
#define BILINEAR_COUNTERS(data, coeffs)                                                                                                                        \
  (void) data;                                                                                                                                                 \
  (void) coeffs
#endif

#if DEBUG_COUNTERS
#define BICUBIC_COUNTERS(data, coeffs)  \
  int C = data.dims()[3];               \
  for (int im_c = 0; im_c < C; im_c++)  \
  {                                     \
    for (int i = 0; i < 16; i ++)       \
    {                                   \
      COUNTERS_MAC(coeffs[i]);          \
    }                                   \
    COUNTERS(0);                        \
  }
#else
#define BICUBIC_COUNTERS(data, coeffs)  \
  (void) data;                          \
  (void) coeffs
#endif

// ////////////////////////////////////////////////////////////////////////////////////////////////////////
// bilinear interpolation utils
// ////////////////////////////////////////////////////////////////////////////////////////////////////////
template<typename T, typename T2>
void bilinear_in_channels_wo_simd(const Tensor<T> &data, const T2 coeffs[], const int pos[], const int shift, const int im_i, const int im_j, Tensor<T> &out);

#if __AVX2__
template<typename T, typename T2>
void bilinear_in_channels_simd256(const Tensor<T> &data, const T2 coeffs[], const int pos[], const int shift, const int im_i, const int im_j, Tensor<T> &out);
#endif

#if __AVX512F__ || __AVX512BW__
template<typename T, typename T2>
void bilinear_in_channels_simd512(const Tensor<T> &data, const T2 coeffs[], const int pos[], const int shift, const int im_i, const int im_j, Tensor<T> &out);
#endif

template<typename T, typename T2>
void bilinear_in_channels(const Tensor<T> &data, const T2 coeffs[], const int pos[], const int shift, const int im_i, const int im_j, Tensor<T> &out)
{
#if __AVX2__
  int in_D = data.dims()[3];
#if __AVX512F__ || __AVX512BW__
  if (in_D % 16 == 0)   // same for float and int16
    bilinear_in_channels_simd512(data, coeffs, pos, shift, im_i, im_j, out);
  else
#endif
  if (in_D % 8 == 0)    // same for float and int16
    bilinear_in_channels_simd256(data, coeffs, pos, shift, im_i, im_j, out);
  else
    bilinear_in_channels_wo_simd(data, coeffs, pos, shift, im_i, im_j, out);
#else
  bilinear_in_channels_wo_simd(data, coeffs, pos, shift, im_i, im_j, out);
#endif
}

template<typename T, typename T2>
void bilinear_in_channels_wo_simd(const Tensor<T> &data, const T2 coeffs[], const int pos[], const int shift, const int im_i, const int im_j, Tensor<T> &out)
{
  constexpr int im_nb      = 0;
  int           in_D       = data.dims()[3];
  const int    &x_ori_left = pos[0], &y_ori_top = pos[1], &x_ori_right = pos[2], &y_ori_bottom = pos[3];
  const int     pos_table[4][2] = { {y_ori_top, x_ori_left}, {y_ori_top, x_ori_right}, {y_ori_bottom, x_ori_left}, {y_ori_bottom, x_ori_right} };

  static std::vector<T2> temp_buffer;
  temp_buffer.resize(in_D);
  std::fill(temp_buffer.begin(),temp_buffer.end(),(T2)0);


  for (int coeff_i = 0; coeff_i < 4; coeff_i++)
  {
    const T2  coeff = coeffs[coeff_i];
    const int pos_y = pos_table[coeff_i][0];
    const int pos_x = pos_table[coeff_i][1];
    for (int im_c = 0; im_c < in_D; im_c++)
    {
      temp_buffer[im_c] += coeff * data(im_nb, pos_y, pos_x, im_c);
    }
  }
  for (int im_c = 0; im_c < in_D; im_c++)
  {
    T2 num = temp_buffer[im_c];
    ComputationType<T>::quantize(num, shift);
    SATURATE(num);
    out(im_nb, im_i, im_j, im_c) = static_cast<T>(num);
  }
}

#if __AVX2__
template<>
inline void bilinear_in_channels_simd256(const Tensor<float> &data, const float coeffs[], const int pos[], const int shift, const int im_i, const int im_j,
                                    Tensor<float> &out)
{
  constexpr int im_nb = 0;
  int           in_D  = data.dims()[3];
  assert(in_D % 8 == 0);   // Should be used with mod8 data.
  const int &x_ori_left = pos[0], &y_ori_top = pos[1], &x_ori_right = pos[2], &y_ori_bottom = pos[3];
  const int  pos_table[4][2] = { {y_ori_top, x_ori_left}, {y_ori_top, x_ori_right}, {y_ori_bottom, x_ori_left}, {y_ori_bottom, x_ori_right} };

  static std::vector<float> temp_buffer;
  temp_buffer.resize(in_D);
  std::fill(temp_buffer.begin(),temp_buffer.end(),0.f);

  for (int coeff_i = 0; coeff_i < 4; coeff_i++)
  {
    const __m256 c0   = _mm256_set1_ps(coeffs[coeff_i]);
    const float *dptr = data.addr(im_nb, pos_table[coeff_i][0], pos_table[coeff_i][1], 0);
    const float *bptr = &temp_buffer[0];
    for (int im_c = 0; im_c < in_D; im_c += 8)
    {
      const __m256 d0 = _mm256_loadu_ps(dptr + im_c);
      const __m256 b0 = _mm256_loadu_ps(bptr + im_c);
#if __FMA__
      const __m256 s = _mm256_fmadd_ps(c0, d0, b0);
#else
      const __m256 s = _mm256_add_ps(_mm256_mul_ps(c0, d0), b0);
#endif
      _mm256_storeu_ps((float *) (bptr + im_c), s);
    }
  }
  for (int im_c = 0; im_c < in_D; im_c++)
  {
    out(im_nb, im_i, im_j, im_c) = temp_buffer[im_c];
  }
}

template<>
inline void bilinear_in_channels_simd256(const Tensor<int16_t> &data, const int32_t coeffs[], const int pos[], const int shift, const int im_i, const int im_j,
                                    Tensor<int16_t> &out)
{
  constexpr int im_nb = 0;
  int           in_D  = data.dims()[3];
  assert(in_D % 8 == 0);   // Should be used with mod8 data.
#if DEBUG_COUNTERS || SATURATE_RESULT
  using T = int16_t;
#endif
  const int &x_ori_left = pos[0], &y_ori_top = pos[1], &x_ori_right = pos[2], &y_ori_bottom = pos[3];
  const int  pos_table[4][2] = { {y_ori_top, x_ori_left}, {y_ori_top, x_ori_right}, {y_ori_bottom, x_ori_left}, {y_ori_bottom, x_ori_right} };

  static std::vector<int32_t> temp_buffer;
  temp_buffer.resize(in_D);
  std::fill(temp_buffer.begin(),temp_buffer.end(),0);

  for (int coeff_i = 0; coeff_i < 4; coeff_i++)
  {
    const __m256i  c0   = _mm256_set1_epi32(coeffs[coeff_i]);
    const int16_t *dptr = data.addr(im_nb, pos_table[coeff_i][0], pos_table[coeff_i][1], 0);
    const int32_t *bptr = &temp_buffer[0];
    for (int im_c = 0; im_c < in_D; im_c += 8)
    {
      const __m256i d0 = _mm256_cvtepi16_epi32(_mm_loadu_si128((__m128i *) (dptr + im_c)));
      const __m256i b0 = _mm256_loadu_si256((__m256i *) (bptr + im_c));
      const __m256i s  = _mm256_add_epi32(_mm256_mullo_epi32(c0, d0), b0);   // res in int32
      _mm256_storeu_si256((__m256i *) (bptr + im_c), s);
    }
  }
  for (int im_c = 0; im_c < in_D; im_c++)
  {
    int32_t num = temp_buffer[im_c];
    ComputationType<int16_t>::quantize(num, shift);
    SATURATE(num);
    out(im_nb, im_i, im_j, im_c) = num;
  }
}

template<typename T, typename T2>
void bilinear_in_channels_simd256(const Tensor<T> &data, const T2 coeffs[], const int pos[], const int shift, const int im_i, const int im_j, Tensor<T> &out)
{
  std::cerr << "TODO " << std::endl;
  exit(-1);
}
#endif

#if __AVX512F__
template<>
inline void bilinear_in_channels_simd512(const Tensor<float> &data, const float coeffs[], const int pos[], const int shift, const int im_i, const int im_j,
                                    Tensor<float> &out)
{
  constexpr int im_nb = 0;
  int           in_D  = data.dims()[3];
  assert(in_D % 16 == 0);   // Should be used with mod16 data.
  const int &x_ori_left = pos[0], &y_ori_top = pos[1], &x_ori_right = pos[2], &y_ori_bottom = pos[3];
  const int  pos_table[4][2] = { {y_ori_top, x_ori_left}, {y_ori_top, x_ori_right}, {y_ori_bottom, x_ori_left}, {y_ori_bottom, x_ori_right} };

  static std::vector<float> temp_buffer;
  temp_buffer.resize(in_D);
  std::fill(temp_buffer.begin(),temp_buffer.end(),0.f);

  for (int coeff_i = 0; coeff_i < 4; coeff_i++)
  {
    const __m512 c0   = _mm512_set1_ps(coeffs[coeff_i]);
    const float *dptr = data.addr(im_nb, pos_table[coeff_i][0], pos_table[coeff_i][1], 0);
    const float *bptr = &temp_buffer[0];
    for (int im_c = 0; im_c < in_D; im_c += 16)
    {
      const __m512 d0 = _mm512_loadu_ps(dptr + im_c);
      const __m512 b0 = _mm512_loadu_ps(bptr + im_c);
#if __FMA__
      const __m512 s = _mm512_fmadd_ps(c0, d0, b0);
#else
      const __m512 s = _mm512_add_ps(_mm512_mul_ps(c0, d0), b0);
#endif
      _mm512_storeu_ps((float *) (bptr + im_c), s);
    }
  }
  for (int im_c = 0; im_c < in_D; im_c++)
  {
    out(im_nb, im_i, im_j, im_c) = temp_buffer[im_c];
  }
}
#endif

#if __AVX512BW__
template<>
inline void bilinear_in_channels_simd512(const Tensor<int16_t> &data, const int32_t coeffs[], const int pos[], const int shift, const int im_i, const int im_j,
                                    Tensor<int16_t> &out)
{
  constexpr int im_nb = 0;
  int           in_D  = data.dims()[3];
  assert(in_D % 16 == 0);   // Should be used with mod16 data.
#if DEBUG_COUNTERS || SATURATE_RESULT
  using T = int16_t;
#endif
  const int &x_ori_left = pos[0], &y_ori_top = pos[1], &x_ori_right = pos[2], &y_ori_bottom = pos[3];
  const int  pos_table[4][2] = { {y_ori_top, x_ori_left}, {y_ori_top, x_ori_right}, {y_ori_bottom, x_ori_left}, {y_ori_bottom, x_ori_right }};

  static std::vector<int32_t> temp_buffer;
  temp_buffer.resize(in_D);
  std::fill(temp_buffer.begin(),temp_buffer.end(),0);

  for (int coeff_i = 0; coeff_i < 4; coeff_i++)
  {
    const __m512i  c0   = _mm512_set1_epi32(coeffs[coeff_i]);
    const int16_t *dptr = data.addr(im_nb, pos_table[coeff_i][0], pos_table[coeff_i][1], 0);
    const int32_t *bptr = &temp_buffer[0];
    for (int im_c = 0; im_c < in_D; im_c += 16)
    {
      const __m512i d0 = _mm512_cvtepi16_epi32(_mm256_loadu_si256((__m256i *) (dptr + im_c)));
      const __m512i b0 = _mm512_loadu_si512(bptr + im_c);
      const __m512i s  = _mm512_add_epi32(_mm512_mullo_epi32(c0, d0), b0);   // res in int32
      _mm512_storeu_si512((void *) (bptr + im_c), s);
    }
  }
  for (int im_c = 0; im_c < in_D; im_c++)
  {
    int32_t num = temp_buffer[im_c];
    ComputationType<int16_t>::quantize(num, shift);
    SATURATE(num);
    out(im_nb, im_i, im_j, im_c) = num;
  }
}
#endif

#if __AVX512BW__ || __AVX512F__
template<typename T, typename T2>
void bilinear_in_channels_simd512(const Tensor<T> &data, const T2 coeffs[], const int pos[], const int shift, const int im_i, const int im_j, Tensor<T> &out)
{
  std::cerr << "TODO " << std::endl;
  exit(-1);
}
#endif

// ////////////////////////////////////////////////////////////////////////////////////////////////////////
// nearest interpolation utils
// ////////////////////////////////////////////////////////////////////////////////////////////////////////
template<typename T>
void nearest_in_channels(const Tensor<T> &data, const int im_i, const int im_j, const int y, const int x, Tensor<T> &out)
{
  constexpr int im_nb = 0;
  int           in_D  = out.dims()[3];

  for (int im_c = 0; im_c < in_D; im_c++)
  {
    out(im_nb, im_i, im_j, im_c) = data(im_nb, y, x, im_c);   // same data type
  }
}

// ////////////////////////////////////////////////////////////////////////////////////////////////////////
// bicubic interpolation utils
// ////////////////////////////////////////////////////////////////////////////////////////////////////////
template<typename T, typename T2>
void bicubic_in_channels_wo_simd(const Tensor<T> &data, const T2 coeffs[], const int pos[][2], const int shift, const int im_i, const int im_j, Tensor<T> &out);

#if __AVX2__
template<typename T, typename T2>
void bicubic_in_channels_simd256(const Tensor<T> &data, const T2 coeffs[], const int pos[][2], const int shift, const int im_i, const int im_j, Tensor<T> &out);
#endif

#if __AVX512F__ || __AVX512BW__
template<typename T, typename T2>
void bicubic_in_channels_simd512(const Tensor<T> &data, const T2 coeffs[], const int pos[][2], const int shift, const int im_i, const int im_j, Tensor<T> &out);
#endif

template<typename T, typename T2>
void bicubic_in_channels(const Tensor<T> &data, const T2 coeffs[], const int pos[][2], const int shift, const int im_i, const int im_j, Tensor<T> &out)
{
#if __AVX2__
  int in_D = data.dims()[3];
#if __AVX512F__ || __AVX512BW__
  if (in_D % 16 == 0)   // same for float and int16
    bicubic_in_channels_simd512(data, coeffs, pos, shift, im_i, im_j, out);
  else
#endif
  if (in_D % 8 == 0)    // same for float and int16
    bicubic_in_channels_simd256(data, coeffs, pos, shift, im_i, im_j, out);
  else
    bicubic_in_channels_wo_simd(data, coeffs, pos, shift, im_i, im_j, out);
#else
  bicubic_in_channels_wo_simd(data, coeffs, pos, shift, im_i, im_j, out);
#endif
}

template<typename T, typename T2>
void bicubic_in_channels_wo_simd(const Tensor<T> &data, const T2 coeffs[], const int pos[][2], const int shift, const int im_i, const int im_j, Tensor<T> &out)
{
  constexpr int im_nb      = 0;
  int           in_D       = data.dims()[3];

  static std::vector<T2> temp_buffer;
  temp_buffer.resize(in_D);
  std::fill(temp_buffer.begin(), temp_buffer.end(), (T2) 0);

  for (int coeff_i = 0; coeff_i < 16; coeff_i++)
  {
    const T2  coeff = coeffs[coeff_i];
    const int pos_y = pos[coeff_i][0];
    const int pos_x = pos[coeff_i][1];
    for (int im_c = 0; im_c < in_D; im_c++)
    {
      temp_buffer[im_c] += coeff * data(im_nb, pos_y, pos_x, im_c);
    }
  }
  for (int im_c = 0; im_c < in_D; im_c++)
  {
    T2 num = temp_buffer[im_c];
    ComputationType<T>::quantize(num, shift);
    SATURATE(num);
    out(im_nb, im_i, im_j, im_c) = static_cast<T>(num);
  }
}

#if __AVX2__
template<>
inline void bicubic_in_channels_simd256(const Tensor<float> &data, const float coeffs[], const int pos[][2], const int shift, const int im_i, const int im_j,
                                        Tensor<float> &out)
{
  constexpr int im_nb = 0;
  int           in_D  = data.dims()[3];
  assert(in_D % 8 == 0);   // Should be used with mod8 data.

  static std::vector<float> temp_buffer;
  temp_buffer.resize(in_D);
  std::fill(temp_buffer.begin(), temp_buffer.end(), 0.f);

  for (int coeff_i = 0; coeff_i < 16; coeff_i++)
  {
    const __m256 c0   = _mm256_set1_ps(coeffs[coeff_i]);
    const float *dptr = data.addr(im_nb, pos[coeff_i][0], pos[coeff_i][1], 0);
    const float *bptr = &temp_buffer[0];
    for (int im_c = 0; im_c < in_D; im_c += 8)
    {
      const __m256 d0 = _mm256_loadu_ps(dptr + im_c);
      const __m256 b0 = _mm256_loadu_ps(bptr + im_c);
#if __FMA__
      const __m256 s = _mm256_fmadd_ps(c0, d0, b0);
#else
      const __m256 s = _mm256_add_ps(_mm256_mul_ps(c0, d0), b0);
#endif
      _mm256_storeu_ps((float *) (bptr + im_c), s);
    }
  }
  for (int im_c = 0; im_c < in_D; im_c++)
  {
    out(im_nb, im_i, im_j, im_c) = temp_buffer[im_c];
  }
}

template<>
inline void bicubic_in_channels_simd256(const Tensor<int16_t> &data, const int32_t coeffs[], const int pos[][2], const int shift, const int im_i, const int im_j,
                                        Tensor<int16_t> &out)
{
  constexpr int im_nb = 0;
  int           in_D  = data.dims()[3];
  assert(in_D % 8 == 0);   // Should be used with mod8 data.
#if DEBUG_COUNTERS || SATURATE_RESULT
  using T = int16_t;
#endif

  static std::vector<int32_t> temp_buffer;
  temp_buffer.resize(in_D);
  std::fill(temp_buffer.begin(), temp_buffer.end(), 0);

  for (int coeff_i = 0; coeff_i < 16; coeff_i++)
  {
    const __m256i  c0   = _mm256_set1_epi32(coeffs[coeff_i]);
    const int16_t *dptr = data.addr(im_nb, pos[coeff_i][0], pos[coeff_i][1], 0);
    const int32_t *bptr = &temp_buffer[0];
    for (int im_c = 0; im_c < in_D; im_c += 8)
    {
      const __m256i d0 = _mm256_cvtepi16_epi32(_mm_loadu_si128((__m128i *) (dptr + im_c)));
      const __m256i b0 = _mm256_loadu_si256((__m256i *) (bptr + im_c));
      const __m256i s  = _mm256_add_epi32(_mm256_mullo_epi32(c0, d0), b0);   // res in int32
      _mm256_storeu_si256((__m256i *) (bptr + im_c), s);
    }
  }
  for (int im_c = 0; im_c < in_D; im_c++)
  {
    int32_t num = temp_buffer[im_c];
    ComputationType<int16_t>::quantize(num, shift);
    SATURATE(num);
    out(im_nb, im_i, im_j, im_c) = num;
  }
}

template<typename T, typename T2>
void bicubic_in_channels_simd256(const Tensor<T> &data, const T2 coeffs[], const int pos[][2], const int shift, const int im_i, const int im_j, Tensor<T> &out)
{
  std::cerr << "TODO " << std::endl;
  exit(-1);
}
#endif

#if __AVX512F__
template<>
inline void bicubic_in_channels_simd512(const Tensor<float> &data, const float coeffs[], const int pos[][2], const int shift, const int im_i, const int im_j,
                                        Tensor<float> &out)
{
  constexpr int im_nb = 0;
  int           in_D  = data.dims()[3];
  assert(in_D % 16 == 0);   // Should be used with mod16 data.

  static std::vector<float> temp_buffer;
  temp_buffer.resize(in_D);
  std::fill(temp_buffer.begin(), temp_buffer.end(), 0.f);

  for (int coeff_i = 0; coeff_i < 16; coeff_i++)
  {
    const __m512 c0   = _mm512_set1_ps(coeffs[coeff_i]);
    const float *dptr = data.addr(im_nb, pos[coeff_i][0], pos[coeff_i][1], 0);
    const float *bptr = &temp_buffer[0];
    for (int im_c = 0; im_c < in_D; im_c += 16)
    {
      const __m512 d0 = _mm512_loadu_ps(dptr + im_c);
      const __m512 b0 = _mm512_loadu_ps(bptr + im_c);
#if __FMA__
      const __m512 s = _mm512_fmadd_ps(c0, d0, b0);
#else
      const __m512 s = _mm512_add_ps(_mm512_mul_ps(c0, d0), b0);
#endif
      _mm512_storeu_ps((float *) (bptr + im_c), s);
    }
  }
  for (int im_c = 0; im_c < in_D; im_c++)
  {
    out(im_nb, im_i, im_j, im_c) = temp_buffer[im_c];
  }
}
#endif

#if __AVX512BW__
template<>
inline void bicubic_in_channels_simd512(const Tensor<int16_t> &data, const int32_t coeffs[], const int pos[][2], const int shift, const int im_i, const int im_j,
                                        Tensor<int16_t> &out)
{
  constexpr int im_nb = 0;
  int           in_D  = data.dims()[3];
  assert(in_D % 16 == 0);   // Should be used with mod16 data.
#if DEBUG_COUNTERS || SATURATE_RESULT
  using T = int16_t;
#endif

  static std::vector<int32_t> temp_buffer;
  temp_buffer.resize(in_D);
  std::fill(temp_buffer.begin(), temp_buffer.end(), 0);

  for (int coeff_i = 0; coeff_i < 16; coeff_i++)
  {
    const __m512i  c0   = _mm512_set1_epi32(coeffs[coeff_i]);
    const int16_t *dptr = data.addr(im_nb, pos[coeff_i][0], pos[coeff_i][1], 0);
    const int32_t *bptr = &temp_buffer[0];
    for (int im_c = 0; im_c < in_D; im_c += 16)
    {
      const __m512i d0 = _mm512_cvtepi16_epi32(_mm256_loadu_si256((__m256i *) (dptr + im_c)));
      const __m512i b0 = _mm512_loadu_si512(bptr + im_c);
      const __m512i s  = _mm512_add_epi32(_mm512_mullo_epi32(c0, d0), b0);   // res in int32
      _mm512_storeu_si512((void *) (bptr + im_c), s);
    }
  }
  for (int im_c = 0; im_c < in_D; im_c++)
  {
    int32_t num = temp_buffer[im_c];
    ComputationType<int16_t>::quantize(num, shift);
    SATURATE(num);
    out(im_nb, im_i, im_j, im_c) = num;
  }
}
#endif

#if __AVX512BW__ || __AVX512F__
template<typename T, typename T2>
void bicubic_in_channels_simd512(const Tensor<T> &data, const T2 coeffs[], const int pos[][2], const int shift, const int im_i, const int im_j, Tensor<T> &out)
{
  std::cerr << "TODO " << std::endl;
  exit(-1);
}
#endif

}   // namespace layers
}   // namespace sadl
