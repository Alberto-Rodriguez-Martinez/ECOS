# -*- coding: utf-8 -*-
"""
Created on Mon Oct  6 11:47:59 2025

@author: Alberto
"""
# acq32.py  (Python 32-bit)
# Requisitos: numpy (evita pandas/pyarrow). Guarda JSON + NPZ.

import json, uuid, csv
from pathlib import Path
from datetime import datetime
import numpy as np
import matplotlib.pyplot as plt

from scan_counts import (ADC_BITS_DEFAULT, counts_to_float, counts_to_float_rows,
                         quantizer, sum_dtype)

DEFAULT_OPERATOR = "Sebas"      # save_experiment_raw_32 still writes it fixed


def experiment_name(pva_pct, additive_pct, sample_id, cycles, exp_type="US", ts=None,
                    material="PVA", additive_tag="PG"):
    """
    Folder name of an experiment, ECOS convention (analysis/ecos_loader.py):
        {material}_{XX}_{additive_tag}_{YY}_{LETTER}_C{NNN}_{exp_type}_{YYYYMMDD_HHMMSS}
    e.g. PVA_10_PG_05_A_C005_SCAN_20261002_091500. Same placeholders as the
    original builder in ecos_gui.py when a field is missing or not a number
    (XX, YY, X, NNN). exp_type: "US", "DENS", "SCAN"...
    """
    pva = str(pva_pct).strip()
    add = str(additive_pct).strip()
    sid = str(sample_id).strip()
    cyc = str(cycles).strip()
    letra = sid[-1].upper() if sid else "X"
    pva = pva.zfill(2) if pva.isdigit() else "XX"
    add = add.zfill(2) if add.isdigit() else "YY"
    cyc = cyc.zfill(3) if cyc.isdigit() else "NNN"
    ts = ts or datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{material}_{pva}_{additive_tag}_{add}_{letra}_C{cyc}_{exp_type}_{ts}"


def _now_iso():
    try:
        return datetime.now().isoformat()
    except Exception:
        # Fallback sin tz
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

def save_experiment_raw_32(
    *,
    specimen,        # dict (estructura exacta de tu espécimen)
    equipment1,      # dict con 'params' incluyendo F_muestreo, Smin, Smax, Slen, WindowLen
    equipment2,      # dict
    protocol,        # dict
    results,         # dict dinámico (T1, T2, C1, C2, Cw, Cl, L, ...)
    Signal_PE,       # np.ndarray (longitud Slen)
    Signal_TT,       # np.ndarray (longitud Slen)
    Signal_Ref,      # np.ndarray (longitud Slen)
    base_dir="data_32",
    exp_name=None    # si se proporciona, el directorio del experimento será base_dir/exp_name
):
    # Validaciones mínimas
    params = equipment1.get("params", {})
    Smin = int(params["Smin"]); Smax = int(params["Smax"]); Slen = int(params["Slen"])
    if Slen != (Smax - Smin):
        raise ValueError("Slen debe ser Smax - Smin")
    for name, arr in [("Signal_PE", Signal_PE), ("Signal_TT", Signal_TT), ("Signal_Ref", Signal_Ref)]:
        if int(np.asarray(arr).size) != Slen:
            raise ValueError("%s tamaño %d != Slen %d" % (name, np.asarray(arr).size, Slen))

    exp_id = "EXPID-" + uuid.uuid4().hex[:8].upper()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = Path(base_dir) / exp_name if exp_name else Path(base_dir) / f"{ts}_{exp_id}"
    (d / "signals").mkdir(parents=True, exist_ok=True)

    meta = {
        "schema_version": "raw-32-1.0",
        "experiment": {"id": exp_id, "timestamp_start": _now_iso(), "timestamp_end": _now_iso(), "operator": "Sebas"},
        "specimen": specimen,
        "protocol": protocol,
        "equipment": {
            "device_1_ultrasound": equipment1,
            "device_2_aux": equipment2
        },
        "notes": ""
    }
    # Guardar metadatos/resultado
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # Guardar señales en un NPZ comprimido (portátil)
    np.savez_compressed(d / "signals" / "signals.npz",
                        Signal_PE=np.asarray(Signal_PE, dtype=np.float64),
                        Signal_TT=np.asarray(Signal_TT, dtype=np.float64),
                        Signal_Ref=np.asarray(Signal_Ref, dtype=np.float64))
    return str(d)

SCAN_SCHEMA_VERSION = "scan-32-3.3"
# 3.3 (2026-10-09): continuous PT100 series (temp_series_wall/mono/T1/T2, every line the
#     Arduino sent, and temp_series_discarded); the event readings (temp_*) gain temp_age_s
#     and temp_stale (their value is the newest sample of the series). Same arrays as 3.2
#     otherwise; a 3.2 file is read as before (no series).
# 3.2 (2026-10-06): saturation per channel, kept apart: arrays saturated_ch1/ch2 and
#     n_top_ch1/ch2, witness_n_top_ch1/ch2, ref_<which>_n_top_ch1/ch2; flag names
#     saturated_ch1 / saturated_ch2 (3.1 had one Ch2 flag, 'saturated').
# 3.1 (2026-10-06): the 'saturated' flag changes meaning: raw samples at the quantizer
#     top in any capture, Smin-Smax (scan.saturation_criterion). Before: |x| >= 0.49 on
#     the averaged float near the echo. Same arrays as 3.0; flags NOT comparable.
# 3.0 (2026-10, phase 6): surface scans. The cube is in spatial order with a partial
#     line padded (point_valid; signals 0, offsets/coords/times NaN there), the witness
#     point series (witness_*), the line index of every temperature (temp_line) and
#     per-point thickness values. A 2.0 file is still read (a line, all points valid).
# 2.0 (2026-10): signals stored as integer sums of counts + conversion metadata.
# 1.0 (float32 signals) is not readable any more: no real scan was ever saved with it.
SCAN_SCHEMA_READABLE = ("scan-32-2.0", "scan-32-3.0", "scan-32-3.1", "scan-32-3.2",
                        SCAN_SCHEMA_VERSION)
_SCAN_REF_OPTIONAL = ("n_top_ch1", "n_top_ch2")   # saturation of each channel (3.2)
_SCAN_REF_FIELDS = ("sum1", "sum2", "offset1", "offset2", "avg_n", "gains", "coords",
                    "time", "T1", "T2")


def _check_sums(name, arr, n_avg, bits):
    a = np.asarray(arr)
    if not np.issubdtype(a.dtype, np.integer):
        raise ValueError("%s must be integer sums of counts, got %s" % (name, a.dtype))
    _, mid = quantizer(bits)
    if a.size and int(np.max(np.abs(a.astype(np.int64)))) > mid * int(n_avg):
        raise ValueError("%s exceeds midpoint·n_avg = %d: not a sum of %d captures of %d bits"
                         % (name, mid * int(n_avg), int(n_avg), int(bits)))
    return a.astype(sum_dtype(n_avg, bits))


def save_scan_raw_32(
    *,
    specimen,           # dict, same structure as save_experiment_raw_32
    protocol,           # dict
    equipment1,         # dict: SeDaq/pulser, 'params' with F_muestreo, Smin, Smax, gains...
    equipment2,         # dict: Arduino / PT100
    scanner_session,    # dict from ScannerPanel.session_dict() (JSON-serialisable)
    scan,               # dict: scan parameters (type, axis, range, step, settle, averages...)
    signals_ch1,        # int (N_line, N_point, N_samples): Σ(raw − midpoint) over n_avg captures
    signals_ch2,        # int (N_line, N_point, N_samples)
    offsets_ch1,        # float (N_line, N_point): whole-record mean removed (scan_counts)
    offsets_ch2,        # float (N_line, N_point)
    n_avg,              # captures summed per point
    gains,              # (gain_ch1, gain_ch2) [dB] of the scan
    coords,             # (N_line, N_point, 4): real X, Y, Z, R read back from the scanner
    point_time,         # (N_line, N_point): epoch seconds of each acquisition
    temperatures,       # list of {label, point, time, T1, T2} (NaN when no PT100), optional
                        # age_s (age of the sample used) and stale
    references=None,    # {'initial': {...}, 'final': {...}}, each with _SCAN_REF_FIELDS
    witness=None,       # witness point series {name: array (N_visit, ...)}: sum1, sum2
                        # (N_visit, N_samples) as the signals, offset1/2, coords, time,
                        # line, ... ; stored as witness_<name>
    adc_bits=ADC_BITS_DEFAULT,
    operator=DEFAULT_OPERATOR,
    comment="",
    base_dir="data_32",
    exp_name=None,
    extra_arrays=None,  # optional {name: array} also stored in scan.npz
    files_extra=None,   # optional {name: description} of extra_arrays, into meta "files"
    temp_series=None,   # continuous PT100 series {wall, mono, T1, T2, discarded}; None or
                        # empty: stored empty (no Arduino)
):
    """
    Raw data of a scan (line or surface), one folder per scan:
        <exp_name>/meta.json   schema scan-32-3.3: experiment (id, timestamps,
                               operator), specimen, protocol, equipment, scanner_session,
                               scan, conversion, comment, and the description of scan.npz
        <exp_name>/scan.npz    (compressed) integer signals per channel
                               (N_line × N_point × N_samples) and their offsets, real
                               coordinates, times, temperatures (event readings and the
                               continuous PT100 series) and water references
    Samples stored: ONLY the analysis window, Smin..Smax-1, for the signals, the
    witness and the references: what is measured is saved. The per-point offsets are
    the one value taken from the whole record (the mean ECOS removes from each
    capture), stored because it cannot be recomputed from the window. The debug dumps
    of the scanner tools, by contrast, keep full records (scanner_tab_spec.md 5.6).
    The signals are the integer sums of counts of the averaged captures, int16 when
    they fit and int32 otherwise (scan_counts.py): exact, about half the size of
    float32, and nothing converted when writing. The conversion parameters (bits,
    midpoint, full scale, averages, dtype, gain per channel) go into meta.json and
    load_scan_raw_32 rebuilds the exact floats. No results.json.
    """
    s1, s2 = np.asarray(signals_ch1), np.asarray(signals_ch2)
    if s1.ndim != 3 or s2.shape != s1.shape:
        raise ValueError("signals must be two arrays (N_line, N_point, N_samples) of equal shape, "
                         "got %s and %s" % (s1.shape, s2.shape))
    s1 = _check_sums("signals_ch1", s1, n_avg, adc_bits)
    s2 = _check_sums("signals_ch2", s2, n_avg, adc_bits)
    n_line, n_point, n_samp = s1.shape
    o1 = np.asarray(offsets_ch1, dtype=np.float64)
    o2 = np.asarray(offsets_ch2, dtype=np.float64)
    xyz = np.asarray(coords, dtype=np.float64)
    tpt = np.asarray(point_time, dtype=np.float64)
    for name, arr, shape in (("offsets_ch1", o1, (n_line, n_point)),
                             ("offsets_ch2", o2, (n_line, n_point)),
                             ("coords", xyz, (n_line, n_point, 4)),
                             ("point_time", tpt, (n_line, n_point))):
        if arr.shape != shape:
            raise ValueError("%s must be %s, got %s" % (name, shape, arr.shape))
    params = equipment1.get("params", {})
    smin, smax = int(params["Smin"]), int(params["Smax"])
    if n_samp != smax - smin:
        raise ValueError("N_samples %d != Smax - Smin %d" % (n_samp, smax - smin))

    exp_id = "EXPID-" + uuid.uuid4().hex[:8].upper()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = Path(base_dir) / exp_name if exp_name else Path(base_dir) / f"{ts}_{exp_id}"
    if d.exists() and any(d.iterdir()):
        raise FileExistsError(f"{d} already exists and is not empty")
    d.mkdir(parents=True, exist_ok=True)

    full, mid = quantizer(adc_bits)

    def conversion(n, g, dtype):
        return {"quantizer_bits": int(adc_bits), "quantizer_midpoint": mid,
                "full_scale_counts": full, "n_avg": int(n), "dtype": np.dtype(dtype).name,
                "gain_db": {"ch1": float(g[0]), "ch2": float(g[1])}}

    arrays = {
        "signals_ch1": s1, "signals_ch2": s2, "offsets_ch1": o1, "offsets_ch2": o2,
        "coords": xyz,
        "coord_axes": np.array(["X", "Y", "Z", "R"]),
        "point_time": tpt,
        "temp_label": np.array([str(t["label"]) for t in temperatures]),
        "temp_point": np.array([int(t["point"]) for t in temperatures], dtype=np.int64),
        "temp_line": np.array([int(t.get("line", -1)) for t in temperatures], dtype=np.int64),
        "temp_time": np.array([float(t["time"]) for t in temperatures], dtype=np.float64),
        "temp_T1": np.array([float(t["T1"]) for t in temperatures], dtype=np.float64),
        "temp_T2": np.array([float(t["T2"]) for t in temperatures], dtype=np.float64),
        "temp_age_s": np.array([float(t.get("age_s", float("nan"))) for t in temperatures],
                               dtype=np.float64),
        "temp_stale": np.array([bool(t.get("stale", False)) for t in temperatures], dtype=bool),
    }
    ts_in = temp_series or {}
    for key in ("wall", "mono", "T1", "T2"):
        arrays[f"temp_series_{key}"] = np.asarray(ts_in.get(key, ()), dtype=np.float64).ravel()
    if len({arrays[f"temp_series_{k}"].size for k in ("wall", "mono", "T1", "T2")}) != 1:
        raise ValueError("temp_series: wall, mono, T1 and T2 must have the same length")
    arrays["temp_series_discarded"] = np.array(int(ts_in.get("discarded", 0)), dtype=np.int64)
    taken, ref_conv = [], {}
    for which, ref in (references or {}).items():
        if ref is None:
            continue
        taken.append(which)
        n_ref = int(ref["avg_n"])
        for key in _SCAN_REF_FIELDS + tuple(k for k in _SCAN_REF_OPTIONAL if k in ref):
            val = np.asarray(ref[key])
            if key in ("sum1", "sum2"):
                val = _check_sums(f"reference {which} {key}", val, n_ref, adc_bits)
            arrays[f"ref_{which}_{key}"] = val
        ref_conv[which] = conversion(n_ref, ref["gains"], sum_dtype(n_ref, adc_bits))
    for name, val in (witness or {}).items():
        val = np.asarray(val)
        if name in ("sum1", "sum2"):
            if val.ndim != 2 or val.shape[1] != n_samp:
                raise ValueError("witness %s must be (N_visit, %d), got %s"
                                 % (name, n_samp, val.shape))
            val = _check_sums(f"witness {name}", val, n_avg, adc_bits)
        arrays[f"witness_{name}"] = val
    for name, val in (extra_arrays or {}).items():
        arrays[name] = np.asarray(val)

    files = {
        "signals_ch1/2": "%s (N_line, N_point, N_samples): sum over n_avg captures of "
                         "(raw − midpoint), samples Smin..Smax-1" % s1.dtype.name,
        "offsets_ch1/2": "float64 (N_line, N_point): mean over the whole record of "
                         "sum/(full_scale·n_avg), removed as ECOS does",
        "float": "x = signals / (full_scale_counts · n_avg) − offsets: the ECOS float "
                 "(full scale ±0.5), rebuilt exactly by load_scan_raw_32; not gain-corrected",
        "coords": "float64 (N_line, N_point, 4): X, Y, Z [mm], R [deg] read back from the "
                  "scanner after each move (not the requested target)",
        "point_time": "float64 (N_line, N_point): epoch [s] of each acquisition",
        "temp_*": "one entry per reading: label, point (index of the last acquired point, "
                  "-1 before the first), line (index of its line, -1 before the first), time "
                  "(epoch), T1, T2 [°C] (NaN without PT100), age_s (age of the newest sample "
                  "of the series used, s; NaN: no sample) and stale (no sample newer than "
                  "scan.temperature_log.stale_after_s: T1, T2 NaN). PT100 at the bottom of the "
                  "tank, not in the beam path: see scan.temperature_note",
        "temp_series_*": "every line the Arduino sent during the session, in arrival order: "
                         "wall (time.time() epoch, s), mono (time.monotonic(), s, never "
                         "decreasing), T1, T2 [°C] (float64, empty without Arduino); "
                         "temp_series_discarded: malformed lines dropped (int). Summary in "
                         "scan.temperature_log",
        "ref_<initial|final>_*": "water references: sum1, sum2 (N_samples, integer sums), "
                                 "offset1, offset2, avg_n, gains (Ch1, Ch2), coords "
                                 "(X, Y, Z, R), time, T1, T2; conversion in "
                                 "conversion.references",
    }
    files.update(files_extra or {})
    if witness:
        files["witness_*"] = ("witness point, one entry per visit (phase 6): sum1, sum2 "
                              "(N_visit, N_samples, same conversion as the signals; floats "
                              "witness_ch1/2 on load), offset1/2, coords (real X, Y, Z, R), "
                              "time (epoch), line (lines completed before the visit), tof_us, "
                              "amplitude, face_um (displacement since the first visit by "
                              "cross-correlation, + away from the PE transducer), thickness_mm, thickness_corr, lost. RAW: "
                              "no drift correction is applied anywhere in this file")
    meta = {
        "schema_version": SCAN_SCHEMA_VERSION,
        "experiment": {"id": exp_id, "type": "SCAN",
                       "timestamp_start": scan.get("timestamp_start", _now_iso()),
                       "timestamp_end": _now_iso(), "operator": operator},
        "specimen": specimen,
        "protocol": protocol,
        "equipment": {"device_1_ultrasound": equipment1, "device_2_aux": equipment2},
        "scanner_session": scanner_session,
        "scan": dict(scan, shape=[n_line, n_point, n_samp], references_taken=taken),
        "conversion": dict(conversion(n_avg, gains, s1.dtype),
                           formula="x = signals / (full_scale_counts * n_avg) - offsets",
                           adc_bits_note="10 bits assumed: the SeDaq resolution cannot be "
                                         "read from the equipment",
                           references=ref_conv),
        "comment": comment,
        "notes": "",
        "files": files,
    }
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str),
                                 encoding="utf-8")
    np.savez_compressed(d / "scan.npz", **arrays)
    return str(d)


def load_scan_raw_32(exp_dir):
    """
    meta (dict) and the arrays of scan.npz (dict of np.ndarray) of a scan folder,
    with the signals as the exact ECOS floats (float64):
        signals_ch1/2, ref_<which>_ch1/2   floats rebuilt with the file's conversion
        signals_ch1/2_sum, ref_<which>_sum1/2   the stored integer sums, as saved
    """
    exp_dir = Path(exp_dir)
    meta = json.loads((exp_dir / "meta.json").read_text(encoding="utf-8"))
    version = meta.get("schema_version")
    if version not in SCAN_SCHEMA_READABLE:
        raise ValueError(f"{exp_dir}: schema {version!r} not supported (only "
                         f"{', '.join(SCAN_SCHEMA_READABLE)}; float32 scans 1.0 are not "
                         "readable)")
    with np.load(exp_dir / "scan.npz") as npz:
        data = {k: npz[k] for k in npz.files}
    conv = meta["conversion"]
    bits, n = conv["quantizer_bits"], conv["n_avg"]
    for ch in ("ch1", "ch2"):
        data[f"signals_{ch}_sum"] = data[f"signals_{ch}"]
        data[f"signals_{ch}"] = counts_to_float_rows(data[f"signals_{ch}_sum"], n,
                                                     data[f"offsets_{ch}"], bits)
    if "point_valid" not in data:                  # 2.0: a line, every point acquired
        data["point_valid"] = np.ones(data["signals_ch1_sum"].shape[:2], dtype=bool)
    if "witness_sum1" in data:                     # same conversion as the signals
        for k in ("1", "2"):
            data[f"witness_ch{k}"] = counts_to_float_rows(data[f"witness_sum{k}"], n,
                                                          data[f"witness_offset{k}"], bits)
    for which, rc in conv.get("references", {}).items():
        for k in ("1", "2"):
            x, _ = counts_to_float(data[f"ref_{which}_sum{k}"], rc["n_avg"], rc["quantizer_bits"],
                                   offset=float(data[f"ref_{which}_offset{k}"]))
            data[f"ref_{which}_ch{k}"] = x
    return meta, data


def load_raw32(exp_dir):
    """
    Carga meta.json, results.json y signals.npz desde la carpeta del experimento.
    Devuelve: meta (dict), results (dict), signals (dict de np.ndarray), tiempos (dict de np.ndarray)
    """
    exp_dir = Path(exp_dir)
    meta    = json.loads((exp_dir/"meta.json").read_text(encoding="utf-8"))
    results = json.loads((exp_dir/"results.json").read_text(encoding="utf-8"))
    npz     = np.load(exp_dir/"signals"/"signals.npz")

    # Señales
    signals = {
        "Signal_PE":  npz["Signal_PE"].astype(np.float64),
        "Signal_TT":  npz["Signal_TT"].astype(np.float64),
        "Signal_Ref": npz["Signal_Ref"].astype(np.float64),
    }

    # Eje temporal (si están F_muestreo y Smin en meta)
    params = meta.get("equipment", {}).get("device_1_ultrasound", {}).get("params", {})
    Fs   = float(params.get("F_muestreo", 0.0) or 0.0)
    Smin = int(params.get("Smin", 0) or 0)

    times = {}
    if Fs > 0:
        for name, y in signals.items():
            n0 = Smin
            N  = y.size
            sample_idx = np.arange(n0, n0 + N, dtype=np.int64)
            times[name] = sample_idx / Fs
    else:
        # Si no hay Fs en meta, devolvemos None y trabajas con índices de muestra
        for name, y in signals.items():
            times[name] = None

    return meta, results, signals, times

def plot_signals(signals, times=None, title="Señales"):
    """Grafica las tres señales si tienes matplotlib instalado."""
    plt.figure()
    for name, y in signals.items():
        x = times.get(name) if (times and times.get(name) is not None) else np.arange(y.size)
        plt.plot(x, y, label=name)  # no forzamos colores
    plt.grid(True)
    plt.xlabel("t [s]" if (times and list(times.values())[0] is not None) else "sample")
    plt.ylabel("amplitud [V]")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.show()
    
def plot_signals_stacked(signals, times=None, title="Señales (3 subplots)"):
    """
    Dibuja Signal_PE, Signal_TT y Signal_Ref en 3 subplots verticales.
    - signals: dict con np.ndarray por señal.
    - times:   dict con eje temporal por señal (o None para usar índice de muestra).
    """
    import numpy as np
    import matplotlib.pyplot as plt

    # Orden preferente; si falta alguna clave, omitimos; si hay extras, las añadimos al final.
    prefer = ["Signal_PE", "Signal_TT", "Signal_Ref"]
    names = [k for k in prefer if k in signals] + [k for k in signals.keys() if k not in prefer]

    fig, axs = plt.subplots(len(names), 1, sharex=True, figsize=(10, 7))
    if len(names) == 1:
        axs = [axs]

    # ¿Tenemos tiempo en segundos?
    has_time = bool(times) and any(times.get(n) is not None for n in names)

    for ax, name in zip(axs, names):
        y = np.asarray(signals[name], dtype=float)
        if times and times.get(name) is not None:
            x = times[name]
            ax.plot(x, y)
        else:
            x = np.arange(y.size)
            ax.plot(x, y)
        ax.set_ylabel(name)     # etiqueta cada subplot con el nombre de la señal
        ax.grid(True)

    axs[-1].set_xlabel("t [s]" if has_time else "sample")
    fig.suptitle(title)
    fig.tight_layout()  # ajusta espacios para que no se solapen títulos/etiquetas
    plt.show()

def quick_stats(y, Fs=None):
    """Estadísticos rápidos de una señal."""
    y = np.asarray(y, dtype=np.float64)
    stats = {
        "N": int(y.size),
        "min": float(np.min(y)),
        "max": float(np.max(y)),
        "rms": float(np.sqrt(np.mean(y**2))),
        "mean": float(np.mean(y)),
        "std": float(np.std(y, ddof=1)) if y.size > 1 else 0.0,
    }
    # pico en frecuencia (aprox) si se conoce Fs
    if Fs and Fs > 0 and y.size > 1:
        Y = np.fft.rfft(y)
        f = np.fft.rfftfreq(y.size, d=1.0/Fs)
        k = int(np.argmax(np.abs(Y)))
        stats["f_peak_Hz"] = float(f[k])
    return stats

def load_latest(base_dir="data_32"):
    """ carga el último experimento."""
    base = Path(base_dir)
    runs = sorted([p for p in base.glob("*_EXPID-*") if p.is_dir()])
    if not runs:
        raise FileNotFoundError(f"No hay experimentos en {base_dir}")
    return load_raw32(runs[-1])

def export_signal_to_csv(exp_dir, name, y, t=None):
    """ exporta señales a CSV"""
    exp_dir = Path(exp_dir)
    out = exp_dir / "signals" / f"{name}.csv"
    if t is not None:
        data = np.column_stack([t, y])
        np.savetxt(out, data, delimiter=",", header="time_s,value", comments="", fmt="%.9g")
    else:
        np.savetxt(out, y, delimiter=",", header="value", comments="", fmt="%.9g")
    return str(out)


def export_results_catalog_csv(base_dir="data_32",
                               out_csv="catalog_results.csv",
                               delimiter=";",
                               decimal_comma=False):
    """
    Recorre <base_dir> y genera un CSV con una fila por experimento usando
    SOLO meta.json (bloque specimen + experiment) y results.json.
    - delimiter: usa ';' si tu Excel está en configuración española.
    - decimal_comma=True: convierte floats '1234.56' -> '1234,56' (como texto).
    """
    base = Path(base_dir)
    runs = sorted([p for p in base.glob("*_EXPID-*") if p.is_dir()])
    rows = []
    specimen_cols, result_cols = set(), set()

    def fmt(v):
        # Convierte floats a coma decimal si se solicita
        if decimal_comma and isinstance(v, float):
            # 12 cifras sig. para no inflar el texto
            s = f"{v:.12g}".replace(".", ",")
            return s
        return v

    for run in runs:
        meta_path = run / "meta.json"
        res_path  = run / "results.json"
        if not (meta_path.exists() and res_path.exists()):
            continue

        meta    = json.loads(meta_path.read_text(encoding="utf-8"))
        results = json.loads(res_path.read_text(encoding="utf-8"))
        specimen = meta.get("specimen", {})
        expinfo  = meta.get("experiment", {})

        row = {
            "experiment_id": expinfo.get("id", ""),
            "timestamp_start": expinfo.get("timestamp_start", ""),
            "timestamp_end": expinfo.get("timestamp_end", ""),
            "operator": expinfo.get("operator", ""),
        }

        # Aplana specimen.* y res.* para evitar colisiones de nombres
        for k, v in specimen.items():
            key = f"specimen.{k}"
            row[key] = fmt(v)
            specimen_cols.add(key)

        for k, v in results.items():
            key = f"res.{k}"
            # Intenta convertir strings numéricas con coma a float
            if isinstance(v, str) and v.count(",") == 1 and v.replace(",", "").replace(".", "").isdigit():
                try:
                    v = float(v.replace(",", "."))
                except Exception:
                    pass
            row[key] = fmt(v)
            result_cols.add(key)

        rows.append(row)

    # Orden de columnas: meta básicas + specimen.* + res.*
    fieldnames = (
        ["experiment_id", "timestamp_start", "timestamp_end", "operator"] +
        sorted(specimen_cols) +
        sorted(result_cols)
    )

    # Escritura del CSV
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=delimiter)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})

    return str(out_csv), len(rows), len(fieldnames)

def _extract_row_for_catalog(exp_dir):
    exp_dir = Path(exp_dir)
    meta    = json.loads((exp_dir/"meta.json").read_text(encoding="utf-8"))
    results = json.loads((exp_dir/"results.json").read_text(encoding="utf-8"))

    specimen = meta.get("specimen", {})
    expinfo  = meta.get("experiment", {})

    row = {
        "experiment_id":   expinfo.get("id", ""),
        "timestamp_start": expinfo.get("timestamp_start", ""),
        "timestamp_end":   expinfo.get("timestamp_end", ""),
        "operator":        expinfo.get("operator", ""),
    }
    # Aplana specimen.* y res.* (evita colisiones de nombres)
    for k, v in specimen.items():
        row[f"specimen.{k}"] = v
    for k, v in results.items():
        # intenta convertir strings con coma a float
        if isinstance(v, str):
            try:
                v = float(v.replace(",", ".")) if ("," in v and v.replace(",", ".").replace(".", "", 1).isdigit()) else v
            except Exception:
                pass
        row[f"res.{k}"] = v
    return row

def append_experiment_to_xlsx(exp_dir, xlsx_path="catalog.xlsx", sheet_name="Catalog"):
    """Añade una fila (un experimento) al Excel. Crea el archivo si no existe."""
    from openpyxl import Workbook, load_workbook

    row = _extract_row_for_catalog(exp_dir)
    xlsx_path = Path(xlsx_path)

    # Abrir o crear libro/hoja
    if xlsx_path.exists():
        wb = load_workbook(xlsx_path)
        ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.create_sheet(sheet_name)
        headers = [c.value for c in (ws[1] if ws.max_row >= 1 else [])]
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = sheet_name
        headers = []

    # Unir columnas: mantener las existentes y añadir las nuevas al final
    desired = headers[:] if headers else ["experiment_id","timestamp_start","timestamp_end","operator"]
    for k in row.keys():
        if k not in desired:
            desired.append(k)

    # Escribir/actualizar cabecera (primera fila)
    if headers != desired:
        for j, h in enumerate(desired, start=1):
            ws.cell(row=1, column=j, value=h)

    # Escribir fila nueva en el orden de 'desired'
    next_row = ws.max_row + 1 if ws.max_row >= 1 else 2
    for j, h in enumerate(desired, start=1):
        ws.cell(row=next_row, column=j, value=row.get(h, ""))

    wb.save(xlsx_path)
    return str(xlsx_path), next_row-1, len(desired)