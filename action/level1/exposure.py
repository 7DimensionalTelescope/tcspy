#%%
from multiprocessing import Event
from multiprocessing import Manager

from tcspy.devices import SingleTelescope
from tcspy.devices import TelescopeStatus
from tcspy.interfaces import *
from tcspy.utils.target import SingleTarget
from tcspy.utils.image import mainImage
from tcspy.utils.logger import mainLogger
from tcspy.utils.exception import *
from tcspy.action.level1.changefilter import ChangeFilter

class Exposure(Interface_Runnable, Interface_Abortable):

    def __init__(self, 
                 singletelescope : SingleTelescope,
                 abort_action : Event):
        self.telescope = singletelescope
        self.telescope_status = TelescopeStatus(self.telescope)
        self.abort_action = abort_action
        self.shared_memory_manager = Manager()
        self.shared_memory = self.shared_memory_manager.dict()
        self.shared_memory['succeeded'] = False
        self.shared_memory['exception'] = None
        self.shared_memory['is_running'] = False
        self.is_running = False

    def run(self,
            # Exposure information
            frame_number : int,
            exptime : float,
            obsmode : str = 'Single',
            filter_ : str = None,
            specmode : str = None,
            colormode : str = None,
            ntelescope : int = 1,
            gain = 16,
            binning : int = 1,
            imgtype : str = 'Light',

            # Target information            
            ra : float = None,
            dec : float = None,
            alt : float = None,
            az : float = None,
            name : str = '',
            objtype : str = None,
            id_ : str = None,
            note : str = None,
            comment : str = None,
            is_ToO: bool = False,
            is_rapidToO : bool = False
            ):
        """
        Performs the action to expose the camera, saves the image, and returns True if successful.

        Parameters
        ----------
        frame_number : int
            The number of the frame that is to be exposed.
        exptime : float
            The exposure time in seconds.
        filter_ : str, optional
            The filter that should be used during exposure.
        imgtype : str, optional
            The type of image to be taken. Defaults to 'Light'.
        binning : int, optional
            Binning factor for camera sensor. Defaults to 1.
        obsmode : str, optional
            The mode of observation. Defaults to 'Single'.
        gain : int, optional
            The gain setting for the camera sensor. Defaults to 0.
        ra, dec : float, optional
            Right Ascension and Declination, respectively, of the target in degrees.
        alt, az : float, optional
            Altitude and Azimuth, respectively, of the target in degrees
        name : str, optional
            Name of the target. 
        objtype : str, optional
            Type of the object targeted.


        Raises
        ------
        ConnectionException
            If the camera or the filterwheel is disconnected.
        ActionFailedException
            If there is an error during the change of filter or exposure.
        AbortionException
            If the operation is aborted.
        """
                
        """
        frame_number : int = 1
        exptime : float = 10
        obsmode : str = 'Single'
        filter_ : str = 'r'
        specmode : str = None
        ntelescope : int = 1
        gain = 0
        binning : int = 1
        imgtype : str = 'Light'

        # Target information            
        ra : float = None
        dec : float = None
        alt : float = None
        az : float = None
        name : str = ''
        objtype : str = None
        id_ : str = None
        note : str = None
        """
        # Check condition of the instruments for this Action
        self.telescope.register_logfile()
        self.telescope.log.info(f'=====LV1[{type(self).__name__}] is triggered.')
        self.is_running = True
        self.shared_memory['is_running'] = True
        self.shared_memory['succeeded'] = False
        status_filterwheel = self.telescope_status.filterwheel
        status_camera = self.telescope_status.camera
        trigger_abort_disconnected = False
        if status_camera.lower() == 'disconnected':
            trigger_abort_disconnected = True
            self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: camera is disconnected.')
        if status_filterwheel.lower() == 'disconnected':
            trigger_abort_disconnected = True
            self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: filterwheel is disconnected.')
        if trigger_abort_disconnected:
            self.shared_memory['exception'] = 'ConnectionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ConnectionException(f'[{type(self).__name__}] is failed: devices are disconnected.')
        
        # If not aborted, execute the action
        if self.abort_action.is_set():
            self.telescope.camera.wait_idle()
            self.telescope.log.warning(f'=====LV1[{type(self).__name__}] is aborted.')
            self.shared_memory['exception'] = 'AbortionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise AbortionException(f'[{type(self).__name__}] is aborted.')  
                
        # Set target
        target = SingleTarget(observer = self.telescope.observer, 
                              ra = ra, 
                              dec = dec, 
                              alt = alt, 
                              az = az, 
                              name = name, 
                              objtype= objtype,
                              id_ = id_,
                              note = note,
                              comment = comment,
                              is_ToO = is_ToO,
                              is_rapidToO=is_rapidToO,
                              exptime = exptime,
                              count = 1,
                              filter_ = filter_,
                              binning = binning, 
                              gain = gain,
                              obsmode = obsmode,
                              specmode = specmode,
                              colormode = colormode,
                              ntelescope = ntelescope
                              )
        # Move filter
        result_changefilter = True
        if imgtype.upper() == 'LIGHT':
            if not filter_:
                self.telescope.log.critical(f'=====LV1[{type(self).__name__}] Filter must be determined for LIGHT frame')
                self.shared_memory['exception'] = 'ActionFailedException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ActionFailedException('Filter must be determined for LIGHT frame')
            info_filterwheel = self.telescope.filterwheel.get_status()
            current_filter = info_filterwheel['filter_']
            do_filterchange = (current_filter != filter_)
            if do_filterchange:
                changefilter = ChangeFilter(singletelescope = self.telescope, abort_action = self.abort_action)    
                try:
                    result_changefilter = changefilter.run(str(filter_))
                except ConnectionException:
                    self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: filterwheel is disconnected.')
                    self.shared_memory['exception'] = 'ConnectionException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise ConnectionException(f'[{type(self).__name__}] is failed: filterwheel is disconnected.')
                except AbortionException:
                    self.telescope.camera.wait_idle()
                    self.telescope.log.warning(f'=====LV1[{type(self).__name__}] is aborted.')
                    self.shared_memory['exception'] = 'AbortionException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise AbortionException(f'[{type(self).__name__}] is aborted.')  
                except ActionFailedException:
                    self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: filterchange failure.')
                    self.shared_memory['exception'] = 'ActionFailedException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise ActionFailedException(f'[{type(self).__name__}] is failed: filterchange failure.')

        # Check device connection
        camera = self.telescope.camera
        status_camera = self.telescope_status.camera

        if status_camera.lower() == 'disconnected':
            self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: camera is disconnected.')
            self.shared_memory['exception'] = 'ConnectionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ConnectionException(f'[{type(self).__name__}] is failed: camera is disconnected.')
        elif status_camera.lower() == 'busy':
            self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: camera is busy.')
            self.shared_memory['exception'] = 'ActionFailedException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ActionFailedException(f'[{type(self).__name__}] is failed: camera is busy.')
        elif status_camera.lower() == 'idle':
            # Exposure camera
            if imgtype.upper() == 'BIAS':
                exptime = camera.device.ExposureMin
                self.telescope.log.warning(f'[{type(self).__name__}]Input exposure time is set to the minimum value for BIAS image')
                is_light = False
            elif imgtype.upper() == 'DARK':
                is_light = False
            elif imgtype.upper() == 'FLAT':
                is_light = True
            else:
                is_light = True
            self.telescope.log.info(f'[{type(self).__name__}]Start exposure %s frame... (exptime = %.1f, filter = %s, binning = %s, gain = %s)'%(imgtype.upper(), exptime, filter_, binning, gain))
            try:
                imginfo = camera.exposure(exptime = float(exptime),
                                          imgtype = imgtype,
                                          binning = int(binning),
                                          is_light = is_light,
                                          gain = gain,
                                          abort_action = self.abort_action)
                
            except ExposureFailedException:
                self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: camera exposure failure.')
                self.shared_memory['exception'] = 'ActionFailedException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ActionFailedException(f'[{type(self).__name__}] is failed: camera exposure failure.')
            except AbortionException:
                self.telescope.log.warning(f'=====LV1[{type(self).__name__}] is aborted.')
                self.shared_memory['exception'] = 'AbortionException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise AbortionException(f'[{type(self).__name__}] is aborted.')
            if imginfo:
                self.telescope.log.info(f'[{type(self).__name__}] Exposure finished (exptime = %.1f, filter = %s, binning = %s, gain = %s)'%(exptime, filter_, binning, gain))
            
            status = self.telescope.status
            try:
                img = mainImage(frame_number = int(frame_number),
                                config_info = self.telescope.config,
                                image_info = imginfo,
                                camera_info = status['camera'],
                                mount_info = status['mount'],
                                filterwheel_info = status['filterwheel'],
                                focuser_info = status['focuser'],
                                observer_info = status['observer'],
                                target_info = target.status,
                                weather_info = status['weather'])
                filepath = img.save()
                self.telescope.log.info(f'[{type(self).__name__}] Image Saved: %s'%(filepath))
                self.shared_memory['succeeded'] = True
            except Exception:
                self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: mainImage save failure.', exc_info=True)
                self.shared_memory['exception'] = 'ActionFailedException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ActionFailedException(f'[{type(self).__name__}] is failed: mainImage save failure.')
        
        self.shared_memory['is_running'] = False
        self.is_running = False
        self.telescope.log.info(f'=====LV1[{type(self).__name__}] is finished.')
        if self.shared_memory['succeeded']:
            return True

    def abort(self):
        self.telescope.register_logfile()
        self.abort_action.set()
        self.telescope.camera.wait_idle()
        self.telescope.log.warning(f'=====LV1[{type(self).__name__}] is aborted.')
        self.shared_memory['exception'] = 'AbortionException'
        self.shared_memory['is_running'] = False
        self.is_running = False
        raise AbortionException(f'[{type(self).__name__}] is aborted.')      