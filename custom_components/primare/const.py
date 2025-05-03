# custom_components/primare/const.py

DOMAIN = "primare"

# Eingangsliste je Gerätetyp
INPUT_MAPS = {
    "Multichannel": {
        1: "Preset1",
        2: "Preset2",
        3: "Preset3",
        4: "Preset4",
        5: "Preset5",
        6: "Preset6",
        7: "Preset7",
        8: "Preset8",
        9: "Preset9",
        10: "Preset10",
        11: "Preset11",
        12: "Preset12",
        13: "Preset13",
        14: "Preset14",
        15: "Preset15",
        16: "Preset16",
        17: "Prisma"
    },
    "Stereo": {
        1: "Input1",
        2: "Input2",
        3: "Input3",
        4: "Input4",
        5: "Input5",
        6: "Input6",
        7: "Input7",
        8: "Input8",
        9: "Input9",
        10: "Input10",
        11: "Input11",
        12: "PC/MAC",
        13: "Prisma"
    }
}

# DSP-Modi (nur bei SP25 genutzt)
DSP_MAP = {
    1: "Auto",
    2: "Bypass",
    3: "Stereo",
    4: "Party",
    5: "Dolby Digital: Movie",
    6: "Dolby Digital: Music",
    7: "Dolby Digital: Night",
    8: "DTS Neural: X",
    9: "Native"
}

DSP_MAP_INV = {v: k for k, v in DSP_MAP.items()}

# Diese beiden werden dynamisch beim Setup gesetzt:
INPUT_MAP = {}
INPUT_MAP_INV = {}
