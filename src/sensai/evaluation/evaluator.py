import logging
from abc import ABC, abstractmethod
from typing import Tuple, Dict, Any, Generator, Generic, TypeVar, Sequence, Optional, List, Union

import pandas as pd

from .eval_stats.eval_stats_base import EvalStats, EvalStatsCollection
from .eval_stats.eval_stats_classification import ClassificationEvalStats, ClassificationMetric
from .eval_stats.eval_stats_regression import RegressionEvalStats, RegressionEvalStatsCollection, RegressionMetric
from ..data_transformation import DataFrameTransformer
from ..data import DataSplitter, DataSplitterFractional, InputOutputData
from ..tracking import TrackingMixin
from ..util.string import ToStringMixin
from ..util.typing import PandasNamedTuple
from ..vector_model import VectorClassificationModel, VectorModel, VectorModelBase, VectorModelFittableBase

log = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=VectorModel)
TEvalStats = TypeVar("TEvalStats", bound=EvalStats)
TEvalStatsCollection = TypeVar("TEvalStatsCollection", bound=EvalStatsCollection)


class MetricsDictProvider(TrackingMixin, ABC):
    @abstractmethod
    def _computeMetrics(self, model, **kwargs) -> Dict[str, float]:
        """
        Computes metrics for the given model, typically by fitting the model and applying it to test data

        :param model: the model
        :param kwargs: parameters to pass on to the underlying evaluation method
        :return: a dictionary with metrics values
        """
        pass

    def computeMetrics(self, model, **kwargs) -> Optional[Dict[str, float]]:
        """
        Computes metrics for the given model, typically by fitting the model and applying it to test data.
        If a tracked experiment was previously set, the metrics are tracked with the string representation
        of the model added under an additional key 'str(model)'.

        :param model: the model for which to compute metrics
        :param kwargs: parameters to pass on to the underlying evaluation method
        :return: a dictionary with metrics values
        """
        valuesDict = self._computeMetrics(model, **kwargs)
        if self.trackedExperiment is not None:
            trackedDict = valuesDict.copy()
            trackedDict["str(model)"] = str(model)
            self.trackedExperiment.trackValues(trackedDict)
        return valuesDict


class VectorModelEvaluationData(ABC, Generic[TEvalStats]):
    def __init__(self, statsDict: Dict[str, TEvalStats], inputData: pd.DataFrame, model: VectorModelBase):
        """
        :param statsDict: a dictionary mapping from output variable name to the evaluation statistics object
        :param inputData: the input data that was used to produce the results
        :param model: the model that was used to produce predictions
        """
        self.inputData = inputData
        self.evalStatsByVarName = statsDict
        self.predictedVarNames = list(self.evalStatsByVarName.keys())
        self.model = model

    @property
    def modelName(self):
        return self.model.getName()

    def getEvalStats(self, predictedVarName=None) -> TEvalStats:
        if predictedVarName is None:
            if len(self.evalStatsByVarName) != 1:
                raise Exception(f"Must provide name of predicted variable name, as multiple variables were predicted {list(self.evalStatsByVarName.keys())}")
            else:
                predictedVarName = next(iter(self.evalStatsByVarName.keys()))
        evalStats = self.evalStatsByVarName.get(predictedVarName)
        if evalStats is None:
            raise ValueError(f"No evaluation data present for '{predictedVarName}'; known output variables: {list(self.evalStatsByVarName.keys())}")
        return evalStats

    def getDataFrame(self):
        """
        Returns an DataFrame with all evaluation metrics (one row per output variable)

        :return: a DataFrame containing evaluation metrics
        """
        statsDicts = []
        varNames = []
        for predictedVarName, evalStats in self.evalStatsByVarName.items():
            statsDicts.append(evalStats.getAll())
            varNames.append(predictedVarName)
        df = pd.DataFrame(statsDicts, index=varNames)
        df.index.name = "predictedVar"
        return df

    def iterInputOutputGroundTruthTuples(self, predictedVarName=None) -> Generator[Tuple[PandasNamedTuple, Any, Any], None, None]:
        evalStats = self.getEvalStats(predictedVarName)
        for i, namedTuple in enumerate(self.inputData.itertuples()):
            yield namedTuple, evalStats.y_predicted[i], evalStats.y_true[i]


class VectorRegressionModelEvaluationData(VectorModelEvaluationData[RegressionEvalStats]):
    def getEvalStatsCollection(self):
        return RegressionEvalStatsCollection(list(self.evalStatsByVarName.values()))


TEvalData = TypeVar("TEvalData", bound=VectorModelEvaluationData)


class VectorModelEvaluatorParams(ToStringMixin, ABC):
    def __init__(self, dataSplitter: DataSplitter = None, fractionalSplitTestFraction: float = None, fractionalSplitRandomSeed=42,
            fractionalSplitShuffle=True):
        """
        :param dataSplitter: [if test data must be obtained via split] a splitter to use in order to obtain; if None, must specify
            fractionalSplitTestFraction for fractional split (default)
        :param fractionalSplitTestFraction: [if test data must be obtained via split, dataSplitter is None] the fraction of the data to use for testing/evaluation;
        :param fractionalSplitRandomSeed: [if test data must be obtained via split, dataSplitter is none] the random seed to use for the fractional split of the data
        :param fractionalSplitShuffle: [if test data must be obtained via split, dataSplitter is None] whether to randomly (based on randomSeed) shuffle the dataset before
            splitting it
        """
        self._dataSplitter = dataSplitter
        self._fractionalSplitTestFraction = fractionalSplitTestFraction
        self._fractionalSplitRandomSeed = fractionalSplitRandomSeed
        self._fractionalSplitShuffle = fractionalSplitShuffle

    def _toStringExcludePrivate(self) -> bool:
        return True

    def _toStringAdditionalEntries(self) -> Dict[str, Any]:
        d = {}
        if self._dataSplitter is not None:
            d["dataSplitter"] = self._dataSplitter
        else:
            d["fractionalSplitTestFraction"] = self._fractionalSplitTestFraction
            d["fractionalSplitRandomSeed"] = self._fractionalSplitRandomSeed
            d["fractionalSplitShuffle"] = self._fractionalSplitShuffle
        return d

    def getDataSplitter(self) -> DataSplitter:
        if self._dataSplitter is None:
            if self._fractionalSplitTestFraction is None:
                raise ValueError("Cannot create default data splitter, as no split fraction was provided")
            self._dataSplitter = DataSplitterFractional(1 - self._fractionalSplitTestFraction, shuffle=self._fractionalSplitShuffle,
                randomSeed=self._fractionalSplitRandomSeed)
        return self._dataSplitter


class VectorModelEvaluator(MetricsDictProvider, Generic[TEvalData], ABC):
    def __init__(self, data: Optional[InputOutputData], testData: InputOutputData = None, params: VectorModelEvaluatorParams = None):
        """
        Constructs an evaluator with test and training data.

        :param data: the full data set, or, if testData is given, the training data
        :param testData: the data to use for testing/evaluation; if None, must specify appropriate parameters to define splitting
        :param params: the parameters
        """
        if testData is None:
            if params is None:
                raise ValueError("Parameters required for data split must be provided")
            dataSplitter = params.getDataSplitter()
            self.trainingData, self.testData = dataSplitter.split(data)
            log.debug(f"{dataSplitter} created split with {len(self.trainingData)} ({100*len(self.trainingData)/len(data):.2f}%) and "
                f"{len(self.testData)} ({100*len(self.testData)/len(data):.2f}%) training and test data points respectively")
        else:
            self.trainingData = data
            self.testData = testData

    def evalModel(self, model: VectorModelBase, onTrainingData=False) -> TEvalData:
        """
        Evaluates the given model

        :param model: the model to evaluate
        :param onTrainingData: if True, evaluate on this evaluator's training data rather than the held-out test data
        :return: the evaluation result
        """
        data = self.trainingData if onTrainingData else self.testData
        return self._evalModel(model, data)

    @abstractmethod
    def _evalModel(self, model: VectorModelBase, data: InputOutputData) -> TEvalData:
        pass

    def _computeMetrics(self, model: VectorModelFittableBase, onTrainingData=False) -> Dict[str, float]:
        self.fitModel(model)
        evalData = self.evalModel(model, onTrainingData=onTrainingData)
        return evalData.getEvalStats().getAll()

    def fitModel(self, model: VectorModelFittableBase):
        """Fits the given model's parameters using this evaluator's training data"""
        if self.trainingData is None:
            raise Exception(f"Cannot fit model with evaluator {self.__class__.__name__}: no training data provided")
        model.fit(self.trainingData.inputs, self.trainingData.outputs)


class VectorRegressionModelEvaluatorParams(VectorModelEvaluatorParams):
    def __init__(self, dataSplitter: DataSplitter = None, fractionalSplitTestFraction: float = None, fractionalSplitRandomSeed=42,
            fractionalSplitShuffle=True, additionalMetrics: Sequence[RegressionMetric] = None,
            outputDataFrameTransformer: DataFrameTransformer = None):
        """
        :param dataSplitter: [if test data must be obtained via split] a splitter to use in order to obtain; if None, must specify
            fractionalSplitTestFraction for fractional split (default)
        :param fractionalSplitTestFraction: [if dataSplitter is None, test data must be obtained via split] the fraction of the data to use for testing/evaluation;
        :param fractionalSplitRandomSeed: [if dataSplitter is none, test data must be obtained via split] the random seed to use for the fractional split of the data
        :param fractionalSplitShuffle: [if dataSplitter is None, test data must be obtained via split] whether to randomly (based on randomSeed) shuffle the dataset before
            splitting it
        :param additionalMetrics: additional regression metrics to apply
        :param outputDataFrameTransformer: a data frame transformer to apply to all output data frames (both model outputs and ground truth),
            such that evaluation metrics are computed on the transformed data frame
        """
        super().__init__(dataSplitter, fractionalSplitTestFraction=fractionalSplitTestFraction, fractionalSplitRandomSeed=fractionalSplitRandomSeed,
            fractionalSplitShuffle=fractionalSplitShuffle)
        self.additionalMetrics = additionalMetrics
        self.outputDataFrameTransformer = outputDataFrameTransformer

    @classmethod
    def fromDictOrInstance(cls, params: Optional[Union[Dict[str, Any], "VectorRegressionModelEvaluatorParams"]]) -> "VectorRegressionModelEvaluatorParams":
        if params is None:
            return VectorRegressionModelEvaluatorParams()
        elif type(params) == dict:
            return cls.fromOldKwArgs(**params)
        elif isinstance(params, VectorRegressionModelEvaluatorParams):
            return params
        else:
            raise ValueError(f"Must provide dictionary or instance, got {params}")

    @classmethod
    def fromOldKwArgs(cls, dataSplitter=None, testFraction=None, randomSeed=42, shuffle=True, additionalMetrics: Sequence[RegressionMetric] = None,
            outputDataFrameTransformer: DataFrameTransformer = None) -> "VectorRegressionModelEvaluatorParams":
        return cls(dataSplitter=dataSplitter, fractionalSplitTestFraction=testFraction, fractionalSplitRandomSeed=randomSeed,
            fractionalSplitShuffle=shuffle, additionalMetrics=additionalMetrics, outputDataFrameTransformer=outputDataFrameTransformer)


class VectorRegressionModelEvaluator(VectorModelEvaluator[VectorRegressionModelEvaluationData]):
    def __init__(self, data: Optional[InputOutputData], testData: InputOutputData = None, params: VectorRegressionModelEvaluatorParams = None,
            **kwArgsOldParams):
        """
        Constructs an evaluator with test and training data.

        :param data: the full data set, or, if testData is given, the training data
        :param testData: the data to use for testing/evaluation; if None, must specify appropriate parameters to define splitting
        :param params: the parameters
        :param kwArgsOldParams: old-style keyword parameters (for backward compatibility only)
        """
        params = self._createParams(params, kwArgsOldParams)
        super().__init__(data=data, testData=testData, params=params)
        self.params = params

    @staticmethod
    def _createParams(params: VectorRegressionModelEvaluatorParams, kwArgsOldParams: dict) -> VectorRegressionModelEvaluatorParams:
        if params is not None:
            return params
        elif len(kwArgsOldParams) > 0:
            return VectorRegressionModelEvaluatorParams.fromOldKwArgs(**kwArgsOldParams)
        else:
            return VectorRegressionModelEvaluatorParams()

    def _evalModel(self, model: VectorModelBase, data: InputOutputData) -> VectorRegressionModelEvaluationData:
        if not model.isRegressionModel():
            raise ValueError(f"Expected a regression model, got {model}")
        evalStatsByVarName = {}
        predictions, groundTruth = self._computeOutputs(model, data)
        for predictedVarName in predictions.columns:
            evalStats = RegressionEvalStats(y_predicted=predictions[predictedVarName], y_true=groundTruth[predictedVarName],
                additionalMetrics=self.params.additionalMetrics)
            evalStatsByVarName[predictedVarName] = evalStats
        return VectorRegressionModelEvaluationData(evalStatsByVarName, data.inputs, model)

    def computeTestDataOutputs(self, model: VectorModelBase) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Applies the given model to the test data

        :param model: the model to apply
        :return: a pair (predictions, groundTruth)
        """
        return self._computeOutputs(model, self.testData)

    def _computeOutputs(self, model: VectorModelBase, inputOutputData: InputOutputData):
        """
        Applies the given model to the given data

        :param model: the model to apply
        :param inputOutputData: the data set
        :return: a pair (predictions, groundTruth)
        """
        predictions = model.predict(inputOutputData.inputs)
        groundTruth = inputOutputData.outputs
        if self.params.outputDataFrameTransformer:
            predictions = self.params.outputDataFrameTransformer.apply(predictions)
            groundTruth = self.params.outputDataFrameTransformer.apply(groundTruth)
        return predictions, groundTruth


class VectorClassificationModelEvaluationData(VectorModelEvaluationData[ClassificationEvalStats]):
    pass


class VectorClassificationModelEvaluatorParams(VectorModelEvaluatorParams):
    def __init__(self, dataSplitter: DataSplitter = None, fractionalSplitTestFraction: float = None, fractionalSplitRandomSeed=42,
            fractionalSplitShuffle=True, additionalMetrics: Sequence[ClassificationMetric] = None,
            computeProbabilities: bool = False):
        """
        :param dataSplitter: [if test data must be obtained via split] a splitter to use in order to obtain; if None, must specify
            fractionalSplitTestFraction for fractional split (default)
        :param fractionalSplitTestFraction: [if dataSplitter is None, test data must be obtained via split] the fraction of the data to use for testing/evaluation;
        :param fractionalSplitRandomSeed: [if dataSplitter is none, test data must be obtained via split] the random seed to use for the fractional split of the data
        :param fractionalSplitShuffle: [if dataSplitter is None, test data must be obtained via split] whether to randomly (based on randomSeed) shuffle the dataset before
            splitting it
        :param additionalMetrics: additional metrics to apply
        :param computeProbabilities: whether to compute class probabilities
        """
        super().__init__(dataSplitter, fractionalSplitTestFraction=fractionalSplitTestFraction, fractionalSplitRandomSeed=fractionalSplitRandomSeed,
            fractionalSplitShuffle=fractionalSplitShuffle)
        self.additionalMetrics = additionalMetrics
        self.computeProbabilities = computeProbabilities

    @classmethod
    def fromOldKwArgs(cls, dataSplitter=None, testFraction=None,
            randomSeed=42, computeProbabilities=False, shuffle=True, additionalMetrics: Sequence[ClassificationMetric] = None):
        return cls(dataSplitter=dataSplitter, fractionalSplitTestFraction=testFraction, fractionalSplitRandomSeed=randomSeed,
            fractionalSplitShuffle=shuffle, additionalMetrics=additionalMetrics, computeProbabilities=computeProbabilities)

    @classmethod
    def fromDictOrInstance(cls, params: Optional[Union[Dict[str, Any], "VectorClassificationModelEvaluatorParams"]]) -> "VectorClassificationModelEvaluatorParams":
        if params is None:
            return VectorClassificationModelEvaluatorParams()
        elif type(params) == dict:
            return cls.fromOldKwArgs(**params)
        elif isinstance(params, VectorClassificationModelEvaluatorParams):
            return params
        else:
            raise ValueError(f"Must provide dictionary or instance, got {params}")


class VectorClassificationModelEvaluator(VectorModelEvaluator[VectorClassificationModelEvaluationData]):
    def __init__(self, data: Optional[InputOutputData], testData: InputOutputData = None, params: VectorClassificationModelEvaluatorParams = None,
            **kwArgsOldParams):
        """
        Constructs an evaluator with test and training data.

        :param data: the full data set, or, if testData is given, the training data
        :param testData: the data to use for testing/evaluation; if None, must specify appropriate parameters to define splitting
        :param params: the parameters
        :param kwArgsOldParams: old-style keyword parameters (for backward compatibility only)
        """
        params = self._createParams(params, kwArgsOldParams)
        super().__init__(data=data, testData=testData, params=params)
        self.params = params

    @staticmethod
    def _createParams(params: VectorClassificationModelEvaluatorParams, kwArgs: dict) -> VectorClassificationModelEvaluatorParams:
        if params is not None:
            return params
        elif len(kwArgs) > 0:
            return VectorClassificationModelEvaluatorParams.fromOldKwArgs(kwArgs)
        else:
            return VectorClassificationModelEvaluatorParams()

    def _evalModel(self, model: VectorClassificationModel, data: InputOutputData) -> VectorClassificationModelEvaluationData:
        if model.isRegressionModel():
            raise ValueError(f"Expected a classification model, got {model}")
        predictions, predictions_proba, groundTruth = self._computeOutputs(model, data)
        evalStats = ClassificationEvalStats(y_predictedClassProbabilities=predictions_proba, y_predicted=predictions, y_true=groundTruth,
            labels=model.getClassLabels(), additionalMetrics=self.params.additionalMetrics)
        predictedVarName = model.getPredictedVariableNames()[0]
        return VectorClassificationModelEvaluationData({predictedVarName: evalStats}, data.inputs, model)

    def computeTestDataOutputs(self, model) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Applies the given model to the test data

        :param model: the model to apply
        :return: a triple (predictions, predicted class probability vectors, groundTruth) of DataFrames
        """
        return self._computeOutputs(model, self.testData)

    def _computeOutputs(self, model, inputOutputData: InputOutputData) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Applies the given model to the given data

        :param model: the model to apply
        :param inputOutputData: the data set
        :return: a triple (predictions, predicted class probability vectors, groundTruth) of DataFrames
        """
        if self.params.computeProbabilities:
            classProbabilities = model.predictClassProbabilities(inputOutputData.inputs)
            predictions = model.convertClassProbabilitiesToPredictions(classProbabilities)
        else:
            classProbabilities = None
            predictions = model.predict(inputOutputData.inputs)
        groundTruth = inputOutputData.outputs
        return predictions, classProbabilities, groundTruth


class RuleBasedVectorClassificationModelEvaluator(VectorClassificationModelEvaluator):
    def __init__(self, data: InputOutputData):
        super().__init__(data, testData=data)

    def evalModel(self, model: VectorModelBase, onTrainingData=False) -> VectorClassificationModelEvaluationData:
        """
        Evaluate the rule based model. The training data and test data coincide, thus fitting the model
        will fit the model's preprocessors on the full data set and evaluating it will evaluate the model on the
        same data set.

        :param model:
        :param onTrainingData: has to be False here. Setting to True is not supported and will lead to an
            exception
        :return:
        """
        if onTrainingData:
            raise Exception("Evaluating rule based models on training data is not supported. In this evaluator"
                            "training and test data coincide.")
        return super().evalModel(model)


class RuleBasedVectorRegressionModelEvaluator(VectorRegressionModelEvaluator):
    def __init__(self, data: InputOutputData):
        super().__init__(data, testData=data)

    def evalModel(self, model: VectorModelBase, onTrainingData=False) -> VectorRegressionModelEvaluationData:
        """
        Evaluate the rule based model. The training data and test data coincide, thus fitting the model
        will fit the model's preprocessors on the full data set and evaluating it will evaluate the model on the
        same data set.

        :param model:
        :param onTrainingData: has to be False here. Setting to True is not supported and will lead to an
            exception
        :return:
        """
        if onTrainingData:
            raise Exception("Evaluating rule based models on training data is not supported. In this evaluator"
                            "training and test data coincide.")
        return super().evalModel(model)
