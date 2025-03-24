# custom_components/primare/const.py
INPUT_MAP = {
    1: "Preset 1",
    2: "Preset 2",
    3: "Preset 3",
    4: "Preset 4",
    5: "Preset 5",
    6: "Preset 6",
    7: "Preset 7",
    8: "Preset 8",
    9: "Preset 9",
    10: "Preset 10",
    11: "Preset 11",
    12: "Preset 12",
    13: "Preset 13",
    14: "Preset 14",
    15: "Preset 15",
    16: "Preset 16",
    17: "Prisma"
}

INPUT_MAP_INV = {v: k for k, v in INPUT_MAP.items()}

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
