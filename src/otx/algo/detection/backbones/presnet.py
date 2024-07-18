from __future__ import annotations
from collections import OrderedDict

import torch
import torch.nn.functional as F
from torch import nn
from typing import Any, Dict, List

from otx.algo.modules import ConvModule, build_activation_layer

__all__ = ["PResNet"]


ResNet_cfg = {
    18: [2, 2, 2, 2],
    34: [3, 4, 6, 3],
    50: [3, 4, 6, 3],
    101: [3, 4, 23, 3],
}


donwload_url = {
    18: "https://github.com/lyuwenyu/storage/releases/download/v0.1/ResNet18_vd_pretrained_from_paddle.pth",
    34: "https://github.com/lyuwenyu/storage/releases/download/v0.1/ResNet34_vd_pretrained_from_paddle.pth",
    50: "https://github.com/lyuwenyu/storage/releases/download/v0.1/ResNet50_vd_ssld_v2_pretrained_from_paddle.pth",
    101: "https://github.com/lyuwenyu/storage/releases/download/v0.1/ResNet101_vd_ssld_pretrained_from_paddle.pth",
}


class ConvNormLayer(nn.Module):
    def __init__(self, ch_in, ch_out, kernel_size, stride, padding=None, bias=False, act=None) -> None:
        super().__init__()
        self.conv = nn.Conv2d(
            ch_in,
            ch_out,
            kernel_size,
            stride,
            padding=(kernel_size - 1) // 2 if padding is None else padding,
            bias=bias,
        )
        self.norm = nn.BatchNorm2d(ch_out)
        self.act = nn.Identity() if act is None else build_activation_layer(act)

    def forward(self, x):
        """forward"""
        return self.act(self.norm(self.conv(x)))


class FrozenBatchNorm2d(nn.Module):
    """copy and modified from https://github.com/facebookresearch/detr/blob/master/models/backbone.py
    BatchNorm2d where the batch statistics and the affine parameters are fixed.
    Copy-paste from torchvision.misc.ops with added eps before rqsrt,
    without which any other models than torchvision.models.resnet[18,34,50,101]
    produce nans.
    """

    def __init__(self, num_features: int, eps: float=1e-5) -> None:
        super(FrozenBatchNorm2d, self).__init__()
        n = num_features
        self.register_buffer("weight", torch.ones(n))
        self.register_buffer("bias", torch.zeros(n))
        self.register_buffer("running_mean", torch.zeros(n))
        self.register_buffer("running_var", torch.ones(n))
        self.eps = eps
        self.num_features = n

    def _load_from_state_dict(
        self, state_dict: Dict[str, torch.Tensor], prefix: str, local_metadata: Any,
        strict: bool, missing_keys: List[str], unexpected_keys: List[str], error_msgs: List[str]
    ) -> None:

        num_batches_tracked_key = prefix + "num_batches_tracked"
        if num_batches_tracked_key in state_dict:
            del state_dict[num_batches_tracked_key]

        super(FrozenBatchNorm2d, self)._load_from_state_dict(
            state_dict, prefix, local_metadata, strict, missing_keys, unexpected_keys, error_msgs
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """forward"""
        # move reshapes to the beginning
        # to make it fuser-friendly
        w = self.weight.reshape(1, -1, 1, 1)
        b = self.bias.reshape(1, -1, 1, 1)
        rv = self.running_var.reshape(1, -1, 1, 1)
        rm = self.running_mean.reshape(1, -1, 1, 1)
        scale = w * (rv + self.eps).rsqrt()
        bias = b - rm * scale
        return x * scale + bias

    def extra_repr(self):
        """str representation"""
        return "{num_features}, eps={eps}".format(**self.__dict__)


class BasicBlock(nn.Module):
    expansion = 1

    def __init__(self, ch_in: int, ch_out: int, stride: int, shortcut: bool, act_cfg: Dict[str, str] | None = None, variant: str="b", norm_cfg: Dict[str, str] | None = None) -> None:
        super().__init__()

        self.shortcut = shortcut

        if not shortcut:
            if variant == "d" and stride == 2:
                self.short = nn.Sequential(
                    OrderedDict(
                        [
                            ("pool", nn.AvgPool2d(2, 2, 0, ceil_mode=True)),
                            ("conv", ConvModule(ch_in, ch_out, 1, 1, act_cfg=None, norm_cfg=norm_cfg)),
                        ]
                    )
                )
            else:
                self.short = ConvModule(ch_in, ch_out, 1, stride, act_cfg=None, norm_cfg=norm_cfg)

        self.branch2a = ConvModule(ch_in, ch_out, 3, stride, padding=1, act_cfg=act_cfg, norm_cfg=norm_cfg)
        self.branch2b = ConvModule(ch_out, ch_out, 3, 1, padding=1, act_cfg=None, norm_cfg=norm_cfg)
        self.act = nn.Identity() if act_cfg is None else build_activation_layer(act_cfg)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """forward"""
        out = self.branch2a(x)
        out = self.branch2b(out)
        if self.shortcut:
            short = x
        else:
            short = self.short(x)

        out = out + short
        out = self.act(out)

        return out


class BottleNeck(nn.Module):
    expansion = 4

    def __init__(self, ch_in: int, ch_out: int, stride: int, shortcut: bool, act_cfg: Dict[str, str] | None = None, variant: str="b", norm_cfg: Dict[str, str] | None = None) -> None:
        super().__init__()

        if variant == "a":
            stride1, stride2 = stride, 1
        else:
            stride1, stride2 = 1, stride

        width = ch_out

        self.branch2a = ConvModule(ch_in, width, 1, stride1, act_cfg=act_cfg, norm_cfg=norm_cfg)
        self.branch2b = ConvModule(width, width, 3, stride2, padding=1, act_cfg=act_cfg, norm_cfg=norm_cfg)
        self.branch2c = ConvModule(width, ch_out * self.expansion, 1, 1, act_cfg=None, norm_cfg=norm_cfg)

        self.shortcut = shortcut
        if not shortcut:
            if variant == "d" and stride == 2:
                self.short = nn.Sequential(
                    OrderedDict(
                        [
                            ("pool", nn.AvgPool2d(2, 2, 0, ceil_mode=True)),
                            ("conv", ConvModule(ch_in, ch_out * self.expansion, 1, 1, act_cfg=None, norm_cfg=norm_cfg)),
                        ]
                    )
                )
            else:
                self.short = ConvModule(ch_in, ch_out * self.expansion, 1, stride, act_cfg=None, norm_cfg=norm_cfg)

        self.act = nn.Identity() if act_cfg is None else build_activation_layer(act_cfg)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """forward"""
        out = self.branch2a(x)
        out = self.branch2b(out)
        out = self.branch2c(out)

        if self.shortcut:
            short = x
        else:
            short = self.short(x)

        out = out + short
        out = self.act(out)

        return out


class Blocks(nn.Module):
    def __init__(self, block: nn.Module, ch_in: int, ch_out: int, count: int, stage_num: int, act_cfg: Dict[str, str] | None = None, variant: str="b", norm_cfg: Dict[str, str] | None = None) -> None:
        super().__init__()

        self.blocks = nn.ModuleList()
        for i in range(count):
            self.blocks.append(
                block(
                    ch_in,
                    ch_out,
                    stride=2 if i == 0 and stage_num != 2 else 1,
                    shortcut=False if i == 0 else True,
                    variant=variant,
                    act_cfg=act_cfg,
                    norm_cfg=norm_cfg
                ),
            )

            if i == 0:
                ch_in = ch_out * block.expansion

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """forward"""
        out = x
        for block in self.blocks:
            out = block(out)
        return out


class PResNet(nn.Module):
    def __init__(
        self,
        depth: int,
        variant: str="d",
        num_stages: int=4,
        return_idx: List[int]=[0, 1, 2, 3],
        act_cfg: Dict[str, str] | None= None,
        norm_cfg: Dict[str, str] | None= None,
        freeze_at: int=-1,
        freeze_norm: bool=True,
        pretrained: bool=False,
    ) -> None:
        super().__init__()

        block_nums = ResNet_cfg[depth]
        ch_in = 64
        if variant in ["c", "d"]:
            conv_def = [
                [3, ch_in // 2, 3, 2, "conv1_1"],
                [ch_in // 2, ch_in // 2, 3, 1, "conv1_2"],
                [ch_in // 2, ch_in, 3, 1, "conv1_3"],
            ]
        else:
            conv_def = [[3, ch_in, 7, 2, "conv1_1"]]
        act_cfg = act_cfg if act_cfg is not None else {"type": "ReLU"}
        norm_cfg = norm_cfg if norm_cfg is not None else {"type": "BN", "name": "norm"}
        self.conv1 = nn.Sequential(
            OrderedDict([(_name, ConvModule(c_in, c_out, k, s, padding=(k - 1) // 2, act_cfg=act_cfg, norm_cfg=norm_cfg)) for c_in, c_out, k, s, _name in conv_def])
        )

        ch_out_list = [64, 128, 256, 512]
        block = BottleNeck if depth >= 50 else BasicBlock

        _out_channels = [block.expansion * v for v in ch_out_list]
        _out_strides = [4, 8, 16, 32]

        self.res_layers = nn.ModuleList()
        for i in range(num_stages):
            stage_num = i + 2
            self.res_layers.append(
                Blocks(block, ch_in, ch_out_list[i], block_nums[i], stage_num, act_cfg=act_cfg, variant=variant, norm_cfg=norm_cfg),
            )
            ch_in = _out_channels[i]

        self.return_idx = return_idx
        self.out_channels = [_out_channels[_i] for _i in return_idx]
        self.out_strides = [_out_strides[_i] for _i in return_idx]

        if freeze_at >= 0:
            self._freeze_parameters(self.conv1)
            for i in range(min(freeze_at, num_stages)):
                self._freeze_parameters(self.res_layers[i])

        if freeze_norm:
            self._freeze_norm(self)

        if pretrained:
            state = torch.hub.load_state_dict_from_url(donwload_url[depth])
            self.load_state_dict(state)
            print(f"Load PResNet{depth} state_dict")

    def _freeze_parameters(self, m: nn.Module) -> None:
        for p in m.parameters():
            p.requires_grad = False

    def _freeze_norm(self, m: nn.Module) -> None:
        if isinstance(m, nn.BatchNorm2d):
            m = FrozenBatchNorm2d(m.num_features)
        else:
            for name, child in m.named_children():
                _child = self._freeze_norm(child)
                if _child is not child:
                    setattr(m, name, _child)
        return m

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """forward"""
        conv1 = self.conv1(x)
        x = F.max_pool2d(conv1, kernel_size=3, stride=2, padding=1)
        outs = []
        for idx, stage in enumerate(self.res_layers):
            x = stage(x)
            if idx in self.return_idx:
                outs.append(x)
        return outs
