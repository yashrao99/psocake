# GUI for browsing LCLS area detectors. Tune hit finding parameters and common mode correction.

# TODO: Zoom in area / numbers
# TODO: Multiple subplots
# TODO: grid of images
# TODO: powder pattern generator
# TODO: dropdown menu for available detectors
# TODO: When front and back detectors given, display both

import sys, signal
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui
import pyqtgraph.console
from pyqtgraph.dockarea import *
from pyqtgraph.dockarea.Dock import DockLabel
import pyqtgraph.parametertree.parameterTypes as pTypes
from pyqtgraph.parametertree import Parameter, ParameterTree, ParameterItem, registerParameterType
import psana
import h5py
from ImgAlgos.PyAlgos import PyAlgos # peak finding
import matplotlib.pyplot as plt
from pyqtgraph import Point
import argparse
import Detector.PyDetector
import logging
import multiprocessing as mp
import time
import subprocess
import os.path

parser = argparse.ArgumentParser()
parser.add_argument("-e","--exp", help="experiment name (e.g. cxis0813), default=''",default="", type=str)
parser.add_argument("-r","--run", help="run number (e.g. 5), default=0",default=0, type=int)
parser.add_argument("-d","--det", help="detector name (e.g. CxiDs1.0:Cspad.0), default=''",default="", type=str)
parser.add_argument("-n","--evt", help="event number (e.g. 1), default=0",default=0, type=int)
parser.add_argument("--localCalib", help="use local calib directory, default=False", action='store_true')
args = parser.parse_args()

# Set up tolerance
eps = np.finfo("float64").eps
resolutionRingList = np.array([100.,300.,500.,700.,900.,1100.])

# Set up list of parameters
exp_grp = 'Experiment information'
exp_name_str = 'Experiment Name'
exp_run_str = 'Run Number'
exp_det_str = 'DetInfo'
exp_evt_str = 'Event Number'
exp_second_str = 'Seconds'
exp_nanosecond_str = 'Nanoseconds'
exp_fiducial_str = 'Fiducial'
exp_numEvents_str = 'Total Events'
exp_detInfo_str = 'Detector ID'

disp_grp = 'Display'
disp_log_str = 'Logscale'
disp_aduThresh_str = 'ADU threshold'

disp_commonMode_str = 'Common mode (override)'
disp_overrideCommonMode_str = 'Apply common mode (override)'
disp_commonModeParam0_str = 'parameters 0'
disp_commonModeParam1_str = 'parameters 1'
disp_commonModeParam2_str = 'parameters 2'
disp_commonModeParam3_str = 'parameters 3'

hitParam_grp = 'Hit finder'
hitParam_classify_str = 'Classify'
hitParam_algorithm_str = 'Algorithm'
hitParam_alg_npix_min_str = 'npix_min'
hitParam_alg_npix_max_str = 'npix_max'
hitParam_alg_amax_thr_str = 'amax_thr'
hitParam_alg_atot_thr_str = 'atot_thr'
hitParam_alg_son_min_str = 'son_min'
# algorithm 1
hitParam_algorithm1_str = 'Droplet'
hitParam_alg1_thr_low_str = 'thr_low'
hitParam_alg1_thr_high_str = 'thr_high'
hitParam_alg1_radius_str = 'radius'
hitParam_alg1_dr_str = 'dr'
# algorithm 2
hitParam_algorithm2_str = 'Flood-fill'
hitParam_alg2_thr_str = 'thr'
hitParam_alg2_r0_str = 'r0'
hitParam_alg2_dr_str = 'dr'
# algorithm 3
hitParam_algorithm3_str = 'Ranker'
hitParam_alg3_rank_str = 'rank'
hitParam_alg3_r0_str = 'r0'
hitParam_alg3_dr_str = 'dr'

geom_grp = 'Diffraction geometry'
geom_detectorDistance_str = 'Detector distance'
geom_photonEnergy_str = 'Photon energy'
geom_wavelength_str = "Wavelength"
geom_pixelSize_str = 'Pixel size'
geom_resolutionRings_str = 'Resolution rings'
geom_resolution_str = 'Resolution (pixels)'

paramsDiffractionGeometry = [
    {'name': geom_grp, 'type': 'group', 'children': [
        {'name': geom_detectorDistance_str, 'type': 'float', 'value': 0.0, 'precision': 12, 'minVal': 1e-6, 'siFormat': (6,6), 'siPrefix': True, 'suffix': 'm'},
        {'name': geom_photonEnergy_str, 'type': 'float', 'value': 0.0, 'step': 1e-6, 'siPrefix': True, 'suffix': 'eV'},
        {'name': geom_wavelength_str, 'type': 'float', 'value': 0.0, 'step': 1e-6, 'siPrefix': True, 'suffix': 'm', 'readonly': True},
        {'name': geom_pixelSize_str, 'type': 'float', 'value': 0.0, 'precision': 12, 'minVal': 1e-6, 'siPrefix': True, 'suffix': 'm'},
        {'name': geom_resolutionRings_str, 'type': 'bool', 'value': False, 'tip': "Display resolution rings", 'children': [
            {'name': geom_resolution_str, 'type': 'str', 'value': None},
        ]},
    ]},
]

# Color scheme
sandstone100_rgb = (221,207,153) # Sandstone
cardinalRed_hex = str("#8C1515") # Cardinal red

class MainFrame(QtGui.QWidget):
    """
    The main frame of the application
    """        
    def __init__(self, arg_list):
        super(MainFrame, self).__init__()
        self.firstUpdate = True
        # Init experiment parameters
        self.experimentName = args.exp
        self.runNumber = int(args.run)
        #self.detInfoList = [1,2,3,4]
        self.detInfo = args.det
        self.eventNumber = int(args.evt)
        self.eventSeconds = ""
        self.eventNanoseconds = ""
        self.eventFiducial = ""
        self.eventTotal = 0
        self.hasExperimentName = False
        self.hasRunNumber = False
        self.hasDetInfo = False
        # Init display parameters
        self.logscaleOn = True
        self.aduThresh = 20.

        self.hasUserDefinedResolution = False
        self.hasCommonMode = False
        self.applyCommonMode = False
        self.commonMode = np.array([0,0,0,0])
        self.commonModeParams = np.array([0,0,0,0])
        # Init diffraction geometry parameters
        self.detectorDistance = None
        self.photonEnergy = None
        self.wavelength = None
        self.pixelSize = None
        self.resolutionRingsOn = False
        self.resolution = None
        self.resolutionText = []
        # Init variables
        self.data = None # assembled detector image
        self.cx = None
        self.cy = None
        self.calib = None # ndarray detector image
        # Init hit finding parameters
        self.algInitDone = False
        self.algorithm = 1
        self.classify = False
        self.hitParam_alg_npix_min = 5.
        self.hitParam_alg_npix_max = 5000.
        self.hitParam_alg_amax_thr = 0.
        self.hitParam_alg_atot_thr = 0.
        self.hitParam_alg_son_min = 10.
        self.hitParam_alg1_thr_low = 10.
        self.hitParam_alg1_thr_high = 150.
        self.hitParam_alg1_radius = 5
        self.hitParam_alg1_dr = 0.05
        self.hitParam_alg2_thr = 10.
        self.hitParam_alg2_r0 = 5.
        self.hitParam_alg2_dr = 0.05
        self.hitParam_alg3_rank = 3
        self.hitParam_alg3_r0 = 5.
        self.hitParam_alg3_dr = 0.05
        # Threads
        self.stackStart = 0
        self.stackSize = 60
        self.params = [
            {'name': exp_grp, 'type': 'group', 'children': [
                {'name': exp_name_str, 'type': 'str', 'value': self.experimentName},
                {'name': exp_run_str, 'type': 'int', 'value': self.runNumber},
                {'name': exp_detInfo_str, 'type': 'str', 'value': self.detInfo},
                {'name': exp_evt_str, 'type': 'int', 'value': self.eventNumber, 'limits': (0, 0), 'children': [
                    {'name': exp_second_str, 'type': 'str', 'value': self.eventSeconds, 'readonly': True},
                    {'name': exp_nanosecond_str, 'type': 'str', 'value': self.eventNanoseconds, 'readonly': True},
                    {'name': exp_fiducial_str, 'type': 'str', 'value': self.eventFiducial, 'readonly': True},
                    {'name': exp_numEvents_str, 'type': 'str', 'value': self.eventTotal, 'readonly': True},
                ]},
            ]},
            {'name': disp_grp, 'type': 'group', 'children': [
                {'name': disp_log_str, 'type': 'bool', 'value': self.logscaleOn, 'tip': "Display in log10"},
                {'name': disp_aduThresh_str, 'type': 'float', 'value': self.aduThresh, 'tip': "Do not display ADUs below the threshold"},
                {'name': disp_commonMode_str, 'visible': True, 'expanded': False, 'type': 'str', 'value': "", 'readonly': True, 'children': [
                    {'name': disp_overrideCommonMode_str, 'type': 'bool', 'value': self.applyCommonMode, 'tip': "Apply common mode (override)"},
                    {'name': disp_commonModeParam0_str, 'type': 'int', 'value': self.commonModeParams[0]},
                    {'name': disp_commonModeParam1_str, 'type': 'int', 'value': self.commonModeParams[1]},
                    {'name': disp_commonModeParam2_str, 'type': 'int', 'value': self.commonModeParams[2]},
                    {'name': disp_commonModeParam3_str, 'type': 'int', 'value': self.commonModeParams[3]},
                ]},
            ]},
            {'name': hitParam_grp, 'type': 'group', 'children': [
                {'name': hitParam_classify_str, 'type': 'bool', 'value': self.classify, 'tip': "Classify current image as hit or miss"},
                {'name': hitParam_algorithm_str, 'type': 'list', 'values': {hitParam_algorithm3_str: 3, hitParam_algorithm2_str: 2, hitParam_algorithm1_str: 1}, 'value': self.algorithm},
                {'name': hitParam_algorithm1_str, 'visible': True, 'expanded': False, 'type': 'str', 'value': "", 'readonly': True, 'children': [
                    {'name': hitParam_alg_npix_min_str, 'type': 'float', 'value': self.hitParam_alg_npix_min},
                    {'name': hitParam_alg_npix_max_str, 'type': 'float', 'value': self.hitParam_alg_npix_max},
                    {'name': hitParam_alg_amax_thr_str, 'type': 'float', 'value': self.hitParam_alg_amax_thr},
                    {'name': hitParam_alg_atot_thr_str, 'type': 'float', 'value': self.hitParam_alg_atot_thr},
                    {'name': hitParam_alg_son_min_str, 'type': 'float', 'value': self.hitParam_alg_son_min},
                    {'name': hitParam_alg1_thr_low_str, 'type': 'float', 'value': self.hitParam_alg1_thr_low},
                    {'name': hitParam_alg1_thr_high_str, 'type': 'float', 'value': self.hitParam_alg1_thr_high},
                    {'name': hitParam_alg1_radius_str, 'type': 'int', 'value': self.hitParam_alg1_radius},
                    {'name': hitParam_alg1_dr_str, 'type': 'float', 'value': self.hitParam_alg1_dr},
                ]},
                {'name': hitParam_algorithm2_str, 'visible': True, 'expanded': False, 'type': 'str', 'value': "", 'readonly': True, 'children': [
                    {'name': hitParam_alg2_thr_str, 'type': 'float', 'value': self.hitParam_alg2_thr},
                    {'name': hitParam_alg2_r0_str, 'type': 'float', 'value': self.hitParam_alg2_r0},
                    {'name': hitParam_alg2_dr_str, 'type': 'float', 'value': self.hitParam_alg2_dr},
                ]},
                {'name': hitParam_algorithm3_str, 'visible': True, 'expanded': False, 'type': 'str', 'value': "", 'readonly': True, 'children': [
                    {'name': hitParam_alg3_rank_str, 'type': 'int', 'value': self.hitParam_alg3_rank},
                    {'name': hitParam_alg3_r0_str, 'type': 'float', 'value': self.hitParam_alg3_r0},
                    {'name': hitParam_alg3_dr_str, 'type': 'float', 'value': self.hitParam_alg3_dr},
                ]},
            ]},
        ]
        self.initUI()

    def initUI(self):
        ## Define a top-level widget to hold everything
        self.win = QtGui.QMainWindow()
        self.area = DockArea()
        self.win.setCentralWidget(self.area)
        self.win.resize(1300,1400)
        self.win.setWindowTitle('psocake')

        ## Create tree of Parameter objects
        self.p = Parameter.create(name='params', type='group', \
                                  children=self.params, expanded=True)
        self.p1 = Parameter.create(name='paramsDiffractionGeometry', type='group', \
                                  children=paramsDiffractionGeometry, expanded=True)
        self.p.sigTreeStateChanged.connect(self.change)
        self.p1.sigTreeStateChanged.connect(self.changeGeomParam)

        #self.p.param('Basic parameter data types', 'Event Number').sigTreeStateChanged.connect(self.change)
        #self.p.param('Basic parameter data types', 'Float').sigTreeStateChanged.connect(save)
        
        ## Create docks, place them into the window one at a time.
        ## Note that size arguments are only a suggestion; docks will still have to
        ## fill the entire dock area and obey the limits of their internal widgets.
        self.d1 = Dock("Image Panel", size=(900, 900))     ## give this dock the minimum possible size
        self.d2 = Dock("Experiment Parameters", size=(500,300))
        self.d3 = Dock("Diffraction Geometry", size=(150,150))
        self.d4 = Dock("ROI Histogram", size=(200,200))
        self.d5 = Dock("Mouse", size=(100,50), closable=False)
        self.d6 = Dock("Image Control", size=(100, 100))
        self.d7 = Dock("Image Scroll", size=(500,500))

        # Set the color scheme
        def updateStylePatched(self):
            r = '3px'
            if self.dim:
                fg = cardinalRed_hex
                bg = sandstone100_rgb
                border = "white"
                pass
            else:
                fg = cardinalRed_hex
                bg = sandstone100_rgb
                border = "white" #sandstone100_rgb

            if self.orientation == 'vertical':
                self.vStyle = """DockLabel {
                    background-color : %s;
                    color : %s;
                    border-top-right-radius: 0px;
                    border-top-left-radius: %s;
                    border-bottom-right-radius: 0px;
                    border-bottom-left-radius: %s;
                    border-width: 0px;
                    border-right: 2px solid %s;
                    padding-top: 3px;
                    padding-bottom: 3px;
                    font-size: 18px;
                }""" % (bg, fg, r, r, border)
                self.setStyleSheet(self.vStyle)
            else:
                self.hStyle = """DockLabel {
                    background-color : %s;
                    color : %s;
                    border-top-right-radius: %s;
                    border-top-left-radius: %s;
                    border-bottom-right-radius: 0px;
                    border-bottom-left-radius: 0px;
                    border-width: 0px;
                    border-bottom: 2px solid %s;
                    padding-left: 13px;
                    padding-right: 13px;
                    font-size: 18px
                }""" % (bg, fg, r, r, border)
                self.setStyleSheet(self.hStyle)
        DockLabel.updateStyle = updateStylePatched

        # Dock positions on the main frame
        self.area.addDock(self.d1, 'left')      ## place d1 at left edge of dock area
        self.area.addDock(self.d6, 'bottom', self.d1)      ## place d1 at left edge of dock area
        self.area.addDock(self.d2, 'right')     ## place d2 at right edge of dock area
        self.area.addDock(self.d3, 'bottom', self.d2)## place d3 at bottom edge of d1
        self.area.addDock(self.d4, 'right')     ## place d4 at right edge of dock area
        self.area.addDock(self.d5, 'top', self.d1)  ## place d5 at left edge of d1
        self.area.addDock(self.d7, 'bottom', self.d4) ## place d7 below d4

        ## Dock 1: Image Panel
        self.w1 = pg.ImageView(view=pg.PlotItem())
        self.w1.getView().invertY(False)
        self.ring_feature = pg.ScatterPlotItem()
        self.peak_feature = pg.ScatterPlotItem()
        self.z_direction = pg.ScatterPlotItem()
        self.z_direction1 = pg.ScatterPlotItem()
        self.w1.getView().addItem(self.ring_feature)
        self.w1.getView().addItem(self.peak_feature)
        self.w1.getView().addItem(self.z_direction)
        self.w1.getView().addItem(self.z_direction1)
        # Custom ROI for selecting an image region
        self.roi = pg.ROI(pos=[900, 900], size=[50, 50], snapSize=1.0, scaleSnap=True, translateSnap=True)
        self.roi.addScaleHandle([0.5, 1], [0.5, 0.5])
        self.roi.addScaleHandle([0, 0.5], [0.5, 0.5])
        self.w1.getView().addItem(self.roi)
        #self.roi.setZValue(10)  # make sure ROI is drawn above image
        # Callbacks for handling user interaction
        def updateRoiHistogram():
            if self.data is not None:
                selected, coord = self.roi.getArrayRegion(self.data, self.w1.getImageItem(), returnMappedCoords=True)
                hist,bin = np.histogram(selected.flatten(), bins=1000)
                self.w4.plot(bin, hist, stepMode=True, fillLevel=0, brush=(0,0,255,150), clear=True)
        self.roi.sigRegionChanged.connect(updateRoiHistogram)
        # Connect listeners to functions
        self.d1.addWidget(self.w1)

        ## Dock 2: parameter
        self.w2 = ParameterTree()
        self.w2.setParameters(self.p, showTop=False)
        self.w2.setWindowTitle('Parameters')
        self.d2.addWidget(self.w2)

        ## Dock 3
        self.w3 = ParameterTree()
        self.w3.setParameters(self.p1, showTop=False)
        self.w3.setWindowTitle('Diffraction geometry')
        self.d3.addWidget(self.w3)

        ## Dock 4
        self.w4 = pg.PlotWidget(title="ROI histogram")
        hist,bin = np.histogram(np.random.random(1000), bins=1000)
        self.w4.plot(bin, hist, stepMode=True, fillLevel=0, brush=(0,0,255,150), clear=True)
        self.d4.addWidget(self.w4)

        ## Dock 5 - mouse intensity display
        #self.d5.hideTitleBar()
        self.w5 = pg.GraphicsView(background=pg.mkColor(sandstone100_rgb))
        self.d5.addWidget(self.w5)

        ## Dock 6: Image Control
        self.nextBtn = QtGui.QPushButton('Next evt')
        self.prevBtn = QtGui.QPushButton('Prev evt')
        self.saveBtn = QtGui.QPushButton('Save evt')
        self.generatePowderBtn = QtGui.QPushButton('Generate Powder')
        self.loadBtn = QtGui.QPushButton('Load image')
        def next():
            self.eventNumber += 1
            if self.eventNumber >= self.eventTotal:
                self.eventNumber = self.eventTotal-1
            else:
                self.calib, self.data = self.getDetImage(self.eventNumber)
                self.w1.setImage(self.data,autoRange=False,autoLevels=False,autoHistogramRange=False)
                self.p.param(exp_grp,exp_evt_str).setValue(self.eventNumber)
        def prev():
            self.eventNumber -= 1
            if self.eventNumber < 0:
                self.eventNumber = 0
            else:
                self.calib, self.data = self.getDetImage(self.eventNumber)
                self.w1.setImage(self.data,autoRange=False,autoLevels=False,autoHistogramRange=False)
                self.p.param(exp_grp,exp_evt_str).setValue(self.eventNumber)
        def save():
            outputName = "psocake_"+str(self.experimentName)+"_"+str(self.runNumber)+"_"+str(self.detInfo)+"_" \
                         +str(self.eventNumber)+"_"+str(self.eventSeconds)+"_"+str(self.eventNanoseconds)+"_" \
                         +str(self.eventFiducial)+".npy"
            fname = QtGui.QFileDialog.getSaveFileName(self, 'Save file', outputName, 'ndarray image (*.npy)')
            np.save(str(fname),self.calib)
        def load():
            fname = str(QtGui.QFileDialog.getOpenFileName(self, 'Open file', './', 'ndarray image (*.npy *.npz)'))
            print "fname: ", fname, fname.split('.')[-1]
            if fname.split('.')[-1] in '.npz':
                print "got npz"
                temp = np.load(fname)
                self.calib = temp['max']
            else:
                print "got npy"
                self.calib = np.load(fname)
            #self.data = self.getAssembledImage(self.calib)
            self.updateImage(self.calib)
        self.nextBtn.clicked.connect(next)
        self.prevBtn.clicked.connect(prev)
        self.saveBtn.clicked.connect(save)
        self.loadBtn.clicked.connect(load)
        # Layout
        self.w6 = pg.LayoutWidget()
        self.w6.addWidget(self.prevBtn, row=0, col=0)
        self.w6.addWidget(self.nextBtn, row=0, col=1)
        self.w6.addWidget(self.saveBtn, row=1, colspan=2)
        self.w6.addWidget(self.generatePowderBtn, row=2, col=0)
        self.w6.addWidget(self.loadBtn, row=2, col=1)
        self.d6.addWidget(self.w6)

        ## Dock 7: Image Scroll
        self.w7L = pg.LayoutWidget()
        self.w7 = pg.ImageView(view=pg.PlotItem())
        self.w7.getView().invertY(False)
        self.scroll = np.random.random((5,10,10))
        self.w7.setImage(self.scroll, xvals=np.linspace(0., self.scroll.shape[0]-1, self.scroll.shape[0]))

        #self.label = QtGui.QLabel("Event Number:")
        self.spinBox = QtGui.QSpinBox()
        self.spinBox.setValue(0)
        self.label = QtGui.QLabel("Event Number:")
        self.stackSizeBox = QtGui.QSpinBox()
        self.stackSizeBox.setMaximum(self.stackSize)
        self.stackSizeBox.setValue(self.stackSize)
        self.startBtn = QtGui.QPushButton("&Load image stack")

        # Connect listeners to functions
        self.w7L.addWidget(self.w7, row=0, colspan=4)
        self.w7L.addWidget(self.label, 1, 0)
        self.w7L.addWidget(self.spinBox, 1, 1)
        self.w7L.addWidget(self.stackSizeBox, 1, 2)
        self.w7L.addWidget(self.startBtn, 1, 3)
        self.d7.addWidget(self.w7L)

        ###############
        ### Threads ###
        ###############
        self.thread = []
        self.threadCounter = 0
        def addImage():
            print "##### addImage!!!!!!"
            self.w1.setImage(self.thread[0].data)
            #self.generatePowderBtn.setEnabled(True)
            print "#%@$%@# Done addImage!!!!!"
        def makePowder():
            print "makePowder!!!!!!"
            self.thread.append(Worker(self)) # send parent parameters with self
            self.connect(self.thread[self.threadCounter], QtCore.SIGNAL("finished()"), addImage)
            self.thread[self.threadCounter].computePowder(self.experimentName,self.runNumber,self.detInfo)
            self.threadCounter+=1
            #self.generatePowderBtn.setEnabled(False)
            print "done makePowder!!!!!!"
        #self.connect(self.thread, QtCore.SIGNAL("finished()"), addImage)
        #self.connect(self.thread, QtCore.SIGNAL("terminated()"), self.updateUi)
        #self.connect(self.thread, QtCore.SIGNAL("done"), self.addImage)
        self.connect(self.generatePowderBtn, QtCore.SIGNAL("clicked()"), makePowder)

        def displayImageStack():
            print "display image stack!!!!!!"
            if self.logscaleOn:
                self.w7.setImage(np.log10(abs(self.threadpool.data)+eps), xvals=np.linspace(self.stackStart,
                                                                     self.stackStart+self.threadpool.data.shape[0]-1,
                                                                     self.threadpool.data.shape[0]))
            else:
                self.w7.setImage(self.threadpool.data, xvals=np.linspace(self.stackStart,
                                                                     self.stackStart+self.threadpool.data.shape[0]-1,
                                                                     self.threadpool.data.shape[0]))
            self.startBtn.setEnabled(True)
            print "Done display image stack!!!!!"
        def loadStack():
            print "loading stack!!!!!!"
            self.stackStart = self.spinBox.value()
            self.stackSize = self.stackSizeBox.value()
            self.threadpool.load(self.stackStart,self.stackSize)
            self.startBtn.setEnabled(False)
            self.w7.getView().setTitle("exp="+self.experimentName+":run="+str(self.runNumber)+":evt"+str(self.stackStart)+"-"
                                       +str(self.stackStart+self.stackSize))
            print "done loading stack!!!!!!"

        self.threadpool = stackProducer(self) # send parent parameters
        self.connect(self.threadpool, QtCore.SIGNAL("finished()"), displayImageStack)
        self.connect(self.startBtn, QtCore.SIGNAL("clicked()"), loadStack)

        # Setup input parameters
        if self.experimentName is not "":
            self.hasExperimentName = True
            self.p.param(exp_grp,exp_name_str).setValue(self.experimentName)
            self.updateExpName(self.experimentName)
        if self.runNumber is not 0:
            self.hasRunNumber = True
            self.p.param(exp_grp,exp_run_str).setValue(self.runNumber)
            self.updateRunNumber(self.runNumber)
        if self.detInfo is not "":
            self.hasDetInfo = True
            self.p.param(exp_grp,exp_detInfo_str).setValue(self.detInfo)
            self.updateDetInfo(self.detInfo)
        self.p.param(exp_grp,exp_evt_str).setValue(self.eventNumber)
        self.updateEventNumber(self.eventNumber)

        self.drawLabCoordinates() # FIXME: This does not match the lab coordinates yet!

        # Try mouse over crosshair
        self.xhair = self.w1.getView()
        self.vLine = pg.InfiniteLine(angle=90, movable=False)
        self.hLine = pg.InfiniteLine(angle=0, movable=False)
        self.xhair.addItem(self.vLine, ignoreBounds=True)
        self.xhair.addItem(self.hLine, ignoreBounds=True)
        self.vb = self.xhair.vb
        self.label = pg.LabelItem()
        self.w5.addItem(self.label)

        def mouseMoved(evt):
            pos = evt[0]  ## using signal proxy turns original arguments into a tuple
            if self.xhair.sceneBoundingRect().contains(pos):
                mousePoint = self.vb.mapSceneToView(pos)
                indexX = int(mousePoint.x())
                indexY = int(mousePoint.y())
                
                # update crosshair position
                self.vLine.setPos(mousePoint.x())
                self.hLine.setPos(mousePoint.y())
                # get pixel value, if data exists
                if self.data is not None:
                    if indexX >= 0 and indexX < self.data.shape[0] \
                       and indexY >= 0 and indexY < self.data.shape[1]:
                        textInfo = "<span style='color: " + cardinalRed_hex + "; font-size: 24pt;'>x=%0.1f y=%0.1f I=%0.1f </span>"
                        self.label.setText(textInfo % (mousePoint.x(), mousePoint.y(), self.data[indexX,indexY]))

        self.proxy = pg.SignalProxy(self.xhair.scene().sigMouseMoved, rateLimit=60, slot=mouseMoved)

        self.win.show()
        #embed()

    def drawLabCoordinates(self):
        # Draw xy arrows
        symbolSize = 40
        cutoff=symbolSize/2
        headLen=30
        tailLen=30-cutoff
        xArrow = pg.ArrowItem(angle=180, tipAngle=30, baseAngle=20, headLen=headLen, tailLen=tailLen, tailWidth=8, pen=None, brush='b', pxMode=False)
        xArrow.setPos(2*headLen,0)
        self.w1.getView().addItem(xArrow)
        yArrow = pg.ArrowItem(angle=-90, tipAngle=30, baseAngle=20, headLen=headLen, tailLen=tailLen, tailWidth=8, pen=None, brush='r', pxMode=False)
        yArrow.setPos(0,2*headLen)
        self.w1.getView().addItem(yArrow)

        # z-direction
        self.z_direction.setData([0], [0], symbol='o', \
                                 size=symbolSize, brush='w', \
                                 pen={'color': 'k', 'width': 4}, pxMode=False)
        self.z_direction1.setData([0], [0], symbol='o', \
                                 size=symbolSize/6, brush='k', \
                                 pen={'color': 'k', 'width': 4}, pxMode=False)
        # Add xyz text
        self.x_text = pg.TextItem(html='<div style="text-align: center"><span style="color: #0000FF; font-size: 16pt;">x</span></div>', anchor=(0,0))
        self.w1.getView().addItem(self.x_text)
        self.x_text.setPos(2*headLen, 0)
        self.y_text = pg.TextItem(html='<div style="text-align: center"><span style="color: #FF0000; font-size: 16pt;">y</span></div>', anchor=(1,1))
        self.w1.getView().addItem(self.y_text)
        self.y_text.setPos(0, 2*headLen)
        self.z_text = pg.TextItem(html='<div style="text-align: center"><span style="color: #FFFFFF; font-size: 16pt;">z</span></div>', anchor=(1,0))
        self.w1.getView().addItem(self.z_text)
        self.z_text.setPos(-headLen, 0)

        # Label xy axes
        self.x_axis = self.w1.getView().getAxis('bottom')
        self.x_axis.setLabel('X-axis (pixels)')
        self.y_axis = self.w1.getView().getAxis('left')
        self.y_axis.setLabel('Y-axis (pixels)')

    def updateClassification(self):
        print("Running hit finder")
        # Peak output (0-16):
        # 0 seg
        # 1 row
        # 2 col
        # 3 npix: no. of pixels in the ROI intensities above threshold
        # 4 amp_max: max intensity
        # 5 amp_tot: sum of intensities
        # 6,7: row_cgrav: center of mass
        # 8,9: row_sigma
        # 10,11,12,13: minimum bounding box
        # 14: background
        # 15: noise
        # 16: signal over noise

        # Only initialize the hit finder algorithm once
        if self.algInitDone is False:
            self.windows = None
            self.mask = None
            self.alg = PyAlgos(windows=self.windows, mask=self.mask, pbits=0)

            # set peak-selector parameters:
            #alg.set_peak_selection_pars(npix_min=2, npix_max=50, amax_thr=10, atot_thr=20, son_min=5)
            self.alg.set_peak_selection_pars(npix_min=self.hitParam_alg_npix_min, npix_max=self.hitParam_alg_npix_max, \
                                        amax_thr=self.hitParam_alg_amax_thr, atot_thr=self.hitParam_alg_atot_thr, \
                                        son_min=self.hitParam_alg_son_min)
            self.algInitDone = True

        if self.algorithm == 1:
            # v1 - aka Droplet Finder - two-threshold peak-finding algorithm in restricted region
            #                           around pixel with maximal intensity.
            #peaks = alg.peak_finder_v1(nda, thr_low=5, thr_high=30, radius=5, dr=0.05)
            self.peaks = self.alg.peak_finder_v1(self.calib, thr_low=self.hitParam_alg1_thr_low, thr_high=self.hitParam_alg1_thr_high, \
                                       radius=int(self.hitParam_alg1_radius), dr=self.hitParam_alg1_dr)
        elif self.algorithm == 2:
            # v2 - define peaks for regions of connected pixels above threshold
            self.peaks = self.alg.peak_finder_v2(self.calib, thr=self.hitParam_alg2_thr, r0=self.hitParam_alg2_r0, dr=self.hitParam_alg2_dr)
        elif self.algorithm == 3:
            self.peaks = self.alg.peak_finder_v3(self.calib, rank=self.hitParam_alg3_rank, r0=self.hitParam_alg3_r0, dr=self.hitParam_alg3_dr)

        self.numPeaksFound = self.peaks.shape[0]
        print "peaks: ", self.peaks
        print "num peaks found: ", self.numPeaksFound, self.peaks.shape
        #sys.stdout.flush()
        self.drawPeaks()

    def drawPeaks(self):
        if self.peaks is not None and self.numPeaksFound > 0:
            iX  = np.array(self.det.indexes_x(self.evt), dtype=np.int64)
            iY  = np.array(self.det.indexes_y(self.evt), dtype=np.int64)
            cenX = iX[np.array(self.peaks[:,0],dtype=np.int64),np.array(self.peaks[:,1],dtype=np.int64),np.array(self.peaks[:,2],dtype=np.int64)]
            cenY = iY[np.array(self.peaks[:,0],dtype=np.int64),np.array(self.peaks[:,1],dtype=np.int64),np.array(self.peaks[:,2],dtype=np.int64)]
            diameter = 8
            self.peak_feature.setData(cenX, cenY, symbol='o', \
                                      size=diameter, brush=(255,255,255,0), \
                                      pen=pg.mkPen({'color': "FF0", 'width': 4}), pxMode=False)
        print "Done updatePeaks"

    def updateImage(self,calib=None):
        if self.hasExperimentName and self.hasRunNumber and self.hasDetInfo:
            if calib is None:
                self.calib, self.data = self.getDetImage(self.eventNumber)
            else:
                self.calib, self.data = self.getDetImage(self.eventNumber,calib=calib)

            if self.firstUpdate:
                if self.logscaleOn:
                    print "################################# 11"
                    self.w1.setImage(np.log10(abs(self.data)+eps))
                    self.firstUpdate = False
                else:
                    print "################################# 22"
                    self.w1.setImage(self.data)
                    self.firstUpdate = False
            else:
                if self.logscaleOn:
                    print "################################# 1"
                    self.w1.setImage(np.log10(abs(self.data)+eps),autoRange=False,autoLevels=False,autoHistogramRange=False)
                else:
                    print "################################# 2"
                    self.w1.setImage(self.data,autoRange=False,autoLevels=False,autoHistogramRange=False)
        print "Done updateImage"

    def updateRings(self):
        if self.resolutionRingsOn:
            self.clearRings()
            cenx = np.ones_like(self.myResolutionRingList)*self.cx
            ceny = np.ones_like(self.myResolutionRingList)*self.cy
            diameter = 2*self.myResolutionRingList
            print "self.myResolutionRingList, diameter: ", self.myResolutionRingList, diameter
            self.ring_feature.setData(cenx, ceny, symbol='o', \
                                      size=diameter, brush=(255,255,255,0), \
                                      pen='r', pxMode=False)
            for i,val in enumerate(self.dMin):
                self.resolutionText.append(pg.TextItem(text='%s A' % float('%.3g' % (val*1e10)), border='w', fill=(0, 0, 255, 100)))
                self.w1.getView().addItem(self.resolutionText[i])
                self.resolutionText[i].setPos(self.myResolutionRingList[i]+self.cx, self.cy)

        else:
            self.clearRings()
        print "Done updateRings"

    def clearRings(self):
        if self.resolutionText:
            print "going to clear rings: ", self.resolutionText, len(self.resolutionText)
            cen = [0,]
            self.ring_feature.setData(cen, cen, size=0)
            for i,val in enumerate(self.resolutionText):
                self.w1.getView().removeItem(self.resolutionText[i])
            self.resolutionText = []

    def getEvt(self,evtNumber):
        print "getEvt: ", evtNumber
        if self.hasRunNumber: #self.run is not None:
            evt = self.run.event(self.times[evtNumber])
            return evt
        else:
            return None

    def getCalib(self,evtNumber):
        if self.run is not None:
            self.evt = self.getEvt(evtNumber)
            if self.applyCommonMode:
                if self.commonMode[0] == 5: # Algorithm 5
                    calib = self.det.calib(self.evt, cmpars=(self.commonMode[0],self.commonMode[1]))
                else: # Algorithms 1 to 4
                    print "### Overriding common mode: ", self.commonMode
                    calib = self.det.calib(self.evt, cmpars=(self.commonMode[0],self.commonMode[1],self.commonMode[2],self.commonMode[3]))
            else:
                calib = self.det.calib(self.evt)
            return calib
        else:
            return None

    def getAssembledImage(self,calib):
        _calib = calib.copy() # this is important
        # Apply gain if available
        if self.det.gain(self.evt) is not None:
            _calib *= self.det.gain(self.evt)
        # Do not display ADUs below threshold
        _calib[np.where(_calib<self.aduThresh)]=0
        tic = time.time()
        data = self.det.image(self.evt, _calib)
        toc = time.time()
        print "time assemble: ", toc-tic
        return data

    def getDetImage(self,evtNumber,calib=None):
        if calib is None:
            calib = self.getCalib(evtNumber)
        if calib is not None:
            data = self.getAssembledImage(calib)
            self.cx, self.cy = self.getCentre(data.shape)
            print "cx,cy: ", self.cx, self.cy
            return calib, data
        else: # is opal
            data = self.det.raw(self.evt)
            # Do not display ADUs below threshold
            data[np.where(data<self.aduThresh)]=0
            self.cx, self.cy = self.getCentre(data.shape)
            print "cx,cy: ", self.cx, self.cy
            return data, data

    def getCentre(self, dim):
        cx = dim[0]/2
        cy = dim[1]/2
        return cx,cy

    def getEventID(self,evt):
        if evt is not None:
            evtid = evt.get(psana.EventId)
            seconds = evtid.time()[0]
            nanoseconds = evtid.time()[1]
            fiducials = evtid.fiducials()
            return seconds, nanoseconds, fiducials

    # If anything changes in the parameter tree, print a message
    def change(self, param, changes):
        for param, change, data in changes:
            path = self.p.childPath(param)
            print('  path: %s'% path)
            print('  change:    %s'% change)
            print('  data:      %s'% str(data))
            print('  ----------')
            self.update(path,change,data)

    def changeGeomParam(self, param, changes):
        for param, change, data in changes:
            path = self.p1.childPath(param)
            print('  path: %s'% path)
            print('  change:    %s'% change)
            print('  data:      %s'% str(data))
            print('  ----------')
            self.update(path,change,data)

    def update(self, path, change, data):
        print "path: ", path
        if path[0] == exp_grp:
            if path[1] == exp_name_str:
                self.updateExpName(data)
                if self.classify:
                    self.updateClassification()
            elif path[1] == exp_run_str:
                self.updateRunNumber(data)
                if self.classify:
                    self.updateClassification()
            elif path[1] == exp_detInfo_str:
                self.updateDetInfo(data)
                if self.classify:
                    self.updateClassification()
            elif path[1] == exp_evt_str and len(path) == 2 and change is 'value':
                self.updateEventNumber(data)
                if self.classify:
                    self.updateClassification()
        if path[0] == disp_grp:
            if path[1] == disp_log_str:
                self.updateLogscale(data)
            elif path[1] == disp_aduThresh_str:
                self.updateAduThreshold(data)

            elif path[2] == disp_commonModeParam0_str:
                self.updateCommonModeParam(data, 0)
            elif path[2] == disp_commonModeParam1_str:
                self.updateCommonModeParam(data, 1)
            elif path[2] == disp_commonModeParam2_str:
                self.updateCommonModeParam(data, 2)
            elif path[2] == disp_commonModeParam3_str:
                self.updateCommonModeParam(data, 3)
            elif path[2] == disp_overrideCommonMode_str:
                self.updateCommonMode(data)
        if path[0] == hitParam_grp:
            if path[1] == hitParam_algorithm_str:
                self.updateAlgorithm(data)
            elif path[1] == hitParam_classify_str:
                self.updateClassify(data)
            elif path[2] == hitParam_alg_npix_min_str:
                self.hitParam_alg_npix_min = data
                self.algInitDone = False
                if self.classify:
                    self.updateClassification()
            elif path[2] == hitParam_alg_npix_max_str:
                self.hitParam_alg_npix_max = data
                self.algInitDone = False
                if self.classify:
                    self.updateClassification()
            elif path[2] == hitParam_alg_amax_thr_str:
                self.hitParam_alg_amax_thr = data
                self.algInitDone = False
                if self.classify:
                    self.updateClassification()
            elif path[2] == hitParam_alg_atot_thr_str:
                self.hitParam_alg_atot_thr = data
                self.algInitDone = False
                if self.classify:
                    self.updateClassification()
            elif path[2] == hitParam_alg_son_min_str:
                self.hitParam_alg_son_min = data
                self.algInitDone = False
                if self.classify:
                    self.updateClassification()
            elif path[2] == hitParam_alg1_thr_low_str:
                self.hitParam_alg1_thr_low = data
                if self.classify:
                    self.updateClassification()
            elif path[2] == hitParam_alg1_thr_high_str:
                self.hitParam_alg1_thr_high = data
                if self.classify:
                    self.updateClassification()
            elif path[2] == hitParam_alg1_radius_str:
                self.hitParam_alg1_radius = data
                if self.classify:
                    self.updateClassification()
            elif path[2] == hitParam_alg1_dr_str:
                self.hitParam_alg1_dr = data
                if self.classify:
                    self.updateClassification()
            elif path[2] == hitParam_alg2_thr_str:
                self.hitParam_alg2_thr = data
                if self.classify:
                    self.updateClassification()
            elif path[2] == hitParam_alg2_r0_str:
                self.hitParam_alg2_r0 = data
                if self.classify:
                    self.updateClassification()
            elif path[2] == hitParam_alg2_dr_str:
                self.hitParam_alg2_dr = data
                if self.classify:
                    self.updateClassification()
            elif path[2] == hitParam_alg3_rank_str:
                self.hitParam_alg3_rank = data
                if self.classify:
                    self.updateClassification()
            elif path[2] == hitParam_alg3_r0_str:
                self.hitParam_alg3_r0 = data
                if self.classify:
                    self.updateClassification()
            elif path[2] == hitParam_alg3_dr_str:
                self.hitParam_alg3_dr = data
                if self.classify:
                    self.updateClassification()
        if path[0] == geom_grp:
            if path[1] == geom_detectorDistance_str:
                self.updateDetectorDistance(data)
            elif path[1] == geom_photonEnergy_str:
                self.updatePhotonEnergy(data)
            elif path[1] == geom_pixelSize_str:
                self.updatePixelSize(data)
            elif path[1] == geom_wavelength_str:
                pass
            elif path[1] == geom_resolutionRings_str and len(path) == 2:
                self.updateResolutionRings(data)
            elif path[2] == geom_resolution_str:
                self.updateResolution(data)

    ###################################
    ###### Experiment Parameters ######
    ###################################

    def updateExpName(self, data):
        self.experimentName = data
        self.hasExperimentName = True

        self.setupExperiment()

        self.updateImage()
        print "Done updateExperimentName:", self.experimentName

    def updateRunNumber(self, data):
        self.runNumber = data
        self.hasRunNumber = True

        self.setupExperiment()

        self.updateImage()
        print "Done updateRunNumber: ", self.runNumber

    def updateDetInfo(self, data):
        self.detInfo = data
        self.hasDetInfo = True
        self.setupExperiment()
        self.updateImage()
        print "Done updateDetInfo: ", self.detInfo

    def updateEventNumber(self, data):
        self.eventNumber = data
        if self.eventNumber >= self.eventTotal:
            self.eventNumber = self.eventTotal-1
        # update timestamps and fiducial
        self.evt = self.getEvt(self.eventNumber)
        if self.evt is not None:
            sec, nanosec, fid = self.getEventID(self.evt)
            self.eventSeconds = str(sec)
            self.eventNanoseconds = str(nanosec)
            self.eventFiducial = str(fid)
            self.updateEventID(self.eventSeconds, self.eventNanoseconds, self.eventFiducial)
            self.p.param(exp_grp,exp_evt_str).setValue(self.eventNumber)
            self.updateImage()
        print "Done updateEventNumber: ", self.eventNumber

    def hasExpRunInfo(self):
        if self.hasExperimentName and self.hasRunNumber:
            print "hasExpRunInfo: True"
            return True
        else:
            print "hasExpRunInfo: False"
            return False

    def hasExpRunDetInfo(self):
        if self.hasExperimentName and self.hasRunNumber and self.hasDetInfo:
            print "hasExpRunDetInfo: True"
            return True
        else:
            print "hasExpRunDetInfo: False"
            return False

    def setupExperiment(self):
        if self.hasExpRunInfo():
            if args.localCalib:
                print "Using local calib directory"
                psana.setOption('psana.calib-dir','./calib')
            self.ds = psana.DataSource('exp='+str(self.experimentName)+':run='+str(self.runNumber)+':idx') # FIXME: psana crashes if runNumber is non-existent
            self.run = self.ds.runs().next()
            self.times = self.run.times()
            self.eventTotal = len(self.times)
            self.spinBox.setMaximum(self.eventTotal-self.stackSize)
            self.p.param(exp_grp,exp_evt_str).setLimits((0,self.eventTotal-1))
            self.p.param(exp_grp,exp_evt_str,exp_numEvents_str).setValue(self.eventTotal)
            self.env = self.ds.env()

            evt = self.run.event(self.times[0])
            myAreaDetectors = []
            for k in evt.keys():
                if Detector.PyDetector.isAreaDetector(k.src()):
                    myAreaDetectors.append(k.alias())
            self.detInfoList = list(set(myAreaDetectors))
            print "# Available detectors: ", self.detInfoList

        if self.hasExpRunDetInfo():
            self.det = psana.Detector(str(self.detInfo), self.env)

            # Get epics variable, clen
            if "cxi" in self.experimentName:
                self.epics = self.ds.env().epicsStore()
                self.clen = self.epics.value('CXI:DS1:MMS:06.RBV')
                print "clen: ", self.clen
            print "Done setupExperiment"

    def updateLogscale(self, data):
        self.logscaleOn = data
        if self.hasExpRunDetInfo():
            self.firstUpdate = True # clicking logscale resets plot colorscale
            self.updateImage()
        print "Done updateLogscale: ", self.logscaleOn

    def updateAduThreshold(self, data):
        self.aduThresh = data
        if self.hasExpRunDetInfo():
            self.updateImage(self.calib)
        print "Done updateAduThreshold: ", self.aduThresh

    def updateResolutionRings(self, data):
        self.resolutionRingsOn = data
        if self.hasExpRunDetInfo():
            self.updateRings()
        print "Done updateResolutionRings: ", self.resolutionRingsOn

    def updateResolution(self, data):
        # convert to array of floats
        _resolution = data.split(',')
        self.resolution = np.zeros((len(_resolution,)))

        a = ['a','b','c','d','e','k','m','n','r','s']
        myStr = a[5]+a[8]+a[0]+a[5]+a[4]+a[7]
        if myStr in data:
            self.d42 = Dock("Console", size=(100,100))
            # build an initial namespace for console commands to be executed in (this is optional;
            # the user can always import these modules manually)
            namespace = {'pg': pg, 'np': np, 'self': self}
            # initial text to display in the console
            text = "You have awoken the "+myStr+"\nWelcome to psocake IPython: dir(self)"
            self.w42 = pg.console.ConsoleWidget(parent=None,namespace=namespace, text=text)
            self.d42.addWidget(self.w42)
            self.area.addDock(self.d42, 'bottom')
            data = ''

        if data != '':
            for i in range(len(_resolution)):
                self.resolution[i] = float(_resolution[i])

        if data != '':
            self.hasUserDefinedResolution = True
        else:
            self.hasUserDefinedResolution = False

        if self.hasGeometryInfo():
            self.updateGeometry()
        if self.hasExpRunDetInfo():
            self.updateRings()
        print "Done updateResolution: ", self.resolution, self.hasUserDefinedResolution

    def updateCommonModeParam(self, data, ind):
        self.commonModeParams[ind] = data
        self.updateCommonMode(self.applyCommonMode)
        print "Done updateCommonModeParam: ", self.commonModeParams

    def updateCommonMode(self, data):
        self.applyCommonMode = data
        if self.applyCommonMode:
            self.commonMode = self.checkCommonMode(self.commonModeParams)
        if self.hasExpRunDetInfo():
            self.setupExperiment()
            self.updateImage()
        print "Done updateCommonMode: ", self.commonMode

    def checkCommonMode(self, _commonMode):
        # TODO: cspad2x2 can only use algorithms 1 and 5
        _alg = int(_commonMode[0])
        if _alg >= 1 and _alg <= 4:
            _param1 = int(_commonMode[1])
            _param2 = int(_commonMode[2])
            _param3 = int(_commonMode[3])
            return (_alg,_param1,_param2,_param3)
        elif _alg == 5 and _numParams == 2:
            _param1 = int(_commonMode[1])
            return (_alg,_param1)
        else:
            print "Undefined common mode algorithm"
            return None

    def updateEventID(self, sec, nanosec, fid):
        print "eventID: ", sec, nanosec, fid
        self.p.param(exp_grp,exp_evt_str,exp_second_str).setValue(self.eventSeconds)
        self.p.param(exp_grp,exp_evt_str,exp_nanosecond_str).setValue(self.eventNanoseconds)
        self.p.param(exp_grp,exp_evt_str,exp_fiducial_str).setValue(self.eventFiducial)

    ########################
    ###### Hit finder ######
    ########################

    def updateAlgorithm(self, data):
        self.algorithm = data
        if self.classify:
            self.updateClassification()
        print "##### Done updateAlgorithm: ", self.algorithm

    def updateClassify(self, data):
        self.classify = data
        if self.classify:
            self.updateClassification()
        print "Done updateClassify: ", self.classify

    ##################################
    ###### Diffraction Geometry ######
    ##################################

    def updateDetectorDistance(self, data):
        self.detectorDistance = data
        if self.hasGeometryInfo():
            self.updateGeometry()

    def updatePhotonEnergy(self, data):
        self.photonEnergy = data
        # E = hc/lambda
        h = 6.626070e-34 # J.m
        c = 2.99792458e8 # m/s
        joulesPerEv = 1.602176621e-19 #J/eV
        self.wavelength = (h/joulesPerEv*c)/self.photonEnergy
        print "wavelength: ", self.wavelength
        self.p1.param(geom_grp,geom_wavelength_str).setValue(self.wavelength)
        if self.hasGeometryInfo():
            self.updateGeometry()

    def updatePixelSize(self, data):
        self.pixelSize = data
        if self.hasGeometryInfo():
            self.updateGeometry()

    def hasGeometryInfo(self):
        if self.detectorDistance is not None \
           and self.photonEnergy is not None \
           and self.pixelSize is not None:
            return True
        else:
            return False

    def updateGeometry(self):
        if self.hasUserDefinedResolution:
            self.myResolutionRingList = self.resolution
        else:
            self.myResolutionRingList = resolutionRingList
        self.dMin = np.zeros_like(self.myResolutionRingList)
        for i, pix in enumerate(self.myResolutionRingList):
            thetaMax = np.arctan(pix*self.pixelSize/self.detectorDistance)
            qMax = 2/self.wavelength*np.sin(thetaMax/2)
            self.dMin[i] = 1/qMax
            print "updateGeometry: ", i, thetaMax, qMax, self.dMin[i]
            if self.resolutionRingsOn:
                self.updateRings()

class Worker(QtCore.QThread):
    def __init__(self, parent = None):
        QtCore.QThread.__init__(self, parent)
        print "WORKER!!!!!!!!!!"
        #self.parent = parent
        self.experimentName = None
        self.runNumber = None
        self.detInfo = None

    def computePowder(self,experimentName,runNumber,detInfo):
        self.experimentName = experimentName
        self.runNumber = runNumber
        self.detInfo = detInfo
        self.start()

    def run(self):
        print "Doing WORK!!!!!!!!!!!!"
        # Command for submitting to batch
        cmd = "bsub -q psanaq -a mympi -n 36 -o %J.log python generatePowder.py exp="+self.experimentName+\
              ":run="+str(self.runNumber)+" -d "+self.detInfo
        print "Submitting batch job: ", cmd
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        out, err = process.communicate()
        jobid = out.split("<")[1].split(">")[0]
        myLog = jobid+".log"
        myKeyString = "The output (if any) is above this job summary."
        mySuccessString = "Successfully completed."
        notDone = 1
        havePowder = 0
        while notDone:
            if os.path.isfile(myLog):
                p = subprocess.Popen(["grep", myKeyString, myLog],stdout=subprocess.PIPE)
                output = p.communicate()[0]
                p.stdout.close()
                if myKeyString in output: # job has finished
                    # check job was a success or a failure
                    p = subprocess.Popen(["grep", mySuccessString, myLog], stdout=subprocess.PIPE)
                    output = p.communicate()[0]
                    p.stdout.close()
                    if mySuccessString in output: # success
                        print "successfully done"
                        havePowder = 1
                    else:
                        print "failed attempt"
                    notDone = 0
                else:
                    print "job hasn't finished yet"
                    time.sleep(10)
            else:
                print "no such file yet"
                time.sleep(10)


class stackProducer(QtCore.QThread):
    def __init__(self, parent = None):
        QtCore.QThread.__init__(self, parent)
        print "stack producer !!!!!!!!!!"
        self.parent = parent
        self.startIndex = 0
        self.numImages = 0
        self.evt = None
        self.data = None

    def load(self, startIndex, numImages):
        self.startIndex = startIndex
        self.numImages = numImages
        self.start()

    def run(self):
        print "Doing WORK!!!!!!!!!!!!: ", self.startIndex,self.startIndex+self.numImages
        counter = 0
        for i in np.arange(self.startIndex,self.startIndex+self.numImages):
            if counter == 0:
                calib,data = self.parent.getDetImage(i,calib=None)
                self.data = np.zeros((self.numImages,data.shape[0],data.shape[1]))
                if data is not None:
                    self.data[counter,:,:] = data
                counter += 1
            else:
                calib,data = self.parent.getDetImage(i,calib=None)
                if data is not None:
                    self.data[counter,:,:] = data
                counter += 1
        #self.emit(QtCore.SIGNAL("done"))
        #time.sleep(1)

def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QtGui.QApplication(sys.argv)
    ex = MainFrame(sys.argv)
    sys.exit(app.exec_())

## Start Qt event loop unless running in interactive mode or using pyside.
if __name__ == '__main__':
    main()