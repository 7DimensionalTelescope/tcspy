
#%%
from astropy.io import ascii
from astropy.table import Table
from astropy.time import Time
import json
import re
from typing import List
import uuid
import numpy as np
from astropy.coordinates import Angle
import astropy.units as u
from tcspy.utils.target import MultiTargets
from tcspy.utils.databases.tiles import Tiles
from tcspy.utils import NightSession
#%%

class Alert:
    
    def __init__(self):
        self.rawdata = None # raw data of the alert
        self.alert_data = None # raw data of the alert
        self.alert_type = None # mail_broker, mail_user, googlesheet, gw, table
        self.alert_sender = 'Undefined' # sender of the alert
        self.formatted_data = None # formatted data of the alert
        self.is_inputted = False # after inputting the alert data to the scheduler, set it to True
        self.is_observed = False # after observing the alert, set it to True
        self.num_observed_targets = 0 # number of observed targets
        self.is_matched_to_tiles = False
        self.distance_to_tile_boundary = None
        self.update_time = None
        self.key = uuid.uuid4().hex # unique key for the alert
        self.historypath = None
        self.statuspath = None
        self._tiles = None
    
    def __repr__(self):
        txt = (f'ALERT (type = {self.alert_type}, sender = {self.alert_sender}, inputted = {self.is_inputted}, observed = {self.is_observed}, history_path = {self.historypath}')
        return txt   
    
    @property
    def default_config(self):
        default_config = dict()
        default_config['exptime'] = 60
        default_config['count'] = 5
        default_config['obsmode'] = 'Single'
        default_config['filter_'] = 'r'
        default_config['colormode'] = 'None'
        default_config['specmode'] = 'None'
        default_config['ntelescope'] = 1
        default_config['priority'] = 50
        default_config['weight'] = 1
        default_config['binning'] = 1
        default_config['gain'] = 25
        default_config['objtype'] = 'Request'
        default_config['is_ToO'] = 1
        default_config['is_rapidToO'] = 0
        default_config['id'] = self.key

        return default_config
    
    def _match_TOS_tile(self, ra : list or str, dec : list or str, match_tolerance_minutes = 3):
        if not self._tiles:
            self._tiles = Tiles(tile_path = None)
        if not isinstance(ra, list):
            ra = [ra]
        if not isinstance(dec, list):
            dec = [dec]
        tile, matched_indices, _ = self._tiles.find_overlapping_tiles(ra, dec, visualize = False, match_tolerance_minutes= match_tolerance_minutes)
        return tile, matched_indices

    def _check_visibility(self, ra : list, dec : list, time_grid_minutes : float = 10) -> List[bool]:
        print('Checking visibility...')
        nightsession = NightSession()
        night_start = nightsession.obsnight_utc.sunset_astro
        night_end = nightsession.obsnight_utc.sunrise_astro
        M = MultiTargets(targets_ra = np.array(ra), targets_dec = np.array(dec))
        is_observable = M.is_ever_observable(utctime_start = night_start, utctime_end = night_end, time_grid_resolution = time_grid_minutes * u.minute)
        return is_observable

    # def decode_gsheet(self, tbl : Table, match_to_tiles : bool = False, match_tolerance_minutes : float = 3):
    #     """
    #     Decodes a Google Sheet and register the alert data as an astropy.Table.
        
    #     Parameters:
    #     - tbl: astropy.Table, the Google Sheet table
        
    #     """
    #     self.rawdata = tbl
    #     self.alert_data = {col: tbl[col].tolist() for col in tbl.colnames}
    #     self.alert_type = 'googlesheet'
        
    #     # Set/Modify the columns to the standard format
    #     formatted_tbl = Table()
    #     for key, value in self.default_config.items():
    #         formatted_tbl[key] = [value] * len(tbl)
        
    #     # Update values from alert_data if the key exists
    #     for key in tbl.keys():
    #         noramlized_key = self._normalize_required_keys(key)
    #         if noramlized_key:
    #             formatted_tbl[noramlized_key] = tbl[key]
    #         else:
    #             print('The key is not found in the key variants: ', key)
        
    #     # Convert the RA, Dec to degrees
    #     formatted_tbl['RA'], formatted_tbl['De'] = self._convert_to_deg(formatted_tbl['RA'].tolist(), formatted_tbl['De'].tolist())
                
    #     # Match the RA, Dec to the RIS tiles
    #     if match_to_tiles:
    #         self.is_matched_to_tiles = True
    #         tile_info, matched_indices = self._match_TOS_tile(formatted_tbl['RA'].tolist(), formatted_tbl['De'].tolist(), match_tolerance_minutes = match_tolerance_minutes)
    #         if len(tile_info) == 0:
    #             raise ValueError(f'No matching tile found for RA = {formatted_tbl["RA"]}, Dec = {formatted_tbl["De"]}')
    #         # Sort the formatted_tbl by the matched_indices
    #         formatted_tbl = formatted_tbl[matched_indices]
            
    #         # Update only rows where is_within_boundary is True
    #         within_boundary_mask = tile_info['is_within_boundary']
    #         if np.any(within_boundary_mask):  # Ensure there are rows within boundary to update
    #             within_boundary_indices = np.where(within_boundary_mask)[0]
    #             objname = formatted_tbl['objname'][within_boundary_indices]
    #             formatted_tbl['objname'][within_boundary_indices] = tile_info['id'][within_boundary_indices]
    #             formatted_tbl['RA'][within_boundary_indices] = tile_info['ra'][within_boundary_indices]
    #             formatted_tbl['De'][within_boundary_indices] = tile_info['dec'][within_boundary_indices]
    #             formatted_tbl['note'][within_boundary_indices] = objname
    #         self.distance_to_tile_boundary = list(tile_info['distance_to_boundary'])
        
    #     # Check visibility 
    #     formatted_tbl['is_observable'] = self._check_visibility(formatted_tbl['RA'].tolist(), formatted_tbl['De'].tolist())
        
    #     existing_columns = [col for col in self.required_key_variants.keys() if col in formatted_tbl.colnames]
    #     self.update_time = Time.now().isot
    #     self.formatted_data = formatted_tbl[existing_columns]

    def decode_tbl(self, tbl : Table, match_to_tiles : bool = False, match_tolerance_minutes = 3, visibility_grid_minutes : float = 10):
        """
        Decodes a Google Sheet and register the alert data as an astropy.Table.
        
        Parameters:
        - tbl: astropy.Table, the Google Sheet table
        
        """
        self.rawdata = tbl
        self.alert_data = {col: tbl[col].tolist() for col in tbl.colnames}
        self.alert_type = 'table'
        
        # Set/Modify the columns to the standard format
        formatted_tbl = Table()
        for key, value in self.default_config.items():
            formatted_tbl[key] = [value] * len(tbl)
        
        # Update values from alert_data if the key exists
        for key in tbl.keys():
            noramlized_key = self._normalize_required_keys(key)
            if noramlized_key:
                formatted_tbl[noramlized_key] = tbl[key]
            else:
                print('The key is not found in the key variants: ', key)
                
        # Convert the RA, Dec to degrees
        formatted_tbl['RA'], formatted_tbl['De'] = self._convert_to_deg(formatted_tbl['RA'].tolist(), formatted_tbl['De'].tolist())

        # Match the RA, Dec to the RIS tiles
        if match_to_tiles:
            self.is_matched_to_tiles = True
            tile_info, matched_indices = self._match_TOS_tile(formatted_tbl['RA'].tolist(), formatted_tbl['De'].tolist(), match_tolerance_minutes = match_tolerance_minutes)
            if len(tile_info) == 0:
                raise ValueError(f'No matching tile found for RA = {formatted_tbl["RA"]}, Dec = {formatted_tbl["De"]}')
            # Sort the formatted_tbl by the matched_indices
            formatted_tbl = formatted_tbl[matched_indices]
            
            # Update only rows where is_within_boundary is True
            within_boundary_mask = tile_info['is_within_boundary']
            if np.any(within_boundary_mask):  # Ensure there are rows within boundary to update
                within_boundary_indices = np.where(within_boundary_mask)[0]
                objname = formatted_tbl['objname'][within_boundary_indices]
                formatted_tbl['objname'][within_boundary_indices] = tile_info['id'][within_boundary_indices]
                formatted_tbl['RA'][within_boundary_indices] = tile_info['ra'][within_boundary_indices]
                formatted_tbl['De'][within_boundary_indices] = tile_info['dec'][within_boundary_indices]
                formatted_tbl['note'][within_boundary_indices] = objname
            self.distance_to_tile_boundary = list(tile_info['distance_to_boundary'])
            
        # Check visibility
        formatted_tbl['is_observable'] = self._check_visibility(formatted_tbl['RA'].tolist(), formatted_tbl['De'].tolist(), time_grid_minutes = visibility_grid_minutes)
        
        existing_columns = [col for col in self.required_key_variants.keys() if col in formatted_tbl.colnames]
        self.update_time = Time.now().isot
        self.formatted_data = formatted_tbl[existing_columns]

    # def decode_gwalert(self, tbl : Table):
        # """
        # Decodes a GW alert file and register the alert data as an astropy.Table.
        
        # Parameters:
        # - tbl: astropy.Table, the GW alert table
        
        # """
        # # Read the alert data from the file
        # self.rawdata = tbl
        # self.alert_data = {col: tbl[col].tolist() for col in tbl.colnames}
        # self.alert_type = 'gw'
        
        # # Set/Modify the columns to the standard format
        # formatted_tbl = Table()
        # for key, value in self.default_config.items():
        #     formatted_tbl[key] = [value] * len(tbl)
        
        # # Update values from alert_data if the key exists         
        # # for key in tbl.keys():
        # #     noramlized_key = self._normalize_required_keys(key)
        # #     if noramlized_key:
        # #         formatted_tbl[noramlized_key] = tbl[key]
        # #     else:
        # #         print('The key is not found in the key variants: ', key)

        # # Convert the RA, Dec to degrees
        # formatted_tbl['RA'], formatted_tbl['De'] = self._convert_to_deg(tbl['ra'].tolist(), tbl['dec'].tolist())
        
        # # Modify the objname to the standard format                    
        # formatted_tbl['objname'] = ['T%.5d'%int(objname) if not str(objname).startswith('T') else objname for objname in tbl['id']]
        # formatted_tbl['priority'] = tbl['rank']
        # formatted_tbl['objtype'] = 'GECKO'
        # formatted_tbl['note'] = tbl['obj'] # Tile observation -> objname is stored in "Note"
        
        # # Check visibility 
        # formatted_tbl['is_observable'] = self._check_visibility(formatted_tbl['RA'].tolist(), formatted_tbl['De'].tolist())
        
        # existing_columns = [col for col in self.required_key_variants.keys() if col in formatted_tbl.colnames]
        # self.update_time = Time.now().isot
        # self.formatted_data = formatted_tbl[existing_columns]
    
    def decode_mail(self, mail_dict, match_to_tiles = True, match_tolerance_minutes = 3, visibility_grid_minutes : float = 10):
        """
        Decodes a mail alert and register the alert data as an astropy.Table.
        
        Parameters:
        - mail_dict: dict, the mail dictionary
        - match_to_tiles: bool, whether to match the RA, Dec to the RIS tiles
        - alert_type: str, the alert type (broker or user)
        
        """
        
        # If Attachment is not present, read the body
        alert_dict_normalized = dict()
        if len(mail_dict['Attachments']) > 0:
            try:
                alert_data = json.load(open(mail_dict['Attachments'][0]))
                for key, value in alert_data.items():
                    normalized_key = self._normalize_required_keys(key)
                    if normalized_key:
                        alert_dict_normalized[normalized_key] = value
                    else:
                        print('The key is not found in the key variants: ', key)
                file_path = mail_dict['Attachments'][0]
            except:
                print('Error reading the alert data. Try reading the mail body')
                pass
        if not alert_dict_normalized:
            try:
                alert_dict_normalized = self._parse_mail_string(mail_dict['Body']) 
                file_path = None
            except:
                raise ValueError(f'Error reading the alert data')
        self.rawdata = mail_dict
        self.alert_data = alert_dict_normalized
        self.alert_type = 'gmail'
        self.alert_sender = mail_dict['From'][1]
        # If the requester is defined, set it as the alert sender, otherwise set it as the mail sender   
        if 'requester' in alert_dict_normalized.keys():
            self.alert_sender = alert_dict_normalized['requester']
        
        # Set/Modify the columns to the standard format
        formatted_dict = dict()
        for key, value in self.default_config.items():
            formatted_dict[key] = value
            
        # Update values from alert_data if the key exists
        for key in alert_dict_normalized.keys():
            formatted_dict[key] = alert_dict_normalized[key]
        
        # Convert the RA, Dec to degrees
        formatted_dict['RA'], formatted_dict['De'] = self._convert_to_deg(formatted_dict['RA'], formatted_dict['De'])

        # Match the RA, Dec to the RIS tiles
        if match_to_tiles:
            tile_info, matched_indices = self._match_TOS_tile(formatted_dict['RA'], formatted_dict['De'], match_tolerance_minutes = match_tolerance_minutes)
            if len(tile_info) == 0:
                raise ValueError(f'No matching tile found for RA = {formatted_dict["RA"]}, Dec = {formatted_dict["De"]}')

            is_within_boundary = tile_info['is_within_boundary'][0]
            if is_within_boundary:
                objname = formatted_dict['objname']
                formatted_dict['objname'] = tile_info['id'][0]
                formatted_dict['RA'] = tile_info['ra'][0]
                formatted_dict['De'] = tile_info['dec'][0]
                formatted_dict['note'] = objname
                self.is_matched_to_tiles = True

            self.distance_to_tile_boundary = list(tile_info['distance_to_boundary'])
        
        # If the value of the dict is list, convert it to comma-separated string
        for key, value in formatted_dict.items():
            if isinstance(value, list):
                formatted_dict[key] = ','.join(value).replace(" ", "")
                
        # if space in the value, remove it
        for key, value in formatted_dict.items():
            if isinstance(value, str):
                formatted_dict[key] = value.replace(" ", "")
                
        # If is_ToO is not defined, set it to 1
        if str(formatted_dict['is_ToO']).upper() == 'TRUE':
            formatted_dict['is_ToO'] = 1
        else:
            formatted_dict['is_ToO'] = 0

        # If is_rapidToO is not defined, set it to 0
        if str(formatted_dict['is_rapidToO']).upper() == 'TRUE':
            formatted_dict['is_rapidToO'] = 1
        else:
            formatted_dict['is_rapidToO'] = 0
            
        # If specmode is defined, remove the extension
        if 'specmode' in alert_dict_normalized.keys():
            formatted_dict['specmode'] = alert_dict_normalized['specmode'].split('.')[0]

        # For Single obsmode, colormode and specmode are not applicable
        if str(formatted_dict.get('obsmode', '')).lower() == 'single':
            formatted_dict['colormode'] = 'None'
            formatted_dict['specmode'] = 'None'

        # Check visibility
        formatted_dict['is_observable'] = self._check_visibility([formatted_dict['RA']], [formatted_dict['De']], time_grid_minutes = visibility_grid_minutes)[0]

        # Convert the dict to astropy.Table
        formatted_tbl = Table()
        for key, value in formatted_dict.items():
            formatted_tbl[key] = [value]
            
        existing_columns = [col for col in self.required_key_variants.keys() if col in formatted_tbl.colnames]
        self.update_time = Time.now().isot
        self.formatted_data = formatted_tbl[existing_columns]
        
    def _convert_to_deg(self, ra, dec):
        def parse_coord(coord, is_ra=False):
            """Convert a coordinate or list of coordinates to degrees."""
            if isinstance(coord, (str, float, int)):
                # Handle single coordinate (str, float, or int)
                if is_ra:
                    return Angle(coord, unit='hourangle' if 'h' in str(coord) or ':' in str(coord) else 'deg').degree
                else:
                    return Angle(coord, unit='deg').degree
            elif isinstance(coord, list):
                # Handle list of coordinates
                return [
                    Angle(c, unit='hourangle' if is_ra and ('h' in str(c) or ':' in str(c)) else 'deg').degree
                    for c in coord
                ]
            else:
                raise ValueError(f"Unsupported coordinate format: {coord}")

        # Parse RA and Dec separately
        ra_deg = parse_coord(ra, is_ra=True)
        dec_deg = parse_coord(dec, is_ra=False)

        # Ensure RA and Dec are in consistent formats (list or single value)
        if isinstance(ra_deg, list) and isinstance(dec_deg, list):
            if len(ra_deg) != len(dec_deg):
                raise ValueError("RA and Dec lists must have the same length.")
        elif isinstance(ra_deg, list) or isinstance(dec_deg, list):
            raise ValueError("Both RA and Dec must be lists or single values.")

        return ra_deg, dec_deg
            

    # Read the alert data from the body
    def _parse_mail_string(self, mail_string):
        # Initialize the dictionary
        parsed_dict = {}

        # Process the string line by line
        for line in mail_string.splitlines():
            # Normalize the key and clean up the value
            key, value = self._check_required_keys_in_string(line)

            if not key:
                continue
            
            # Add to the dictionary
            normalized_key = self._normalize_required_keys(key)
            if not normalized_key:
                raise ValueError(f'Key {key} is not found in the key variants')
            parsed_dict[normalized_key] = value

        return parsed_dict
    
    def _check_required_keys_in_string(self, line_string: str):
        """
        Check if the line contains any required keys and return the canonical key if a match is found.
        :param line_string: str, the input line to check
        :return: str, canonical key and value if a match is found; None and None otherwise
        """
        # Iterate through the dictionary to find a match
        for canonical_key, variants in self.required_key_variants.items():
            # Create a regex pattern for each variant followed by ':' or '=' or a space
            pattern = r'(?<!\w)[ \W]*(' + '|'.join(re.escape(variant) for variant in variants) + r')\s*[:= ]\s*(.*)$'
            
            # Search for the pattern in the line string
            #match = re.search(pattern, line_string.lower())
            match = re.search(pattern, line_string, re.IGNORECASE)

            if match:
                # Extract the matched key variant and the value
                key_variant = match.group(1)  # The matched key (variant)
                value = match.group(2).strip()  # The value after ':' or '=' or space
                return key_variant, value
        
        # If no match is found, return None
        return None, None
    
    def _normalize_required_keys(self, key: str):

        # Iterate through the dictionary to find a match
        for canonical_key, variants in self.required_key_variants.items():
            if key.lower() in variants:
                return canonical_key
        return None
    
    @property
    def required_key_variants(self):
        # Define key variants, if a word is duplicated in the same variant, posit the word with the highest priority first
        required_key_variants_lower = {
            'requester': ['requester', 'requestor', 'requestinguser', 'requesting user', 'requesting user name'],
            'objname': ['target name', 'target', 'object', 'objname'],
            'RA': ['right ascension (ra)', 'right ascension (r.a.)', 'ra', 'r.a.'],
            'De': ['de', 'dec', 'dec.', 'declination', 'declination (dec)', 'declination (dec.)'],
            'exptime': ['exptime', 'exposure', 'exposuretime', 'exposure time', 'singleexposure', 'singleframeexposure', 'single frame exposure', 'single exposure time (seconds)'],
            'count': ['count', 'counts', 'imagecount', 'numbercount', 'image count', 'number count'],
            'obsmode': ['obsmode', 'observationmode', 'mode'],
            'colormode': ['colormode', 'color mode', 'color_mode'],
            'specmode': ['specmode', 'spectralmode', 'spectral mode', 'selectedspecfile'],
            'filter_': ['filter', 'filters', 'selectedfilters'],
            'ntelescope': ['ntelescopes', 'ntelescope', 'numberoftelescopes', 'number of telescopes', 'selectedtelnumber'],
            'binning': ['binning'],
            'gain': ['gain'],
            'priority': ['priority', 'rank'],
            'weight': ['weight'],
            'objtype': ['objtype', 'objecttype'],
            'note': ['note', 'notes'],
            'comments': ['comment', 'comments'],
            'is_ToO': ['is_too', 'istoo','Is_ToO','IS_TOO','IS_ToO'],
            'is_rapidToO': ['israpidtoo','is_rapidtoo','is_rapid_too','is rapid too', 'Is_Rapid_ToO','Is_rapid_ToO', 'IS_RAPID_TOO', 'IS_RAPID_ToO', 'abortobservation', 'abort current observation'],
            'obs_starttime': ['obsstarttime', 'starttime', 'start time', 'obs_starttime'],
            'id': ['id', 'uuid', 'uniqueid', 'unique id', 'unique identifier'],
            'is_observable': ['is_observable']
        }
        # Sort each list in the dictionary by string length (descending order)
        sorted_required_key_variants = {
            key: sorted(variants, key=len, reverse=True)
            for key, variants in required_key_variants_lower.items()
        }
        return sorted_required_key_variants
#%%
# %%
if __name__ == '__main__':
    alert = Alert()
    #ABC = Gsheet.read_sheet(sheet_name = '241210')
    #alert.decode_gsheet(tbl= ABC, match_to_tiles = True, match_tolerance_minutes= 10)

# %%
if __name__ == '__main__':
    tbl = ascii.read('/Users/hhchoi1022/code/GECKO/S240925n/SkyGridCatalog_7DT_90.csv')
#%%
