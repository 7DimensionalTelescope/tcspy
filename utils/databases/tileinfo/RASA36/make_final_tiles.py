import os
import numpy as np

center_path = os.path.join(os.path.dirname(__file__), "displaycenter.txt")
footprint_path = os.path.join(os.path.dirname(__file__), "displayfootprint.txt")
output_path = "/home/snu/code/tcspy/utils/databases/tileinfo/RASA36/final_tiles.txt"

with open(center_path) as fc, open(footprint_path) as ff:
    center_lines = fc.readlines()
    footprint_lines = ff.readlines()

# Skip headers
center_data = center_lines[1:]   # id,ra,dec
footprint_data = footprint_lines[1:]  # ra1,dec1,ra2,dec2,ra3,dec3,ra4,dec4


def footprint_centroid(ras, decs):
    """Circular mean for RA (handles 0/360 wrap), arithmetic mean for Dec."""
    mean_ra = np.degrees(np.arctan2(
        np.mean(np.sin(np.radians(ras))),
        np.mean(np.cos(np.radians(ras)))
    )) % 360
    mean_dec = np.mean(decs)
    return mean_ra, mean_dec


def ra_diff(a, b):
    """Signed angular difference a-b in [−180, 180]."""
    d = (a - b + 180) % 360 - 180
    return d

assert len(center_data) == len(footprint_data), (
    f"Row count mismatch: center={len(center_data)}, footprint={len(footprint_data)}"
)

THRESHOLD_DEG = 1  # maximum allowed offset between center and footprint centroid

mismatches = []

with open(output_path, "w") as fout:
    fout.write("id ra dec ra1 dec1 ra2 dec2 ra3 dec3 ra4 dec4\n")
    for c_line, f_line in zip(center_data, footprint_data):
        c_parts = [p.strip() for p in c_line.strip().split(",")]
        f_parts = [p.strip() for p in f_line.strip().split(",")]

        tile_id = int(c_parts[0])
        ra = float(c_parts[1])
        dec = float(c_parts[2])
        ra1, dec1, ra2, dec2, ra3, dec3, ra4, dec4 = (float(v) for v in f_parts)

        # Check: center should match the geometric centroid of the 4 corners
        corner_ras = [ra1, ra2, ra3, ra4]
        corner_decs = [dec1, dec2, dec3, dec4]
        cen_ra, cen_dec = footprint_centroid(corner_ras, corner_decs)
        delta_ra = abs(ra_diff(ra, cen_ra))
        delta_dec = abs(dec - cen_dec)
        if delta_ra > THRESHOLD_DEG or delta_dec > THRESHOLD_DEG:
            mismatches.append((f"T{tile_id:05d}", ra, dec, cen_ra, cen_dec, delta_ra, delta_dec))

        fout.write(
            f"T{tile_id:05d} {ra} {dec} "
            f"{ra1} {dec1} {ra2} {dec2} {ra3} {dec3} {ra4} {dec4}\n"
        )

if mismatches:
    print(f"WARNING: {len(mismatches)} tile(s) where center deviates > {THRESHOLD_DEG}° from footprint centroid:")
    for tid, ra, dec, cen_ra, cen_dec, dra, ddec in mismatches:
        print(f"  {tid}: center=({ra:.6f},{dec:.6f})  centroid=({cen_ra:.6f},{cen_dec:.6f})  Δra={dra:.4f}°  Δdec={ddec:.4f}°")
else:
    print("OK: all centers match their footprint centroids.")

print(f"Written {len(center_data)} tiles to {output_path}")
