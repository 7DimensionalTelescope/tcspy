#%%
from tcspy.configuration import mainConfig
from tcspy.devices.observer import mainObserver
from tcspy.utils.target import MultiTargets
from tcspy.utils.target import SingleTarget
from tcspy.utils.connector import SQLConnector
from tcspy.utils.nightsession import NightSession

from astropy.table import Table  
from astropy.time import Time
import astropy.units as u
from astropy.coordinates import SkyCoord
import numpy as np
from astroplan import observability_table
from astroplan import AltitudeConstraint, MoonSeparationConstraint
from tqdm import tqdm
import os
# %%

class DB_Dynamic(mainConfig):
    """
    class of Dynamic target table for the observation of each night.

    Parameters
    ----------
    utctime : astropy.time.Time
        The current universal time.
    tbl_name : str
        The name of the database table used for this observing information.

    Attributes
    ----------
    observer : mainObserver
        The station observing the night sky.
    tblname : str
        The name of the table used to track the observing information.
    sql : SQLConnector
        A connection to the SQL database.
    constraints : constraint
        The observer's constraints.
    utctime : astropy.time.Time
        The current universal time.
    obsinfo : object
        The observer and celestial body information.
    obsnight : object
        The observing information at sunset and sunrise.
    connected
        Whether the connection to the database is alive.

    Methods
    -------
    connect(self)
        Establish a connection to the MySQL database and set the cursor and executor.
    disconnect(self)
        Disconnect from the MySQL database and update the connection status flag to False.
    initialize(self, initialize_all)
        Initialize the target status if it requires updates.
    best_target(self, utctime, duplicate)
        Returns the best target to observe.
    insert(self, target_tbl)
        Insert a new record into the table.
    update_target(self, update_value, update_key, id_value, id_key)
        Update an existing target's attribute.
    data(self)
        Return the entire information stored in the table.
    """
    
    def __init__(self,
                 utctime : Time = Time.now(),
                 tbl_name : str = 'Dynamic'):

        super().__init__()       
        self.observer = mainObserver()
        self.tblname = tbl_name
        self.sql = SQLConnector(id_user = self.config['DB_ID'], pwd_user= self.config['DB_PWD'], host_user = self.config['DB_HOSTIP'], db_name = self.config['DB_NAME'])
        self.constraints = self._set_constrints()
        self.utctime = utctime
        self.obsinfo = self._set_obs_info(utctime = utctime)
        self.obsnight = NightSession(utctime = utctime).obsnight_utc
    '''
    @property    
    def connected(self):
        return self.sql.connected
    
    def connect(self):
        """
        Establish a connection to the MySQL database and set the cursor and executor.
        """
        self.sql.connect()
    
    def disconnect(self):
        """
        Disconnects from the MySQL database and update the connection status flag to 
        """
        self.sql.disconnect()
    '''
    def disconnect(self):
        """
        Disconnects from the MySQL database and update the connection status flag to 
        """
        self.sql.disconnect()
        
    def initialize(self, 
                   initialize_all : bool = False):       
        """
        Initializes the target status if it requires updates.

        Parameters
        ----------
        initialize_all : bool
            Boolean flag to control whether all targets should be initialized or not. Defaults to False.
        """
        #self.connect()
        target_tbl_all = self.data
        
        # If there is targets with no "id", set ID for each target
        rows_to_update_id = [any(row[name] in (None, '') for name in ['id']) for row in target_tbl_all]
        if np.sum(rows_to_update_id) > 0:
            self.sql.set_data_id(tbl_name = self.tblname, update_all = False)
            target_tbl_all = self.data
        
        target_tbl_to_update = target_tbl_all
        column_names_to_update = ['id', 'binning', 'risetime', 'transittime', 'settime', 'besttime', 'maxalt', 'moonsep']
        
        # If initialize_all == False, filter the target table that requires update 
        if not initialize_all:
            rows_to_update = [any(row[name] is None or row[name] == '' for name in column_names_to_update) for row in target_tbl_all]
            target_tbl_to_update =  target_tbl_all[rows_to_update]
        
        if len(target_tbl_to_update) == 0:
            return 
        
        multitargets = MultiTargets(observer = self.observer,
                                   targets_ra = target_tbl_to_update['RA'],
                                   targets_dec = target_tbl_to_update['De'],
                                   targets_name = target_tbl_to_update['objname'])
        print(f'Calculating celestial information of {len(multitargets.coordinate)} targets...')
        
        # Target information 
        risetime_tmp = self._get_risetime(multitargets = multitargets, utctime = self.obsnight.sunrise_civil, mode = 'previous', horizon = self.config['TARGET_MINALT'], n_grid_points= 100)
        settime_tmp = self._get_settime(multitargets = multitargets, utctime = self.obsnight.sunset_civil, mode = 'next', horizon = self.config['TARGET_MINALT'], n_grid_points= 100)
        # If targets are always up
        risetime = Time(np.array([self.obsnight.sunset_astro.value if rt.mask else np.array(rt.value) for rt in risetime_tmp]), format = 'jd')
        settime_tmp2 = Time(np.array([(self.obsnight.sunset_astro + 1 * u.day).value if st.mask else np.array(st.value) for st in settime_tmp]), format = 'jd')
        # If targets are never up
        settime = Time([st - 1*u.day if (st - rt).value > 1 else st for rt, st in zip(risetime, settime_tmp2)])
        transittime, maxalt, besttime = self._get_transit_besttime(multitargets = multitargets)
        moonsep = self._get_moonsep(multitargets = multitargets)
        targetinfo_listdict = [{'risetime' : rt, 'transittime' : tt, 'settime' : st, 'besttime' : bt, 'maxalt' : mt, 'moonsep': ms} for rt, tt, st, bt, mt, ms in zip(risetime.isot, transittime.isot, settime.isot, besttime.isot, maxalt, moonsep)]

        # Exposure information
        exposureinfo_listdict = []
        for target in target_tbl_to_update:
            try:
                S = SingleTarget(observer = self.observer, 
                                exptime = target['exptime'], 
                                count = target['count'], 
                                filter_ = target['filter_'], 
                                binning = target['binning'], 
                                colormode = target['colormode'],
                                specmode = target['specmode'],
                                obsmode = target['obsmode'],
                                gain = target['gain'],
                                ntelescope = target['ntelescope'])
                exposure_info = S.exposure_info
                del exposure_info['specmode_filter']
                del exposure_info['colormode_filter']
                exposureinfo_listdict.append(exposure_info)
            except:
                exposureinfo_listdict.append(dict(status = 'error'))

        values_update = [{**targetinfo_dict, **exposureinfo_dict} for targetinfo_dict, exposureinfo_dict in zip(targetinfo_listdict, exposureinfo_listdict)]
                
        for i, value in enumerate(tqdm(values_update)):
            target_to_update = target_tbl_to_update[i]  
            self.sql.update_row(tbl_name = self.tblname, update_value = list(value.values()), update_key = list(value.keys()), id_value= [target_to_update['id']], id_key = ['id'])
        print(f'{len(target_tbl_to_update)} targets are updated')
        return self.data
    
    def best_target(self,
                    utctime : Time = Time.now(),
                    force_non_ToO : bool = False):
        """
        Returns the best target to observe.

        Parameters
        ----------
        utctime : astropy.time.Time
            The current universal time. Defaults to the current time.
        duplicate : bool
            Whether to allow duplicate targets. Defaults to False.
        """
        all_targets = self.data
        column_names_for_scoring = ['exptime_tot', 'id', 'risetime', 'transittime', 'settime', 'besttime', 'maxalt', 'moonsep']
        
        # If one of the targets do not have the required information, initialize
        rows_to_update = [any(row[name] is None or row[name] == '' for name in column_names_for_scoring) for row in all_targets]
        target_tbl_to_update =  all_targets[rows_to_update]
        if len(target_tbl_to_update) > 0:
            target_all = self.initialize(initialize_all= False)
        else:
            target_all = self.data
        idx_ToO = target_all['is_ToO'] == 1
        target_ToO = target_all[idx_ToO]
        target_ordinary = target_all[~idx_ToO]
        
        # If there is any observable ToO target, return ToO target with the scoring algorithm
        if not force_non_ToO:
            exist_ToO = (len(target_ToO) > 0)
            if exist_ToO:
                target_best, target_score = self._scorer(utctime = utctime, target_tbl = target_ToO)        
                if target_score:
                    return target_best, target_score
        
        # Else, ordinary targets are scored with the group. First, Observe Group 1 target, seconds, group 2 targets, and so on...
        exist_ordinary = (len(target_ordinary) > 0)
        if exist_ordinary:
            target_ordinary_by_group = target_ordinary.group_by('priority').groups
            for target_ordinary_group in target_ordinary_by_group:
                target_best, target_score = self._scorer(utctime = utctime, target_tbl = target_ordinary_group)        
                if target_score:
                    return target_best, target_score
        return None, None
    
    def insert(self,
               target_tbl : Table):
        """
        Inserts a new record into the table.

        Parameters
        ----------
        target_tbl : Table
            An astropy table containing the target data to be inserted.
        """
        insertion_result = self.sql.insert_rows(tbl_name = self.tblname, data = target_tbl)
        return insertion_result
        
    def update_target(self,
                      update_values,
                      update_keys,
                      id_value,
                      id_key = ['objname','id']):
        """
        Updates an existing target's attribute.

        Parameters
        ----------
        update_value: various
            The new value to be updated.
        update_key: str
            The attribute key to be updated.
        id_value: int, str, etc
            The id value of the target to be updated.
        id_key: str
            The attribute key used to identify the target. 
        """
        self.sql.update_row(tbl_name = self.tblname,
                            update_value = update_values,
                            update_key = update_keys,
                            id_value = id_value,
                            id_key = id_key)
    
    def from_TOS(self,
                 utcdate : Time = Time.now(),
                 size : int = 100,
                 observable_minimum_hour : float = 2,
                 n_time_grid : float = 10,
                 ):
        from tcspy.utils.databases import DB_Annual
        TOS = DB_Annual(tbl_name = 'TOS')
        best_targets = TOS.select_best_targets(utcdate = utcdate, size = size, observable_minimum_hour = observable_minimum_hour, n_time_grid = n_time_grid)
        self.insert(best_targets)
        print(f'{len(best_targets)} TOS targets are inserted')
        
    def from_IMS(self):
        from tcspy.utils.databases import DB_Annual
        IMS = DB_Annual(tbl_name = 'IMS')
        best_targets = IMS.data
        self.insert(best_targets)
        print(f'{len(best_targets)} IMS targets are inserted')
    
    def update_7DS_obscount(self,
                            remove : bool = False,
                            reset_status: bool = True,
                            update_RIS : bool = True,
                            update_IMS : bool = True,
                            update_WFS : bool = False):
        dynamic_tbl = self.data
        obs_tbl = dynamic_tbl[dynamic_tbl['status'] == 'observed']
        from tcspy.utils.databases import DB_Annual
        DB_annual = DB_Annual()
        
        observed_ids = []
        update_survey_list = [tbl_name for tbl_name, do_update in zip(['RIS', 'IMS', 'WFS'],[update_RIS, update_IMS, update_WFS]) if do_update]
        for tbl_name in update_survey_list:
            try:
                DB_annual.change_table(tbl_name)
                DB_data = DB_annual.data
                obscount = 0
                for target in obs_tbl:    
                    count_before = DB_data[DB_data['objname'] == target['objname']]['obs_count']
                    if len(count_before) == 1:
                        today_str = Time.now().isot[:10]
                        DB_annual.update_target(target_id = target['objname'], update_keys = ['obs_count','note','last_obsdate'], update_values = [count_before[0]+1, target['note'], today_str], id_key = 'objname')
                        obscount +=1
                        observed_ids.append(target['id'])
                print(f'{obscount} {DB_annual.tblname} tiles are updated')
            except:
                pass
        if reset_status:
            for id_ in observed_ids:
                self.update_target(update_values = ['unscheduled'], update_keys = ['status'], id_value = id_, id_key = 'id')
        if remove:
            self.sql.remove_rows(tbl_name = self.tblname, ids = observed_ids)

        DB_annual.disconnect()
        
    def from_GSheet(self,
                    sheet_name : str,
                    update: bool = True
                    ):
        from tcspy.utils.connector import GoogleSheetConnector
        print('Connecting to DB...')
        gsheet = GoogleSheetConnector(spreadsheet_url = self.config['GOOGLESHEET_URL'], 
                                      authorize_json_file = self.config['GOOGLESHEET_AUTH'],
                                      scope = self.config['GOOGLESHEET_SCOPE'])  
        tbl_sheet = gsheet.read_sheet(sheet_name = sheet_name, format_ = 'Table')
        # Insert data
        print('Inserting GoogleSheet data to DB...')
        insertion_result = self.insert(tbl_sheet)
        # Update google sheet 
        if update:
            tbl_sheet['is_inputted'] = insertion_result
            print('Updating GoogleSheet data...')
            gsheet.write_sheet(sheet_name = sheet_name, data = tbl_sheet, append = False, clear_header = False)        
    
    def clear(self, 
            clear_only_7ds: bool = True,
            clear_only_observed: bool = False):
        """
        Clears rows from the database table based on the specified conditions.

        Parameters:
            clear_only_7ds (bool): If True, only clear rows with objtype in ['RIS', 'IMS', 'WFS'].
            clear_only_observed (bool): If True, only clear rows with status 'observed'.
        """
        data = self.data  # Assuming `self.data` is a DataFrame or similar structure.

        if clear_only_7ds and clear_only_observed:
            # Clear rows that are both 7DS objects and observed.
            filtered_data = data[
                ((data['objtype'] == 'RIS') | 
                (data['objtype'] == 'IMS') | 
                (data['objtype'] == 'WFS')) & 
                (data['status'] == 'observed')
            ]
        elif clear_only_7ds:
            # Clear only 7DS objects.
            filtered_data = data[
                (data['objtype'] == 'RIS') | 
                (data['objtype'] == 'IMS') | 
                (data['objtype'] == 'WFS')
            ]
        elif clear_only_observed:
            # Clear only observed objects.
            filtered_data = data[data['status'] == 'observed']
        else:
            # Clear all rows if no specific filter is applied.
            filtered_data = data

        # Extract IDs of rows to be cleared.
        all_ids = filtered_data['id']

        # Remove rows from the database table.
        self.sql.remove_rows(tbl_name=self.tblname, ids=all_ids)
    
    @property
    def data(self):
        """
        Returns the entire data stored in the table.

        Parameters
        ----------
        None

        Returns
        -------
        Table
            An astropy table containing all the data in the observing table.
        """
        #if not self.sql.connected:
        #    self.connect()
        return self.sql.get_data(tbl_name = self.tblname, select_key= '*')
        
    def export_to_csv(self, save_type : str = 'status' #status or history
                      ):
        """

        """
        try:
            tbl = self.data
            if save_type.lower() == 'history':
                dt_ut = Time.now().datetime     
                if not os.path.exists(self.config['DB_HISTORYPATH']):
                    os.makedirs(self.config['DB_HISTORYPATH'], exist_ok = True) 
                file_abspath =  os.path.join(self.config['DB_HISTORYPATH'], f'Dynamic_%.4d%.2d%.2d.{self.config["DB_HISTORYFORMAT"]}' % (dt_ut.year, dt_ut.month, dt_ut.day))
                tbl.write(file_abspath, format = self.config['DB_HISTORYFORMAT'], overwrite = True)
                print(f"Exported Dynamic table to {file_abspath}")

            elif save_type.lower() == 'status':
                if not os.path.exists(self.config['DB_STATUSPATH']):
                    os.makedirs(self.config['DB_STATUSPATH'], exist_ok = True)
                file_abspath = os.path.join(self.config['DB_STATUSPATH'], f'DB_Dynamic.{self.config["DB_STATUSFORMAT"]}')
                tbl.write(file_abspath, format= self.config['DB_STATUSFORMAT'], overwrite=True)
                print(f"Exported Dynamic table to {file_abspath}")
            
            else:
                raise ValueError(f"Invalid save_type: {save_type}")
        except Exception as e:
            print(f"Failed to export data: {e}")
    
    def _scorer(self,
                utctime : Time,
                target_tbl : Table
                ):
        
        def calc_constraints(target_tbl_for_scoring):
            multitargets = MultiTargets(observer = self.observer,
                                    targets_ra = target_tbl_for_scoring['RA'],
                                    targets_dec = target_tbl_for_scoring['De'],
                                    targets_name = target_tbl_for_scoring['objname'])
            
            multitarget_altaz = multitargets.altaz(utctimes = utctime)
            multitarget_alt = multitarget_altaz.alt.value
            
            score = np.ones(len(target_tbl_for_scoring))
            # Applying constraints
            constraint_moonsep = target_tbl_for_scoring['moonsep'].astype(float) > self.constraints.moon_separation
            score *= constraint_moonsep
            
            constraint_altitude_min = multitarget_alt > self.constraints.minalt
            score *= constraint_altitude_min
            
            constraint_altitude_max = multitarget_alt < self.constraints.maxalt
            score *= constraint_altitude_max
            
            constraint_set = (utctime + target_tbl_for_scoring['exptime_tot'].astype(float) * u.s < Time(target_tbl_for_scoring['settime'])) & (utctime + target_tbl_for_scoring['exptime_tot'].astype(float) * u.s < self.obsnight.sunrise_astro)
            #score *= constraint_set
            
            constraint_night = self.observer.is_night(utctimes = utctime)
            #score *= constraint_night
            return score, multitarget_alt
        
        # Start
        target_tbl_for_scoring = target_tbl
        # Exclude scheduled targets
        unscheduled_idx = (target_tbl['status'] == 'unscheduled')
        target_tbl_for_scoring = target_tbl[unscheduled_idx]
        
        # Exit when no observable target
        if len(target_tbl_for_scoring) == 0:
            return None, None
        
        obstime_nonspecified_idx = (target_tbl_for_scoring['obs_starttime'] == None) | (target_tbl_for_scoring['obs_starttime'] == "")
        obstime_fixed_targets = target_tbl_for_scoring[~obstime_nonspecified_idx]
        obstime_nonfixed_targets = target_tbl_for_scoring[obstime_nonspecified_idx]
         
        # When target observation time is specified       
        urgent_targets = Table()
        if len(obstime_fixed_targets) > 0:
            obstime = Time([Time(time) for time in obstime_fixed_targets['obs_starttime']])
            time_left_sec = (obstime - utctime).sec
            urgent_targets = obstime_fixed_targets[(time_left_sec < 0) & (obstime < self.obsnight.sunrise_observation) & (obstime > self.obsnight.sunset_observation)]
            if len(urgent_targets) > 0:
                score, alt = calc_constraints(urgent_targets)
                urgent_targets_scored = urgent_targets[score.astype(bool)]
                # If urgent target observable exists, return the target and score 1
                if len(urgent_targets_scored) > 0:
                    urgent_obstime = Time([Time(time) for time in urgent_targets_scored['obs_starttime']])
                    urgent_targets_scored['obs_starttime'] = urgent_obstime
                    urgent_targets_scored.sort('obs_starttime')
                    return urgent_targets_scored[0], 1
        
        # When target observation time is not specified
        if len(obstime_nonfixed_targets) == 0:
            return None, None
        
        score, multitarget_alt = calc_constraints(obstime_nonfixed_targets)
                
        # Exit when no observable target
        if np.sum(score) == 0:
            return None, None
        
        multitarget_priority = obstime_nonfixed_targets['weight'].astype(float)
        weight_sum = self.config['TARGET_WEIGHT_ALT'] + self.config['TARGET_WEIGHT_PRIORITY']
        weight_alt = self.config['TARGET_WEIGHT_ALT'] / weight_sum
        weight_priority = self.config['TARGET_WEIGHT_PRIORITY'] / weight_sum
        
        multitarget_alt = np.array([0 if target_alt <= 0 else target_alt for target_alt in multitarget_alt])
        score_relative_alt = weight_alt * np.clip(0, 1, (multitarget_alt) / (np.abs(obstime_nonfixed_targets['maxalt'])))
        
        highest_priority = np.max(multitarget_priority)
        score_weight = weight_priority* (multitarget_priority / highest_priority)

        score_all = (score_relative_alt  + score_weight) 
        score *= score_all
        idx_best = np.argmax(score)
        score_best = score[idx_best]
        return target_tbl_for_scoring[idx_best], score_best

    def _set_obs_info(self,
                      utctime : Time = Time.now()):
        class info: pass
        info.moon_phase = self.observer.moon_phase(utctime)
        info.moon_radec = self.observer.moon_radec(utctime)
        info.sun_radec = self.observer.sun_radec(utctime)
        info.observer_info = self.observer.get_status()
        info.observer_astroplan = self.observer._observer
        info.is_night = self.observer.is_night(utctime)
        return info

    def _set_constrints(self):
        class constraint: pass
        constraint_astroplan = []
        if (self.config['TARGET_MINALT'] != None) & (self.config['TARGET_MAXALT'] != None):
            constraint_altitude = AltitudeConstraint(min = self.config['TARGET_MINALT'] * u.deg, max = self.config['TARGET_MAXALT'] * u.deg, boolean_constraint = False)
            constraint_astroplan.append(constraint_altitude)
            constraint.minalt = self.config['TARGET_MINALT']
            constraint.maxalt = self.config['TARGET_MAXALT']
        if self.config['TARGET_MOONSEP'] != None:
            constraint_gallatitude = MoonSeparationConstraint(min = self.config['TARGET_MOONSEP'] * u.deg, max = None)
            constraint_astroplan.append(constraint_gallatitude)
            constraint.moon_separation = self.config['TARGET_MOONSEP']
        constraint.astroplan = constraint_astroplan
        return constraint
    
    def _get_moonsep(self,
                     multitargets : MultiTargets):
        '''
        multitargets = MultiTargets(observer = self.observer, 
                            targets_ra = target_tbl['RA'], 
                            targets_dec = target_tbl['De'],    
                            targets_name = target_tbl['objname'])
        '''
        all_coords = multitargets.coordinate
        moon_coord = SkyCoord(ra =self.obsinfo.moon_radec.ra.value, dec = self.obsinfo.moon_radec.dec.value, unit = 'deg')
        moonsep = np.array(all_coords.separation(moon_coord).value).round(2)
        return moonsep        
        
    def _get_risetime(self,
                      multitargets : MultiTargets,
                      **kwargs):
        if len(multitargets.coordinate) == 1:
            risetime = [multitargets.risetime(**kwargs)]
        else:
            risetime = multitargets.risetime(**kwargs)
        return Time(risetime)
    
    def _get_settime(self,
                     multitargets : MultiTargets,
                     **kwargs):
        if len(multitargets.coordinate) == 1:
            settime = [multitargets.settime(**kwargs)]
        else:
            settime = multitargets.settime(**kwargs)
        return Time(settime)
        
    def _get_transit_besttime(self,
                              multitargets : MultiTargets):
        
        all_time_hourangle = multitargets.hourangle(self.obsnight.midnight)
        all_hourangle_converted = [hourangle if (hourangle -12 < 0) else hourangle-24 for hourangle in all_time_hourangle.value]
        all_target_altaz_at_sunset = multitargets.altaz(utctimes=self.obsnight.sunset_astro)
        all_target_altaz_at_sunrise = multitargets.altaz(utctimes=self.obsnight.sunrise_astro)
        all_transittime = self.obsnight.midnight - all_hourangle_converted * u.hour
        all_besttime = []
        all_maxalt = []
        for i, target_info in enumerate(zip(all_transittime, multitargets.coordinate)):
            target_time_transit, target_coord = target_info
            if (target_time_transit > self.obsnight.sunset_astro) & (target_time_transit < self.obsnight.sunrise_astro):
                maxaltaz = self.obsinfo.observer_astroplan.altaz(target_time_transit, target = target_coord)
                maxalt = np.round(maxaltaz.alt.value,2)
                all_besttime.append(target_time_transit)
            else:
                sunset_alt = all_target_altaz_at_sunset[i].alt.value
                sunrise_alt = all_target_altaz_at_sunrise[i].alt.value
                maxalt = np.round(np.max([sunset_alt, sunrise_alt]),2)
                if sunset_alt > sunrise_alt:
                    all_besttime.append(self.obsnight.sunset_astro)
                else:
                    all_besttime.append(self.obsnight.sunrise_astro)
            all_maxalt.append(maxalt)
        return all_transittime, all_maxalt, Time(all_besttime)

    def _get_target_observable(self,
                               multitargets : MultiTargets,
                               fraction_observable : float = 0.1):
        observability_tbl = observability_table(constraints = self.constraints, observer = multitargets._astroplan_observer, targets = multitargets.coordinate , time_range = [self.obsnight.sunset_astro, self.obsnight.sunrise_astro], time_grid_resolution = 20 * u.minute)
        obs_tbl['fraction_obs'] = ['%.2f'%fraction for fraction in observability_tbl['fraction of time observable']]
        key = observability_tbl['fraction of time observable'] > fraction_observable
        obs_tbl = obs_tbl[key]

# %%
if __name__ == '__main__':
    self = DB_Dynamic(Time.now())
# %%
