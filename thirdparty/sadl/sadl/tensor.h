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
#include <algorithm>
#include <cstdlib>
#if _WIN32 || __USE_ISOC11
#include <malloc.h>
#else
#include <malloc/malloc.h>
#endif
#include <numeric>
#include <vector>
#include <limits>
#include <utility>
#include "options.h"

#include "dimensions.h"

namespace sadl
{
// tensor between layers: depth height width (or width height?)
template<typename T, std::size_t Alignment> struct aligned_allocator
{
  using pointer         = T *;
  using const_pointer   = const T *;
  using reference       = T &;
  using const_reference = const T &;
  using value_type      = T;
  using size_type       = std::size_t;
  using difference_type = std::ptrdiff_t;

  pointer       address(reference r) const { return &r; }
  const_pointer address(const_reference s) const { return &s; }
  size_type     max_size() const { return (static_cast<std::size_t>(0) - static_cast<std::size_t>(1)) / sizeof(T); }
  template<typename U> struct rebind
  {
    typedef aligned_allocator<U, Alignment> other;
  };

  bool operator!=(const aligned_allocator &other) const { return !(*this == other); }
  void construct(pointer p, const_reference t) const
  {
    void *const pv = static_cast<void *>(p);
    new (pv) T(t);
  }
  void destroy(T *const p) const { p->~T(); }
  bool operator==(const aligned_allocator & /*other*/) const { return true; }

  aligned_allocator()                          = default;
  aligned_allocator(const aligned_allocator &) = default;
  ~aligned_allocator()                         = default;
  aligned_allocator &operator=(const aligned_allocator &) = delete;

  template<typename U> aligned_allocator(const aligned_allocator<U, Alignment> &) {}

  pointer allocate(const std::size_t n) const
  {
    if (n == 0)
      return nullptr;
    size_t s = ((n * sizeof(T) + Alignment - 1) / Alignment) * Alignment;

#if _WIN32
#if __MINGW32__
    void *const pv = __mingw_aligned_malloc(s, Alignment);
#else
    void *const pv = _aligned_malloc(s, Alignment);
#endif
#else
#if __USE_ISOC11
    void *const pv = aligned_alloc(Alignment, s);
#else
    void *pv = nullptr;
    if (posix_memalign(&pv, Alignment, s))
    {
      throw std::bad_alloc();
    }
#endif
#endif

    if (!pv)
      throw std::bad_alloc();
    return static_cast<T *>(pv);
  }

#ifdef _WIN32
  void deallocate(T *const p, const std::size_t n) const { _aligned_free(p); }
#else
  void deallocate(T *const p, const std::size_t /*n*/) const { free(p); }
#endif

  template<typename U> pointer allocate(const std::size_t n, const U * /* const hint */) const { return allocate(n); }
};

template<typename T> struct ComputationType
{
};

// predecl for friendness
template<typename T> class Tensor;
template<typename T> void swap(Tensor<T> &t0, Tensor<T> &t1);
template<typename T> void swapData(Tensor<T> &t0, Tensor<T> &t1);
#if SPARSE_SUPPORT
template<typename T> void sparsify(Tensor<T> &weights);
template<typename T> void sparsifyWithPacking(Tensor<T> &weights, int packingSize);
template<typename T> int  computePackedSparsity(Tensor<T> &weights);
#endif

template<typename T> class Tensor
{
public:
  using value_type     = T;
  using Data           = std::vector<value_type, aligned_allocator<value_type, 64>>;
  using iterator       = typename Data::iterator;
  using const_iterator = typename Data::const_iterator;
#if SPARSE_SUPPORT
  using index = uint16_t;
#endif

  Tensor() = default;
  explicit Tensor(Dimensions d);

  void resize(Dimensions d);
#if SPARSE_SUPPORT
  void resizeSparse(Dimensions d, int32_t sizeSparse, int32_t packedSparsitySize);
#endif
  // linear access
  value_type &operator[](int i);
  value_type  operator[](int i) const;

  // tensor access
  value_type &operator()(int i);
  value_type  operator()(int i) const;

  value_type &operator()(int i, int j);
  value_type  operator()(int i, int j) const;

  value_type &operator()(int i, int j, int k);
  value_type  operator()(int i, int j, int k) const;

  value_type &      operator()(int i, int j, int k, int l);
  value_type        operator()(int i, int j, int k, int l) const;
  const value_type *addr(int i, int j, int k, int l) const;
  bool in(int i) const;
  bool in(int i, int j) const;
  bool in(int i, int j, int k) const;
  bool in(int i, int j, int k, int l) const;
  void fill(value_type value);

  const Dimensions &dims() const;
  int64_t           size() const;

  const value_type *data() const { return m_data.data(); }
  value_type *      data() { return m_data.data(); }

  iterator begin()
  {
#if SPARSE_SUPPORT
    assert(!isSparse());
#endif
    return m_data.begin();
  }
  const_iterator begin() const { return m_data.begin(); }
  iterator       end()
  {
#if SPARSE_SUPPORT
    assert(!isSparse());
#endif
    return m_data.end();
  }
  const_iterator end() const { return m_data.end(); }

  int                      quantizer   = 0;   // for int
  static constexpr int64_t kMaxSize    = 32LL * 1024 * 1024 * 1024;

  Data &getData() { return m_data; }
  void                           setTransposed(const bool val) { m_transposed = val; }
  bool                           getTransposed() const { return m_transposed; }
#if SPARSE_SUPPORT
  std::vector<value_type>       &getDataSparse() { return m_data_sparse; }
  const std::vector<value_type> &getDataSparse() const { return m_data_sparse; }
  const std::vector<index> &     getIndices() const { return m_indices; }
  std::vector<index> &           getIndices() { return m_indices; }
  const std::vector<uint16_t> &  getNbNonzerosCol() const { return m_nb_nonzeros_col; }
  std::vector<uint16_t> &        getNbNonzerosCol() { return m_nb_nonzeros_col; }
  bool                           isSparse() const { return !m_data_sparse.empty(); }
  bool                           isDenseDataAvailable() const { return !m_data.empty(); }
  bool                           isSparsePack8() const { return !m_data_sparse.empty() && m_packed_sparsity_size == 8; }
  bool                           isSparsePack16() const { return !m_data_sparse.empty() && m_packed_sparsity_size == 16; }
  void                           setPackedSparsitySize(const int16_t val) { m_packed_sparsity_size = val; }
  int16_t                        getPackedSparsitySize() const { return m_packed_sparsity_size; }
  void                           checkSimdAlignment();
  void                           redensifySparseData();
#else
  void                           redensifySparseData(const std::vector<T>& dataSparse,
                                                     const std::vector<uint16_t>&   nbNonzerosCol,
                                                     const int32_t packedSparsitySize,
                                                     const std::vector<uint16_t>& indices);
#endif
private:
  Dimensions m_dims;
  Data       m_data;
  bool                    m_transposed = false;
#if SPARSE_SUPPORT
  int16_t                 m_packed_sparsity_size = 1;
  std::vector<value_type> m_data_sparse;
  std::vector<index>      m_indices;
  std::vector<uint16_t>   m_nb_nonzeros_col;
  friend void             sparsify<>(Tensor<T> &weights);
  friend void             sparsifyWithPacking<>(Tensor<T> &weights, int packingSize);
#endif

  friend void swap<>(Tensor<T> &t0, Tensor<T> &t1);
  friend void swapData<>(Tensor<T> &t0, Tensor<T> &t1);
#if DEBUG_PRINT
public:
  static bool m_verbose;
#endif
};

#if SPARSE_SUPPORT
// Sparse Matmul
template<typename T> bool isFullMatrixSparse(const Tensor<T> &weights, float sparsity_threshold, float sparsity_size_threshold)
{
  int N = weights.dims()[0], M = weights.dims()[1];

  if (N * M < sparsity_size_threshold)
    return false;

  float cnt_zeros = 0;

  for (int j = 0; j < M; ++j)
  {
    for (int i = 0; i < N; ++i)
    {
      if (weights[N * j + i] == 0)
        cnt_zeros++;
    }
  }
#if DEBUG_PRINT
  std::cout << weights << ' ' << cnt_zeros << ' ' << M << ' ' << N << std::endl;
#endif
  auto sparsity_level = cnt_zeros / (float) (N * M);
  return (sparsity_level >= sparsity_threshold);
}

template<typename T> int computePackedSparsity(Tensor<T> &weights)
{
  std::vector<int> packSizes = { 8, 16 };
  std::vector<float> packedFillingRatio;
  std::vector<float> packedSparsityRatio;

  uint16_t N = weights.dims()[0], M = weights.dims()[1];
  assert(N < (1 << 16) && M < (1 << 16));
  for (auto packedSparsitySize: packSizes)
  {
    size_t nbBlocks        = 0;
    size_t nbTotalNonZeros = 0;
    for (uint16_t j = 0; j < M; ++j)
    {
      for (uint16_t i = 0; i < N; i ++)
      {
        if (weights[N * j + i] != 0)
        {
          nbBlocks++;
          for (uint16_t s = 0; s < packedSparsitySize && s + i < N; s++)
          {
            if (weights[N * j + i + s] != 0)
            {
              nbTotalNonZeros++;
            }
          }
          i += packedSparsitySize - 1;
        }
      }
    }
    float fillingRatio = (float) nbTotalNonZeros / (nbBlocks * packedSparsitySize);
    float packedSparsity = 1.f - (float) nbBlocks * packedSparsitySize / (M * N);
    packedFillingRatio.push_back(fillingRatio);
    packedSparsityRatio.push_back(packedSparsity);
  }
  int packedSparsity = 1;

#if DEBUG_PRINT
  std::cout << "packedSparsityRatio[0] " << packedSparsityRatio[0] 
    << " packedSparsityRatio[1] " << packedSparsityRatio[1] 
    << " packedFillingRatio[0] " << packedFillingRatio[0] 
    << " packedFillingRatio[1] " << packedFillingRatio[1] << std::endl;
#endif

  if ((packedSparsityRatio[0] >= packedSparsityRatio[1] + 0.1 || packedFillingRatio[0] >= packedFillingRatio[1] + 0.05) 
    && packedFillingRatio[0] > .27f)
  {
    packedSparsity = packSizes[0];
  }
  else if (packedFillingRatio[1] > .40f)
  {
    packedSparsity = packSizes[1];
  }
  return packedSparsity;
}

template<typename T> void sparsifyWithPacking(Tensor<T> &weights, int packingSize)
{
  weights.m_data_sparse.clear();
  weights.m_nb_nonzeros_col.clear();
  weights.m_packed_sparsity_size = packingSize;

  uint16_t N = weights.dims()[0], M = weights.dims()[1];
  assert(N < (1 << 16) && M < (1 << 16));

  for (uint16_t j = 0; j < M; ++j)
  {
    auto cnt_non_zeros = 0;
    for (uint16_t i = 0; i < N; i ++)
    {
      if (weights.m_data[N * j + i] != 0)
      {
        int idx = i;
        int nbValidData = std::min(packingSize, (int)N - i);
        if (i > N - packingSize)
        {
          int nbPad = packingSize - (N - i);
          idx = i - nbPad;
          weights.m_data_sparse.insert(weights.m_data_sparse.end(), nbPad, 0);
        }
        for (int s = 0; s < nbValidData; s++)
        {
          weights.m_data_sparse.push_back(weights.m_data[N * j + i + s]);
        }
        weights.m_indices.push_back(idx);
        cnt_non_zeros += packingSize;

        i += packingSize - 1;
      }
    }

#if (__SSE4_2__ || __AVX2__)
#if __AVX2__
    const int pad = 16;
    const int padShift = 4;
#else
    const int pad = 8;
    const int padShift = 3;
#endif
    if (std::is_same<T, int16_t>::value)
    {
      int nbPad = (((cnt_non_zeros + (pad - 1)) >> padShift) << padShift) - cnt_non_zeros;
      if (nbPad > 0)
      {
        weights.m_data_sparse.insert(weights.m_data_sparse.end(), nbPad, 0);
      }
      int nbPadIdx = nbPad / weights.m_packed_sparsity_size;
      if (nbPadIdx > 0)
      {
        weights.m_indices.insert(weights.m_indices.end(), nbPadIdx, weights.m_indices.back());
      }
    }
#endif

    weights.m_nb_nonzeros_col.push_back(cnt_non_zeros);
  }
}

template<typename T> void sparsify(Tensor<T> &weights)
{
  weights.m_data_sparse.clear();
  weights.m_nb_nonzeros_col.clear();
  weights.m_indices.clear();

  uint16_t N = weights.dims()[0], M = weights.dims()[1];
  assert(N < (1 << 16) && M < (1 << 16));

  for (uint16_t j = 0; j < M; ++j)
  {
    auto cnt_non_zeros = 0;

    for (uint16_t i = 0; i < N; ++i)
    {
      auto val = weights.m_data[N * j + i];
      if (val != 0)
      {
        weights.m_data_sparse.push_back(val);
        weights.m_indices.push_back(i);
        cnt_non_zeros++;
      }
    }

#if (__SSE4_2__ || __AVX2__)
#if __AVX2__
    int pad = 16;
#else
    int pad = 8;
#endif
    if (std::is_same<T, int16_t>::value)
    {
      int tmp = cnt_non_zeros;
      while (tmp % pad != 0)
      {
        weights.m_data_sparse.push_back(0);
        weights.m_indices.push_back(weights.m_indices.back());
        tmp++;
      }
    }
#endif

    weights.m_nb_nonzeros_col.push_back(cnt_non_zeros);
  }
}

template<typename T> void Tensor<T>::checkSimdAlignment()
{
#if __SSE4_2__ || __AVX2__
  assert(dims()[0] < (1 << 16) && dims()[0] < (1 << 16));

#if __AVX2__
  const int pad = 16;
  const int padShift = 4;
#else
  const int pad = 8;
  const int padShift = 3;
#endif

  uint64_t totalWeights = 0;
  bool alreadyAligned = true;
  uint64_t totalnbAligned = 0;

  for (auto nb_nonzero : getNbNonzerosCol())
  {
    totalWeights += nb_nonzero;
    if ((nb_nonzero % pad) != 0)
    {
      alreadyAligned = false;
    }
    totalnbAligned += ((nb_nonzero + (pad - 1)) >> padShift) << padShift;
  }
  if (alreadyAligned)
  {
    std::cout << "already aligned number " << std::endl;
  }
  else if (totalnbAligned == m_data_sparse.size())
  {
    std::cout << "data seems already padded " << std::endl;
  }
  else if (totalWeights != m_data_sparse.size())
  {
    std::cout << "WARNING: unknown padding have already been processed" << std::endl;
  }
  else
  {
    std::vector<T> tmpDataSparse;
    std::vector<index>      tmpIndices;

    //std::cout << "==> process padding" << std::endl;
    T* bptr = getDataSparse().data();
    const auto *   idx  = getIndices().data();
    for (auto nb_nonzero : getNbNonzerosCol())
    {
      if (nb_nonzero > 0)
      {
        tmpDataSparse.insert(tmpDataSparse.end(), bptr, bptr + nb_nonzero);
        tmpIndices.insert(tmpIndices.end(), idx, idx + (nb_nonzero + m_packed_sparsity_size - 1) / m_packed_sparsity_size);

        int nbPad = (((nb_nonzero + (pad - 1)) >> padShift) << padShift) - nb_nonzero;
        tmpDataSparse.insert(tmpDataSparse.end(), nbPad, 0);
        int nbPadIdx = ((((nb_nonzero + (pad - 1)) >> padShift) << padShift) - nb_nonzero) / m_packed_sparsity_size;
        tmpIndices.insert(tmpIndices.end(), nbPadIdx, tmpIndices.back());
        bptr += nb_nonzero;
        idx += (nb_nonzero + m_packed_sparsity_size - 1) / m_packed_sparsity_size;
      }
    }      
    std::swap(tmpDataSparse, m_data_sparse);
    std::swap(tmpIndices, m_indices);
  }
#endif
}
#endif

#if SPARSE_SUPPORT
template<typename T> void Tensor<T>::redensifySparseData()
#else
template<typename T> void Tensor<T>::redensifySparseData(const std::vector<T> &dataSparse, 
  const std::vector<uint16_t>& nbNonzerosCol, const int32_t packedSparsitySize, const std::vector<uint16_t>& indices)
#endif
{
#if SPARSE_SUPPORT
  const std::vector<T>& dataSparse = m_data_sparse;
  const std::vector<uint16_t>& nbNonzerosCol = m_nb_nonzeros_col;
  const int32_t packedSparsitySize = m_packed_sparsity_size;
  const std::vector<uint16_t>& indices = m_indices;
  m_data.resize(dims().nbElements());
#endif
  uint32_t offset_data = 0;
  const auto* idx = indices.data();
  const int        R{ dims()[0] };
  int idxSparse = 0;
  for (const auto& nb_nonzero : nbNonzerosCol)
  {
    int i = 0;
    for (auto k = 0; k < nb_nonzero / packedSparsitySize; k++)
    {
      int j = idx[k];
      if (i > j)
        idxSparse += i - j;
      while (i < j)
      {
        m_data[offset_data + i++] = 0;
      }
      while (i < j + packedSparsitySize)
      {
        m_data[offset_data + i++] = dataSparse[idxSparse++];
      }
    }
    while (i < R)
    {
      m_data[offset_data + i++] = 0;
    }
    offset_data += R;
    idx += nb_nonzero / packedSparsitySize;
  }
#if SPARSE_SUPPORT
  m_data_sparse.clear();
  m_nb_nonzeros_col.clear();
  m_packed_sparsity_size = 1;
  m_indices.clear();
#endif
}
// spe
template<> struct ComputationType<float>
{
  using type                = float;
  static constexpr type max = std::numeric_limits<float>::max();
  static void           quantize(type, int) {}     // nothing to do
  static void           shift_left(type, int) {}   // nothing to do
};

template<> struct ComputationType<int32_t>
{
  using type                = int64_t;  
  static constexpr type max = std::numeric_limits<int32_t>::max();
  static void           quantize(type &z, int q) { z >>= q; }
  static void           shift_left(type &z, int q) { z <<= q; }
  static void           quantize(int32_t &z, int q) { z >>= q; }
  static void           shift_left(int32_t &z, int q) { z <<= q; }
};


template<> struct ComputationType<int16_t>
{
#if DEBUG_OVERFLOW
  using type                = int64_t;
  static void           quantize(int32_t &z, int q) { z >>= q; }
  static void           shift_left(int32_t &z, int q) { z <<= q; }
#else
  using type                = int32_t;
#endif
  static constexpr type max = std::numeric_limits<int16_t>::max();
  static void           quantize(type &z, int q) { z >>= q; }
  static void           shift_left(type &z, int q) { z <<= q; }
  static void           quantize(int16_t &z, int q) { z >>= q; }
  static void           shift_left(int16_t &z, int q) { z <<= q; }
};

// impl

template<typename T> void swap(Tensor<T> &t0, Tensor<T> &t1)
{
  std::swap(t0.m_dims, t1.m_dims);
  std::swap(t0.m_data, t1.m_data);
  std::swap(t0.quantizer, t1.quantizer);
#if SPARSE_SUPPORT
  std::swap(t0.m_data_sparse, t1.m_data_sparse);
#endif
}

template<typename T> void swapData(Tensor<T> &t0, Tensor<T> &t1)
{
  assert(t0.size() == t1.size());
  std::swap(t0.m_data, t1.m_data);
  std::swap(t0.quantizer, t1.quantizer);
#if SPARSE_SUPPORT
  std::swap(t0.m_data_sparse, t1.m_data_sparse);
#endif
}

template<typename T> Tensor<T>::Tensor(Dimensions d)
{
#if SPARSE_SUPPORT
  assert(!isSparse());
#endif
  resize(d);
}

template<typename T> const Dimensions &Tensor<T>::dims() const { return m_dims; }

template<typename T> int64_t Tensor<T>::size() const { return m_data.size(); }

template<typename T> void Tensor<T>::resize(Dimensions d)
{
  m_dims     = d;
  int64_t m = m_dims.nbElements();
  assert(m < kMaxSize);
  m_data.resize(m);
#if SPARSE_SUPPORT
  m_data_sparse.clear();
  m_indices.clear();
  m_nb_nonzeros_col.clear();
  m_packed_sparsity_size = 1;
#endif
}

#if SPARSE_SUPPORT
template<typename T> void Tensor<T>::resizeSparse(Dimensions d, int32_t sizeSparse, int32_t packedSparsitySize)
{
  m_dims     = d;
  [[ maybe_unused ]] int64_t m = m_dims.nbElements();
  assert(m < kMaxSize);
  assert(sizeSparse > 0);
  assert(packedSparsitySize > 0);
  m_data_sparse.clear();
  m_data.clear();
  m_data_sparse.resize(sizeSparse);
  m_indices.resize(sizeSparse / packedSparsitySize);
  m_packed_sparsity_size = packedSparsitySize;
  m_nb_nonzeros_col.resize(d[1]);
}
#endif

// TODO: variadic template to define all accesors
template<typename T> T &Tensor<T>::operator[](int i)
{
#if SPARSE_SUPPORT
  assert(!isSparse());
#endif
  return m_data[i];
}

template<typename T> T &Tensor<T>::operator()(int i)
{
#if SPARSE_SUPPORT
  assert(!isSparse());
#endif
  assert(m_dims.size() == 1);
  assert(i < m_dims[0] && i >= 0);

  return m_data[i];
}

template<typename T> bool Tensor<T>::in(int i) const { return m_dims.size() == 1 && i < m_dims[0] && i >= 0; }

template<typename T> T Tensor<T>::operator[](int i) const { return m_data[i]; }

template<typename T> T Tensor<T>::operator()(int i) const
{
  assert(m_dims.size() == 1);
  assert(i < m_dims[0] && i >= 0);

  return m_data[i];
}

template<typename T> T &Tensor<T>::operator()(int i, int j)
{
#if SPARSE_SUPPORT
  assert(!isSparse());
#endif
  assert(m_dims.size() == 2);
  assert(i < m_dims[0] && i >= 0);
  assert(j < m_dims[1] && j >= 0);

  return m_data[(int64_t) m_dims[1] * i + j];
}

template<typename T> T Tensor<T>::operator()(int i, int j) const
{
  assert(m_dims.size() == 2);
  assert(i < m_dims[0] && i >= 0);
  assert(j < m_dims[1] && j >= 0);

  return m_data[(int64_t) m_dims[1] * i + j];
}

template<typename T> bool Tensor<T>::in(int i, int j) const { return m_dims.size() == 2 && i < m_dims[0] && i >= 0 && j < m_dims[1] && j >= 0; }

template<typename T> T &Tensor<T>::operator()(int i, int j, int k)
{
#if SPARSE_SUPPORT
  assert(!isSparse());
#endif
  assert(m_dims.size() == 3);
  assert(i < m_dims[0] && i >= 0);
  assert(j < m_dims[1] && j >= 0);
  assert(k < m_dims[2] && k >= 0);

  return m_data[(int64_t) m_dims[2] * (m_dims[1] * i + j) + k];
}

template<typename T> T Tensor<T>::operator()(int i, int j, int k) const
{
  assert(m_dims.size() == 3);
  assert(i < m_dims[0] && i >= 0);
  assert(j < m_dims[1] && j >= 0);
  assert(k < m_dims[2] && k >= 0);

  return m_data[(int64_t) m_dims[2] * (m_dims[1] * i + j) + k];
}

template<typename T> bool Tensor<T>::in(int i, int j, int k) const
{
  return m_dims.size() == 3 && i < m_dims[0] && i >= 0 && j < m_dims[1] && j >= 0 && k < m_dims[2] && k >= 0;
}

template<typename T> T &Tensor<T>::operator()(int i, int j, int k, int l)
{
#if SPARSE_SUPPORT
  assert(!isSparse());
#endif
  assert(m_dims.size() == 4);
  assert(i < m_dims[0] && i >= 0);
  assert(j < m_dims[1] && j >= 0);
  assert(k < m_dims[2] && k >= 0);
  assert(l < m_dims[3] && l >= 0);

  return m_data[(int64_t) m_dims[3] * (m_dims[2] * (m_dims[1] * i + j) + k) + l];
}

template<typename T> bool Tensor<T>::in(int i, int j, int k, int l) const
{
  return m_dims.size() == 4 && i < m_dims[0] && i >= 0 && j < m_dims[1] && j >= 0 && k < m_dims[2] && k >= 0 && l < m_dims[3] && l >= 0;
}

template<typename T> const T *Tensor<T>::addr(int i, int j, int k, int l) const
{
  assert(m_dims.size() == 4);
  assert(i < m_dims[0] && i >= 0);
  assert(j < m_dims[1] && j >= 0);
  assert(k < m_dims[2] && k >= 0);
  assert(l < m_dims[3] && l >= 0);
  return &m_data[(int64_t) m_dims[3] * (m_dims[2] * (m_dims[1] * i + j) + k) + l];
}

template<typename T> T Tensor<T>::operator()(int i, int j, int k, int l) const
{
  assert(m_dims.size() == 4);
  assert(i < m_dims[0] && i >= 0);
  assert(j < m_dims[1] && j >= 0);
  assert(k < m_dims[2] && k >= 0);
  assert(l < m_dims[3] && l >= 0);
  return m_data[(int64_t) m_dims[3] * (m_dims[2] * (m_dims[1] * i + j) + k) + l];
}

template<typename T> void Tensor<T>::fill(value_type value)
{
#if SPARSE_SUPPORT
  m_data_sparse.clear();
#endif
  std::fill(m_data.begin(), m_data.end(), value);
}

}   // namespace sadl

#include <iostream>
#include <sstream>

#if DEBUG_PRINT
template<typename T> bool sadl::Tensor<T>::m_verbose = true;

#define SADL_DBG(X)                                                                                                                                            \
  if (sadl::Tensor<T>::m_verbose)                                                                                                                              \
  {                                                                                                                                                            \
    X;                                                                                                                                                         \
  }
#else
#define SADL_DBG(X)
#endif

namespace sadl
{
template<typename T> std::ostream &operator<<(std::ostream &out, const Tensor<T> &t)
{
  // adhoc
  if (t.dims().size() == 4u)
  {
    out << "[";
    if (t.dims()[0] > 1)
      out << '\n';
    for (int k = 0; k < t.dims()[0]; ++k)
    {
      out << " [";
      if (t.dims()[1] > 1)
        out << '\n';
      for (int d = 0; d < t.dims()[1]; ++d)
      {
        out << "  [";
        if (t.dims()[2] > 1)
          out << '\n';
        for (int i = 0; i < t.dims()[2]; ++i)
        {
          out << "   [";
          for (int j = 0; j < t.dims()[3]; ++j)
            out << t(k, d, i, j) << ' ';
          out << "   ]";
          if (t.dims()[2] > 1)
            out << '\n';
        }
        out << "  ]";
        if (t.dims()[1] > 1)
          out << '\n';
      }
      out << " ]";
      if (t.dims()[0] > 1)
        out << '\n';
    }
    out << "]";
  }
  else if (t.dims().size() == 3u)
  {
    out << "[";
    for (int d = 0; d < t.dims()[0]; ++d)
    {
      out << " [";
      if (t.dims()[0] > 1)
        out << '\n';
      for (int i = 0; i < t.dims()[1]; ++i)
      {
        out << "  [";
        if (t.dims()[1] > 1)
          out << '\n';
        for (int j = 0; j < t.dims()[2]; ++j)
          out << t(d, i, j) << '\t';
        out << "  ]";
        if (t.dims()[1] > 1)
          out << '\n';
      }
      out << " ]";
      if (t.dims()[0] > 1)
        out << '\n';
    }
    out << "]";
  }
  else if (t.dims().size() == 2u)
  {
    out << "[";
#if SPARSE_SUPPORT
    int offset_data = 0;
      if (t.isSparse())
      {
        out << "data_sparse = ";
        int i = 0;
        for (const auto& nb_nonzero : t.getNbNonzerosCol())
        {
          out << " [";
          for (auto k = 0; k < nb_nonzero; k += t.getPackedSparsitySize(), offset_data += t.getPackedSparsitySize())
          {
            for (auto p = 0; p < t.getPackedSparsitySize(); ++p)
            {
              uint16_t j = t.getIndices()[offset_data / t.getPackedSparsitySize()];
              out << j + p << ": " << t.getDataSparse()[offset_data + p] << ", ";
            }
          }
          i++;
          out << " ]\n";
        }
      }
      else
#endif
    for (int i = 0; i < t.dims()[0]; ++i)
    {
      out << " [";
      if (t.dims()[0] > 1)
        out << '\n';
      for (int j = 0; j < t.dims()[1]; ++j)
        out << t(i, j) << ' ';
      out << " ]";
      if (t.dims()[0] > 1)
        out << '\n';
    }
    out << "]\n";
  }
  else if (t.dims().size() == 1u)
  {
    out << "[";
    for (int j = 0; j < t.dims()[0]; ++j)
      out << t(j) << ' ';
    out << "]";
  }
  else
  {
    out << "TODO\n";
  }
  out << " shape=" << t.dims() << " type=";

  return out;
}

}   // namespace sadl
