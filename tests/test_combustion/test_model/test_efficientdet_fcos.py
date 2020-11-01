#!/usr/bin/env python
# -*- coding: utf-8 -*-
import gc

import pytest
import torch
from torch import Tensor

from combustion.models import EfficientDetFCOS
from combustion.nn import MobileNetBlockConfig
from combustion.testing import TorchScriptTestMixin, TorchScriptTraceTestMixin


class TestEfficientDetFCOS(TorchScriptTestMixin, TorchScriptTraceTestMixin):
    @pytest.fixture
    def model_type(self):
        return EfficientDetFCOS

    @pytest.fixture
    def data(self):
        return torch.rand(1, 3, 512, 512)

    @pytest.fixture
    def num_classes(self):
        return 3

    @pytest.fixture
    def model(self, num_classes, model_type):
        block1 = MobileNetBlockConfig(4, 8, 3, num_repeats=2, stride=2)
        block2 = MobileNetBlockConfig(8, 16, 3, num_repeats=1, stride=2)
        blocks = [block1, block2]
        model = model_type(num_classes, blocks, [1, 2, 3, 4])
        yield model
        del model
        gc.collect()

    def test_construct(self, model_type, num_classes):
        block1 = MobileNetBlockConfig(4, 8, 3, num_repeats=2)
        block2 = MobileNetBlockConfig(8, 16, 3, num_repeats=1)
        blocks = [block1, block2]
        model_type(num_classes, blocks, [1, 2])
        gc.collect()

    def test_forward(self, model, data, num_classes):
        cls_pred, reg_pred, centering = model(data)
        for x in (cls_pred, reg_pred, centering):
            assert isinstance(x, list)
            assert all([isinstance(y, Tensor) for y in x])

        batch_size = 1

        for i, (cls, reg, cen) in enumerate(zip(cls_pred, reg_pred, centering)):
            assert cls.shape[1] == num_classes
            assert reg.shape[1] == 4
            assert cen.shape[1] == 1

            expected_size = torch.Size([x // (2 ** (i + 2)) for x in data.shape[2:]])
            assert cls.shape[2:] == expected_size
            assert reg.shape[2:] == expected_size
            assert cen.shape[2:] == expected_size
            assert cls.shape[0] == batch_size
            assert reg.shape[0] == batch_size
            assert cen.shape[0] == batch_size

    def test_backward(self, model, data):
        output = model(data)
        scalar = sum([t.sum() for f in output for t in f])
        scalar.backward()

    @pytest.mark.parametrize("compound_coeff", [0, 1, 2])
    def test_from_predefined(self, model_type, compound_coeff, data, num_classes):
        model = model_type.from_predefined(compound_coeff, num_classes)
        assert isinstance(model, model_type)
        assert model.compound_coeff == compound_coeff
        del model

    def test_from_predefined_repeated_calls(self, model_type, data, num_classes):
        model0_1 = model_type.from_predefined(0, num_classes)
        model2_1 = model_type.from_predefined(2, num_classes)
        model2_2 = model_type.from_predefined(2, num_classes)
        model0_2 = model_type.from_predefined(0, num_classes)

        params0_1 = sum([x.numel() for x in model0_1.parameters()])
        params0_2 = sum([x.numel() for x in model0_2.parameters()])
        params2_1 = sum([x.numel() for x in model2_1.parameters()])
        params2_2 = sum([x.numel() for x in model2_2.parameters()])

        assert params2_1 == params2_2
        assert params0_1 == params0_2
        assert params0_2 < params2_1

        print(f"Params: {params2_1}")
        assert params2_1 > 5e6

    def test_create_boxes(self, model_type):
        num_classes = 2
        strides = [8, 16, 32, 64, 128]
        base_size = 512
        sizes = [(base_size // stride,) * 2 for stride in strides]

        pred_cls = [torch.rand(2, num_classes, *size, requires_grad=True) for size in sizes]
        pred_reg = [torch.rand(2, 4, *size, requires_grad=True).mul(512).round() for size in sizes]
        pred_centerness = [torch.rand(2, 1, *size, requires_grad=True) for size in sizes]

        boxes, locations = model_type.create_boxes(pred_cls, pred_reg, pred_centerness, strides)