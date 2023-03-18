# -*- coding: utf-8 -*-
"""
/***************************************************************************
 SpeckleQGIS
                                 A QGIS plugin
 SpeckleQGIS Description
 Generated by Plugin Builder: https://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2021-08-04
        git sha              : $Format:%H$
        copyright            : (C) 2021 by Speckle Systems
        email                : alan@speckle.systems
 ***************************************************************************/
"""


import inspect
import os.path
import sys
import time 
from typing import Any, Callable, List, Optional, Tuple, Union

import threading
from qgis.core import (Qgis, QgsProject, QgsLayerTreeLayer,
                       QgsRasterLayer, QgsVectorLayer)
from qgis.PyQt.QtCore import QCoreApplication, QSettings, Qt, QTranslator, QRect 
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QApplication, QAction, QDockWidget, QVBoxLayout, QWidget
from qgis.PyQt import QtWidgets
from qgis import PyQt
import sip

from specklepy.api import operations
from specklepy.logging.exceptions import SpeckleException, GraphQLException
#from specklepy.api.credentials import StreamWrapper
from specklepy.api.models import Stream
from specklepy.api.wrapper import StreamWrapper
from specklepy.objects import Base
from specklepy.transports.server import ServerTransport
from specklepy.api.credentials import Account, get_local_accounts #, StreamWrapper
from specklepy.api.client import SpeckleClient
from specklepy.logging import metrics
import webbrowser

# Initialize Qt resources from file resources.py
from resources import *
from plugin_utils.object_utils import callback, traverseObject
from speckle.converter.layers.Layer import Layer, VectorLayer, RasterLayer
from speckle.converter.layers import convertSelectedLayers, getLayers
from speckle.converter.layers.utils import findAndClearLayerGroup

from speckle.logging import logger
from ui.add_stream_modal import AddStreamModalDialog
from ui.create_stream import CreateStreamModalDialog
from ui.create_branch import CreateBranchModalDialog
from ui.logger import logToUser, logToUserWithAction

# Import the code for the dialog
from ui.validation import tryGetStream, validateBranch, validateCommit, validateStream, validateTransport 


SPECKLE_COLOR = (59,130,246)
SPECKLE_COLOR_LIGHT = (69,140,255)

class SpeckleQGIS:
    """Speckle Connector Plugin for QGIS"""

    dockwidget: Optional[QDockWidget]
    add_stream_modal: AddStreamModalDialog
    create_stream_modal: CreateStreamModalDialog
    current_streams: List[Tuple[StreamWrapper, Stream]]  #{id:(sw,st),id2:()}
    current_layers: List[Tuple[str, Union[QgsVectorLayer, QgsRasterLayer]]] = []

    active_stream: Optional[Tuple[StreamWrapper, Stream]] 

    qgis_project: QgsProject

    lat: float
    lon: float

    default_account: Account
    accounts: List[Account]
    active_account: Account

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.dockwidget = None
        self.iface = iface
        self.qgis_project = QgsProject.instance()
        self.current_streams = []
        self.active_stream = None
        self.default_account = None 
        self.accounts = [] 
        self.active_account = None 

        self.btnAction = 0

        self.lat = 0.0
        self.lon = 0.0
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value("locale/userLocale")[0:2]
        locale_path = os.path.join(
            self.plugin_dir, "i18n", "SpeckleQGIS_{}.qm".format(locale)
        )

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr("&SpeckleQGIS")

        # Check if plugin was started the first time in current QGIS session
        # Must be set in initGui() to survive plugin reloads
        self.pluginIsActive = False

    # noinspection PyMethodMayBeStatic

    def tr(self, message: str):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate("SpeckleQGIS", message)

    def add_action(
        self,
        icon_path: str,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None,
    ):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            # Adds plugin icon to Plugins toolbar
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToWebMenu(self.menu, action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ":/plugins/speckle_qgis/icon.png"
        self.add_action(
            icon_path,
            text=self.tr("SpeckleQGIS"),
            callback=self.run,
            parent=self.iface.mainWindow(),
        )

    def onClosePlugin(self):
        """Cleanup necessary items here when plugin dockwidget is closed"""

        # disconnects
        if self.dockwidget:
            try: self.dockwidget.closingPlugin.disconnect(self.onClosePlugin)
            except: pass 

        # remove this statement if dockwidget is to remain
        # for reuse if plugin is reopened
        # Commented next statement since it causes QGIS crashe
        # when closing the docked window:
        # self.dockwidget = None

        self.pluginIsActive = False
        self.dockwidget.close()

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        try:
            for action in self.actions:
                self.iface.removePluginWebMenu(self.tr("&SpeckleQGIS"), action)
                self.iface.removeToolBarIcon(action)
        except Exception as e:
            logToUser(e, level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)
            return

    def onRunButtonClicked(self):
        
        # set the project instance 
        self.qgis_project = QgsProject.instance()

        # send 
        if self.btnAction == 0: 
            
            # Reset Survey point
            self.dockwidget.populateSurveyPoint(self)
            
            # Get and clear message
            message = str(self.dockwidget.messageInput.text())
            self.dockwidget.messageInput.setText("")
            
            if not self.dockwidget.experimental.isChecked(): self.onSend(message)
            else:
                try:
                    streamWrapper = self.active_stream[0]
                    client = streamWrapper.get_client()
                    self.active_account = client.account
                    metrics.track("Connector Action", self.active_account, {"name": "Toggle Multi-threading Send"})
                    
                    t = threading.Thread(target=self.onSend, args=(message,))
                    t.start()
                except: self.onSend(message)
        # receive 
        elif self.btnAction == 1: 
            if not self.dockwidget.experimental.isChecked(): self.onReceive()
            else:
                try:
                    streamWrapper = self.active_stream[0]
                    client = streamWrapper.get_client()
                    self.active_account = client.account
                    metrics.track("Connector Action", self.active_account, {"name": "Toggle Multi-threading Receive"})

                    t = threading.Thread(target=self.onReceive, args=())
                    t.start()
                except: self.onReceive()

    def onSend(self, message):
        """Handles action when Send button is pressed."""
        #logToUser("Some message here", level = 0, func = inspect.stack()[0][3], plugin=self.dockwidget )
        try: 
            if not self.dockwidget: return
            #self.dockwidget.showWait()
            
            projectCRS = self.qgis_project.crs()

            bySelection = True
            if self.dockwidget.layerSendModeDropdown.currentIndex() == 1: 
                bySelection = False 
            layers = getLayers(self, bySelection) # List[QgsLayerTreeNode]

            # Check if stream id/url is empty
            if self.active_stream is None:
                logToUser("Please select a stream from the list", level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget )
                return
            
            # Check if no layers are selected
            if len(layers) == 0: #len(selectedLayerNames) == 0:
                logToUser("No layers selected", level = 1, func = inspect.stack()[0][3], plugin=self.dockwidget)
                return

            base_obj = Base(units = "m")
            base_obj.layers = convertSelectedLayers(layers, [],[], projectCRS, self.qgis_project)
            if base_obj.layers is None:
                return 

            # Get the stream wrapper
            streamWrapper = self.active_stream[0]
            streamName = self.active_stream[1].name
            streamId = streamWrapper.stream_id
            client = streamWrapper.get_client()

            stream = validateStream(streamWrapper)
            if stream == None: 
                return
            
            branchName = str(self.dockwidget.streamBranchDropdown.currentText())
            branch = validateBranch(stream, branchName, False)
            if branch == None: 
                return

            transport = validateTransport(client, streamId)
            if transport == None: 
                return
        
        except Exception as e:
            logToUser(e, level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)
            return

        try:
            # this serialises the block and sends it to the transport
            objId = operations.send(base=base_obj, transports=[transport])
        except SpeckleException as e:
            logToUser("Error sending data: " + str(e.message), level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)
            return

        #logToUser("long errror something something msg1", level=2, plugin= self.dockwidget)
        try:
            # you can now create a commit on your stream with this object
            commit_id = client.commit.create(
                stream_id=streamId,
                object_id=objId,
                branch_name=branchName,
                message="Sent objects from QGIS" if len(message) == 0 else message,
                source_application="QGIS",
            )
            url: str = streamWrapper.stream_url.split("?")[0] + "/commits/" + commit_id
            
            #self.dockwidget.hideWait()
            #self.dockwidget.showLink(url, streamName)
            time.sleep(1)
            logToUserWithAction(f"👌 Data sent to \"{streamName}\" \n View it online", level = 0, plugin=self.dockwidget, url = url)

            return url

        except Exception as e:
            time.sleep(1)
            logToUser("Error creating commit: "+str(e), level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)

    def onReceive(self):
        """Handles action when the Receive button is pressed"""
        print("Receive")
        try:
            if not self.dockwidget: return
            # Check if stream id/url is empty
            if self.active_stream is None:
                logToUser("Please select a stream from the list", level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)
                return
            
            # Get the stream wrapper
            streamWrapper = self.active_stream[0]
            streamId = streamWrapper.stream_id
            client = streamWrapper.get_client()
        except Exception as e:
            logToUser(e, level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)
            return

        # Ensure the stream actually exists
        try:
            stream = validateStream(streamWrapper)
            if stream == None: 
                return
            
            branchName = str(self.dockwidget.streamBranchDropdown.currentText())
            branch = validateBranch(stream, branchName, True)
            if branch == None: 
                return

            commitId = str(self.dockwidget.commitDropdown.currentText())
            commit = validateCommit(branch, commitId)
            if commit == None: 
                return

        except Exception as e:
            logToUser(str(e), level = 2, func = inspect.stack()[0][3], plugin = self.dockwidget)
            return

        try:
            transport = validateTransport(client, streamId)
            if transport == None: 
                return 
            
            objId = commit.referencedObject
            #commitDetailed = client.commit.get(streamId, commit.id)
            app = commit.sourceApplication
            if branch.name is None or commit.id is None or objId is None: 
                return 

            commitObj = operations.receive(objId, transport, None)

            client.commit.received(
            streamId,
            commit.id,
            source_application="QGIS",
            message="Received commit in QGIS",
            )

            if app != "QGIS" and app != "ArcGIS": 
                if self.qgis_project.crs().isGeographic() is True or self.qgis_project.crs().isValid() is False: 
                    logToUser("Conversion from metric units to DEGREES not supported. It is advisable to set the project CRS to Projected type before receiving CAD geometry (e.g. EPSG:32631), or create a custom one from geographic coordinates", level = 1, func = inspect.stack()[0][3], plugin = self.dockwidget)
            #logger.log(f"Succesfully received {objId}")

            # If group exists, remove layers inside  
            newGroupName = streamId + "_" + branch.name + "_" + commit.id
            findAndClearLayerGroup(self.qgis_project, newGroupName)

            if app == "QGIS" or app == "ArcGIS": check: Callable[[Base], bool] = lambda base: isinstance(base, VectorLayer) or isinstance(base, Layer) or isinstance(base, RasterLayer)
            else: check: Callable[[Base], bool] = lambda base: isinstance(base, Base)
            traverseObject(self, commitObj, callback, check, str(newGroupName))
            
            time.sleep(1)
            logToUser("👌 Data received", level = 0, plugin = self.dockwidget, blue = True)
            return 
            
        except Exception as e:
            time.sleep(1)
            logToUser("Receive failed: "+ str(e), level = 2, func = inspect.stack()[0][3], plugin = self.dockwidget)
            return

    def reloadUI(self):
        print("___RELOAD UI")
        try:
            from ui.project_vars import get_project_streams, get_survey_point, get_project_layer_selection

            self.is_setup = self.check_for_accounts()
            if self.dockwidget is not None:
                self.active_stream = None
                get_project_streams(self)
                get_survey_point(self)
                get_project_layer_selection(self)

                self.dockwidget.reloadDialogUI(self)
        except Exception as e:
            logToUser(e, level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)
            return

    def check_for_accounts(self):
        try:
            def go_to_manager():
                webbrowser.open("https://speckle-releases.netlify.app/")
            accounts = get_local_accounts()
            self.accounts = accounts
            if len(accounts) == 0:
                logToUser("No accounts were found. Please remember to install the Speckle Manager and setup at least one account", level = 1, func = inspect.stack()[0][3], plugin = self.dockwidget) #, action_text="Download Manager", callback=go_to_manager)
                return False
            for acc in accounts:
                if acc.isDefault: 
                    self.default_account = acc 
                    self.active_account = acc 
                    break 
            return True
        except Exception as e:
            logToUser(e, level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)
            return

    def run(self):
        """Run method that performs all the real work"""
        from ui.speckle_qgis_dialog import SpeckleQGISDialog
        from ui.project_vars import get_project_streams, get_survey_point, get_project_layer_selection

        # Create the dialog with elements (after translation) and keep reference
        # Only create GUI ONCE in callback, so that it will only load when the plugin is started
        self.is_setup = self.check_for_accounts()
            
        if self.pluginIsActive:
            self.reloadUI()
        else:
            self.pluginIsActive = True
            if self.dockwidget is None:
                self.dockwidget = SpeckleQGISDialog()
                self.qgis_project.fileNameChanged.connect(self.reloadUI)
                self.qgis_project.homePathChanged.connect(self.reloadUI)

            get_project_streams(self)
            get_survey_point(self)
            get_project_layer_selection(self)

            self.dockwidget.run(self)

            # Setup reload of UI dropdowns when layers change.
            #layerRoot = QgsProject.instance()
            #layerRoot.layersAdded.connect(self.reloadUI)
            #layerRoot.layersRemoved.connect(self.reloadUI)

            # show the dockwidget
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)
            self.dockwidget.enableElements(self)

    def onStreamAddButtonClicked(self):
        try:
            self.add_stream_modal = AddStreamModalDialog(None)
            self.add_stream_modal.handleStreamAdd.connect(self.handleStreamAdd)
            self.add_stream_modal.show()
        except Exception as e:
            logToUser(e, level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)
            return

    def set_survey_point(self): 
        try:
            from ui.project_vars import set_survey_point
            set_survey_point(self)
        except Exception as e:
            logToUser(e, level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)
            return

    def onStreamCreateClicked(self):
        try:
            self.create_stream_modal = CreateStreamModalDialog(None)
            self.create_stream_modal.handleStreamCreate.connect(self.handleStreamCreate)
            #self.create_stream_modal.handleCancelStreamCreate.connect(lambda: self.dockwidget.populateProjectStreams(self))
            self.create_stream_modal.show()
        except Exception as e:
            logToUser(e, level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)
            return
    
    def handleStreamCreate(self, account, str_name, description, is_public): 
        try:
            new_client = SpeckleClient(
                account.serverInfo.url,
                account.serverInfo.url.startswith("https")
            )
            new_client.authenticate_with_token(token=account.token)

            str_id = new_client.stream.create(name=str_name, description = description, is_public = is_public) 
            if isinstance(str_id, GraphQLException) or isinstance(str_id, SpeckleException):
                logToUser(str_id.message, level = 2, plugin = self.dockwidget)
                return
            else:
                sw = StreamWrapper(account.serverInfo.url + "/streams/" + str_id)
                self.handleStreamAdd(sw)
            return 
        except Exception as e:
            logToUser(e, level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)
            return

    def onBranchCreateClicked(self):
        try:
            self.create_stream_modal = CreateBranchModalDialog(None)
            self.create_stream_modal.handleBranchCreate.connect(self.handleBranchCreate)
            self.create_stream_modal.show()
        except Exception as e:
            logToUser(e, level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)
            return
    
    def handleBranchCreate(self, br_name, description):
        try: 
            br_name = br_name.lower()
            sw: StreamWrapper = self.active_stream[0]
            account = sw.get_account()
            new_client = SpeckleClient(
                account.serverInfo.url,
                account.serverInfo.url.startswith("https")
            )
            new_client.authenticate_with_token(token=account.token)
            #description = "No description provided"
            br_id = new_client.branch.create(stream_id = sw.stream_id, name = br_name, description = description) 
            if isinstance(br_id, GraphQLException):
                logToUser(br_id.message, level = 1, plugin = self.dockwidget)

            self.active_stream = (sw, tryGetStream(sw))
            self.current_streams[0] = self.active_stream

            self.dockwidget.populateActiveStreamBranchDropdown(self)
            self.dockwidget.populateActiveCommitDropdown(self)
            self.dockwidget.streamBranchDropdown.setCurrentText(br_name) # will be ignored if branch name is not in the list 

            return 
        except Exception as e:
            logToUser(e, level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)
            return

    def handleStreamAdd(self, sw: StreamWrapper):
        try: 
            from ui.project_vars import set_project_streams
            
            streamExists = 0
            index = 0

            stream = tryGetStream(sw)
            
            for st in self.current_streams: 
                #if isinstance(st[1], SpeckleException) or isinstance(stream, SpeckleException): pass 
                if isinstance(stream, Stream) and st[0].stream_id == stream.id: 
                    streamExists = 1; 
                    break 
                index += 1
        except SpeckleException as e:
            logToUser(e.message, level = 1, plugin=self.dockwidget)
            stream = None
        
        try: 
            if streamExists == 0: 
                self.current_streams.insert(0,(sw, stream))
            else: 
                del self.current_streams[index]
                self.current_streams.insert(0,(sw, stream))
            try: self.add_stream_modal.handleStreamAdd.disconnect(self.handleStreamAdd)
            except: pass 
            set_project_streams(self)
            self.dockwidget.populateProjectStreams(self)
        except Exception as e:
            logToUser(e, level = 2, func = inspect.stack()[0][3], plugin=self.dockwidget)
            return
