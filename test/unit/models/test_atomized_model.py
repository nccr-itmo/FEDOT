import json
from datetime import timedelta

import pytest
from sklearn.metrics import mean_squared_error

from test.unit.utilities.test_chain_import_export import create_func_delete_files, create_correct_path
from fedot.core.chains.chain import Chain
from fedot.core.chains.node import PrimaryNode, SecondaryNode
from fedot.core.models.atomized_model import AtomizedModel
from fedot.core.data.data import InputData
from cases.data.data_utils import get_scoring_case_data_paths


@pytest.fixture(scope='session', autouse=True)
def preprocessing_files_before_and_after_tests(request):
    paths = ['test_save_load_atomized_chain_correctly', 'test_save_load_fitted_atomized_chain_correctly_loaded',
             'test_save_load_fitted_atomized_chain_correctly']

    delete_files = create_func_delete_files(paths)

    delete_files()
    request.addfinalizer(delete_files)


def create_chain() -> Chain:
    chain = Chain()
    node_logit = PrimaryNode('logit')

    node_lda = PrimaryNode('lda')
    node_lda.custom_params = {'n_components': 1}

    node_xgboost = SecondaryNode('xgboost')
    node_xgboost.custom_params = {'n_components': 1}
    node_xgboost.nodes_from = [node_logit, node_lda]

    chain.add_node(node_xgboost)

    return chain


def create_atomized_model() -> AtomizedModel:
    """
    Example, how to create Atomized model.
    """
    chain = create_chain()
    atomized_model = AtomizedModel(chain)

    return atomized_model


def create_atomized_model_with_several_atomized_models() -> AtomizedModel:
    chain = Chain()
    node_atomized_model_primary = PrimaryNode(model_type=create_atomized_model())
    node_atomized_model_secondary = SecondaryNode(model_type=create_atomized_model())
    node_atomized_model_secondary_second = SecondaryNode(model_type=create_atomized_model())
    node_atomized_model_secondary_third = SecondaryNode(model_type=create_atomized_model())

    node_atomized_model_secondary.nodes_from = [node_atomized_model_primary]
    node_atomized_model_secondary_second.nodes_from = [node_atomized_model_primary]
    node_atomized_model_secondary_third.nodes_from = [node_atomized_model_secondary,
                                                      node_atomized_model_secondary_second]

    chain.add_node(node_atomized_model_secondary_third)
    atomized_model = AtomizedModel(chain)

    return atomized_model


def create_chain_with_several_nested_atomized_model() -> Chain:
    chain = Chain()
    node_atomized_model = PrimaryNode(model_type=create_atomized_model_with_several_atomized_models())

    node_atomized_model_secondary = SecondaryNode(model_type=create_atomized_model())
    node_atomized_model_secondary.nodes_from = [node_atomized_model]

    node_knn = SecondaryNode('knn')
    node_knn.custom_params = {'n_neighbors': 9}
    node_knn.nodes_from = [node_atomized_model]

    node_knn_second = SecondaryNode('knn')
    node_knn_second.custom_params = {'n_neighbors': 5}
    node_knn_second.nodes_from = [node_atomized_model, node_atomized_model_secondary, node_knn]

    node_atomized_model_secondary_second = \
        SecondaryNode(model_type=create_atomized_model_with_several_atomized_models())

    node_atomized_model_secondary_second.nodes_from = [node_knn_second]

    chain.add_node(node_atomized_model_secondary_second)

    return chain


def create_data_for_train():
    train_file_path, test_file_path = get_scoring_case_data_paths()
    train_data = InputData.from_csv(train_file_path)
    test_data = InputData.from_csv(test_file_path)

    return train_data, test_data


def test_save_load_atomized_chain_correctly():
    chain = create_chain_with_several_nested_atomized_model()

    json_actual = chain.save_chain('test_save_load_atomized_chain_correctly')

    json_path_load = create_correct_path('test_save_load_atomized_chain_correctly')

    with open(json_path_load, 'r') as json_file:
        json_expected = json.load(json_file)

    chain_loaded = Chain()
    chain_loaded.load_chain(json_path_load)

    assert chain.length == chain_loaded.length
    assert json_actual == json.dumps(json_expected)


def test_save_load_fitted_atomized_chain_correctly():
    chain = create_chain_with_several_nested_atomized_model()

    train_data, test_data = create_data_for_train()
    chain.fit(train_data)

    json_actual = chain.save_chain('test_save_load_fitted_atomized_chain_correctly')

    json_path_load = create_correct_path('test_save_load_fitted_atomized_chain_correctly')

    chain_loaded = Chain()
    chain_loaded.load_chain(json_path_load)
    json_expected = chain_loaded.save_chain('test_save_load_fitted_atomized_chain_correctly_loaded')

    assert chain.length == chain_loaded.length
    assert json_actual == json_expected

    before_save_predicted = chain.predict(test_data)

    chain_loaded.fit(train_data)
    after_save_predicted = chain_loaded.predict(test_data)

    bfr_tun_mse = mean_squared_error(y_true=test_data.target, y_pred=before_save_predicted.predict)
    aft_tun_mse = mean_squared_error(y_true=test_data.target, y_pred=after_save_predicted.predict)

    assert aft_tun_mse <= bfr_tun_mse


def test_fit_predict_atomized_model_correctly():
    train_data, test_data = create_data_for_train()

    chain = create_chain_with_several_nested_atomized_model()
    atomized_model = AtomizedModel(chain)

    chain.fit(train_data)
    predicted_values = chain.predict(test_data)

    atomized_model.fit(train_data)
    predicted_atomized_values = atomized_model.predict(None, test_data)

    bfr_tun_mse = mean_squared_error(y_true=test_data.target, y_pred=predicted_values.predict)
    aft_tun_mse = mean_squared_error(y_true=test_data.target, y_pred=predicted_atomized_values)

    assert aft_tun_mse == bfr_tun_mse


def test_create_empty_atomized_model_raised_exception():
    with pytest.raises(Exception):
        empty_chain = Chain()
        AtomizedModel(empty_chain)


def test_fine_tune_atomized_model_correct():
    train_data, test_data = create_data_for_train()

    fine_tuned_atomized_model = create_atomized_model()
    dummy_atomized_model = create_atomized_model()

    fine_tuned_atomized_model.fine_tune(train_data, iterations=5, max_lead_time=timedelta(minutes=0.01))
    dummy_atomized_model.fit(train_data)

    after_tuning_predicted = fine_tuned_atomized_model.predict(None, test_data)
    before_tuning_predicted = dummy_atomized_model.predict(None, test_data)

    aft_tun_mse = mean_squared_error(y_true=test_data.target, y_pred=after_tuning_predicted)
    bfr_tun_mse = mean_squared_error(y_true=test_data.target, y_pred=before_tuning_predicted)

    assert aft_tun_mse <= bfr_tun_mse
