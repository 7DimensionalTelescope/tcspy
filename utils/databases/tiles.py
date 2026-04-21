

#%%
import os
import numpy as np
import matplotlib.pyplot as plt
from shapely.geometry import Point, Polygon
from astropy.coordinates import SkyCoord
import astropy.units as u
from astropy.io import ascii
from astropy.table import Table
from datetime import datetime
from astropy.table import vstack

class Tiles:
    def __init__(self, tile_path: str = None):
        if tile_path is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            self.tile_path = os.path.join(current_dir, './tileinfo/7-DT/final_tiles.txt')
        else:
            self.tile_path = tile_path
        self.tbl_RIS = None
        self.coords_RIS = None

    def find_overlapping_tiles(self, 
                               list_ra, 
                               list_dec, 
                               list_aperture= 0,
                               visualize: bool = True, 
                               visualize_ncols: int = 5, 
                               visualize_savepath: str = './tiles',
                               match_tolerance_minutes = 4,
                               fraction_overlap_lower = 0.2):
        """
        list_ra = [10, 15]
        list_dec = [-20, -20] 
        list_aperture= 3
        visualize: bool = True 
        visualize_ncols: int = 5
        visualize_savepath: str = './tiles'
        match_tolerance_minutes=4
        fraction_overlap_lower = 0.2
        Find the tiles that overlap with the given coordinates and aperture sizes.

        Parameters:
        - list_ra: list of RA coordinates
        - list_dec: list of Dec coordinates
        - list_aperture: list of aperture sizes in degrees or single value (default is 0 for point matching)
        - visualize (bool): Whether to visualize the overlapping tiles
        - visualize_ncols (int): Number of columns in the visualization grid

        Returns:
        - A table containing the overlapping or innermost tiles for each coordinate.
        """
        # Ensure list_aperture matches list_ra and list_dec
        if isinstance(list_aperture, (int, float)):
            list_aperture = [list_aperture] * len(list_ra)
        elif len(list_aperture) != len(list_ra):
            raise ValueError("list_aperture must have the same length as list_ra and list_dec.")

        # Load the tile data
        if not self.tbl_RIS:
            self.tbl_RIS = ascii.read(self.tile_path)
        if not self.coords_RIS:
            self.coords_RIS = SkyCoord(ra=self.tbl_RIS['ra'], dec=self.tbl_RIS['dec'], unit=(u.deg, u.deg))

        list_matched_tiles = []        
        list_matched_coords = []
        list_distance_to_boundary = []
        list_overlapped_areas = []

        for i, (ra, dec, aperture) in enumerate(zip(list_ra, list_dec, list_aperture)):
            target_point = Point(ra, dec)
            coord_targets = SkyCoord(ra=ra, dec=dec, unit=(u.deg, u.deg))

            # Find nearby tiles
            nearby_tiles_idx = coord_targets.separation(self.coords_RIS) < (aperture + 2) * u.deg
            RIS_polygons_nearby = self._create_polygons(self.tbl_RIS[nearby_tiles_idx])

            if aperture == 0:  # Point-based matching
                closest_tile_id, distance_to_boundary = self._find_innermost_tile(polygons_by_id = RIS_polygons_nearby, target_point = target_point)
                if closest_tile_id is not None:
                    list_matched_tiles.append([closest_tile_id])
                    list_matched_coords.append(i)
                    list_distance_to_boundary.append([distance_to_boundary])
                    list_overlapped_areas.append([1])
            else:  # Aperture-based matching
                target_circle = target_point.buffer(aperture)
                overlapped_tiles, overlapped_areas = self._find_overlapped_tiles(polygons_by_id = RIS_polygons_nearby, target_circle = target_circle, fraction_overlap_lower = fraction_overlap_lower)
                if overlapped_tiles:
                    list_matched_tiles.extend([overlapped_tiles])
                    list_matched_coords.append(i)
                    list_distance_to_boundary.append([0.5]*len(overlapped_areas))
                    list_overlapped_areas.append(overlapped_areas)

        if not list_matched_tiles:
            return Table(), list_matched_coords, None

        fig_path = None
        if visualize:
            fig_path = self.visualize_tiles(list_ra, list_dec, list_aperture, list_matched_coords, list_matched_tiles, visualize_ncols, visualize_savepath)

        matched_tbl = Table()
        for matched_coord, matched_tiles, distance_to_boundaries, overlapped_areas in zip(list_matched_coords, list_matched_tiles, list_distance_to_boundary, list_overlapped_areas):
            matched_tbl_single = self.tbl_RIS[np.isin(self.tbl_RIS['id'], matched_tiles)]
            matched_tbl_single['matched_idx'] = matched_coord
            matched_tbl_single['distance_to_boundary'] = distance_to_boundaries
            matched_tbl_single['overlapped_area'] = overlapped_areas
            matched_tbl_single['is_within_boundary'] = np.array(distance_to_boundaries) > match_tolerance_minutes/60
            matched_tbl = vstack([matched_tbl, matched_tbl_single])
        
        _, unique_indices = np.unique(matched_tbl['id'], return_index=True)
        unique_table = matched_tbl[sorted(unique_indices)]
        
        return unique_table, list_matched_coords, fig_path

    def _find_innermost_tile(self, polygons_by_id, target_point):
        """
        Determine the innermost tile for a given target point.
        """
        max_distance = -float('inf')
        closest_tile_id = None

        for tile_id, polygons in polygons_by_id.items():
            for poly in polygons:
                if poly.contains(target_point) or poly.boundary.contains(target_point):
                    distance_to_boundary = target_point.distance(poly.boundary)
                    if distance_to_boundary > max_distance:
                        max_distance = distance_to_boundary
                        closest_tile_id = tile_id
        return closest_tile_id, max_distance

    def _find_overlapped_tiles(self, polygons_by_id, target_circle, fraction_overlap_lower = 0.2):
        """
        Find all tiles overlapping with the given target circle.
        """
        overlapped_tiles = []
        overlapped_area = []

        for tile_id, polygons in polygons_by_id.items():
            for poly in polygons:
                if target_circle.intersects(poly):
                    intersection = target_circle.intersection(poly)
                    fraction_overlap = intersection.area / poly.area
                    if fraction_overlap > fraction_overlap_lower:
                        overlapped_tiles.append(tile_id)
                        overlapped_area.append(fraction_overlap)
                    break  # Avoid duplicate entries for the same tile_id
        return overlapped_tiles, overlapped_area

    def visualize_tiles(self, list_ra, list_dec, list_aperture, list_matched_coords, list_matched_tiles, visualize_ncols, visualize_savepath):
        """
        Visualize the tiles and matched coordinates with aperture regions.
        """
        list_ra = [list_ra[i] for i in list_matched_coords]
        list_dec = [list_dec[i] for i in list_matched_coords]
        list_aperture = [list_aperture[i] for i in list_matched_coords]
        list_matched_tiles = [list_matched_tiles[i] for i in list_matched_coords]

        n_coords = len(list_ra)
        cols = visualize_ncols
        rows = (n_coords + cols - 1) // cols

        fig, axes = plt.subplots(rows, cols, figsize=(15, rows * 3), subplot_kw={'aspect': 'equal'})
        if rows == 1 and cols == 1:
            axes = [axes]
        elif isinstance(axes, np.ndarray):
            axes = axes.flatten()

        for i, (ra, dec, matched_tile_id, aperture) in enumerate(zip(list_ra, list_dec, list_matched_tiles, list_aperture)):
            ax = axes[i]
            coord_targets = SkyCoord(ra=ra, dec=dec, unit=(u.deg, u.deg))
            nearby_tiles_idx = coord_targets.separation(self.coords_RIS) < (aperture + 3) * u.deg
            nearby_polygons_by_id = self._create_polygons(self.tbl_RIS[nearby_tiles_idx])

            # Plot surrounding polygons in blue
            for tile_id, polygons in nearby_polygons_by_id.items():
                for poly in polygons:
                    x, y = poly.exterior.xy
                    ax.plot(x, y, color='blue', lw=1)
                    ax.fill(x, y, color='blue', alpha=0.3)

            for tile_id in matched_tile_id:
                for poly in nearby_polygons_by_id[tile_id]:
                    x, y = poly.exterior.xy
                    ax.plot(x, y, color='red', lw=2)

            # Draw the aperture if applicable
            if aperture > 0:
                aperture_circle = plt.Circle((ra, dec), aperture, color='red', fill=True, linestyle='--', label='Aperture', lw =3, alpha = 0.2)
                ax.add_patch(aperture_circle)
                ax.text(ra, dec, rf'N_tiles ={len(matched_tile_id)}', fontsize=8, ha='center', va='center', color='black',
                        bbox=dict(facecolor='white', alpha=0.6, edgecolor='none'))
                ax.set_xlim(ra - 1.2* aperture , ra + 1.2* aperture)
                ax.set_ylim(dec - 1.2* aperture , dec + 1.2* aperture)
            else:
                ax.scatter(ra, dec, color='green', marker='o', s=50, label='Target Point' if i == 0 else None)
                ax.set_xlim(ra - 2, ra + 2)
                ax.set_ylim(dec - 2, dec + 2)
                innermost_poly = nearby_polygons_by_id[matched_tile_id[0]][0]
                x, y = innermost_poly.exterior.xy
                ax.plot(x, y, color='red', lw=2)
                centroid = innermost_poly.centroid
                ax.text(ra, dec - 0.3, matched_tile_id[0], fontsize=8, ha='center', va='center', color='black',
                        bbox=dict(facecolor='white', alpha=0.6, edgecolor='none'))
            ax.set_title(f'Target {i + 1}: ({ra:.2f}, {dec:.2f})')

        # Add a legend to the first subplot
        axes[0].legend(loc='upper left', fontsize=8)

        # Remove unused subplots
        for j in range(len(list_ra), len(axes)):
            fig.delaxes(axes[j])

        plt.tight_layout()
        if visualize_savepath:
            os.makedirs(visualize_savepath, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            fig_path = f"{os.path.join(visualize_savepath, f'matched_tiles_{timestamp}')}.png"
            plt.savefig(fig_path)
        plt.show()
        return fig_path
    

    def _split_wrapping_polygon(self, polygon):
        """
        Splits a polygon into two parts if it crosses the RA = 0 (360) boundary.
        Ensures correct wrapping at the boundary and forms two valid polygons.

        Parameters:
        - polygon: Shapely Polygon object.

        Returns:
        - A list of Shapely Polygons split at the RA = 0 (360) boundary.
        """
        exterior_coords = list(polygon.exterior.coords)[:4]
        list_ra = [coord[0] for coord in exterior_coords]
        list_dec = [coord[1] for coord in exterior_coords]
        is_crossing = (np.max(list_ra) - np.min(list_ra)) > 180
        if not is_crossing:
            return [polygon]
        else:
            # Contruct polygons for the two parts
            left_part = []  # Coordinates for the part near RA = 0
            right_part = []  # Coordinates for the part near RA = 360
            left_part_idx = [0,1]
            right_part_idx = [2,3]
            for idx_left in left_part_idx:
                left_part.append(exterior_coords[idx_left])
            left_part.append([0, left_part[1][1]])
            left_part.append([0, left_part[0][1]])
            left_part.append(left_part[0])
            for idx_right in right_part_idx:
                right_part.append(exterior_coords[idx_right])
            right_part.append([360, right_part[1][1]])
            right_part.append([360, right_part[0][1]])
            right_part.append(right_part[0])
            # Create polygons
            polygons = []
            if len(left_part) > 2:
                polygons.append(Polygon(left_part))
            if len(right_part) > 2:
                polygons.append(Polygon(right_part))

            return polygons
        
    def _create_polygons(self, table):
        """
        Create polygons for the tiles, splitting them if necessary.
        """
        polygons_by_id = {}
        for row in table:
            try:
                corners = [
                    (float(row['ra1']), float(row['dec1'])),
                    (float(row['ra2']), float(row['dec2'])),
                    (float(row['ra3']), float(row['dec3'])),
                    (float(row['ra4']), float(row['dec4'])),
                ]
                polygons_by_id[row['id']] = self._split_wrapping_polygon(Polygon(corners))
            except Exception as e:
                print(f"Failed to create polygon for row {row}: {e}")
        return polygons_by_id



# %%
# Example usage
if __name__ == "__main__":
    from tcspy.utils.databases.DB_dynamic import DB_Dynamic
    #tbl = ascii.read('./Subset_White_Dwarfs_with_Matched_Tiles.csv')
    T = Tiles()
    #data = ascii.read('./7DT_observed_Tile')
    #list_ra = data['ra']
    #list_dec = data['dec']
    list_ra = [260.03428]#tbl['ra']#[350.1]
    list_dec = [-60.15669]#bl['dec']
    
    #tbl_filtered, tbl_idx, fig_path =T.find_overlapping_tiles(list_ra, list_dec, 0.5, visualize = False, visualize_ncols=5, match_tolerance_minutes= 11)  
    tbl_filtered, tbl_idx, fig_path = T.find_overlapping_tiles(list_ra, list_dec, list_aperture = 0, visualize=True, visualize_ncols=5, visualize_savepath='./output', match_tolerance_minutes=4, fraction_overlap_lower= 0.1 )
    #print(tbl_filtered['distance_to_boundary'])
# %%
