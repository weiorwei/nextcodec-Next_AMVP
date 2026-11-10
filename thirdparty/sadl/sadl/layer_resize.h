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
#include "interpolation_utils.h"

namespace sadl
{
namespace layers
{
template<typename T> class Resize : public Layer<T>
{
public:
  using Layer<T>::Layer;
  using Layer<T>::m_out;   // to avoid this->
  using Layer<T>::m_initDone;
  virtual bool apply(std::vector<Tensor<T> *> &in) override;
  virtual bool init(const std::vector<Tensor<T> *> &in) override;

protected:
  using T2 = typename ComputationType<T>::type;
  virtual bool loadInternal(std::istream &file, Version v) override;
  bool         interpolate_bilinear(std::vector<Tensor<T> *> &in);
  bool         interpolate_nearest(std::vector<Tensor<T> *> &in);
  bool         interpolate_bicubic(std::vector<Tensor<T> *> &in);
  void         calc_bicubic_positions(int y, int x, int H, int W, int pos[][2], T2 ori[]) const;
  void         calc_positions(int y, int x, int H, int W, int pos[], T2 ori[]);
  void         get_bilinear_coeffs(T2 y_ori, T2 x_ori, T2 coeffs[]);
  void         get_nearest_coeffs(T2 ratio, T2 &coeff_1, T2 &coeff_2);
  void         get_bicubic_coeffs(T2 y_ori, T2 x_ori, T2 coeffs[]) const;
  T2           cubic_coeffs(T2 x, int i) const;

  enum resize_coordinate_transformation_mode
  {
    resize_coordinate_transformation_mode_half_pixel = 0,
    resize_coordinate_transformation_mode_asymmetric = 1
  };
  enum resize_mode
  {
    resize_mode_linear  = 0,
    resize_mode_nearest = 1,
    resize_mode_cubic = 2
  };
  enum resize_nearest_mode
  {
    resize_nearest_mode_floor             = 0,
    resize_nearest_mode_round_prefer_ceil = 1
  };
  int        m_coordinate_transformation_mode;   // 0: "half_pixel", 1: "asymmetric"
  int        m_mode;                             // 0: "linear", 1: "nearest", 2: "bicubic"
  int        m_nearest_mode;                     // 0: "floor", 1: "round_prefer_ceil"
  int        m_input_label;                      // 1: "X and sizes", 2: "X and scales"
  int        m_quantizer;
  Tensor<T2> scale_factors;
  DUMP_MODEL_EXT;
};

template<typename T> bool Resize<T>::loadInternal(std::istream &file, Version v)
{
  int32_t x = 0;
  file.read((char *) &x, sizeof(x));
  m_input_label = x;
  SADL_DBG(std::cout << "  - input_label: " << m_input_label << std::endl);
  file.read((char *) &x, sizeof(x));
  m_coordinate_transformation_mode = x;
  SADL_DBG(std::cout << "  - coordinate_transformation_mode: " << m_coordinate_transformation_mode << std::endl);
  file.read((char *) &x, sizeof(x));
  m_mode = x;
  SADL_DBG(std::cout << "  - mode: " << m_mode << std::endl);
  file.read((char *) &x, sizeof(x));
  m_nearest_mode = x;
  SADL_DBG(std::cout << "  - nearest_mode: " << m_nearest_mode << std::endl);
  if (m_input_label != 1 && m_input_label != 2)
  {
    std::cerr << "[ERROR] invalid input label: " << m_input_label << ". Currently, the inputs of Resize have to be X and sizes, or X and scales." << std::endl;
    return false;
  }
  if (m_coordinate_transformation_mode != 0 && m_coordinate_transformation_mode != 1)
  {
    std::cerr << "[ERROR] invalid coordinate transformation mode: " << m_coordinate_transformation_mode << std::endl;
    return false;
  }
  if (m_mode != 0 && m_mode != 1 && m_mode != 2)
  {
    std::cerr << "[ERROR] invalid mode: " << m_mode << std::endl;
    return false;
  }
  if (m_nearest_mode != 0 && m_nearest_mode != 1)
  {
    std::cerr << "[ERROR] invalid nearest mode: " << m_nearest_mode << std::endl;
    return false;
  }
  return true;
}

template<typename T> bool Resize<T>::init(const std::vector<Tensor<T> *> &in)
{
  if (in.size() != 2)
    return false;
  if (in[1]->quantizer != 0)
  {
    std::cerr << "[ERROR] In Resize, the quantizer of the scales or sizes must be 0." << std::endl;
    return false;
  }
  int N    = in[0]->dims()[0];
  int H_in = in[0]->dims()[1];
  int W_in = in[0]->dims()[2];
  int C    = in[0]->dims()[3];
  // scale factor
  int scale_N = 0, scale_C = 0, scale_H = 0, scale_W = 0;
  if (m_input_label == 1)   // inputs are X and sizes
  {
    scale_N = (int)round(in[1]->data()[0] / (float)N);
    scale_C = (int)round(in[1]->data()[1] / (float)C);
    scale_H = (int)round(in[1]->data()[2] / (float)H_in);
    scale_W = (int)round(in[1]->data()[3] / (float)W_in);
  }
  else if (m_input_label == 2)   // inputs are X and scales
  {
    scale_N = (int)round(in[1]->data()[0]);
    scale_C = (int)round(in[1]->data()[1]);
    scale_H = (int)round(in[1]->data()[2]);
    scale_W = (int)round(in[1]->data()[3]);
  } else {
    std::cerr << "[ERROR] invalid type " << m_input_label<< std::endl;
    return false;
  }

  if (scale_N != 1 || scale_H != 2 || scale_W != 2 || scale_C != 1)
  {
    std::cerr << "[ERROR] invalid scale factor: input: "<<in[0]->dims()<<" scales: "<<*in[1]<<" result=(" << scale_N << ", " << scale_H << ", " << scale_W << ", " << scale_C << ")" << std::endl;
    return false;
  }
  scale_factors.resize(in[1]->dims());
  scale_factors[0] = static_cast<T2>(scale_N);
  scale_factors[1] = static_cast<T2>(scale_H);
  scale_factors[2] = static_cast<T2>(scale_W);
  scale_factors[3] = static_cast<T2>(scale_C);
  // resize m_out
  Dimensions dim;
  dim.resize(4);
  dim[0] = (int)(N * scale_N);
  dim[1] = (int)(H_in * scale_H);
  dim[2] = (int)(W_in * scale_W);
  dim[3] = (int)(C * scale_C);
  m_out.resize(dim);
  m_initDone = true;
  return true;
}

template<typename T> bool Resize<T>::apply(std::vector<Tensor<T> *> &in)
{
  if (m_mode == resize_mode_linear)
    return interpolate_bilinear(in);
  else if (m_mode == resize_mode_nearest)
    return interpolate_nearest(in);
  else if (m_mode == resize_mode_cubic)
    return interpolate_bicubic(in);

  return false;
}

template<typename T> bool Resize<T>::interpolate_bicubic(std::vector<Tensor<T> *> &in)
{
  assert(in.size() == 2);
  assert(in[0]->dims().size() == 4 && in[0]->dims()[0] == 1);
  const Tensor<T> &data = *in[0];
  m_out.quantizer       = data.quantizer;
  m_quantizer           = data.quantizer;

  int shift = m_quantizer;
  int H_out = m_out.dims()[1];
  int W_out = m_out.dims()[2];

  for (int im_i = 0; im_i < H_out; im_i++)
  {
    for (int im_j = 0; im_j < W_out; im_j++)
    {
      T2   ori[4]    = { 0, 0, 0, 0 };
      int  pos[16][2];
      T2   coeffs[16];
      T2  &x_ori = ori[0], &y_ori = ori[1];

      // calculate original pixel position (x_ori, y_ori) and adjacent pixel positions.
      calc_bicubic_positions(im_i, im_j, data.dims()[1], data.dims()[2], pos, ori);

      // coeffs
      get_bicubic_coeffs(y_ori, x_ori, coeffs);

      BICUBIC_COUNTERS(data, coeffs);
      bicubic_in_channels(data, coeffs, pos, shift, im_i, im_j, m_out);
    }
  }
  return true;
}

template<typename T> bool Resize<T>::interpolate_bilinear(std::vector<Tensor<T> *> &in)
{
  assert(in.size() == 2);
  assert(in[0]->dims().size() == 4 && in[0]->dims()[0] == 1);
  const Tensor<T> &data = *in[0];
  m_out.quantizer       = data.quantizer;
  m_quantizer           = data.quantizer;

  int           shift = m_quantizer;
  int           H_out = m_out.dims()[1];
  int           W_out = m_out.dims()[2];

  for (int im_i = 0; im_i < H_out; im_i++)
  {
    for (int im_j = 0; im_j < W_out; im_j++)
    {
      T2   ori[4]    = { 0, 0, 0, 0 };
      int  pos[4]    = { 0, 0, 0, 0 };
      T2   coeffs[4] = { 0, 0, 0, 0 };
      T2  &x_ori = ori[0], &y_ori = ori[1];

      // calculate original pixel position (x_ori, y_ori) and adjacent pixel positions.
      calc_positions(im_i, im_j, data.dims()[1], data.dims()[2], pos, ori);

      // coeffs
      get_bilinear_coeffs(y_ori, x_ori, coeffs);

      BILINEAR_COUNTERS(data, coeffs);
      bilinear_in_channels(data, coeffs, pos, shift, im_i, im_j, m_out);
    }
  }
  return true;
}

template<typename T> bool Resize<T>::interpolate_nearest(std::vector<Tensor<T> *> &in)
{
  assert(in.size() == 2);
  assert(in[0]->dims().size() == 4 && in[0]->dims()[0] == 1);
  const Tensor<T> &data = *in[0];
  m_out.quantizer       = data.quantizer;
  m_quantizer           = data.quantizer;

  int           H_out = m_out.dims()[1];
  int           W_out = m_out.dims()[2];

  for (int im_i = 0; im_i < H_out; im_i++)
  {
    for (int im_j = 0; im_j < W_out; im_j++)
    {
      T2   ori[4]    = { 0, 0, 0, 0 };
      int  pos[4]    = { 0, 0, 0, 0 };
      T2   coeffs[4] = { 0, 0, 0, 0 };
      T2  &x_ori = ori[0], &y_ori = ori[1];
      int &x_ori_left = pos[0], &y_ori_top = pos[1], &x_ori_right = pos[2], &y_ori_bottom = pos[3];
      T2  &x_coeff1 = coeffs[0], &x_coeff2 = coeffs[1], &y_coeff1 = coeffs[2], &y_coeff2 = coeffs[3];

      // calculate original pixel position (x_ori, y_ori) and adjacent pixel positions.
      calc_positions(im_i, im_j, data.dims()[1], data.dims()[2], pos, ori);

      // coeffs
      get_nearest_coeffs(y_ori, y_coeff1, y_coeff2);
      get_nearest_coeffs(x_ori, x_coeff1, x_coeff2);

      int y_ori_nearest = y_ori_top;
      int x_ori_nearest = x_ori_left;
      if (y_coeff1 == 0)
        y_ori_nearest = y_ori_bottom;
      if (x_coeff1 == 0)
        x_ori_nearest = x_ori_right;
      nearest_in_channels(data, im_i, im_j, y_ori_nearest, x_ori_nearest, m_out);
    }
  }
  return true;
}

template<> inline void Resize<float>::calc_bicubic_positions(int y, int x, int H, int W, int pos[][2], float ori[]) const
{
  float &x_ori = ori[0], &y_ori = ori[1], &x_ori_int = ori[2], &y_ori_int = ori[3];

  if (m_coordinate_transformation_mode == resize_coordinate_transformation_mode_half_pixel)
  {
    x_ori = (x + 0.5f) / scale_factors[2] - 0.5f;
    y_ori = (y + 0.5f) / scale_factors[1] - 0.5f;
  }
  else if (m_coordinate_transformation_mode == resize_coordinate_transformation_mode_asymmetric)
  {
    x_ori = x / scale_factors[2];
    y_ori = y / scale_factors[1];
  }
  x_ori_int = std::floor(x_ori);
  y_ori_int = std::floor(y_ori);

  // acquire the positions of 16 adjacent pixels
  int idx = 0;
  for (int dy = -1; dy <= 2; dy++)
  {
    for (int dx = -1; dx <= 2; dx++)
    {
      pos[idx][0] = std::min(std::max((int)(y_ori_int + dy), 0), H - 1);
      pos[idx][1] = std::min(std::max((int)(x_ori_int + dx), 0), W - 1);
      idx++;
    }
  }
}

template<typename T> void Resize<T>::calc_bicubic_positions(int y, int x, int H, int W, int pos[][2], T2 ori[]) const
{
  static_assert(std::is_same<T, int16_t>::value || std::is_same<T, int32_t>::value, "T must be int16_t or int32_t");
  assert(scale_factors[1] == 2 && scale_factors[2] == 2);
  int  shift = m_quantizer;
  T2  &x_ori = ori[0], &y_ori = ori[1], &x_ori_int = ori[2], &y_ori_int = ori[3];
  
  if (m_coordinate_transformation_mode == resize_coordinate_transformation_mode_half_pixel)
  {
    T2 normalize_bias = (T)(1 << (shift - 2));
    x                 = x << shift;
    y                 = y << shift;
    x_ori             = ((x + 1) >> 1) - normalize_bias;
    y_ori             = ((y + 1) >> 1) - normalize_bias;
  }
  else if (m_coordinate_transformation_mode == resize_coordinate_transformation_mode_asymmetric)
  {
    x     = x << shift;
    y     = y << shift;
    x_ori = (x + 1) >> 1;
    y_ori = (y + 1) >> 1;
  }
  x_ori_int = x_ori >> shift;   // floor
  y_ori_int = y_ori >> shift;

  // acquire the positions of 16 adjacent pixels
  int idx = 0;
  for (int dy = -1; dy <= 2; dy++)
  {
    for (int dx = -1; dx <= 2; dx++)
    {
      pos[idx][0] = std::min(std::max((int)(y_ori_int + dy), 0), H - 1);
      pos[idx][1] = std::min(std::max((int)(x_ori_int + dx), 0), W - 1);
      idx++;
    }
  }
}

template<> inline void Resize<float>::calc_positions(int y, int x, int H, int W, int pos[], float ori[])
{
  float &x_ori = ori[0], &y_ori = ori[1], &x_ori_int = ori[2], &y_ori_int = ori[3];
  int   &x_ori_left = pos[0], &y_ori_top = pos[1], &x_ori_right = pos[2], &y_ori_bottom = pos[3];

  if (m_coordinate_transformation_mode == resize_coordinate_transformation_mode_half_pixel)
  {
    x_ori = (x + 0.5f) / scale_factors[2] - 0.5f;
    y_ori = (y + 0.5f) / scale_factors[1] - 0.5f;
  }
  else if (m_coordinate_transformation_mode == resize_coordinate_transformation_mode_asymmetric)
  {
    x_ori = x / scale_factors[2];
    y_ori = y / scale_factors[1];
  }
  x_ori_int = std::floor(x_ori);
  y_ori_int = std::floor(y_ori);

  // acquire the positions of adjacent pixels, prioritizing the left and top pixels
  x_ori_left   = (int)((x_ori == x_ori_int) ? x_ori_int - 1 : x_ori_int);
  y_ori_top    = (int)((y_ori == y_ori_int) ? y_ori_int - 1 : y_ori_int);
  x_ori_right  = x_ori_left + 1;
  y_ori_bottom = y_ori_top + 1;
  x_ori_left   = std::max(0, x_ori_left);
  y_ori_top    = std::max(0, y_ori_top);
  x_ori_right  = std::min(W - 1, x_ori_right);
  y_ori_bottom = std::min(H - 1, y_ori_bottom);
}

template<typename T> void Resize<T>::calc_positions(int y, int x, int H, int W, int pos[], T2 ori[])
{
  assert(scale_factors[1] == 2 && scale_factors[2] == 2);
  int  shift = m_quantizer;
  T2  &x_ori = ori[0], &y_ori = ori[1], &x_ori_int = ori[2], &y_ori_int = ori[3];
  int &x_ori_left = pos[0], &y_ori_top = pos[1], &x_ori_right = pos[2], &y_ori_bottom = pos[3];
  
  if (m_coordinate_transformation_mode == resize_coordinate_transformation_mode_half_pixel)
  {
    T2 normalize_bias = (T)(1 << (shift - 2));
    x                 = x << shift;
    y                 = y << shift;
    x_ori             = ((x + 1) >> 1) - normalize_bias;
    y_ori             = ((y + 1) >> 1) - normalize_bias;
  }
  else if (m_coordinate_transformation_mode == resize_coordinate_transformation_mode_asymmetric)
  {
    x     = x << shift;
    y     = y << shift;
    x_ori = (x + 1) >> 1;
    y_ori = (y + 1) >> 1;
  }
  x_ori_int = x_ori >> shift;   // floor
  y_ori_int = y_ori >> shift;

  // acquire the positions of adjacent pixels, prioritizing the left and top pixels
  x_ori_left   = (int)((x_ori == x_ori_int << shift) ? x_ori_int - 1 : x_ori_int);
  y_ori_top    = (int)((y_ori == y_ori_int << shift) ? y_ori_int - 1 : y_ori_int);
  x_ori_right  = x_ori_left + 1;
  y_ori_bottom = y_ori_top + 1;
  x_ori_left   = std::max(0, x_ori_left);   // boundary clamp
  y_ori_top    = std::max(0, y_ori_top);
  x_ori_right  = std::min(W - 1, x_ori_right);
  y_ori_bottom = std::min(H - 1, y_ori_bottom);
}

template<> inline float Resize<float>::cubic_coeffs(float x, int i) const
{
  if (i == -1)
    return (-3 * x * x * x + 6 * x * x - 3 * x) / 4;
  else if (i == 0)
    return (5 * x * x * x - 9 * x * x + 4) / 4;
  else if (i == 1)
    return (-5 * x * x * x + 6 * x * x + 3 * x) / 4;
  else
    return (3 * x * x * x - 3 * x * x) / 4;
}

template<typename T> inline typename Resize<T>::T2 Resize<T>::cubic_coeffs(T2 x, int i) const
{
  int shift = m_quantizer;
  T2 x2 = x * x;
  ComputationType<T>::quantize(x2, shift);
  T2 x3 = x2 * x;
  ComputationType<T>::quantize(x3, shift);
  if (i == -1)
    return (-3 * x3 + 6 * x2 - 3 * x) >> 2;
  else if (i == 0)
    return (5 * x3 - 9 * x2 + (4 << shift)) >> 2;
  else if (i == 1)
    return (-5 * x3 + 6 * x2 + 3 * x) >> 2;
  else
    return (3 * x3 - 3 * x2) >> 2;
}

template<> inline void Resize<float>::get_bicubic_coeffs(float y_ori, float x_ori, float coeffs[]) const
{
  float x_ori_int = std::floor(x_ori);
  float y_ori_int = std::floor(y_ori);
  float x_ratio   = (x_ori == x_ori_int) ? 1 : x_ori - x_ori_int;
  float y_ratio   = (y_ori == y_ori_int) ? 1 : y_ori - y_ori_int;

  float wx[4], wy[4];
  for (int i = -1; i <= 2; i++)
  {
    wx[i + 1] = cubic_coeffs(x_ratio, i);
    wy[i + 1] = cubic_coeffs(y_ratio, i);
  }

  int idx = 0;
  for (int j = 0; j < 4; j++)
  {
    for (int i = 0; i < 4; i++)
    {
      coeffs[idx++] = wx[i] * wy[j];
    }
  }
}

template<typename T> void Resize<T>::get_bicubic_coeffs(T2 y_ori, T2 x_ori, T2 coeffs[]) const
{
  int shift = m_quantizer;

  T2 x_ori_int = (x_ori >> shift) << shift;
  T2 y_ori_int = (y_ori >> shift) << shift;
  T2 x_ratio   = (x_ori == x_ori_int) ? (T)(1 << shift) : x_ori - x_ori_int;
  T2 y_ratio   = (y_ori == y_ori_int) ? (T)(1 << shift) : y_ori - y_ori_int;

  T2 wx[4], wy[4];
  for (int i = -1; i <= 2; i++)
  {
    wx[i + 1] = cubic_coeffs(x_ratio, i);
    wy[i + 1] = cubic_coeffs(y_ratio, i);
  }

  int idx = 0;
  for (int j = 0; j < 4; j++)
  {
    for (int i = 0; i < 4; i++)
    {
      coeffs[idx] = wx[i] * wy[j] + (T)(1 << (shift - 1));
      ComputationType<T>::quantize(coeffs[idx], shift);
      idx++;
    }
  }
}

template<> inline void Resize<float>::get_bilinear_coeffs(float y_ori, float x_ori, float coeffs[])
{
  float &coeff11 = coeffs[0], &coeff12 = coeffs[1], &coeff21 = coeffs[2], &coeff22 = coeffs[3];

  float x_ori_int = std::floor(x_ori);
  float y_ori_int = std::floor(y_ori);
  float x_ratio   = (x_ori == std::floor(x_ori)) ? 1 : x_ori - x_ori_int;
  float y_ratio   = (y_ori == std::floor(y_ori)) ? 1 : y_ori - y_ori_int;

  float x_coeff1 = 1 - x_ratio;
  float x_coeff2 = x_ratio;
  float y_coeff1 = 1 - y_ratio;
  float y_coeff2 = y_ratio;

  coeff11 = y_coeff1 * x_coeff1;
  coeff12 = y_coeff1 * x_coeff2;
  coeff21 = y_coeff2 * x_coeff1;
  coeff22 = y_coeff2 * x_coeff2;
}

template<typename T> void Resize<T>::get_bilinear_coeffs(T2 y_ori, T2 x_ori, T2 coeffs[])
{
  int shift   = m_quantizer;
  T2 &coeff11 = coeffs[0], &coeff12 = coeffs[1], &coeff21 = coeffs[2], &coeff22 = coeffs[3];

  T2 x_ori_int = x_ori >> shift;
  T2 y_ori_int = y_ori >> shift;
  T2 x_ratio   = (x_ori == (x_ori_int << shift)) ? (T)(1 << shift) : x_ori - (x_ori_int << shift);
  T2 y_ratio   = (y_ori == (y_ori_int << shift)) ? (T)(1 << shift) : y_ori - (y_ori_int << shift);

  T2 x_coeff1 = (T)(1 << shift) - x_ratio;
  T2 x_coeff2 = x_ratio;
  T2 y_coeff1 = (T)(1 << shift) - y_ratio;
  T2 y_coeff2 = y_ratio;

  coeff11 = (y_coeff1 * x_coeff1) >> shift;
  coeff12 = (y_coeff1 * x_coeff2) >> shift;
  coeff21 = (y_coeff2 * x_coeff1) >> shift;
  coeff22 = (y_coeff2 * x_coeff2) >> shift;
}

template<> inline void Resize<float>::get_nearest_coeffs(float ori, float &coeff_1, float &coeff_2)
{
  float ori_int = std::floor(ori);
  float ratio   = (ori == std::floor(ori)) ? 1 : ori - ori_int;

  // if (ratio == std::floor(ratio))
  if (ratio == 1)
  {
    coeff_1 = 0;
    coeff_2 = 1;
    return;
  }
  if (m_nearest_mode == resize_nearest_mode_floor)
  {
    coeff_1 = 1;
    coeff_2 = 0;
    return;
  }
  if (m_nearest_mode == resize_nearest_mode_round_prefer_ceil)
  {
    if (ratio < 0.5)
      coeff_1 = 1;
    else
      coeff_1 = 0;
    coeff_2 = 1 - coeff_1;
    return;
  }
}

template<typename T> void Resize<T>::get_nearest_coeffs(T2 ori, T2 &coeff_1, T2 &coeff_2)
{
  int shift   = m_quantizer;
  T2  ori_int = ori >> shift;   // floor
  T2  ratio   = (ori == (ori_int << shift)) ? (T)(1 << shift) : (ori - (ori_int << shift));

  if (ratio == (T)(1 << shift))
  {
    coeff_1 = 0;
    coeff_2 = 1;
    return;
  }
  if (m_nearest_mode == resize_nearest_mode_floor)
  {
    coeff_1 = 1;
    coeff_2 = 0;
    return;
  }
  if (m_nearest_mode == resize_nearest_mode_round_prefer_ceil)
  {
    if (ratio < (T)(1 << (shift - 1)))
      coeff_1 = 1;
    else
      coeff_1 = 0;
    coeff_2 = 1 - coeff_1;
    return;
  }
}
}   // namespace layers
}   // namespace sadl
