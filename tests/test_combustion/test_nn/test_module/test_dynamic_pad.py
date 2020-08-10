#!/usr/bin/env python
# -*- coding: utf-8 -*-

from math import ceil

import pytest
import torch
import torch.nn as nn
from torch import Tensor

from combustion.nn import DynamicSamePad
from combustion.testing import TorchScriptTestMixin, TorchScriptTraceTestMixin


@pytest.fixture(params=[1, 3, 5])
def kernel_size(request):
    return request.param


@pytest.fixture(params=[1, 2, 3])
def stride(request):
    return request.param


@pytest.fixture(
    params=[pytest.param("constant"), pytest.param("reflect"), pytest.param("replicate"), pytest.param("circular"),]
)
def padding_mode(request):
    return request.param


@pytest.fixture(
    params=[
        pytest.param(lambda k, s: nn.Conv1d(1, 1, k, stride=s), id="conv1d"),
        pytest.param(lambda k, s: nn.Conv3d(1, 1, k, stride=s), id="conv3d"),
        pytest.param(lambda k, s: nn.MaxPool2d(k, stride=s), id="maxpool2d"),
        pytest.param(lambda k, s: nn.AvgPool2d(k, stride=s), id="avgpool2d"),
    ]
)
def base_module(request, kernel_size, stride):
    return request.param(kernel_size, stride)


def test_construct(base_module, padding_mode):
    DynamicSamePad(base_module, padding_mode)


def test_construct_overrides(base_module, padding_mode, kernel_size, stride):
    DynamicSamePad(base_module, padding_mode, kernel_size=kernel_size, stride=stride)


@pytest.mark.parametrize("shape", [(32, 32), (9, 9), (11, 11),])
@pytest.mark.parametrize("override", [True, False])
def test_forward(padding_mode, kernel_size, stride, shape, override):
    base_module = nn.Conv2d(1, 1, kernel_size, stride=stride)
    if not override:
        layer = DynamicSamePad(base_module, padding_mode)
    else:
        layer = DynamicSamePad(base_module, padding_mode, kernel_size=kernel_size, stride=stride)
    inputs = torch.rand(1, 1, *shape, requires_grad=True)

    output = layer(inputs)
    assert isinstance(output, Tensor)
    assert tuple(output.shape[:2]) == (1, 1)
    assert tuple(output.shape[2:]) == tuple([ceil(x / stride) for x in shape])
    assert output.requires_grad


class TestScript(TorchScriptTestMixin, TorchScriptTraceTestMixin):
    @pytest.fixture
    def model(self):
        return DynamicSamePad(nn.Conv2d(1, 1, 3, stride=2))

    @pytest.fixture
    def data(self):
        return torch.rand(1, 1, 11, 11)