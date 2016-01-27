#!/usr/bin/env python
#usage: python xtc2cxidb.py -e cxic0415 -d DscCsPad -i /reg/d/psdm/cxi/cxic0415/res/reindex_cxic0415 --sample "selenobiotinyl streptavidin" --instrument CXI --pixelSize 110e-6 --coffset 0.588696 -r 14
#usage: python xtc2cxidb.py -e cxic0915 -d DscCsPad -i /reg/neh/home/yoon82/ana-current/psocake/src --sample "phyco" --instrument CXI --pixelSize 110e-6 --coffset 0.581 -r 24 --condition /entry_1/result_1/nPeaks,ge,20

import h5py
import numpy as np
import math
import psana
from IPython import embed
import matplotlib.pyplot as plt
import time
import argparse
import os

parser = argparse.ArgumentParser()
parser.add_argument("-e","--exp", help="psana experiment name (e.g. cxic0415)", type=str)
parser.add_argument("-r","--run", help="psana run number (e.g. 15)", type=int)
parser.add_argument("-d","--det",help="psana detector name (e.g. DscCsPad)", type=str)
parser.add_argument("-i","--indir",help="input directory where files_XXXX.lst exists (e.g. /reg/d/psdm/cxi/cxic0415/scratch)", type=str)
parser.add_argument("-o","--outdir",help="output directory (e.g. /reg/d/psdm/cxi/cxic0415/scratch)", type=str)
parser.add_argument("--sample",help="sample name (e.g. lysozyme)", type=str)
parser.add_argument("--instrument",help="instrument name (e.g. CXI)", type=str)
parser.add_argument("--coffset", help="camera offset, CXI home position to sample (m)", type=float)
parser.add_argument("--cxiVersion", help="cxi version",default=140, type=int)
parser.add_argument("--pixelSize", help="pixel size (m)", type=float)
parser.add_argument("--condition",help="comparator operation for choosing input data from an hdf5 dataset."
                                       "Must be double quotes and comma separated for now."
                                       "Available comparators are: gt(>), ge(>=), eq(==), le(<=), lt(<)"
                                       "e.g. /particleSize/corrCoef,ge,0.85 ",default='', type=str)
args = parser.parse_args()

inDir = args.indir
assert os.path.isdir(inDir)
if args.outdir is None:
    outDir = inDir
else:
    outDir = args.outdir
    assert os.path.isdir(outDir)
experimentName = args.exp
runNumber = args.run
detInfo = args.det
sampleName = args.sample
instrumentName = args.instrument
coffset = args.coffset
(x_pixel_size,y_pixel_size) = (args.pixelSize,args.pixelSize)

class psanaWhisperer():
    def __init__(self,experimentName,runNumber,detInfo):
        self.experimentName = experimentName
        self.runNumber = runNumber
        self.detInfo = detInfo

    def setupExperiment(self):
        self.ds = psana.DataSource('exp='+str(self.experimentName)+':run='+str(self.runNumber)+':idx')
        self.run = self.ds.runs().next()
        self.times = self.run.times()
        self.eventTotal = len(self.times)
        self.env = self.ds.env()
        self.evt = self.run.event(self.times[0])
        self.det = psana.Detector(str(self.detInfo), self.env)
        self.gain = self.det.gain(self.evt)
        # Get epics variable, clen
        if "cxi" in self.experimentName:
            self.epics = self.ds.env().epicsStore()
            self.clen = self.epics.value('CXI:DS1:MMS:06.RBV')

    def getEvent(self,number):
        self.evt = self.run.event(self.times[number])
    
    def getImg(self,number):
        self.getEvent(number)
        img = self.det.image(self.evt, self.det.calib(self.evt)*self.gain)
        return img

    def getImg(self):
        if self.evt is not None:
            img = self.det.image(self.evt, self.det.calib(self.evt)*self.gain)
            return img
        return None

    def getCheetahImg(self):
        """Converts seg, row, col assuming (32,185,388)
           to cheetah 2-d table row and col (8*185, 4*388)
        """
        calib = self.det.calib(self.evt)*self.gain # (32,185,388)
        img = np.zeros((8*185, 4*388))
        counter = 0
        for quad in range(4):
            for seg in range(8):
                img[seg*185:(seg+1)*185,quad*388:(quad+1)*388] = calib[counter,:,:]
                counter += 1
        return img

    def getPsanaEvent(self,cheetahFilename):
        # Gets psana event given cheetahFilename, e.g. LCLS_2015_Jul26_r0014_035035_e820.h5
        hrsMinSec = cheetahFilename.split('_')[-2]
        fid = int(cheetahFilename.split('_')[-1].split('.')[0],16)
        for t in ps.times:
            if t.fiducial() == fid:
                localtime = time.strftime('%H:%M:%S',time.localtime(t.seconds()))
                localtime = localtime.replace(':','')
                if localtime[0:3] == hrsMinSec[0:3]: 
                    self.evt = ps.run.event(t)
                else:
                    self.evt = None

    def getStartTime(self):
        self.evt = self.run.event(self.times[0])
        evtId = self.evt.get(psana.EventId)
        sec = evtId.time()[0]
        nsec = evtId.time()[1]
        fid = evtId.fiducials()
        return time.strftime('%FT%H:%M:%S-0800',time.localtime(sec)) # Hard-coded pacific time

ps = psanaWhisperer(experimentName,runNumber,detInfo)
ps.setupExperiment()
startTime = ps.getStartTime()
numEvents = ps.eventTotal
es = ps.ds.env().epicsStore()
pulseLength = es.value('SIOC:SYS0:ML00:AO820')*1e-15 # s
numPhotons = es.value('SIOC:SYS0:ML00:AO580')*1e12 # number of photons
ebeam = ps.evt.get(psana.Bld.BldDataEBeamV7, psana.Source('BldInfo(EBeam)'))
photonEnergy = ebeam.ebeamPhotonEnergy() * 1.60218e-19 # J
pulseEnergy = ebeam.ebeamL3Energy() # MeV
detectorDistance = coffset + ps.clen*1e-3 # sample to detector in m

# Read list of files
runStr = "%04d" % runNumber
filename = inDir+'/'+experimentName+'_'+runStr+'.cxi'
print "Reading file: %s" % (filename)

f          = h5py.File(filename, "r+")
# Condition:
if args.condition:
    import operator
    operations = {"lt":operator.lt,
                  "le":operator.le,
                  "eq":operator.eq,
                  "ge":operator.ge,
                  "gt":operator.gt,}

    s = args.condition.split(",")
    ds = s[0] # hdf5 dataset containing metric
    comparator = s[1] # operation
    cond = float(s[2]) # conditional value
    print "######### ds,comparator,cond: ", ds,comparator,cond

    metric = f[ds].value
    hitInd = np.argwhere(operations[comparator](metric,cond))
    numHits = len(hitInd)
    print "hitInd: ", hitInd, numHits

print "start time: ", startTime
print "number of hits/events: ", numHits,numEvents
print "pulseLength (s): ", pulseLength
print "number of photons : ", numPhotons
print "photon energy (eV,J): ", ebeam.ebeamPhotonEnergy(), photonEnergy
print "pulse energy (MeV): ", pulseEnergy
print "detector distance (m): ", detectorDistance

if 0:
    ps.getEvent(hitInd[0])
    img = ps.getCheetahImg()
    plt.imshow(np.log10(img),interpolation='none')
    plt.show()

ps.getEvent(hitInd[0])
img = ps.getCheetahImg()
(dim0,dim1) = img.shape

# open the HDF5 CXI file for writing
if "cxi_version" in f:
    del f["cxi_version"]
f.create_dataset("cxi_version",data=args.cxiVersion)

###################
# LCLS
###################
if "LCLS" in f:
    del f["LCLS"]
lcls_1 = f.create_group("LCLS")
lcls_detector_1 = lcls_1.create_group("detector_1")
ds_lclsDet_1 = lcls_detector_1.create_dataset("EncoderValue",(numHits,))
ds_lclsDet_1.attrs["axes"] = "experiment_identifier"
ds_lclsDet_1.attrs["numEvents"] = numHits
ds_ebeamCharge_1 = lcls_1.create_dataset("electronBeamEnergy",(numHits,))
ds_ebeamCharge_1.attrs["axes"] = "experiment_identifier"
ds_ebeamCharge_1.attrs["numEvents"] = numHits
ds_beamRepRate_1 = lcls_1.create_dataset("beamRepRate",(numHits,))
ds_beamRepRate_1.attrs["axes"] = "experiment_identifier"
ds_beamRepRate_1.attrs["numEvents"] = numHits
ds_particleN_electrons_1 = lcls_1.create_dataset("particleN_electrons",(numHits,))
ds_particleN_electrons_1.attrs["axes"] = "experiment_identifier"
ds_particleN_electrons_1.attrs["numEvents"] = numHits
ds_eVernier_1 = lcls_1.create_dataset("eVernier",(numHits,))
ds_eVernier_1.attrs["axes"] = "experiment_identifier"
ds_eVernier_1.attrs["numEvents"] = numHits
ds_charge_1 = lcls_1.create_dataset("charge",(numHits,))
ds_charge_1.attrs["axes"] = "experiment_identifier"
ds_charge_1.attrs["numEvents"] = numHits
ds_peakCurrentAfterSecondBunchCompressor_1 = lcls_1.create_dataset("peakCurrentAfterSecondBunchCompressor",(numHits,))
ds_peakCurrentAfterSecondBunchCompressor_1.attrs["axes"] = "experiment_identifier"
ds_peakCurrentAfterSecondBunchCompressor_1.attrs["numEvents"] = numHits
ds_pulseLength_1 = lcls_1.create_dataset("pulseLength",(numHits,))
ds_pulseLength_1.attrs["axes"] = "experiment_identifier"
ds_pulseLength_1.attrs["numEvents"] = numHits
ds_ebeamEnergyLossConvertedToPhoton_mJ_1 = lcls_1.create_dataset("ebeamEnergyLossConvertedToPhoton_mJ",(numHits,))
ds_ebeamEnergyLossConvertedToPhoton_mJ_1.attrs["axes"] = "experiment_identifier"
ds_ebeamEnergyLossConvertedToPhoton_mJ_1.attrs["numEvents"] = numHits
ds_calculatedNumberOfPhotons_1 = lcls_1.create_dataset("calculatedNumberOfPhotons",(numHits,))
ds_calculatedNumberOfPhotons_1.attrs["axes"] = "experiment_identifier"
ds_calculatedNumberOfPhotons_1.attrs["numEvents"] = numHits
ds_photonBeamEnergy_1 = lcls_1.create_dataset("photonBeamEnergy",(numHits,))
ds_photonBeamEnergy_1.attrs["axes"] = "experiment_identifier"
ds_photonBeamEnergy_1.attrs["numEvents"] = numHits
ds_wavelength_1 = lcls_1.create_dataset("wavelength",(numHits,))
ds_wavelength_1.attrs["axes"] = "experiment_identifier"
ds_wavelength_1.attrs["numEvents"] = numHits
ds_sec_1 = lcls_1.create_dataset("machineTime",(numHits,),dtype=int)
ds_sec_1.attrs["axes"] = "experiment_identifier"
ds_sec_1.attrs["numEvents"] = numHits
ds_nsec_1 = lcls_1.create_dataset("machineTimeNanoSeconds",(numHits,),dtype=int)
ds_nsec_1.attrs["axes"] = "experiment_identifier"
ds_nsec_1.attrs["numEvents"] = numHits
ds_fid_1 = lcls_1.create_dataset("fiducial",(numHits,),dtype=int)
ds_fid_1.attrs["axes"] = "experiment_identifier"
ds_fid_1.attrs["numEvents"] = numHits
ds_photonEnergy_1 = lcls_1.create_dataset("photon_energy_eV", (numHits,)) # photon energy in eV
ds_photonEnergy_1.attrs["axes"] = "experiment_identifier"
ds_photonEnergy_1.attrs["numEvents"] = numHits
ds_wavelengthA_1 = lcls_1.create_dataset("photon_wavelength_A",(numHits,))
ds_wavelengthA_1.attrs["axes"] = "experiment_identifier"
ds_wavelengthA_1.attrs["numEvents"] = numHits
###################
# entry_1
###################
entry_1 = f.require_group("entry_1")

dt = h5py.special_dtype(vlen=bytes)
if "experimental_identifier" in entry_1:
    del entry_1["experimental_identifier"]
ds_expId = entry_1.create_dataset("experimental_identifier",(numHits,),dtype=dt)
ds_expId.attrs["axes"] = "experiment_identifier"
ds_expId.attrs["numEvents"] = numHits

if "start_time" in entry_1:
    del entry_1["start_time"]
entry_1.create_dataset("start_time",data=startTime)

if "sample_1" in entry_1:
    del entry_1["sample_1"]
sample_1 = entry_1.create_group("sample_1")
sample_1.create_dataset("name",data=sampleName)

if "instrument_1" in entry_1:
    del entry_1["instrument_1"]
instrument_1 = entry_1.create_group("instrument_1")
instrument_1.create_dataset("name",data=instrumentName)

source_1 = instrument_1.create_group("source_1")
ds_photonEnergy = source_1.create_dataset("energy", (numHits,)) # photon energy in J
ds_photonEnergy.attrs["axes"] = "experiment_identifier"
ds_photonEnergy.attrs["numEvents"] = numHits
ds_pulseEnergy = source_1.create_dataset("pulse_energy", (numHits,)) # in J
ds_pulseEnergy.attrs["axes"] = "experiment_identifier"
ds_pulseEnergy.attrs["numEvents"] = numHits
ds_pulseWidth = source_1.create_dataset("pulse_width", (numHits,)) # in s
ds_pulseWidth.attrs["axes"] = "experiment_identifier"
ds_pulseWidth.attrs["numEvents"] = numHits

detector_1 = instrument_1.create_group("detector_1")
ds_dist_1 = detector_1.create_dataset("distance", (numHits,)) # in meters
ds_dist_1.attrs["axes"] = "experiment_identifier"
ds_dist_1.attrs["numEvents"] = numHits
ds_x_pixel_size_1 = detector_1.create_dataset("x_pixel_size", (numHits,))
ds_x_pixel_size_1.attrs["axes"] = "experiment_identifier"
ds_x_pixel_size_1.attrs["numEvents"] = numHits
ds_y_pixel_size_1 = detector_1.create_dataset("y_pixel_size", (numHits,))
ds_y_pixel_size_1.attrs["axes"] = "experiment_identifier"
ds_y_pixel_size_1.attrs["numEvents"] = numHits
dset_1 = detector_1.create_dataset("data",(numHits,dim0,dim1),
                                   chunks=(1,dim0,dim1),
                                   compression='gzip',
                                   compression_opts=9)
dset_1.attrs["axes"] = "experiment_identifier:y:x"
dset_1.attrs["numEvents"] = numHits
detector_1.create_dataset("description",data=detInfo)

# Soft links
if "data_1" in entry_1:
    del entry_1["data_1"]
data_1 = entry_1.create_group("data_1")
data_1["data"] = h5py.SoftLink('/entry_1/instrument_1/detector_1/data')
source_1["experimental_identifier"] = h5py.SoftLink('/entry_1/experimental_identifier')

# create data 1
for i,val in enumerate(hitInd):
    # entry_1
    ds_expId[i] = val #cheetahfilename.split("/")[-1].split(".")[0]

    ps.getEvent(val)
    img = ps.getCheetahImg()
    assert(img is not None)
    dset_1[i,:,:] = img

    es = ps.ds.env().epicsStore()
    pulseLength = es.value('SIOC:SYS0:ML00:AO820')*1e-15 # s
    numPhotons = es.value('SIOC:SYS0:ML00:AO580')*1e12 # number of photons
    ebeam = ps.evt.get(psana.Bld.BldDataEBeamV7, psana.Source('BldInfo(EBeam)'))
    photonEnergy = ebeam.ebeamPhotonEnergy() * 1.60218e-19 # J
    pulseEnergy = ebeam.ebeamL3Energy() # MeV

    ds_photonEnergy_1[i] = ebeam.ebeamPhotonEnergy()
    ds_photonEnergy[i] = photonEnergy
    ds_pulseEnergy[i] = pulseEnergy
    ds_pulseWidth[i] = pulseLength
    
    ds_dist_1[i] = detectorDistance
    
    ds_x_pixel_size_1[i] = x_pixel_size
    ds_y_pixel_size_1[i] = y_pixel_size

    # LCLS
    ds_lclsDet_1[i] = es.value('CXI:DS1:MMS:06.RBV') # mm
    ds_ebeamCharge_1[i] = es.value('BEND:DMP1:400:BDES')
    try:
        ds_beamRepRate_1[i] = es.value('EVNT:SYS0:1:LCLSBEAMRATE')
    except:
        ds_beamRepRate_1[i] = 0
    try:
        ds_particleN_electrons_1[i] = es.value('BPMS:DMP1:199:TMIT1H')
    except:
        ds_particleN_electrons_1[i] = 0
    ds_eVernier_1[i] = es.value('SIOC:SYS0:ML00:AO289')
    ds_charge_1[i] = es.value('BEAM:LCLS:ELEC:Q')
    ds_peakCurrentAfterSecondBunchCompressor_1[i] = es.value('SIOC:SYS0:ML00:AO195')
    ds_pulseLength_1[i] = es.value('SIOC:SYS0:ML00:AO820')
    ds_ebeamEnergyLossConvertedToPhoton_mJ_1[i] = es.value('SIOC:SYS0:ML00:AO569')
    ds_calculatedNumberOfPhotons_1[i] = es.value('SIOC:SYS0:ML00:AO580')
    ds_photonBeamEnergy_1[i] = es.value('SIOC:SYS0:ML00:AO541')
    ds_wavelength_1[i] = es.value('SIOC:SYS0:ML00:AO192')
    ds_wavelengthA_1[i] = ds_wavelength_1[i] * 10.

    evtId = ps.evt.get(psana.EventId)
    sec = evtId.time()[0]
    nsec = evtId.time()[1]
    fid = evtId.fiducials()
    ds_sec_1[i] = sec
    ds_nsec_1[i] = nsec
    ds_fid_1[i] = fid

f.close()
