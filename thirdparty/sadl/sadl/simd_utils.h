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
#include "tensor.h"
#include <cmath>
#if __AVX2__
#include <immintrin.h>
#endif

#if __AVX2__
static inline float sum8_float(__m256 x)
{
  const __m128 hiQuad  = _mm256_extractf128_ps(x, 1);
  const __m128 loQuad  = _mm256_castps256_ps128(x);
  const __m128 sumQuad = _mm_add_ps(loQuad, hiQuad);
  const __m128 loDual  = sumQuad;
  const __m128 hiDual  = _mm_movehl_ps(sumQuad, sumQuad);
  const __m128 sumDual = _mm_add_ps(loDual, hiDual);
  const __m128 lo      = sumDual;
  const __m128 hi      = _mm_shuffle_ps(sumDual, sumDual, 0x1);
  const __m128 sum     = _mm_add_ss(lo, hi);
  return _mm_cvtss_f32(sum);
}
// int32
static inline typename sadl::ComputationType<int32_t>::type sum64_int32(__m256i x)
{   //  to optiz
  return _mm256_extract_epi64(x, 0) + _mm256_extract_epi64(x, 1) + _mm256_extract_epi64(x, 2) + _mm256_extract_epi64(x, 3);
}
static inline typename sadl::ComputationType<int16_t>::type hsum_epi32_avx(__m128i x)
{
  __m128i hi64 = _mm_unpackhi_epi64(x, x);   // 3-operand non-destructive AVX lets us save a
                                             // byte without needing a movdqa
  __m128i sum64 = _mm_add_epi32(hi64, x);
  __m128i hi32  = _mm_shuffle_epi32(sum64, _MM_SHUFFLE(2, 3, 0, 1));   // Swap the low two elements
  __m128i sum32 = _mm_add_epi32(sum64, hi32);
  return _mm_cvtsi128_si32(sum32);   // movd
}

static inline typename sadl::ComputationType<int16_t>::type sum32_int16(__m256i x)
{
  __m128i sum128 = _mm_add_epi32(_mm256_castsi256_si128(x), _mm256_extracti128_si256(x, 1));
  return hsum_epi32_avx(sum128);
}

static inline typename sadl::ComputationType<int16_t>::type sum32_int16(__m128i s)
{
  __m128i hi64  = _mm_unpackhi_epi64(s, s);   // 3-operand non-destructive AVX lets us save a byte without needing a movdqa
  __m128i sum64 = _mm_add_epi32(hi64, s);
  __m128i hi32  = _mm_shuffle_epi32(sum64, _MM_SHUFFLE(2, 3, 0, 1));   // Swap the low two elements
  __m128i sum32 = _mm_add_epi32(sum64, hi32);

  typename sadl::ComputationType<int16_t>::type z = _mm_cvtsi128_si32(sum32);
  return z;
}
#if __AVX512F__
static inline float sum16_float(const __m512 vec_in)
{
  const __m128 vec_low_quad_0  = _mm512_extractf32x4_ps(vec_in, 0);
  const __m128 vec_high_quad_0 = _mm512_extractf32x4_ps(vec_in, 1);
  const __m128 vec_sum_quad_0  = _mm_add_ps(vec_low_quad_0, vec_high_quad_0);
  const __m128 vec_low_quad_1  = _mm512_extractf32x4_ps(vec_in, 2);
  const __m128 vec_high_quad_1 = _mm512_extractf32x4_ps(vec_in, 3);
  const __m128 vec_sum_quad_1  = _mm_add_ps(vec_low_quad_1, vec_high_quad_1);
  const __m128 vec_sum_quad    = _mm_add_ps(vec_sum_quad_0, vec_sum_quad_1);
  const __m128 vec_moved       = _mm_movehl_ps(vec_sum_quad, vec_sum_quad);
  const __m128 vec_sum_dual    = _mm_add_ps(vec_sum_quad, vec_moved);
  const __m128 vec_shuffled    = _mm_shuffle_ps(vec_sum_dual, vec_sum_dual, 0x1);
  const __m128 vec_sum_single  = _mm_add_ss(vec_sum_dual, vec_shuffled);
  return _mm_cvtss_f32(vec_sum_single);
}
#endif
#endif
