from typing import Any, Dict, List, Optional
from specklepy.objects.base import Base
from specklepy.objects.other import Collection

from speckle.converter.layers.CRS import CRS
from deprecated import deprecated

class Layer(Base, detachable={"features"}):
    """A GIS Layer"""

    def __init__(
        self,
        name:str=None,
        crs:CRS=None,
        units: str = "m",
        features: Optional[List[Base]] = None,
        layerType: str = "None",
        geomType: str = "None",
        renderer: Optional[dict[str, Any]] = None,
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.name = name
        self.crs = crs
        self.units = units
        self.type = layerType
        self.features = features or []
        self.geomType = geomType
        self.renderer = renderer or {} 

class VectorLayer(Collection, detachable={"elements"}, speckle_type="Objects.GIS.VectorLayer", serialize_ignore={"features"}):
    """A GIS Layer"""

    def __init__(
        self,
        #name: str=None,
        crs: CRS=None,
        units: Optional[str] = None,
        elements: Optional[List[Base]] = None,
        attributes: Optional[Base] = None,
        #layerType: str = "None",
        geomType: str = "None",
        renderer: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        #self.name = name
        self.crs = crs
        self.units = units
        #self.type = layerType
        self.elements = elements or []
        self.attributes = attributes
        self.geomType = geomType
        self.renderer = renderer or {}
        self.collectionType = "VectorLayer"
        self.name = "VectorLayer"
    
    @property
    @deprecated(version="2.14", reason="Use elements")
    def features(self) -> Optional[List[Base]]:
        return self.elements

    @features.setter
    def features(self, value: Optional[List[Base]]) -> None:
        self.elements = value

class RasterLayer(Collection, detachable={"elements"}, speckle_type="Objects.GIS.RasterLayer", serialize_ignore={"features"}):
    """A GIS Layer"""

    def __init__(
        self,
        #name: str=None,
        crs: CRS=None,
        units: Optional[str] = None,
        rasterCrs: CRS=None,
        elements: Optional[List[Base]] = None,
        #layerType: str = "None",
        geomType: str = "None",
        renderer: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        #self.name = name
        self.crs = crs
        self.units = units
        self.rasterCrs = rasterCrs
        #self.type = layerType
        self.elements = elements or []
        self.geomType = geomType
        self.renderer = renderer or {}
        self.collectionType = "RasterLayer"
        self.name = "RasterLayer"
    
    @property
    @deprecated(version="2.14", reason="Use elements")
    def features(self) -> Optional[List[Base]]:
        return self.elements

    @features.setter
    def features(self, value: Optional[List[Base]]) -> None:
        self.elements = value

@deprecated(version="2.14")
class oldRasterLayer(RasterLayer, speckle_type = "RasterLayer"): 
    pass

@deprecated(version="2.14")
class oldVectorLayer(VectorLayer, speckle_type = "VectorLayer"): 
    pass
