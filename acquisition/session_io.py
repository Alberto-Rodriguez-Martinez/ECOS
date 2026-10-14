# -*- coding: utf-8 -*-
"""
session_io.py — Reading the GUI session files (ecos_gui, density_gui) without
losing a damaged one. No Qt.
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

A session that cannot be read used to be skipped silently (except: pass), and the
GUI then overwrote it on closing. Now the damaged file is copied aside first
(<file>.bak, or <file>.<timestamp>.bak if that exists already) and the caller gets
a notice to show: the defaults are used.
"""
import json
import os
import shutil
import time


def backup_path(path):
    """<path>.bak, or <path>.<YYYYmmdd_HHMMSS>.bak when <path>.bak exists already."""
    bak = path + '.bak'
    if os.path.exists(bak):
        bak = f'{path}.{time.strftime("%Y%m%d_%H%M%S")}.bak'
    return bak


def keep_damaged(path, error):
    """Copy the damaged session aside; the notice to show (console and status bar)."""
    bak = backup_path(path)
    try:
        shutil.copy2(path, bak)
        kept = f'kept as {bak}'
    except Exception as e:
        kept = f'could not be copied aside ({type(e).__name__}: {e})'
    return (f'Session file {path} could not be read ({type(error).__name__}: {error}): '
            f'default values are used. The damaged file is {kept}.')


def load_session(path):
    """
    (data, notice). data: the session dict, None when there is no file or it cannot
    be read; notice: None, or what happened (keep_damaged) when it could not be read.
    """
    if not os.path.exists(path):
        return None, None
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError('not a JSON object')
        return data, None
    except Exception as e:
        return None, keep_damaged(path, e)
