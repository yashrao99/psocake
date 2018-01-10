import ChooseMethod
import os

class Crystfel(object):

    def __init__(self, expDir = None, darkcal = None, gaincal = None, geomgeo = None, geomh5 = None, badpix = None, peakmask = None):

        self.expDir = expDir
        self.darkcal = []
        self.gaincal = []
        self.geomgeo = []
        self.geomh5 = []
        self.badpix = []
        self.peakmask = []


    def SetExpDir(self, instrument, expName, **kwargs):

        lowerInst = instrument.lower()
        lowerExpName = expName.lower()

        # The extraPath variable must end with a '/'
        extraPath = kwargs.get('extraPath', '')

        self.expDir = '/reg/d/psdm/' + lowerInst + '/' + lowerExpName + '/' + extraPath


    def GetCalibInfo(self, topDown=True):

        expDir = self.expDir
        cheetahPath = 'cheetah/calib'
        calibPath = expDir + cheetahPath

        for dirPath, subDirs, files in os.walk(calibPath):
            for file in files:
                if file.endswith(".h5") and "darkcal" in file:
                    self.darkcal.append(os.path.join(dirPath,file))

                elif file.endswith(".h5") and "gainmap" in file:
                    self.gaincal.append(os.path.join(dirPath,file))

                elif file.endswith(".h5") and "cspad" in file:
                    self.geomh5.append(os.path.join(dirPath,file))

                elif file.endswith(".geom") and "cspad" in file:
                    self.geomgeo.append(os.path.join(dirPath,file))

                elif file.endswith(".h5") and "badpix" in file:
                    self.badpix.append(os.path.join(dirPath,file))

