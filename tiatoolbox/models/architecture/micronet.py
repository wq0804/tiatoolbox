# ***** BEGIN GPL LICENSE BLOCK *****
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# The Original Code is Copyright (C) 2021, TIA Centre, University of Warwick
# All rights reserved.
# ***** END GPL LICENSE BLOCK *****
"""Defines MicroNet architecture.

Raza, SEA et al., “Micro-Net: A unified model for segmentation of
various objects in microscopy images,” Medical Image Analysis,
Dec. 2018, vol. 52, p. 160–173.

"""

from collections import OrderedDict

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as functional
from scipy import ndimage
from skimage import morphology

from tiatoolbox.models.abc import ModelABC
from tiatoolbox.models.architecture.hovernet import HoVerNet
from tiatoolbox.utils import misc


def group1_forward_branch(layer, in_tensor, resized_feat):
    """Defines group 1 connections.

    Args:
        layer (torch.nn.Module): Network layer.
        in_tensor (torch.Tensor): Input tensor.
        resized_feat (torch.Tensor): Resized input.

    Returns:
        torch.Tensor: Output of group 1 layer.

    """
    a = layer["conv1"](in_tensor)
    a = layer["conv2"](a)
    a = layer["pool"](a)
    b = layer["conv3"](resized_feat)
    b = layer["conv4"](b)
    return torch.cat(tensors=(a, b), dim=1)


def group2_forward_branch(layer, in_tensor):
    """Defines group 1 connections.

    Args:
        layer (torch.nn.Module): Network layer.
        in_tensor (torch.Tensor): Input tensor.

    Returns:
        torch.Tensor: Output of group 1 layer.

    """
    a = layer["conv1"](in_tensor)
    return layer["conv2"](a)


def group3_forward_branch(layer, main_feat, skip):
    """Defines group 1 connections.

    Args:
        layer (torch.nn.Module): Network layer.
        main_feat (torch.Tensor): Input tensor.
        skip (torch.Tensor): Skip connection.

    Returns:
        torch.Tensor: Output of group 1 layer.

    """
    a = layer["up1"](main_feat)
    a = layer["conv1"](a)
    a = layer["conv2"](a)

    b1 = layer["up2"](a)
    b2 = layer["up3"](skip)
    b = torch.cat(tensors=(b1, b2), dim=1)
    return layer["conv3"](b)


def group4_forward_branch(layer, in_tensor):
    """Defines group 1 connections.

    Args:
        layer (torch.nn.Module): Network layer.
        in_tensor (torch.Tensor): Input tensor.

    Returns:
        torch.Tensor: Output of group 1 layer.

    """
    a = layer["up1"](in_tensor)
    return layer["conv1"](a)


def group1_arch_branch(in_ch: int, resized_in_ch: int, out_ch: int):
    """Group1 branch for MicroNet.

    Args:
        in_ch (int): Number of input channels.
        resized_in_ch (int): Number of input channels from
            resized input.
        out_ch (int): Number of output channels.

    Returns:
        torch.nn.ModuleDict: An output of type :class:`torch.nn.ModuleDict`

    """
    module_dict = OrderedDict()
    module_dict["conv1"] = nn.Sequential(
        nn.Conv2d(
            in_ch,
            out_ch,
            kernel_size=(3, 3),
            stride=(1, 1),
            padding=0,
            bias=True,
        ),
        nn.Tanh(),
        nn.BatchNorm2d(out_ch),
    )
    module_dict["conv2"] = nn.Sequential(
        nn.Conv2d(
            out_ch,
            out_ch,
            kernel_size=(3, 3),
            stride=(1, 1),
            padding=0,
            bias=True,
        ),
        nn.Tanh(),
    )
    module_dict["pool"] = nn.MaxPool2d(2, padding=0)  # check padding

    module_dict["conv3"] = nn.Sequential(
        nn.Conv2d(
            resized_in_ch,
            out_ch,
            kernel_size=(3, 3),
            stride=(1, 1),
            padding=0,
            bias=True,
        ),
        nn.Tanh(),
        nn.BatchNorm2d(out_ch),
    )
    module_dict["conv4"] = nn.Sequential(
        nn.Conv2d(
            out_ch,
            out_ch,
            kernel_size=(3, 3),
            stride=(1, 1),
            padding=0,
            bias=True,
        ),
        nn.Tanh(),
    )
    return nn.ModuleDict(module_dict)


def group2_arch_branch(in_ch, out_ch):
    """Group2 branch for MicroNet.

    Args:
        in_ch (int): Number of input channels.
        out_ch (int): Number of output channels.

    Returns:
        torch.nn.ModuleDict: An output of type :class:`torch.nn.ModuleDict`

    """
    module_dict = OrderedDict()
    module_dict["conv1"] = nn.Sequential(
        nn.Conv2d(
            in_ch,
            out_ch,
            kernel_size=(3, 3),
            stride=(1, 1),
            padding=0,
            bias=True,
        ),
        nn.Tanh(),
    )
    module_dict["conv2"] = nn.Sequential(
        nn.Conv2d(
            out_ch,
            out_ch,
            kernel_size=(3, 3),
            stride=(1, 1),
            padding=0,
            bias=True,
        ),
        nn.Tanh(),
    )
    return nn.ModuleDict(module_dict)


def group3_arch_branch(in_ch, skip, out_ch):
    """Group3 branch for MicroNet.

    Args:
        in_ch (int): Number of input channels.
        skip (int): Number of channels for the skip connection.
        out_ch (int): Number of output channels.

    Returns:
        torch.nn.ModuleDict: An output of type :class:`torch.nn.ModuleDict`

    """
    module_dict = OrderedDict()
    module_dict["up1"] = nn.ConvTranspose2d(
        in_ch, out_ch, kernel_size=(2, 2), stride=(2, 2)
    )
    module_dict["conv1"] = nn.Sequential(
        nn.Conv2d(
            out_ch,
            out_ch,
            kernel_size=(3, 3),
            stride=(1, 1),
            padding=0,
            bias=True,
        ),
        nn.Tanh(),
    )
    module_dict["conv2"] = nn.Sequential(
        nn.Conv2d(
            out_ch,
            out_ch,
            kernel_size=(3, 3),
            stride=(1, 1),
            padding=0,
            bias=True,
        ),
        nn.Tanh(),
    )
    module_dict["up2"] = nn.ConvTranspose2d(
        out_ch, out_ch, kernel_size=(5, 5), stride=(1, 1)
    )

    module_dict["up3"] = nn.ConvTranspose2d(
        skip, out_ch, kernel_size=(5, 5), stride=(1, 1)
    )

    module_dict["conv3"] = nn.Sequential(
        nn.Conv2d(
            2 * out_ch,
            out_ch,
            kernel_size=(1, 1),
            stride=(1, 1),
            padding=0,
            bias=True,
        ),
        nn.Tanh(),
    )
    return nn.ModuleDict(module_dict)


def group4_arch_branch(in_ch, out_ch, up_kernel=(2, 2), up_strides=(2, 2)):
    """Group4 branch for MicroNet.

    Args:
        in_ch (int): Number of input channels.
        out_ch (int): Number of output channels.
        up_kernel (tuple of int): Kernel size for
            :class:`torch.nn.ConvTranspose2d`.
        up_strides (tuple of int): Stride size for
            :class:`torch.nn.ConvTranspose2d`.

    Returns:
        torch.nn.ModuleDict: An output of type :class:`torch.nn.ModuleDict`

    """
    module_dict = OrderedDict()
    module_dict["up1"] = nn.ConvTranspose2d(
        in_ch, out_ch, kernel_size=up_kernel, stride=up_strides
    )
    module_dict["conv1"] = nn.Sequential(
        nn.Conv2d(
            out_ch,
            out_ch,
            kernel_size=(3, 3),
            stride=(1, 1),
            padding=0,
            bias=True,
        ),
        nn.Tanh(),
    )
    return nn.ModuleDict(module_dict)


def out_arch_branch(in_ch, num_class=2):
    """Group5 branch for MicroNet.

    Args:
        in_ch (int): Number of input channels.
        num_class (int): Number of output channels. default=2.

    Returns:
        torch.nn.Sequential: An output of type :class:`torch.nn.Sequential`

    """
    return nn.Sequential(
        nn.Dropout2d(p=0.5),
        nn.Conv2d(
            in_ch,
            num_class,
            kernel_size=(3, 3),
            stride=(1, 1),
            padding=0,
            bias=True,
        ),
        nn.Softmax(),
    )


class MicroNet(ModelABC):
    """Initialise MicroNet [1].
    The following models have been included in tiatoolbox.
    1. `micronet-consep`: This is trained on
    `ConSep dataset <https://warwick.ac.uk/fac/cross_fac/tia/data/hovernet/>`_
    The model is retrained in torch as the original model with results on ConSep [2]
    was trained in TensorFlow.

    The tiatoolbox model should produce following results on the ConSep dataset.

    .. list-table:: MicroNet Performance
       :widths: 15 15 15 15 15 15 15 15
       :header-rows: 1

       * - Model name
         - Data set
         - DICE
         - AJI
         - DQ
         - SQ
         - PQ
         - AJI+
       * - micronet_hovernet-consep
         - ConSep
         - 0.80
         - 0.49
         - 0.62
         - 0.75
         - 0.47
         - 0.54

    Args:
        num_input_channels (int): Number of channels in input. default=3.
        num_class (int): Number of output channels. default=2.

    References:
        [1] Raza, Shan E Ahmed, et al. "Micro-Net: A unified model for
        segmentation of various objects in microscopy images."
        Medical image analysis 52 (2019): 160-173.

        [2] Graham, Simon, et al. "Hover-net: Simultaneous segmentation
        and classification of nuclei in multi-tissue histology images."
        Medical Image Analysis 58 (2019): 101563.

    """

    def __init__(self, num_input_channels=3, num_class=2):
        super().__init__()
        if num_class < 2:
            raise ValueError("Number of classes should be >=2.")
        self.__num_class = num_class
        self.in_ch = num_input_channels

        module_dict = OrderedDict()
        module_dict["b1"] = group1_arch_branch(
            num_input_channels, num_input_channels, 64
        )
        module_dict["b2"] = group1_arch_branch(128, num_input_channels, 128)
        module_dict["b3"] = group1_arch_branch(256, num_input_channels, 256)
        module_dict["b4"] = group1_arch_branch(512, num_input_channels, 512)

        module_dict["b5"] = group2_arch_branch(1024, 2048)

        module_dict["b6"] = group3_arch_branch(2048, 1024, 1024)
        module_dict["b7"] = group3_arch_branch(1024, 512, 512)
        module_dict["b8"] = group3_arch_branch(512, 256, 256)
        module_dict["b9"] = group3_arch_branch(256, 128, 128)

        module_dict["fm1"] = group4_arch_branch(128, 64, (2, 2), (2, 2))
        module_dict["fm2"] = group4_arch_branch(256, 128, (4, 4), (4, 4))
        module_dict["fm3"] = group4_arch_branch(512, 256, (8, 8), (8, 8))

        module_dict["aux_out1"] = out_arch_branch(64, num_class=self.__num_class)
        module_dict["aux_out2"] = out_arch_branch(128, num_class=self.__num_class)
        module_dict["aux_out3"] = out_arch_branch(256, num_class=self.__num_class)

        module_dict["out"] = out_arch_branch(64 + 128 + 256, num_class=self.__num_class)

        self.layer = nn.ModuleDict(module_dict)

    def forward(self, input_tensor: torch.Tensor):  # skipcq: PYL-W0221
        """Logic for using layers defined in init.

        This method defines how layers are used in forward operation.

        Args:
            input_tensor (torch.Tensor): Input images, the tensor is
                in the shape of NCHW.

        Returns:
            list: A list of main and auxiliary outputs.
                The expected format is [main_output, aux1, aux2, aux3].

        """
        b1 = group1_forward_branch(
            self.layer["b1"],
            input_tensor,
            functional.interpolate(input_tensor, size=(128, 128), mode="bicubic"),
        )
        b2 = group1_forward_branch(
            self.layer["b2"],
            b1,
            functional.interpolate(input_tensor, size=(64, 64), mode="bicubic"),
        )
        b3 = group1_forward_branch(
            self.layer["b3"],
            b2,
            functional.interpolate(input_tensor, size=(32, 32), mode="bicubic"),
        )
        b4 = group1_forward_branch(
            self.layer["b4"],
            b3,
            functional.interpolate(input_tensor, size=(16, 16), mode="bicubic"),
        )
        b5 = group2_forward_branch(self.layer["b5"], b4)
        b6 = group3_forward_branch(self.layer["b6"], b5, b4)
        b7 = group3_forward_branch(self.layer["b7"], b6, b3)
        b8 = group3_forward_branch(self.layer["b8"], b7, b2)
        b9 = group3_forward_branch(self.layer["b9"], b8, b1)
        fm1 = group4_forward_branch(self.layer["fm1"], b9)
        fm2 = group4_forward_branch(self.layer["fm2"], b8)
        fm3 = group4_forward_branch(self.layer["fm3"], b7)

        aux1 = self.layer["aux_out1"](fm1)
        aux2 = self.layer["aux_out2"](fm2)
        aux3 = self.layer["aux_out3"](fm3)

        out = torch.cat(tensors=(fm1, fm2, fm3), dim=1)
        out = self.layer["out"](out)

        return [out, aux1, aux2, aux3]

    @staticmethod
    def postproc(image: np.ndarray):
        """Post-processing script for MicroNet.

        Args:
            image (ndarray): input image of type numpy array.

        Returns:
            ndarray: pixel-wise nuclear instance segmentation
                prediction.

        """
        pred_bin = np.argmax(image[0], axis=2)
        pred_inst = ndimage.measurements.label(pred_bin)[0]
        pred_inst = morphology.remove_small_objects(pred_inst, min_size=50)
        canvas = np.zeros(pred_inst.shape[:2], dtype=np.int32)
        for inst_id in range(1, np.max(pred_inst) + 1):
            inst_map = np.array(pred_inst == inst_id, dtype=np.uint8)
            inst_map = ndimage.binary_fill_holes(inst_map)
            canvas[inst_map > 0] = inst_id
        nuc_inst_info_dict = HoVerNet.get_instance_info(canvas)
        return canvas, nuc_inst_info_dict

    @staticmethod
    def preproc(image: np.ndarray):
        """Preprocessing function for MicroNet.

        Performs per image standardization.

        Args:
            image (ndarray): input image of type numpy array.

        Returns:
            :class:`numpy.ndarray`: Pre-processed numpy array.

        """
        image = np.transpose(image, axes=(2, 0, 1))
        image = image / 255.0
        image = torch.from_numpy(image)

        image_mean = torch.mean(image, dim=(-1, -2, -3))
        stddev = torch.std(image, dim=(-1, -2, -3))
        num_pixels = torch.tensor(torch.numel(image), dtype=torch.float32)
        min_stddev = torch.rsqrt(num_pixels)
        adjusted_stddev = torch.max(stddev, min_stddev)

        image -= image_mean
        image = torch.div(image, adjusted_stddev)

        return np.transpose(image.numpy(), axes=(1, 2, 0))

    @staticmethod
    def infer_batch(model, batch_data, on_gpu):
        """Run inference on an input batch.

        This contains logic for forward operation as well as batch i/o
        aggregation.

        Args:
            model (nn.Module): PyTorch defined model.
            batch_data (ndarray): a batch of data generated by
                torch.utils.data.DataLoader.
            on_gpu (bool): Whether to run inference on a GPU.

        Returns:
            List of output from each head, each head is expected to contain
            N predictions for N input patches. There are two cases, one
            with 2 heads (Nuclei Pixels `np` and Hover `hv`) or with 2 heads
            (`np`, `hv`, and Nuclei Types `tp`).

        """
        patch_imgs = batch_data

        device = misc.select_device(on_gpu)
        patch_imgs_gpu = patch_imgs.to(device).type(torch.float32)  # to NCHW
        patch_imgs_gpu = patch_imgs_gpu.permute(0, 3, 1, 2).contiguous()

        model.eval()  # infer mode

        # --------------------------------------------------------------
        with torch.inference_mode():
            pred, _, _, _ = model(patch_imgs_gpu)

        pred = pred.permute(0, 2, 3, 1).contiguous()
        pred = pred.cpu().numpy()

        return [
            pred,
        ]
