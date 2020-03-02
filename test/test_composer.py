import os
import random

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score as roc_auc

from core.composer.composer import DummyChainTypeEnum
from core.composer.composer import DummyComposer
from core.composer.node import PrimaryNode, SecondaryNode
from core.composer.random_composer import RandomSearchComposer
from core.models.data import InputData
from core.models.model import LogRegression
from core.models.model import XGBoost, KNN
from core.repository.dataset_types import NumericalDataTypesEnum, CategoricalDataTypesEnum
from core.repository.model_types_repository import (
    ModelMetaInfoTemplate,
    ModelTypesRepository
)
from core.repository.quality_metrics_repository import MetricsRepository, ClassificationMetricsEnum
from core.repository.task_types import MachineLearningTasksEnum


@pytest.fixture()
def file_data_setup():
    test_file_path = str(os.path.dirname(__file__))
    file = 'data/test_dataset.csv'
    input_data = InputData.from_csv(
        os.path.join(test_file_path, file))
    input_data.idx = _to_numerical(categorical_ids=input_data.idx)
    return input_data


def _to_numerical(categorical_ids: np.ndarray):
    encoded = pd.factorize(categorical_ids)[0]
    return encoded


def test_composer_hierarchical_chain():
    composer = DummyComposer(DummyChainTypeEnum.hierarchical)
    empty_data = InputData(np.zeros(1), np.zeros(1), np.zeros(1))
    new_chain = composer.compose_chain(data=empty_data,
                                       initial_chain=None,
                                       primary_requirements=[LogRegression(), XGBoost()],
                                       secondary_requirements=[LogRegression()],
                                       metrics=None)

    assert len(new_chain.nodes) == 3
    assert isinstance(new_chain.nodes[0], PrimaryNode)
    assert isinstance(new_chain.nodes[1], PrimaryNode)
    assert isinstance(new_chain.nodes[2], SecondaryNode)
    assert new_chain.nodes[2].nodes_from[0] is new_chain.nodes[0]
    assert new_chain.nodes[2].nodes_from[1] is new_chain.nodes[1]
    assert new_chain.nodes[1].nodes_from is None


def test_composer_flat_chain():
    composer = DummyComposer(DummyChainTypeEnum.flat)
    empty_data = InputData(np.zeros(1), np.zeros(1), np.zeros(1))
    new_chain = composer.compose_chain(data=empty_data,
                                       initial_chain=None,
                                       primary_requirements=[LogRegression()],
                                       secondary_requirements=[LogRegression(), XGBoost()],
                                       metrics=None)

    assert len(new_chain.nodes) == 3
    assert isinstance(new_chain.nodes[0], PrimaryNode)
    assert isinstance(new_chain.nodes[1], SecondaryNode)
    assert isinstance(new_chain.nodes[2], SecondaryNode)
    assert new_chain.nodes[1].nodes_from[0] is new_chain.nodes[0]
    assert new_chain.nodes[2].nodes_from[0] is new_chain.nodes[1]
    assert new_chain.nodes[0].nodes_from is None


@pytest.mark.parametrize('data_fixture', ['file_data_setup'])
def test_random_composer(data_fixture, request):
    random.seed(1)
    np.random.seed(1)
    data = request.getfixturevalue(data_fixture)
    dataset_to_compose = data
    dataset_to_validate = data

    models_repo = ModelTypesRepository()
    available_model_names = models_repo.search_model_types_by_attributes(
        desired_metainfo=ModelMetaInfoTemplate(input_type=NumericalDataTypesEnum.table,
                                               output_type=CategoricalDataTypesEnum.vector,
                                               task_type=MachineLearningTasksEnum.classification,
                                               can_be_initial=True,
                                               can_be_secondary=True))

    models_impl = [models_repo.model_by_id(model_name) for model_name in available_model_names]

    # exclude KNN because number of samples is too small
    models_impl = [model_id for model_id in models_impl if not isinstance(model_id, KNN)]

    metric_function = MetricsRepository().metric_by_id(ClassificationMetricsEnum.ROCAUC)

    random_composer = RandomSearchComposer(iter_num=1)
    chain_random_composed = random_composer.compose_chain(data=dataset_to_compose,
                                                          initial_chain=None,
                                                          primary_requirements=models_impl,
                                                          secondary_requirements=models_impl,
                                                          metrics=metric_function)

    predicted_random_composed = chain_random_composed.predict(dataset_to_validate)

    roc_on_valid_random_composed = roc_auc(y_true=dataset_to_validate.target,
                                           y_score=predicted_random_composed.predict)

    assert roc_on_valid_random_composed > 0.99