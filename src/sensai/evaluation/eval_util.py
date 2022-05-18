"""
This module contains methods and classes that facilitate evaluation of different types of models. The suggested
workflow for evaluation is to use these higher-level functionalities instead of instantiating
the evaluation classes directly.
"""
# TODO: provide a notebook (and possibly an rst file) that illustrates standard evaluation scenarios and at the same
#  time serves as an integration test
import functools
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import Tuple, Dict, Any, Union, Generic, TypeVar, Optional, Sequence, Callable, Set, Iterable, List

import matplotlib.figure
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from .crossval import VectorModelCrossValidationData, VectorRegressionModelCrossValidationData, \
    VectorClassificationModelCrossValidationData, \
    VectorClassificationModelCrossValidator, VectorRegressionModelCrossValidator, VectorModelCrossValidator, VectorModelCrossValidatorParams
from .eval_stats import RegressionEvalStatsCollection, ClassificationEvalStatsCollection, RegressionEvalStatsPlotErrorDistribution, \
    RegressionEvalStatsPlotHeatmapGroundTruthPredictions, RegressionEvalStatsPlotScatterGroundTruthPredictions, \
    ClassificationEvalStatsPlotConfusionMatrix, ClassificationEvalStatsPlotPrecisionRecall, RegressionEvalStatsPlot, \
    ClassificationEvalStatsPlotProbabilityThresholdPrecisionRecall, ClassificationEvalStatsPlotProbabilityThresholdCounts
from .eval_stats.eval_stats_base import EvalStats, EvalStatsCollection, EvalStatsPlot
from .eval_stats.eval_stats_classification import ClassificationEvalStats
from .eval_stats.eval_stats_regression import RegressionEvalStats
from .evaluator import VectorModelEvaluator, VectorModelEvaluationData, VectorRegressionModelEvaluator, \
    VectorRegressionModelEvaluationData, VectorClassificationModelEvaluator, VectorClassificationModelEvaluationData, \
    VectorRegressionModelEvaluatorParams, VectorClassificationModelEvaluatorParams, VectorModelEvaluatorParams
from ..data import InputOutputData
from ..sklearn.sklearn_util import AggregatedFeatureImportances
from ..util.io import ResultWriter
from ..util.string import prettyStringRepr
from ..vector_model import VectorClassificationModel, VectorRegressionModel, VectorModel

log = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=VectorModel)
TEvalStats = TypeVar("TEvalStats", bound=EvalStats)
TEvalStatsPlot = TypeVar("TEvalStatsPlot", bound=EvalStatsPlot)
TEvalStatsCollection = TypeVar("TEvalStatsCollection", bound=EvalStatsCollection)
TEvaluator = TypeVar("TEvaluator", bound=VectorModelEvaluator)
TCrossValidator = TypeVar("TCrossValidator", bound=VectorModelCrossValidator)
TEvalData = TypeVar("TEvalData", bound=VectorModelEvaluationData)
TCrossValData = TypeVar("TCrossValData", bound=VectorModelCrossValidationData)


def _isRegression(model: Optional[VectorModel], isRegression: Optional[bool]) -> bool:
    if model is None and isRegression is None or (model is not None and isRegression is not None):
        raise ValueError("One of the two parameters have to be passed: model or isRegression")

    if isRegression is None:
        model: VectorModel
        return model.isRegressionModel()
    return isRegression


def createVectorModelEvaluator(data: InputOutputData, model: VectorModel = None,
        isRegression: bool = None, params: Union[VectorModelEvaluatorParams, Dict[str, Any]] = None, **kwargs) \
            -> Union[VectorRegressionModelEvaluator, VectorClassificationModelEvaluator]:
    if params is not None and len(kwargs) > 0:
        raise ValueError("Provide either params or keyword arguments")
    if params is None:
        params = kwargs
    regression = _isRegression(model, isRegression)
    if regression:
        params = VectorRegressionModelEvaluatorParams.fromDictOrInstance(params)
    else:
        params = VectorClassificationModelEvaluatorParams.fromDictOrInstance(params)
    cons = VectorRegressionModelEvaluator if regression else VectorClassificationModelEvaluator
    return cons(data, params=params)


def createVectorModelCrossValidator(data: InputOutputData, model: VectorModel = None,
        isRegression: bool = None,
        params: Union[VectorModelCrossValidatorParams, Dict[str, Any]] = None,
        **kwArgsOldParams) -> Union[VectorClassificationModelCrossValidator, VectorRegressionModelCrossValidator]:
    if params is not None:
        params = VectorModelCrossValidatorParams.fromDictOrInstance(params)
    params = VectorModelCrossValidatorParams.fromEitherDictOrInstance(kwArgsOldParams, params)
    cons = VectorRegressionModelCrossValidator if _isRegression(model, isRegression) else VectorClassificationModelCrossValidator
    return cons(data, params=params)


def createEvaluationUtil(data: InputOutputData, model: VectorModel = None, isRegression: bool = None,
        evaluatorParams: Optional[Dict[str, Any]] = None,
        crossValidatorParams: Optional[Dict[str, Any]] = None) \
            -> Union["ClassificationEvaluationUtil", "RegressionEvaluationUtil"]:
    cons = RegressionEvaluationUtil if _isRegression(model, isRegression) else ClassificationEvaluationUtil
    return cons(data, evaluatorParams=evaluatorParams, crossValidatorParams=crossValidatorParams)


def evalModelViaEvaluator(model: TModel, inputOutputData: InputOutputData, testFraction=0.2,
        plotTargetDistribution=False, computeProbabilities=True, normalizePlots=True, randomSeed=60) -> TEvalData:
    """
    Evaluates the given model via a simple evaluation mechanism that uses a single split

    :param model: the model to evaluate
    :param inputOutputData: data on which to evaluate
    :param testFraction: the fraction of the data to test on
    :param plotTargetDistribution: whether to plot the target values distribution in the entire dataset
    :param computeProbabilities: only relevant if the model is a classifier
    :param normalizePlots: whether to normalize plotted distributions such that the sum/integrate to 1
    :param randomSeed:

    :return: the evaluation data
    """
    if plotTargetDistribution:
        title = "Distribution of target values in entire dataset"
        fig = plt.figure(title)

        outputDistributionSeries = inputOutputData.outputs.iloc[:, 0]
        log.info(f"Description of target column in training set: \n{outputDistributionSeries.describe()}")
        if not model.isRegressionModel():
            outputDistributionSeries = outputDistributionSeries.value_counts(normalize=normalizePlots)
            ax = sns.barplot(outputDistributionSeries.index, outputDistributionSeries.values)
            ax.set_ylabel("%")
        else:
            ax = sns.distplot(outputDistributionSeries)
            ax.set_ylabel("Probability density")
        ax.set_title(title)
        ax.set_xlabel("target value")
        fig.show()

    if model.isRegressionModel():
        evaluatorParams = dict(testFraction=testFraction, randomSeed=randomSeed)
    else:
        evaluatorParams = dict(testFraction=testFraction, computeProbabilities=computeProbabilities, randomSeed=randomSeed)
    ev = createEvaluationUtil(inputOutputData, model=model, evaluatorParams=evaluatorParams)
    return ev.performSimpleEvaluation(model, showPlots=True, logResults=True)


class EvaluationResultCollector:
    def __init__(self, showPlots: bool = True, resultWriter: Optional[ResultWriter] = None):
        self.showPlots = showPlots
        self.resultWriter = resultWriter

    def addFigure(self, name, fig: matplotlib.figure.Figure):
        if self.resultWriter is not None:
            self.resultWriter.writeFigure(name, fig, closeFigure=not self.showPlots)

    def child(self, addedFilenamePrefix):
        resultWriter = self.resultWriter
        if resultWriter:
            resultWriter = resultWriter.childWithAddedPrefix(addedFilenamePrefix)
        return self.__class__(showPlots=self.showPlots, resultWriter=resultWriter)


class EvalStatsPlotCollector(Generic[TEvalStats, TEvalStatsPlot]):
    def __init__(self):
        self.plots: Dict[str, EvalStatsPlot] = {}
        self.disabledPlots: Set[str] = set()

    def addPlot(self, name: str, plot: EvalStatsPlot):
        self.plots[name] = plot

    def getEnabledPlots(self) -> List[str]:
        return [p for p in self.plots if p not in self.disabledPlots]

    def disablePlots(self, *names: str):
        self.disabledPlots.update(names)

    def createPlots(self, evalStats: EvalStats, subtitle: str, resultCollector: EvaluationResultCollector):
        knownPlots = set(self.plots.keys())
        unknownDisabledPlots = self.disabledPlots.difference(knownPlots)
        if len(unknownDisabledPlots) > 0:
            log.warning(f"Plots were disabled which are not registered: {unknownDisabledPlots}; known plots: {knownPlots}")
        for name, plot in self.plots.items():
            if name not in self.disabledPlots:
                fig = plot.createFigure(evalStats, subtitle)
                if fig is not None:
                    resultCollector.addFigure(name, fig)


class RegressionEvalStatsPlotCollector(EvalStatsPlotCollector[RegressionEvalStats, RegressionEvalStatsPlot]):
    def __init__(self):
        super().__init__()
        self.addPlot("error-dist", RegressionEvalStatsPlotErrorDistribution())
        self.addPlot("heatmap-gt-pred", RegressionEvalStatsPlotHeatmapGroundTruthPredictions())
        self.addPlot("scatter-gt-pred", RegressionEvalStatsPlotScatterGroundTruthPredictions())


class ClassificationEvalStatsPlotCollector(EvalStatsPlotCollector[RegressionEvalStats, RegressionEvalStatsPlot]):
    def __init__(self):
        super().__init__()
        self.addPlot("confusion-matrix-rel", ClassificationEvalStatsPlotConfusionMatrix(normalise=True))
        self.addPlot("confusion-matrix-abs", ClassificationEvalStatsPlotConfusionMatrix(normalise=False))
        # the plots below apply to the binary case only (skipped for non-binary case)
        self.addPlot("precision-recall", ClassificationEvalStatsPlotPrecisionRecall())
        self.addPlot("threshold-precision-recall", ClassificationEvalStatsPlotProbabilityThresholdPrecisionRecall())
        self.addPlot("threshold-counts", ClassificationEvalStatsPlotProbabilityThresholdCounts())


class EvaluationUtil(ABC, Generic[TModel, TEvaluator, TEvalData, TCrossValidator, TCrossValData, TEvalStats]):
    """
    Utility class for the evaluation of models based on a dataset
    """
    def __init__(self, inputOutputData: InputOutputData,
            evalStatsPlotCollector: Union[RegressionEvalStatsPlotCollector, ClassificationEvalStatsPlotCollector],
            evaluatorParams: Optional[Union[VectorRegressionModelEvaluatorParams, VectorClassificationModelEvaluatorParams, Dict[str, Any]]] = None,
            crossValidatorParams: Optional[Union[VectorModelCrossValidatorParams, Dict[str, Any]]] = None):
        """
        :param inputOutputData: the data set to use for evaluation
        :param evalStatsPlotCollector: a collector for plots generated from evaluation stats objects
        :param evaluatorParams: parameters with which to instantiate evaluators
        :param crossValidatorParams: parameters with which to instantiate cross-validators
        """
        if evaluatorParams is None:
            evaluatorParams = dict(testFraction=0.2)
        if crossValidatorParams is None:
            crossValidatorParams = VectorModelCrossValidatorParams(folds=5)
        self.evaluatorParams = evaluatorParams
        self.crossValidatorParams = crossValidatorParams
        self.inputOutputData = inputOutputData
        self.evalStatsPlotCollector = evalStatsPlotCollector

    def createEvaluator(self, model: TModel = None, isRegression: bool = None) -> TEvaluator:
        """
        Creates an evaluator holding the current input-output data

        :param model: the model for which to create an evaluator (just for reading off regression or classification,
            the resulting evaluator will work on other models as well)
        :param isRegression: whether to create a regression model evaluator. Either this or model have to be specified
        :return: an evaluator
        """
        return createVectorModelEvaluator(self.inputOutputData, model=model, isRegression=isRegression, params=self.evaluatorParams)

    def createCrossValidator(self, model: TModel = None, isRegression: bool = None) -> TCrossValidator:
        """
        Creates a cross-validator holding the current input-output data

        :param model: the model for which to create a cross-validator (just for reading off regression or classification,
            the resulting evaluator will work on other models as well)
        :param isRegression: whether to create a regression model cross-validator. Either this or model have to be specified
        :return: an evaluator
        """
        return createVectorModelCrossValidator(self.inputOutputData, model=model, isRegression=isRegression, params=self.crossValidatorParams)

    def performSimpleEvaluation(self, model: TModel, createPlots=True, showPlots=False, logResults=True, resultWriter: ResultWriter = None,
            additionalEvaluationOnTrainingData=False, fitModel=True, writeEvalStats=False) -> TEvalData:
        if showPlots and not createPlots:
            raise ValueError("showPlots=True requires createPlots=True")
        resultWriter = self._resultWriterForModel(resultWriter, model)
        evaluator = self.createEvaluator(model)
        log.info(f"Evaluating {model} via {evaluator}")
        if fitModel:
            evaluator.fitModel(model)

        def gatherResults(evalResultData: VectorModelEvaluationData, resultWriter, subtitlePrefix=""):
            strEvalResults = ""
            for predictedVarName in evalResultData.predictedVarNames:
                evalStats = evalResultData.getEvalStats(predictedVarName)
                strEvalResult = str(evalStats)
                if logResults:
                    log.info(f"{subtitlePrefix}Evaluation results for {predictedVarName}: {strEvalResult}")
                strEvalResults += predictedVarName + ": " + strEvalResult + "\n"
                if writeEvalStats and resultWriter is not None:
                    resultWriter.writePickle(f"eval-stats-{predictedVarName}", evalStats)
            strEvalResults += f"\n\n{prettyStringRepr(model)}"
            if resultWriter is not None:
                resultWriter.writeTextFile("evaluator-results", strEvalResults)
            if createPlots:
                self.createPlots(evalResultData, showPlots=showPlots, resultWriter=resultWriter, subtitlePrefix=subtitlePrefix)

        evalResultData = evaluator.evalModel(model)
        gatherResults(evalResultData, resultWriter)
        if additionalEvaluationOnTrainingData:
            evalResultDataTrain = evaluator.evalModel(model, onTrainingData=True)
            additionalResultWriter = resultWriter.childWithAddedPrefix("onTrain-") if resultWriter is not None else None
            gatherResults(evalResultDataTrain, additionalResultWriter, subtitlePrefix="[onTrain] ")

        return evalResultData

    @staticmethod
    def _resultWriterForModel(resultWriter: Optional[ResultWriter], model: TModel) -> Optional[ResultWriter]:
        if resultWriter is None:
            return None
        return resultWriter.childWithAddedPrefix(model.getName() + "-")

    def performCrossValidation(self, model: TModel, showPlots=False, logResults=True, resultWriter: Optional[ResultWriter] = None) -> TCrossValData:
        """
        Evaluates the given model via cross-validation

        :param model: the model to evaluate
        :param showPlots: whether to show plots that visualise evaluation results (combining all folds)
        :param logResults: whether to log evaluation results
        :param resultWriter: a writer with which to store text files and plots. The evaluated model's name is added to each filename
            automatically
        :return: cross-validation result data
        """
        resultWriter = self._resultWriterForModel(resultWriter, model)
        crossValidator = self.createCrossValidator(model)
        crossValidationData = crossValidator.evalModel(model)
        aggStatsByVar = {varName: crossValidationData.getEvalStatsCollection(predictedVarName=varName).aggMetricsDict()
                for varName in crossValidationData.predictedVarNames}
        df = pd.DataFrame.from_dict(aggStatsByVar, orient="index")
        strEvalResults = df.to_string()
        if logResults:
            log.info(f"Cross-validation results:\n{strEvalResults}")
        if resultWriter is not None:
            resultWriter.writeTextFile("crossval-results", strEvalResults)
        self.createPlots(crossValidationData, showPlots=showPlots, resultWriter=resultWriter)
        return crossValidationData

    def compareModels(self, models: Sequence[TModel], resultWriter: Optional[ResultWriter] = None, useCrossValidation=False,
            fitModels=True, writeIndividualResults=True, sortColumn: Optional[str] = None, sortAscending: bool = True,
            visitors: Optional[Iterable["ModelComparisonVisitor"]] = None) -> "ModelComparisonData":
        """
        Compares several models via simple evaluation or cross-validation

        :param models: the models to compare
        :param resultWriter: a writer with which to store results of the comparison
        :param useCrossValidation: whether to use cross-validation in order to evaluate models; if False, use a simple evaluation
            on test data (single split)
        :param fitModels: whether to fit models before evaluating them; this can only be False if useCrossValidation=False
        :param writeIndividualResults: whether to write results files on each individual model (in addition to the comparison
            summary)
        :param sortColumn: column/metric name by which to sort
        :param sortAscending: whether to sort in ascending order
        :param visitors: visitors which may process individual results
        :return: the comparison results
        """
        statsList = []
        resultByModelName = {}
        for model in models:
            modelName = model.getName()
            if useCrossValidation:
                if not fitModels:
                    raise ValueError("Cross-validation necessitates that models be retrained; got fitModels=False")
                crossValData = self.performCrossValidation(model, resultWriter=resultWriter if writeIndividualResults else None)
                modelResult = ModelComparisonData.Result(crossValData=crossValData)
                resultByModelName[modelName] = modelResult
                evalStatsCollection = crossValData.getEvalStatsCollection()
                statsDict = evalStatsCollection.aggMetricsDict()
            else:
                evalData = self.performSimpleEvaluation(model, resultWriter=resultWriter if writeIndividualResults else None,
                    fitModel=fitModels)
                modelResult = ModelComparisonData.Result(evalData=evalData)
                resultByModelName[modelName] = modelResult
                evalStats = evalData.getEvalStats()
                statsDict = evalStats.metricsDict()
            statsDict["modelName"] = modelName
            statsList.append(statsDict)
            if visitors is not None:
                for visitor in visitors:
                    visitor.visit(modelName, modelResult)
        resultsDF = pd.DataFrame(statsList).set_index("modelName")
        if sortColumn is not None:
            if sortColumn not in resultsDF.columns:
                log.warning(f"Requested sort column '{sortColumn}' not in list of columns {list(resultsDF.columns)}")
            else:
                resultsDF.sort_values(sortColumn, ascending=sortAscending, inplace=True)
        strResults = f"Model comparison results:\n{resultsDF.to_string()}"
        log.info(strResults)
        if resultWriter is not None:
            suffix = "crossval" if useCrossValidation else "simple-eval"
            strResults += "\n\n" + "\n\n".join([f"{model.getName()} = {str(model)}" for model in models])
            resultWriter.writeTextFile(f"model-comparison-results-{suffix}", strResults)
        return ModelComparisonData(resultsDF, resultByModelName)

    def compareModelsCrossValidation(self, models: Sequence[TModel], resultWriter: Optional[ResultWriter] = None) -> "ModelComparisonData":
        """
        Compares several models via cross-validation

        :param models: the models to compare
        :param resultWriter: a writer with which to store results of the comparison
        :return: the comparison results
        """
        return self.compareModels(models, resultWriter=resultWriter, useCrossValidation=True)

    def createPlots(self, data: Union[TEvalData, TCrossValData], showPlots=True, resultWriter: Optional[ResultWriter] = None, subtitlePrefix: str = ""):
        """
        Creates default plots that visualise the results in the given evaluation data

        :param data: the evaluation data for which to create the default plots
        :param showPlots: whether to show plots
        :param resultWriter: if not None, plots will be written using this writer
        :param subtitlePrefix: a prefix to add to the subtitle (which itself is the model name)
        """
        if not showPlots and resultWriter is None:
            return
        resultCollector = EvaluationResultCollector(showPlots=showPlots, resultWriter=resultWriter)
        self._createPlots(data, resultCollector, subtitle=subtitlePrefix + data.modelName)

    def _createPlots(self, data: Union[TEvalData, TCrossValData], resultCollector: EvaluationResultCollector, subtitle=None):

        def createPlots(predVarName, rc, subt):
            if isinstance(data, VectorModelCrossValidationData):
                evalStats = data.getEvalStatsCollection(predictedVarName=predVarName).getGlobalStats()
            elif isinstance(data, VectorModelEvaluationData):
                evalStats = data.getEvalStats(predictedVarName=predVarName)
            else:
                raise ValueError(f"Unexpected argument: data={data}")
            return self._createEvalStatsPlots(evalStats, rc, subtitle=subt)

        predictedVarNames = data.predictedVarNames
        if len(predictedVarNames) == 1:
            createPlots(predictedVarNames[0], resultCollector, subtitle)
        else:
            for predictedVarName in predictedVarNames:
                createPlots(predictedVarName, resultCollector.child(predictedVarName+"-"), f"{predictedVarName}, {subtitle}")

    def _createEvalStatsPlots(self, evalStats: TEvalStats, resultCollector: EvaluationResultCollector, subtitle=None):
        """
        :param evalStats: the evaluation results for which to create plots
        :param resultCollector: the collector to which all plots are to be passed
        :param subtitle: the subtitle to use for generated plots (if any)
        """
        self.evalStatsPlotCollector.createPlots(evalStats, subtitle, resultCollector)


class RegressionEvaluationUtil(EvaluationUtil[VectorRegressionModel, VectorRegressionModelEvaluator, VectorRegressionModelEvaluationData, VectorRegressionModelCrossValidator, VectorRegressionModelCrossValidationData, RegressionEvalStats]):
    def __init__(self, inputOutputData: InputOutputData,
            evaluatorParams: Optional[Union[VectorRegressionModelEvaluatorParams, Dict[str, Any]]] = None,
            crossValidatorParams: Optional[Union[VectorModelCrossValidatorParams, Dict[str, Any]]] = None):
        """
        :param inputOutputData: the data set to use for evaluation
        :param evaluatorParams: parameters with which to instantiate evaluators
        :param crossValidatorParams: parameters with which to instantiate cross-validators
        """
        super().__init__(inputOutputData, evalStatsPlotCollector=RegressionEvalStatsPlotCollector(), evaluatorParams=evaluatorParams,
            crossValidatorParams=crossValidatorParams)


class ClassificationEvaluationUtil(EvaluationUtil[VectorClassificationModel, VectorClassificationModelEvaluator, VectorClassificationModelEvaluationData, VectorClassificationModelCrossValidator, VectorClassificationModelCrossValidationData, ClassificationEvalStats]):
    def __init__(self, inputOutputData: InputOutputData,
            evaluatorParams: Optional[Union[VectorClassificationModelEvaluatorParams, Dict[str, Any]]] = None,
            crossValidatorParams: Optional[Union[VectorModelCrossValidatorParams, Dict[str, Any]]] = None):
        """
        :param inputOutputData: the data set to use for evaluation
        :param evaluatorParams: parameters with which to instantiate evaluators
        :param crossValidatorParams: parameters with which to instantiate cross-validators
        """
        super().__init__(inputOutputData, evalStatsPlotCollector=ClassificationEvalStatsPlotCollector(), evaluatorParams=evaluatorParams,
            crossValidatorParams=crossValidatorParams)


class MultiDataEvaluationUtil:
    def __init__(self, inputOutputDataDict: Dict[str, InputOutputData], keyName: str = "dataset",
            metaDataDict: Optional[Dict[str, Dict[str, Any]]] = None):
        """
        :param inputOutputDataDict: a dictionary mapping from names to the data sets with which to evaluate models
        :param keyName: a name for the key value used in inputOutputDataDict, which will be used as a column name in result data frames
        :param metaDataDict: a dictionary which maps from a name (same keys as in inputOutputDataDict) to a dictionary, which maps
            from a column name to a value and which is to be used to extend the result data frames containing per-dataset results
        """
        self.inputOutputDataDict = inputOutputDataDict
        self.keyName = keyName
        if metaDataDict is not None:
            self.metaDF = pd.DataFrame(metaDataDict.values(), index=metaDataDict.keys())
        else:
            self.metaDF = None

    def compareModelsCrossValidation(self, modelFactories: Sequence[Callable[[], Union[VectorRegressionModel, VectorClassificationModel]]],
            resultWriter: Optional[ResultWriter] = None, writePerDatasetResults=True,
            crossValidatorParams: Optional[Dict[str, Any]] = None, columnNameForModelRanking: str = None, rankMax=True) -> "MultiDataModelComparisonData":
        """
        Deprecated. Use compareModels instead.
        """
        return self.compareModels(modelFactories, useCrossValidation=True, resultWriter=resultWriter, writePerDatasetResults=writePerDatasetResults,
            crossValidatorParams=crossValidatorParams,
            columnNameForModelRanking=columnNameForModelRanking, rankMax=rankMax)

    def compareModels(self, modelFactories: Sequence[Callable[[], Union[VectorRegressionModel, VectorClassificationModel]]],
            useCrossValidation=False,
            resultWriter: Optional[ResultWriter] = None,
            writePerDatasetResults=True,
            evaluatorParams: Optional[Union[VectorRegressionModelEvaluatorParams, VectorClassificationModelEvaluatorParams, Dict[str, Any]]] = None,
            crossValidatorParams: Optional[Union[VectorModelCrossValidatorParams, Dict[str, Any]]] = None,
            columnNameForModelRanking: str = None,
            rankMax=True,
            createCombinedEvalStatsPlots=False,
            visitors: Optional[Iterable["ModelComparisonVisitor"]] = None) -> Union["RegressionMultiDataModelComparisonData", "ClassificationMultiDataModelComparisonData"]:
        """
        :param modelFactories: a sequence of factory functions for the creation of models to evaluate; every factory must result
            in a model with a fixed model name (otherwise results cannot be correctly aggregated)
        :param useCrossValidation: whether to use cross-validation (rather than a single split) for model evaluation
        :param resultWriter: a writer with which to store results
        :param writePerDatasetResults: whether to use resultWriter (if not None) in order to generate detailed results for each
            dataset in a subdirectory named according to the name of the dataset
        :param evaluatorParams: parameters to use for the instantiation of evaluators (relevant if useCrossValidation==False)
        :param crossValidatorParams: parameters to use for the instantiation of cross-validators (relevant if useCrossValidation==True)
        :param columnNameForModelRanking: column name to use for ranking models
        :param rankMax: if true, use max for ranking, else min
        :param createCombinedEvalStatsPlots: whether to combine, for each type of model, the EvalStats objects from the individual experiments
            into a single objects that holds all results and use it to create plots reflecting the overall result.
            Note that for classification, this is only possible if all individual experiments use the same set of class labels.
        :param visitors: visitors which may process individual results
        :return: a pair of data frames (allDF, meanDF) where allDF contains all the individual evaluation results (one row per data set)
            and meanDF contains one row for each model with results averaged across datasets
        """
        allResultsDF = pd.DataFrame()
        evalStatsByModelName = defaultdict(list)
        isRegression = None
        plotCollector: Optional[EvalStatsPlotCollector] = None
        modelNames = None

        for i, (key, inputOutputData) in enumerate(self.inputOutputDataDict.items(), start=1):
            log.info(f"Evaluating models for data set #{i}/{len(self.inputOutputDataDict)}: {self.keyName}={key}")
            models = [f() for f in modelFactories]

            currentModelNames = [model.getName() for model in models]
            if modelNames is None:
                modelNames = currentModelNames
            elif modelNames != currentModelNames:
                log.warning(f"Model factories do not produce fixed names; use model.withName to name your models. Got {currentModelNames}, previously got {modelNames}")

            if isRegression is None:
                modelsAreRegression = [model.isRegressionModel() for model in models]
                if all(modelsAreRegression):
                    isRegression = True
                elif not any(modelsAreRegression):
                    isRegression = False
                else:
                    raise ValueError("The models have to be either all regression models or all classification, not a mixture")

            ev = createEvaluationUtil(inputOutputData, isRegression=isRegression, evaluatorParams=evaluatorParams,
                crossValidatorParams=crossValidatorParams)

            if plotCollector is None:
                plotCollector = ev.evalStatsPlotCollector

            # compute data frame with results for current data set
            childResultWriter = resultWriter.childForSubdirectory(key) if (writePerDatasetResults and resultWriter is not None) else None
            comparisonData = ev.compareModels(models, useCrossValidation=useCrossValidation, resultWriter=childResultWriter, visitors=visitors)
            df = comparisonData.resultsDF

            # augment data frame
            df[self.keyName] = key
            df["modelName"] = df.index
            df = df.reset_index(drop=True)

            # collect eval stats objects by model name and remove from data frame
            for modelName, result in comparisonData.resultByModelName.items():
                if useCrossValidation:
                    evalStats = result.crossValData.getEvalStatsCollection().getGlobalStats()
                else:
                    evalStats = result.evalData.getEvalStats()
                evalStatsByModelName[modelName].append(evalStats)

            allResultsDF = pd.concat((allResultsDF, df))

        if self.metaDF is not None:
            allResultsDF = allResultsDF.join(self.metaDF, on=self.keyName, how="left")

        strAllResults = f"All results:\n{allResultsDF.to_string()}"
        log.info(strAllResults)

        # create mean result by model, removing any metrics/columns that produced NaN values
        # (because the mean would be computed without them, skipna parameter unsupported)
        allResultsGrouped = allResultsDF.dropna(axis=1).groupby("modelName")
        meanResultsDF: pd.DataFrame = allResultsGrouped.mean()
        if columnNameForModelRanking in meanResultsDF:
            meanResultsDF.sort_values(columnNameForModelRanking, inplace=True, ascending=not rankMax)
        strMeanResults = f"Mean results (averaged across {len(self.inputOutputDataDict)} data sets):\n{meanResultsDF.to_string()}"
        log.info(strMeanResults)

        # create further aggregations
        aggDFs = []
        for opName, aggFn in [("mean", lambda x: x.mean()), ("std", lambda x: x.std()), ("min", lambda x: x.min()), ("max", lambda x: x.max())]:
            aggDF = aggFn(allResultsGrouped)
            aggDF.columns = [f"{opName}[{c}]" for c in aggDF.columns]
            aggDFs.append(aggDF)
        furtherAggsDF = pd.concat(aggDFs, axis=1)
        furtherAggsDF = furtherAggsDF.loc[meanResultsDF.index]  # apply same sort order (index is modelName)
        columnOrder = functools.reduce(lambda a, b: a + b, [list(t) for t in zip(*[df.columns for df in aggDFs])])
        furtherAggsDF = furtherAggsDF[columnOrder]
        strFurtherAggs = f"Further aggregations:\n{furtherAggsDF.to_string()}"
        log.info(strFurtherAggs)

        if resultWriter is not None:
            resultWriter.writeTextFile("model-comparison-results", strMeanResults + "\n\n" + strFurtherAggs + "\n\n" + strAllResults)

        # create plots from combined data for each model
        if createCombinedEvalStatsPlots:
            for modelName, evalStatsList in evalStatsByModelName.items():
                childResultWriter = resultWriter.childWithAddedPrefix(modelName + "_") if resultWriter is not None else None
                resultCollector = EvaluationResultCollector(showPlots=False, resultWriter=childResultWriter)
                if isRegression:
                    evalStats = RegressionEvalStatsCollection(evalStatsList).getGlobalStats()
                else:
                    evalStats = ClassificationEvalStatsCollection(evalStatsList).getGlobalStats()
                plotCollector.createPlots(evalStats, subtitle=modelName, resultCollector=resultCollector)

        if isRegression:
            return RegressionMultiDataModelComparisonData(allResultsDF, meanResultsDF, furtherAggsDF, evalStatsByModelName)
        else:
            return ClassificationMultiDataModelComparisonData(allResultsDF, meanResultsDF, furtherAggsDF, evalStatsByModelName)


class ModelComparisonData:
    @dataclass
    class Result:
        evalData: Union[VectorClassificationModelEvaluationData, VectorRegressionModelEvaluationData] = None
        crossValData: Union[VectorClassificationModelCrossValidationData, VectorRegressionModelCrossValidationData] = None

    def __init__(self, resultsDF: pd.DataFrame, resultsByModelName: Dict[str, Result]):
        self.resultsDF = resultsDF
        self.resultByModelName = resultsByModelName


class ModelComparisonVisitor(ABC):
    @abstractmethod
    def visit(self, modelName: str, result: ModelComparisonData.Result):
        pass


class ModelComparisonVisitorAggregatedFeatureImportances(ModelComparisonVisitor):
    """
    During a model comparison, computes aggregated feature importance values for the model with the given name
    """
    def __init__(self, modelName: str):
        """
        :param modelName: the name of the model for which to compute the aggregated feature importance values
        """
        self.modelName = modelName
        self.aggFeatureImportance = AggregatedFeatureImportances()

    def visit(self, modelName: str, result: ModelComparisonData.Result):
        if modelName == self.modelName:
            if result.crossValData is not None:
                models = result.crossValData.trainedModels
                if models is not None:
                    for model in models:
                        self._collect(model)
                else:
                    raise ValueError("Models were not returned in cross-validation results")
            elif result.evalData is not None:
                self._collect(result.evalData.model)

    def _collect(self, model):
        if not hasattr(model, "getFeatureImportances"):
            raise ValueError(f"Got model which does not have method 'getFeatureImportances': {model}")
        self.aggFeatureImportance.add(model.getFeatureImportances())


class MultiDataModelComparisonData(Generic[TEvalStats, TEvalStatsCollection], ABC):
    def __init__(self, allResultsDF: pd.DataFrame, meanResultsDF: pd.DataFrame, aggResultsDF: pd.DataFrame,
            evalStatsByModelName: Dict[str, List[TEvalStats]]):
        self.allResultsDF = allResultsDF
        self.meanResultsDF = meanResultsDF
        self.aggResultsDF = aggResultsDF
        self.evalStatsByModelName = evalStatsByModelName

    def getModelNames(self) -> List[str]:
        return list(self.evalStatsByModelName.keys())

    def getEvalStatsList(self, modelName: str) -> List[TEvalStats]:
        return self.evalStatsByModelName[modelName]

    @abstractmethod
    def getEvalStatsCollection(self, modelName: str) -> TEvalStatsCollection:
        pass


class ClassificationMultiDataModelComparisonData(MultiDataModelComparisonData[ClassificationEvalStats, ClassificationEvalStatsCollection]):
    def getEvalStatsCollection(self, modelName: str):
        return ClassificationEvalStatsCollection(self.getEvalStatsList(modelName))


class RegressionMultiDataModelComparisonData(MultiDataModelComparisonData[RegressionEvalStats, RegressionEvalStatsCollection]):
    def getEvalStatsCollection(self, modelName: str):
        return RegressionEvalStatsCollection(self.getEvalStatsList(modelName))