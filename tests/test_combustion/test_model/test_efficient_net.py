#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pytest
import torch
from torch import Tensor
from combustion.nn import MobileNetBlockConfig
from combustion.models import EfficientNet1d, EfficientNet2d, EfficientNet3d
from combustion.testing import TorchScriptTestMixin, TorchScriptTraceTestMixin

class EfficientNetBaseTest(TorchScriptTestMixin):

    @pytest.fixture
    def model_type(self):
        raise NotImplementedError()

    @pytest.fixture
    def data(self):
        raise NotImplementedError()

    @pytest.fixture
    def model(self, model_type):
        block1 = MobileNetBlockConfig(4, 8, 3, num_repeats=2, stride=2)
        block2 = MobileNetBlockConfig(8, 16, 3, num_repeats=1, stride=2)
        blocks = [block1, block2]
        return model_type(blocks, 1.0, 1.0)


    def test_construct(self, model_type):
        block1 = MobileNetBlockConfig(4, 8, 3, num_repeats=2)
        block2 = MobileNetBlockConfig(8, 16, 3, num_repeats=1)
        blocks = [block1, block2]
        model_type(blocks, 1.0, 1.0)

    def test_forward(self, model, data):
        output = model(data)
        assert isinstance(output, list)
        assert all([isinstance(x, Tensor) for x in output])
        for out in output:
            assert out.ndim == data.ndim
            assert out.shape[0] == 1

    def test_backward(self, model, data):
        output = model(data)
        flat = torch.cat([x.flatten() for x in output], dim=-1)
        scalar = flat.sum()
        scalar.backward()


class TestEfficientNet1d(EfficientNetBaseTest):
    @pytest.fixture
    def model_type(self):
        return EfficientNet1d

    @pytest.fixture
    def data(self):
        torch.random.manual_seed(42)
        return torch.rand(1, 3, 32, requires_grad=True)

