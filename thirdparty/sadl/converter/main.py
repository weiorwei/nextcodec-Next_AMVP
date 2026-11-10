"""
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
"""

from __future__ import print_function

import argparse
import copy
import struct
from collections import OrderedDict
from enum import IntEnum

import numpy as np
import onnx

# file format:
# MAGIC: SADL0004 [char[8]]
# type_model [int32_t] 0:int32, 1:float, 2:int16
# nb_layers [int32_t]
# nb_inputs [int32_t]
# inputs_id [int32_t[nb_inputs]]
# nb_outputs [int32_t]
# outputs_id [int32_t[nb_outputs]]
# (for all layers:)
#  layer_id [int32_t]
#  op_id    [int32_t]
#  name_size [int32_t]
#  name [char[name_size]]
#  nb_inputs [int32_t]
#  intput_ids [int32_t[nb_inputs]]
#
# (additional information)
#  Const_layer:
#   length_dim [int32_t]
#   dim [int32_t[length_dim]]
#   type [int32_t] 0:int32, 1:float32 2:int16
#   [if integer: quantizer [int32])
#   data [type[prod(dim)]]
#
#  Conv2DTranspose
#    nb_dim_strides [int32_t]
#    strides [int32_t[nb_dim_strides]]
#    quantizer [int32_t]
#
#  Conv2D
#    nb_dim_strides [int32_t]
#    strides [int32_t[nb_dim_strides]]
#    quantizer [int32_t]
#
#  MatMul
#    quantizer [int32_t]
#
#  Mul
#    quantizer [int32_t]
#
#  PlaceHolder
#   length_dim [int32_t]
#   dim [int32_t[length_dim]]
#   quantizer [int32_t]
#
#  MaxPool
#    nb_dim_strides [int32_t]
#    strides [int32_t[nb_dim_strides]]
#    nb_dim_kernel [int32_t]
#    kernel_dim [int32_t[nb_dim_kernel]]


class OPTYPE(IntEnum):
    Const = (1,)
    Placeholder = (2,)
    Identity = (3,)
    BiasAdd = (4,)
    MaxPool = (5,)
    MatMul = (6,)
    Reshape = (7,)
    Relu = (8,)
    Conv2D = (9,)
    Add = (10,)
    ConcatV2 = (11,)
    Mul = (12,)
    Maximum = (13,)
    LeakyReLU = (14,)
    Transpose = (15,)
    Flatten = (16,)
    Shape = (17,)
    Expand = (18,)
    Conv2DTranspose = (19,)
    Slice = (
        20,
    )  # Currently slicing across depth is supported with default step size of 1
    PReLU = (21,)
    # In "tf2cpp", the same layer performs the matrix multiplication
    # and the matrix multiplication by batches.
    BatchMatMul = (6,)
    ScatterND = (22,)
    GridSample = (23,)
    Resize = (24,)
    Compare = (25,)
    Where = (26,)
    Minimum = (27,)
    AveragePool = (28,)
    ReduceMean = (29,)

    # "BatchMatMulV2" did not exist in Tensorflow 1.9. It exists in
    # Tensorflow 1.15.
    BatchMatMulV2 = 6

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name


class DTYPE_SADL(IntEnum):
    FLOAT = (1,)  # float
    INT8 = (3,)  # int8_t
    INT16 = (2,)  # int16_t
    INT32 = 0  # int32_t

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name


class DTYPE_ONNX(IntEnum):
    # https://github.com/onnx/onnx/blob/master/onnx/onnx.in.proto#L483-L485
    FLOAT = (1,)  # float
    INT8 = (3,)  # int8_t
    INT16 = (4,)  # int16_t
    INT32 = (6,)  # int32_t
    INT64 = 7  # int64_t

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name


class Node_Annotation:
    to_remove = False
    transpose_before_in0 = None
    transpose_before_in1 = None
    to_nhwc_after_out = False
    to_transpose = False
    layout_onnx = None

    def __repr__(self):
        return "to_remove={}, to_transpose={}, layout_onnx={}, transpose_before_in0={} transpose_before_in1={} to_nhwc_after_out={}".format(
            self.to_remove,
            self.to_transpose,
            self.layout_onnx,
            self.transpose_before_in0,
            self.transpose_before_in1,
            self.to_nhwc_after_out,
        )


# get attribute name in node
def getAttribute(node, attr):
    for a in node.attribute:
        if a.name == attr:
            return a
    return None


def transpose_tensor(raw_data, dims):
    """
    When convert TF2 to ONNX, ONNX weight's  are not represent in the same way as TF2 weight's
    """
    # print(dims)
    tmp = []
    tmp.append(dims[2])
    tmp.append(dims[3])
    tmp.append(dims[1])
    tmp.append(dims[0])

    x = np.frombuffer(raw_data, dtype=np.float32)
    # if verbose > 3: print(x)
    x = x.reshape(tmp[3], tmp[2], tmp[0] * tmp[1]).transpose().flatten()
    # if verbose > 3: print("after",x)
    return x.tobytes(), tmp


def nchw_to_nhwc(raw_data, dims):
    # print(dims)
    assert dims[0] == 4
    tmp = []
    tmp.append(dims[0])
    x = np.frombuffer(raw_data, dtype=np.int32)
    x2 = []
    x2.append(x[0])
    x2.append(x[2])
    x2.append(x[3])
    x2.append(x[1])
    x = np.asarray(x2)
    return x.tobytes(), tmp


def transpose_matrix(raw_data, dims):
    x = np.frombuffer(raw_data, dtype=np.float32)
    tmp = []
    tmp.append(dims[1])
    tmp.append(dims[0])
    x = x.reshape(dims[0], dims[1])
    x = np.transpose(x)  # moveaxis(x, -2, -1)
    return x.flatten().tobytes(), tmp


def toList(ii):
    d = []
    for i in ii:
        d.append(i)
    return d


def is_constant(name, onnx_initializer):
    for n in onnx_initializer:
        if n.name == name:
            return True
    return False


def is_output(name, onnx_output):
    for out in onnx_output:
        if out.name == name:
            return True
    return False


def parse_graph_input_node(
    input_node, map_onnx_to_myGraph, to_transpose, input_default_value
):
    map_onnx_to_myGraph[input_node.name] = input_node.name
    struct = {}
    struct["inputs"] = []
    struct["additional"] = {}
    if (
        to_transpose
    ):  # data_layout == 'nchw' and len(input_node.type.tensor_type.shape.dim)==4:
        struct["additional"]["dims"] = [
            input_node.type.tensor_type.shape.dim[0].dim_value,
            input_node.type.tensor_type.shape.dim[2].dim_value,
            input_node.type.tensor_type.shape.dim[3].dim_value,
            input_node.type.tensor_type.shape.dim[1].dim_value,
        ]
    else:
        struct["additional"]["dims"] = [
            d.dim_value for d in input_node.type.tensor_type.shape.dim
        ]
    for i in range(len(struct["additional"]["dims"])):
        if struct["additional"]["dims"][i] == 0:
            struct["additional"]["dims"][i] = input_default_value
    # print(struct["additional"]["dims"])
    struct["op_type"] = OPTYPE.Placeholder
    return struct


def extract_additional_data_from_node(data, to_transpose):
    tmp = {}
    if data.dims == []:
        tmp["dims"] = [1]
    else:
        tmp["dims"] = [dim for dim in data.dims]

    tmp["raw_data"] = data.raw_data

    if data.data_type == DTYPE_ONNX.FLOAT:
        tmp["dtype"] = DTYPE_SADL.FLOAT
    elif data.data_type == DTYPE_ONNX.INT8:
        tmp["dtype"] = DTYPE_SADL.INT8
    elif data.data_type == DTYPE_ONNX.INT16:
        tmp["dtype"] = DTYPE_SADL.INT16
    elif data.data_type == DTYPE_ONNX.INT32:
        tmp["dtype"] = DTYPE_SADL.INT32
    elif data.data_type == DTYPE_ONNX.INT64:

        def convert_int64_to_int32(binary_data):
            x = np.frombuffer(binary_data, dtype=np.int64)
            x = x.astype(np.int32)
            return x.tobytes()

        tmp["dtype"] = DTYPE_SADL.INT32
        tmp["raw_data"] = convert_int64_to_int32(tmp["raw_data"])
    else:
        raise ValueError("extract_additional_data: Unknown dtype")
    if to_transpose:
        if len(tmp["dims"]) == 4:
            tmp["raw_data"], tmp["dims"] = transpose_tensor(
                tmp["raw_data"], tmp["dims"]
            )
        elif len(tmp["dims"]) == 2:  # and data_layout == "nchw":
            tmp["raw_data"], tmp["dims"] = transpose_matrix(
                tmp["raw_data"], tmp["dims"]
            )
        elif len(tmp["dims"]) == 1 and tmp["dtype"] == DTYPE_SADL.INT32:
            tmp["raw_data"], tmp["dims"] = nchw_to_nhwc(tmp["raw_data"], tmp["dims"])
        else:
            raise ValueError("extract_additional_data_from_node")
    return tmp["dims"], tmp["raw_data"], tmp["dtype"]


def extract_attribute_values(node):
    L = []
    tmp = getAttribute(node, "value")
    if tmp.t is None:
        return L
    binary_data = tmp.t.raw_data
    data = tmp.t
    if data.data_type == DTYPE_ONNX.FLOAT:
        x = np.frombuffer(binary_data, dtype=np.float)
    elif data.data_type == DTYPE_ONNX.INT8:
        x = np.frombuffer(binary_data, dtype=np.int8)
    elif data.data_type == DTYPE_ONNX.INT16:
        x = np.frombuffer(binary_data, dtype=np.int16)
    elif data.data_type == DTYPE_ONNX.INT32:
        x = np.frombuffer(binary_data, dtype=np.int32)
    elif data.data_type == DTYPE_ONNX.INT64:
        x = np.frombuffer(binary_data, dtype=np.int64)
    else:
        raise ValueError("extract_attribute_values: Unknown dtype")
    return x.tolist()


def extract_additional_data(name, to_transpose, onnx_graph, verbose):
    if verbose:
        print("[INFO] additional data {} transpose={}".format(name, to_transpose))

    for init in onnx_graph.initializer:
        if name == init.name:
            return extract_additional_data_from_node(init, to_transpose)
    for node in onnx_graph.node:  # not found in initializaer, search in Constant
        if name == node.output[0]:
            if node.op_type == "Identity":
                return extract_additional_data(
                    node.input[0], to_transpose, onnx_graph, verbose
                )
            else:
                return extract_additional_data_from_node(
                    node.attribute[0].t, to_transpose
                )
    quit("[ERROR] unable to extract data in {}".format(name))


def extract_dims(name, onnx_graph):
    for init in onnx_graph.initializer:
        if name == init.name:
            return init.dims
    for node in onnx_graph.node:  # not found in initializaer, search in Constant
        if name == node.output[0]:
            a = getAttribute(node, "value")
            if a is not None:
                return a.t.dims
            else:
                return []  # None
    for node in onnx_graph.input:  # not found in initializaer, search in Constant
        if name == node.name:
            return node.type.tensor_type.shape.dim
    quit("[ERROR] unable to extract dims in {}".format(name))


# get the nodes with name as input
def getNodesWithInput(name, model):
    L = []
    for node in model.graph.node:
        for inp in node.input:
            if inp == name:
                L.append(node)
    return L


#
def isInitializer(name, model):
    for node in model.graph.initializer:
        if node.name == name:
            return True
    return False


# get the nodes with name as output
def getNodesWithOutput(name, model):
    for node in model.graph.node:
        for out in node.output:
            if out == name:
                return node
    for node in model.graph.initializer:
        if node.name == name:
            return node
    for node in model.graph.input:
        if node.name == name:
            return node
    # print("[ERROR] not found: {}".format(name))
    return None


# get the nodes with name as output
def getNodesWithOutputNotConst(name, model):
    for node in model.graph.node:
        for out in node.output:
            if out == name:
                if node.op_type == "Identity":
                    return getNodesWithOutputNotConst(node.input[0], model)
                else:
                    return node
    for node in model.graph.input:
        if node.name == name:
            return node
    return None


# get dims from data
def getDims(node):
    if node.data_type != DTYPE_ONNX.INT64:
        quit("[ERROR] bad node type fpr getDims {}".format(node))

    x = np.frombuffer(node.raw_data, dtype=np.int64)
    dims = x.tolist()
    return dims


def getInitializer(name, model_onnx):
    for node in model_onnx.graph.initializer:
        if node.name == name:
            return node
    return None


def add_transpose_to_input(
    node, typet, i, myGraph, model_onnx, node_annotation, map_onnx_to_myGraph
):
    # Transpose inserted
    if isInitializer(node.input[i], model_onnx):  # case of a constant input
        if node.input[i] in myGraph:
            quit(
                f"[ERROR] input already processed {node.input[i]} in processing node {node.name}"
            )
        node_annotation[node.input[i]].to_transpose = True
        return node.input[i]

    n2 = getNodesWithOutputNotConst(node.input[i], model_onnx)
    if hasattr(n2, "type") and hasattr(n2.type, "tensor_type"):
        if len(n2.type.tensor_type.shape.dim) != 4:
            quit(f"[WARNING] cannot transpose tensor with dim !=4")
            return node.input[i]

    in_node = node.input[i]
    reshape_coef_name = in_node + "_COEF_TRANSPOSE_NOT_IN_GRAPH"
    myGraph[reshape_coef_name] = {}
    myGraph[reshape_coef_name]["op_type"] = OPTYPE.Const
    myGraph[reshape_coef_name]["inputs"] = []
    additional = {}
    additional["dims"] = [4]
    if typet == "nchw":
        additional["raw_data"] = np.array(
            [0, 3, 1, 2], dtype=np.int32
        ).tobytes()  # nhwc -> nchw
    else:
        additional["raw_data"] = np.array(
            [0, 2, 3, 1], dtype=np.int32
        ).tobytes()  # nchw -> nhwc
    additional["dtype"] = DTYPE_SADL.INT32
    additional["data"] = node
    myGraph[reshape_coef_name]["additional"] = additional
    map_onnx_to_myGraph[reshape_coef_name] = reshape_coef_name

    nname = in_node + "_TRANSPOSE_NOT_IN_GRAPH"
    myGraph[nname] = {}
    myGraph[nname]["op_type"] = OPTYPE.Transpose
    myGraph[nname]["inputs"] = [map_onnx_to_myGraph[in_node], reshape_coef_name]
    map_onnx_to_myGraph[nname] = nname

    return nname


def add_transpose_to_output(node, myGraph, map_onnx_to_myGraph):
    # Transpose inserted
    # Const
    reshape_coef_name = node.output[0] + "_COEF_TRANSPOSE_AFTER_NOT_IN_GRAPH"
    myGraph[reshape_coef_name] = {}
    myGraph[reshape_coef_name]["op_type"] = OPTYPE.Const
    myGraph[reshape_coef_name]["inputs"] = []
    additional = {}
    additional["dims"] = [4]
    additional["raw_data"] = np.array(
        [0, 2, 3, 1], dtype=np.int32
    ).tobytes()  # nchw -> nhwc
    additional["dtype"] = DTYPE_SADL.INT32
    additional["data"] = node
    myGraph[reshape_coef_name]["additional"] = additional
    map_onnx_to_myGraph[reshape_coef_name] = reshape_coef_name

    nname = node.output[0] + "_TRANSPOSE_AFTER_NOT_IN_GRAPH"
    myGraph[nname] = {}
    myGraph[nname]["op_type"] = OPTYPE.Transpose
    myGraph[nname]["inputs"] = [map_onnx_to_myGraph[node.output[0]], reshape_coef_name]
    map_onnx_to_myGraph[nname] = nname
    map_onnx_to_myGraph[node.output[0]] = nname
    return nname


def parse_graph_node(
    node, model_onnx, myGraph, node_annotation, map_onnx_to_myGraph, verbose
):
    if node.name not in node_annotation:
        print(f"[WARN] node {node.name} never reached: removed")
        return

    if verbose > 1:
        print(f"parse node {node.name} remove={node_annotation[node.name].to_remove}")

    if (
        node_annotation[node.name].transpose_before_in0 is not None
    ):  # layout_onnx == 'nchw' : # need to go back to original layout before process
        n0name = add_transpose_to_input(
            node,
            node_annotation[node.name].transpose_before_in0,
            0,
            myGraph,
            model_onnx,
            node_annotation,
            map_onnx_to_myGraph,
        )
    else:
        if len(node.input) >= 1:
            n0name = node.input[0]
        else:
            n0name = None
    if (
        len(node.input) > 1
        and node_annotation[node.name].transpose_before_in1 is not None
    ):  # layout_onnx == 'nchw' : # need to go back to original layout before process
        n1name = add_transpose_to_input(
            node,
            node_annotation[node.name].transpose_before_in1,
            1,
            myGraph,
            model_onnx,
            node_annotation,
            map_onnx_to_myGraph,
        )
    else:
        if len(node.input) >= 2:
            n1name = node.input[1]
        else:
            n1name = None

    if (
        node.op_type == "Conv"
        or node.op_type == "Gemm"
        or node.op_type == "ConvTranspose"
    ):
        nb_inputs = len(node.input)
        if (nb_inputs != 3) and (nb_inputs != 2):
            raise Exception("parse_graph_node: Error on node type")
        additional = {}
        # Const: weight
        additional["data"] = node
        n2 = getNodesWithOutput(n1name, model_onnx)
        (
            additional["dims"],
            additional["raw_data"],
            additional["dtype"],
        ) = extract_additional_data(
            n1name, node_annotation[n2.name].to_transpose, model_onnx.graph, verbose
        )
        map_onnx_to_myGraph[n1name] = n1name

        myGraph[n1name] = {}
        myGraph[n1name]["inputs"] = []
        myGraph[n1name]["additional"] = additional
        myGraph[n1name]["op_type"] = OPTYPE.Const

        # Conv2d
        inputs, additional = [], {}
        inputs = [map_onnx_to_myGraph[n0name]] + [map_onnx_to_myGraph[n1name]]

        additional["data"] = node
        if node.op_type == "Conv" or node.op_type == "ConvTranspose":
            a = getAttribute(node, "strides")
            additional["strides"] = a.ints
            if node.op_type == "Conv":
                a = getAttribute(node, "group")
                additional["group"] = a.i
            a = getAttribute(node, "pads")
            # if pads is unavailable then no padding
            if a:
                additional["pads"] = a.ints
            else:
                additional["pads"] = [0, 0, 0, 0]
        if node.op_type == "ConvTranspose":
            a = getAttribute(node, "output_padding")
            if a:
                additional["output_padding"] = a.ints
            else:
                additional["output_padding"] = [0, 0]

        if nb_inputs == 2:
            map_onnx_to_myGraph[node.output[0]] = node.output[0]
        elif nb_inputs == 3:
            map_onnx_to_myGraph[node.output[0]] = node.output[0] + "_NOT_IN_GRAPH"

        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["inputs"] = inputs
        myGraph[node.output[0]]["additional"] = additional
        if node.op_type == "Conv":
            myGraph[node.output[0]]["op_type"] = OPTYPE.Conv2D
        elif node.op_type == "ConvTranspose":
            myGraph[node.output[0]]["op_type"] = OPTYPE.Conv2DTranspose
        elif node.op_type == "Gemm":
            myGraph[node.output[0]]["op_type"] = OPTYPE.MatMul

        if nb_inputs == 3:
            additional = {}
            # Const: bias
            additional["data"] = node
            (
                additional["dims"],
                additional["raw_data"],
                additional["dtype"],
            ) = extract_additional_data(node.input[2], False, model_onnx.graph, verbose)
            map_onnx_to_myGraph[node.input[2]] = node.input[2]
            myGraph[node.input[2]] = {}
            myGraph[node.input[2]]["inputs"] = []
            myGraph[node.input[2]]["additional"] = additional
            myGraph[node.input[2]]["op_type"] = OPTYPE.Const
            # BiasAdd
            inputs, additional = [], {}
            inputs = [node.output[0]] + [map_onnx_to_myGraph[node.input[2]]]
            additional["data"] = node
            map_onnx_to_myGraph[node.output[0] + "_NOT_IN_GRAPH"] = None
            myGraph[node.output[0] + "_NOT_IN_GRAPH"] = {}
            myGraph[node.output[0] + "_NOT_IN_GRAPH"]["inputs"] = inputs
            myGraph[node.output[0] + "_NOT_IN_GRAPH"]["additional"] = additional
            myGraph[node.output[0] + "_NOT_IN_GRAPH"]["op_type"] = OPTYPE.BiasAdd

    elif node.op_type == "Relu":
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Relu
        myGraph[node.output[0]]["inputs"] = [map_onnx_to_myGraph[n0name]]
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    # Constant node value has to be skipped for slicing
    # This node is not used by any other onnx model in utests/models directory
    # Const value of slice is taken care inside "Slice" condition
    elif node.op_type == "Constant":  # ~ like an initializer
        pass

    elif node.op_type == "Add":
        swap_inputs = False
        if is_constant(n0name, model_onnx.graph.initializer):
            additional = {}
            additional["data"] = node
            (
                additional["dims"],
                additional["raw_data"],
                additional["dtype"],
            ) = extract_additional_data(n0name, False, model_onnx.graph, verbose)
            map_onnx_to_myGraph[n0name] = n0name
            myGraph[n0name] = {}
            myGraph[n0name]["inputs"] = []
            myGraph[n0name]["additional"] = additional
            myGraph[n0name]["op_type"] = OPTYPE.Const
            swap_inputs = True
        if is_constant(n1name, model_onnx.graph.initializer):
            additional = {}
            additional["data"] = node
            (
                additional["dims"],
                additional["raw_data"],
                additional["dtype"],
            ) = extract_additional_data(n1name, False, model_onnx.graph, verbose)
            map_onnx_to_myGraph[n1name] = n1name
            myGraph[n1name] = {}
            myGraph[n1name]["inputs"] = []
            myGraph[n1name]["additional"] = additional
            myGraph[n1name]["op_type"] = OPTYPE.Const
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Add
        if not swap_inputs:
            D1 = extract_dims(n0name, model_onnx.graph)
            D2 = extract_dims(n1name, model_onnx.graph)
            if len(D1) and len(D2) and len(D1) < len(D2):
                swap_inputs = True

        if swap_inputs:
            myGraph[node.output[0]]["inputs"] = [
                map_onnx_to_myGraph[n1name],
                map_onnx_to_myGraph[n0name],
            ]
        else:
            myGraph[node.output[0]]["inputs"] = [
                map_onnx_to_myGraph[n0name],
                map_onnx_to_myGraph[n1name],
            ]
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "MaxPool":
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.MaxPool
        myGraph[node.output[0]]["inputs"] = [map_onnx_to_myGraph[n0name]]
        myGraph[node.output[0]]["additional"] = {}
        a = getAttribute(node, "strides")
        myGraph[node.output[0]]["additional"]["strides"] = [1, a.ints[0], a.ints[1], 1]
        a = getAttribute(node, "pads")
        if a is None:
            pp = [0, 0, 0, 0]
        else:
            pp = a.ints
        myGraph[node.output[0]]["additional"]["pads"] = pp
        a = getAttribute(node, "kernel_shape")
        myGraph[node.output[0]]["additional"]["kernel_shape"] = [
            1,
            a.ints[0],
            a.ints[1],
            1,
        ]
        myGraph[node.output[0]]["additional"]["data"] = node
        # todo: check pads?
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Mul":
        # check the inputs
        if is_constant(n0name, model_onnx.graph.initializer) and is_constant(
            n1name, model_onnx.graph.initializer
        ):
            quit("[ERROR] unsupported double constants Mul", node)
        swap_inputs = False
        if is_constant(n0name, model_onnx.graph.initializer):
            additional = {}
            additional["data"] = node
            n2 = getNodesWithOutput(n0name, model_onnx)
            (
                additional["dims"],
                additional["raw_data"],
                additional["dtype"],
            ) = extract_additional_data(
                n0name, node_annotation[n2.name].to_transpose, model_onnx.graph, verbose
            )
            map_onnx_to_myGraph[n0name] = n0name
            myGraph[n0name] = {}
            myGraph[n0name]["inputs"] = []
            myGraph[n0name]["additional"] = additional
            myGraph[n0name]["op_type"] = OPTYPE.Const
            swap_inputs = True
        if is_constant(n1name, model_onnx.graph.initializer):
            additional = {}
            additional["data"] = node
            n2 = getNodesWithOutput(n1name, model_onnx)
            (
                additional["dims"],
                additional["raw_data"],
                additional["dtype"],
            ) = extract_additional_data(
                n1name, node_annotation[n2.name].to_transpose, model_onnx.graph, verbose
            )
            map_onnx_to_myGraph[n1name] = n1name
            myGraph[n1name] = {}
            myGraph[n1name]["inputs"] = []
            myGraph[n1name]["additional"] = additional
            myGraph[n1name]["op_type"] = OPTYPE.Const
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Mul
        if swap_inputs:
            myGraph[node.output[0]]["inputs"] = [
                map_onnx_to_myGraph[n1name],
                map_onnx_to_myGraph[n0name],
            ]
        else:
            myGraph[node.output[0]]["inputs"] = [
                map_onnx_to_myGraph[n0name],
                map_onnx_to_myGraph[n1name],
            ]
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Identity" or node.op_type == "Cast":
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Identity
        myGraph[node.output[0]]["inputs"] = [map_onnx_to_myGraph[n0name]]
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "LeakyRelu":
        # leaky coef
        additional = {}
        additional["data"] = node
        additional["dims"] = [1]
        additional["raw_data"] = np.array(
            float(node.attribute[0].f), dtype=np.float32
        ).tobytes()
        additional["dtype"] = DTYPE_SADL.FLOAT
        map_onnx_to_myGraph[node.output[0] + "_COEF_NOT_IN_GRAPH"] = None
        myGraph[node.output[0] + "_NOT_IN_GRAPH"] = {}
        myGraph[node.output[0] + "_NOT_IN_GRAPH"]["inputs"] = []
        myGraph[node.output[0] + "_NOT_IN_GRAPH"]["additional"] = additional
        myGraph[node.output[0] + "_NOT_IN_GRAPH"]["op_type"] = OPTYPE.Const

        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.LeakyReLU
        myGraph[node.output[0]]["inputs"] = [
            map_onnx_to_myGraph[n0name],
            node.output[0] + "_NOT_IN_GRAPH",
        ]
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "PRelu":
        additional = {}
        additional["data"] = node
        n2 = getNodesWithOutput(n1name, model_onnx)
        (
            additional["dims"],
            additional["raw_data"],
            additional["dtype"],
        ) = extract_additional_data(n1name, False, model_onnx.graph, verbose)
        myGraph[n1name] = {}
        myGraph[n1name]["op_type"] = OPTYPE.Const
        myGraph[n1name]["inputs"] = []
        myGraph[n1name]["additional"] = additional
        map_onnx_to_myGraph[n1name] = n1name

        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.PReLU
        myGraph[node.output[0]]["inputs"] = [map_onnx_to_myGraph[n0name]] + [
            map_onnx_to_myGraph[n1name]
        ]
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Flatten":
        inputs, additional = [], {}
        inputs = [map_onnx_to_myGraph[n0name]]
        additional["data"] = node
        a = getAttribute(node, "axis")
        additional["axis"] = a.i
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["inputs"] = inputs
        myGraph[node.output[0]]["additional"] = additional
        myGraph[node.output[0]]["op_type"] = OPTYPE.Flatten
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Shape":
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Shape
        myGraph[node.output[0]]["inputs"] = [map_onnx_to_myGraph[n0name]]
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Expand":
        inputs, additional = [], {}
        inputs = [map_onnx_to_myGraph[n0name], map_onnx_to_myGraph[n1name]]
        additional["data"] = node
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["inputs"] = inputs
        myGraph[node.output[0]]["additional"] = additional
        myGraph[node.output[0]]["op_type"] = OPTYPE.Expand
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Reshape":
        n2 = getNodesWithOutput(n1name, model_onnx)
        if n2 is not None and (not hasattr(n2, "op_type") or n2.op_type == "Constant"):
            # Const
            myGraph[n1name] = {}
            myGraph[n1name]["op_type"] = OPTYPE.Const
            myGraph[n1name]["inputs"] = []
            additional = {}
            n2 = getNodesWithOutput(n1name, model_onnx)
            (
                additional["dims"],
                additional["raw_data"],
                additional["dtype"],
            ) = extract_additional_data(
                n1name, node_annotation[n2.name].to_transpose, model_onnx.graph, verbose
            )
            additional["data"] = node
            myGraph[n1name]["additional"] = additional

        map_onnx_to_myGraph[n1name] = n1name
        n2 = getNodesWithOutput(node.input[0], model_onnx)
        # Reshape
        inputs, additional = [], {}
        inputs = [map_onnx_to_myGraph[n0name], n1name]
        additional["data"] = node
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["inputs"] = inputs
        myGraph[node.output[0]]["additional"] = additional

        # why this? if node.op_type == "Reshape":
        myGraph[node.output[0]]["op_type"] = OPTYPE.Reshape

        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "MatMul":
        # check the inputs
        if is_constant(n0name, model_onnx.graph.initializer) and is_constant(
            n1name, model_onnx.graph.initializer
        ):
            quit("[ERROR] unsupported double constants MatMul", node)
        swap_inputs = False
        if is_constant(n0name, model_onnx.graph.initializer):
            additional = {}
            additional["data"] = node
            n2 = getNodesWithOutput(n0name, model_onnx)
            (
                additional["dims"],
                additional["raw_data"],
                additional["dtype"],
            ) = extract_additional_data(
                n0name, node_annotation[n2.name].to_transpose, model_onnx.graph, verbose
            )
            map_onnx_to_myGraph[n0name] = n0name
            myGraph[n0name] = {}
            myGraph[n0name]["inputs"] = []
            myGraph[n0name]["additional"] = additional
            myGraph[n0name]["op_type"] = OPTYPE.Const
            swap_inputs = True
        if is_constant(n1name, model_onnx.graph.initializer):
            additional = {}
            additional["data"] = node
            n2 = getNodesWithOutput(n1name, model_onnx)
            (
                additional["dims"],
                additional["raw_data"],
                additional["dtype"],
            ) = extract_additional_data(
                n1name, node_annotation[n2.name].to_transpose, model_onnx.graph, verbose
            )
            map_onnx_to_myGraph[n1name] = n1name
            myGraph[n1name] = {}
            myGraph[n1name]["inputs"] = []
            myGraph[n1name]["additional"] = additional
            myGraph[n1name]["op_type"] = OPTYPE.Const
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.MatMul
        if swap_inputs:
            myGraph[node.output[0]]["inputs"] = [
                map_onnx_to_myGraph[n1name],
                map_onnx_to_myGraph[n0name],
            ]
        else:
            myGraph[node.output[0]]["inputs"] = [
                map_onnx_to_myGraph[n0name],
                map_onnx_to_myGraph[n1name],
            ]
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Concat":
        # Const
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Const
        myGraph[node.output[0]]["inputs"] = []
        additional = {}
        additional["dims"] = [1]
        additional["raw_data"] = np.array(node.attribute[0].i, dtype=np.int32).tobytes()
        additional["dtype"] = DTYPE_SADL.INT32
        additional["data"] = node
        myGraph[node.output[0]]["additional"] = additional
        map_onnx_to_myGraph[node.output[0] + "_NOT_IN_GRAPH"] = None

        # Concatenate
        inputs, additional = [], {}
        for inp in node.input:
            inputs.append(map_onnx_to_myGraph[inp])
        inputs.append(node.output[0])
        additional["data"] = node
        myGraph[node.output[0] + "_NOT_IN_GRAPH"] = {}
        myGraph[node.output[0] + "_NOT_IN_GRAPH"]["inputs"] = inputs
        myGraph[node.output[0] + "_NOT_IN_GRAPH"]["additional"] = additional
        myGraph[node.output[0] + "_NOT_IN_GRAPH"]["op_type"] = OPTYPE.ConcatV2
        map_onnx_to_myGraph[node.output[0]] = node.output[0] + "_NOT_IN_GRAPH"

    elif node.op_type == "Max":
        for node_input in [n0name, n1name]:
            if is_constant(node_input, model_onnx.graph.initializer):
                additional = {}
                additional["data"] = node
                n2 = getNodesWithOutput(node_input, model_onnx)
                (
                    additional["dims"],
                    additional["raw_data"],
                    additional["dtype"],
                ) = extract_additional_data(
                    node_input,
                    node_annotation[n2.name].to_transpose,
                    model_onnx.graph,
                    verbose,
                )
                map_onnx_to_myGraph[node_input] = node_input
                myGraph[node_input] = {}
                myGraph[node_input]["inputs"] = []
                myGraph[node_input]["additional"] = additional
                myGraph[node_input]["op_type"] = OPTYPE.Const
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Maximum
        myGraph[node.output[0]]["inputs"] = [
            map_onnx_to_myGraph[n0name],
            map_onnx_to_myGraph[n1name],
        ]
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Min":
        for node_input in [n0name, n1name]:
            if is_constant(node_input, model_onnx.graph.initializer):
                additional = {}
                additional["data"] = node
                n2 = getNodesWithOutput(node_input, model_onnx)
                (
                    additional["dims"],
                    additional["raw_data"],
                    additional["dtype"],
                ) = extract_additional_data(
                    node_input,
                    node_annotation[n2.name].to_transpose,
                    model_onnx.graph,
                    verbose,
                )
                map_onnx_to_myGraph[node_input] = node_input
                myGraph[node_input] = {}
                myGraph[node_input]["inputs"] = []
                myGraph[node_input]["additional"] = additional
                myGraph[node_input]["op_type"] = OPTYPE.Const
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Minimum
        myGraph[node.output[0]]["inputs"] = [
            map_onnx_to_myGraph[n0name],
            map_onnx_to_myGraph[n1name],
        ]
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Unsqueeze":
        # No need to parse Unsqueeze as SADL can handle it.
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Transpose":
        # Const
        reshape_coef_name = node.output[0] + "_COEF_TRANSPOSE"
        myGraph[reshape_coef_name] = {}
        myGraph[reshape_coef_name]["op_type"] = OPTYPE.Const
        myGraph[reshape_coef_name]["inputs"] = []
        additional = {}
        d = toList(getAttribute(node, "perm").ints)
        additional["dims"] = [len(d)]
        additional["raw_data"] = np.array(d, dtype=np.int32).tobytes()
        additional["dtype"] = DTYPE_SADL.INT32
        additional["data"] = node
        myGraph[reshape_coef_name]["additional"] = additional
        map_onnx_to_myGraph[reshape_coef_name] = reshape_coef_name

        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Transpose
        myGraph[node.output[0]]["inputs"] = [
            map_onnx_to_myGraph[n0name],
            reshape_coef_name,
        ]
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Slice":
        # Slice
        if len(node.input) == 5:  # PyTorch
            initializer = getInitializer(node.input[3], model_onnx)
            # Case: In pytorch, Slice is not in model_onnx.graph.initializer but in model_onnx.graph.node
            if initializer is None:
                attribute = getAttribute(
                    getNodesWithOutput(node.input[3], model_onnx), "value"
                )
                initializer = attribute.t
            axes = getDims(initializer)

            initializer = getInitializer(node.input[4], model_onnx)
            # Case: In pytorch, Slice is not in model_onnx.graph.initializer but in model_onnx.graph.node
            if initializer is None:
                attribute = getAttribute(
                    getNodesWithOutput(node.input[4], model_onnx), "value"
                )
                initializer = attribute.t
            steps = getDims(initializer)

            if len(axes) != 1:
                quit(
                    "[ERROR] currently sadl slicing support lenght of axes equal to one"
                )
            if axes[0] == 0:
                quit("[ERROR] currently slicing not supported for first dimension")
            if not (len(steps) == 1 and steps[0] == 1):
                quit("[ERROR] currently step has to be default one")

        # Currently slicing support only across width is added
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Slice
        myGraph[node.output[0]]["inputs"] = [map_onnx_to_myGraph[n0name]]
        # assume depth is the last one, assume axes are always 0, 1, 2, etc.

        initializer = getInitializer(n1name, model_onnx)
        if initializer is None:
            attribute = getAttribute(getNodesWithOutput(n1name, model_onnx), "value")
            initializer = attribute.t
        start = getDims(initializer)

        initializer = getInitializer(node.input[2], model_onnx)
        if initializer is None:
            attribute = getAttribute(
                getNodesWithOutput(node.input[2], model_onnx), "value"
            )
            initializer = attribute.t
        end = getDims(initializer)
        additional = {}
        dim_keys = ["b", "h", "w", "c"]
        for i in range(1, len(dim_keys)):
            additional[f"start_{dim_keys[i]}"] = 0
            additional[f"end_{dim_keys[i]}"] = 2147483647

        # model_onnx got from tensorflow has length of start and end equal to 4
        # model_onnx got from pytorch has length of start and end equal to 1. The dimension of slicing
        # i.e., if slicing is done across C or H or W is controlled by axes
        if len(start) > 1:  # TensorFlow to onnx models
            if start[0] != 0:
                quit("[ERROR] currently slicing not supported for first dimension")
            if end[0] != 2147483647:
                quit("[ERROR] currently slicing not supported for first dimension")
            for i in range(1, len(start)):
                initializer = getInitializer(n1name, model_onnx)
                if initializer is None:
                    attribute = getAttribute(
                        getNodesWithOutput(n1name, model_onnx), "value"
                    )
                    initializer = attribute.t
                start_d = getDims(initializer)[i]

                initializer = getInitializer(node.input[2], model_onnx)
                if initializer is None:
                    attribute = getAttribute(
                        getNodesWithOutput(node.input[2], model_onnx), "value"
                    )
                    initializer = attribute.t
                end_d = getDims(initializer)[i]
                if (
                    end_d > 2147483647
                ):  # The default infinity number in PyTorch INT64 ONNX is 9223372036854775807.
                    end_d = 2147483647
                additional[f"start_{dim_keys[i]}"] = start_d
                additional[f"end_{dim_keys[i]}"] = end_d
        else:  # PyTorch to onnx models
            dim_keys_torch = ["b", "c", "h", "w"]
            for i in range(len(end) - 1):
                if start[i] != 0:
                    quit("[ERROR] currently slicing not supported for first dimension")
                if end[i] < 2147483647:
                    quit("[ERROR] currently slicing only supported for last channel")

            initializer = getInitializer(n1name, model_onnx)
            if initializer is None:
                attribute = getAttribute(
                    getNodesWithOutput(n1name, model_onnx), "value"
                )
                initializer = attribute.t
            start_d = getDims(initializer)[-1]

            initializer = getInitializer(node.input[2], model_onnx)
            if initializer is None:
                attribute = getAttribute(
                    getNodesWithOutput(node.input[2], model_onnx), "value"
                )
                initializer = attribute.t
            end_d = getDims(initializer)[-1]
            if (
                end_d > 2147483647
            ):  # The default infinity number in PyTorch INT64 ONNX is 9223372036854775807.
                end_d = 2147483647
            additional[f"start_{dim_keys_torch[axes[0]]}"] = start_d
            additional[f"end_{dim_keys_torch[axes[0]]}"] = end_d
        myGraph[node.output[0]]["additional"] = additional
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "ScatterND":
        # The default input order for the ScatterND is data, indices, and updates.
        if not is_constant(n1name, model_onnx.graph.initializer):
            quit("[ERROR] The second input of the ScatterND must be indices.")
        # indices
        additional = {}
        additional["data"] = node
        (
            additional["dims"],
            additional["raw_data"],
            additional["dtype"],
        ) = extract_additional_data(n1name, False, model_onnx.graph, verbose)
        if len(additional["dims"]) == 5:
            # When the tensor format is specified as NCHW4 (or NHWC4) and the value of N is 1, the format is transformed
            # to CHW4 (or HWC4). Here, the "4" indicates the position index within a 4-dimensional tensor.
            additional["dims"] = additional["dims"][1:]
            # transpose CHW4 to HWC4
            if node_annotation[n1name].to_transpose:
                tmp = [
                    additional["dims"][1],
                    additional["dims"][2],
                    additional["dims"][0],
                    additional["dims"][3],
                ]
                x = (
                    np.frombuffer(additional["raw_data"], dtype=np.int32)
                    .reshape(additional["dims"])
                    .transpose(1, 2, 0, 3)
                )
                indices = x.copy()
                for i in np.ndindex(indices.shape[:-1]):
                    indices[i] = [
                        indices[i][0],
                        indices[i][2],
                        indices[i][3],
                        indices[i][1],
                    ]
                additional["dims"] = tmp
                additional["raw_data"] = indices.flatten().tobytes()
        else:
            quit("[ERROR] Currently, ScatterND only supports indices of length 5.")
        map_onnx_to_myGraph[n1name] = n1name
        myGraph[n1name] = {}
        myGraph[n1name]["inputs"] = []
        myGraph[n1name]["additional"] = additional
        myGraph[n1name]["op_type"] = OPTYPE.Const

        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.ScatterND
        myGraph[node.output[0]]["inputs"] = [
            map_onnx_to_myGraph[n0name],  # data
            map_onnx_to_myGraph[node.input[2]],  # updates
            map_onnx_to_myGraph[n1name],
        ]  # indices
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "GridSample":
        # Currently, the official TensorFlow does not have an implementation for GridSample.
        align_corners = getAttribute(node, "align_corners").i
        mode = getAttribute(node, "mode").s.decode("utf-8")
        padding_mode = getAttribute(node, "padding_mode").s.decode("utf-8")

        mode_list = ["nearest", "bilinear", "bicubic"]
        if not mode in mode_list:
            quit("[ERROR] Currently, the mode of GridSample must in", mode_list, node)
        else:
            mode = mode_list.index(mode)
        padding_mode_list = ["border"]
        if not padding_mode in padding_mode_list:
            quit(
                "[ERROR] Currently, the padding_mode of GridSample must in",
                padding_mode_list,
                node,
            )
        else:
            padding_mode = padding_mode_list.index(padding_mode)

        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.GridSample
        myGraph[node.output[0]]["inputs"] = [
            map_onnx_to_myGraph[n0name],
            map_onnx_to_myGraph[n1name],
        ]
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        myGraph[node.output[0]]["additional"]["align_corners"] = align_corners
        myGraph[node.output[0]]["additional"]["mode"] = mode
        myGraph[node.output[0]]["additional"]["padding_mode"] = padding_mode
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Resize":
        # Between 2 and 4 inputs. The default input order for the Resize is X, roi, scales, and sizes.
        input_label = 0
        input_list = [map_onnx_to_myGraph[n0name]]
        for input_index, input_name in enumerate(node.input):
            if is_constant(input_name, model_onnx.graph.initializer):
                additional = {}
                additional["data"] = node
                (
                    additional["dims"],
                    additional["raw_data"],
                    additional["dtype"],
                ) = extract_additional_data(
                    input_name, False, model_onnx.graph, verbose
                )
                if (
                    additional["raw_data"] == b""
                ):  # When tensor data is empty, just ignore it.
                    continue

                map_onnx_to_myGraph[input_name] = input_name
                myGraph[input_name] = {}
                myGraph[input_name]["inputs"] = []
                myGraph[input_name]["additional"] = additional
                myGraph[input_name]["op_type"] = OPTYPE.Const
                input_list.append(map_onnx_to_myGraph[input_name])
                input_label = input_label + (1 << (3 - input_index))
        if input_label != 1 and input_label != 2:
            quit(
                "[ERROR] Currently, the inputs of Resize have to be X and sizes, or X and scales."
            )

        # attribute (str -> int)
        coordinate_transformation_mode = getAttribute(
            node, "coordinate_transformation_mode"
        ).s.decode("utf-8")
        cubic_coeff_a = getAttribute(node, "cubic_coeff_a")
        exclude_outside = getAttribute(node, "exclude_outside")
        mode = getAttribute(node, "mode").s.decode("utf-8")
        nearest_mode = getAttribute(node, "nearest_mode").s.decode("utf-8")

        if (
            coordinate_transformation_mode == "half_pixel"
            or coordinate_transformation_mode == "pytorch_half_pixel"
        ):
            coordinate_transformation_mode = 0
        elif coordinate_transformation_mode == "asymmetric":
            coordinate_transformation_mode = 1
        else:
            quit(
                f"[ERROR] Currently, the coordinate_transformation_mode (={coordinate_transformation_mode}) of Resize must in {coordinate_transformation_mode_list} {node}"
            )
        if cubic_coeff_a is None:
            cubic_coeff_a = -0.75
        else:
            cubic_coeff_a = cubic_coeff_a.f
        if not cubic_coeff_a == -0.75:
            quit(
                "[ERROR] Currently, the cubic_coeff_a of Resize must be default -0.75.",
                node,
            )
        if exclude_outside is None:
            exclude_outside = 0
        else:
            exclude_outside = exclude_outside.i
        if not exclude_outside == 0:
            quit(
                "[ERROR] Currently, the exclude_outside of Resize must be default 0.",
                node,
            )
        mode_list = ["linear", "nearest", "cubic"]
        if not mode in mode_list:
            quit("[ERROR] Currently, the mode of Resize must in", mode_list, node)
        else:
            mode = mode_list.index(mode)
        nearest_mode_list = ["floor", "round_prefer_ceil"]
        if not nearest_mode in nearest_mode_list:
            quit(
                "[ERROR] Currently, the nearest_mode of Resize must in",
                nearest_mode_list,
                node,
            )
        else:
            nearest_mode = nearest_mode_list.index(nearest_mode)

        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Resize
        myGraph[node.output[0]]["inputs"] = input_list
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        myGraph[node.output[0]]["additional"]["input_label"] = input_label
        myGraph[node.output[0]]["additional"][
            "coordinate_transformation_mode"
        ] = coordinate_transformation_mode
        myGraph[node.output[0]]["additional"]["mode"] = mode
        myGraph[node.output[0]]["additional"]["nearest_mode"] = nearest_mode
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Less":
        additional = {}
        additional["data"] = node
        if is_constant(n1name, model_onnx.graph.initializer):
            n2 = getNodesWithOutput(n1name, model_onnx)  # constant
            (
                additional["dims"],
                additional["raw_data"],
                additional["dtype"],
            ) = extract_additional_data(n1name, False, model_onnx.graph, verbose)
            myGraph[n1name] = {}
            myGraph[n1name]["op_type"] = OPTYPE.Const
            myGraph[n1name]["inputs"] = []
            myGraph[n1name]["additional"] = additional
            map_onnx_to_myGraph[n1name] = n1name

        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Compare
        myGraph[node.output[0]]["inputs"] = [map_onnx_to_myGraph[n0name]] + [
            map_onnx_to_myGraph[n1name]
        ]
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        myGraph[node.output[0]]["additional"]["mode"] = 0
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Greater":
        additional = {}
        additional["data"] = node
        if is_constant(n1name, model_onnx.graph.initializer):
            n2 = getNodesWithOutput(n1name, model_onnx)  # constant
            (
                additional["dims"],
                additional["raw_data"],
                additional["dtype"],
            ) = extract_additional_data(n1name, False, model_onnx.graph, verbose)
            myGraph[n1name] = {}
            myGraph[n1name]["op_type"] = OPTYPE.Const
            myGraph[n1name]["inputs"] = []
            myGraph[n1name]["additional"] = additional
            map_onnx_to_myGraph[n1name] = n1name

        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Compare
        myGraph[node.output[0]]["inputs"] = [map_onnx_to_myGraph[n0name]] + [
            map_onnx_to_myGraph[n1name]
        ]
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        myGraph[node.output[0]]["additional"]["mode"] = 1
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Where":
        if is_constant(n1name, model_onnx.graph.initializer):
            additional = {}
            additional["data"] = node
            n2 = getNodesWithOutput(n1name, model_onnx)
            (
                additional["dims"],
                additional["raw_data"],
                additional["dtype"],
            ) = extract_additional_data(n1name, False, model_onnx.graph, verbose)
            myGraph[n1name] = {}
            myGraph[n1name]["op_type"] = OPTYPE.Const
            myGraph[n1name]["inputs"] = []
            myGraph[n1name]["additional"] = additional
            map_onnx_to_myGraph[n1name] = n1name
        if is_constant(node.input[2], model_onnx.graph.initializer):
            additional = {}
            additional["data"] = node
            n2 = getNodesWithOutput(node.input[2], model_onnx)
            (
                additional["dims"],
                additional["raw_data"],
                additional["dtype"],
            ) = extract_additional_data(node.input[2], False, model_onnx.graph, verbose)
            myGraph[node.input[2]] = {}
            myGraph[node.input[2]]["op_type"] = OPTYPE.Const
            myGraph[node.input[2]]["inputs"] = []
            myGraph[node.input[2]]["additional"] = additional
            map_onnx_to_myGraph[node.input[2]] = node.input[2]

        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Where
        myGraph[node.output[0]]["inputs"] = (
            [map_onnx_to_myGraph[n0name]]
            + [map_onnx_to_myGraph[n1name]]
            + [map_onnx_to_myGraph[node.input[2]]]
        )
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "Equal":
        additional = {}
        additional["data"] = node
        if is_constant(n1name, model_onnx.graph.initializer):
            n2 = getNodesWithOutput(n1name, model_onnx)  # constant
            (
                additional["dims"],
                additional["raw_data"],
                additional["dtype"],
            ) = extract_additional_data(n1name, False, model_onnx.graph, verbose)
            myGraph[n1name] = {}
            myGraph[n1name]["op_type"] = OPTYPE.Const
            myGraph[n1name]["inputs"] = []
            myGraph[n1name]["additional"] = additional
            map_onnx_to_myGraph[n1name] = n1name

        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.Compare
        myGraph[node.output[0]]["inputs"] = [map_onnx_to_myGraph[n0name]] + [
            map_onnx_to_myGraph[n1name]
        ]
        myGraph[node.output[0]]["additional"] = {}
        myGraph[node.output[0]]["additional"]["data"] = node
        myGraph[node.output[0]]["additional"]["mode"] = 2
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "AveragePool":
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.AveragePool
        myGraph[node.output[0]]["inputs"] = [map_onnx_to_myGraph[n0name]]
        myGraph[node.output[0]]["additional"] = {}
        a = getAttribute(node, "strides")
        myGraph[node.output[0]]["additional"]["strides"] = [1, a.ints[0], a.ints[1], 1]
        a = getAttribute(node, "pads")
        if a is None:
            pp = [0, 0, 0, 0]
        else:
            pp = a.ints
        myGraph[node.output[0]]["additional"]["pads"] = pp
        a = getAttribute(node, "kernel_shape")
        myGraph[node.output[0]]["additional"]["kernel_shape"] = [
            1,
            a.ints[0],
            a.ints[1],
            1,
        ]
        myGraph[node.output[0]]["additional"]["data"] = node
        # todo: check pads?
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    elif node.op_type == "ReduceMean":
        myGraph[node.output[0]] = {}
        myGraph[node.output[0]]["op_type"] = OPTYPE.ReduceMean
        myGraph[node.output[0]]["inputs"] = [map_onnx_to_myGraph[n0name]]
        myGraph[node.output[0]]["additional"] = {}
        a = getAttribute(node, "keepdims")
        if a.i == 0:
            quit(
                "[ERROR] Currently, the value of keepdims in ReduceMean can not be set to 0."
            )
        myGraph[node.output[0]]["additional"]["keepdims"] = a.i
        a = getAttribute(node, "axes")
        myGraph[node.output[0]]["additional"]["axes"] = a.ints
        myGraph[node.output[0]]["additional"]["data"] = node
        map_onnx_to_myGraph[node.output[0]] = node.output[0]

    else:
        raise Exception("[ERROR] node not supported:\n{})".format(node))

    if node_annotation[node.name].to_nhwc_after_out:
        n0name = add_transpose_to_output(node, myGraph, map_onnx_to_myGraph)


def parse_onnx(model_onnx, node_annotation, input_default_value, verbose=False):
    myGraph, map_onnx_to_myGraph = OrderedDict(), {}

    # Inputs
    for inp in model_onnx.graph.input:
        myGraph[inp.name] = parse_graph_input_node(
            inp,
            map_onnx_to_myGraph,
            node_annotation[inp.name].to_transpose,
            input_default_value,
        )

    # Nodes removal
    for node in model_onnx.graph.node:
        if node.name in node_annotation and node_annotation[node.name].to_remove:
            curr_key = node.input[0]
            while (
                map_onnx_to_myGraph[curr_key] is not None
                and map_onnx_to_myGraph[curr_key] != curr_key
            ):
                next_key = map_onnx_to_myGraph[curr_key]
                curr_key = next_key
                if curr_key not in map_onnx_to_myGraph:
                    curr_key = node.input[0]
                    break

            map_onnx_to_myGraph[node.output[0]] = curr_key
        else:
            parse_graph_node(
                node, model_onnx, myGraph, node_annotation, map_onnx_to_myGraph, verbose
            )

    myInputs = []
    for inp in model_onnx.graph.input:
        myInputs.append(inp.name)

    myOutputs = []
    for out in model_onnx.graph.output:
        for key, value in map_onnx_to_myGraph.items():
            if key == out.name:
                myOutputs.append(value)

    return myGraph, myInputs, myOutputs


def dump_onnx(graph, my_inputs, my_outputs, output_filename, verbose=False):
    # graph[my_name]={ op_type
    #                  inputs: []
    #                  dtype:
    #                  onnx : model.graph.node[x]
    #                  }

    # my_input=[my_name, my_name..]
    # outputs=[my_name, ...]
    # print(graph)
    map_name_to_idx = dict()
    for idx, (key, _value) in enumerate(graph.items()):
        map_name_to_idx[key] = idx

    # dbg print(map_name_to_idx)
    with open(output_filename, "wb") as f:
        f.write(str.encode("SADL0004"))
        # output of the network type 0: int32 | 1: float | 2: int16 | default: float(1)
        f.write(struct.pack("i", int(DTYPE_SADL.FLOAT)))

        if verbose:
            print(f"# Nb layers: {len(graph.keys())}")
        f.write(struct.pack("i", int(len(graph.keys()))))

        inputs = []
        for name in my_inputs:
            inputs.append(map_name_to_idx[name])
        if verbose:
            print(f"# Nb inputs: {len(inputs)}")
        f.write(struct.pack("i", int(len(inputs))))
        for i in inputs:
            if verbose:
                print(f"#  input {i}")
            f.write(struct.pack("i", int(i)))

        outputs = []
        for name in my_outputs:
            outputs.append(map_name_to_idx[name])
        if verbose:
            print(f"# Nb outputs: {len(outputs)}")
        f.write(struct.pack("i", int(len(outputs))))
        for i in outputs:
            if verbose:
                print(f"#  output {i}")
            f.write(struct.pack("i", int(i)))

        for (name, node) in graph.items():
            if verbose:
                print(f"# Layer id {map_name_to_idx[name]}")
            f.write(struct.pack("i", int(map_name_to_idx[name])))

            if verbose:
                print("#\t op " + str(node["op_type"]))
            f.write(struct.pack("i", int(node["op_type"].value)))

            # Name size
            if verbose:
                print(f"#\t name_size {len(name)}")
            f.write(struct.pack("i", int(len(name))))

            # Name
            if verbose:
                print(f"#\t name {name}")
            f.write(str.encode(str(name)))

            # Nb inputs
            if verbose:
                print(f"#\t nb_inputs {len(node['inputs'])}")
            f.write(struct.pack("i", int(len(node["inputs"]))))

            for name_i in node["inputs"]:
                idx = map_name_to_idx[name_i]
                if verbose:
                    print(f"#\t\t {idx} ({name_i})")
                f.write(struct.pack("i", int(idx)))

            # Additional info depending on OPTYPE
            if node["op_type"] == OPTYPE.Const:
                if verbose:
                    print(f"#\t nb_dim {len(node['additional']['dims'])}")
                f.write(struct.pack("i", int(len(node["additional"]["dims"]))))

                for dim in node["additional"]["dims"]:
                    if verbose:
                        print(f"#\t\t {dim}")
                    f.write(struct.pack("i", int(dim)))

                if verbose:
                    print(f"#\t dtype {node['additional']['dtype']}")
                f.write(struct.pack("i", int(node["additional"]["dtype"])))

                if node["additional"]["dtype"] != DTYPE_SADL.FLOAT:  # not float
                    if verbose:
                        print("#\t quantizer 0")
                    f.write(struct.pack("i", int(0)))

                f.write(node["additional"]["raw_data"])
            # ???    if "alpha" in layer['additional']:
            #        f.write(struct.pack('f', float(layer['additional']['alpha'])))

            elif node["op_type"] == OPTYPE.Slice:
                dim_keys = ["h", "w", "c"]
                for dim in dim_keys:
                    if verbose:
                        print(
                            f"#\t start_depth index for {dim} slicing",
                            node["additional"][f"start_{dim}"],
                        )
                        print(
                            f"#\t end_depth index for {dim} slicing",
                            node["additional"][f"end_{dim}"],
                        )
                    f.write(struct.pack("i", int(node["additional"][f"start_{dim}"])))
                    f.write(struct.pack("i", int(node["additional"][f"end_{dim}"])))

            elif node["op_type"] == OPTYPE.Conv2D:
                if verbose:
                    print("#\t  nb_dim_strides", len(node["additional"]["strides"]))
                f.write(struct.pack("i", int(len(node["additional"]["strides"]))))

                for stride in node["additional"]["strides"]:
                    if verbose:
                        print(f"#\t\t {stride}")
                    f.write(struct.pack("i", int(stride)))

                if verbose:
                    print("#\t  nb_dim_pads", len(node["additional"]["pads"]))
                f.write(struct.pack("i", int(len(node["additional"]["pads"]))))

                for p in node["additional"]["pads"]:
                    if verbose:
                        print(f"#\t\t {p}")
                    f.write(struct.pack("i", int(p)))

                if verbose:
                    print("#\t  nb_group", node["additional"]["group"])
                f.write(struct.pack("i", int(node["additional"]["group"])))

            elif node["op_type"] == OPTYPE.Conv2DTranspose:
                if verbose:
                    print("#\t  nb_dim_strides", len(node["additional"]["strides"]))
                f.write(struct.pack("i", int(len(node["additional"]["strides"]))))

                for stride in node["additional"]["strides"]:
                    if verbose:
                        print(f"#\t\t {stride}")
                    f.write(struct.pack("i", int(stride)))

                if verbose:
                    print("#\t  nb_dim_pads", len(node["additional"]["pads"]))
                f.write(struct.pack("i", int(len(node["additional"]["pads"]))))

                for p in node["additional"]["pads"]:
                    if verbose:
                        print(f"#\t\t {p}")
                    f.write(struct.pack("i", int(p)))

                if verbose:
                    print(
                        "#\t  nb_dim_output_padding",
                        len(node["additional"]["output_padding"]),
                    )
                f.write(
                    struct.pack("i", int(len(node["additional"]["output_padding"])))
                )

                for p in node["additional"]["output_padding"]:
                    if verbose:
                        print(f"#\t\t {p}")
                    f.write(struct.pack("i", int(p)))

            elif node["op_type"] == OPTYPE.Placeholder:
                if verbose:
                    print(f"#\t nb input dimension {len(node['additional']['dims'])}")
                f.write(struct.pack("i", int(len(node["additional"]["dims"]))))

                for dim in node["additional"]["dims"]:
                    if verbose:
                        print(f"#\t\t {dim}")
                    f.write(struct.pack("i", int(dim)))

                # output the quantizer of the input default: 0
                if verbose:
                    print("#\t quantizer_of_input 0")
                f.write(struct.pack("i", int(0)))

            elif node["op_type"] == OPTYPE.MaxPool:
                if verbose:
                    print("#\t  nb_dim_strides", len(node["additional"]["strides"]))
                f.write(struct.pack("i", int(len(node["additional"]["strides"]))))

                for stride in node["additional"]["strides"]:
                    if verbose:
                        print(f"#\t\t {stride}")
                    f.write(struct.pack("i", int(stride)))

                if verbose:
                    print("#\t  nb_dim_kernel", len(node["additional"]["kernel_shape"]))
                f.write(struct.pack("i", int(len(node["additional"]["kernel_shape"]))))

                for ks in node["additional"]["kernel_shape"]:
                    if verbose:
                        print(f"#\t\t {ks}")
                    f.write(struct.pack("i", int(ks)))

                if verbose:
                    print("#\t  nb_dim_pads", len(node["additional"]["pads"]))
                f.write(struct.pack("i", int(len(node["additional"]["pads"]))))

                for p in node["additional"]["pads"]:
                    if verbose:
                        print(f"#\t\t {p}")
                    f.write(struct.pack("i", int(p)))

            elif node["op_type"] == OPTYPE.Flatten:
                if verbose:
                    print("#\t axis", node["additional"]["axis"])
                f.write(struct.pack("i", int(node["additional"]["axis"])))

            elif node["op_type"] == OPTYPE.GridSample:
                if verbose:
                    print("#\t align_corners", node["additional"]["align_corners"])
                f.write(struct.pack("i", int(node["additional"]["align_corners"])))

                if verbose:
                    print("#\t mode", node["additional"]["mode"])
                f.write(struct.pack("i", int(node["additional"]["mode"])))

                if verbose:
                    print("#\t padding_mode", node["additional"]["padding_mode"])
                f.write(struct.pack("i", int(node["additional"]["padding_mode"])))

            elif node["op_type"] == OPTYPE.Resize:
                if verbose:
                    print("#\t input_label", node["additional"]["input_label"])
                f.write(struct.pack("i", int(node["additional"]["input_label"])))

                if verbose:
                    print(
                        "#\t coordinate_transformation_mode",
                        node["additional"]["coordinate_transformation_mode"],
                    )
                f.write(
                    struct.pack(
                        "i", int(node["additional"]["coordinate_transformation_mode"])
                    )
                )

                if verbose:
                    print("#\t mode", node["additional"]["mode"])
                f.write(struct.pack("i", int(node["additional"]["mode"])))

                if verbose:
                    print("#\t nearest_mode", node["additional"]["nearest_mode"])
                f.write(struct.pack("i", int(node["additional"]["nearest_mode"])))

            elif node["op_type"] == OPTYPE.Compare:
                if verbose:
                    print("#\t mode", node["additional"]["mode"])
                f.write(struct.pack("i", int(node["additional"]["mode"])))

            elif node["op_type"] == OPTYPE.AveragePool:
                if verbose:
                    print("#\t  nb_dim_strides", len(node["additional"]["strides"]))
                f.write(struct.pack("i", int(len(node["additional"]["strides"]))))

                for stride in node["additional"]["strides"]:
                    if verbose:
                        print(f"#\t\t {stride}")
                    f.write(struct.pack("i", int(stride)))

                if verbose:
                    print("#\t  nb_dim_kernel", len(node["additional"]["kernel_shape"]))
                f.write(struct.pack("i", int(len(node["additional"]["kernel_shape"]))))

                for ks in node["additional"]["kernel_shape"]:
                    if verbose:
                        print(f"#\t\t {ks}")
                    f.write(struct.pack("i", int(ks)))

                if verbose:
                    print("#\t  nb_dim_pads", len(node["additional"]["pads"]))
                f.write(struct.pack("i", int(len(node["additional"]["pads"]))))

                for p in node["additional"]["pads"]:
                    if verbose:
                        print(f"#\t\t {p}")
                    f.write(struct.pack("i", int(p)))

            elif node["op_type"] == OPTYPE.ReduceMean:
                if verbose:
                    print("#\t  nb_dim_axes", len(node["additional"]["axes"]))
                f.write(struct.pack("i", int(len(node["additional"]["axes"]))))

                for axis in node["additional"]["axes"]:
                    if verbose:
                        print(f"#\t\t {axis}")
                    f.write(struct.pack("i", int(axis)))

                if verbose:
                    print("#\t keepdims", node["additional"]["keepdims"])
                f.write(struct.pack("?", bool(node["additional"]["keepdims"])))

            if (
                node["op_type"] == OPTYPE.Conv2D
                or node["op_type"] == OPTYPE.Conv2DTranspose
                or node["op_type"] == OPTYPE.MatMul
                or node["op_type"] == OPTYPE.Mul
            ):
                # output the internal quantizer default: 0
                f.write(struct.pack("i", int(0)))

            if verbose:
                print("")


# adhoc to detect a reshape(x,shape(n)) which is transformed into reshape(x, concat(unsqueeze(gather(0,shape(n))),unsqueeze(gather(1,shape(n))),unsqueeze(gather(2,shape(n))),unsqueeze(gather(03shape(n)))))
def detect_silly_reshape(node, model_onnx, node_annotation, verbose):
    if node.op_type != "Concat":
        return False
    a = getAttribute(node, "axis")
    if a.i != 0:
        return False
    if len(node.input) != 4:
        return False
    parent = None
    shape = None
    for i in range(4):
        n2 = getNodesWithOutputNotConst(node.input[i], model_onnx)
        # check all inputs are unsqueze
        if n2.op_type != "Unsqueeze":
            return False
        a = getAttribute(n2, "axes")
        if a.ints != [0]:
            return False
        n2 = getNodesWithOutputNotConst(n2.input[0], model_onnx)
        # check all inputs of unsqueze are gather with prm 0, 1 ,2 ,3
        if n2.op_type != "Gather":
            return False
        if len(n2.input) != 2:
            return False
        n2b = getNodesWithOutputNotConst(n2.input[1], model_onnx)
        t = extract_attribute_values(n2b)
        if len(t) != 1 or int(t[0]) != i:
            return False
        n3 = getNodesWithOutputNotConst(n2.input[0], model_onnx)
        # check inputs of gather are shape
        if n3.op_type != "Shape":
            return False
        if parent is None:
            shape = n3
        p = getNodesWithOutputNotConst(n3.input[0], model_onnx)
        # check all shapes have same input
        if parent is not None and p.name != parent.name:
            return False
        parent = p
    # pass all tests
    node_annotation[node.name].to_remove = True
    for i in range(4):
        n2 = getNodesWithOutputNotConst(node.input[i], model_onnx)  # unsqueeze
        node_annotation[n2.name].to_remove = True
        n2 = getNodesWithOutputNotConst(n2.input[0], model_onnx)  # gather
        node_annotation[n2.name].to_remove = True
        n2b = getNodesWithOutputNotConst(n2.input[0], model_onnx)  # shape
        if n2b.name != shape.name:
            node_annotation[n2b.name].to_remove = True
        n2 = getNodesWithOutputNotConst(n2.input[1], model_onnx)  # cst indices
    # replace concat
    for n in range(len(model_onnx.graph.node)):
        for inp in range(len(model_onnx.graph.node[n].input)):
            if model_onnx.graph.node[n].input[inp] == node.output[0]:
                if verbose > 2:
                    print(
                        "Replace ",
                        model_onnx.graph.node[n],
                        model_onnx.graph.node[n].input[inp],
                        "->",
                        shape.output[0],
                    )
                model_onnx.graph.node[n].input[inp] = shape.output[0]

    return True


# adatp (remove/add) the current node to the data_layout and
# recurse in the output
def annotate_node(
    node, model_onnx, node_annotation, global_data_layout, verbose
):  # recusrive
    if node.name in node_annotation:
        return
    if verbose:
        print("[INFO] annotate_node {} op={}".format(node.name, node.op_type))
    data_layout = None

    # inherit from input
    for inp in node.input:
        n2 = getNodesWithOutputNotConst(inp, model_onnx)
        if n2 is not None:
            if verbose:
                print(f"[INFO]   input: {n2.name}")
            if n2.name in node_annotation:
                if data_layout is None:
                    data_layout = node_annotation[n2.name].layout_onnx
                elif (
                    node_annotation[n2.name].layout_onnx is not None
                    and node_annotation[n2.name].layout_onnx != data_layout
                ):
                    print(
                        f"[ERROR] inputs with different layout node={data_layout} input[{n2.name}]={node_annotation[n2.name].layout_onnx} for\n{node}\n"
                    )
                    # temporary fix
                    # print("[INFO] annotations:\n{" + "\n".join("{!r}: {!r},".format(k, v) for k, v in node_annotation.items())+ "}")
                    # quit()
            else:  # not ready yet
                if verbose > 2:
                    print(f"[INFO]   input not ready: {n2.name}, abord")
                return

    if verbose > 1 and data_layout is None:
        print(
            "[WARNING] no data layout constraints for {}\n {}".format(node.name, node)
        )

    if node.name not in node_annotation:
        node_annotation[node.name] = Node_Annotation()
    node_annotation[node.name].layout_onnx = data_layout  # default

    if node.op_type == "Transpose":  # to clean
        a = getAttribute(node, "perm")
        if data_layout == "nhwc":
            if (
                a.ints[0] == 0 and a.ints[1] == 3 and a.ints[2] == 1 and a.ints[3] == 2
            ):  # nhwc ->nchw
                node_annotation[node.name].to_remove = True  # will be removed
                node_annotation[node.name].layout_onnx = "nchw"  # new layout at output
            else:
                if verbose > 1:
                    print("[WARNING] transpose not for NCHW handling in\n", node)
        elif data_layout == "nchw":
            if (
                a.ints[0] == 0 and a.ints[1] == 2 and a.ints[2] == 3 and a.ints[3] == 1
            ):  # nchw ->nhwc
                node_annotation[node.name].to_remove = True  # will be removed
                node_annotation[node.name].layout_onnx = "nhwc"  # new layout at output
            else:
                if verbose > 1:
                    print("[WARNING] transpose not for NCHW handling in\n", node)
        elif global_data_layout == "nchw":
            if len(a.ints) == 4:  # assume a user tranpose
                node_annotation[node.name].transpose_before_in0 = "nchw"
                node_annotation[node.name].to_nhwc_after_out = True
                node_annotation[node.name].layout_onnx = "nhwc"

        if node_annotation[node.name].to_remove:
            # The GridSample is usually used with Transpose. Cause the optical-flow will be
            # transposed from (N,2,H,W) to (N,H,W,2) and this operation should not be removed.
            # Meanwhile there will not have other operations after transposed feature with
            # shape (N,H,W,2) in PyTorch, so the code in this IF statement will not influnce
            # other situations.
            nexts = getNodesWithInput(node.output[0], model_onnx)
            for n in nexts:
                if n.op_type == "GridSample":
                    node_annotation[node.name].to_remove = False
                    node_annotation[node.name].layout_onnx = "nchw"
                    break

    elif node.op_type == "Shape":
        node_annotation[node.name].layout_onnx = None

    elif node.op_type == "Reshape":

        initializer = getInitializer(node.input[1], model_onnx)
        # Case: In pytorch, Reshape is not in model_onnx.graph.initializer but in model_onnx.graph.node
        if initializer is None:
            attribute = getAttribute(
                getNodesWithOutput(node.input[1], model_onnx), "value"
            )
            if attribute is not None:  # maybe a shape node
                initializer = attribute.t

        if initializer is not None:  # constant case
            dims = getDims(initializer)
            # detect if this reshape is actually added by onnx to emulate a transpose
            # we need to test more if reshpae is for transpose...
            if (
                len(dims) == 4
            ):  # general case should be fine now REMOVED: and (dims[0] == 1 or dims[0] == -1):
                if len(dims) > 1 and data_layout == "nhwc":
                    if dims[1] == 1:  # or dims2 * dims3 == 1 # nhwc ->nchw
                        node_annotation[node.name].to_remove = True  # will be removed
                        node_annotation[
                            node.name
                        ].layout_onnx = "nchw"  # new layout at output
                    else:
                        if global_data_layout == "nchw":
                            node_annotation[node.name].transpose_before_in0 = "nchw"
                            node_annotation[node.name].to_nhwc_after_out = True
                            node_annotation[node.name].layout_onnx = None
                        else:
                            if verbose > 1:
                                print(
                                    "[WARNING] reshape unknown for NODE:\n",
                                    node,
                                    "\n shape: dims=",
                                    dims,
                                )
                            node_annotation[node.name].layout_onnx = None
                elif data_layout == "nchw":
                    node_annotation[node.name].to_nhwc_after_out = True
                    node_annotation[node.name].transpose_before_in0 = "nchw"
                    node_annotation[node.name].layout_onnx = None
                    if verbose > 1:
                        print(" case nchw with cst shape")
                elif data_layout is None:
                    node_annotation[
                        node.name
                    ].layout_onnx = global_data_layout  # back to org
                    if global_data_layout == "nchw":
                        node_annotation[
                            node.name
                        ].to_nhwc_after_out = True  # a bit too agressive
            else:
                node_annotation[node.name].layout_onnx = None
            n2 = getNodesWithOutputNotConst(node.input[0], model_onnx)
            if (
                node_annotation[n2.name].layout_onnx == "nchw"
            ):  # need to go back to original layout before reshape
                node_annotation[node.name].transpose_before_in0 = "nchw"
                if node_annotation[node.name].to_nhwc_after_out is False:
                    node_annotation[node.name].layout_onnx = "nchw"
        else:  # case where shape is not a constant
            if global_data_layout == "nchw":
                node_annotation[
                    node.name
                ].transpose_before_in0 = "nhwc"  # applying a channel last transfo will keep the reshape correct.
                if verbose > 1:
                    print(" case nchw with shape from a tensor")

    elif node.op_type == "Flatten":
        if (
            node_annotation[node.name].layout_onnx == "nchw"
        ):  # need to go back to original layout before reshape
            node_annotation[node.name].transpose_before_in0 = "nchw"

    elif node.op_type == "Concat":
        if data_layout == "nchw":  # nhwc -> nhwc
            a = getAttribute(node, "axis")
            if a.i == 1:
                a.i = 3
            elif a.i == 2:
                a.i = 1
            elif a.i == 3:
                a.i = 2
            elif a.i == -3:
                a.i = -1
        if detect_silly_reshape(node, model_onnx, node_annotation, verbose):
            print("[WARNING] strange ONNX pattern detected and simplified")

    elif node.op_type == "Unsqueeze":
        node_annotation[node.name].to_remove = True

    elif node.op_type == "Conv":
        n2 = getInitializer(node.input[1], model_onnx)
        node_annotation[n2.name].to_transpose = True
        node_annotation[n2.name].layout_onnx = "nhwc"

    elif node.op_type == "ConvTranspose":
        n2 = getInitializer(node.input[1], model_onnx)
        node_annotation[n2.name].to_transpose = True
        node_annotation[n2.name].layout_onnx = "nhwc"

    elif node.op_type == "MatMul":
        if global_data_layout == "nchw":
            dim0 = extract_dims(node.input[0], model_onnx.graph)
            dim1 = extract_dims(node.input[1], model_onnx.graph)
            # note: we assume len==0 is the output of a computing node (conv) and dim is 4.. to refine
            if len(dim0) == 4 or len(dim0) == 0:
                node_annotation[node.name].transpose_before_in0 = "nchw"
                node_annotation[node.name].to_nhwc_after_out = True
            if len(dim1) == 4 or len(dim1) == 0:
                node_annotation[node.name].transpose_before_in1 = "nchw"

    elif node.op_type == "Gemm":
        n2 = getInitializer(node.input[1], model_onnx)
        if global_data_layout == "nchw":
            node_annotation[n2.name].to_transpose = True
        #    node_annotation[n2.name].layout_onnx = 'nhwc'

    elif node.op_type == "ScatterND":
        n2 = getInitializer(node.input[1], model_onnx)
        if global_data_layout == "nchw":
            node_annotation[n2.name].to_transpose = True

    elif node.op_type == "ReduceMean":
        if global_data_layout == "nchw":
            node_annotation[node.name].transpose_before_in0 = "nchw"
            node_annotation[node.name].to_nhwc_after_out = True

    nexts = getNodesWithInput(node.output[0], model_onnx)

    for n in nexts:
        annotate_node(
            n, model_onnx, node_annotation, global_data_layout, verbose
        )  # rec


def annotate_graph(model_onnx, node_annotation, data_layout, verbose):

    # track the data layout in the graph and remove/add layers if necessary
    for inp in model_onnx.graph.input:
        node_annotation[inp.name] = Node_Annotation()
        if len(inp.type.tensor_type.shape.dim) == 4:
            node_annotation[inp.name].layout_onnx = data_layout
            if data_layout == "nchw":
                node_annotation[inp.name].to_transpose = True
        else:
            node_annotation[inp.name].layout_onnx = None

    for inp in model_onnx.graph.initializer:
        node_annotation[inp.name] = Node_Annotation()
        node_annotation[inp.name].layout_onnx = None

    for inp in model_onnx.graph.node:
        if inp.op_type == "Constant":
            node_annotation[inp.name] = Node_Annotation()
            node_annotation[inp.name].layout_onnx = None

    for inp in model_onnx.graph.input:
        nexts = getNodesWithInput(inp.name, model_onnx)
        for n in nexts:
            annotate_node(
                n, model_onnx, node_annotation, data_layout, verbose
            )  # recusrive

    if verbose > 1:
        for node in model_onnx.graph.node:
            if node.op_type == "Transpose" and (
                node.name not in node_annotation
                or not node_annotation[node.name].to_remove
            ):
                print(
                    "[ERROR] preprocess_onnxGraph: all transpose node should be removed but this is not the case here: {}\n{}".format(
                        node.name, node
                    )
                )


def detectDataType(model):  # more adaptation to do here if tf is using nchw
    if model.producer_name == "tf2onnx":
        return "nhwc"
    elif model.producer_name == "pytorch":
        return "nchw"
    else:
        quit("[ERROR] unable to detect data layout")


def dumpModel(
    model_onnx,
    output_filename,
    data_layout,
    verbose,
    user_annotation,
    input_default_value,
):
    """Writes the neural network model in the \"sadl\" format to binary file.

    Parameters
    ----------
    model : onnx model
    output_filename : either str or None
        Path to the binary file to which the neural network model
        is written.
    data_type: None, 'nchw' or 'nhwc'
    verbose : bool
        Is additional information printed?
    """
    model_onnx_copy = copy.deepcopy(model_onnx)
    if data_layout is None:
        data_layout = detectDataType(model_onnx_copy)

    if verbose:
        print("[INFO] assume data type", data_layout)

    if verbose > 1:
        # remove data
        gg = copy.deepcopy(model_onnx.graph)
        for node in gg.initializer:
            node.raw_data = np.array(0.0).tobytes()
        print("[INFO] original graph:\n", gg)
        del gg

    if data_layout != "nhwc" and data_layout != "nchw":
        quit("[ERROR] unsupported layout", data_layout)

    node_annotation = {}
    annotate_graph(model_onnx_copy, node_annotation, data_layout, verbose)

    for k, v in user_annotation.items():
        if k in node_annotation:
            if v.transpose_before_in0 is not None:
                node_annotation[k].transpose_before_in0 = v.transpose_before_in0
            if v.to_nhwc_after_out is not None:
                node_annotation[k].to_nhwc_after_out = v.to_nhwc_after_out
            if v.to_remove is not None:
                node_annotation[k].to_remove = v.to_remove
            if v.to_transpose is not None:
                node_annotation[k].to_transpose = v.to_transpose
        else:
            print("[ERROR] unknown node user custom", k)
            quit()

    if verbose > 1:
        print(
            "INFO] annotations:\n{"
            + "\n".join("{!r}: {!r},".format(k, v) for k, v in node_annotation.items())
            + "}"
        )  # print("[INFO] node annotations:", node_annotation)
    my_graph, my_inputs, my_outputs = parse_onnx(
        model_onnx_copy, node_annotation, input_default_value, verbose=verbose
    )
    dump_onnx(my_graph, my_inputs, my_outputs, output_filename, verbose=verbose)
    if data_layout == "nchw":
        print(
            "[INFO] in SADL, your inputs and outputs has been changed from NCHW to NHWC"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="onnx2sadl conversion", usage="NB: force run on CPU"
    )
    parser.add_argument(
        "--input_onnx",
        action="store",
        nargs="?",
        type=str,
        help="name of the onnx file",
    )
    parser.add_argument(
        "--input_default_value",
        action="store",
        nargs="?",
        type=int,
        default=128,
        help="default values to replace named inputs",
    )
    parser.add_argument(
        "--output",
        action="store",
        nargs="?",
        type=str,
        help="name of model binary file",
    )
    parser.add_argument("--nchw", action="store_true")
    parser.add_argument("--nhwc", action="store_true")
    parser.add_argument("--verbose", action="count")
    parser.add_argument(
        "--do_not_add_transpose_before",
        action="store",
        nargs="+",
        default=[],
        help="specify a node where add transpose before will be disable",
    )
    parser.add_argument(
        "--do_not_add_transpose_after",
        action="store",
        nargs="+",
        default=[],
        help="specify a node where add transpose after will be disable",
    )

    args = parser.parse_args()
    if args.input_onnx is None:
        quit("[ERROR] You should specify an onnx file")
    if args.output is None:
        quit("[ERROR] You should specify an output file")

    print("[INFO] ONNX converter")
    if args.verbose is None:
        args.verbose = 0

    model_onnx = onnx.load(args.input_onnx)

    user_annotation = {}
    for node in args.do_not_add_transpose_before:
        if node not in user_annotation:
            user_annotation[node] = Node_Annotation()
            user_annotation[node].to_remove = None
            user_annotation[node].transpose_before_in0 = None
            user_annotation[node].to_nhwc_after_out = None
            user_annotation[node].to_transpose = None
        user_annotation[node].transpose_before_in0 = False

    for node in args.do_not_add_transpose_after:
        if node not in user_annotation:
            user_annotation[node] = Node_Annotation()
            user_annotation[node].to_remove = None
            user_annotation[node].transpose_before_in0 = None
            user_annotation[node].to_nhwc_after_out = None
            user_annotation[node].to_transpose = None
        user_annotation[node].to_nhwc_after_out = False

    data_layout = None
    if args.nchw:
        data_layout = "nchw"
    elif args.nhwc:
        data_layout = "nhwc"

    dumpModel(
        model_onnx,
        args.output,
        data_layout,
        args.verbose,
        user_annotation,
        args.input_default_value,
    )
