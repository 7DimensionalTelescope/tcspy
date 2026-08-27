#%%
# Other modules
from astroplan import FixedTarget, is_event_observable, is_observable, is_always_observable
from astroplan import AltitudeConstraint
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time
import numpy as np
import datetime
from typing import List
from tqdm import tqdm
# TCSpy modules
from tcspy.devices.observer import mainObserver
from tcspy.configuration import mainConfig
#%%
class MultiTargets(mainConfig):
    """
    A class representing multiple astronomical targets for observation.

    Parameters
    ----------s
    observer : mainObserver
        An instance of mainObserver representing the observer.
    targets_ra : numpy.array
        An array containing the right ascension values of the targets, in degrees.
    targets_dec : numpy.array
        An array containing the declination values of the targets, in degrees.
    targets_name : numpy.array, optional
        An array containing the names of the targets. Default is None.
        
    Attributes
    ----------
    ra : numpy.array
        An array of right ascension coordinates of the targets in degrees.
    dec : numpy.array
        An array of declination coordinates of the targets in degrees.
    coordinate : SkyCoord
        The astropy SkyCoord object representing the coordinates of the targets.
    target_astroplan : list
        A list of astroplan FixedTarget objects representing the targets.
    name : numpy.array
        An array of names corresponding to the targets.

    Methods
    -------
    rts_date(year=None, time_grid_resolution=3)
        Calculate the rise, transit, and set times of the targets for each day of the specified year.
    is_ever_observable(utctime=None, time_grid_resolution=1*u.hour)
        Determines whether the targets are observable during the specified time.
    is_always_observable(utctimes=None)
        Determines whether the targets are always observable during the specified time.
    is_event_observable(utctimes=None)
        Determines whether the targets are observable at the specified time or at the current time.
    altaz(utctimes=None)
        Calculate the alt-az coordinates of the targets for the given time(s) in UTC.
    risetime(utctime=None, mode='nearest', horizon=30, n_grid_points=50)
        Calculate the next rise time of the targets as seen by the observer.
    settime(utctime=None, mode='nearest', horizon=30, n_grid_points=50)
        Calculate the time when the targets set below the horizon.
    meridiantime(utctime=None, mode='nearest', n_grid_points=50)
        Calculate the time at which the targets pass through the observer's meridian.
    hourangle(utctimes=None)
        Calculate the hour angle of the targets for the given time(s) in UTC.
    """
    
    def __init__(self,
                 targets_ra : np.array,
                 targets_dec : np.array,
                 targets_name : np.array = None,
                 **kwargs):
        
        super().__init__()
        self._observer = mainObserver()
        self._astroplan_observer = self._observer.status['observer']
        self._constraints = self._get_constraints(**self.config)
        self.ra = np.array(targets_ra)
        self.dec = np.array(targets_dec)     
        self.coordinate = self._get_coordinate_radec(ra = targets_ra, dec = targets_dec)
        self.target_astroplan = self._get_target(self.coordinate, targets_name)
        self.name = targets_name
        
    def __repr__(self):
        txt = f'MultiTargets[n_targets = {len(self.coordinate)}]'
        return txt
    
    def rts_date(self,
                 year : int = None,
                 time_grid_resolution : float = 3 # timegrid for checking the observability 
                 ):
        """
        Calculate the rise, transit, and set times of the targets for each day of the specified year.

        Parameters
        ----------
        year : int, optional
            The year for which to calculate the rise, transit, and set times. Default is None.
        time_grid_resolution : float, optional
            The time grid resolution for checking the observability. Default is 3.

        Returns
        -------
        numpy.array
            An array containing the calculated rise, transit, and set times of the targets for each day of the year.
        """
        # If start_date & end_date are not specified, defaults to current year
        if year == None:
            year = Time.now().datetime.year
        start_date = Time(datetime.datetime(year = year, month = 1, day = 1))
        end_date = Time(datetime.datetime(year = year+1 , month = 1, day = 1))

        expanded_arrays_observability = []
        expanded_arrays_altitude_midnight = []
        expanded_arrays_date = []
        n_days = int((end_date - start_date).to(u.day).value) + 1
        date_range = (start_date + i * u.day for i in range(n_days))
        for current_date in tqdm(date_range, total=n_days, desc='Calculating observability'):
            tonight_times = self._observer.tonight(current_date)
            midnight = Time((tonight_times[0].jd + tonight_times[1].jd) / 2, format='jd')
            alt_at_midnight = self.altaz(midnight).alt.value
            expanded_arrays_altitude_midnight.append(alt_at_midnight)
            observablity = self.is_ever_observable(tonight_times[0], tonight_times[1], time_grid_resolution=time_grid_resolution * u.hour)
            expanded_arrays_observability.append(observablity)
            expanded_arrays_date.append(current_date.datetime)

        observablity_array = np.array(expanded_arrays_observability).T
        altitude_array = np.array(expanded_arrays_altitude_midnight).T
        date_array = np.array(expanded_arrays_date)
        
        all_observability = []
        # Find the indices where the value changes
        for target_observability, target_altitude in zip(observablity_array, altitude_array):
            if all(target_observability):
                risedate = 'Always'
                setdate = 'Always'
                bestdate = date_array[np.argmax(target_altitude)]
            elif all(~target_observability):
                risedate = 'Never'
                setdate = 'Never'
                bestdate = 'Never'
            else:
                # Find index where observability False to True
                risedate_index = np.where(np.diff(target_observability.astype(int)) == 1)[0] + 1
                risedate = date_array[risedate_index[0]] if len(risedate_index) > 0 else date_array[0]
                # Find index where observability True to False
                setdate_index = np.where(np.diff(target_observability.astype(int)) == -1)[0] + 1
                setdate = date_array[setdate_index[0]] if len(setdate_index) > 0 else date_array[-1]
                bestdate = date_array[np.argmax(target_altitude)]
            all_observability.append((risedate, bestdate, setdate))
        
        return np.array(all_observability)
        
    def moon_sep(self,
                 utctime : datetime or Time or np.array = None):
        """
        Calculate the separation between the Moon and the target.

        Parameters
        ----------
        utctime : datetime or Time, optional
            The time at which to calculate the separation. If not provided, the current time will be used.

        Returns
        -------
        moonsep : astropy.coordinates.Angle
            The separation between the Moon and the target.
        """
            
        if utctime is None:
            utctime = Time.now()
        if not isinstance(utctime, Time):
            utctime = Time(utctime)
        moon_coord = self._observer.moon_radec(utctime)
        target_coord = self.coordinate
        moonsep = np.round(moon_coord.separation(target_coord),2)
        return moonsep.value
        
    def is_ever_observable(self,
                           utctime_start : datetime or Time = None,
                           utctime_end : datetime or Time = None,
                           time_grid_resolution = 1 * u.hour) -> List[bool]:
        """
        Determines whether the targets are observable during the specified time.

        Parameters
        ----------
        utctime : datetime or Time, optional
            The time at which to check observability. Defaults to the current time.
        time_grid_resolution : astropy.units.Quantity, optional
            The time grid resolution for checking the observability. Default is 1 hour.

        Returns
        -------
        List[bool]
            A list of boolean values indicating whether each target is observable during the specified time.

        Raises
        ------
        TypeError
            If the provided time is not a valid datetime or Time object.
        """
        # Ensure both start and end times are Time objects
        if utctime_start is not None and not isinstance(utctime_start, Time):
            utctime_start = Time(utctime_start)
        if utctime_end is not None and not isinstance(utctime_end, Time):
            utctime_end = Time(utctime_end)
  
        # Handle case where both times are None
        if utctime_start is None and utctime_end is None:
            tonight = self._observer.tonight(Time.now())
            starttime, endtime = tonight[0], tonight[1]
        # Handle case where one time is None
        elif utctime_start is None:
            tonight = self._observer.tonight(utctime_end)
            starttime, endtime = tonight[0], utctime_end
        elif utctime_end is None:
            tonight = self._observer.tonight(utctime_start)
            starttime, endtime = utctime_start, tonight[1]
        # Handle case where both times are provided
        else:
            starttime, endtime = utctime_start, utctime_end              

        time_range = [starttime, endtime]
        return is_observable(constraints = self._constraints, observer = self._astroplan_observer, targets = self.target_astroplan, time_range = time_range, time_grid_resolution = time_grid_resolution)
    

    def is_always_observable(self,
                             utctimes : datetime or Time or np.array = None) -> bool:
        """
        Determines whether the targets are always observable during the specified time.

        Parameters
        ----------
        utctimes : datetime or Time or numpy.array, optional
            The time at which to check observability. Defaults to the current time.

        Returns
        -------
        bool
            True if all targets are always observable, False otherwise.

        Raises
        ------
        TypeError
            If the provided time is not a valid datetime, Time, or numpy.array object.
        """
        if utctimes is None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
        return is_always_observable(constraints = self._constraints, observer = self._astroplan_observer, targets = self.target_astroplan, times = utctimes)
    
    def is_event_observable(self,
                            utctimes : datetime or Time or np.array = None) -> bool:
        """
        Determines whether the targets are observable at the specified time or at the current time.

        Parameters
        ----------
        utctimes : datetime or Time or numpy.array, optional
            The time at which to check observability. Defaults to the current time.

        Returns
        -------
        bool
            True if all targets are observable, False otherwise.

        Raises
        ------
        TypeError
            If the provided time is not a valid datetime, Time, or numpy.array object.
        """
        if utctimes is None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
        return is_event_observable(constraints = self._constraints, observer = self._astroplan_observer, target = self.target_astroplan, times = utctimes)
    
    def altaz(self,
              utctimes : datetime or Time or np.array = None) -> SkyCoord:
        """
        Calculate the alt-az coordinates of the targets for the given time(s) in UTC.

        Parameters
        ----------
        utctimes : datetime or Time or numpy.array, optional
            The time(s) to calculate the alt-az coordinates for, in UTC. If not provided, the current time will be used.

        Returns
        -------
        SkyCoord
            The alt-az coordinates of the targets at the specified time(s).

        Raises
        ------
        TypeError
            If the provided time is not a valid datetime, Time, or numpy.array object.
        """
        if utctimes is None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
        return self._astroplan_observer.altaz(utctimes, target = self.target_astroplan)
    
    def risetime(self,
                 utctime : datetime or Time = None ,
                 mode : str = 'nearest',
                 horizon : float = 30,
                 n_grid_points : int = 50) -> Time:
        """
        Calculate the next rise time of the targets as seen by the observer.

        Parameters
        ----------
        utctime : datetime or Time, optional
            The time to start searching for the next rise time. If not provided, the current time will be used.
        mode : str, optional
            The method used to determine the rise time. Possible values are 'next' (the next rise time), 'previous' (the previous rise time), or 'nearest' (the nearest rise time). Default is 'next'.
        horizon : float, optional
            The altitude of the horizon, in degrees. Default is 30.
        n_grid_points : int, optional
            The number of grid points to use in the interpolation. Default is 50.

        Returns
        -------
        Time
            The rise time of the targets as seen by the observer.

        """
        if utctime == None:
            utctime = Time.now()
        if not isinstance(utctime, Time):
            utctime = Time(utctime)
        return self._astroplan_observer.target_rise_time(utctime, target = self.target_astroplan, which = mode, horizon = horizon*u.deg, n_grid_points = n_grid_points)
    
    def settime(self,
                utctime : datetime or Time or np.array = None,
                mode : str = 'nearest',
                horizon : float = 30,
                n_grid_points : int = 50) -> Time:
        """
        Calculate the time when the targets set below the horizon.

        Parameters
        ----------
        utctime : datetime or Time or numpy.array, optional
            The time to use as the reference time for the calculation, by default the current time.
        mode : str, optional
            Set to 'nearest', 'next' or 'previous', by default 'nearest'.
        horizon : float, optional
            The altitude of the horizon in degrees. Default is 30.
        n_grid_points : int, optional
            The number of grid points to use in the interpolation. Default is 50.

        Returns
        -------
        Time
            The time when the targets set below the horizon.

        """
        if utctime is None:
            utctime = Time.now()
        if not isinstance(utctime, Time):
            utctime = Time(utctime)
        return self._astroplan_observer.target_set_time(utctime, self.target_astroplan, which = mode, horizon = horizon*u.deg , n_grid_points = n_grid_points)
    
    def meridiantime(self,
                     utctime : datetime or Time or np.array = None,
                     mode : str = 'nearest',
                     n_grid_points : int = 50) -> Time:
        """
        Calculate the time at which the targets pass through the observer's meridian.

        Parameters
        ----------
        utctime : datetime or Time or numpy.array, optional
            The time at which to calculate the meridian transit time. If not provided, the current time will be used.
        mode : str, optional
            Set to 'nearest', 'next' or 'previous', by default 'nearest'.
        n_grid_points : int, optional
            The number of grid points to use in the interpolation. Default is 50.

        Returns
        -------
        Time
            The time at which the targets pass through the observer's meridian.

        """
        if utctime is None:
            utctime = Time.now()
        if not isinstance(utctime, Time):
            utctime = Time(utctime)
        return self._astroplan_observer.target_meridian_transit_time(utctime, self.target_astroplan, which = mode, n_grid_points = n_grid_points)
    
    def hourangle(self,
                  utctimes : datetime or Time or np.array = None):
        """
        Calculate the hour angle of the targets for the given time(s) in UTC.

        Parameters
        ----------
        utctimes : datetime or Time or numpy.array, optional
            The time(s) to calculate the hour angle of the targets for, in UTC. If not provided, the current time will be used.

        Returns
        -------
        astropy.coordinates.Angle
            The hour angle of the targets at the specified time(s).

        Raises
        ------
        ValueError
            If no target is specified for hourangle.

        """
        if utctimes is None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
        if not isinstance(self.target_astroplan, FixedTarget):
            raise ValueError('No target is specified for hourangle')
        return self._astroplan_observer.target_hour_angle(utctimes, self.target_astroplan)
        
    def _get_coordinate_radec(self,
                              ra,
                              dec,
                              frame : str = 'icrs') -> SkyCoord:
        return SkyCoord(ra = ra, dec = dec, frame = frame, unit = (u.deg, u.deg))

    def _get_target(self,
                    coord,
                    target_name : str = '') -> FixedTarget:
        return FixedTarget(coord = coord, name = target_name)
    
    def _get_constraints(self,
                         TARGET_MINALT : float = None,
                         TARGET_MAXALT : float = None,
                         **kwargs) -> list:
        constraint_all = []
        if (TARGET_MINALT != None) & (TARGET_MAXALT != None):
            constraint_altitude = AltitudeConstraint(min = TARGET_MINALT * u.deg, max = TARGET_MAXALT * u.deg, boolean_constraint = True)
            constraint_all.append(constraint_altitude)
        return constraint_all
    
# %%
