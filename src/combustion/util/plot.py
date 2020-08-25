#!/usr/bin/env python
# -*- coding: utf-8 -*-

from typing import Tuple, Union

import torch
from matplotlib import cm
from torch import Tensor


def apply_colormap(inputs: Tensor, cmap: str = "gnuplot") -> Tensor:
    r"""Applies a Matplotlib colormap to a tensor, returning a tensor.

    Args:
        inputs (:class:`torch.Tensor`):
            Tensor to apply colormap to

        cmap (str):
            The Matplotlib colormap

    Shape
        * ``inputs`` - :math:`(B, 1, *)`
        * Output - :math:`(B, 4, *)`
    """
    channel_dim = 1
    batch_dim = 0
    if inputs.shape[channel_dim] != 1:
        raise ValueError(f"Expected channel size = 1, but found inputs.shape == {inputs.shape}")
    cmap = cm.get_cmap(cmap)

    output_shape = list(inputs.shape)
    output_channels = 4
    output_shape[channel_dim] = output_channels

    output: List[Tensor] = []
    _ = inputs.flatten(start_dim=channel_dim, end_dim=-1).numpy()
    for batch_elem in _:
        mapped = torch.as_tensor(cmap(batch_elem), device=inputs.device, dtype=torch.float).transpose_(0, 1)
        output.append(mapped)

    return torch.stack(output, dim=batch_dim).view(*output_shape)


def alpha_blend(
    src: Tensor, dest: Tensor, src_alpha: Union[float, Tensor] = 0.5, dest_alpha: Union[float, Tensor] = 1.0
) -> Tuple[Tensor, Tensor]:
    r"""Alpha blends two tensors

    Args:
        src (:class:`torch.Tensor`):
            Source tensor to be blended

        dest (:class:`torch.Tensor`):
            Destination tensor to be blended

        src_alpha (float or :class:`torch.Tensor`):
            Alpha for source tensor

        dest_alpha (float or :class:`torch.Tensor`):
            Alpha for source tensor

    Returns:
        Tuple of (blended channels, blended alpha)

    Shape
        * ``src`` - :math:`(B, C, *)`
        * ``dest`` - :math:`(B, C, *)`
        * Output - Tuple of shapes (:math:`(B, C, *)`, :math:`(B, 1, *)`)
    """
    if src.shape != dest.shape:
        raise ValueError(f"src and dest shape mismatch: {src.shape} vs {dest.shape}")
    dest = dest.type_as(src)

    # source alpha preprocess
    if isinstance(src_alpha, Tensor):
        if src_alpha.shape != src.shape:
            raise ValueError(f"src and src_alpha shape mismatch: {src.shape} vs {src_alpha.shape}")
    else:
        src_alpha = torch.as_tensor(src_alpha, device=src.device)
    src_alpha = src_alpha.type_as(src).expand_as(src)

    # dest alpha preprocess
    if isinstance(dest_alpha, Tensor):
        if dest_alpha.shape != dest.shape:
            raise ValueError(f"dest and dest_alpha shape mismatch: {dest.shape} vs {dest_alpha.shape}")
    else:
        dest_alpha = torch.tensor(dest_alpha, device=dest.device)
    dest_alpha = dest_alpha.type_as(dest).expand_as(src)

    output_alpha = src_alpha + (1 - src_alpha).mul_(dest_alpha)
    output_channels = (src * src_alpha + (1 - src_alpha).mul_(dest).mul_(dest_alpha)).div_(output_alpha)
    return output_channels, output_alpha