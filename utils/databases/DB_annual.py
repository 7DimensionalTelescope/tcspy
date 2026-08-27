#%%
from tcspy.utils.target import MultiTargets
from tcspy.configuration import mainConfig
from tcspy.utils.connector import SQLConnector
from tcspy.devices.observer import mainObserver
from tcspy.utils.nightsession import NightSession

from astropy.table import Table, vstack
from astropy.time import Time
import astropy.units as u
from astropy.coordinates import SkyCoord
import numpy as np
from astroplan import observability_table
from astroplan import AltitudeConstraint, MoonSeparationConstraint
from tqdm import tqdm
import matplotlib.pyplot as plt
from astropy.io import ascii
# %%

class DB_Annual(mainConfig):
    """
    A class representing data from the TOS database.

    Parameters
    ----------
    utcdate : Time
    	Rename to the current time.
    tbl_name : str
    	Rename the table. 

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
    utcdate : astropy.time.Time
        The current universal time.
    obsinfo : object
        The observer and celestial body information.
    obsnight : object
        The observing information at sunset and sunrise.
    connected
        Whether the connection to the database is alive.

    Methods
    -------
    connect()
        Establish a connection to the MySQL database and set the cursor and executor.
    disconnect()
        Disconnect from the MySQL database and update the connection status flag to False.
    initialize()
    	Initializes the target table to update.
    select_best_targets()
    	Select the best observable targets for observation.
    to_Dynamic()
    	Inserts rows to the 'Daily' table.
    update_targets_count()
    	Update observation counts for target.
    """
    
    def __init__(self,
                 tbl_name : str = 'TOS'):
        super().__init__()       
        self.observer = mainObserver()
        self.tblname = tbl_name
        self.sql = SQLConnector(id_user = self.config['DB_ID'], pwd_user= self.config['DB_PWD'], host_user = self.config['DB_HOSTIP'], db_name = self.config['DB_NAME'])
        self.constraints = self._set_constrints()
        self.nightsession = NightSession()

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

    def change_table(self, 
                     tbl_name : str):
        self.tblname = tbl_name
    
    def initialize(self, 
                   utcdate : Time = Time.now(),
                   initialize_all : bool = False):
        """
        Initializes and updates the target table.

        Parameters
        ----------
        initialize_all : bool
        	Whether to re-calculate all rows of the table, or only the rows that need update.
        """
        #self.connect()
        target_tbl_all = self.data
        
        # If there is targets with no "id", set ID for each target
        rows_to_update_id = [any(row[name] is None for name in ['id']) for row in target_tbl_all]
        if np.sum(rows_to_update_id) > 0:
            self.sql.set_data_id(tbl_name = self.tblname, update_all = False)
            target_tbl_all = self.data
        
        target_tbl_to_update = target_tbl_all
        column_names_to_update = ['risedate', 'bestdate', 'setdate']
        
        # If initialize_all == False, filter the target table that requires update 
        if not initialize_all:
            rows_to_update = [any(row[name] is None or row[name] == '' for name in column_names_to_update) for row in target_tbl_all]
            target_tbl_to_update =  target_tbl_all[rows_to_update]
        
        if len(target_tbl_to_update) == 0:
            return 
        
        multitargetss = MultiTargets(observer = self.observer,
                                          targets_ra = target_tbl_to_update['RA'],
                                          targets_dec = target_tbl_to_update['De'],
                                          targets_name = target_tbl_to_update['objname'])
        
        # Target information 
        rbs_date = multitargetss.rts_date(year = utcdate.datetime.year, time_grid_resolution= 1)
        targetinfo_listdict = [{'risedate' : rd, 'bestdate' : bd, 'setdate' : sd} for rd, bd, sd in rbs_date]
        
        from tcspy.utils.target import SingleTarget
        
        # Exposure information — compute once if all rows share identical params
        exposure_keys = ['exptime', 'count', 'filter_', 'binning', 'obsmode', 'ntelescope']
        first = target_tbl_to_update[0]
        all_same_params = all(
            all(str(row[k]) == str(first[k]) for k in exposure_keys)
            for row in target_tbl_to_update[1:]
        )

        if all_same_params:
            try:
                S = SingleTarget(observer=self.observer,
                                 exptime=first['exptime'],
                                 count=first['count'],
                                 filter_=first['filter_'],
                                 binning=first['binning'],
                                 obsmode=first['obsmode'],
                                 ntelescope=first['ntelescope'])
                shared_exposure = S.exposure_info.copy()
                shared_exposure.pop('specmode_filter')
                shared_exposure.pop('colormode_filter')
                exposureinfo_listdict = [shared_exposure] * len(target_tbl_to_update)
            except:
                exposureinfo_listdict = [dict(status='error')] * len(target_tbl_to_update)
        else:
            exposureinfo_listdict = []
            for target in target_tbl_to_update:
                try:
                    S = SingleTarget(observer=self.observer,
                                     exptime=target['exptime'],
                                     count=target['count'],
                                     filter_=target['filter_'],
                                     binning=target['binning'],
                                     obsmode=target['obsmode'],
                                     ntelescope=target['ntelescope'])
                    exposure_dict = S.exposure_info.copy()
                    exposure_dict.pop('specmode_filter')
                    exposure_dict.pop('colormode_filter')
                    exposureinfo_listdict.append(exposure_dict)
                except:
                    exposureinfo_listdict.append(dict(status='error'))

        values_update_dict = [{**targetinfo_dict, **exposureinfo_dict} for targetinfo_dict, exposureinfo_dict in zip(targetinfo_listdict, exposureinfo_listdict)]

        valid = [(i, v) for i, v in enumerate(values_update_dict) if 'status' not in v]
        if valid:
            valid_indices, valid_values = zip(*valid)
            rows_for_bulk = [{**v, 'id': target_tbl_to_update[i]['id']} for i, v in zip(valid_indices, valid_values)]
            update_keys = list(valid_values[0].keys())
            self.sql.bulk_update_rows(tbl_name=self.tblname, update_keys=update_keys, rows_values=rows_for_bulk, id_key='id')
        print(f'{len(valid) if valid else 0}/{len(target_tbl_to_update)} targets are updated')
    
    def select_best_targets(self,
                            utcdate : Time = Time.now(),
                            size : int = 300,
                            observable_minimum_hour: float = 2,
                            n_time_grid : float = 10,
                            galactic_latitude_limit: float = None,
                            declination_upper_limit: float = None,
                            declination_lower_limit: float = None
                            ):
        if galactic_latitude_limit is None:
            galactic_latitude_limit = self.config.get('TARGET_GALACTIC_LATITUDE_LIMIT', 0)
        if declination_upper_limit is None:
            declination_upper_limit = self.config.get('TARGET_DECLINATION_UPPER_LIMIT', 20)
        if declination_lower_limit is None:
            declination_lower_limit = self.config.get('TARGET_DECLINATION_LOWER_LIMIT', -90)
        obsnight = self.nightsession.set_obsnight(utctime = utcdate)
        observable_fraction_criteria = observable_minimum_hour / obsnight.observable_hour 
        
        #if not self.sql.connected:
        #    self.connect()
        all_targets = self.data
        column_names_for_scoring = ['risedate', 'bestdate', 'setdate']
        
        # If one of the targets do not have the required information, calculate
        rows_to_update = [any(row[name] is None or row[name] == '' for name in column_names_for_scoring) for row in all_targets]
        target_tbl_to_update =  all_targets[rows_to_update]
        if len(target_tbl_to_update) > 0:
            self.initialize(initialize_all= True)
        
        all_target_tbl = self.data
        all_coords = SkyCoord(all_target_tbl['RA'], all_target_tbl['De'], unit ='deg', frame = 'icrs')
        # galactic latitude cut
        highb_idx = np.abs(all_coords.galactic.b.value) > galactic_latitude_limit
        # declination cut
        decl_idx = (all_coords.dec.value < declination_upper_limit) & (all_coords.dec.value > declination_lower_limit)
        # all cut
        total_idx = highb_idx & decl_idx
        target_tbl = all_target_tbl[total_idx]
        
        print('Checking Observability of the targets...')
        obs_tbl = observability_table(constraints = self.constraints.astroplan, 
                                      observer = self.observer._observer,
                                      targets = SkyCoord(target_tbl['RA'], target_tbl['De'], unit = 'deg'), 
                                      time_range = [obsnight.sunset_observation, obsnight.sunrise_observation],
                                      time_grid_resolution = 30 * u.minute)
        target_tbl_observable_idx = obs_tbl['fraction of time observable'] > observable_fraction_criteria
        target_always_idx = target_tbl['risedate'] == 'Always'
        target_neverup_idx = target_tbl['risedate'] == 'Never'
        target_normal_idx =  ~(target_neverup_idx)
        target_tbl_observable = target_tbl[target_tbl_observable_idx & target_normal_idx]
        target_tbl_by_obscount = target_tbl_observable.group_by('obs_count')        
        
        # Create a time grid
        time_grid = obsnight.sunset_observation + np.linspace(0, 1, n_time_grid) * (obsnight.sunrise_observation - obsnight.sunset_observation)
        # Determine the number of targets for each time grid
        n_target_for_each_timegrid = np.full(n_time_grid, size / n_time_grid, dtype = int)
        n_target_for_each_timegrid[len(n_target_for_each_timegrid)//2] += size - sum(n_target_for_each_timegrid)

        best_targets = Table()
        for target_tbl_for_scoring in target_tbl_by_obscount.groups:
            
            # Sort all observable targets by declination in descending order
            target_tbl_for_scoring_sorted = target_tbl_for_scoring[np.argsort(-target_tbl_for_scoring['De'])]
            multitargets_for_scoring = MultiTargets(
                observer=self.observer,
                targets_ra=target_tbl_for_scoring_sorted['RA'],
                targets_dec=target_tbl_for_scoring_sorted['De'],
                targets_name=target_tbl_for_scoring_sorted['objname']
            )
            maxalt = 90 - np.abs(self.config['OBSERVER_LATITUDE'] - target_tbl_for_scoring_sorted['De'])
        
            # Allocate targets across time grids
            selected_indices = []
            best_target_group = Table()
            for i, (n_target, time) in enumerate(zip(n_target_for_each_timegrid, time_grid)):
                # Check the altitude and moon separation for sorted targets at the current time

                altaz = multitargets_for_scoring.altaz(utctimes=time)
                score = altaz.alt.value / maxalt
                moonsep = multitargets_for_scoring.moon_sep(utctime=time)

                # Filter targets meeting criteria
                high_scored_idx = ((score > 0.7) &
                                   (altaz.alt.value > self.config['TARGET_MINALT']) &
                                   (moonsep > self.config['TARGET_MOONSEP']))

                available_indices = np.where(high_scored_idx)[0]
                available_indices = np.setdiff1d(available_indices, selected_indices)

                # Select up to n_target targets
                if len(available_indices) < n_target:
                    selected_idx = available_indices
                else:
                    selected_idx = available_indices[:n_target]

                n_target_for_each_timegrid[i] -= len(selected_idx)
                selected_indices.extend(selected_idx)
                best_target_group = target_tbl_for_scoring_sorted[list(selected_indices)]
                if len(selected_indices) >= size:
                    break
            best_targets = vstack([best_targets, best_target_group])
        # Return the selected targets
        return best_targets[:size]

    def to_Dynamic(self,
                 target_tbl : Table):
        """
        Insert targets to dynamic.

        Parameters
        ----------
        target_tbl : Table
        	The table containing the targets.
        """
        self.sql.insert_rows(tbl_name = 'Dynamic', data = target_tbl)
    
    def update_target(self,
                     target_id : str,
                     update_keys : list,
                     update_values : list,
                     id_key : str = 'id'
                     ):
        """
        Update observation counts for target.

        Parameters
        -------
        targets_id : list or np.array
        	A list containing the id of each target.
        targets_count : int or list or np.array
        	A list containing the count of each target or int to set the all observations to.
        """
        self.sql.update_row(tbl_name = self.tblname, update_value = update_values, update_key = update_keys, id_value = target_id, id_key = id_key)
    
    @property
    def data(self):
        """
        Retrieves the data from the database.

        Returns
        -------
        Table
        	The table containing the data from the database. 
        """
        return self.sql.get_data(tbl_name = self.tblname, select_key= '*')
    
    def visualize(self, 
                show_observed: bool = True, 
                tileinfo_filepath: str = '../databases/sky-grid and tiling/7-DT/final_tiles.txt'):
        from matplotlib.patches import Polygon
        from astropy.table import join

        # Read the tile information from the ASCII file
        tileinfo = ascii.read(tileinfo_filepath)
        # Extract tile information from the database
        observed_tiles_in_DB = self.data[self.data['obs_count'] > 0]        
        observed_tileinfo = join(tileinfo, observed_tiles_in_DB, keys_left = 'id', keys_right = 'objname', join_type = 'inner')
        observed_tileinfo['ob_couunt'] = observed_tiles_in_DB['obs_count']
        
        # Prepare figure and axis
        fig = plt.figure(figsize=(12, 6), dpi=300)
        ax = fig.add_subplot(111, projection="mollweide")
           
        # Helper function to convert degrees to radians (for Mollweide projection)
        def to_radians(ra, dec):
            # Convert RA to the range [-180, 180) in radians
            ra = np.deg2rad(ra - 180)
            dec = np.deg2rad(dec)
            return ra, dec

        # Loop through tiles and add them as polygons
        for tile in tileinfo:
            # Extract the corners
            corners = [
                (tile['ra1'], tile['dec1']),
                (tile['ra2'], tile['dec2']),
                (tile['ra3'], tile['dec3']),
                (tile['ra4'], tile['dec4']),
            ]
            
            # Convert corners to radians for plotting
            corners_rad = [to_radians(ra, dec) for ra, dec in corners]

            # Create a polygon for the tile
            polygon = Polygon(corners_rad, closed=True, edgecolor='black', facecolor='black', alpha=0.1, linewidth=0.3)
            ax.add_patch(polygon)

        if show_observed:
            for tile in observed_tileinfo:
                # Extract the corners
                corners = [
                    (tile['ra1'], tile['dec1']),
                    (tile['ra2'], tile['dec2']),
                    (tile['ra3'], tile['dec3']),
                    (tile['ra4'], tile['dec4']),
                ]
                centers = (tile['ra'], tile['dec'])
                
                # Convert corners to radians for plotting
                corners_rad = [to_radians(ra, dec) for ra, dec in corners]
                
                # Create a polygon for the tile
                ax.scatter(*to_radians(centers[0], centers[1]), color='red', s=5, alpha = 0.5)
                #polygon = Polygon(corners_rad, closed=True, edgecolor='red', facecolor='red', alpha=0.3, linewidth=0.3)
                #ax.add_patch(polygon)
        
        # Configure the Mollweide projection
        ax.grid(True, linestyle='--', alpha=0.5)
        ax.set_xticklabels(
            ['14h', '16h', '18h', '20h', '22h', '0h', '2h', '4h', '6h', '8h', '10h'], 
            fontsize=10
        )

        # Title and show the plot
        plt.title('Sky Tiles Visualization in Mollweide Projection')
        plt.show()
    
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

    def _set_constrints(self):
        class constraint: pass
        constraint_astroplan = []
        if (self.config['TARGET_MINALT'] != None) & (self.config['TARGET_MAXALT'] != None):
            constraint_altitude = AltitudeConstraint(min = self.config['TARGET_MINALT'] * u.deg, max = self.config['TARGET_MAXALT'] * u.deg, boolean_constraint = False)
            constraint_astroplan.append(constraint_altitude)
            constraint.minalt = self.config['TARGET_MINALT']
            constraint.maxalt = self.config['TARGET_MAXALT']
        if self.config['TARGET_MOONSEP'] != None:
            constraint_moonsep = MoonSeparationConstraint(min = self.config['TARGET_MOONSEP'] * u.deg, max = None)
            constraint_astroplan.append(constraint_moonsep)
            constraint.moonsep = self.config['TARGET_MOONSEP']
        constraint.astroplan = constraint_astroplan
        return constraint  
# %%
if __name__ == '__main__':
    import matplotlib.pyplot as plt
    self = DB_Annual()
# %%
# if __name__ == '__main__':
#     import numpy as np
#     import matplotlib.pyplot as plt
        
#     survey_data = db.data
#     all_coords = SkyCoord(survey_data['RA'], survey_data['De'], unit ='deg', frame = 'icrs')
#     # galactic latitude cut
#     highb_idx = np.abs(all_coords.galactic.b.value) > 20
#     # declination cut
#     decl_idx = (all_coords.dec.value < -20) & (all_coords.dec.value > -90)
#     # all cut
#     total_idx1 = highb_idx# & decl_idx
#     total_idx2 = highb_idx & decl_idx

#     survey_tbl = survey_data[total_idx1]
#     survey_tbl2 = survey_data[total_idx2]

    
#     all_data = db.data
#     obs_data = all_data[all_data['obs_count'] > 0]
#     high_data = all_data[all_data['obs_count'] > 3]
#     intense_data = all_data[all_data['obs_count'] > 10]
#     tonight_data = db.select_best_targets(size = 100)


#     # Convert RA to radians and shift to [-180, 180] range
#     def convert_ra(ra):
#         return np.radians((ra + 180) % 360 - 180)

#     # Convert Dec to radians
#     def convert_dec(dec):
#         return np.radians(dec)

#     plt.figure(figsize=(10, 5), dpi=300)
#     ax = plt.subplot(111, projection="mollweide")

#     # Convert RA and Dec for plotting
#     all_ra = convert_ra(survey_tbl['RA'])
#     all_dec = convert_dec(survey_tbl['De'])
#     survey_ra = convert_ra(survey_tbl2['RA'])
#     survey_dec = convert_dec(survey_tbl2['De'])

#     obs_ra = convert_ra(obs_data['RA'])
#     obs_dec = convert_dec(obs_data['De'])

#     high_ra = convert_ra(high_data['RA'])
#     high_dec = convert_dec(high_data['De'])

#     intense_ra = convert_ra(intense_data['RA'])
#     intense_dec = convert_dec(intense_data['De'])
    
#     tonight_ra = convert_ra(tonight_data['RA'])
#     tonight_dec = convert_dec(tonight_data['De'])

#     # Plot data
#     ax.scatter(all_ra, all_dec, s=1, c='k', alpha=0.2, label="|l| > 20")
#     ax.scatter(survey_ra, survey_dec, s=1, c='k', alpha=0.3, label="|l| > 20 & Decl < -20")
#     ax.scatter(obs_ra, obs_dec, s=1, c='r', alpha=0.5, label="Observed")
#     ax.scatter(high_ra, high_dec, s=5, c='orange', alpha=0.5, label="N_obs >3")
#     ax.scatter(intense_ra, intense_dec, s=10, c='r', alpha=1.0, label="N_obs >10")
#     #ax.scatter(tonight_ra, tonight_dec, s=1, c='b', alpha=1, label="Tonight scheduled")

#     # Labels and grid
#     ax.set_xticklabels(['14h', '16h', '18h', '20h', '22h', '0h', '2h', '4h', '6h', '8h', '10h'])
#     ax.grid(True)
#     plt.legend()
#     plt.title(f"7DT RIS Observations on {Time.now().datetime.strftime('%Y-%m-%d')}")
#     plt.show()

# # %%
