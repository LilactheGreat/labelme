import functools
import os
import os.path as osp
import re
import webbrowser
import subprocess
import platform
import qdarkstyle
import requests
import math
import imgviz
import sys
from distutils.version import StrictVersion

from qtpy import QtCore
from qtpy.QtCore import Qt
from qtpy import QtGui
from qtpy import QtWidgets
from qtpy import uic

from itertools import zip_longest

from enhancedlabelme import __appname__
from enhancedlabelme import __version__
from enhancedlabelme import PY2
from enhancedlabelme import QT5

from datetime import datetime

from . import utils
from enhancedlabelme.config import get_config
from enhancedlabelme.label_file import LabelFile
from enhancedlabelme.label_file import LabelFileError
from enhancedlabelme.logger import logger
from enhancedlabelme.shape import Shape
from enhancedlabelme.widgets import BrightnessContrastDialog
from enhancedlabelme.widgets import Canvas
from enhancedlabelme.widgets import LabelDialog
from enhancedlabelme.widgets import LabelListWidget
from enhancedlabelme.widgets import LabelListWidgetItem
from enhancedlabelme.widgets import ToolBar
from enhancedlabelme.widgets import UniqueLabelQListWidget
from enhancedlabelme.widgets import ZoomWidget


# FIXME
# - [medium] Set max zoom value to something big enough for FitWidth/Window

# TODO(unknown):
# - [high] Add polygon movement with arrow keys
# - [high] Deselect shape when clicking and already selected(?)
# - [low,maybe] Preview images on file dialogs.
# - Zoom is too "steppy".


LABEL_COLORMAP = imgviz.label_colormap(value=200)
os.environ['QT_API'] = 'pyqt5'

class PenStyleWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(PenStyleWindow, self).__init__(parent)
        self.penColor = parent.canvas.penColor
        self.penThickness = parent.canvas.penThickness
        self.penStyle = parent.canvas.penStyle
        
        # Import .ui forms for the GUI using function resource_path()
        # self.penOptionForm = self.resource_path("enhancedlabelme/ui/penstylewindow.ui")
        self.initUI(parent)

    # Define function to import external files when using PyInstaller.
    def resource_path(self, relative_path):
        """ Get absolute path to resource, works for dev and for PyInstaller """
        try:
            # PyInstaller creates a temp folder and stores path in _MEIPASS
            base_path = sys._MEIPASS
        except Exception:
            base_path = osp.abspath(".")

        return osp.join(base_path, relative_path)


    def initUI(self, parent):
        option_ui = osp.join(osp.dirname(osp.realpath(__file__)), 'ui/penstylewindow.ui')
        uic.loadUi(option_ui, self)
        # uic.loadUi(self.penOptionForm, self)
        
        # Load current style
        self.horizontalSlider_thickness.setSliderPosition(self.penThickness * 10)
        
        if self.penColor == QtCore.Qt.black:
            self.comboBox_color.setCurrentIndex(0)
        elif self.penColor == QtCore.Qt.white:
            self.comboBox_color.setCurrentIndex(1)
        elif self.penColor == QtCore.Qt.gray:
            self.comboBox_color.setCurrentIndex(2)
        elif self.penColor == QtCore.Qt.red:
            self.comboBox_color.setCurrentIndex(3)
        elif self.penColor == QtCore.Qt.yellow:
            self.comboBox_color.setCurrentIndex(4)
        elif self.penColor == QtCore.Qt.green:
            self.comboBox_color.setCurrentIndex(5)
        elif self.penColor == QtCore.Qt.blue:
            self.comboBox_color.setCurrentIndex(6)
        elif self.penColor == QtCore.Qt.cyan:
            self.comboBox_color.setCurrentIndex(7)
        elif self.penColor == QtCore.Qt.magenta:
            self.comboBox_color.setCurrentIndex(8)        
        
        if self.penStyle == QtCore.Qt.SolidLine:
            self.comboBox_shape.setCurrentIndex(0)
        elif self.penStyle == QtCore.Qt.DashLine:
            self.comboBox_shape.setCurrentIndex(1)
        elif self.penStyle == QtCore.Qt.DotLine:
            self.comboBox_shape.setCurrentIndex(2)     
        
        self.comboBox_shape.activated[str].connect(self.saveShape)
        self.comboBox_color.activated[str].connect(self.saveColor)
        self.horizontalSlider_thickness.valueChanged.connect(self.saveThickness)
        self.buttonBox_cross.accepted.connect(functools.partial(self.saveSettings, parent))
        self.setWindowTitle('Cross-line Style Configuration')
        self.show()
        
    def paintEvent(self, event):
        qp = QtGui.QPainter()
        qp.begin(self)
        self.drawLines(qp)
        qp.end()
        
    def drawLines(self, qp):
        pen = QtGui.QPen(self.penColor, self.penThickness, self.penStyle)
        qp.setPen(pen)
        qp.drawLine(50, 170, 250, 170)
        
    def saveShape(self, value):
        if value == 'SolidLine':
            self.penStyle = QtCore.Qt.SolidLine
        elif value == 'DashLine':
            self.penStyle = QtCore.Qt.DashLine
        elif value == 'DotLine':
            self.penStyle = QtCore.Qt.DotLine
        self.repaint()
        
    def saveColor(self, value):
        if value == 'Black':
            self.penColor = QtCore.Qt.black
        elif value == 'White':
            self.penColor = QtCore.Qt.white
        elif value == 'gray':
            self.penColor = QtCore.Qt.gray
        elif value == 'Red':
            self.penColor = QtCore.Qt.red
        elif value == 'Yellow':
            self.penColor = QtCore.Qt.yellow
        elif value == 'Green':
            self.penColor = QtCore.Qt.green
        elif value == 'Blue':
            self.penColor = QtCore.Qt.blue
        elif value == 'Cyan':
            self.penColor = QtCore.Qt.cyan
        elif value == 'Pink':
            self.penColor = QtCore.Qt.magenta
        self.repaint()
        
    def saveThickness(self, value):
        value = float(value / 10)
        self.penThickness = value
        self.repaint()
    
    def saveSettings(self, parent):
        parent.canvas.penColor = self.penColor
        parent.canvas.penThickness = self.penThickness 
        parent.canvas.penStyle = self.penStyle
        with open(osp.join(osp.dirname(osp.realpath(__file__)), 'widgets/crossSave.txt'), 'w', encoding='utf-8') as f:
            f.write(str(self.penStyle)+'\n')
            f.write(str(self.penThickness)+'\n')
            f.write(str(self.penColor)+'\n')    
        
class MainWindow(QtWidgets.QMainWindow):

    FIT_WINDOW, FIT_WIDTH, MANUAL_ZOOM = 0, 1, 2

    def __init__(
        self,
        config=None,
        filename=None,
        tempfilename=None,
        output=None,
        output_file=None,
        output_dir=None,
    ):
        if output is not None:
            logger.warning(
                'argument output is deprecated, use output_file instead'
            )
            if output_file is None:
                output_file = output
        
        # see labelme/config/default_config.yaml for valid configuration
        if config is None:
            config = get_config()
        self._config = config

        super(MainWindow, self).__init__()
        self.setWindowTitle(__appname__ + ' ' + __version__)

        # Whether we need to save or not.
        self.dirty = False

        self._noSelectionSlot = False

        # Main widgets and related state.
        self.labelDialog = LabelDialog(
            parent=self,
            labels=self._config['labels'],
            sort_labels=self._config['sort_labels'],
            show_text_field=self._config['show_label_text_field'],
            completion=self._config['label_completion'],
            fit_to_content=self._config['fit_to_content'],
            flags=self._config['label_flags']
        )

        self.labelList = LabelListWidget()
        self.lastOpenDir = None

        self.loadTime = str(datetime.now())

        self.flag_dock = self.flag_widget = None
        self.flag_dock = QtWidgets.QDockWidget(self.tr('Flags'), self)
        self.flag_dock.setObjectName('Flags')
        self.flag_widget = QtWidgets.QListWidget()
        if config['flags']:
            self.loadFlags({k: False for k in config['flags']})
        self.flag_dock.setWidget(self.flag_widget)
        self.flag_widget.itemChanged.connect(self.setDirty)




        #self.labelList.itemActivated.connect(self.labelSelectionChanged)
        self.labelList.itemSelectionChanged.connect(self.labelSelectionChanged)
        self.labelList.itemDoubleClicked.connect(self.editLabel)
        # Connect to itemChanged to detect checkbox changes.
        self.labelList.itemChanged.connect(self.labelItemChanged)
        self.labelList.itemDropped.connect(self.labelOrderChanged)
        self.labelList.setDragDropMode(
           QtWidgets.QAbstractItemView.InternalMove)
        self.labelList.setParent(self)
        self.shape_dock = QtWidgets.QDockWidget(
            self.tr('Polygon Labels'),
            self
        )
        self.shape_dock.setObjectName('Labels')
        self.shape_dock.setWidget(self.labelList)




        self.uniqLabelList = UniqueLabelQListWidget()
        self.uniqLabelList.setToolTip(self.tr(
            "Select label to start annotating for it. "
            "Press 'Esc' to deselect."))
        if self._config['labels']:
            for label in self._config["labels"]:
                item = self.uniqLabelList.createItemFromLabel(label)
                self.uniqLabelList.addItem(item)
                rgb = self._get_rgb_by_label(label)
                self.uniqLabelList.setItemLabel(item, label, rgb)
        self.label_dock = QtWidgets.QDockWidget(self.tr(u'Label List'), self)
        self.label_dock.setObjectName(u'Label List')
        self.label_dock.setWidget(self.uniqLabelList)
        
        self.fileName = QtWidgets.QLineEdit()
        self.fileName.setPlaceholderText(self.tr('Waiting for file to load...'))
        self.fileSearch = QtWidgets.QLineEdit()
        self.fileSearch.setPlaceholderText(self.tr('Search Filename'))
        self.fileSearch.textChanged.connect(self.fileSearchChanged)
        self.fileListWidget = QtWidgets.QListWidget()
        self.fileListWidget.itemSelectionChanged.connect(
            self.fileSelectionChanged
        )
        fileListLayout = QtWidgets.QVBoxLayout()
        fileListLayout.setContentsMargins(0, 0, 0, 0)
        fileListLayout.setSpacing(0)
        fileListLayout.addWidget(self.fileName)
        fileListLayout.addWidget(self.fileSearch)
        fileListLayout.addWidget(self.fileListWidget)
        self.file_dock = QtWidgets.QDockWidget(self.tr(u'File List'), self)
        self.file_dock.setObjectName(u'Files')
        fileListWidget = QtWidgets.QWidget()
        fileListWidget.setLayout(fileListLayout)
        self.file_dock.setWidget(fileListWidget)

        self.zoomWidget = ZoomWidget()
        self.setAcceptDrops(True)

        self.canvas = self.labelList.canvas = Canvas(
            epsilon=self._config['epsilon'],
            double_click=self._config['canvas']['double_click'],
            cross_hair=self._config['cross_hair'],
            hide_others=self._config['hide_others'],
        )
        self.canvas.zoomRequest.connect(self.zoomRequest)

        scrollArea = QtWidgets.QScrollArea()
        scrollArea.setWidget(self.canvas)
        scrollArea.setWidgetResizable(True)
        self.scrollBars = {
            Qt.Vertical: scrollArea.verticalScrollBar(),
            Qt.Horizontal: scrollArea.horizontalScrollBar(),
        }
        self.canvas.scrollRequest.connect(self.scrollRequest)

        self.canvas.newShape.connect(self.newShape)
        self.canvas.shapeMoved.connect(self.setDirty)
        self.canvas.selectionChanged.connect(self.shapeSelectionChanged)
        self.canvas.drawingPolygon.connect(self.toggleDrawingSensitive)

        self.setCentralWidget(scrollArea)

        features = QtWidgets.QDockWidget.DockWidgetFeatures()
        for dock in ['flag_dock', 'label_dock', 'shape_dock', 'file_dock']:
            if self._config[dock]['closable']:
                features = features | QtWidgets.QDockWidget.DockWidgetClosable
            if self._config[dock]['floatable']:
                features = features | QtWidgets.QDockWidget.DockWidgetFloatable
            if self._config[dock]['movable']:
                features = features | QtWidgets.QDockWidget.DockWidgetMovable
            getattr(self, dock).setFeatures(features)
            if self._config[dock]['show'] is False:
                getattr(self, dock).setVisible(False)

        self.addDockWidget(Qt.RightDockWidgetArea, self.flag_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.label_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.shape_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.file_dock)

        # Actions
        action = functools.partial(utils.newAction, self)
        shortcuts = self._config['shortcuts']
        quit = action(self.tr('&Quit'), self.close, shortcuts['quit'], 'quit',
                      self.tr('Quit application'))
        restart = action(self.tr('&Restart'), self.reload, 'restart',
                self.tr('Restart application'))
        open_ = action(self.tr('&Open'),
                       self.openFile,
                       shortcuts['open'],
                       'open',
                       self.tr('Open image or label file'))
        opendir = action(self.tr('&Open Dir'), self.openDirDialog,
                         shortcuts['open_dir'], 'open', self.tr(u'Open Dir'))
        openNextImg = action(
            self.tr('&Next Image'),
            self.openNextImg,
            shortcuts['open_next'],
            'next',
            self.tr(u'Open next (hold Ctl+Shift to copy labels)'),
            enabled=False,
        )
        openPrevImg = action(
            self.tr('&Prev Image'),
            self.openPrevImg,
            shortcuts['open_prev'],
            'prev',
            self.tr(u'Open prev (hold Ctl+Shift to copy labels)'),
            enabled=False,
        )
        save = action(self.tr('&Save'),
                      self.saveFile, shortcuts['save'], 'save',
                      self.tr('Save labels to file'), enabled=False)
        saveAs = action(self.tr('&Save As'), self.saveFileAs,
                        shortcuts['save_as'],
                        'save-as', self.tr('Save labels to a different file'),
                        enabled=False)

        deleteFile = action(
            self.tr('&Delete File'),
            self.deleteFile,
            shortcuts['delete_file'],
            'delete',
            self.tr('Delete current label file'),
            enabled=False)

        changeOutputDir = action(
            self.tr('&Change Output Dir'),
            slot=self.changeOutputDirDialog,
            shortcut=shortcuts['save_to'],
            icon='open',
            tip=self.tr(u'Change where annotations are loaded/saved')
        )

        saveAuto = action(
            text=self.tr('Save &Automatically'),
            slot=lambda x: self.actions.saveAuto.setChecked(x),
            tip=self.tr('Save automatically'),
            checkable=True,
            enabled=True
        )
        saveAuto.setChecked(self._config['auto_save'])

        saveWithImageData = action(
            text='Save With Image Data',
            slot=self.enableSaveImageWithData,
            tip='Save image data in label file',
            checkable=True,
            checked=self._config['store_data'],
        )

        close = action('&Close', self.closeFile, shortcuts['close'], 'close',
                       'Close current file')

        toggle_keep_prev_mode = action(
            self.tr('Keep Previous Annotation'),
            self.toggleKeepPrevMode,
            shortcuts['toggle_keep_prev_mode'], None,
            self.tr('Toggle "keep pevious annotation" mode'),
            checkable=True)
        toggle_keep_prev_mode.setChecked(self._config['keep_prev'])

        createMode = action(
            self.tr('Create Polygons'),
            lambda: self.toggleDrawMode(False, createMode='polygon'),
            shortcuts['create_polygon'],
            'objects',
            self.tr('Start drawing polygons'),
            enabled=False,
        )
        createRectangleMode = action(
            self.tr('Create Rectangle'),
            lambda: self.toggleDrawMode(False, createMode='rectangle'),
            shortcuts['create_rectangle'],
            'objects',
            self.tr('Start drawing rectangles'),
            enabled=False,
        )
        createCircleMode = action(
            self.tr('Create Circle'),
            lambda: self.toggleDrawMode(False, createMode='circle'),
            shortcuts['create_circle'],
            'objects',
            self.tr('Start drawing circles'),
            enabled=False,
        )
        createLineMode = action(
            self.tr('Create Line'),
            lambda: self.toggleDrawMode(False, createMode='line'),
            shortcuts['create_line'],
            'objects',
            self.tr('Start drawing lines'),
            enabled=False,
        )
        createPointMode = action(
            self.tr('Create Point'),
            lambda: self.toggleDrawMode(False, createMode='point'),
            shortcuts['create_point'],
            'objects',
            self.tr('Start drawing points'),
            enabled=False,
        )
        createLineStripMode = action(
            self.tr('Create LineStrip'),
            lambda: self.toggleDrawMode(False, createMode='linestrip'),
            shortcuts['create_linestrip'],
            'objects',
            self.tr('Start drawing linestrip. Ctrl+LeftClick ends creation.'),
            enabled=False,
        )
        editMode = action(self.tr('Edit Polygons'), self.setEditMode,
                          shortcuts['edit_polygon'], 'edit',
                          self.tr('Move and edit the selected polygons'),
                          enabled=False)

        delete = action(self.tr('Delete Polygons'), self.deleteSelectedShape,
                        shortcuts['delete_polygon'], 'cancel',
                        self.tr('Delete the selected polygons'), enabled=False)
        copy = action(self.tr('Duplicate Polygons'), self.copySelectedShape,
                      shortcuts['duplicate_polygon'], 'copy',
                      self.tr('Create a duplicate of the selected polygons'),
                      enabled=False)
        undoLastPoint = action(self.tr('Undo last point'),
                               self.canvas.undoLastPoint,
                               shortcuts['undo_last_point'], 'undo',
                               self.tr('Undo last drawn point'), enabled=False)
        addPointToEdge = action(
            self.tr('Add Point to Edge'),
            self.canvas.addPointToEdge,
            None,
            'edit',
            self.tr('Add point to the nearest edge'),
            enabled=False,
        )
        removePoint = action(
            text='Remove Selected Point',
            slot=self.canvas.removeSelectedPoint,
            icon='edit',
            tip='Remove selected point from polygon',
            enabled=False,
        )

        undo = action(self.tr('Undo'), self.undoShapeEdit,
                      shortcuts['undo'], 'undo',
                      self.tr('Undo last add and edit of shape'),
                      enabled=False)

        showAll = action(self.tr('&Hide/Show\nPolygons'),
                         functools.partial(self.togglePolygons, 0, False),
                         shortcuts['show_polygon'], checkable=True,
                         icon='eye', tip=self.tr('Show all polygons'),
                         enabled=True)

        hideOthers = action(self.tr('&Immersive mode'),
                            self.immersiveMode,
                            icon='focus', tip=self.tr('Hide other polygons when creating polygon'),
                            checkable=True, checked=self._config['hide_others'], enabled=True)
        hideOthers.setChecked(self._config['hide_others'])
        
        help = action(self.tr('&About'), self.about, icon='help',
                      tip=self.tr('About EnhancedLabelMe'))
        
        readme = action(self.tr('&README'), self.readme, icon='icon',
                      tip=self.tr('Open README.md'))
        
        update = action(self.tr('&Check Update'), self.checkUpdate, icon='update',
                      tip=self.tr('Check available update'))
        
        prefer = action(self.tr('&Preference'), self.preference, icon='edit',
                      tip=self.tr('Configure preference'))

        zoom = QtWidgets.QWidgetAction(self)
        zoom.setDefaultWidget(self.zoomWidget)
        self.zoomWidget.setWhatsThis(
            self.tr(
                'Zoom in or out of the image. Also accessible with '
                '{} and {} from the canvas.'
            ).format(
                utils.fmtShortcut(
                    '{},{}'.format(
                        shortcuts['zoom_in'], shortcuts['zoom_out']
                    )
                ),
                utils.fmtShortcut(self.tr("Ctrl+Wheel")),
            )
        )
        self.zoomWidget.setEnabled(False)

        zoomIn = action(self.tr('Zoom &In'),
                        functools.partial(self.addZoom, 1.1),
                        shortcuts['zoom_in'], 'zoom-in',
                        self.tr('Increase zoom level'), enabled=False)
        zoomOut = action(self.tr('&Zoom Out'),
                         functools.partial(self.addZoom, 0.9),
                         shortcuts['zoom_out'], 'zoom-out',
                         self.tr('Decrease zoom level'), enabled=False)
        zoomOrg = action(self.tr('&Original size'),
                         functools.partial(self.setZoom, 100),
                         shortcuts['zoom_to_original'], 'zoom',
                         self.tr('Zoom to original size'), enabled=False)
        fitWindow = action(self.tr('&Fit Window'), self.setFitWindow,
                           shortcuts['fit_window'], 'fit-window',
                           self.tr('Zoom follows window size'), checkable=True,
                           enabled=False)
        fitWidth = action(self.tr('Fit &Width'), self.setFitWidth,
                          shortcuts['fit_width'], 'fit-width',
                          self.tr('Zoom follows window width'),
                          checkable=True, enabled=False)
        brightnessContrast = action(
            "&Brightness Contrast",
            self.brightnessContrast,
            None,
            "color",
            "Adjust brightness and contrast",
            enabled=False,
        )
        crossHair = action(self.tr('&Show Cross-line'), self.crossHairToggle,
                           shortcuts['cross_hair'], icon='cross',
                           tip=self.tr('Show cross hair around the mouse cursor'),
                           checkable=True, checked=self._config['cross_hair'],)
        crossHair.setChecked(self._config['cross_hair'])
        crossStyle = action(self.tr('&Customize Cross-line Style'), self.crossStyleSetting,
                             icon='edit', tip=self.tr(u'Configure Cross-line Style'))

        darkMode = action(self.tr('&Dark Theme'), self.darkModeToggle, icon='dark',
                tip=self.tr('Toggle dark theme'), checkable=True, checked=self._config['dark_mode'],)

        # Group zoom controls into a list for easier toggling.
        zoomActions = (
            self.zoomWidget,
            zoomIn,
            zoomOut,
            zoomOrg,
            fitWindow,
            fitWidth,
        )
        self.zoomMode = self.FIT_WINDOW
        fitWindow.setChecked(Qt.Checked)
        self.scalers = {
            self.FIT_WINDOW: self.scaleFitWindow,
            self.FIT_WIDTH: self.scaleFitWidth,
            # Set to one to scale to 100% when loading files.
            self.MANUAL_ZOOM: lambda: 1,
        }

        edit = action(self.tr('&Edit Label'), self.editLabel,
                      shortcuts['edit_label'], 'edit',
                      self.tr('Modify the label of the selected polygon'),
                      enabled=False)

        fill_drawing = action(
            self.tr('Fill Drawing Polygon'),
            self.canvas.setFillDrawing,
            None,
            'color',
            self.tr('Fill polygon while drawing'),
            checkable=True,
            enabled=True,
        )
        fill_drawing.trigger()

        # Lavel list context menu.
        labelMenu = QtWidgets.QMenu()
        utils.addActions(labelMenu, (edit, delete))
        self.labelList.setContextMenuPolicy(Qt.CustomContextMenu)
        self.labelList.customContextMenuRequested.connect(
            self.popLabelListMenu)

        # Store actions for further handling.
        self.actions = utils.struct(
            saveAuto=saveAuto,
            saveWithImageData=saveWithImageData,
            changeOutputDir=changeOutputDir,
            save=save, saveAs=saveAs, open=open_, close=close,
            deleteFile=deleteFile,
            toggleKeepPrevMode=toggle_keep_prev_mode,
            delete=delete, edit=edit, copy=copy,
            undoLastPoint=undoLastPoint, undo=undo,
            addPointToEdge=addPointToEdge, removePoint=removePoint,
            createMode=createMode, editMode=editMode,
            createRectangleMode=createRectangleMode,
            createCircleMode=createCircleMode,
            createLineMode=createLineMode,
            createPointMode=createPointMode,
            createLineStripMode=createLineStripMode,
            zoom=zoom, zoomIn=zoomIn, zoomOut=zoomOut, zoomOrg=zoomOrg,
            fitWindow=fitWindow, fitWidth=fitWidth,
            brightnessContrast=brightnessContrast,
            zoomActions=zoomActions,
            openNextImg=openNextImg, openPrevImg=openPrevImg,
            fileMenuActions=(open_, opendir, save, saveAs, close, restart, quit),
            tool=(),
            crossHair=crossHair,
            crossStyle=crossStyle,
            darkMode=darkMode,
            hideOthers=hideOthers,
            showAll=showAll,
            # XXX: need to add some actions here to activate the shortcut
            editMenu=(
                edit,
                copy,
                delete,
                None,
                undo,
                undoLastPoint,
                None,
                addPointToEdge,
                None,
                toggle_keep_prev_mode,
            ),
            # menu shown at right click
            menu=(
                createMode,
                createRectangleMode,
                createCircleMode,
                createLineMode,
                createPointMode,
                createLineStripMode,
                editMode,
                edit,
                copy,
                delete,
                undo,
                undoLastPoint,
                addPointToEdge,
                removePoint,
            ),
            onLoadActive=(
                close,
                createMode,
                createRectangleMode,
                createCircleMode,
                createLineMode,
                createPointMode,
                createLineStripMode,
                editMode,
                brightnessContrast,
            ),
            onShapesPresent=(saveAs, showAll),
        )

        self.canvas.edgeSelected.connect(self.canvasShapeEdgeSelected)
        self.canvas.vertexSelected.connect(self.actions.removePoint.setEnabled)

        self.menus = utils.struct(
            file=self.menu(self.tr('&File')),
            edit=self.menu(self.tr('&Edit')),
            view=self.menu(self.tr('&View')),
            help=self.menu(self.tr('&Help')),
            recentFiles=QtWidgets.QMenu(self.tr('Open &Recent File')),
            #recentDirectories=QtWidgets.QMenu(self.tr('Open &Recent Directory')),
            labelList=labelMenu,
        )

        utils.addActions(
            self.menus.file,
            (
                open_,
                openNextImg,
                openPrevImg,
                opendir,
                self.menus.recentFiles,
                #self.menus.recentDirectories,
                save,
                saveAs,
                saveAuto,
                changeOutputDir,
                saveWithImageData,
                close,
                deleteFile,
                None,
                prefer,
                None,
                restart,
                quit,
            ),
        )
        utils.addActions(self.menus.help, (help, readme, update))
        utils.addActions(
            self.menus.view,
            (
                self.flag_dock.toggleViewAction(),
                self.label_dock.toggleViewAction(),
                self.shape_dock.toggleViewAction(),
                self.file_dock.toggleViewAction(),
                None,
                crossHair,
                crossStyle,
                None,
                fill_drawing,
                None,
                showAll,
                hideOthers,
                None,
                zoomIn,
                zoomOut,
                zoomOrg,
                None,
                fitWindow,
                fitWidth,
                None,
                brightnessContrast,
                None,
                darkMode,
            ),
        )
        self.menus.file.aboutToShow.connect(self.updateFileMenu)

        # Custom context menu for the canvas widget:
        utils.addActions(self.canvas.menus[0], self.actions.menu)
        utils.addActions(
            self.canvas.menus[1],
            (
                action('&Copy here', self.copyShape),
                action('&Move here', self.moveShape),
            ),
        )

        self.tools = self.toolbar('Tools')
        # Menu buttons on Left
        self.actions.tool = (
            open_,
            opendir,
            openNextImg,
            openPrevImg,
            save,
            deleteFile,
            None,
            createMode,
            editMode,
            copy,
            delete,
            undo,
            brightnessContrast,
            None,
            zoom,
            fitWidth,
        )

        self.statusBar().showMessage(self.tr('%s started.') % __appname__)
        self.statusBar().show()

        if output_file is not None and self._config['auto_save']:
            logger.warn(
                'If `auto_save` argument is True, `output_file` argument '
                'is ignored and output filename is automatically '
                'set as IMAGE_BASENAME.json.'
            )
        self.output_file = output_file
        self.output_dir = output_dir

        # Application state.
        self.image = QtGui.QImage()
        self.imagePath = None
        self.recentFiles = []
        #self.recentDirectories = []
        self.maxRecent = 10
        self.otherData = None
        self.zoom_level = 100
        self.fit_window = False
        self.zoom_values = {}  # key=filename, value=(zoom_mode, zoom_value)
        self.brightnessContrast_values = {}
        self.scroll_values = {
            Qt.Horizontal: {},
            Qt.Vertical: {},
        }  # key=filename, value=scroll_value
        
        if filename is not None and osp.isdir(filename):
            self.importDirImages(filename, load=False)
        else:
            self.filename = filename

        if config['file_search']:
            self.fileSearch.setText(config['file_search'])
            self.fileSearchChanged()

        # XXX: Could be completely declarative.
        # Restore application settings.
        self.settings = QtCore.QSettings('enhancedlabelme', 'enhancedlabelme')
        # FIXME: QSettings.value can return None on PyQt4
        self.recentFiles = self.settings.value('recentFiles', []) or []
        #self.recentDirectories = self.settings.value('recentDirectories', []) or []
        size = self.settings.value('window/size', QtCore.QSize(600, 500))
        position = self.settings.value('window/position', QtCore.QPoint(0, 0))
        self.resize(size)
        self.move(position)
        # or simply:
        # self.restoreGeometry(settings['window/geometry']
        self.restoreState(
            self.settings.value('window/state', QtCore.QByteArray()))

        # Populate the File menu dynamically.
        self.updateFileMenu()
        #self.updateDirectoryMenu()
        # Since loading the file may take some time,
        # make sure it runs in the background.
        if self.filename is not None:
            self.queueEvent(functools.partial(self.loadFile, self.filename))

        # Callbacks:
        self.zoomWidget.valueChanged.connect(self.paintCanvas)

        self.populateModeActions()

        # self.firstStart = True
        # if self.firstStart:
        #    QWhatsThis.enterWhatsThisMode()

    def menu(self, title, actions=None):
        menu = self.menuBar().addMenu(title)
        if actions:
            utils.addActions(menu, actions)
        return menu

    def toolbar(self, title, actions=None):
        toolbar = ToolBar(title)
        toolbar.setObjectName('%sToolBar' % title)
        # toolbar.setOrientation(Qt.Vertical)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        if actions:
            utils.addActions(toolbar, actions)
        self.addToolBar(Qt.LeftToolBarArea, toolbar)
        return toolbar

    # Support Functions

    def noShapes(self):
        return not len(self.labelList)

    def populateModeActions(self):
        tool, menu = self.actions.tool, self.actions.menu
        self.tools.clear()
        utils.addActions(self.tools, tool)
        self.canvas.menus[0].clear()
        utils.addActions(self.canvas.menus[0], menu)
        self.menus.edit.clear()
        actions = (
            self.actions.createMode,
            self.actions.createRectangleMode,
            self.actions.createCircleMode,
            self.actions.createLineMode,
            self.actions.createPointMode,
            self.actions.createLineStripMode,
            self.actions.editMode,
        )
        utils.addActions(self.menus.edit, actions + self.actions.editMenu)

    def setDirty(self):
        if self._config['auto_save'] or self.actions.saveAuto.isChecked():
            label_file = osp.splitext(self.imagePath)[0] + '.json'
            if self.output_dir:
                label_file_without_path = osp.basename(label_file)
                label_file = osp.join(self.output_dir, label_file_without_path)
            self.saveLabels(label_file)
            return
        self.dirty = True
        self.actions.save.setEnabled(True)
        self.actions.undo.setEnabled(self.canvas.isShapeRestorable)
        title = __appname__ + ' ' + __version__
        json_count = len([file for file in os.listdir(osp.dirname(self.filename)) if file.endswith(".json")])
        if self.filename is not None:
            title = '{} - ({}/{}) {}*'.format(title, self.fileListWidget.count(), json_count, self.filename)
        self.setWindowTitle(title)

    def setClean(self):
        self.dirty = False
        self.actions.save.setEnabled(False)
        self.actions.createMode.setEnabled(True)
        self.actions.createRectangleMode.setEnabled(True)
        self.actions.createCircleMode.setEnabled(True)
        self.actions.createLineMode.setEnabled(True)
        self.actions.createPointMode.setEnabled(True)
        self.actions.createLineStripMode.setEnabled(True)
        title = __appname__ + ' ' + __version__
        json_count = len([file for file in os.listdir(osp.dirname(self.filename)) if file.endswith(".json")])
        if self.filename is not None:
            title = '{} - ({}/{}) {}*'.format(title, self.fileListWidget.count(), json_count, self.filename)
        self.setWindowTitle(title)

        if self.hasLabelFile():
            self.actions.deleteFile.setEnabled(True)
        else:
            self.actions.deleteFile.setEnabled(False)

    def toggleActions(self, value=True):
        """Enable/Disable widgets which depend on an opened image."""
        for z in self.actions.zoomActions:
            z.setEnabled(value)
        for action in self.actions.onLoadActive:
            action.setEnabled(value)

    def canvasShapeEdgeSelected(self, selected, shape):
        self.actions.addPointToEdge.setEnabled(
            selected and shape and shape.canAddPoint()
        )

    def queueEvent(self, function):
        QtCore.QTimer.singleShot(0, function)

    def status(self, message, delay=5000):
        self.statusBar().showMessage(message, delay)

    def resetState(self):
        self.labelList.clear()
        self.filename = None
        self.imagePath = None
        self.imageData = None
        self.labelFile = None
        self.otherData = None
        self.canvas.resetState()

    def currentItem(self):
        items = self.labelList.selectedItems()
        if items:
            return items[0]
        return None

    def addRecentFile(self, filename):
        if filename in self.recentFiles:
            self.recentFiles.remove(filename)
        elif len(self.recentFiles) >= self.maxRecent:
            self.recentFiles.pop()
        self.recentFiles.insert(0, filename)
        
    # def addRecentDirectory(self, dirpath):
    #     if dirpath in self.recentDirectories:
    #         self.recentDirectories.remove(dirpath)
    #     elif len(self.recentDirectories) >= self.maxRecent:
    #         self.recentDirectories.pop()
    #     self.recentDirectories.insert(0, dirpath)

    # Callbacks

    def undoShapeEdit(self):
        self.canvas.restoreShape()
        self.labelList.clear()
        self.loadShapes(self.canvas.shapes)
        self.actions.undo.setEnabled(self.canvas.isShapeRestorable)
        
    def preference(self):
        try:
            if platform.system() == 'Darwin':       # macOS
                subprocess.call(('open', osp.join(osp.dirname(osp.realpath(__file__)), 'config/config')))
            elif platform.system() == 'Windows':    # Windows
                subprocess.call(('notepad.exe', osp.join(osp.dirname(osp.realpath(__file__)), 'config/config')))
            else:                                   # linux variants
                subprocess.call(('xdg-open', osp.join(osp.dirname(osp.realpath(__file__)), 'config/config'))   )
        except Exception:
            pass

    def reload(self):
        self.close()
        fn = osp.join(osp.dirname(osp.realpath(__file__)), '__main__.py')
        sys.exit(os.execl(sys.executable, sys.executable, *sys.argv))
    
    def about(self):
        return QtWidgets.QMessageBox.about(
            self, 'About', '\n<Version %s>\n%s'%(__version__, "Modified by LilactheGreat"))
        
    def crossStyleSetting(self):
        psw = PenStyleWindow(self)
        #self.canvas.penStyle, self.canvas.penThickness, self.canvas.penColor = psw.saveSettings(self)
        
    def readme(self):
        if platform.system() == 'Darwin':       # macOS
            subprocess.call(('open', osp.join(osp.dirname(osp.realpath(__file__)), 'README.md')))
        elif platform.system() == 'Windows':    # Windows
            subprocess.call(('notepad.exe', osp.join(osp.dirname(osp.realpath(__file__)), 'README.md')))
        else:                                   # linux variants
            subprocess.call(('xdg-open', osp.join(osp.dirname(osp.realpath(__file__)), 'README.md')))
            
    def checkUpdate(self):
        # def compare(left, right):
        #     left_vars = map(int, left.split('.'))
        #     right_vars = map(int, right.split('.'))
        #     for a, b in zip_longest(left_vars, right_vars, fillvalue = 0):
        #         if a > b:
        #             return '>'
        #         elif a < b:
        #             return '<'
        #     return '='
        
        if osp.isfile('version.txt'):
            os.remove('version.txt')
        url= "https://raw.githubusercontent.com/LilactheGreat/labelme/master/version.txt"
        os.system("curl " + url + " > version.txt")
        with open("version.txt", 'r', encoding='utf-8') as f:
            newversion = f.readlines()
        # if compare(newversion[0], __version__) == '<':
        if StrictVersion(__version__) < StrictVersion(str(newversion[0])):
            buttonReply = QtWidgets.QMessageBox.question(
                self, 'Checking Version', '\nLatest Version : %s\nCurrent Version : %s\n%s'%(
                    newversion[0], __version__, 'Newer version is available. Wanna update now?'),
                 QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
            if buttonReply == QtWidgets.QMessageBox.Yes:
                self.close()
                # package = 'enhancedlabelme==%s'%(str(newversion[0]))
                package = 'enhancedlabelme'
                subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", package])
                sys.exit(self.reload())
        else:
            return QtWidgets.QMessageBox.about(
                self, 'Checking Version', '\nLatest Version : %sCurrent Version : %s\n%s'%(
                    newversion[0], __version__, 'No new version is available'))
        
    def darkModeToggle(self):
        app = QtWidgets.QApplication.instance()
        if app is None:
            raise RuntimeError("No Qt Application found.")
        if self.actions.darkMode.isChecked():
            app.setStyleSheet(qdarkstyle.load_stylesheet())
        elif self.actions.darkMode.isChecked() == False:
            app.setStyleSheet("")
            
    def crossHairToggle(self):
        if self.actions.crossHair.isChecked() == True:
            self.canvas.cross = True
        elif self.actions.crossHair.isChecked() == False:
            self.canvas.cross = False
            
    def immersiveMode(self):
        # Prevent user from toggle mode while creating polygon
        if self.canvas.immersive_ok:
            if self.actions.hideOthers.isChecked() == True:
                self.actions.hideOthers.setChecked(False)
            elif self.actions.hideOthers.isChecked() == False:
                self.actions.hideOthers.setChecked(True)
        elif not self.canvas.immersive_ok:
            if self.actions.hideOthers.isChecked() == True:
                self.canvas.immersive = True
            elif self.actions.hideOthers.isChecked() == False:
                self.canvas.immersive = False
    
    def toggleDrawingSensitive(self, drawing=True):
        """Toggle drawing sensitive.

        In the middle of drawing, toggling between modes should be disabled.
        """
        self.actions.editMode.setEnabled(not drawing)
        self.actions.undoLastPoint.setEnabled(drawing)
        self.actions.undo.setEnabled(not drawing)
        self.actions.delete.setEnabled(not drawing)

    def toggleDrawMode(self, edit=True, createMode='polygon'):
        self.canvas.setEditing(edit)
        self.canvas.createMode = createMode
        if edit:
            self.actions.createMode.setEnabled(True)
            self.actions.createRectangleMode.setEnabled(True)
            self.actions.createCircleMode.setEnabled(True)
            self.actions.createLineMode.setEnabled(True)
            self.actions.createPointMode.setEnabled(True)
            self.actions.createLineStripMode.setEnabled(True)
        else:
            if createMode == 'polygon':
                self.actions.createMode.setEnabled(False)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createPointMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == 'rectangle':
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(False)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createPointMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == 'line':
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(False)
                self.actions.createPointMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == 'point':
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createPointMode.setEnabled(False)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == "circle":
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(False)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createPointMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == "linestrip":
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createPointMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(False)
            else:
                raise ValueError('Unsupported createMode: %s' % createMode)
        self.actions.editMode.setEnabled(not edit)  

    def setEditMode(self):
        self.toggleDrawMode(True)

    def updateFileMenu(self):
        current = self.filename

        def exists(filename):
            return osp.exists(str(filename))

        menu = self.menus.recentFiles
        menu.clear()
        files = [f for f in self.recentFiles if f != current and exists(f)]
        for i, f in enumerate(files):
            icon = utils.newIcon('labels')
            action = QtWidgets.QAction(
                icon, '&%d %s' % (i + 1, QtCore.QFileInfo(f).fileName()), self)
            action.triggered.connect(functools.partial(self.loadRecent, f))
            menu.addAction(action)
            
    # def updateDirectoryMenu(self):
    #     try:
    #         current = osp.dirname(self.filename)

    #         def exists(filename):
    #             return osp.exists(str(filename))

    #         menu = self.menus.recentDirectories
    #         menu.clear()
    #         directories = [f for f in self.recentDirectories if f != current and exists(f)]
    #         for i, f in enumerate(directories):
    #             icon = utils.newIcon('labels')
    #             action = QtWidgets.QAction(
    #                 icon, '&%d %s' % (i + 1, current), self)
    #             action.triggered.connect(functools.partial(self.loadRecentDirectory, f))
    #             menu.addAction(action)
    #     except Exception:
    #         pass

    def popLabelListMenu(self, point):
        self.menus.labelList.exec_(self.labelList.mapToGlobal(point))

    def validateLabel(self, label):
        # no validation
        if self._config['validate_label'] is None:
            return True

        for i in range(self.uniqLabelList.count()):
            label_i = self.uniqLabelList.item(i).text()
            if self._config['validate_label'] in ['exact']:
                if label_i == label:
                    return True
        return False

    def editLabel(self, item=False):
        if item and not isinstance(item, LabelListWidgetItem):
            raise TypeError("item must be LabelListWidgetItem type")
        
        if not self.canvas.editing():
            return
        if not item:
            item = self.currentItem()
        if item is None:
            return
        shape = item.shape()
        if shape is None:
            return
        text, flags, group_id = self.labelDialog.popUp(
            text=shape.label, flags=shape.flags, group_id=shape.group_id,
        )
        if text is None:
            return
        if not self.validateLabel(text):
            self.errorMessage(
                self.tr('Invalid label'),
                self.tr(
                    "Invalid label '{}' with validation type '{}'"
                ).format(text, self._config['validate_label'])
            )
            return
        shape.label = text
        shape.flags = flags
        shape.group_id = group_id
        if shape.group_id is None:
            item.setText(shape.label)
        else:
            item.setText('{} ({})'.format(shape.label, shape.group_id))
        self.setDirty()
        if not self.uniqLabelList.findItemsByLabel(shape.label):
            item = QtWidgets.QListWidgetItem()
            item.setData(Qt.UserRole, shape.label)
            self.uniqLabelList.addItem(item)

    def fileSearchChanged(self):
        self.importDirImages(
            self.lastOpenDir,
            pattern=self.fileSearch.text(),
            load=False,
        )

    def fileSelectionChanged(self):
        items = self.fileListWidget.selectedItems()
        if not items:
            return
        item = items[0]

        if not self.mayContinue():
            return

        currIndex = self.imageList.index(str(item.text()))
        if currIndex < len(self.imageList):
            filename = self.imageList[currIndex]
            if filename:
                self.loadFile(filename)

    # React to canvas signals.
    def shapeSelectionChanged(self, selected_shapes):
        self._noSelectionSlot = True
        for shape in self.canvas.selectedShapes:
            shape.selected = False
        self.labelList.clearSelection()
        self.canvas.selectedShapes = selected_shapes
        for shape in self.canvas.selectedShapes:
            shape.selected = True
            item = self.labelList.findItemByShape(shape)
            self.labelList.selectItem(item)
            self.labelList.scrollToItem(item)
        self._noSelectionSlot = False
        n_selected = len(selected_shapes)
        self.actions.delete.setEnabled(n_selected)
        self.actions.copy.setEnabled(n_selected)
        self.actions.edit.setEnabled(n_selected == 1)

    def addLabel(self, shape):
        if shape.group_id is None:
            text = shape.label
        else:
            text = '{} ({})'.format(shape.label, shape.group_id)
        label_list_item = LabelListWidgetItem(text, shape)
        self.labelList.addItem(label_list_item)
        if not self.uniqLabelList.findItemsByLabel(shape.label):
            item = self.uniqLabelList.createItemFromLabel(shape.label)
            self.uniqLabelList.addItem(item)
            rgb = self._get_rgb_by_label(shape.label)
            self.uniqLabelList.setItemLabel(item, shape.label, rgb)
        self.labelDialog.addLabelHistory(shape.label)
        for action in self.actions.onShapesPresent:
            action.setEnabled(True)

        rgb = self._get_rgb_by_label(shape.label)

        r, g, b = rgb
        label_list_item.setText(
            '{} <font color="#{:02x}{:02x}{:02x}">●</font>'.format(
                text, r, g, b
            )
        )
        shape.line_color = QtGui.QColor(r, g, b)
        shape.vertex_fill_color = QtGui.QColor(r, g, b)
        shape.hvertex_fill_color = QtGui.QColor(255, 255, 255)
        shape.fill_color = QtGui.QColor(r, g, b, 128)
        shape.select_line_color = QtGui.QColor(255, 255, 255)
        shape.select_fill_color = QtGui.QColor(r, g, b, 155)

    def _get_rgb_by_label(self, label):
        if self._config["shape_color"] == "auto":
            item = self.uniqLabelList.findItemsByLabel(label)[0]
            label_id = self.uniqLabelList.indexFromItem(item).row() + 1
            label_id += self._config["shift_auto_shape_color"]
            return LABEL_COLORMAP[label_id % len(LABEL_COLORMAP)]
        elif (
            self._config["shape_color"] == "manual"
            and self._config["label_colors"]
            and label in self._config["label_colors"]
        ):
            return self._config["label_colors"][label]
        elif self._config["default_shape_color"]:
            return self._config["default_shape_color"]


    def remLabels(self, shapes):
        for shape in shapes:
            item = self.labelList.findItemByShape(shape)
            self.labelList.removeItem(item)

    def loadShapes(self, shapes, replace=True):
        self._noSelectionSlot = True
        for shape in shapes:
            self.addLabel(shape)
        self.labelList.clearSelection()
        self._noSelectionSlot = False
        self.canvas.loadShapes(shapes, replace=replace)

    def loadLabels(self, shapes):
        s = []
        self.loadTime = str(datetime.now())
        for shape in shapes:
            label = shape['label']
            points = shape['points']
            shape_type = shape['shape_type']
            flags = shape['flags']
            group_id = shape.get('group_id')

            shape = Shape(
                label=label,
                shape_type=shape_type,
                group_id=group_id,
            )
            for x, y in points:
                shape.addPoint(QtCore.QPointF(x, y))
            shape.close()

            default_flags = {}
            if self._config['label_flags']:
                for pattern, keys in self._config['label_flags'].items():
                    if re.match(pattern, label):
                        for key in keys:
                            default_flags[key] = False
            shape.flags = default_flags
            shape.flags.update(flags)

            s.append(shape)
        self.loadShapes(s)

    def loadFlags(self, flags):
        self.flag_widget.clear()
        for key, flag in flags.items():
            item = QtWidgets.QListWidgetItem(key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if flag else Qt.Unchecked)
            self.flag_widget.addItem(item)

    def saveLabels(self, filename):
        lf = LabelFile()

        def format_shape(s):
            return dict(
                label=s.label.encode('utf-8') if PY2 else s.label,
                points=[(p.x(), p.y()) for p in s.points],
                group_id=s.group_id,
                shape_type=s.shape_type,
                flags=s.flags
            )

        shapes = [format_shape(item.shape()) for item in self.labelList]
        flags = {}
        for i in range(self.flag_widget.count()):
            item = self.flag_widget.item(i)
            key = item.text()
            flag = item.checkState() == Qt.Checked
            flags[key] = flag
        try:
            saveTime = str(datetime.now())
            imagePath = osp.relpath(
                self.imagePath, osp.dirname(filename))
            imageData = self.imageData if self._config['store_data'] else None
            if osp.dirname(filename) and not osp.exists(osp.dirname(filename)):
                os.makedirs(osp.dirname(filename))
            lf.save(
                filename=filename,
                shapes=shapes,
                imagePath=imagePath,
                imageData=imageData,
                imageHeight=self.image.height(),
                imageWidth=self.image.width(),
                otherData=self.otherData,
                flags=flags,
                loadTime=self.loadTime,
                saveTime=saveTime
            )
            self.labelFile = lf
            items = self.fileListWidget.findItems(
                self.imagePath, Qt.MatchExactly
            )
            if len(items) > 0:
                if len(items) != 1:
                    raise RuntimeError('There are duplicate files.')
                items[0].setCheckState(Qt.Checked)
            # disable allows next and previous image to proceed
            # self.filename = filename
            return True
        except LabelFileError as e:
            self.errorMessage(
                self.tr('Error saving label data'),
                self.tr('<b>%s</b>') % e
            )
            return False

    def copySelectedShape(self):
        added_shapes = self.canvas.copySelectedShapes()
        self.labelList.clearSelection()
        for shape in added_shapes:
            self.addLabel(shape)
        self.setDirty()

    def labelSelectionChanged(self):
        if self._noSelectionSlot:
            return
        if self.canvas.editing():
            selected_shapes = []
            for item in self.labelList.selectedItems():
                selected_shapes.append(item.shape())
            if selected_shapes:
                self.canvas.selectShapes(selected_shapes)
            else:
                self.canvas.deSelectShape()

    def labelItemChanged(self, item):
        shape = item.shape()
        self.canvas.setShapeVisible(shape, item.checkState() == Qt.Checked)
        
    def labelOrderChanged(self):
        self.setDirty()
        self.canvas.loadShapes([item.shape() for item in self.labelList])

    # Callback functions:

    def newShape(self):
        """Pop-up and give focus to the label editor.

        position MUST be in global coordinates.
        """
        items = self.uniqLabelList.selectedItems()
        text = None
        flags = {}
        group_id = None
        if items:
            text = items[0].text()
        if self._config['display_label_popup'] or not text:
            # instance label auto increment
            if self._config['instance_label_auto_increment']:
                previous_label = self.labelDialog.edit.text()
                split = previous_label.split('-')
                if len(split) > 1 and split[-1].isdigit():
                    split[-1] = str(int(split[-1]) + 1)
                    instance_text = '-'.join(split)
                else:
                    instance_text = previous_label
                if instance_text != '':
                    text = instance_text
            text, flags, group_id = self.labelDialog.popUp(text)
            if text is None:
                self.labelDialog.edit.setText(previous_label)

        if text and not self.validateLabel(text):
            self.errorMessage(
                self.tr('Invalid label'),
                self.tr(
                    "Invalid label '{}' with validation type '{}'"
                ).format(text, self._config['validate_label'])
            )
            text = ''
        if text:
            self.labelList.clearSelection()
            shape = self.canvas.setLastLabel(text, flags)
            shape.group_id = group_id
            self.addLabel(shape)
            self.actions.editMode.setEnabled(True)
            self.actions.undoLastPoint.setEnabled(False)
            self.actions.undo.setEnabled(True)
            self.setDirty()
            if self.actions.hideOthers.isChecked() == True:
                self.canvas.keyboard_con()
                self.canvas.immersive_first = True
            self.canvas.immersive_ok = False
        else:
            self.canvas.undoLastLine()
            self.canvas.shapesBackups.pop()

    def scrollRequest(self, delta, orientation):
        units = - delta * 0.1  # natural scroll
        bar = self.scrollBars[orientation]
        value = bar.value() + bar.singleStep() * units
        self.setScroll(orientation, value)

    def setScroll(self, orientation, value):
        self.scrollBars[orientation].setValue(value)
        self.scroll_values[orientation][self.filename] = value

    def setZoom(self, value):
        self.actions.fitWidth.setChecked(False)
        self.actions.fitWindow.setChecked(False)
        self.zoomMode = self.MANUAL_ZOOM
        self.zoomWidget.setValue(value)
        self.zoom_values[self.filename] = (self.zoomMode, value)

    def addZoom(self, increment=1.1):
        self.setZoom(self.zoomWidget.value() * increment)
        zoom_value = self.zoomWidget.value() * increment
        if increment > 1:
            zoom_value = math.ceil(zoom_value)
        else:
            zoom_value = math.floor(zoom_value)
        self.setZoom(zoom_value)
    def zoomRequest(self, delta, pos):
        canvas_width_old = self.canvas.width()
        units = 1.1
        if delta < 0:
            units = 0.9
        self.addZoom(units)

        canvas_width_new = self.canvas.width()
        if canvas_width_old != canvas_width_new:
            canvas_scale_factor = canvas_width_new / canvas_width_old

            x_shift = round(pos.x() * canvas_scale_factor) - pos.x()
            y_shift = round(pos.y() * canvas_scale_factor) - pos.y()

            self.setScroll(
                Qt.Horizontal,
                self.scrollBars[Qt.Horizontal].value() + x_shift,
            )
            self.setScroll(
                Qt.Vertical,
                self.scrollBars[Qt.Vertical].value() + y_shift,
            )

    def setFitWindow(self, value=True):
        if value:
            self.actions.fitWidth.setChecked(False)
        self.zoomMode = self.FIT_WINDOW if value else self.MANUAL_ZOOM
        self.adjustScale()

    def setFitWidth(self, value=True):
        if value:
            self.actions.fitWindow.setChecked(False)
        self.zoomMode = self.FIT_WIDTH if value else self.MANUAL_ZOOM
        self.adjustScale()

    def onNewBrightnessContrast(self, qimage):
        self.canvas.loadPixmap(
            QtGui.QPixmap.fromImage(qimage), clear_shapes=False
        )

    def brightnessContrast(self, value):
        dialog = BrightnessContrastDialog(
            utils.img_data_to_pil(self.imageData),
            self.onNewBrightnessContrast,
            parent=self,
        )
        brightness, contrast = self.brightnessContrast_values.get(
            self.filename, (None, None)
        )
        if brightness is not None:
            dialog.slider_brightness.setValue(brightness)
        if contrast is not None:
            dialog.slider_contrast.setValue(contrast)
        dialog.exec_()

        brightness = dialog.slider_brightness.value()
        contrast = dialog.slider_contrast.value()
        self.brightnessContrast_values[self.filename] = (brightness, contrast)

    def togglePolygons(self, mode, value):
        if mode == 0:
            for item in self.labelList:
                item.setCheckState(Qt.Checked if not self.actions.showAll.isChecked() else Qt.Unchecked)
        elif mode == 1:
            for item in self.labelList:
                item.setCheckState(Qt.Checked if not value else Qt.Unchecked)

    def loadFile(self, filename=None):
        """Load the specified file, or the last opened file if None."""
        # changing fileListWidget loads file
        if (filename in self.imageList and
                self.fileListWidget.currentRow() !=
                self.imageList.index(filename)):
            self.fileListWidget.setCurrentRow(self.imageList.index(filename))
            self.fileListWidget.repaint()
            return

        self.resetState()
        self.canvas.setEnabled(False)
        if filename is None:
            filename = self.settings.value('filename', '')
        filename = str(filename)
        self.fileName.setText(filename)
        if not QtCore.QFile.exists(filename):
            self.errorMessage(
                self.tr('Error opening file'),
                self.tr('No such file: <b>%s</b>') % filename
            )
            return False
        # assumes same name, but json extension
        self.status(self.tr("Loading %s...") % osp.basename(str(filename)))
        label_file = osp.splitext(filename)[0] + '.json'
        if self.output_dir:
            label_file_without_path = osp.basename(label_file)
            label_file = osp.join(self.output_dir, label_file_without_path)
        if QtCore.QFile.exists(label_file) and \
                LabelFile.is_label_file(label_file):
            try:
                self.labelFile = LabelFile(label_file)
            except LabelFileError as e:
                self.errorMessage(
                    self.tr('Error opening file'),
                    self.tr(
                        "<p><b>%s</b></p>"
                        "<p>Make sure <i>%s</i> is a valid label file."
                    ) % (e, label_file)
                )
                self.status(self.tr("Error reading %s") % label_file)
                return False
            self.imageData = self.labelFile.imageData
            self.imagePath = osp.join(
                osp.dirname(label_file),
                self.labelFile.imagePath,
            )
            self.otherData = self.labelFile.otherData
        else:
            self.imageData = LabelFile.load_image_file(self, filename, str(datetime.now()))
            if self.imageData:
                self.imagePath = filename
            self.labelFile = None
        image = QtGui.QImage.fromData(self.imageData)

        if image.isNull():
            formats = ['*.{}'.format(fmt.data().decode())
                       for fmt in QtGui.QImageReader.supportedImageFormats()]
            self.errorMessage(
                self.tr('Error opening file'),
                self.tr(
                    '<p>Make sure <i>{0}</i> is a valid image file.<br/>'
                    'Supported image formats: {1}</p>'
                ).format(filename, ','.join(formats))
            )
            self.status(self.tr("Error reading %s") % filename)
            return False
        self.image = image
        self.filename = filename
        if self._config['keep_prev']:
            prev_shapes = self.canvas.shapes
        self.canvas.loadPixmap(QtGui.QPixmap.fromImage(image))
        flags = {k: False for k in self._config["flags"] or []}
        if self._config['flags']:
            self.loadFlags({k: False for k in self._config['flags']})
        if self.labelFile:
            self.loadLabels(self.labelFile.shapes)
            if self.labelFile.flags is not None:
                self.loadFlags(self.labelFile.flags)
        self.loadFlags(flags)
        if self._config['keep_prev'] and self.noShapes():
            self.loadShapes(prev_shapes, replace=False)
            self.setDirty()
        else:
            self.setClean()
        self.canvas.setEnabled(True)
        # set zoom values
        is_initial_load = not self.zoom_values
        if self.filename in self.zoom_values:
            self.zoomMode = self.zoom_values[self.filename][0]
            self.setZoom(self.zoom_values[self.filename][1])
        elif is_initial_load or not self._config['keep_prev_scale']:
            self.adjustScale(initial=True)
        # set scroll values
        for orientation in self.scroll_values:
            if self.filename in self.scroll_values[orientation]:
                self.setScroll(
                    orientation, self.scroll_values[orientation][self.filename]
                )
        # set brightness constrast values
        dialog = BrightnessContrastDialog(
            utils.img_data_to_pil(self.imageData),
            self.onNewBrightnessContrast,
            parent=self,
        )
        brightness, contrast = self.brightnessContrast_values.get(
            self.filename, (None, None)
        )
        if self._config["keep_prev_brightness"] and self.recentFiles:
            brightness, _ = self.brightnessContrast_values.get(
                self.recentFiles[0], (None, None)
            )
        if self._config["keep_prev_contrast"] and self.recentFiles:
            _, contrast = self.brightnessContrast_values.get(
                self.recentFiles[0], (None, None)
            )
        if brightness is not None:
            dialog.slider_brightness.setValue(brightness)
        if contrast is not None:
            dialog.slider_contrast.setValue(contrast)
        self.brightnessContrast_values[self.filename] = (brightness, contrast)
        if brightness is not None or contrast is not None:
            dialog.onNewValue(None)
        self.paintCanvas()
        self.addRecentFile(self.filename)
        self.toggleActions(True)
        self.status(self.tr("Loaded %s") % osp.basename(str(filename)))
        return True

    def resizeEvent(self, event):
        if (
            self.canvas
            and not self.image.isNull()
            and self.zoomMode != self.MANUAL_ZOOM
        ):
            self.adjustScale()
        super(MainWindow, self).resizeEvent(event)

    def paintCanvas(self):
        assert not self.image.isNull(), "cannot paint null image"
        self.canvas.scale = 0.01 * self.zoomWidget.value()
        self.canvas.adjustSize()
        self.canvas.update()

    def adjustScale(self, initial=False):
        value = self.scalers[self.FIT_WINDOW if initial else self.zoomMode]()
        value = int(100 * value)
        self.zoomWidget.setValue(value)
        self.zoom_values[self.filename] = (self.zoomMode, value)

    def scaleFitWindow(self):
        """Figure out the size of the pixmap to fit the main widget."""
        e = 2.0  # So that no scrollbars are generated.
        w1 = self.centralWidget().width() - e
        h1 = self.centralWidget().height() - e
        a1 = w1 / h1
        # Calculate a new scale value based on the pixmap's aspect ratio.
        w2 = self.canvas.pixmap.width() - 0.0
        h2 = self.canvas.pixmap.height() - 0.0
        a2 = w2 / h2
        return w1 / w2 if a2 >= a1 else h1 / h2

    def scaleFitWidth(self):
        # The epsilon does not seem to work too well here.
        w = self.centralWidget().width() - 2.0
        return w / self.canvas.pixmap.width()

    def enableSaveImageWithData(self, enabled):
        self._config['store_data'] = enabled
        self.actions.saveWithImageData.setChecked(enabled)

    def closeEvent(self, event):
        if not self.mayContinue():
            event.ignore()
        self.settings.setValue(
            'filename', self.filename if self.filename else '')
        self.settings.setValue('window/size', self.size())
        self.settings.setValue('window/position', self.pos())
        self.settings.setValue('window/state', self.saveState())
        self.settings.setValue('recentFiles', self.recentFiles)
        #self.settings.setValue('recentDirectories', self.recentDirectories)
        # ask the use for where to save the labels
        # self.settings.setValue('window/geometry', self.saveGeometry())
        
    def dragEnterEvent(self, event):
        extensions = [
            ".%s" % fmt.data().decode().lower()
            for fmt in QtGui.QImageReader.supportedImageFormats()
        ]
        if event.mimeData().hasUrls():
            items = [i.toLocalFile() for i in event.mimeData().urls()]
            if any([i.lower().endswith(tuple(extensions)) for i in items]):
                event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not self.mayContinue():
            event.ignore()
            return
        items = [i.toLocalFile() for i in event.mimeData().urls()]
        self.importDroppedImageFiles(items)

    # User Dialogs #

    def loadRecent(self, filename):
        if self.mayContinue():
            self.loadFile(filename)

    def openPrevImg(self, _value=False):
        keep_prev = self._config['keep_prev']
        if QtGui.QGuiApplication.keyboardModifiers() == \
                (QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier):
            self._config['keep_prev'] = True

        if not self.mayContinue():
            return

        if len(self.imageList) <= 0:
            return

        if self.filename is None:
            return

        currIndex = self.imageList.index(self.filename)
        if currIndex - 1 >= 0:
            filename = self.imageList[currIndex - 1]
            if filename:
                self.loadFile(filename)

        self._config['keep_prev'] = keep_prev

    def openNextImg(self, _value=False, load=True):
        keep_prev = self._config['keep_prev']
        if QtGui.QGuiApplication.keyboardModifiers() == \
                (QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier):
            self._config['keep_prev'] = True

        if not self.mayContinue():
            return

        if len(self.imageList) <= 0:
            return

        filename = None
        if self.filename is None:
            filename = self.imageList[0]
        else:
            currIndex = self.imageList.index(self.filename)
            if currIndex + 1 < len(self.imageList):
                filename = self.imageList[currIndex + 1]
            else:
                filename = self.imageList[-1]
        self.filename = filename

        if self.filename and load:
            self.loadFile(self.filename)

        self._config['keep_prev'] = keep_prev

    def openFile(self, _value=False):
        self.canvas.dialog = True
        if not self.mayContinue():
            return
        self.loadTime = str(datetime.now())
        path = osp.dirname(str(self.filename)) if self.filename else '.'
        formats = ['*.{}'.format(fmt.data().decode())
                   for fmt in QtGui.QImageReader.supportedImageFormats()]
        filters = self.tr("Image & Label files (%s)") % ' '.join(
            formats + ['*%s' % LabelFile.suffix])
        filename = QtWidgets.QFileDialog.getOpenFileName(
            self, self.tr('%s - Choose Image or Label file') % __appname__,
            path, filters)
        if QT5:
            filename, _ = filename
        filename = str(filename)
        if filename:
            self.loadFile(filename)
        self.canvas.dialog = False

    def changeOutputDirDialog(self, _value=False):
        self.canvas.dialog = True
        default_output_dir = self.output_dir
        if default_output_dir is None and self.filename:
            default_output_dir = osp.dirname(self.filename)
        if default_output_dir is None:
            default_output_dir = self.currentPath()

        output_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self.tr('%s - Save/Load Annotations in Directory') % __appname__,
            default_output_dir,
            QtWidgets.QFileDialog.ShowDirsOnly |
            QtWidgets.QFileDialog.DontResolveSymlinks,
        )
        output_dir = str(output_dir)

        if not output_dir:
            return

        self.output_dir = output_dir

        self.statusBar().showMessage(
            self.tr('%s . Annotations will be saved/loaded in %s') %
            ('Change Annotations Dir', self.output_dir))
        self.statusBar().show()

        current_filename = self.filename
        self.importDirImages(self.lastOpenDir, load=False)
        self.canvas.dialog = False

        if current_filename in self.imageList:
            # retain currently selected file
            self.fileListWidget.setCurrentRow(
                self.imageList.index(current_filename))
            self.fileListWidget.repaint()

    def saveFile(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        if self._config['flags'] or self.hasLabels():
            if self.labelFile:
                # DL20180323 - overwrite when in directory
                self._saveFile(self.labelFile.filename)
            elif self.output_file:
                self._saveFile(self.output_file)
                self.close()
            else:
                self._saveFile(self.saveFileDialog())

    def saveFileAs(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        if self.hasLabels():
            self._saveFile(self.saveFileDialog())

    def saveFileDialog(self):
        caption = self.tr('%s - Choose File') % __appname__
        filters = self.tr('Label files (*%s)') % LabelFile.suffix
        if self.output_dir:
            dlg = QtWidgets.QFileDialog(
                self, caption, self.output_dir, filters
            )
        else:
            dlg = QtWidgets.QFileDialog(
                self, caption, self.currentPath(), filters
            )
        dlg.setDefaultSuffix(LabelFile.suffix[1:])
        dlg.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
        dlg.setOption(QtWidgets.QFileDialog.DontConfirmOverwrite, False)
        dlg.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, False)
        basename = osp.basename(osp.splitext(self.filename)[0])
        if self.output_dir:
            default_labelfile_name = osp.join(
                self.output_dir, basename + LabelFile.suffix
            )
        else:
            default_labelfile_name = osp.join(
                self.currentPath(), basename + LabelFile.suffix
            )
        filename = dlg.getSaveFileName(
            self, self.tr('Choose File'), default_labelfile_name,
            self.tr('Label files (*%s)') % LabelFile.suffix)
        if QT5:
            filename, _ = filename
        filename = str(filename)
        return filename

    def _saveFile(self, filename):
        if filename and self.saveLabels(filename):
            self.addRecentFile(filename)
            self.setClean()

    def closeFile(self, _value=False):
        try:
            if not self.mayContinue():
                return
            self.setClean()
            self.resetState()
            self.toggleActions(False)
            self.canvas.setEnabled(False)
            self.actions.saveAs.setEnabled(False)
        except Exception:
            pass

    def getLabelFile(self):
        if self.filename.lower().endswith('.json'):
            label_file = self.filename
        else:
            label_file = osp.splitext(self.filename)[0] + '.json'

        return label_file

    def deleteFile(self):
        mb = QtWidgets.QMessageBox
        msg = self.tr('You are about to permanently delete this label file, '
                      'proceed anyway?')
        answer = mb.warning(self, self.tr('Attention'), msg, mb.Yes | mb.No)
        if answer != mb.Yes:
            return

        label_file = self.getLabelFile()
        if osp.exists(label_file):
            os.remove(label_file)
            logger.info('Label file is removed: {}'.format(label_file))

            item = self.fileListWidget.currentItem()
            item.setCheckState(Qt.Unchecked)

            self.resetState()

    # Message Dialogs. #
    def hasLabels(self):
        if self.noShapes():
            self.errorMessage(
                "No objects labeled",
                "You must label at least one object to save the file.",
            )
            return False
        return True


    def hasLabelFile(self):
        if self.filename is None:
            return False

        label_file = self.getLabelFile()
        return osp.exists(label_file)

    def mayContinue(self):
        if not self.dirty:
            return True
        mb = QtWidgets.QMessageBox
        msg = self.tr('Save annotations to "{}" before closing?').format(
            self.filename)
        answer = mb.question(self,
                             self.tr('Save annotations?'),
                             msg,
                             mb.Save | mb.Discard | mb.Cancel,
                             mb.Save)
        if answer == mb.Discard:
            return True
        elif answer == mb.Save:
            self.saveFile()
            return True
        else:  # answer == mb.Cancel
            return False

    def errorMessage(self, title, message):
        return QtWidgets.QMessageBox.critical(
            self, title, '<p><b>%s</b></p>%s' % (title, message))

    def currentPath(self):
        return osp.dirname(str(self.filename)) if self.filename else '.'

    def toggleKeepPrevMode(self):
        self._config['keep_prev'] = not self._config['keep_prev']
        
    def removeSelectedPoint(self):
        shape = self.canvas.removeSelectedPoint()
        if(shape.haveNoPoints()):
            self.canvas.deleteShape(shape)
            self.remLabels([shape])
            self.setDirty()
            if self.noShapes():
                for action in self.actions.onShapesPresent:
                    action.setEnabled(False)

    def deleteSelectedShape(self):
        yes, no = QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No
        msg = self.tr(
            'You are about to permanently delete {} polygons, '
            'proceed anyway?'
        ).format(len(self.canvas.selectedShapes))
        if yes == QtWidgets.QMessageBox.warning(
                self, self.tr('Attention'), msg,
                yes | no):
            self.remLabels(self.canvas.deleteSelected())
            self.setDirty()
            if self.noShapes():
                for action in self.actions.onShapesPresent:
                    action.setEnabled(False)

    def copyShape(self):
        self.canvas.endMove(copy=True)
        self.labelList.clearSelection()
        for shape in self.canvas.selectedShapes:
            self.addLabel(shape)
        self.setDirty()

    def moveShape(self):
        self.canvas.endMove(copy=False)
        self.setDirty()

    def openDirDialog(self, _value=False, dirpath=None):
        self.canvas.dialog = True
        if not self.mayContinue():
            return

        defaultOpenDirPath = dirpath if dirpath else "."
        if self.lastOpenDir and osp.exists(self.lastOpenDir):
            defaultOpenDirPath = self.lastOpenDir
        else:
            defaultOpenDirPath = (
                osp.dirname(self.filename) if self.filename else "."
            )

        targetDirPath = str(
            QtWidgets.QFileDialog.getExistingDirectory(
                self,
                self.tr("%s - Open Directory") % __appname__,
                defaultOpenDirPath,
                QtWidgets.QFileDialog.ShowDirsOnly
                | QtWidgets.QFileDialog.DontResolveSymlinks,
            )
        )
        self.importDirImages(targetDirPath)
        self.canvas.dialog = False
            
            
    @property
    def imageList(self):
        lst = []
        for i in range(self.fileListWidget.count()):
            item = self.fileListWidget.item(i)
            # item_temp = str(osp.basename(item.text())) + str('(%s)'%(osp.dirname(item.text())))
            lst.append(item.text())
        return lst

    def importDroppedImageFiles(self, imageFiles):
        extensions = [
            ".%s" % fmt.data().decode().lower()
            for fmt in QtGui.QImageReader.supportedImageFormats()
        ]

        self.filename = None
        for file in imageFiles:
            if file in self.imageList or not file.lower().endswith(
                tuple(extensions)
            ):
                continue
            label_file = osp.splitext(file)[0] + ".json"
            if self.output_dir:
                label_file_without_path = osp.basename(label_file)
                label_file = osp.join(self.output_dir, label_file_without_path)
            item = QtWidgets.QListWidgetItem(file)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if QtCore.QFile.exists(label_file) and LabelFile.is_label_file(
                label_file
            ):
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.fileListWidget.addItem(item)

        if len(self.imageList) > 1:
            self.actions.openNextImg.setEnabled(True)
            self.actions.openPrevImg.setEnabled(True)

        self.openNextImg()

    def importDirImages(self, dirpath, pattern=None, load=True):
        self.actions.openNextImg.setEnabled(True)
        self.actions.openPrevImg.setEnabled(True)

        if not self.mayContinue() or not dirpath:
            return

        self.lastOpenDir = dirpath
        self.filename = None
        self.fileListWidget.clear()
        for filename in self.scanAllImages(dirpath):
            if pattern and pattern not in filename:
                continue
            label_file = osp.splitext(filename)[0] + '.json'
            if self.output_dir:
                label_file_without_path = osp.basename(label_file)
                label_file = osp.join(self.output_dir, label_file_without_path)
            item = QtWidgets.QListWidgetItem(filename)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if QtCore.QFile.exists(label_file) and \
                    LabelFile.is_label_file(label_file):
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.fileListWidget.addItem(item)
        self.openNextImg(load=load)

    def scanAllImages(self, folderPath):
        extensions = [
            ".%s" % fmt.data().decode().lower()
            for fmt in QtGui.QImageReader.supportedImageFormats()
        ]

        images = []
        for root, dirs, files in os.walk(folderPath):
            for file in files:
                if file.lower().endswith(tuple(extensions)):
                    relativePath = osp.join(root, file)
                    images.append(relativePath)
        images.sort(key=lambda x: x.lower())
        return images