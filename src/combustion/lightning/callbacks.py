#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
from typing import Any, Optional

import pytorch_lightning as pl
import torch
from pytorch_lightning.callbacks.base import Callback
from torch.jit import ScriptModule


log = logging.getLogger(__name__)


class TorchScriptCallback(Callback):
    r"""Callback to export a model using TorchScript upon completion of training.

    .. note::

        A type hint of :class:`pytorch_lightning.LightningModule`, ``_device: ...`` causes
        problems with TorchScript exports. This type hint must be manually overridden
        as follows::

            >>> class MyModule(pl.LightningModule):
            >>>     _device: torch.device
            >>>     ...

    Args:
        path (str, optional):
            The filepath where the exported model will be saved. If unset, the model will be saved
            in the PyTorch Lightning default save path.

        trace (bool, optional):
            If true, export a :class:`torch.jit.ScriptModule` using :func:`torch.jit.trace`.
            Otherwise, :func:`torch.jit.script` will be used.

        sample_input (Any, optional):
            Sample input data to use with :func:`torch.jit.trace`. If ``sample_input`` is unset and
            ``trace`` is true, the attribute :attr:`example_input_array` will be used as input. If
            ``trace`` is true and :attr:`example_input_array` is unset a :class:`RuntimeError` will
            be raised.
    """

    def __init__(self, path: Optional[str] = None, trace: bool = False, sample_input: Optional[Any] = None):
        self.path = path
        self.trace = trace
        self.sample_input = sample_input

    def on_train_end(self, trainer: pl.Trainer, pl_module: pl.LightningModule) -> None:
        r"""Called after training to export a model using TorchScript.

        Args:
            trainer:
                The :class:`pytorch_lightning.Trainer` instance

            pl_module:
                The :class:`pytorch_lightning.LightningModule` to export.
        """
        # check _device annotation is not ...
        # scripting will fail if _device type annotation is not overridden
        if pl_module.__annotations__["_device"] == ...:
            raise RuntimeError(
                "Please override type annotation for pl_module._device for scripting to work. "
                "Using _deivce: torch.device seems to work."
            )

        path = self.path if self.path is not None else self._get_default_save_path(trainer)

        if self.trace and self.sample_input is None:
            if not hasattr(pl_module, "example_input_array"):
                raise RuntimeError(
                    "Trace export was requested, but sample_input was not given and "
                    "module.example_input_array was not set."
                )
            self.sample_input = pl_module.example_input_array

        if self.trace:
            log.debug("Tracing %s", pl_module.__class__.__name__)
            script = self._get_trace(pl_module)
        else:
            log.debug("Scripting %s", pl_module.__class__.__name__)
            script = self._get_script(pl_module)
        torch.jit.save(script, path)
        log.info("Exported ScriptModule to %s", path)

    def _get_trace(self, pl_module: pl.LightningModule) -> ScriptModule:
        assert self.sample_input is not None
        return torch.jit.trace(pl_module, self.sample_input)

    def _get_script(self, pl_module: pl.LightningModule) -> ScriptModule:
        return torch.jit.script(pl_module)

    def _get_default_save_path(self, trainer: pl.Trainer) -> str:
        if hasattr(trainer, "default_root_dir"):
            return trainer.default_root_dir
        # backwards compat
        elif hasattr(trainer, "default_save_path"):
            return trainer.default_save_path
        else:
            import warnings
            import os

            warnings.warn("Failed to find default path attribute on Trainer")
            return os.getcwd()
