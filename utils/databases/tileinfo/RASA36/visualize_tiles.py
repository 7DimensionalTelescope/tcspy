"""
Visualize RASA36 tile coverage: centers overlaid on footprint polygons.

Outputs:
  - All-sky Mollweide: footprints + centers combined in one plot
  - Zoom panel: footprint polygons with center dots and tile IDs
  - Console: angular size check per tile
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import os

DIR = os.path.dirname(os.path.abspath(__file__))
CENTER_FILE = os.path.join(DIR, "displaycenter.txt")
FOOTPRINT_FILE = os.path.join(DIR, "displayfootprint.txt")
FOV_DEG = 2.67


def load_centers():
    data = np.genfromtxt(CENTER_FILE, delimiter=",", skip_header=1)
    return data[:, 0].astype(int), data[:, 1], data[:, 2]


def load_footprints():
    data = np.genfromtxt(FOOTPRINT_FILE, delimiter=",", skip_header=1)
    return data[:, [0, 2, 4, 6]], data[:, [1, 3, 5, 7]]


def angular_size(corners_ra, corners_dec):
    widths, heights = [], []
    for ra, dec in zip(corners_ra, corners_dec):
        cos_dec = np.cos(np.radians(np.mean(dec)))
        dra = np.max(ra) - np.min(ra)
        if dra > 180:
            dra = 360 - dra
        widths.append(dra * cos_dec)
        heights.append(abs(np.max(dec) - np.min(dec)))
    return np.array(widths), np.array(heights)


def unwrap_corners(ra_corners, ra_center):
    """Shift each corner so it is within 180° of the tile centre.
    Fixes tiles that straddle the RA=0/360 boundary.
    """
    diff = (np.asarray(ra_corners) - ra_center + 180) % 360 - 180
    return ra_center + diff


def to_moll(ra_deg, dec_deg):
    """RA (any range) / Dec [-90,90]  ->  Mollweide (lon, lat) in radians.
    RA=0 at centre, RA increases to the left (standard sky convention).
    """
    ra_norm = (np.asarray(ra_deg) + 180) % 360 - 180   # -> [-180, 180]
    return -np.radians(ra_norm), np.radians(dec_deg)


RA_TICKS = ["150°", "120°", "90°", "60°", "30°", "0°",
            "330°", "300°", "270°", "240°", "210°"]


def plot_allsky(ids, ra, dec, corners_ra, corners_dec):
    """Single Mollweide panel: footprint polygons with centers overlaid."""
    fig = plt.figure(figsize=(14, 7))
    ax = fig.add_subplot(111, projection="mollweide")

    for i in range(len(corners_ra)):
        ra_uw = unwrap_corners(corners_ra[i], ra[i])
        lon_c, lat_c = to_moll(ra_uw, corners_dec[i])

        if (np.max(ra_uw) - np.min(ra_uw)) > 180:
            # Pole-cap tile: corners span all quadrants — sort by longitude so
            # the polygon closes correctly instead of drawing a bowtie.
            order = np.argsort(lon_c)
            lon_c, lat_c = lon_c[order], lat_c[order]

        lon_c = np.append(lon_c, lon_c[0])
        lat_c = np.append(lat_c, lat_c[0])
        ax.fill(lon_c, lat_c, color="steelblue", alpha=0.30, linewidth=0)
        ax.plot(lon_c, lat_c, color="steelblue", linewidth=0.2, alpha=0.7)

    # centers on top
    lon, lat = to_moll(ra, dec)
    ax.scatter(lon, lat, s=1.0, c="crimson", alpha=0.8,
               rasterized=True, zorder=3, label="tile center")

    ax.set_title(
        f"RASA36 tile coverage  |  FoV = {FOV_DEG}° x {FOV_DEG}°  |  N = {len(ra)} tiles\n"
        "Blue = footprint,  Red = center",
        fontsize=11, pad=10,
    )
    ax.grid(True, linewidth=0.4, alpha=0.5)
    ax.set_xticklabels(RA_TICKS, fontsize=8)

    plt.tight_layout()
    out = os.path.join(DIR, "tile_allsky_mollweide.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved: {out}")
    plt.close()


def plot_zoom(corners_ra, corners_dec, ids, ra_c, dec_c,
              center_ra=180.0, center_dec=-30.0, radius=8.0):
    """Flat RA/Dec zoom: footprint polygons + center dots + tile ID labels."""
    from matplotlib.patches import Polygon
    from matplotlib.ticker import FuncFormatter

    # Angular distance in RA (handles 0/360 wrap-around)
    ra_dist = np.abs((ra_c - center_ra + 180) % 360 - 180)
    mask = (ra_dist < radius) & (np.abs(dec_c - center_dec) < radius)
    idx = np.where(mask)[0]

    fig, ax = plt.subplots(figsize=(9, 9))

    for i in idx:
        # Unwrap corners relative to this tile's center, then shift to center_ra frame
        ra_uw = unwrap_corners(corners_ra[i], ra_c[i])
        # Re-express in the zoom frame (so negative RA near 0° plots correctly)
        ra_plot = center_ra + ((ra_uw - center_ra + 180) % 360 - 180)
        dec = corners_dec[i]
        if (np.max(ra_plot) - np.min(ra_plot)) > 180:
            continue
        xy = np.column_stack([ra_plot, dec])
        poly = Polygon(xy, closed=True, edgecolor="steelblue",
                       facecolor="lightblue", alpha=0.4, linewidth=0.8)
        ax.add_patch(poly)

        ra_c_plot = center_ra + ((ra_c[i] - center_ra + 180) % 360 - 180)
        ax.plot(ra_c_plot, dec_c[i], "r.", markersize=4, zorder=4)
        ax.text(ra_c_plot, dec_c[i] - 0.6, str(ids[i]),
                fontsize=4, ha="center", va="top", color="navy", alpha=0.8)

    # FoV reference box
    rect = mpatches.Rectangle(
        (center_ra - FOV_DEG / 2, center_dec - FOV_DEG / 2), FOV_DEG, FOV_DEG,
        linewidth=1.5, edgecolor="red", facecolor="none",
        label=f"FoV {FOV_DEG}° x {FOV_DEG}°", zorder=5,
    )
    ax.add_patch(rect)

    ax.set_xlim(center_ra - radius, center_ra + radius)
    ax.set_ylim(max(center_dec - radius, -90), min(center_dec + radius, 90))
    ax.invert_xaxis()
    ax.set_aspect("equal")
    # Show RA ticks as proper 0–360° values
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x % 360:.1f}°"))
    ax.set_title(
        f"Zoom  RA={center_ra}°  Dec={center_dec}°  (+-{radius}°)\n"
        "Blue = footprint,  Red dot = center,  Red box = FoV reference",
        fontsize=11,
    )
    ax.set_xlabel("RA [deg]")
    ax.set_ylabel("Dec [deg]")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, linewidth=0.4, alpha=0.5)

    plt.tight_layout()
    out = os.path.join(DIR, f"tile_zoom_ra{int(center_ra)}_dec{int(center_dec)}.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved: {out}")
    plt.close()


def size_check(corners_ra, corners_dec):
    widths, heights = angular_size(corners_ra, corners_dec)
    dec_c = np.mean(corners_dec, axis=1)
    w, h = widths[np.abs(dec_c) <= 85], heights[np.abs(dec_c) <= 85]
    print("=" * 50)
    print(f"Tile size check  (excl. |dec|>85, N={len(w)})")
    print(f"  Width  (RA cos-corrected):  {w.min():.3f} - {w.max():.3f} deg  mean {w.mean():.3f}")
    print(f"  Height (Dec):               {h.min():.3f} - {h.max():.3f} deg  mean {h.mean():.3f}")
    print(f"  Expected FoV: {FOV_DEG} x {FOV_DEG} deg")
    print("=" * 50)


if __name__ == "__main__":
    print("Loading tile data...")
    ids, ra_c, dec_c = load_centers()
    corners_ra, corners_dec = load_footprints()
    print(f"Total tiles: {len(ids)}")
    size_check(corners_ra, corners_dec)

    print("Plotting all-sky Mollweide map...")
    plot_allsky(ids, ra_c, dec_c, corners_ra, corners_dec)

    print("Plotting zoom panels...")
    plot_zoom(corners_ra, corners_dec, ids, ra_c, dec_c,
              center_ra=357.2519083969466, center_dec=20.571428571428573, radius=8.0)
    plot_zoom(corners_ra, corners_dec, ids, ra_c, dec_c,
              center_ra=0, center_dec=18.0, radius=8.0)
    plot_zoom(corners_ra, corners_dec, ids, ra_c, dec_c,
              center_ra=0.0, center_dec=-87.42857142857143, radius=8.0)

    print("Done.")
