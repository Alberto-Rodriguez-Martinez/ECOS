# -*- coding: utf-8 -*-
"""
scan_sequencer.py — helpers shared by the scanner sequences (phase 2).
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

See scanner_tab_spec.md section 3 and task_scanner_phase2.md.
"""
from contextlib import contextmanager


@contextmanager
def preserved_reclen(sedaq, new_reclen=None):
    """
    SeDaq's RecLen is global state: SetRecLen fixes the record length for every
    later acquisition, live refresh included (tools/SeDaq.py). Optionally set
    `new_reclen` for the duration of the block and always put the previous
    value back afterwards, also when the block raises.
    """
    saved = sedaq.RecLen
    try:
        if new_reclen is not None and int(new_reclen) != saved:
            sedaq.SetRecLen(int(new_reclen))
        yield
    finally:
        if sedaq.RecLen != saved:
            sedaq.SetRecLen(saved)
