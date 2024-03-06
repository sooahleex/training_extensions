# Copyright (C) 2024 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""OTX semantic segmentation perfomance benchmark tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from .benchmark import Benchmark
from .conftest import PerfTestBase


class TestPerfSemanticSegmentation(PerfTestBase):
    """Benchmark semantic segmentation."""

    MODEL_TEST_CASES = [  # noqa: RUF012
        Benchmark.Model(task="semantic_segmentation", name="litehrnet_18", category="balance"),
        Benchmark.Model(task="semantic_segmentation", name="litehrnet_s", category="speed"),
        Benchmark.Model(task="semantic_segmentation", name="litehrnet_x", category="accuracy"),
        Benchmark.Model(task="semantic_segmentation", name="segnext_b", category="other"),
        Benchmark.Model(task="semantic_segmentation", name="segnext_s", category="other"),
        Benchmark.Model(task="semantic_segmentation", name="segnext_t", category="other"),
        Benchmark.Model(task="semantic_segmentation", name="dino_v2", category="other"),
    ]

    DATASET_TEST_CASES = [
        Benchmark.Dataset(
            name=f"kvasir_small_{idx}",
            path=Path("semantic_seg/kvasir_small") / f"{idx}",
            size="small",
            data_format="common_semantic_segmentation_with_subset_dirs",
            num_classes=2,
            num_repeat=3,
            extra_overrides={},
        )
        for idx in (1, 2, 3)
    ] + [
        Benchmark.Dataset(
            name="kvasir_medium",
            path=Path("semantic_seg/kvasir_medium"),
            size="medium",
            data_format="common_semantic_segmentation_with_subset_dirs",
            num_classes=2,
            num_repeat=3,
            extra_overrides={},
        ),
        Benchmark.Dataset(
            name="kvasir_large",
            path=Path("semantic_seg/kvasir_large"),
            size="large",
            data_format="common_semantic_segmentation_with_subset_dirs",
            num_classes=2,
            num_repeat=1,
            extra_overrides={},
        ),
    ]

    BENCHMARK_TEST_CASES = [  # noqa: RUF012
        {
            "type": "accuracy",
            "criteria": [
                Benchmark.Criterion(name="epoch", summary="max", compare="<", margin=0.1),
                Benchmark.Criterion(name="val/Dice", summary="max", compare=">", margin=0.1),
                Benchmark.Criterion(name="test/Dice", summary="max", compare=">", margin=0.1),
                Benchmark.Criterion(name="export/Dice", summary="max", compare=">", margin=0.1),
                Benchmark.Criterion(name="optimize/Dice", summary="max", compare=">", margin=0.1),
            ],
        },
        {
            "type": "efficiency",
            "criteria": [
                Benchmark.Criterion(name="train/iter_time", summary="mean", compare="<", margin=0.1),
                Benchmark.Criterion(name="test/iter_time", summary="mean", compare="<", margin=0.1),
                Benchmark.Criterion(name="export/iter_time", summary="mean", compare="<", margin=0.1),
                Benchmark.Criterion(name="optimize/iter_time", summary="mean", compare="<", margin=0.1),
            ],
        },
    ]

    @pytest.mark.parametrize(
        "fxt_model",
        MODEL_TEST_CASES,
        ids=lambda model: model.name,
        indirect=True,
    )
    @pytest.mark.parametrize(
        "fxt_dataset",
        DATASET_TEST_CASES,
        ids=lambda dataset: dataset.name,
        indirect=True,
    )
    @pytest.mark.parametrize(
        "fxt_benchmark",
        BENCHMARK_TEST_CASES,
        ids=lambda benchmark: benchmark["type"],
        indirect=True,
    )
    def test_perf(
        self,
        fxt_model: Benchmark.Model,
        fxt_dataset: Benchmark.Dataset,
        fxt_benchmark: Benchmark,
    ):
        self._test_perf(
            model=fxt_model,
            dataset=fxt_dataset,
            benchmark=fxt_benchmark,
        )