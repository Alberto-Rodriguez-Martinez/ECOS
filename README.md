[README.md](https://github.com/user-attachments/files/26564099/README.md)
# ECOS — Elastic Characterization Of Soft-tissue phantoms

> Ultrasonic characterization of tissue-mimicking materials for surgical robotics applications  
> **Universidad Miguel Hernández (UMH)** · Department of Communications Engineering · Medical Robotics Group

---

## Overview

ECOS is a research project focused on the ultrasonic characterization of soft-tissue phantoms — primarily PVA (polyvinyl alcohol) hydrogels — for use as validation tools in robotic probe manipulation and trajectory testing. The project builds on prior expertise in ultrasonic characterization of nanoparticle-doped composites and extends it to viscoelastic modeling of biological tissue surrogates.

Key features of the methodology:
- Simultaneous measurement of ultrasonic velocity and thickness (three-signal scheme: s_W, s_T, s_R)
- Multi-frequency characterization with viscoelastic modelling (complex E*(f), G*(f))
- Custom APWP (Adaptive Pulse Waveform Programming) excitation for flat spectral coverage
- Repeated-measures experimental design across freeze-thaw cycles
- Cross-validation with mechanical force measurements

---

## Repository Structure

```
ECOS/
├── acquisition/
│   └── ECOS_acquisition.py             ← Main acquisition script
│
├── tools/                              ← Lab toolboxes
│   ├── ACQ_ToolBox.py
│   ├── GenCode_ToolBox.py
│   ├── US_ToolBox_2025.py
│   ├── Apply_SSP_V1.py
│   ├── Loaders_ToolBox_V1.py
│   ├── Plotters_ToolBox_V1.py
│   ├── SpectralAnalysis_ToolBox.py
│   ├── SSP_TOOLBOX.py
│   ├── SSP_RealTime.py
│   ├── Scanner.py
│   ├── SeDaq.py
│   ├── SeDaqDLL.dll                    ← Hardware DLL (digitizer interface)
│   ├── UserFunct.py
│   └── ultrasound_velocity_tools/
│       ├── ultrasound_velocity_tools.py
│       ├── demo.ipynb
│       └── README.md
│
├── database/
│   └── BD_Experimentos_PVA.py          ← Experiment database manager
│
├── hardware/
│   ├── temperature_Alberto_temporal.py ← Temperature acquisition (active)
│   ├── SpeedsoundWater.py
│   └── arduino/
│       └── SPI_MAX31865_temperature_2sensors.ino
│
├── analysis/
│   └── ejemplo_uso_BD_PVA.py           ← Database usage example
│
├── _archive/                           ← Obsolete code (local only, not synced)
│
├── data/                               ← Measurement data (local only, not synced)
│
└── .gitignore
```

> `data/` and `_archive/` are excluded from the repository via `.gitignore`.

---

## Requirements

### Hardware
- Custom pulser/receiver system (APWP-capable, with `SeDaqDLL.dll` interface)
- Immersion tank (temperature-controlled)
- Ultrasonic transducers (multiple frequencies)
- Temperature sensors (2× PT100 via MAX31865, Arduino interface)
- Mechanical force measurement instrument (micro-resolution sensor)
- Medical ultrasound equipment (for heterogeneous phantom validation)

### Software
- Python 3.x
- NumPy, SciPy, Matplotlib
- Jupyter Notebook / JupyterLab

Install dependencies:
```bash
pip install -r requirements.txt
```

---

## Measurement Method

The core methodology uses a **three-signal acquisition scheme** to simultaneously solve for two unknowns: longitudinal wave velocity (c_s) and sample thickness (L).

| Signal | Description |
|--------|-------------|
| s_W    | Reference signal through water (no sample) |
| s_T    | Transmitted signal through sample |
| s_R    | Reflected signal from sample surfaces |

Time-of-flight (TOF) is extracted via **cross-correlation**. Overlapping echoes are resolved using iterative deconvolution. The method is extended to the frequency domain to obtain velocity dispersion and attenuation spectra (α·f^n model).

Viscoelastic moduli are derived from:
- **Longitudinal velocity** → complex longitudinal modulus E*(f)
- **Shear velocity** → complex shear modulus G*(f)

---

## Phantom Fabrication

Materials studied:
- PVA hydrogels (variable concentration and freeze-thaw cycles)
- Propylene glycol as cryo-protectant (variable concentration)
- Nanoparticle dopants (exploratory)

> ⚠️ **Critical**: Handling protocols between measurement cycles must be strictly followed. Refer to the lab protocol documentation for full procedures.

---

## Experimental Design

A **repeated-measures design** is used: the same phantom pieces are measured across freeze-thaw cycles, reducing sample count while maintaining statistical validity. Conditions span PVA and propylene glycol concentration combinations.

Phases:
1. Calibration with homogeneous PVA samples
2. Multi-frequency characterization + viscoelastic modelling
3. Nanoparticle doping studies
4. Heterogeneous phantom validation with clinical equipment
5. Project closure and publication

---

## Key Publications

- A. Rodriguez *et al.*, "Automatic simultaneous measurement of velocity and thickness," *NDT&E International*, 2014.
- A. Rodriguez *et al.*, "Characterization of nanoparticle-doped composites using ultrasound," 2018.
- A. Rodriguez *et al.*, "On the Optimisation of Ultrasonic Pulser-Receiver Systems (APWP)," *IEEE Access*, 2022.

---

## Contact

**A. Rodriguez-Martinez**  
Professor, Department of Communications Engineering  
Universidad Miguel Hernández, Elche (Spain)  
`arodriguezm@umh.es`

---

## License

This repository is for research use within the group. Please contact the author before reusing or redistributing any content.
