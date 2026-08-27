#%%
"""
Manually transfer selected image folders to the archive server.

Edit the FOLDERS list below with the image folders you want to transfer, then
run this script (or its #%% cells). Each entry may be:
  - a folder name under <source_homedir>/image  (e.g. '2026-06-28')
  - a glob pattern under <source_homedir>/image  (e.g. '*2026-06-28*')
  - a path relative to <source_homedir>          (e.g. 'image/2026-06-28')

This reuses DataTransferManager.run() with the same defaults as the
datatransfer.py __main__ block (tar, transfer, move_and_clean; no hashing).
"""
import os
import glob
from tcspy.utils.datatransfer import DataTransferManager

#%%
# ---------------------------------------------------------------------------
# EDIT ME: the image folders you want to transfer.
# ---------------------------------------------------------------------------
FOLDERS = [
    #'2026-06-25_gain25',
    '2026-06-26_gain25',
   # '2026-06-27_gain25',
    # '*_ToO',
]

#%%
def tar_exists(manager: DataTransferManager, key):
    """Return True if a tarball for this key already exists in the archive dir."""
    tar_path = os.path.join(manager.archive_homedir, os.path.basename(key) + '.tar')
    return os.path.isfile(tar_path)


def resolve_folders(manager: DataTransferManager, entries):
    """Expand each entry into folder keys (relative to source_homedir).

    A key is kept if its source folder still exists OR a tarball for it already
    exists in the archive dir (so already-tarred/cleaned folders still pass).
    """
    keys = []
    for entry in entries:
        # Build candidate glob patterns: try as-is (relative to source_homedir)
        # and, if it has no path separator, under the 'image' subdirectory.
        candidates = [entry]
        if os.sep not in entry:
            candidates.append(os.path.join('image', entry))

        matches = []
        for cand in candidates:
            matches += glob.glob(os.path.join(manager.source_homedir, cand))
        matches = sorted({m for m in matches if os.path.isdir(m)})

        if not matches:
            # No source folder, but accept the entry if its tarball is already
            # present in the archive dir.
            if os.sep not in entry and tar_exists(manager, entry):
                keys.append(os.path.join('image', entry))
                continue
            print(f'  [skip] no folder matched: {entry}')
            continue
        for m in matches:
            keys.append(os.path.relpath(m, manager.source_homedir))
    # Preserve order, drop duplicates
    return list(dict.fromkeys(keys))


#%%
if __name__ == '__main__':
    A = DataTransferManager()

    keys = resolve_folders(A, FOLDERS)
    if not keys:
        print('No matching image folders found to transfer.')
    else:
        print('Folders to transfer:')
        for key in keys:
            print(f'  - {key}')

    for key in keys:
        # If a tarball already exists, reuse it instead of re-creating it.
        reuse_tar = tar_exists(A, key)
        if reuse_tar:
            print(f'Transferring (reusing existing tar): {key}')
        else:
            print(f'Transferring: {key}')
        try:
            A.run(key=key, save_hash=False,
                  tar=not reuse_tar, transfer=True,
                  move_and_clean=True, from_archive=False)
            print(f'Transfer complete: {key}')
        except Exception as e:
            print(f'Transfer failed for {key}: {e}')

#%%
