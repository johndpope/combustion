#!/usr/bin/env python
# -*- coding: utf-8 -*-


from pytorch_lightning.metrics.functional import average_precision

from .bbox_metric import BoxClassificationMetric


class BoxAveragePrecision(BoxClassificationMetric):
    r"""Computes average precision using anchor boxes.

    Args:
        pos_label (float, optional):
            Label type to compute the metric for. Boxes that are not of ``pos_label`` type
            will be discarded. By default all boxes are retained.

        iou_threshold (float):
            Intersection over union threshold for a prediction to be considered a true
            positive.

        true_positive_limit (bool):
            If ``False``, consider all boxes with IoU above threshold with a target box as
            true positives.

        pred_box_limit (int, optional):
            If given, only include the top ``pred_box_limit`` predicted boxes (by score)
            in the calculation.

        compute_on_step: See :class:`pytorch_lightning.metrics.Metric`
        dist_sync_on_step: See :class:`pytorch_lightning.metrics.Metric`
        process_group: See :class:`pytorch_lightning.metrics.Metric`
        dist_sync_fn: See :class:`pytorch_lightning.metrics.Metric`

    Shapes:
        * ``pred`` - :math:`(N, 6)` in form :math:`(x_1, y_1, x_2, y_2, \text{score}, \text{type})`
        * ``target`` - :math:`(N, 5)` in form :math:`(x_1, y_1, x_2, y_2, \text{type})`
    """

    def compute(self):
        return average_precision(self.pred_score, self.binary_target, pos_label=1)
