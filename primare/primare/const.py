# custom_components/primare/const.py
INPUT_MAP = {
    1: "BD LG",
    2: "BD PAN",
    3: "FireTV",
    4: "HDMI ARC",
    5: "TV Opto",
    6: "Game Console",
    7: "SAT/Receiver",
    8: "PC/Mac",
    9: "Radio",
    10: "PC",
    11: "Spotify",
    12: "Tidal",
    13: "Deezer",
    14: "USB",
    15: "Kabel TV",
    16: "Test Input 1",
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
