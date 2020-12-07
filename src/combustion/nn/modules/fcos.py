#!/usr/bin/env python
# -*- coding: utf-8 -*-


from abc import ABC, abstractclassmethod
from typing import Callable, List, Optional, Tuple

import torch
import torch.nn as nn
from torch import Tensor
from torchvision.ops import batched_nms

from combustion.vision import batch_box_target

from .fpn_shared_head import SharedDecoder2d


class BaseFCOSDecoder(nn.Module, ABC):
    def __init__(
        self,
        in_channels: int,
        num_classes: int,
        num_regressions: int,
        num_convs: int,
        strides: Optional[Tuple[int]] = None,
        activation: nn.Module = nn.ReLU(inplace=True),
        reg_activation: nn.Module = nn.ReLU(inplace=True),
        bn_momentum: float = 0.1,
        bn_epsilon: float = 1e-5,
    ):
        super().__init__()
        self.cls_head = SharedDecoder2d(
            in_channels,
            num_classes,
            num_convs,
            strides=strides,
            activation=activation,
            final_activation=nn.Identity(),
            bn_momentum=bn_momentum,
            bn_epsilon=bn_epsilon,
        )

        self.reg_head = SharedDecoder2d(
            in_channels,
            num_regressions + 1,
            num_convs,
            strides=strides,
            activation=activation,
            final_activation=nn.Identity(),
            bn_momentum=bn_momentum,
            bn_epsilon=bn_epsilon,
        )
        self.reg_activation = reg_activation

    def forward(self, fpn: Tuple[Tensor]) -> Tuple[List[Tensor], List[Tensor], List[Tensor]]:
        cls = self.cls_head(fpn)
        _ = self.reg_head(fpn)
        centerness = [layer[..., 0:1, :, :] for layer in _]
        reg = [self.reg_activation(layer[..., 1:, :, :]) for layer in _]
        return cls, reg, centerness

    @abstractclassmethod
    def postprocess(clazz, cls: List[Tensor], reg: List[Tensor], centerness: List[Tensor]) -> Tensor:
        raise NotImplementedError()

    @staticmethod
    def reduce_heatmaps(
        heatmap: Tuple[Tensor, ...], reduction: Callable[[Tensor, Tensor], Tensor] = torch.max, mode: str = "nearest"
    ) -> Tensor:
        result = heatmap[0]
        for i in range(len(heatmap) - 1):
            current_level = F.interpolate(heatmap[i + 1], result.shape[-2:], mode=mode)
            result = combine(current_level, result)
        return top


class FCOSDecoder(BaseFCOSDecoder):
    r"""Decoder for Fully Convolutional One-Stage Object Detector (FCOS) as described
    in PAPER. FCOS is an anchor-free object detection implementation that predicts
    detection, regression, and centerness heatmaps at each FPN level. These predictions
    are postprocessed to create a set of anchor boxes.

    Args:
        in_channels (int):
            Number of input channels at each FPN level.

        num_classes (int):
            Number of classes to detect.

        num_convs (int):
            Number of convolutional repeats in each decoder head.

        strides (tuple of ints, optional):
            Strides at each FPN level.  By default, assume each FPN level differs
            in stride by a factor of 2.

        activation (nn.Module):
            Activation function for each intermediate repeat in the heads.

        bn_momentum (float):
            Momentum value for batch norm

        bn_epsilon (float):
            Epsilon value for batch norm

    Returns:
        List of classification, regression, and centerness predictions for each
        FPN level.

    Shape:
        * ``fpn`` - :math:`(N, C, H_i, W_i)` where :math:`i` is the :math:`i`'th FPN level
        * Classification - :math:`(N, O, H_i, W_i)` where :math:`O` is the number of classes
        * Regression - :math:`(N, 4, H_i, W_i)`
        * Centerness - :math:`(N, 1, H_i, W_i)`
    """

    def __init__(
        self,
        in_channels: int,
        num_classes: int,
        num_convs: int,
        strides: Optional[Tuple[int]] = None,
        activation: nn.Module = nn.ReLU(inplace=True),
        bn_momentum: float = 0.1,
        bn_epsilon: float = 1e-5,
    ):

        super().__init__(
            in_channels,
            num_classes,
            4,
            num_convs,
            strides,
            activation,
            nn.ReLU(inplace=True),
            bn_momentum,
            bn_epsilon,
        )

    @classmethod
    def postprocess(
        clazz,
        cls: Tuple[Tensor, ...],
        reg: Tuple[Tensor, ...],
        centerness: Tuple[Tensor, ...],
        strides: Tuple[int, ...],
        threshold: float = 0.05,
        pad_value: float = -1,
        from_logits: bool = False,
        nms_threshold: Optional[float] = 0.5,
        use_raw_score: bool = False,
    ) -> Tensor:
        r"""Postprocesses detection, regression, and centerness predictions into a set
        of anchor boxes.

        Args:
            cls (iterable of tensors):
                Classification predictions at each FPN level

            reg (iterable of tensors):
                Regression predictions at each FPN level

            centerness (iterable of tensors):
                Centerness predictions at each FPN level

            strides (tuple of ints):
                Strides at each FPN level.

            threshold (float):
                Detection confidence threshold

            from_logits (bool):
                If ``True``, assume that ``cls`` and ``centerness`` are logits and not
                probabilities.

            nms_threshold (float, optional):
                Threshold for non-maximal suppression. If ``None``, do not apply NMS.

            use_raw_score (bool):
                If ``True``, assign scores to boxes based on their predicted classification score.
                Otherwise, scores are assigned based on classification and centerness scores.

        Returns:
            Predicted boxes in the form :math:`(x_1, y_1, x_2, y_x, score, class)`.

        Shape:
            * ``cls`` - :math:`(*, C, H_i, W_i)` where :math:`i` is the :math:`i`'th FPN level
            * ``reg`` - :math:`(*, 4, H_i, W_i)` where :math:`i` is the :math:`i`'th FPN level
            * ``centerness`` - :math:`(*, 1, H_i, W_i)` where :math:`i` is the :math:`i`'th FPN level
            * Output - :math:`(*, N, 6)`
        """
        threshold = abs(float(threshold))
        nms_threshold = abs(float(nms_threshold)) if nms_threshold is not None else None
        assert len(strides) == len(cls)
        assert len(strides) == len(reg)
        assert len(strides) == len(centerness)

        _ = [x * strides[0] for x in cls[0].shape[-2:]]
        y_lim, x_lim = _

        batch_idx, boxes = [], []

        batch_size = cls[0].shape[0]
        num_classes = cls[0].shape[1]

        # iterate over each FPN level
        for i, (stride, level_cls, level_reg, level_centerness) in enumerate(zip(strides, cls, reg, centerness)):

            if from_logits:
                level_cls = torch.sigmoid(level_cls)
                level_centerness = torch.sigmoid(level_centerness)

            # scale classifications based on centerness
            scaled_score = (level_cls * level_centerness.expand_as(level_cls)).sqrt_()

            # get indices of positions that exceed threshold
            positive_locations = (level_cls >= threshold).nonzero(as_tuple=False)

            if not positive_locations.numel():
                continue

            # extract coordinates of positive predictions and drop scores for negative predictions
            batch, cls, y, x = positive_locations.split(1, dim=-1)
            raw_score = level_cls[batch, cls, y, x]
            scaled_score = scaled_score[batch, cls, y, x]

            # use stride to compute base coodinates within the original image
            # use pred regression to compute l, t, r, b offset
            base = (positive_locations[..., (-1, -2)] * stride).add_(int(stride / 2)).repeat(1, 2)
            offset = level_reg[batch, :, y, x].view_as(base)
            offset[..., :2].neg_()

            # compute final regressions and clamp to lie within image_size
            coords = (base + offset).clamp_min_(0)
            coords[..., 2].clamp_max_(x_lim)
            coords[..., 3].clamp_max_(y_lim)

            # record the boxes and box -> batch mapping
            boxes.append(torch.cat([coords, raw_score, scaled_score, cls], dim=-1))
            batch_idx.append(batch)

        # combine boxes across all FPN levels
        if boxes:
            boxes = torch.cat(boxes, dim=-2)
            batch_idx = torch.cat(batch_idx, dim=-2)
        else:
            boxes = coords.new_empty(batch_size, 0, 6)
            return boxes, []

        # apply NMS to boxes
        if nms_threshold is not None:
            coords = boxes[..., :4]
            raw_score = boxes[..., -3, None]
            scaled_score = boxes[..., -2, None]
            cls = boxes[..., -1, None]

            # torchvision NMS cant do batches of images, but it can separate based on class id
            # create a new "class id" that distinguishes batch and class
            idx = (batch_idx * num_classes + cls.view_as(batch_idx)).view(-1).long()
            keep = batched_nms(coords.float(), scaled_score.view(-1), idx, nms_threshold)
            boxes = boxes[keep, :]
            batch_idx = batch_idx[keep, :]

        # create final box using raw or centerness adjusted score as specified
        if use_raw_score:
            boxes = boxes[..., (0, 1, 2, 3, 4, 6)]
        else:
            boxes = boxes[..., (0, 1, 2, 3, 5, 6)]

        # pack boxes into a padded batch
        boxes = [boxes[(batch_idx == i).view(-1), :] for i in range(batch_size)]
        boxes = batch_box_target(boxes, pad_value)
        return boxes
