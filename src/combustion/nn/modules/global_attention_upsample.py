#!/usr/bin/env python
# -*- coding: utf-8 -*-

from typing import Tuple, Union

import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor

from combustion.util import double, single, triple

from ..activations import HardSigmoid
from .dynamic_pad import DynamicSamePad


class _GAUMeta(type):
    def __new__(cls, name, bases, dct):
        x = super().__new__(cls, name, bases, dct)
        if "3d" in name:
            x.Conv = nn.Conv3d
            x.BatchNorm = nn.BatchNorm3d
            x.AdaptiveAvgPool = nn.AdaptiveAvgPool3d
            x.AdaptiveMaxPool = nn.AdaptiveMaxPool3d
            x.Tuple = staticmethod(triple)
            x.UpsampleMode = "trilinear"
        elif "2d" in name:
            x.Conv = nn.Conv2d
            x.BatchNorm = nn.BatchNorm2d
            x.AdaptiveAvgPool = nn.AdaptiveAvgPool2d
            x.AdaptiveMaxPool = nn.AdaptiveMaxPool2d
            x.Tuple = staticmethod(double)
            x.UpsampleMode = "bilinear"
        elif "1d" in name:
            x.Conv = nn.Conv1d
            x.BatchNorm = nn.BatchNorm1d
            x.AdaptiveAvgPool = nn.AdaptiveAvgPool1d
            x.AdaptiveMaxPool = nn.AdaptiveMaxPool1d
            x.Tuple = staticmethod(single)
            x.UpsampleMode = "linear"
        else:
            raise RuntimeError(f"Metaclass: error processing name {cls.__name__}")
        return x


class _AttentionUpsample(nn.Module):
    def __init__(
        self,
        low_filters: int,
        high_filters: int,
        output_filters: int,
        kernel_size: Union[int, Tuple[int, ...]] = 3,
        pool: bool = True,
        low_activation: nn.Module = nn.ReLU(),
        high_activation: nn.Module = HardSigmoid(),
        bn_momentum: float = 0.1,
        bn_epsilon: float = 1e-5,
    ):
        super().__init__()
        kernel_size = self.Tuple(kernel_size)
        self.upsample_mode = self.UpsampleMode
        self.align_corners = False
        self._pool = pool

        self.low_level_path = nn.Sequential(
            DynamicSamePad(self.Conv(low_filters, output_filters, kernel_size, bias=False)),
            self.BatchNorm(output_filters, momentum=bn_momentum, eps=bn_epsilon),
            low_activation,
        )

        # gets weights for low_level
        self.high_level_path = nn.Sequential(
            self.AdaptiveAvgPool(1) if pool else nn.Identity(),
            self.Conv(high_filters, output_filters, 1),
            high_activation,
        )

        # pointwise conv when high_filters != output_filters
        if high_filters != output_filters:
            self.high_level_conv = self.Conv(high_filters, output_filters, 1)
        else:
            self.high_level_conv = nn.Identity()

    def forward(self, low_level: Tensor, high_level: Tensor) -> Tensor:
        low_level = self.low_level_path(low_level)

        # get weights from high level path
        weights = self.high_level_path(high_level)

        # pointwise conv when high_filters != output_filters
        high_level = self.high_level_conv(high_level)

        # upsample high_level feature map and weights to match low_level if needed
        if high_level.shape[2:] != low_level.shape[2:]:
            high_level = F.interpolate(
                high_level, low_level.shape[2:], mode=self.upsample_mode, align_corners=self.align_corners
            )

            if not self._pool:
                weights = F.interpolate(
                    weights, low_level.shape[2:], mode=self.upsample_mode, align_corners=self.align_corners
                )

        return high_level + low_level * weights


class AttentionUpsample2d(_AttentionUpsample, metaclass=_GAUMeta):
    r"""Implements the global attention upsample (GAU) block described in
    `Pyramid Attention Network for Semantic Segmentation`_. This is a
    FPN decoder block for use in semantic segmentation.

    .. image:: ./gau.png
        :width: 500px
        :align: center
        :height: 300px
        :alt: Diagram of Global Attention Upsample.

    .. note::
        For this implementation, high level features denote features that
        were extracted by deep levels of the FPN backbone, while low level features
        are those that were extracted in the shallow levels of the backbone.


    Args:
        low_filters (int):
            Number of input filters for low level feature maps

        high_filters (int):
            Number of input filters for high level feature maps

        output_filters (int):
            Number of output channels

        kernel_size (int or tuple of ints):
            Kernel size for the low-level convolution

        pool (bool):
            By default, a global average pooling step is used when computing weights
            for the low level feature maps. When ``pool=False``, do not apply a
            global average pool when computing attention weights.

        low_activation (:class:`torch.nn.Module`):
            Activation function to use along the low level pathway. By default,
            :class:`torch.nn.ReLU` is used.

        high_activation (:class:`torch.nn.Module`):
            Activation function to use for attention weights. By default,
            :class:`torch.nn.HardSigmoid` is used. Note that the textbook
            GAU layer used :class:`torch.nn.ReLU`.

        bn_momentum (float):
            Batch norm momentum

        bn_epsilon (float):
            Batch norm epsilon

    Shapes:
        * ``low_level`` - :math:`(N, C_l, H_l, W_l)`
        * ``high_level`` - :math:`(N, C_h, H_h, W_h)`
        * Output - :math:`(N, C_o, H_l, W_l)`

    .. note::
        When :math:`C_h \neq C_o`, an additional pointwise convolution is used to map
        :math:`C_h \rightarrow C_o`.

        When :math:`(H_h, W_h) \neq (H_l, W_l)`, upsampling is
        used to ensure output has shape :math:`(H_l, W_l)`.

    .. _Pyramid Attention Network for Semantic Segmentation:
        https://arxiv.org/abs/1805.10180v1
    """


class AttentionUpsample1d(_AttentionUpsample, metaclass=_GAUMeta):
    pass


class AttentionUpsample3d(_AttentionUpsample, metaclass=_GAUMeta):
    pass