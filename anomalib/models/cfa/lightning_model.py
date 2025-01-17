"""Lightning Implementatation of the CFA Model.

CFA: Coupled-hypersphere-based Feature Adaptation for Target-Oriented Anomaly Localization

Paper https://arxiv.org/abs/2206.04325
"""

# Copyright (C) 2022 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import logging
from typing import List, Optional, Tuple, Union

import torch
from omegaconf import DictConfig, ListConfig
from pytorch_lightning import Callback
from pytorch_lightning.callbacks import EarlyStopping
from pytorch_lightning.utilities.cli import MODEL_REGISTRY
from pytorch_lightning.utilities.types import STEP_OUTPUT
from torch import Tensor
from torch.optim.optimizer import Optimizer

from anomalib.models.cfa.loss import CfaLoss
from anomalib.models.cfa.torch_model import CfaModel
from anomalib.models.components import AnomalyModule

logger = logging.getLogger(__name__)

__all__ = ["Cfa", "CfaLightning"]


@MODEL_REGISTRY
class Cfa(AnomalyModule):
    """CFA: Coupled-hypersphere-based Feature Adaptation for Target-Oriented Anomaly Localization.

    Args:
        input_size (Tuple[int, int]): Size of the model input.
        backbone (str): Backbone CNN network
        gamma_c (int, optional): gamma_c value from the paper. Defaults to 1.
        gamma_d (int, optional): gamma_d value from the paper. Defaults to 1.
        num_nearest_neighbors (int): Number of nearest neighbors.
        num_hard_negative_features (int): Number of hard negative features.
        radius (float): Radius of the hypersphere to search the soft boundary.
    """

    def __init__(
        self,
        input_size: Tuple[int, int],
        backbone: str,
        gamma_c: int = 1,
        gamma_d: int = 1,
        num_nearest_neighbors: int = 3,
        num_hard_negative_features: int = 3,
        radius: float = 1e-5,
    ) -> None:
        super().__init__()
        self.model: CfaModel = CfaModel(
            input_size=input_size,
            backbone=backbone,
            gamma_c=gamma_c,
            gamma_d=gamma_d,
            num_nearest_neighbors=num_nearest_neighbors,
            num_hard_negative_features=num_hard_negative_features,
            radius=radius,
        )
        self.loss_func = CfaLoss(
            num_nearest_neighbors=num_nearest_neighbors,
            num_hard_negative_features=num_hard_negative_features,
            radius=radius,
        )

    def on_train_start(self) -> None:
        """Initialize the centroid for the memory bank computation."""
        self.model.initialize_centroid(data_loader=self.trainer.datamodule.train_dataloader())  # type: ignore

    def training_step(self, batch) -> STEP_OUTPUT:
        """Training step for the CFA model.

        Args:
            batch (dict): Batch input.

        Returns:
            STEP_OUTPUT: Loss value.
        """
        distance = self.model(batch["image"])
        loss = self.loss_func(distance)
        return {"loss": loss}

    def validation_step(self, batch, batch_idx) -> dict:
        """Validation step for the CFA model.

        Args:
            batch (dict): Input batch.
            batch_idx (int): Index of the batch.

        Returns:
            dict: Anomaly map computed by the model.
        """
        batch["anomaly_maps"] = self.model(batch["image"])
        return batch

    # pylint: disable=unused-argument
    def backward(
        self, loss: Tensor, optimizer: Optional[Optimizer], optimizer_idx: Optional[int], *args, **kwargs
    ) -> None:
        """Backward step for the CFA model.

        Args:
            loss (Tensor): Loss value.
            optimizer (Optional[Optimizer]): Optimizer.
            optimizer_idx (Optional[int]): Optimizer index.
        """
        # TODO: Investigate why retain_graph is needed.
        loss.backward(retain_graph=True)


class CfaLightning(Cfa):
    """PL Lightning Module for the CFA model.

    Args:
        hparams (Union[DictConfig, ListConfig]): Model params
    """

    def __init__(self, hparams: Union[DictConfig, ListConfig]) -> None:
        super().__init__(
            input_size=hparams.model.input_size,
            backbone=hparams.model.backbone,
            gamma_c=hparams.model.gamma_c,
            gamma_d=hparams.model.gamma_d,
        )
        self.hparams: Union[DictConfig, ListConfig]  # type: ignore
        self.save_hyperparameters(hparams)

    def configure_callbacks(self) -> List[Callback]:
        """Configure model-specific callbacks.

        Note:
            This method is used for the existing CLI.
            When PL CLI is introduced, configure callback method will be
                deprecated, and callbacks will be configured from either
                config.yaml file or from CLI.
        """
        early_stopping = EarlyStopping(
            monitor=self.hparams.model.early_stopping.metric,
            patience=self.hparams.model.early_stopping.patience,
            mode=self.hparams.model.early_stopping.mode,
        )
        return [early_stopping]

    def configure_optimizers(self) -> torch.optim.Optimizer:
        """Configures optimizers for the CFA Model.

        Note:
            This method is used for the existing CLI.
            When PL CLI is introduced, configure optimizers method will be
                deprecated, and optimizers will be configured from either
                config.yaml file or from CLI.

        Returns:
            Optimizer: Adam optimizer for each decoder
        """
        return torch.optim.AdamW(
            params=self.model.parameters(),
            lr=self.hparams.model.lr,
            weight_decay=self.hparams.model.weight_decay,
            amsgrad=self.hparams.model.amsgrad,
        )
