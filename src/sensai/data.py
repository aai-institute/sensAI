from abc import ABC, abstractmethod
from typing import Tuple, Sequence, TypeVar, Callable, List, Any, Iterator, Generic, Hashable

import numpy as np
import pandas as pd
import scipy.stats


class BaseInputOutputData(ABC):
    def __init__(self, inputs, outputs):
        """
        :param inputs: expected to have shape and __len__
        :param outputs: expected to have shape and __len__
        """
        if len(inputs) != len(outputs):
            raise ValueError("Lengths do not match")
        self.inputs = inputs
        self.outputs = outputs

    def __len__(self):
        return len(self.inputs)

    @abstractmethod
    def filterIndices(self, indices: Sequence[int]) -> __qualname__:
        pass


class InputOutputArrays(BaseInputOutputData):
    def __init__(self, inputs: np.ndarray, outputs: np.ndarray):

        if inputs.shape[0] != outputs.shape[0]:
            raise ValueError(f"First dimension of inputs array is not the same as first dimension of outputs array")

        super().__init__(inputs, outputs)

    def filterIndices(self, indices: Sequence[int]) -> __qualname__:
        inputs = self.inputs[indices]
        outputs = self.outputs[indices]
        return InputOutputArrays(inputs, outputs)

    def toTorchDataLoader(self, batchSize=64, shuffle=True):
        try:
            import torch
            from torch.utils.data import DataLoader, TensorDataset
        except ImportError:
            raise ImportError(f"Could not import torch, did you install it?")
        dataSet = TensorDataset(torch.tensor(self.inputs), torch.tensor(self.outputs))
        return DataLoader(dataSet, batch_size=batchSize, shuffle=shuffle)


# TODO: Rename to InputOutputDataFrames when the time for breaking changes has come
class InputOutputData(BaseInputOutputData):
    def __init__(self, inputs: pd.DataFrame, outputs: pd.DataFrame):

        if not inputs.index.equals(outputs.index):
            raise ValueError(f"Input dataframe index not the same as output dataframe index")

        super().__init__(inputs, outputs)

    def filterIndices(self, indices: Sequence[int]) -> __qualname__:
        inputs = self.inputs.iloc[indices]
        outputs = self.outputs.iloc[indices]
        return InputOutputData(inputs, outputs)

    def filterDataFrameIndices(self, indices: Sequence[Hashable]) -> __qualname__:
        inputs = self.inputs.loc[indices]
        outputs = self.outputs.loc[indices]
        return InputOutputData(inputs, outputs)

    def iterDataFrameIndex(self) -> Iterator[Any]:
        yield from self.outputs.index

    @property
    def inputDim(self):
        return self.inputs.shape[1]

    @property
    def outputDim(self):
        return self.outputs.shape[1]

    def computeInputOutputCorrelation(self):
        correlations = {}
        for outputCol in self.outputs.columns:
            correlations[outputCol] = {}
            outputSeries = self.outputs[outputCol]
            for inputCol in self.inputs.columns:
                inputSeries = self.inputs[inputCol]
                pcc, pvalue = scipy.stats.pearsonr(inputSeries, outputSeries)
                correlations[outputCol][inputCol] = pcc
        return correlations


TInputOutputData = TypeVar("TInputOutputData", bound=BaseInputOutputData)


class DataSplitter(Generic[TInputOutputData], ABC):
    @abstractmethod
    def split(self, data: TInputOutputData) -> Tuple[TInputOutputData, TInputOutputData]:
        pass


class DataSplitterFractional(DataSplitter):
    def __init__(self, fractionalSizeOfFirstSet: float, shuffle=True, randomSeed=42):
        if not 0 <= fractionalSizeOfFirstSet <= 1:
            raise Exception(f"invalid fraction: {fractionalSizeOfFirstSet}")
        self.fractionalSizeOfFirstSet = fractionalSizeOfFirstSet
        self.shuffle = shuffle
        self.randomSeed = randomSeed

    def split(self, data: TInputOutputData) -> Tuple[TInputOutputData, TInputOutputData]:
        numDataPoints = len(data)
        splitIndex = int(numDataPoints * self.fractionalSizeOfFirstSet)
        rand = np.random.RandomState(self.randomSeed)
        if self.shuffle:
            indices = rand.permutation(numDataPoints)
        else:
            indices = range(numDataPoints)
        indicesA = indices[:splitIndex]
        indicesB = indices[splitIndex:]
        A = data.filterIndices(list(indicesA))
        B = data.filterIndices(list(indicesB))
        return A, B


class ComplementBasedInputOutputDataSplitter(DataSplitter[InputOutputData], ABC):

    def split(self, data: InputOutputData) -> Tuple[InputOutputData, InputOutputData]:
        firstSetIndices = self._determineFirstSetIndices(data)
        firstSetIndicesSet = set(firstSetIndices)
        secondSetIndices = [idx for idx in data.inputs.index if idx not in firstSetIndicesSet]

        firstSet = data.filterDataFrameIndices(firstSetIndices)
        secondSet = data.filterDataFrameIndices(secondSetIndices)
        
        return firstSet, secondSet

    @abstractmethod
    def _determineFirstSetIndices(self, data: InputOutputData) -> List[Hashable]:
        pass
