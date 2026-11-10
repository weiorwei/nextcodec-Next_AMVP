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
template<typename T> class PReLU : public Layer<T>
{
public:
  using Layer<T>::Layer;
  using Layer<T>::m_out;   // to avoid this->
  using Layer<T>::m_initDone;

  virtual bool apply(std::vector<Tensor<T> *> &in) override;
  virtual bool init(const std::vector<Tensor<T> *> &in) override;
  virtual bool mutateInput() const override { return true; }

protected:
  virtual bool                   loadInternal(std::istream &file, Version) override;
  template<bool multialpha> bool apply_scalar(std::vector<Tensor<T> *> &in);
#if __AVX2__
  template<bool multialpha> bool apply_simd256(std::vector<Tensor<T> *> &in);
#endif
#if __AVX512F__ || __AVX512BW__
  template<bool multialpha> bool apply_simd512(std::vector<Tensor<T> *> &in);
#endif
};

template<typename T> bool PReLU<T>::apply(std::vector<Tensor<T> *> &in)
{
  assert(in.size() == 2);
  assert(in[0]->dims() == m_out.dims());
#if DEBUG_MODEL_ANALYZE
  std::cout << "\n[ANALYZE] prelu (in):\t" << m_out.size() << std::endl;
#endif
#if __AVX512F__
  if (std::is_same<T, float>::value && in[0]->size() % 16 == 0)
  {
    if (in[1]->size() == 1)
    {
      return apply_simd512<false>(in);
    }
    else if (in[1]->size() % 16 == 0)
    {
      return apply_simd512<true>(in);
    }
  }
#endif
#if __AVX512BW__
  if (std::is_same<T, int16_t>::value && in[0]->size() % 32 == 0)
  {
    if (in[1]->size() == 1)
    {
      return apply_simd512<false>(in);
    }
    else if (in[1]->size() % 32 == 0)
    {
      return apply_simd512<true>(in);
    }
  }
#endif
#if __AVX2__
  if (std::is_same<T, float>::value && in[0]->size() % 8 == 0)
  {
    if (in[1]->size() == 1)
    {
      return apply_simd256<false>(in);
    }
    else if (in[1]->size() % 8 == 0)
    {
      return apply_simd256<true>(in);
    }
  }
#endif

#if __AVX2__
  if (std::is_same<T, int16_t>::value && in[0]->size() % 16 == 0)
  {
    if (in[1]->size() == 1)
    {
      return apply_simd256<false>(in);
    }
    else if (in[1]->size() % 16 == 0)
    {
      return apply_simd256<true>(in);
    }
  }
#endif
  if (in[1]->size() == 1)
  {
    return apply_scalar<false>(in);
  }
  else
  {
    return apply_scalar<true>(in);
  }
}

template<typename T> template<bool multialpha> bool PReLU<T>::apply_scalar(std::vector<Tensor<T> *> &in)   // without simd
{
  const Tensor<T> &A = *in[1];
  swap(*in[0], m_out);
  const int alpha_q = A.quantizer;
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  if (multialpha)
  {
    switch (in[0]->dims().size()) {
      case 4: {
        const int in_N{ in[0]->dims()[0] };
        const int in_H{ in[0]->dims()[1] };
        const int in_W{ in[0]->dims()[2] };
        const int in_C{ in[0]->dims()[3] };

        // keep same qunatiz as input
        for (int n_nb = 0; n_nb < in_N; n_nb++)
        {
          for (int c_nb = 0; c_nb < in_C; c_nb++)
          {
            // A.dims()[0] == 1, means all channels share the same alpha parameter
            const typename ComputationType<T>::type alpha = (A.dims()[0] == 1) ? A(0, 0, 0) : A(c_nb, 0, 0);
            for (int h_nb = 0; h_nb < in_H; h_nb++)
            {
              for (int w_nb = 0; w_nb < in_W; w_nb++)
              {
                if (m_out(n_nb, h_nb, w_nb, c_nb) < 0)
                {
                  typename ComputationType<T>::type z = m_out(n_nb, h_nb, w_nb, c_nb) * alpha;
                  ComputationType<T>::quantize(z, alpha_q);
                  COUNTERS(z);
                  COUNTERS_MAC(z);
                  SATURATE(z);
                  m_out(n_nb, h_nb, w_nb, c_nb) = static_cast<T>(z);
                }
                else
                {
                  COUNTERS_MAC_NOP(1);
                }
              }
            }
          }
        }
        break;
      }
      case 2: {
        const int in_N{ in[0]->dims()[0] };
        const int in_C{ in[0]->dims()[1] };
        
        // keep same qunatiz as input
        const int alpha_q = A.quantizer;
        for (int n_nb = 0; n_nb < in_N; n_nb++)
        {
          for (int c_nb = 0; c_nb < in_C; c_nb++)
          {
            // A.dims()[0] == 1, means all channels share the same alpha parameter
            const typename ComputationType<T>::type alpha = A(A.dims()[0] == 1 ? 0 : c_nb);
            if (m_out(n_nb, c_nb) < 0)
            {
              typename ComputationType<T>::type z = m_out(n_nb, c_nb) * alpha;
              ComputationType<T>::quantize(z, alpha_q);
              COUNTERS(z);
              COUNTERS_MAC(z);
              SATURATE(z);
              m_out(n_nb, c_nb) = static_cast<T>(z);
            }
            else
            {
              COUNTERS_MAC_NOP(1);
            }
          }
        }
        break;
      }
      default:
        return false;
    }
  }
  else
  {
    const typename ComputationType<T>::type alpha = A[0];
    for (auto &x: m_out)
    {
      if (x < 0)
      {
        typename ComputationType<T>::type z = x * alpha;
        ComputationType<T>::quantize(z, alpha_q);
        COUNTERS(z);
        COUNTERS_MAC(z);
        SATURATE(z);
        x = static_cast<T>(z);
      }
      else
      {
        COUNTERS_MAC_NOP(1);
      }
    }
  }
  return true;
}

#if __AVX2__
template<> template<bool multialpha> inline bool PReLU<float>::apply_simd256(std::vector<Tensor<float> *> &in)   // simd256 float
{
  Tensor<float> &A = *in[1];
  swap(*in[0], m_out);
  float *const       data_ptr  = m_out.data();
  const float *const alpha_ptr = A.data();
  const __m256       m_zeros   = _mm256_setzero_ps();
  __m256             alpha     = _mm256_set1_ps(*A.data());
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  for (int iter = 0; iter < m_out.size(); iter += 8)
  {
    if (multialpha)
      alpha = _mm256_load_ps(alpha_ptr + iter % A.size());

    float *const aptr       = data_ptr + iter;
    auto         a          = _mm256_load_ps(aptr);               // load
    auto         min_a_zero = _mm256_min_ps(a, m_zeros);          // min(a,0)
    auto         max_a_zero = _mm256_max_ps(a, m_zeros);          // max(a,0)
    auto         b          = _mm256_mul_ps(min_a_zero, alpha);   // min(a,0)*alpha
    const __m256 v          = _mm256_add_ps(max_a_zero, b);       // max(a,0)+min(a,0)*alpha
    /*store*/ _mm256_store_ps(aptr, v);
  }

  return true;
}

template<> template<bool multialpha> inline bool PReLU<int16_t>::apply_simd256(std::vector<Tensor<int16_t> *> &in)
{
  Tensor<int16_t> &A = *in[1];
  swap(*in[0], m_out);
  int16_t *const                        data_ptr  = m_out.data();
  [[maybe_unused]] const int16_t *const alpha_ptr = A.data();
  const int                             alpha_q   = A.quantizer;

  __m256i       alpha = _mm256_set1_epi16(A[0]);
  const __m256i mask  = _mm256_set1_epi32(65535);
  const __m256i max   = _mm256_set1_epi32(32767);
  const __m256i min   = _mm256_set1_epi32(-32768);
  const __m256i zeros = _mm256_setzero_si256();
  const auto     N     = m_out.size();
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  for (int64_t iter = 0; iter < N; iter += 16)
  {
    int16_t *aptr = data_ptr + iter;
    auto     a    = _mm256_load_si256((__m256i *) aptr);   // load
    if (multialpha)
    {
      alpha = _mm256_load_si256((__m256i *) (alpha_ptr + (iter % A.size())));
    }

    // prepare branches
    auto max0 = _mm256_max_epi16(a, zeros);
    auto min0 = _mm256_min_epi16(a, zeros);
    // branch neg
    // mul
    auto lo = _mm256_mullo_epi16(min0, alpha);   // min(a,0)*alpha lo part
    auto hi = _mm256_mulhi_epi16(min0, alpha);   // min(a,0)*alpha hi part
    // repack32
    auto lo32 = _mm256_unpacklo_epi16(lo, hi);
    auto hi32 = _mm256_unpackhi_epi16(lo, hi);
    auto y0   = _mm256_permute2x128_si256(lo32, hi32, _MM_SHUFFLE(0, 2, 0, 0));
    auto y1   = _mm256_permute2x128_si256(lo32, hi32, _MM_SHUFFLE(0, 3, 0, 1));
    // shift
    auto y0s = _mm256_srai_epi32(y0, alpha_q);
    auto y1s = _mm256_srai_epi32(y1, alpha_q);
#if SATURATE_RESULT
    // clip
    auto y0c  = _mm256_max_epi32(y0s, min);
    auto y1c  = _mm256_max_epi32(y1s, min);
    auto y0c2 = _mm256_min_epi32(y0c, max);
    auto y1c2 = _mm256_min_epi32(y1c, max);
#else
    auto y0c2 = y0s;
    auto y1c2 = y1s;
#endif
    // mask 16bits
    auto y0p = _mm256_and_si256(y0c2, mask);
    auto y1p = _mm256_and_si256(y1c2, mask);
    // repack
    auto z  = _mm256_packus_epi32(y0p, y1p);
    auto z2 = _mm256_permute4x64_epi64(z, _MM_SHUFFLE(3, 1, 2, 0));
    // merge 2 branches
    auto r = _mm256_add_epi16(max0, z2);
    _mm256_store_si256((__m256i *) aptr, r);
  }
  return true;
}

template<typename T> template<bool multialpha> bool PReLU<T>::apply_simd256(std::vector<Tensor<T> *> &in)   //
{
  std::cerr << "[ERROR] simd type not supported: " << std::endl;
  exit(-1);
}
#endif

#if __AVX512F__
template<> template<bool multialpha> inline bool PReLU<float>::apply_simd512(std::vector<Tensor<float> *> &in)   // simd512 float
{
  Tensor<float> &A = *in[1];
  swap(*in[0], m_out);
  float *const       data_ptr  = m_out.data();
  const float *const alpha_ptr = A.data();
  const __m512       m_zeros   = _mm512_setzero_ps();
  __m512             alpha     = _mm512_set1_ps(*A.data());
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  for (int64_t iter = 0; iter < m_out.size(); iter += 16)
  {
    if (multialpha)
      alpha = _mm512_load_ps(alpha_ptr + iter % A.size());

    float *const aptr       = data_ptr + iter;   // load
    auto         a          = _mm512_load_ps(aptr);
    auto         min_a_zero = _mm512_min_ps(a, m_zeros);          // min(a,0)
    auto         max_a_zero = _mm512_max_ps(a, m_zeros);          // max(a,0)
    auto         b          = _mm512_mul_ps(min_a_zero, alpha);   // min(a,0)*alpha
    auto         v          = _mm512_add_ps(max_a_zero, b);       // max(a,0)+min(a,0)*alpha
    /*store*/ _mm512_store_ps(aptr, v);
  }

  return true;
}

#endif

#if __AVX512BW__  
template<> template<bool multialpha> inline bool PReLU<int16_t>::apply_simd512(std::vector<Tensor<int16_t> *> &in)   // simd512 int16 quantize
{
  Tensor<int16_t> &A = *in[1];
  swap(*in[0], m_out);
  int16_t                              *data_ptr  = m_out.data();
  [[maybe_unused]] const int16_t *const alpha_ptr = A.data();
  const int                             alpha_q   = A.quantizer;
  auto                                  alpha0    = _mm512_set1_epi32(A[0]);
  auto                                  alpha1    = alpha0;
  const auto                            max       = _mm512_set1_epi32(32767);
  const auto                            min       = _mm512_set1_epi32(-32768);
  const auto                            zeros     = _mm512_setzero_si512();
  static constexpr int16_t data[]={0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54, 56, 58, 60, 62};
  const auto shuffle=  _mm512_loadu_si512((void *)data);

  const auto N = m_out.size();
#if DEBUG_PATH
  std::cout<<__PRETTY_FUNCTION__<<std::endl;
#endif
  for (int64_t iter = 0; iter < N; iter += 32)
  {
    int16_t *aptr = data_ptr + iter;
    auto     a    = _mm512_loadu_si512((__m512i *) aptr);   // load
    if (multialpha)
    {
      auto a2   = _mm512_loadu_si512((__m512i *) (alpha_ptr + (iter % A.size())));
      auto a2lo = _mm512_castsi512_si256(a2);
      alpha0    = _mm512_cvtepi16_epi32(a2lo);
      auto a2hi = _mm512_extracti64x4_epi64(a2, 1);
      alpha1    = _mm512_cvtepi16_epi32(a2hi);
    }
    // prepare branches
    auto max0 = _mm512_max_epi16(a, zeros);
    auto min0 = _mm512_min_epi16(a, zeros);
    // branch neg
    // extract
    auto lo = _mm512_castsi512_si256(min0);
    auto hi = _mm512_extracti64x4_epi64(min0, 1);
    // unpack 16 to 32
    auto lo32 = _mm512_cvtepi16_epi32(lo);
    auto hi32 = _mm512_cvtepi16_epi32(hi);
    // mul
    auto y0 = _mm512_mullo_epi32(lo32, alpha0);
    auto y1 = _mm512_mullo_epi32(hi32, alpha1);
    // shift
    auto y0s = _mm512_srai_epi32(y0, alpha_q);
    auto y1s = _mm512_srai_epi32(y1, alpha_q);
#if SATURATE_RESULT
    // clip
    auto y0c  = _mm512_max_epi32(y0s, min);
    auto y1c  = _mm512_max_epi32(y1s, min);
    auto y0c2 = _mm512_min_epi32(y0c, max);
    auto y1c2 = _mm512_min_epi32(y1c, max);
#else
    auto y0c2 = y0s;
    auto y1c2 = y1s;
#endif
    // pack
    auto z2 = _mm512_permutex2var_epi16(y0c2, shuffle, y1c2);
    // merge branches
    auto r = _mm512_add_epi16(max0, z2);
    _mm512_storeu_si512((__m512i *) aptr, r);
  }
  return true;
}
#endif

#if __AVX512F__ || __AVX512BW__
template<typename T> template<bool multialpha> bool PReLU<T>::apply_simd512(std::vector<Tensor<T> *> &in)   //
{
  std::cerr << "[ERROR] simd type not supported: " << std::endl;
  exit(-1);
}
#endif

template<typename T> bool PReLU<T>::init(const std::vector<Tensor<T> *> &in)
{
  if (in.size() != 2)
    return false;
  if (in[0]->dims().size()!=2 && in[0]->dims().size()!=4)
    return false;
  m_out.resize(in[0]->dims());
  m_initDone = true;
  return true;
}

template<typename T> bool PReLU<T>::loadInternal(std::istream &, Version) { return true; }

}   // namespace layers
}   // namespace sadl
