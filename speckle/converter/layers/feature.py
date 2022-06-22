from distutils.log import error
from qgis._core import QgsCoordinateTransform, Qgis, QgsPointXY, QgsGeometry, QgsRasterBandStats, QgsFeature, QgsFields, \
    QgsField
from specklepy.objects import Base

from PyQt5.QtCore import QVariant
from speckle.converter import geometry
from speckle.converter.geometry import convertToSpeckle, transform
from speckle.converter.geometry.mesh import rasterToMesh
from speckle.logging import logger
from speckle.converter.layers.utils import getLayerGeomType, getVariantFromValue, getLayerAttributes
from osgeo import (  # # C:\Program Files\QGIS 3.20.2\apps\Python39\Lib\site-packages\osgeo
    gdal, osr)

def featureToSpeckle(fieldnames, f, sourceCRS, targetCRS, project, selectedLayer):
    b = Base()

    #apply transformation if needed
    if sourceCRS != targetCRS:
        xform = QgsCoordinateTransform(sourceCRS, targetCRS, project)
        geometry = f.geometry()
        geometry.transform(xform)
        f.setGeometry(geometry)

    # Try to extract geometry
    try:
        geom = convertToSpeckle(f, selectedLayer)
        #print(geom)
        if geom is not None:
            b["geometry"] = geom
    except Exception as error:
        logger.logToUser("Error converting geometry: " + str(error), Qgis.Critical)

    for name in fieldnames:
        corrected = name.replace("/", "_").replace(".", "-")
        if corrected == "id":
            corrected = "applicationId"
        f_name = str(f[name])
        b[corrected] = f_name
    return b


def rasterFeatureToSpeckle(selectedLayer, projectCRS, project):
    rasterBandCount = selectedLayer.bandCount()
    rasterBandNames = []
    rasterDimensions = [selectedLayer.width(), selectedLayer.height()]
    if rasterDimensions[0]*rasterDimensions[1] > 1000000 :
       logger.logToUser("Large layer: ", Qgis.Warning)

    ds = gdal.Open(selectedLayer.source(), gdal.GA_ReadOnly)
    rasterOriginPoint = QgsPointXY(ds.GetGeoTransform()[0], ds.GetGeoTransform()[3])
    rasterResXY = [ds.GetGeoTransform()[1],ds.GetGeoTransform()[5]]
    rasterBandNoDataVal = []
    rasterBandMinVal = []
    rasterBandMaxVal = []
    rasterBandVals = []

    b = Base()
    # Try to extract geometry
    reprojectedPt = QgsGeometry.fromPointXY(QgsPointXY())
    try:
        reprojectedPt = rasterOriginPoint
        if selectedLayer.crs()!= projectCRS: reprojectedPt = transform.transform(rasterOriginPoint, selectedLayer.crs(), projectCRS)
        pt = QgsGeometry.fromPointXY(reprojectedPt)
        geom = convertToSpeckle(pt, selectedLayer)
        if (geom != None):
            b['displayValue'] = [geom]
    except Exception as error:
        logger.logToUser("Error converting point geometry: " + str(error), Qgis.Critical)

    for index in range(rasterBandCount):
        rasterBandNames.append(selectedLayer.bandName(index+1))
        rb = ds.GetRasterBand(index+1)
        valMin = selectedLayer.dataProvider().bandStatistics(index+1, QgsRasterBandStats.All).minimumValue
        valMax = selectedLayer.dataProvider().bandStatistics(index+1, QgsRasterBandStats.All).maximumValue
        bandVals = rb.ReadAsArray().tolist()

        '''
        ## reduce resolution if needed: 
        if totalValues>max_values : 
            bandVals_resized = [] #list of lists
            factor = 1 #recalculate factor to reach max size
            for i in range(1,20):
                if totalValues/(i*i) <= max_values:
                    factor = i
                    break
            for item in bandVals: #reduce each row and each column
                bandVals_resized = [bandVals]
        '''
        bandValsFlat = []
        [bandValsFlat.extend(item) for item in bandVals]
        #look at mesh chunking
        b["@(10000)" + selectedLayer.bandName(index+1) + "_values"] = bandValsFlat #[0:int(max_values/rasterBandCount)]
        rasterBandVals.append(bandValsFlat)
        rasterBandNoDataVal.append(rb.GetNoDataValue())
        rasterBandMinVal.append(valMin)
        rasterBandMaxVal.append(valMax)

    b["X resolution"] = rasterResXY[0]
    b["Y resolution"] = rasterResXY[1]
    b["X pixels"] = rasterDimensions[0]
    b["Y pixels"] = rasterDimensions[1]
    b["Band count"] = rasterBandCount
    b["Band names"] = rasterBandNames

    # creating a mesh
    vertices = []
    faces = []
    colors = []
    count = 0
    rendererType = selectedLayer.renderer().type()
    #print(rendererType)
    # identify symbology type and if Multiband, which band is which color
    for v in range(rasterDimensions[1] ): #each row, Y
        for h in range(rasterDimensions[0] ): #item in a row, X
            pt1 = QgsPointXY(rasterOriginPoint.x()+h*rasterResXY[0], rasterOriginPoint.y()+v*rasterResXY[1])
            pt2 = QgsPointXY(rasterOriginPoint.x()+h*rasterResXY[0], rasterOriginPoint.y()+(v+1)*rasterResXY[1])
            pt3 = QgsPointXY(rasterOriginPoint.x()+(h+1)*rasterResXY[0], rasterOriginPoint.y()+(v+1)*rasterResXY[1])
            pt4 = QgsPointXY(rasterOriginPoint.x()+(h+1)*rasterResXY[0], rasterOriginPoint.y()+v*rasterResXY[1])
            # first, get point coordinates with correct position and resolution, then reproject each:
            if selectedLayer.crs()!= projectCRS:
                pt1 = transform.transform(src = pt1, crsSrc = selectedLayer.crs(), crsDest = projectCRS)
                pt2 = transform.transform(src = pt2, crsSrc = selectedLayer.crs(), crsDest = projectCRS)
                pt3 = transform.transform(src = pt3, crsSrc = selectedLayer.crs(), crsDest = projectCRS)
                pt4 = transform.transform(src = pt4, crsSrc = selectedLayer.crs(), crsDest = projectCRS)
            vertices.extend([pt1.x(), pt1.y(), 0, pt2.x(), pt2.y(), 0, pt3.x(), pt3.y(), 0, pt4.x(), pt4.y(), 0]) ## add 4 points
            faces.extend([4, count, count+1, count+2, count+3])

            # color vertices according to QGIS renderer
            color = (0<<16) + (0<<8) + 0
            noValColor = selectedLayer.renderer().nodataColor().getRgb()

            if rendererType == "multibandcolor":
                redBand = selectedLayer.renderer().redBand()
                greenBand = selectedLayer.renderer().greenBand()
                blueBand = selectedLayer.renderer().blueBand()
                rVal = 0
                gVal = 0
                bVal = 0
                for k in range(rasterBandCount):
                    #### REMAP band values to (0,255) range
                    valRange = (rasterBandMaxVal[k] - rasterBandMinVal[k])
                    colorVal = int( (rasterBandVals[k][int(count/4)] - rasterBandMinVal[k]) / valRange * 255 )
                    if k+1 == redBand: rVal = colorVal
                    if k+1 == greenBand: gVal = colorVal
                    if k+1 == blueBand: bVal = colorVal
                color =  (rVal<<16) + (gVal<<8) + bVal
                # for missing values (check by 1st band)
                if rasterBandVals[0][int(count/4)] != rasterBandVals[0][int(count/4)]:
                    color = (noValColor[0]<<16) + (noValColor[1]<<8) + noValColor[2]

            elif rendererType == "paletted":
                bandIndex = selectedLayer.renderer().band()-1 #int
                value = rasterBandVals[bandIndex][int(count/4)] #find in the list and match with color

                rendererClasses = selectedLayer.renderer().classes()
                for c in range(len(rendererClasses)-1):
                    if value >= rendererClasses[c].value and value <= rendererClasses[c+1].value :
                        rgb = rendererClasses[c].color.getRgb()
                        color =  (rgb[0]<<16) + (rgb[1]<<8) + rgb[2]
                        break

            elif rendererType == "singlebandpseudocolor":
                bandIndex = selectedLayer.renderer().band()-1 #int
                value = rasterBandVals[bandIndex][int(count/4)] #find in the list and match with color

                rendererClasses = selectedLayer.renderer().legendSymbologyItems()
                for c in range(len(rendererClasses)-1):
                    if value >= float(rendererClasses[c][0]) and value <= float(rendererClasses[c+1][0]) :
                        rgb = rendererClasses[c][1].getRgb()
                        color =  (rgb[0]<<16) + (rgb[1]<<8) + rgb[2]
                        break

            else:
                if rendererType == "singlebandgray":
                    bandIndex = selectedLayer.renderer().grayBand()-1
                if rendererType == "hillshade":
                    bandIndex = selectedLayer.renderer().band()-1
                if rendererType == "contour":
                    try: bandIndex = selectedLayer.renderer().inputBand()-1
                    except:
                        try: bandIndex = selectedLayer.renderer().band()-1
                        except: bandIndex = 0
                else: # e.g. single band data
                    bandIndex = 0
                # REMAP band values to (0,255) range
                valRange = (rasterBandMaxVal[bandIndex] - rasterBandMinVal[bandIndex])
                colorVal = int( (rasterBandVals[bandIndex][int(count/4)] - rasterBandMinVal[bandIndex]) / valRange * 255 )
                color =  (colorVal<<16) + (colorVal<<8) + colorVal

            colors.extend([color,color,color,color])
            count += 4

    mesh = rasterToMesh(vertices, faces, colors)
    if(b['displayValue'] is None):
        b['displayValue'] = []
    b['displayValue'].append(mesh)
    return b


def featureToNative(feature: Base, attrs):
    feat = QgsFeature()
    try: # ignore 'broken' geometry
        try: speckle_geom = feature["geometry"] # for created in QGIS Layer type
        except:  speckle_geom = feature # for created in other software

        if isinstance(speckle_geom, list):
            qgsGeom = geometry.convertToNativeMulti(speckle_geom)
        else:
            qgsGeom = geometry.convertToNative(speckle_geom)

        if qgsGeom is not None:
            feat.setGeometry(qgsGeom)

        #get object properties to add as attributes
        dynamicProps = feature.get_dynamic_member_names()
        try: dynamicProps.remove("geometry")
        except: pass

        try: 
            if feature["applicationId"]: dynamicProps.append("id")
        except: 
            pass
        dynamicProps.sort()


        fields = QgsFields()
        # create fields from existing features
        #attr_names = []
        #for name in attrs:
        #    try: attr_names.append(name.name())
        #    except: attr_names.append(name)

        # add field names from current geometry
        for name in dynamicProps:
            fields.append(QgsField(name)) 
            '''
            try: 
                if name not in attr_names: fields.append(QgsField(name)) 
                else: dynamicProps.remove(name)
                #print(feature[name])
            except: 
                dynamicProps.remove(name)
                pass #print(error)
            '''
        feat.setFields(fields)
        
        for name in dynamicProps:
            value = feature[name]
            if name == "id": 
                try: value = int(feature["applicationId"])
                except: value = None
            feat[name] = value
            #https://qgis.org/pyqgis/master/core/QgsFeature.html#qgis.core.QgsFeature.setAttribute
        
        return feat, dynamicProps
    except:
        return "", []

def cadFeatureToNative(feature: Base, attrs: QgsFields):
    feat = QgsFeature()
    try: # ignore 'broken' geometry
        try: speckle_geom = feature["geometry"] # for created in QGIS Layer type
        except:  speckle_geom = feature # for created in other software

        if isinstance(speckle_geom, list):
            qgsGeom = geometry.convertToNativeMulti(speckle_geom)
        else:
            qgsGeom = geometry.convertToNative(speckle_geom)

        if qgsGeom is not None:
            feat.setGeometry(qgsGeom)

        #get object properties to add as attributes
        dynamicProps = feature.get_dynamic_member_names()
        try: dynamicProps.remove("geometry")
        except: pass

        try: 
            if feature["applicationId"]: dynamicProps.append("id")
        except: pass
        dynamicProps.sort()

        # add existing fields
        fields = QgsFields()
        for a in attrs.toList(): # should be QgsField
            fields.append(a) 

        # add new field names from current geometry  
        # and make an attribute list to pass for layer creation
        for name in dynamicProps:
            if name not in attrs.names(): 

                variant = getVariantFromValue(feature[name])
                if variant: 
                    if name == "id": fields.append( QgsField(name, QVariant.Int) )
                    else: fields.append( QgsField(name, variant) )
                else: fields.append( QgsField(name, QVariant.String) )

        # assign fields and their values to the feature
        feat.setFields(fields)
        for f in fields.toList():
        #for name in dynamicProps:
            try: value = feature[f.name()]
            except: value = None
            if name == "id": 
                try: value = int(feature["applicationId"])
                except: value = None
            feat[f.name()] = value
            #https://qgis.org/pyqgis/master/core/QgsFeature.html#qgis.core.QgsFeature.setAttribute
        
        return feat, fields
    except:
        return "", []