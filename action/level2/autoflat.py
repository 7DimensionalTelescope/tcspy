#%%
from multiprocessing import Event
from multiprocessing import Manager

from tcspy.configuration import mainConfig
from tcspy.devices import SingleTelescope
from tcspy.devices import TelescopeStatus
from tcspy.interfaces import *
from tcspy.utils.error import *
from tcspy.utils.logger import mainLogger
from tcspy.action.level1 import SlewRADec
from tcspy.action.level1 import SlewAltAz
from tcspy.action.level1 import ChangeFocus
from tcspy.action.level1 import ChangeFilter
from tcspy.action.level1 import Exposure


from tcspy.utils.image import mainImage
from tcspy.utils.target import SingleTarget
from tcspy.action.level2 import AutoFocus
from tcspy.utils.exception import *
import numpy as np
import time
import uuid
#%%
class AutoFlat(Interface_Runnable, Interface_Abortable):
    def __init__(self, 
                 singletelescope : SingleTelescope,
                 abort_action : Event):
        self.telescope = singletelescope
        self.telescope_status = TelescopeStatus(self.telescope)
        self.abort_action = abort_action
        self.shared_memory_manager = Manager()
        self.shared_memory = self.shared_memory_manager.dict()
        self.shared_memory['status'] = dict()
        self.shared_memory['succeeded'] = False
        self.shared_memory['exception'] = None
        self.shared_memory['is_running'] = False
        self.is_running = False
        self.is_focus_changed = False
    
    def run(self,
            count : int = 9,
            gain : int = 2750,
            binning : int = 1):
        self.telescope.register_logfile()
        self.telescope.log.info(f'==========LV2[{type(self).__name__}] is triggered.')
        self.is_running = True
        self.shared_memory['is_running'] = True
        self.shared_memory['succeeded'] = False

        if (self.telescope.safetymonitor.get_status()['is_safe'] == False) | (self.telescope.weather.get_status()['is_safe'] == False):
            self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is failed: Unsafe weather.')
            self.shared_memory['exception'] = 'ActionFailedException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ActionFailedException(f'[{type(self).__name__}] is failed: Unsafe weather.')
        
        # Check condition of the instruments for this Action
        status_filterwheel = self.telescope_status.filterwheel
        status_camera = self.telescope_status.camera
        status_telescope = self.telescope_status.mount
        trigger_abort_disconnected = False
        if status_camera.lower() == 'disconnected':
            trigger_abort_disconnected = True
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: camera is disconnected.')
        if status_filterwheel.lower() == 'disconnected':
            trigger_abort_disconnected = True
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: filterwheel is disconnected.')
        if status_telescope.lower() == 'disconnected':
            trigger_abort_disconnected = True
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: mount is disconnected.')
        if trigger_abort_disconnected:
            self.shared_memory['exception'] = 'ConnectionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ConnectionException(f'==========LV2[{type(self).__name__}] is failed: devices are disconnected.')
        
        # Abort action when triggered
        if self.abort_action.is_set():
            self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
            self.shared_memory['exception'] = 'AbortionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise AbortionException(f'[{type(self).__name__}] is aborted.')
        
        # Define actions required
        action_slew = SlewAltAz(singletelescope = self.telescope, abort_action= self.abort_action)
        action_changefocus = ChangeFocus(singletelescope = self.telescope, abort_action = self.abort_action)
        action_changefilter = ChangeFilter(singletelescope = self.telescope, abort_action = self.abort_action)
        action_exposure = Exposure(singletelescope = self.telescope, abort_action = self.abort_action)
        
        # Slewing
        try:
            result_slew = action_slew.run(alt = self.telescope.config['AUTOFLAT_ALTITUDE'], az = self.telescope.config['AUTOFLAT_AZIMUTH'], tracking = False)
        except ConnectionException:
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: mount is disconnected.')
            self.shared_memory['exception'] = 'ConnectionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ConnectionException(f'[{type(self).__name__}] is failed: mount is disconnected.')
        except AbortionException:
            while action_slew.shared_memory['is_running']:
                time.sleep(0.1)
            self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
            self.shared_memory['exception'] = 'AbortionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise AbortionException(f'[{type(self).__name__}] is aborted: mount sleing is aborted.')
        except ActionFailedException:
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: slewing failure.')
            self.shared_memory['exception'] = 'ActionFailedException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ActionFailedException(f'[{type(self).__name__}] is failed: slewing failure.')
        
        # Abort action when triggered
        if self.abort_action.is_set():
            self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
            self.shared_memory['exception'] = 'AbortionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise AbortionException(f'[{type(self).__name__}] is aborted.')
        
        # Get bias value
        camera = self.telescope.camera
        status_camera = self.telescope_status.camera
        # Check camera status
        if status_camera.lower() == 'disconnected':
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: camera is disconnected.')
            self.shared_memory['exception'] = 'ConnectionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ConnectionException(f'[{type(self).__name__}] is failed: camera is disconnected.')
        elif status_camera.lower() == 'busy':
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: camera is busy.')
            self.shared_memory['exception'] = 'ActionFailedException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ActionFailedException(f'[{type(self).__name__}] is failed: camera is busy.')
        elif status_camera.lower() == 'idle':
            is_light = False
            self.telescope.log.info(f'=====[{type(self).__name__}] Start exposure for calculation of a BIAS level')
            try:
                imginfo = camera.exposure(exptime = 0,
                                          imgtype = 'BIAS',
                                          binning = binning,
                                          is_light = is_light,
                                          gain = gain,
                                          abort_action = self.abort_action)
                bias_level = float(np.mean(imginfo['data'])) 
                self.telescope.log.info(f'=====[{type(self).__name__}] BIAS level: {bias_level}')
            except ExposureFailedException:
                self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: camera exposure failure.')
                self.shared_memory['exception'] = 'ActionFailedException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ActionFailedException(f'[{type(self).__name__}] is failed: camera exposure failure.')
            except AbortionException:
                camera.wait_idle()
                self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
                self.shared_memory['exception'] = 'AbortionException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise AbortionException(f'[{type(self).__name__}] is aborted: Exposure is aborted')
            except Exception:
                self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is failed.', exc_info=True)
                self.shared_memory['exception'] = 'ActionFailedException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ActionFailedException(f'[{type(self).__name__}] is failed: BIAS level calculation failure')
        else:
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: camera is under unknown condition.')
            self.shared_memory['exception'] = 'ActionFailedException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ActionFailedException(f'[{type(self).__name__}] is failed: camera is under unknown condition.')

        # Define the filter order for FLAT observation
        filtnames = self.telescope.filterwheel.filtnames
        auto_flat_order = self.telescope.config.get('AUTOFLAT_FILTERORDER', [])
        defined_filtnames = [f for f in filtnames if f in auto_flat_order]
        ordered_filtnames = sorted(defined_filtnames, key=lambda x: auto_flat_order.index(x))
        observation_status = {filter_name: False for filter_name in ordered_filtnames}
        self.shared_memory['status'] = observation_status

        # Start autoflat
        def autoflat_filter(filter_, count, gain, binning):
            self.telescope.log.info(f'=====[{type(self).__name__}] for filter {filter_} is triggered')
            # Filterchange
            try:    
                self.action = action_changefilter
                result_filterchange = action_changefilter.run(filter_ = filter_)
            except ConnectionException:
                self.telescope.log.critical(f'=====[{type(self).__name__}] is failed: Filterwheel is disconnected.')                
                raise ConnectionException(f'[{type(self).__name__}] is failed: Filterwheel is disconnected.')                
            except AbortionException:
                self.telescope.log.warning(f'=====[{type(self).__name__}] is aborted.')
                raise AbortionException(f'[{type(self).__name__}] is aborted.')
            except ActionFailedException:
                self.telescope.log.critical(f'=====[{type(self).__name__}] is failed: Filterwheel movement failure.')
                self.shared_memory['exception'] = 'ActionFailedException'
                raise ActionFailedException(f'[{type(self).__name__}] is failed: Filterwheel movement failure.')
            
            # Exposure with default value & wait for the sky level arised
            obs_count = 0
            exptime = self.telescope.config['AUTOFLAT_MINEXPTIME']
            sky_level_per_second_this = 0
            id_ = uuid.uuid4().hex
            
            while obs_count < count:    
                # Check camera status
                status_camera = self.telescope_status.camera
                if status_camera.lower() == 'disconnected':
                    self.telescope.log.critical(f'=====[{type(self).__name__}] is failed: camera is disconnected.')
                    raise ConnectionException(f'[{type(self).__name__}] is failed: camera is disconnected.')
                elif status_camera.lower() == 'busy':
                    self.telescope.log.critical(f'=====[{type(self).__name__}] is failed: camera is busy.')
                    raise ActionFailedException(f'[{type(self).__name__}] is failed: camera is busy.')
                elif status_camera.lower() == 'idle':
                    self.telescope.log.info(f'[{type(self).__name__}] Start exposure for calculation of a sky level')
                    try:
                        imginfo = camera.exposure(exptime = exptime,
                                                  imgtype = 'FLAT',
                                                  binning = binning,
                                                  is_light = True,
                                                  gain = gain,
                                                  abort_action = self.abort_action)
                        sky_level = float(np.median(imginfo['data'])) - bias_level
                        sky_level_per_second_prev = sky_level_per_second_this
                        sky_level_per_second_this = sky_level / exptime
                        sky_level_ratio = (sky_level_per_second_this / sky_level_per_second_prev) if sky_level_per_second_prev > 0 else 1.0
                        sky_level_per_second_expected = sky_level_per_second_this * sky_level_ratio
                        self.telescope.log.info(f'[{type(self).__name__}] Sky level: {sky_level} with {exptime}s exposure')
                    except ExposureFailedException:
                        self.telescope.log.critical(f'=====[{type(self).__name__}] is failed: camera exposure failure.')
                        raise ActionFailedException(f'[{type(self).__name__}] is failed: camera exposure failure.')
                    except AbortionException:
                        self.telescope.log.warning(f'=====[{type(self).__name__}] is aborted.')
                        raise AbortionException(f'[{type(self).__name__}] is aborted.')
                    except Exception:
                        self.telescope.log.warning(f'=====[{type(self).__name__}] is failed.', exc_info=True)
                        raise ActionFailedException(f'[{type(self).__name__}] is failed: Sky level calculation failure')
                else:
                    self.telescope.log.critical(f'=====[{type(self).__name__}] is failed: camera is under unknown condition.')
                    raise ActionFailedException(f'[{type(self).__name__}] is failed: camera is under unknown condition.')
                
                # If sky level is within the range, then save the image
                if (sky_level > self.telescope.config['AUTOFLAT_MINCOUNT']) and (sky_level < self.telescope.config['AUTOFLAT_MAXCOUNT']):
                    target = SingleTarget(observer = self.telescope.observer, 
                                          ra = None,
                                          dec = None, 
                                          alt = self.telescope.config['AUTOFLAT_ALTITUDE'], 
                                          az = self.telescope.config['AUTOFLAT_AZIMUTH'], 
                                          name = 'FLAT', 
                                          objtype= 'FLAT',
                                          id_ = id_,
                                          note = None,
                                          comment = None,
                                          is_ToO = False,
                                          is_rapidToO = False,
                                        
                                          exptime = exptime,
                                          count = 1,
                                          filter_ = filter_,
                                          binning = binning, 
                                          gain = gain,
                                          obsmode = None,
                                          specmode = None,
                                          colormode = None,
                                          ntelescope = 1
                                          )
                    status = self.telescope.status
                    try:
                        img = mainImage(frame_number = int(obs_count),
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
                        self.telescope.log.info(f'[{type(self).__name__}] Image saved: %s'%(filepath))
                        obs_count += 1

                    except Exception:
                        self.telescope.log.critical(f'=====[{type(self).__name__}] is failed: mainImage save failure.', exc_info=True)
                        raise ActionFailedException(f'[{type(self).__name__}] is failed: mainImage save failure.')
                
                # Abort action when triggered
                if self.abort_action.is_set():
                    self.telescope.log.warning(f'=====[{type(self).__name__}] is aborted.')
                    raise AbortionException(f'[{type(self).__name__}] is aborted.')
                
                # Adjust the exposure time
                exptime_min = np.round(np.abs(self.telescope.config['AUTOFLAT_MINCOUNT']/sky_level_per_second_expected),2)
                exptime_max = np.round(np.abs(self.telescope.config['AUTOFLAT_MAXCOUNT']/sky_level_per_second_this),2)
                self.telescope.log.info(f'[{type(self).__name__}] Required exposure time: (%s~%s) sec'%(exptime_min, exptime_max))
                
                # If sky level is too low, then wait for the sky level arised
                if exptime_min > self.telescope.config['AUTOFLAT_MAXEXPTIME']:
                    time.sleep(self.telescope.config['AUTOFLAT_WAITDURATION'])
                    self.telescope.log.info(f'[{type(self).__name__}] Waiting {self.telescope.config["AUTOFLAT_WAITDURATION"]}s for the sky level arised')
                # If sky level is too high, raise an exception
                elif exptime_max < self.telescope.config['AUTOFLAT_MINEXPTIME']:
                    self.telescope.log.warning(f'=====[{type(self).__name__}] is failed: Sky is too bright.')
                    raise ActionFailedException(f'[{type(self).__name__}] is failed: Sky is too bright.')
                # If sky level is within the range, then adjust the exposure time
                else:
                    exptime = np.round(np.max([np.sum([0.9*exptime_min, 0.1*exptime_max]), self.telescope.config['AUTOFLAT_MINEXPTIME']]),2)
                    self.telescope.log.info(f'[{type(self).__name__}] Exposure time is adjusted to {exptime} sec')
            self.telescope.log.info(f'=====[{type(self).__name__}] for filter {filter_} is succeeded')
        
        for filtname in ordered_filtnames:
            try:
                autoflat_filter(filtname, count, gain, binning)
                observation_status[filtname] = True
                self.shared_memory['status'] = observation_status
            except ActionFailedException:
                self.is_running = False
                self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: autoflat_filter failure.')
            except ConnectionException:
                self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: devices are disconnected.')
                self.shared_memory['exception'] = 'ConnectionException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ConnectionException(f'[{type(self).__name__}] is failed: devices are disconnected.')
            except AbortionException:
                self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
                self.shared_memory['exception'] = 'AbortionException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise AbortionException(f'[{type(self).__name__}] is aborted.')
        
        self.telescope.log.info(f'==========LV2[{type(self).__name__}] is finished.')
        self.is_running = False
        self.shared_memory['succeeded'] = all(observation_status.values())
        
        if self.shared_memory['succeeded']:
            return True    
        
    def abort(self):
        self.telescope.register_logfile()
        self.abort_action.set()
        while self.shared_memory['is_running']:
            time.sleep(0.1)
        self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
        self.shared_memory['exception'] = 'AbortionException'
        self.shared_memory['is_running'] = False
        self.is_running = False
        raise AbortionException(f'[{type(self).__name__}] is aborted.')
        
# %%
if __name__ == '__main__':
    tel = SingleTelescope(36)
    self = AutoFlat(tel, Event())
    self.run(count = 10, gain = 16, binning = 1)
# %%
