#%%
from astropy.io import ascii
import time
from astropy.time import Time
import numpy as np
from multiprocessing import Event
from multiprocessing import Lock

from tcspy.devices import NINA
from tcspy.utils.logger import mainLogger
from tcspy.utils import Timeout
from tcspy.configuration import mainConfig
from tcspy.utils.exception import *

# %%
class mainFocuser_NINA(mainConfig):
    """
    A class for controlling a Focuser device via NINA API.

    Parameters
    ----------
    unitnum : int
        The unit number.

    Attributes
    ----------
    device : NINA
        The Focuser device to control.
    status : dict
        A dictionary containing the current status of the Focuser device.

    Methods
    -------
    get_status() -> dict
        Get the status of the Focuser device.
    connect() -> bool
        Connect to the focuser.
    disconnect() -> bool
        Disconnect from the focuser.
    move(position: int, abort_action: Event) -> bool
        Move the Focuser device to the specified position.
    fans_on() -> bool
        Turn on the fans (not supported via NINA).
    fans_off() -> bool
        Turn off the fans (not supported via NINA).
    autofocus_start(abort_action: Event) -> bool
        Start autofocus.
    autofocus_stop() -> None
        Stop autofocus.
    abort() -> None
        Abort the movement of the Focuser device.
    """

    def __init__(self,
                 unitnum : int,
                 **kwargs):

        super().__init__(unitnum = unitnum)
        self.device = NINA(self.config['FOCUSER_HOSTIP'], self.config['FOCUSER_PORTNUM'])
        self._is_autofocusing = False
        self.status = self.get_status()
        self.is_idle = Event()
        self.is_idle.set()
        self.device_lock = Lock()
        self._log = mainLogger(unitnum = unitnum, logger_name = __name__+str(unitnum)).log()

    def get_status(self) -> dict:
        """
        Get the status of the Focuser device.

        Returns
        -------
        status : dict
            A dictionary containing the current status of the Focuser device.
        """
        status = dict()
        status['update_time'] = Time.now().isot
        status['jd'] = round(Time.now().jd,6)
        status['position'] = None
        status['temperature'] = None
        status['is_connected'] = False
        status['is_moving'] = None
        status['is_autofocusing'] = self._is_autofocusing
        status['is_autofocus_success'] = None
        status['autofocus_bestposition'] = None
        status['autofocus_tolerance'] = None

        try:
            info = self.device.focuser_info()
            response = info['Response']
            status['position'] = response['Position']
            status['temperature'] = response['Temperature']
            status['is_connected'] = response['Connected']
            status['is_moving'] = response['IsMoving'] or response['IsSettling']
        except:
            pass

        try:
            last_af = self.device.autofocus_last()
            af_response = last_af['Response']
            calculated = af_response.get('CalculatedFocusPoint', {})
            status['autofocus_bestposition'] = calculated.get('Position')
            tolerance_value = calculated.get('Value')
            if isinstance(tolerance_value, (int, float)):
                status['autofocus_tolerance'] = tolerance_value
            status['is_autofocus_success'] = calculated.get('Position') is not None
        except:
            pass
        return status

    def _get_last_af_timestamp(self):
        """
        Get the timestamp of the last autofocus result.
        Returns empty string if no previous result exists.
        """
        try:
            last_af = self.device.autofocus_last()
            return last_af['Response'].get('Timestamp', '')
        except:
            return ''

    @Timeout(5, 'Timeout')
    def connect(self):
        """
        Connect to the focuser.
        """
        self._log.info('Connecting to the focuser...')
        status = self.get_status()
        try:
            if not status['is_connected']:
                self.device.focuser_connect()
            time.sleep(float(self.config['FOCUSER_CHECKTIME']))
            while not status['is_connected']:
                time.sleep(float(self.config['FOCUSER_CHECKTIME']))
                status = self.get_status()
            if status['is_connected']:
                self._log.info('Focuser connected')
        except:
            self._log.critical('Connection failed')
            raise ConnectionException('Connection failed')
        return True

    @Timeout(5, 'Timeout')
    def disconnect(self):
        """
        Disconnect from the focuser.
        """
        self._log.info('Disconnecting from the focuser...')
        status = self.get_status()
        try:
            if status['is_connected']:
                self.device.focuser_disconnect()
            time.sleep(float(self.config['FOCUSER_CHECKTIME']))
            while status['is_connected']:
                time.sleep(float(self.config['FOCUSER_CHECKTIME']))
                status = self.get_status()
            if not status['is_connected']:
                self._log.info('Focuser disconnected')
        except:
            self._log.critical('Disconnect failed')
            raise ConnectionException('Disconnect failed')
        return True

    def move(self,
             position : int,
             abort_action : Event):
        """
        Move the Focuser device to the specified position.

        Parameters
        ----------
        position : int
            The position to move the device to.
        abort_action : Event
            Event object for aborting the movement.
        """
        self.is_idle.clear()
        self.device_lock.acquire()
        exception_raised = None

        try:
            maxstep =  self.config['FOCUSER_MAXSTEP']
            minstep =  self.config['FOCUSER_MINSTEP']
            if (position <= minstep) | (position > maxstep):
                self._log.critical('Set position is out of bound of this focuser (Min : %d Max : %d)'%(minstep, maxstep))
                raise FocusChangeFailedException('Set position is out of bound of this focuser (Min : %d Max : %d)'%(minstep, maxstep))
            else:
                status =  self.get_status()
                current_position = status['position']
                self._log.info('Moving focuser position... (Current : %s To : %s)'%(current_position, position))
                self.device.focuser_goto(target = position)
                time.sleep(float(self.config['FOCUSER_CHECKTIME']))
                status =  self.get_status()
                while status['is_moving']:
                    status =  self.get_status()
                    current_position = status['position']
                    time.sleep(float(self.config['FOCUSER_CHECKTIME']))
                    if abort_action.is_set():
                        self._log.warning('Abort requested during focuser move')
                        raise AbortionException('Focuser movement is aborted')
                time.sleep(3 * float (self.config['FOCUSER_CHECKTIME']))
                status =  self.get_status()
                current_position = status['position']
                self._log.info('Focuser position is set (Current : %s)'%(current_position))
            return True

        except Exception as e:
            exception_raised = e

        finally:
            self.device_lock.release()
            self.is_idle.set()
            if exception_raised:
                raise exception_raised

    def fans_on(self):
        """
        Turn on the fans (not supported via NINA).
        """
        self._log.info('Fans operation is not supported via NINA')
        return True

    def fans_off(self):
        """
        Turn off the fans (not supported via NINA).
        """
        self._log.info('Fans operation is not supported via NINA')
        return True

    def autofocus_start(self,
                        abort_action : Event):
        """
        Start autofocus.

        Parameters
        ----------
        abort_action : Event
            Event object for aborting the autofocus.

        Raises
        ------
        AbortionException
            If autofocus is aborted.
        AutofocusFailedException
            If autofocus fails.

        """
        self.is_idle.clear()
        self.device_lock.acquire()
        exception_raised = None

        try:
            status =  self.get_status()
            current_position = status['position']
            self._log.info('Start autofocus (Central position : %s)'%(current_position))

            # Record the last AF timestamp before starting
            prev_af_timestamp = self._get_last_af_timestamp()

            self._is_autofocusing = True
            self.device.autofocus_start()
            checktime = float(self.config['FOCUSER_CHECKTIME'])
            time.sleep(checktime)

            # Poll until a new autofocus result appears (new timestamp in last-af)
            # NINA has no is_autofocusing status, so we detect completion by:
            #   1. Primary: /last-af timestamp changes (successful AF)
            #   2. Backup: extended idle period without new result (failed AF)
            #   3. Safety: overall timeout
            af_complete = False
            idle_count = 0
            max_idle_count = int(90 / checktime)
            max_total_time = 900
            start_time = time.time()

            while not af_complete:
                time.sleep(checktime)

                if abort_action.is_set():
                    self.device.autofocus_stop()
                    self._is_autofocusing = False
                    status = self.get_status()
                    while status['is_moving']:
                        status =  self.get_status()
                        time.sleep(checktime)
                    self._log.warning('Autofocus is aborted. Move back to the previous position')
                    self.device_lock.release()
                    self.move(position = current_position, abort_action= Event())
                    self.device_lock.acquire()
                    raise AbortionException('Autofocus is aborted. Move back to the previous position')

                current_af_timestamp = self._get_last_af_timestamp()
                if current_af_timestamp != prev_af_timestamp and current_af_timestamp != '':
                    af_complete = True
                    break

                # Track idle periods for failure detection
                try:
                    info = self.device.focuser_info()
                    is_moving = info['Response']['IsMoving'] or info['Response']['IsSettling']
                except:
                    is_moving = False

                if not is_moving:
                    idle_count += 1
                else:
                    idle_count = 0

                if idle_count >= max_idle_count:
                    self._log.warning('Autofocus appears to have ended without a new result (idle for extended period)')
                    break

                if time.time() - start_time > max_total_time:
                    self._log.warning('Autofocus timed out after %d seconds'%(max_total_time))
                    self.device.autofocus_stop()
                    time.sleep(checktime)
                    break

            self._is_autofocusing = False

            # Wait for any remaining movement to finish
            status =  self.get_status()
            while status['is_moving']:
                status =  self.get_status()
                time.sleep(checktime)
            time.sleep(3 * checktime)

            # Get the autofocus result
            status = self.get_status()
            if af_complete & (status['is_autofocus_success']) & (status['autofocus_tolerance'] < self.config['AUTOFOCUS_TOLERANCE']):
                self._log.info('Autofocus complete! (Best position : %s (%s))'%(status['autofocus_bestposition'], status['autofocus_tolerance']))
                return status['is_autofocus_success'], status['autofocus_bestposition'], status['autofocus_tolerance']
            else:
                self.device_lock.release()
                self.move(position = current_position, abort_action= Event())
                self.device_lock.acquire()
                self._log.warning('Autofocus failed. Move back to the previous position')
                raise AutofocusFailedException('Autofocus failed. Move back to the previous position')

        except Exception as e:
            self._is_autofocusing = False
            exception_raised = e
            print(exception_raised)

        finally:
            self._is_autofocusing = False
            self.device_lock.release()
            self.is_idle.set()
            if exception_raised:
                raise exception_raised

    def wait_idle(self):
        self.is_idle.wait()

# %%
if __name__ == '__main__':
    F = mainFocuser_NINA(1)
    F.autofocus_start(Event())
# %%
