from abc import ABC, abstractmethod
import logging
from typing import Any, Union, Optional

import numpy as np
import pandas as pd

from .data_transformation import DFTNormalisation
from .featuregen import FeatureGeneratorFromColumnGenerator
from .util.cache import KeyValueCache


log = logging.getLogger(__name__)


class ColumnGenerator:
    """
    Generates a single column (pd.Series) from an input data frame, which is to have the same index as the input
    """
    def __init__(self, generated_column_name: str):
        """
        :param generated_column_name: the name of the column being generated
        """
        self.generatedColumnName = generated_column_name

    def generate_column(self, df: pd.DataFrame) -> pd.Series:
        """
        Generates a column from the input data frame

        :param df: the input data frame
        :return: the column as a named series, which has the same index as the input
        """
        result = self._generate_column(df)
        if isinstance(result, pd.Series):
            result.name = self.generatedColumnName
        else:
            result = pd.Series(result, index=df.index, name=self.generatedColumnName)
        return result

    @abstractmethod
    def _generate_column(self, df: pd.DataFrame) -> Union[pd.Series, list, np.ndarray]:
        """
        Performs the actual column generation

        :param df: the input data frame
        :return: a list/array of the same length as df or a series with the same index
        """
        pass

    def to_feature_generator(self,
            take_input_column_if_present: bool = False,
            normalisation_rule_template: DFTNormalisation.RuleTemplate = None,
            is_categorical: bool = False):
        """
        Transforms this column generator into a feature generator that can be used as part of a VectorModel.

        :param take_input_column_if_present: if True, then if a column whose name corresponds to the column to generate exists
            in the input data, simply copy it to generate the output (without using the column generator); if False, always
            apply the columnGen to generate the output
        :param is_categorical: whether the resulting column is categorical
        :param normalisation_rule_template: template for a DFTNormalisation for the resulting column.
            This should only be provided if is_categorical is False
        :return:
        """
        return FeatureGeneratorFromColumnGenerator(self,
            take_input_column_if_present=take_input_column_if_present,
            normalisation_rule_template=normalisation_rule_template,
            is_categorical=is_categorical)


class IndexCachedColumnGenerator(ColumnGenerator):
    """
    Decorator for a column generator which adds support for cached column generation where cache keys are given by the input data frame's
    index. Entries not found in the cache are computed by the wrapped column generator.

    The main use case for this class is to add caching to existing ColumnGenerators. For creating a new caching
    ColumnGenerator the use of ColumnGeneratorCachedByIndex is encouraged.
    """

    log = log.getChild(__qualname__)

    def __init__(self, column_generator: ColumnGenerator, cache: KeyValueCache):
        """
        :param column_generator: the column generator with which to generate values for keys not found in the cache
        :param cache: the cache in which to store key-value pairs
        """
        super().__init__(column_generator.generatedColumnName)
        self.columnGenerator = column_generator
        self.cache = cache

    def _generate_column(self, df: pd.DataFrame) -> pd.Series:
        # compute series of cached values
        cache_values = [self.cache.get(nt.Index) for nt in df.itertuples()]
        cache_series = pd.Series(cache_values, dtype=object, index=df.index).dropna()

        # compute missing values (if any) via wrapped generator, storing them in the cache
        missing_values_df = df[~df.index.isin(cache_series.index)]
        self.log.info(f"Retrieved {len(cache_series)} values from the cache, {len(missing_values_df)} still to be computed by "
                      f"{self.columnGenerator}")
        if len(missing_values_df) == 0:
            return cache_series
        else:
            missing_series = self.columnGenerator.generate_column(missing_values_df)
            for key, value in missing_series.iteritems():
                self.cache.set(key, value)
            return pd.concat((cache_series, missing_series))


class ColumnGeneratorCachedByIndex(ColumnGenerator, ABC):
    """
    Base class for column generators, which supports cached column generation, each value being generated independently.
    Cache keys are given by the input data frame's index.
    """

    log = log.getChild(__qualname__)

    def __init__(self, generated_column_name: str, cache: Optional[KeyValueCache], persist_cache=False):
        """
        :param generated_column_name: the name of the column being generated
        :param cache: the cache in which to store key-value pairs. If None, caching will be disabled
        :param persist_cache: whether to persist the cache when pickling
        """
        super().__init__(generated_column_name)
        self.cache = cache
        self.persistCache = persist_cache

    def _generate_column(self, df: pd.DataFrame) -> Union[pd.Series, list, np.ndarray]:
        self.log.info(f"Generating column {self.generatedColumnName} with {self.__class__.__name__}")
        values = []
        cache_hits = 0
        column_length = len(df)
        percentage_to_log = 0
        for i, namedTuple in enumerate(df.itertuples()):
            percentage_generated = int(100*i/column_length)
            if percentage_generated == percentage_to_log:
                self.log.debug(f"Processed {percentage_to_log}% of {self.generatedColumnName}")
                percentage_to_log += 5

            key = namedTuple.Index
            if self.cache is not None:
                value = self.cache.get(key)
                if value is None:
                    value = self._generate_value(namedTuple)
                    self.cache.set(key, value)
                else:
                    cache_hits += 1
            else:
                value = self._generate_value(namedTuple)
            values.append(value)
        if self.cache is not None:
            self.log.info(f"Cached column generation resulted in {cache_hits}/{column_length} cache hits")
        return values

    def __getstate__(self):
        if not self.persistCache:
            d = self.__dict__.copy()
            d["cache"] = None
            return d
        return self.__dict__

    @abstractmethod
    def _generate_value(self, named_tuple) -> Any:
        pass
