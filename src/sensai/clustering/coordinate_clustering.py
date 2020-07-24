import logging
from typing import Callable, Union, Iterable

import geopandas as gp
import numpy as np
from shapely.geometry import MultiPoint

from .base.clustering import ClusteringModel, SKLearnTypeClusterer, SKLearnClusteringModel
from ..base.interfaces import GeoDataFrameWrapper, LoadSaveInterface
from ..util.coordinates import validateCoordinates, coordinatesFromGeoDF
from ..util.tracking import timeit


log = logging.getLogger(__name__)


class CoordinateClusteringModel(ClusteringModel, GeoDataFrameWrapper):
    """
    Wrapper around a clustering model. This class adds additional, geospatial-specific features to the provided
    clusterer

    :param clusterer: an instance of ClusteringModel
    """
    def __init__(self, clusterer: ClusteringModel):
        self.clusterer = clusterer
        super().__init__(noiseLabel=clusterer.noiseLabel,
            maxClusterSize=clusterer.maxClusterSize, minClusterSize=clusterer.minClusterSize)

    class Cluster(ClusteringModel.Cluster, GeoDataFrameWrapper, LoadSaveInterface):
        """
        Wrapper around a coordinates array

        :param coordinates:
        :param identifier:
        """

        def __init__(self, coordinates: np.ndarray, identifier: Union[str, int]):
            validateCoordinates(coordinates)
            super().__init__(coordinates, identifier)

        def toGeoDF(self, crs='epsg:3857'):
            """
            Export the cluster as a GeoDataFrame of length 1 with the cluster as an instance of
            MultiPoint and the identifier as index.

            :param crs: projection. By default pseudo-mercator
            :return: GeoDataFrame
            """
            gdf = gp.GeoDataFrame({"geometry": [self.asMultipoint()]}, index=[self.identifier])
            gdf.index.name = "identifier"
            gdf.crs = crs
            return gdf

        def asMultipoint(self):
            """
            :return: The cluster's coordinates as a MultiPoint object
            """
            return MultiPoint(self.datapoints)

        @classmethod
        def load(cls, path):
            """
            Instantiate from a geopandas readable file containing a single row with an identifier and an instance
            of MultiPoint

            :param path:
            :return: instance of CoordinateCluster
            """
            log.info(f"Loading instance of {cls.__name__} from {path}")
            gdf = gp.read_file(path)
            if len(gdf) != 1:
                raise Exception(f"Expected {path} to contain a single row, instead got {len(gdf)}")
            identifier, multipoint = gdf.identifier.values[0], gdf.geometry.values[0]
            return cls(np.array([[p.x, p.y] for p in multipoint]), identifier)

        def save(self, path, crs="EPSG:3857"):
            """
            Saves the cluster's coordinates as shapefile

            :param crs:
            :param path:
            :return:
            """
            log.info(f"Saving instance of {self.__class__.__name__} as shapefile to {path}")
            self.toGeoDF(crs).to_file(path, index=True)

    def _fit(self, x: np.ndarray) -> None:
        validateCoordinates(x)
        self.clusterer._fit(x)

    def _getLabels(self) -> np.ndarray:
        return self.clusterer._getLabels()

    def fit(self, data: Union[np.ndarray, gp.GeoDataFrame, MultiPoint]):
        """
        Fitting to coordinates from a numpy array, a MultiPoint object or a GeoDataFrame with one Point per row

        :param data:
        :return:
        """
        if isinstance(data, gp.GeoDataFrame):
            data = coordinatesFromGeoDF(data)
        if isinstance(data, MultiPoint):
            data = np.array(data)
        super().fit(data)

    @timeit
    def toGeoDF(self, condition: Callable[[Cluster], bool] = None, crs='epsg:3857',
            includeNoise=False) -> gp.GeoDataFrame:
        """
        GeoDataFrame containing all clusters found by the model.
        It is a concatenation of GeoDataFrames of individual clusters

        :param condition: if provided, only clusters fulfilling the condition will be included
        :param crs: projection. By default pseudo-mercator
        :param includeNoise:
        :return: GeoDataFrame with all clusters indexed by their identifier
        """
        gdf = gp.GeoDataFrame()
        gdf.crs = crs
        # TODO or not TODO: parallelize this or improve performance some another way
        for cluster in self.clusters(condition):
            gdf = gdf.append(cluster.toGeoDF(crs=crs))
        if includeNoise:
            gdf = gdf.append(self.noiseCluster().toGeoDF(crs=crs))
        return gdf

    def plot(self, includeNoise=False, condition=None, **kwargs):
        """
        Plots the resulting clusters with random coloring

        :param includeNoise: Whether to include the noise cluster
        :param condition: If provided, only clusters fulfilling this condition will be included
        :param kwargs: passed to GeoDataFrame.plot
        :return:
        """
        gdf = self.toGeoDF(condition=condition, includeNoise=includeNoise)
        gdf["color"] = np.random.random(len(gdf))
        if includeNoise:
            gdf.loc[self.noiseLabel, "color"] = 0
        gdf.plot(column="color", **kwargs)

    # the overriding of the following methods is only necessary for getting the type annotations right
    # if mypy ever permits annotating nested classes correctly, these methods can be removed
    def getCluster(self, clusterId: int) -> Cluster:
        return super().getCluster(clusterId)

    def noiseCluster(self) -> Cluster:
        return super().noiseCluster()

    def clusters(self, condition: Callable[[Cluster], bool] = None) -> Iterable[Cluster]:
        return super().clusters()


class SKLearnCoordinateClustering(CoordinateClusteringModel):
    """
    Wrapper around a sklearn clusterer. This class adds additional features like relabelling and convenient methods
    for handling geospatial data

    :param clusterer: a clusterer object compatible the sklearn API
    :param noiseLabel: label that is associated with the noise cluster or None
    :param minClusterSize: if not None, clusters below this size will be labeled as noise
    :param maxClusterSize: if not None, clusters above this size will be labeled as noise
    """
    def __init__(self, clusterer: SKLearnTypeClusterer, noiseLabel=-1,
            minClusterSize: int = None, maxClusterSize: int = None):
        clusterer = SKLearnClusteringModel(clusterer, noiseLabel=noiseLabel,
                           minClusterSize=minClusterSize, maxClusterSize=maxClusterSize)
        super().__init__(clusterer)
