import operator
from datetime import timedelta
from typing import Callable, Tuple, Union

from imblearn.under_sampling import RandomUnderSampler
from numpy.random import choice as nprand_choice, randint
from sklearn.metrics import make_scorer, mean_squared_error, mean_squared_error as mse, roc_auc_score
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV
from skopt import BayesSearchCV

from core.composer.timer import TunerTimer
from core.models.data import InputData, train_test_data_setup
from core.models.tuning.hyperparams import flo_params_range_by_model, params_range_by_model
from core.models.tuning.tuner_adapter import FLOAdapter, HyperoptAdapter
from core.repository.tasks import TaskTypesEnum

TUNER_ERROR_PREFIX = 'Unsuccessful fit because of'
import random


def get_params_range(tuner_type, model_type):
    if tuner_type == FLOTuner:
        return flo_params_range_by_model.get(model_type, None)
    else:
        return params_range_by_model.get(model_type, None)


class Tuner:
    __tuning_metric_by_type = {
        TaskTypesEnum.classification:
            make_scorer(roc_auc_score, greater_is_better=True, needs_proba=True),
        TaskTypesEnum.regression:
            make_scorer(mean_squared_error, greater_is_better=False),
    }

    def __init__(self, trained_model, tune_data: InputData,
                 params_range: dict,
                 cross_val_fold_num: int,
                 time_limit,
                 iterations: int):
        self.time_limit: timedelta \
            = time_limit
        self.trained_model = trained_model
        self.tune_data = tune_data
        self.params_range = params_range
        self.cross_val_fold_num = cross_val_fold_num
        self.scorer = self.__tuning_metric_by_type.get(self.tune_data.task.task_type, None)
        self.max_iterations = iterations
        self.default_score, self.default_params = \
            self.get_cross_val_score_and_params(self.trained_model)

    def tune(self) -> Union[Tuple[dict, object], Tuple[None, None]]:
        raise NotImplementedError()

    def is_score_better(self, previous, current):
        __compare = {
            TaskTypesEnum.classification: operator.gt,
            TaskTypesEnum.regression: operator.lt
        }
        comparison = __compare.get(self.tune_data.task.task_type)
        try:
            return comparison(current, previous)
        except ValueError as ex:
            print(f'Score comparison can not be held because {ex}')

    def is_better_than_default(self, score):
        return self.is_score_better(self.default_score, score)

    def get_cross_val_score_and_params(self, model):
        balanced_features, balanced_target = RandomUnderSampler(sampling_strategy=0.5). \
            fit_resample(self.tune_data.features, self.tune_data.target)

        c = list(zip(balanced_features, balanced_target))

        random.shuffle(c)

        balanced_features, balanced_target = zip(*c)

        # balanced_features = np.asarray(balanced_features)
        # balanced_target = np.asarray(balanced_target)

        from sklearn.metrics import roc_auc_score as roc_auc

        from core.models.data import InputData

        from benchmark.benchmark_utils import get_scoring_case_data_paths

        train_file_path, test_file_path = get_scoring_case_data_paths()

        train_data = InputData.from_csv(train_file_path)
        test_data = InputData.from_csv(test_file_path)
        # scaler = Scaling().fit(train_data.features)
        # features = scaler.apply(train_data.features)

        from core.composer.chain import Chain
        from core.composer.node import PrimaryNode, SecondaryNode

        def get_simple_chain():
            first = PrimaryNode(model_type='knn')
            second = PrimaryNode(model_type='knn')
            final = SecondaryNode(model_type='knn',
                                  nodes_from=[first, second])

            chain = Chain(final)

            return chain

        chain = get_simple_chain()
        params = model.get_params()

        for node in [_ for _ in chain.nodes if isinstance(_, PrimaryNode)]:
            if str(node.model) == str(model):
                node.model.params = params

        chain.fit(train_data)

        after_tuning_predicted = chain.predict(test_data).predict

        # Metrics
        score = roc_auc(y_true=test_data.target,
                        y_score=after_tuning_predicted)

        # score = abs(cross_val_score(model, balanced_features,
        #                            balanced_target, scoring=self.scorer,
        #                            cv=2, n_jobs=-1).mean())

        # params = model.get_params()

        return score, params

    def get_cross_val_score_and_params2(self, model):
        balanced_features, balanced_target = RandomUnderSampler(sampling_strategy=0.5). \
            fit_resample(self.tune_data.features, self.tune_data.target)

        c = list(zip(balanced_features, balanced_target))

        random.shuffle(c)

        balanced_features, balanced_target = zip(*c)

        # balanced_features = np.asarray(balanced_features)
        # balanced_target = np.asarray(balanced_target)
        from core.models.preprocessing import Scaling

        from sklearn.metrics import roc_auc_score as roc_auc

        from core.models.data import InputData

        from benchmark.benchmark_utils import get_scoring_case_data_paths

        train_file_path, test_file_path = get_scoring_case_data_paths()

        train_data = InputData.from_csv(train_file_path)
        test_data = InputData.from_csv(test_file_path)
        scaler = Scaling().fit(train_data.features)
        features = scaler.apply(train_data.features)

        model.fit(features, train_data.target)
        features = scaler.apply(test_data.features)

        after_tuning_predicted = model.predict_proba(features)

        # Metrics
        score = roc_auc(y_true=test_data.target,
                        y_score=after_tuning_predicted[:, 1])

        # score = abs(cross_val_score(model, balanced_features,
        #                            balanced_target, scoring=self.scorer,
        #                            cv=2, n_jobs=-1).mean())

        params = model.get_params()

        return score, params


class SklearnTuner(Tuner):
    def __init__(self, trained_model, tune_data: InputData,
                 params_range: dict,
                 cross_val_fold_num: int,
                 time_limit, iterations):
        super().__init__(trained_model=trained_model,
                         tune_data=tune_data,
                         params_range=params_range,
                         cross_val_fold_num=cross_val_fold_num,
                         time_limit=time_limit,
                         iterations=iterations)
        self.search_strategy = None

    def tune(self) -> Union[Tuple[dict, object], Tuple[None, None]]:
        raise NotImplementedError()

    def _sklearn_tune(self, tune_data: InputData):
        try:
            search = self.search_strategy.fit(tune_data.features, tune_data.target.ravel())
            new_score, _ = self.get_cross_val_score_and_params(search.best_estimator_)
            if self.is_better_than_default(new_score):
                return search.best_params_, search.best_estimator_
            else:
                return self.default_params, self.trained_model
        except ValueError as ex:
            print(f'{TUNER_ERROR_PREFIX} {ex}')
            return None, None


class SklearnRandomTuner(SklearnTuner):
    def tune(self) -> Union[Tuple[dict, object], Tuple[None, None]]:
        self.search_strategy = RandomizedSearchCV(estimator=self.trained_model,
                                                  param_distributions=self.params_range,
                                                  n_iter=self.max_iterations,
                                                  cv=self.cross_val_fold_num,
                                                  scoring=self.scorer)
        return self._sklearn_tune(tune_data=self.tune_data)


class SklearnGridSearchTuner(SklearnTuner):
    def tune(self) -> Union[Tuple[dict, object], Tuple[None, None]]:
        self.search_strategy = GridSearchCV(estimator=self.trained_model,
                                            param_grid=self.params_range,
                                            cv=self.cross_val_fold_num,
                                            scoring=self.scorer)
        return self._sklearn_tune(self.tune_data)


class SklearnBayesSearchCV(SklearnTuner):
    def tune(self) -> Union[Tuple[dict, object], Tuple[None, None]]:
        self.search_strategy = BayesSearchCV(estimator=self.trained_model,
                                             search_spaces=self.params_range,
                                             n_iter=self.max_iterations,
                                             cv=self.cross_val_fold_num,
                                             scoring=self.scorer)
        return self._sklearn_tune(self.tune_data)


class SklearnCustomRandomTuner(Tuner):
    def tune(self) -> Union[Tuple[dict, object], Tuple[None, None]]:
        try:
            with TunerTimer() as timer:
                best_model = self.trained_model
                best_score, best_params = self.get_cross_val_score_and_params(best_model)
                for iteration in range(self.max_iterations):
                    params = {k: nprand_choice(v) for k, v in self.params_range.items()}
                    self.trained_model.set_params(**params)
                    score, _ = self.get_cross_val_score_and_params(self.trained_model)
                    if self.is_score_better(previous=best_score, current=score):
                        best_params = params
                        best_model = self.trained_model
                        best_score = score

                    if timer.is_time_limit_reached(self.time_limit):
                        break
                return best_params, best_model
        except ValueError as ex:
            print(f'{TUNER_ERROR_PREFIX} {ex}')
            return None, None


class ForecastingCustomRandomTuner:
    # TODO discuss
    def tune(self,
             fit: Callable,
             predict: Callable,
             tune_data: InputData, params_range: dict,
             default_params: dict, iterations: int) -> dict:

        tune_train_data, tune_test_data = train_test_data_setup(tune_data, 0.5)

        trained_model_default = fit(tune_test_data, default_params)
        prediction_default = predict(trained_model_default, tune_test_data)
        best_quality_metric = _regression_prediction_quality(prediction=prediction_default,
                                                             real=tune_test_data.target)
        best_params = default_params

        for _ in range(iterations):
            random_params = get_random_params(params_range)
            try:
                trained_model_candidate = fit(tune_train_data, random_params)
                prediction_candidate = predict(trained_model_candidate,
                                               tune_test_data)
                quality_metric = _regression_prediction_quality(prediction=prediction_candidate,
                                                                real=tune_test_data.target)
                if quality_metric < best_quality_metric:
                    best_params = random_params
            except ValueError:
                pass
        return best_params


def get_random_params(params_range):
    candidate_params = {}
    for param in params_range:
        param_range = params_range[param]
        param_range_left, param_range_right = param_range[0], param_range[1]
        if isinstance(param_range_left, tuple):
            # set-based params with constant length
            candidate_param = get_constant_length_range(param_range_left, param_range_right)
        elif isinstance(param_range_left, list):
            # set-based params with varied length
            candidate_param = get_varied_length_range(param_range_left, param_range_right)
        else:
            raise ValueError(f'Un-supported params range type {type(param_range_left)}')
        candidate_params[param] = candidate_param
    return candidate_params


def get_constant_length_range(left_range, right_range):
    candidate_param = []
    for sub_param_ind in range(len(left_range)):
        new_sub_param = randint(left_range[sub_param_ind],
                                right_range[sub_param_ind] + 1)
        candidate_param.append(new_sub_param)
    return tuple(candidate_param)


def get_varied_length_range(left_range, right_range):
    candidate_param = []
    subparams_num = randint(1, len(right_range))
    for sub_param_ind in range(subparams_num):
        new_sub_param = randint(left_range[sub_param_ind],
                                right_range[sub_param_ind] + 1)
        candidate_param.append(new_sub_param)
    return candidate_param


def _regression_prediction_quality(prediction, real):
    return mse(y_true=real, y_pred=prediction, squared=False)


class TPETuner(Tuner):
    def tune(self) -> Union[Tuple[dict, object], Tuple[None, None]]:
        try:
            adapter = HyperoptAdapter(self)
            best_params, best_model = adapter.tune(iterations=self.max_iterations,
                                                   timeout_sec=self.time_limit.seconds)
            new_score, _ = self.get_cross_val_score_and_params(best_model)

            if self.is_better_than_default(new_score):
                return best_params, best_model
            else:
                return self.default_params, self.trained_model
        except ValueError as ex:
            print(f'{TUNER_ERROR_PREFIX} {ex}')
            return None, None


class FLOTuner(Tuner):
    def tune(self):
        try:
            adapter = FLOAdapter(self)
            best_params, best_model = adapter.tune()

            new_score, _ = self.get_cross_val_score_and_params(best_model)

            if self.is_better_than_default(new_score):
                return best_params, best_model
            else:
                return self.default_params, self.trained_model

            # return best_params, best_model
        except ValueError as ex:
            print(f'{TUNER_ERROR_PREFIX} {ex}')
            return None, None
