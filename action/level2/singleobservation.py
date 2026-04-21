#%%
from multiprocessing import Event
from multiprocessing import Manager
from astropy.time import Time
import astropy.units as u
import time

from numpy import False_

from tcspy.devices import SingleTelescope
from tcspy.devices import TelescopeStatus
from tcspy.interfaces import *
from tcspy.utils.error import *
from tcspy.utils.target import SingleTarget
from tcspy.utils.exception import *

from tcspy.action.level1 import SlewRADec
from tcspy.action.level1 import SlewAltAz
from tcspy.action.level1 import Exposure
from tcspy.action.level1 import ChangeFocus
from tcspy.action.level1 import ChangeFilter
from tcspy.action.level2 import AutoFocus

#%%
class SingleObservation(Interface_Runnable, Interface_Abortable):
    """
    A class representing a single observation action for a single telescope.

    Parameters
    ----------
    singletelescope : SingleTelescope
        An instance of SingleTelescope class representing the individual telescope on which the single observation action is performed.
    abort_action : Event
        An instance of the built-in Event class to handle the abort action.

    Methods
    -------
    run(exptime, count, filter_=None, binning='1', imgtype='Light', ra=None, dec=None, alt=None, az=None, name=None,
        obsmode='Single', specmode=None, ntelescope=1, objtype=None, autofocus_before_start=False,
        autofocus_when_filterchange=False, **kwargs)
        Triggers the single observation process. This includes checking device status, setting target, slewing,
        changing filter and focuser position according to the necessity and conducting exposure.
    abort()
        Aborts any running actions related to the filter wheel, camera, and mount.
    """
    
    def __init__(self, 
                 singletelescope : SingleTelescope,
                 abort_action : Event):
        self.telescope = singletelescope
        self.telescope_status = TelescopeStatus(self.telescope)
        self.abort_action = abort_action
        self.shared_memory_manager = Manager()
        self.shared_memory = self.shared_memory_manager.dict()
        self.shared_memory['succeeded'] = False
        self.shared_memory['status'] = dict()
        self.shared_memory['exception'] = None
        self.shared_memory['is_running'] = True
        self.is_running = False

    def run(self, 
            # Exposure information
            exptime : str,
            count : str,
            obsmode : str = 'Single',
            filter_ : str = 'r',
            specmode : str = None,
            colormode : str = None,
            ntelescope : int = 1,
            gain : int = 2750,
            binning : str = '1',
            imgtype : str = 'Light',
            
            # Target information
            ra : float = None, # When radec == None: do not move 
            dec : float = None,
            alt : float = None, # When altaz == None: do not move 
            az : float = None,
            name : str = None,
            objtype : str = None,
            id_: str = None,
            note : str = None,
            comment : str = None,
            is_ToO : bool = False,
            
            # Auxiliary parameters
            force_slewing : bool = False,
            autofocus_use_history : bool = True,
            autofocus_history_duration : float = 60,
            autofocus_before_start : bool = False,
            autofocus_when_filterchange : bool = False,
            autofocus_when_elapsed : bool = False,
            autofocus_elapsed_duration : float = 60,
            observation_status : dict = None,
            **kwargs
            ):
        """
        Triggers the single observation process. This includes checking device status, setting target, slewing,
        changing filter and focuser position according to the necessity and conducting exposure.

        Parameters
        ----------
        exptime : str
            The exposure time.
        count : str
            The exposure count.
        filter_ : str, optional
            The type of filter to be used. 
        binning : str, optional
            The binning value. If not provided, defaults to '1'.
        imgtype : str, optional
            The type of image. If not provided, defaults to 'Light'.
        ra : float, optional
            The right ascension of the target. If not provided, the telescope does not move.
        dec : float, optional
            The declination of the target. If not provided, the telescope does not move.
        alt : float, optional
            The altitude of the target. If neither `alt` nor `az` are provided, the telescope does not move.
        az : float, optional
            The azimuth of the target. If neither `alt` nor `az` are provided, the telescope does not move.
        autofocus_before_start : bool, optional
            Whether or not to autofocus before beginning the first observation set. If not provided, it will not autofocus before beginning the observation.
        autofocus_when_filterchange : bool, optional
            Whether or not to autofocus when filter changes. If not provided, it will not autofocus when the filter changes.
        
        Raises
        ------
        ConnectionException:
            If the required devices are disconnected.
        AbortionException:
            If the action is aborted during execution.
        ActionFailedException:
            If the slewing process or the exposure fails.
        """
        
        """
          exptime = '5,5'
          count = '2,2'
          filter_ = 'm400,m425'
          binning = '1'
          imgtype = 'Light'
          ra = 200
          dec = -58.0666 
          obsmode = 'Spec'
          autofocus_use_history = True
          autofocus_history_duration = 60
          autofocus_before_start = True
          autofocus_when_filterchange= True
          autofocus_when_elapsed = True
          autofocus_elapsed_duration = 60
          observation_status = None
          az = None
          alt = None
          name = None
          objtype = None
          specmode = None
          ntelescope = 1
          id_ = '193yhiujashdijqhweu9'
          force_slewing = False
          note = 'This is for Deep observing mode. (5 Telescopes will be used for sequential g,r,i observation)'
        """
        self.telescope.register_logfile()
        self.telescope.log.info(f'==========LV2[{type(self).__name__}] is triggered.')
        self.is_running = True
        self.shared_memory['is_running'] = True
        self.shared_memory['succeeded'] = False
        
        # Check condition of the instruments for this Action
        trigger_abort_disconnected = False
        try:        
            status_mount = self.telescope_status.mount
        except:
            trigger_abort_disconnected = True
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: mount status cannot be loaded.')
        try:
            status_camera = self.telescope_status.camera
        except Exception as e:
            trigger_abort_disconnected = True
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: camera status cannot be loaded. Exception: {e}')
        try:
            status_filterwheel = self.telescope_status.filterwheel
        except Exception as e:
            trigger_abort_disconnected = True
            self.telescope.log.info(f'==========LV2[{type(self).__name__}] is failed: filterwheel status cannot be loaded. Exception: {e}')

        if status_camera.lower() == 'disconnected':
            trigger_abort_disconnected = True
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: camera is disconnected.')
        if status_filterwheel.lower() == 'disconnected':
            trigger_abort_disconnected = True
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: filterwheel is disconnected.')
        if status_mount.lower() == 'disconnected':
            trigger_abort_disconnected = True
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: mount is disconnected.')
        if trigger_abort_disconnected:
            self.shared_memory['exception'] = 'ConnectionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ConnectionException(f'==========LV2[{type(self).__name__}] is failed: devices are disconnected.')
        # Done
        self.telescope.log.info(f'==========LV2[{type(self).__name__}] is ready.')
        
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
                              
                              exptime = exptime,
                              count = count,
                              filter_ = filter_,
                              binning = binning, 
                              gain = gain,
                              obsmode = obsmode,
                              specmode = specmode,
                              colormode = colormode,
                              ntelescope = ntelescope
                              )
        self.telescope.log.info(f'==========LV2[{type(self).__name__}] Target is set.')
        target_info = target.target_info
        exposure_info = target.exposure_info
        self.telescope.log.info(f'==========LV2[{type(self).__name__}] Exposure information is set.')

        if exposure_info['filter_'] == 'None':
            try:
                if specmode:
                    exposure_info['filter_'] = exposure_info['specmode_filter'][self.telescope.tel_name]
                else:
                    exposure_info['filter_'] = exposure_info['colormode_filter'][self.telescope.tel_name]
            except:
                self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: filter is not defined.')
                self.shared_memory['exception'] = 'ActionFailedException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ActionFailedException(f'[{type(self).__name__}] is failed: filter is not defined.')

        # Slewing
        if target.status['coordtype'] == 'radec':
            try:
                action_slew = SlewRADec(singletelescope = self.telescope, abort_action= self.abort_action)
                result_slew = action_slew.run(ra = float(target_info['ra']), dec = float(target_info['dec']), force_action = force_slewing)
            except ConnectionException:
                self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: telescope is disconnected.')
                self.shared_memory['exception'] = 'ConnectionException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ConnectionException(f'[{type(self).__name__}] is failed: telescope is disconnected.')
            except AbortionException:
                while action_slew.shared_memory['is_running']:
                    time.sleep(0.1)
                self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted: slewing is aborted.')
                self.shared_memory['exception'] = 'AbortionException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise AbortionException(f'[{type(self).__name__}] is aborted: Slewing is aborted.')
            except ActionFailedException:
                self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: slewing failure.')
                self.shared_memory['exception'] = 'ActionFailedException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ActionFailedException(f'[{type(self).__name__}] is failed: slewing failure.')
            except Exception as e:
                raise RuntimeError(f'Error occured: {e}')
            
        elif target.status['coordtype'] == 'altaz':
            try:
                action_slew = SlewAltAz(singletelescope = self.telescope, abort_action= self.abort_action)
                result_slew = action_slew.run(alt = float(target_info['alt']), az = float(target_info['az']), force_action = force_slewing)
            except ConnectionException:
                self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: telescope is disconnected.')
                self.shared_memory['exception'] = 'ConnectionException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ConnectionException(f'[{type(self).__name__}] is failed: telescope is disconnected.')
            except AbortionException:
                while action_slew.shared_memory['is_running']:
                    print(action_slew.shared_memory['is_running'])
                    time.sleep(0.1)
                self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted: slewing is aborted.')
                self.shared_memory['exception'] = 'AbortionException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise AbortionException(f'[{type(self).__name__}] is aborted: Autofocus is aborted.')
            except ActionFailedException:
                self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: slewing failure.')
                self.shared_memory['exception'] = 'ActionFailedException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ActionFailedException(f'[{type(self).__name__}] is failed: slewing failure.')
        else:
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Coordinate type of the target : {target.status["coordtype"]} is not defined')
            self.shared_memory['exception'] = 'ActionFailedException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ActionFailedException(f'[{type(self).__name__}] is failed: Coordinate type of the target : {target.status["coordtype"]} is not defined')

        # Get exposure information
        observation_requested = self._exposureinfo_to_list(filter_ = exposure_info['filter_'], exptime = exposure_info['exptime'], count = exposure_info['count'], binning = exposure_info['binning'])
        # Set observation status. If observation_status is inputted, run() will resume according to the observation_status
        if not observation_status:
            observation_status = self._set_observation_status(filter_ = exposure_info['filter_'], exptime = exposure_info['exptime'], count = exposure_info['count'], binning = exposure_info['binning'])
        
        # When inputted observation_status.keys() are not matched with observation_requested, set default value
        if not (set(observation_status.keys())) == (set(observation_requested['filter_'])):
            observation_status = self._set_observation_status(filter_ = exposure_info['filter_'], exptime = exposure_info['exptime'], count = exposure_info['count'], binning = exposure_info['binning'])
        
        action_autofocus = AutoFocus(singletelescope= self.telescope, abort_action= self.abort_action)
        self.shared_memory['status'] = observation_status

        observation_trigger = {'filter_': [],
                               'exptime': [],
                               'count': [],
                               'binning': []}
        
        for filter_, exptime, count, binning in zip(observation_requested['filter_'], observation_requested['exptime'], observation_requested['count'], observation_requested['binning']):
             observation_status_filter = observation_status[filter_]
             net_count = observation_status_filter['triggered'] - observation_status_filter['observed']
             if net_count > 0:
                observation_trigger['filter_'].append(filter_)
                observation_trigger['exptime'].append(exptime)
                observation_trigger['count'].append(net_count)
                observation_trigger['binning'].append(binning)
 
        # Autofocus before beginning the first observation set 
        if autofocus_before_start:
            try:
                filter_ = observation_trigger['filter_'][0]
                result_autofocus = action_autofocus.run(filter_ = filter_, use_offset = True, use_history= autofocus_use_history, history_duration = autofocus_history_duration)
            except ConnectionException:
                self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Device connection is lost.')
                self.shared_memory['exception'] = 'ConnectionException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ConnectionException(f'[{type(self).__name__}] is failed: Device connection is lost.')
            except AbortionException:
                while action_autofocus.shared_memory['is_running']:
                    time.sleep(0.1)
                self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted: Autofocus is aborted.')
                self.shared_memory['exception'] = 'AbortionException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise AbortionException(f'[{type(self).__name__}] is aborted: Autofocus is aborted.')
            except ActionFailedException:
                self.telescope.log.warning(f'[{type(self).__name__}] Autofocus is failed. Return to the previous focus value')
                pass
        result_all_exposure = []
        for filter_, exptime, count, binning in zip(observation_trigger['filter_'], observation_trigger['exptime'], observation_trigger['count'], observation_trigger['binning']):
            info_filterwheel = self.telescope.filterwheel.get_status()
            current_filter = info_filterwheel['filter_']
            is_filter_changed = (current_filter != filter_)
            
            if is_filter_changed:

                # Apply offset
                offset = self.telescope.filterwheel.get_offset_from_currentfilt(filter_ = filter_)
                self.telescope.log.info(f'[{type(self).__name__}] Focuser is moving with the offset of {offset}[{current_filter} >>> {filter_}]')
                try:
                    action_changefocus = ChangeFocus(singletelescope = self.telescope, abort_action = self.abort_action)
                    result_changefocus = action_changefocus.run(position = offset, is_relative= True)
                except ConnectionException:
                    self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Focuser is disconnected.')      
                    self.shared_memory['exception'] = 'ConnectionException'          
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise ConnectionException(f'[{type(self).__name__}] is failed: Focuser is disconnected.')                
                except AbortionException:
                    while action_changefocus.shared_memory['is_running']:
                        time.sleep(0.1)
                    self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted: Focuser movement is aborted.')
                    self.shared_memory['exception'] = 'AbortionException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise AbortionException(f'[{type(self).__name__}] is aborted: Focuser movement is aborted.')
                except ActionFailedException:
                    self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Focuser movement failure.')
                    self.shared_memory['exception'] = 'ActionFailedException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise ActionFailedException(f'[{type(self).__name__}] is failed: Focuser movement failure.')
                
                # Filterchange
                try:    
                    action_filterchange = ChangeFilter(singletelescope= self.telescope, abort_action= self.abort_action)
                    result_filterchange = action_filterchange.run(filter_ = filter_)
                except ConnectionException:
                    self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Filterwheel is disconnected.')                
                    self.shared_memory['exception'] = 'ConnectionException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise ConnectionException(f'[{type(self).__name__}] is failed: Filterwheel is disconnected.')                
                except AbortionException:
                    while action_filterchange.shared_memory['is_running']:
                        time.sleep(0.1)
                    self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted: Filterwheel movement is aborted.')
                    self.shared_memory['exception'] = 'AbortionException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise AbortionException(f'[{type(self).__name__}] is aborted: Filterwheel movement is aborted.')
                except ActionFailedException:
                    self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Filterwheel movement failure.')
                    self.shared_memory['exception'] = 'ActionFailedException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise ActionFailedException(f'[{type(self).__name__}] is failed: Filterwheel movement failure.')

                # Autofocus when filter changed
                if autofocus_when_filterchange:
                    try:
                        result_autofocus = action_autofocus.run(filter_ = filter_, use_offset = False, use_history= autofocus_use_history, history_duration= autofocus_history_duration)
                    except ConnectionException:
                        self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Device connection is lost.')
                        self.shared_memory['exception'] = 'ConnectionException'
                        self.shared_memory['is_running'] = False
                        self.is_running = False
                        raise ConnectionException(f'[{type(self).__name__}] is failed: Device connection is lost.')
                    except AbortionException:
                        while action_autofocus.shared_memory['is_running']:
                            time.sleep(0.1)
                        self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted: Autofocus is aborted.')
                        self.shared_memory['exception'] = 'AbortionException'
                        self.shared_memory['is_running'] = False
                        self.is_running = False
                        raise AbortionException(f'[{type(self).__name__}] is aborted: Autofocus is aborted.')
                    except ActionFailedException:
                        self.telescope.log.warning(f'[{type(self).__name__}] Autofocus is failed. Return to the previous focus value')
                        pass

            # Exposure
            action_exposure = Exposure(singletelescope = self.telescope, abort_action = self.abort_action)
            for frame_number in range(int(count)):
                
                # Autofocus_when_elapsed
                if autofocus_when_elapsed:
                    history = action_autofocus.history[filter_]
                    now = Time.now()
                    if ((Time(history['update_time']) + autofocus_elapsed_duration * u.minute) < now) | (not history['succeeded']):
                        try:
                            result_autofocus = action_autofocus.run(filter_ = filter_, use_offset = False, use_history = False)
                        except ConnectionException:
                            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Device connection is lost.')
                            self.shared_memory['exception'] = 'ConnectionException'
                            self.shared_memory['is_running'] = False
                            self.is_running = False
                            raise ConnectionException(f'[{type(self).__name__}] is failed: Device connection is lost.')
                        except AbortionException:
                            while action_autofocus.shared_memory['is_running']:
                                time.sleep(0.1)
                            self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted: Autofocus is aborted.')
                            self.shared_memory['exception'] = 'AbortionException'
                            self.shared_memory['is_running'] = False  
                            self.is_running = False
                            raise AbortionException(f'[{type(self).__name__}] is aborted: Autofocus is aborted.')
                        except ActionFailedException:
                            self.telescope.log.warning(f'[{type(self).__name__}] Autofocus is failed. Return to the previous focus value')
                            
                # Exposure
                try:
                    self.action = action_exposure
                    result_exposure = action_exposure.run(frame_number = int(observation_status[filter_]['observed']),
                                                          exptime = float(exptime),
                                                          obsmode = obsmode,
                                                          filter_ = filter_,
                                                          specmode = specmode,
                                                          colormode = colormode,
                                                          ntelescope = ntelescope,
                                                          gain = int(gain),
                                                          binning = int(binning),
                                                          imgtype = imgtype,
                                                        
                                                          ra = ra,
                                                          dec = dec,
                                                          alt = alt,
                                                          az = az,
                                                          name = name,
                                                          objtype = objtype,
                                                          id_ = id_,
                                                          note = note,
                                                          comment = comment,
                                                          is_ToO = is_ToO)

                    # Update self.observation_status
                    observation_status[filter_]['observed'] += 1
                    self.shared_memory['status'] = observation_status
                    result_all_exposure.append(result_exposure)
                except ConnectionException:
                    self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: camera is disconnected.')
                    self.shared_memory['exception'] = 'ConnectionException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise ConnectionException(f'[{type(self).__name__}] is failed: camera is disconnected.')
                except AbortionException:
                    while action_exposure.shared_memory['is_running']:
                        time.sleep(0.1)
                    self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted: Exposure is aborted.')
                    self.shared_memory['exception'] = 'AbortionException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise AbortionException(f'[{type(self).__name__}] is aborted: Autofocus is aborted.')
                except ActionFailedException:
                    self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: exposure failure.')
                    self.shared_memory['exception'] = 'ActionFailedException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise ActionFailedException(f'[{type(self).__name__}] is failed: exposure failure.')

        self.telescope.log.info(f'==========LV2[{type(self).__name__}] is finished')
        self.shared_memory['succeeded'] = all(result_all_exposure)
        self.shared_memory['is_running'] = False
        self.is_running = False
        
        return all(result_all_exposure)

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
        
    def _exposureinfo_to_list(self,
                              filter_ : str,
                              exptime : str,
                              count : str,
                              binning : str):
        filter_list = filter_.split(',')
        exptime_list = exptime.split(',')
        count_list = count.split(',')
        binning_list = binning.split(',')
        exposure_info = dict()
        exposure_info['filter_'] = filter_list
        exposure_info['exptime'] = exptime_list
        exposure_info['count'] = count_list
        exposure_info['binning'] = binning_list
        len_filt = len(filter_list)        
        for name, value in exposure_info.items():
            len_value = len(value)
            if len_filt != len_value:
                exposure_info[name] = [value[0]] * len_filt
        return exposure_info
    
    def _set_observation_status(self,
                                filter_ : str,
                                exptime : str,
                                count : str,
                                binning : str):
        exposureinfo = self._exposureinfo_to_list(filter_ = filter_, exptime= exptime, count = count, binning = binning)
        observation_status = dict()
        for filt, count in zip(exposureinfo['filter_'], exposureinfo['count']):
            observation_status[filt] = dict()
            observation_status[filt]['triggered'] = int(count)
            observation_status[filt]['observed'] = 0 
        return observation_status


#%%    
if __name__ == '__main__':
    tel = SingleTelescope(36)
    self = SingleObservation(tel, Event())
    self.run(exptime = 0, count = 10, filter_ = 'r', imgtype = 'BIAS', alt = 40, az = 270, name= 'BIAS')
# %%
if __name__ == '__main__':
    tel = SingleTelescope(36)
    self = SingleObservation(tel, Event())
    self.run(exptime = 100, count = 10, filter_ = 'r', imgtype = 'DARK', alt = 40, az = 170, name= 'DARK')
# %%
if __name__ == '__main__':
    tel = SingleTelescope(36)
    self = SingleObservation(tel, Event())
    self.run(exptime = 60, count = 10, filter_ = 'r', imgtype = 'DARK', alt = 40, az = 270, name= 'DARK')
# %%
if __name__ == '__main__':
    tel = SingleTelescope(36)
    self = SingleObservation(tel, Event())
    for ra, dec in [(219.14, -80.378), (10.97, -18.88), (14.60, 19.67), (18.22, -19.02)]: # 180,40 / 270,40 / 0, 40 / 90, 40
        self.run(
            exptime = '10',
            count = '1',
            obsmode = 'Single',
            filter_ = 'r',
            specmode = None,
            colormode = None,
            ntelescope = 1,
            gain = 25,
            binning = '1',
            imgtype = 'LIGHT',
            
            # Target information
            ra = ra, # When radec == None: do not move 
            dec = dec,  
            alt = None, # When altaz == None: do not move 
            az = None,
            name = f'Ra_{ra}_Dec_{dec}',
            objtype = 'Test',
            id_ = None,
            note = 'Test',
            comment = 'Test',
            is_ToO = False,
            
            # Auxiliary parameters
            force_slewing = False,
            autofocus_use_history = False,
            autofocus_history_duration = 60,
            autofocus_before_start = False,
            autofocus_when_filterchange = False,
            autofocus_when_elapsed = False,
            autofocus_elapsed_duration = 60,
            observation_status = None,
        )
## %%
# %%
if __name__ == '__main__':
    tel = SingleTelescope(36)
    self = SingleObservation(tel, Event())
    self.run(
        exptime = '10',
        count = '1',
        obsmode = 'Single',
        filter_ = 'r',
        specmode = None,
        colormode = None,
        ntelescope = 1,
        gain = 25,
        binning = '1',
        imgtype = 'LIGHT',
        
        # Target information
        ra = 16.0125, # When radec == None: do not move 
        dec = -40.359,  
        alt = None, # When altaz == None: do not move 
        az = None,
        name = f'Ra_{ra}_Dec_{dec}',
        objtype = 'Test',
        id_ = None,
        note = 'Test',
        comment = 'Test',
        is_ToO = False,
        
        # Auxiliary parameters
        force_slewing = False,
        autofocus_use_history = False,
        autofocus_history_duration = 60,
        autofocus_before_start = False,
        autofocus_when_filterchange = False,
        autofocus_when_elapsed = False,
        autofocus_elapsed_duration = 60,
        observation_status = None,
    )
## %%
