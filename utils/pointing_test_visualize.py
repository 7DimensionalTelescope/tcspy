"""
pointing_test_visualize.py
--------------------------
Crop, stretch, and plot RASA36 pointing-test FITS images from 2026-05-23.

Each image is stretched independently (per-image scale) so stars are
visible regardless of background level differences between frames.
A red crosshair marks the frame centre to help verify star position.

Outputs to OUTPUT_DIR (/home/snu/code/RASA36/image/point_test/):
  track_grid.png       — all TRACK images, each auto-scaled, sorted by (RA, Dec)
  track_skymap.png     — scatter plot of observed (RA, Dec) sky positions
  track_altaz_grid.png — TRACK images arranged by Azimuth (x) and Altitude (y)
  exptest_grid.png     — EXPTEST images grouped by exposure time (rows)

Usage:
    python utils/pointing_test_visualize.py
"""

# %%
import re
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from astropy.io import fits

INPUT_DIR  = Path('/home/snu/code/RASA36/image/2026-05-28_gain25')
OUTPUT_DIR = Path('/home/snu/code/RASA36/image/point_test_260528')
CROP_SIZE  = 256   # centre-crop pixels (square) — smaller = more zoomed in


# %%  ── Image helpers ──────────────────────────────────────────────────────

def load_crop(fits_path: Path, crop: int = CROP_SIZE) -> np.ndarray:
    """Return a float32 centre-cropped array from the primary HDU."""
    with fits.open(fits_path) as hdul:
        data = hdul[0].data.astype(np.float32)
    cy, cx = data.shape[0] // 2, data.shape[1] // 2
    h = crop // 2
    return data[cy - h: cy + h, cx - h: cx + h]


def auto_stretch(arr: np.ndarray, lo: float = 1.0, hi: float = 99.0) -> np.ndarray:
    """Per-image percentile stretch to [0, 1].  Each call is independent."""
    vlo, vhi = np.percentile(arr, [lo, hi])
    return np.clip((arr - vlo) / max(vhi - vlo, 1e-9), 0.0, 1.0).astype(np.float32)


def show_image(ax, fits_path: Path, lo: float = 1.0, hi: float = 99.0):
    """Load, crop, auto-stretch, and display one FITS image on *ax*.

    Each image gets its own stretch so star brightness is comparable
    across frames even when sky background levels differ.
    Draws a red crosshair at frame centre.
    """
    img = auto_stretch(load_crop(fits_path), lo=lo, hi=hi)
    ax.imshow(img, cmap='gray', origin='lower', interpolation='nearest',
              vmin=0.0, vmax=1.0)
    mid = CROP_SIZE // 2
    ax.axhline(mid, color='red', linewidth=0.6, alpha=0.7)
    ax.axvline(mid, color='red', linewidth=0.6, alpha=0.7)
    ax.axis('off')


# %%  ── Filename parsers ───────────────────────────────────────────────────

_TRACK_RE   = re.compile(r'TRACK_RA([\d.]+)_D([+-]?\d+)')
_EXPTEST_RE = re.compile(r'EXPTEST_exp([\d.]+)s')


def parse_track(name: str):
    """Return (ra_deg, dec_deg) from a TRACK filename, or (None, None)."""
    m = _TRACK_RE.search(name)
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def parse_exptest(name: str):
    """Return exptime (float) from an EXPTEST filename, or None."""
    m = _EXPTEST_RE.search(name)
    return float(m.group(1)) if m else None


def parse_altaz(fits_path: Path):
    """Return (az_deg, alt_deg) from FITS header, or (None, None)."""
    az_keys  = ('AZIMUTH', 'AZ', 'OBJCTAZ')
    alt_keys = ('ALTITUDE', 'ALT', 'OBJCTALT')
    with fits.open(fits_path) as hdul:
        hdr = hdul[0].header
        az  = next((float(hdr[k]) for k in az_keys  if k in hdr), None)
        alt = next((float(hdr[k]) for k in alt_keys if k in hdr), None)
    return az, alt


# %%  ── Plot builders ──────────────────────────────────────────────────────

def make_track_grid(records: list, out_path: Path):
    """
    records : list of (ra_deg, dec_deg, fits_path)
    RA on x axis (columns), Dec on y axis (rows, higher Dec at top).
    Each panel is independently auto-scaled — best for spotting star drift.
    """
    from collections import Counter

    lookup = {(ra, dec): fp for ra, dec, fp in records}

    unique_decs = sorted(set(r[1] for r in records), reverse=True)
    ra_counts   = Counter(r[0] for r in records)
    center_ra   = ra_counts.most_common(1)[0][0]
    unique_ras  = sorted(set(r[0] for r in records))
    ncols       = len(unique_ras)
    ci_center   = unique_ras.index(center_ra)
    shift       = (ncols // 2) - ci_center
    unique_ras  = unique_ras[-shift % ncols:] + unique_ras[:-shift % ncols]

    nrows = len(unique_decs)

    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(ncols * 4.0, nrows * 4.2),
                             squeeze=False)
    fig.subplots_adjust(left=0.07, right=0.99, top=0.94,
                        bottom=0.03, hspace=0.10, wspace=0.03)
    fig.suptitle(
        f'RASA36 Pointing Test — TRACK ({len(records)} fields)\n'
        f'Centre {CROP_SIZE}×{CROP_SIZE} px · per-image 1–99 % stretch · red crosshair = frame centre',
        fontsize=11,
    )

    for ri, dec in enumerate(unique_decs):
        for ci, ra in enumerate(unique_ras):
            ax = axes[ri, ci]
            ax.axis('off')
            if (ra, dec) in lookup:
                show_image(ax, lookup[(ra, dec)])
        axes[ri, 0].text(-0.10, 0.5, f'Dec {dec:+.0f}°',
                         transform=axes[ri, 0].transAxes,
                         fontsize=8.5, ha='right', va='center')

    for ci, ra in enumerate(unique_ras):
        axes[0, ci].set_title(f'RA {ra:.0f}°', fontsize=8)

    fig.savefig(out_path, dpi=100)
    plt.close(fig)
    print(f'  → {out_path.name}')


def make_track_skymap(records: list, out_path: Path):
    """
    records : list of (ra, dec, fits_path)
    Full-sky Mollweide projection coloured by observation order.
    """
    ras  = np.array([r[0] for r in records])
    decs = np.array([r[1] for r in records])
    order = np.arange(len(records))

    ra_wrap = np.where(ras > 180, ras - 360, ras)
    lon = np.deg2rad(-ra_wrap)
    lat = np.deg2rad(decs)

    fig = plt.figure(figsize=(12, 6))
    ax = fig.add_subplot(111, projection='mollweide')

    sc = ax.scatter(lon, lat, c=order, cmap='plasma',
                    s=80, edgecolors='k', linewidths=0.5, zorder=3)
    cbar = fig.colorbar(sc, ax=ax, orientation='horizontal',
                        pad=0.08, shrink=0.5, aspect=30)
    cbar.set_label('Observation order (sorted RA → Dec)', fontsize=10)

    ra_tick_labels = [f'{int((-t) % 360)}°' for t in range(-150, 180, 30)]
    ax.set_xticklabels(ra_tick_labels, fontsize=8)
    ax.set_title('RASA36 Pointing Test — Sky Coverage (2026-05-24)', fontsize=13)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f'  → {out_path.name}')


def make_altaz_grid(records: list, out_path: Path, bin_deg: float = 10.0):
    """
    records  : list of (az_deg, alt_deg, fits_path)
    Az on x axis (columns, 0–360°), Alt on y axis (rows, higher Alt at top).
    Values are rounded to the nearest bin_deg to form the grid; if two images
    fall in the same bin the later one silently wins (rarest edge case).
    """
    def _bin(v: float) -> int:
        return int(round(v / bin_deg) * bin_deg)

    binned = [(_bin(az), _bin(alt), fp) for az, alt, fp in records]

    lookup     = {(az, alt): fp for az, alt, fp in binned}
    unique_azs  = sorted(set(b[0] for b in binned))
    unique_alts = sorted(set(b[1] for b in binned), reverse=True)  # high Alt at top
    ncols, nrows = len(unique_azs), len(unique_alts)

    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(ncols * 4.0, nrows * 4.2),
                             squeeze=False)
    fig.subplots_adjust(left=0.09, right=0.99, top=0.94,
                        bottom=0.03, hspace=0.10, wspace=0.03)
    fig.suptitle(
        f'RASA36 Pointing Test — TRACK by Az / Alt ({len(records)} fields)\n'
        f'Centre {CROP_SIZE}×{CROP_SIZE} px · per-image 1–99 % stretch'
        f' · bin {bin_deg:.0f}° · red crosshair = frame centre',
        fontsize=11,
    )

    for ri, alt in enumerate(unique_alts):
        for ci, az in enumerate(unique_azs):
            ax = axes[ri, ci]
            ax.axis('off')
            if (az, alt) in lookup:
                show_image(ax, lookup[(az, alt)])
        axes[ri, 0].text(-0.12, 0.5, f'Alt {alt:+.0f}°',
                         transform=axes[ri, 0].transAxes,
                         fontsize=8.5, ha='right', va='center')

    for ci, az in enumerate(unique_azs):
        axes[0, ci].set_title(f'Az {az:.0f}°', fontsize=8)

    fig.savefig(out_path, dpi=100)
    plt.close(fig)
    print(f'  → {out_path.name}')


def make_exptest_grid(records: list, out_path: Path):
    """
    records : list of (exptime, fits_path) — one row per exptime.
    Each panel independently auto-scaled for fair star-visibility comparison.
    """
    grouped: dict[float, list] = {}
    for exp, fp in records:
        grouped.setdefault(exp, []).append(fp)

    exptimes = sorted(grouped)
    ncols = max(len(v) for v in grouped.values())
    nrows = len(exptimes)

    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(ncols * 5.0, nrows * 5.2),
                             constrained_layout=True,
                             squeeze=False)
    fig.suptitle(
        f'RASA36 Pointing Test — EXPTEST\n'
        f'Centre {CROP_SIZE}×{CROP_SIZE} px · per-image 1–99 % stretch · red crosshair = frame centre',
        fontsize=12,
    )

    for row, exp in enumerate(exptimes):
        fps = grouped[exp]
        for col in range(ncols):
            ax = axes[row, col]
            ax.axis('off')
            if col < len(fps):
                show_image(ax, fps[col])
                title = f'exp={exp}s  (#1)' if col == 0 else f'#{col + 1}'
                ax.set_title(title, fontsize=8)
        axes[row, 0].text(-0.05, 0.5, f'{exp} s',
                          transform=axes[row, 0].transAxes,
                          fontsize=10, ha='right', va='center', rotation=90)

    fig.savefig(out_path, dpi=100)
    plt.close(fig)
    print(f'  → {out_path.name}')


# %%  ── Main ─────────────────────────────────────────────────────────────

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_fits     = sorted(INPUT_DIR.glob('*.fits'))
    track_fits   = [f for f in all_fits if 'TRACK_RA'   in f.name]
    exptest_fits = [f for f in all_fits if 'EXPTEST_exp' in f.name]

    print(f'Input  : {INPUT_DIR}')
    print(f'Output : {OUTPUT_DIR}')
    print(f'Found  : {len(track_fits)} TRACK + {len(exptest_fits)} EXPTEST FITS files')
    print()

    # ── 1. TRACK grid ────────────────────────────────────────────────────
    print('Building track_grid.png ...')
    track_records = []
    for fp in track_fits:
        ra, dec = parse_track(fp.name)
        if ra is not None and dec != -90:
            track_records.append((ra, dec, fp))
    track_records.sort(key=lambda x: (x[0], x[1]))
    make_track_grid(track_records, OUTPUT_DIR / 'track_grid.png')

    # ── 2. Sky-coverage map ───────────────────────────────────────────────
    print('Building track_skymap.png ...')
    make_track_skymap(track_records, OUTPUT_DIR / 'track_skymap.png')

    # ── 3. Alt/Az grid ───────────────────────────────────────────────────
    print('Building track_altaz_grid.png ...')
    altaz_records = []
    for fp in track_fits:
        az, alt = parse_altaz(fp)
        if az is not None and alt is not None:
            altaz_records.append((az, alt, fp))
        else:
            print(f'  [skip] no AZ/ALT header: {fp.name}')
    altaz_records.sort(key=lambda x: (x[0], x[1]))
    if altaz_records:
        make_altaz_grid(altaz_records, OUTPUT_DIR / 'track_altaz_grid.png')
    else:
        print('  [skip] no AZ/ALT data found in any TRACK header')

    # ── 4. EXPTEST grid ───────────────────────────────────────────────────
    print('Building exptest_grid.png ...')
    exptest_records = []
    for fp in exptest_fits:
        exp = parse_exptest(fp.name)
        if exp is not None:
            exptest_records.append((exp, fp))
    exptest_records.sort(key=lambda x: (x[0], x[1].name))
    make_exptest_grid(exptest_records, OUTPUT_DIR / 'exptest_grid.png')

    print()
    print('Done.')


if __name__ == '__main__':
    main()
