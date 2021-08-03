from enum import Enum
from typing import Callable, Union, TypeVar, Generic, Sequence, List, Tuple, Iterable, Dict, Hashable, Optional

import numpy as np

from .util.string import listString, ToStringMixin, dictString

T = TypeVar("T")


class Vectoriser(Generic[T]):
    """
    A vectoriser represents a method for the conversion of instances of some type T into
    vectors, i.e. one-dimensional (numeric) arrays, or (in the special case of a 1D vector) scalars
    """
    def __init__(self, f: Callable[[T], Union[float, np.ndarray, list]], transformer=None):
        """
        :param f: the function which maps from an instance of T to an array/list/scalar
        :param transformer: an optional transformer (e.g. instance of one of the classes in sklearn.preprocessing)
            which can be used to transform/normalise the generated arrays
        """
        self.f = f
        self.transformer = transformer
        self._resultType = None
        self.name = None

    def __setstate__(self, state):
        for newOptionalProperty in ["_resultType", "name"]:
            if newOptionalProperty not in state:
                state[newOptionalProperty] = None
        self.__dict__ = state

    def setName(self, name):
        self.name = name

    def getName(self):
        """
        :return: the name of this feature generator, which may be a default name if the name has not been set. Note that feature generators created
            by a FeatureGeneratorFactory always get the name with which the generator factory was registered.
        """
        if self.name is None:
            return f"{self.__class__.__name__}-{id(self)}"
        return self.name

    def fit(self, items: Iterable[T]):
        if self.transformer is not None:
            values = [self._f(item) for item in items]
            self.transformer.fit(np.array(values))

    def _f(self, x) -> np.array:
        y = self.f(x)

        if self._resultType is None:
            self._resultType = self.ResultType.fromValue(y)

        if self._resultType == self.ResultType.LIST:
            y = np.array(y)
        elif self._resultType == self.ResultType.SCALAR:
            y = np.array([y])

        return y

    def apply(self, item: T, transform=True) -> np.array:
        """
        :param item: the item to be vectorised
        :param transform: whether to apply this instance's transformer (if any)
        :return: a vector
        """
        value = self._f(item)
        if self.transformer is not None and transform:
            value = self.transformer.transform([value])[0]
        return value

    def applyMulti(self, items: Iterable[T], transform=True) -> List[np.array]:
        """
        Applies this vectoriser to multiple items at once.
        Especially for cases where this vectoriser uses a transformer, this method is significantly faster than
        calling apply repeatedly.

        :param items: the items to be vectorised
        :param transform: whether to apply this instance's transformer (if any)
        :return: a list of vectors
        """
        values = [self._f(x) for x in items]
        if self.transformer is not None and transform:
            values = self.transformer.transform(values)
        return values

    class ResultType(Enum):
        SCALAR = 0
        LIST = 1
        NUMPY_ARRAY = 2

        @classmethod
        def fromValue(cls, y):
            if type(y) == list:
                return cls.LIST
            elif np.isscalar(y):
                return cls.SCALAR
            elif isinstance(y, np.ndarray):
                return cls.NUMPY_ARRAY
            else:
                raise ValueError(f"Received unhandled value of type {type(y)}")


class SequenceVectoriser(Generic[T], ToStringMixin):
    """
    Supports the application of Vectorisers to sequences of objects of some type T, where each object of type T is
    mapped to a vector (1D array) by the vectorisers.
    A SequenceVectoriser is fitted by fitting the underlying Vectorisers. In order to obtain the instances of T that
    are used for training, we take into consideration the fact that the sequences of T may overlap and thus training
    is performed on the set of unique instances.
    """
    def __init__(self, vectorisers: Union[Sequence[Vectoriser[T]], Vectoriser[T]]):
        """
        :param vectorisers: one or more vectorisers that are to be applied. If more than one vectoriser is supplied,
            vectors are generated from input instances of type T by concatenating the results of the vectorisers in
            the order the vectorisers are given.
        """
        if isinstance(vectorisers, Vectoriser):
            self.vectorisers = [vectorisers]
        else:
            self.vectorisers = vectorisers

    def _toStringObjectInfo(self) -> str:
        return dictString(dict(vectoriserNames=[v.getName() for v in self.vectorisers]))

    def fit(self, data: Iterable[Sequence[T]]):
        uniqueItems = set()
        for seq in data:
            uniqueItems.update(seq)
        for v in self.vectorisers:
            v.fit(uniqueItems)

    def apply(self, seq: Sequence[T], transform=True) -> List[np.array]:
        """
        Applies vectorisation to the given sequence of objects

        :param seq: the sequence to vectorise
        :param transform: whether to apply any post-vectorisation transformers
        :return:
        """
        vectorsList = []
        for item in seq:
            vectors = [vec.apply(item, transform=transform) for vec in self.vectorisers]
            conc = np.concatenate(vectors, axis=0)
            vectorsList.append(conc)
        return vectorsList

    def applyMulti(self, sequences: Iterable[Sequence[T]]) -> Tuple[List[List[np.array]], List[int]]:
        """
        Applies this vectoriser to multiple sequences of objects of type T, where each sequence is mapped to a sequence
        of 1D arrays.
        This method can be significantly faster than multiple applications of apply, especially in cases where the vectorisers
        use transformers.

        :param sequences: the sequences to vectorise
        :return: a pair (vl, l) where vl is a list of lists of vectors/arrays and l is a list of integers containing the lengths
            of the sequences
        """
        lengths = [len(s) for s in sequences]

        combinedSeq = []
        for seq in sequences:
            combinedSeq.extend(seq)

        individualVectoriserResults = [vectoriser.applyMulti(combinedSeq) for vectoriser in self.vectorisers]
        concVectors = [np.concatenate(x, axis=0) for x in zip(*individualVectoriserResults)]

        vectorSequences = []
        idxStart = 0
        for l in lengths:
            vectorSequences.append(concVectors[idxStart:idxStart+l])
            idxStart += l

        return vectorSequences, lengths

    def applyMultiWithPadding(self, sequences: Sequence[Sequence[T]]) -> Tuple[List[List[np.array]], List[int]]:
        """
        Applies this vectoriser to multiple sequences of objects of type T, where each sequence is mapped to a sequence
        of 1D arrays.
        Sequences are allowed to vary in length. for shorter sequences, 0-vectors are appended until the maximum sequence length
        is reached (padding).

        :param sequences: the sequences to vectorise
        :return: a pair (vl, l) where vl is a list of lists of vectors/arrays, each list having the same length, and l is a list of
            integers containing the original unpadded lengths of the sequences
        """
        result, lengths = self.applyMulti(sequences)
        maxLength = max(lengths)
        dim = len(result[0][0])
        dummyVec = np.zeros((dim,))
        for seq in result:
            for i in range(maxLength - len(seq)):
                seq.append(dummyVec)
        return result, lengths


if __name__ == '__main__':
    def myf(x):
        return np.array([x/2, x*x])

    import sklearn.preprocessing

    items = [1,2,3]
    items2 = [4,5,6,7]
    data = [items, items2]
    vectoriser = Vectoriser(myf, transformer=sklearn.preprocessing.MaxAbsScaler())
    #vectoriser.fit(items)
    #result = vectoriser.apply(items[1])

    svec = SequenceVectoriser([vectoriser, vectoriser])
    svec.fit(data)
    result, lengths = svec.applyMultiWithPadding(data)


class VectoriserRegistry:
    def __init__(self):
        self._factories: Dict[Hashable, Callable[[Callable], Vectoriser]] = {}

    def getAvailableVectorisers(self):
        return list(self._factories.keys())

    @staticmethod
    def _name(name: Hashable):
        # for enums, which have .name, use the name only, because it is less problematic to persist
        if hasattr(name, "name"):
            name = name.name
        return name

    def registerFactory(self, name: Hashable, factory: Callable[[Callable], Vectoriser],
            additionalNames: Optional[Iterable[Hashable]] = None):
        """
        Registers a vectoriser factory which can subsequently be referenced via their name

        :param name: the name (which can, in particular, be a string or an enum item)
        :param factory: the factory, which takes the default transformer factory as an argument
        :param additionalNames: (optional) additional names under which to register the factory
        """
        self._registerFactory(name, factory)
        if additionalNames is not None:
            for n in additionalNames:
                self._registerFactory(n, factory)

    def _registerFactory(self, name: Hashable, factory):
        name = self._name(name)
        if name in self._factories:
            raise ValueError(f"Vectoriser factory for name '{name}' already registered")
        self._factories[name] = factory

    def getVectoriser(self, name: Hashable, defaultTransformerFactory: Callable) -> Vectoriser:
        """
        Creates a vectoriser from a name, which must have been previously registered.

        :param name: the name (which can, in particular, be a string or an enum item)
        :param defaultTransformerFactory: the default transformer factory
        :return: a new vectoriser instance
        """
        name = self._name(name)
        factory = self._factories.get(name)
        if factory is None:
            raise ValueError(f"No factory registered for name '{name}': known names: {listString(self._factories.keys())}. Register the factory first.")
        instance = factory(defaultTransformerFactory)
        instance.setName(name)
        return instance

    def getVectorisers(self, names: List[Hashable], defaultTransformerFactory: Callable) -> List[Vectoriser]:
        return [self.getVectoriser(name, defaultTransformerFactory) for name in names]