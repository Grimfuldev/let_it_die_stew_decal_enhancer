"""
Stew Decal Enhancer - choose how many of each premium skill decal the
Mushroom Lady's stew may still give you in the LET IT DIE offline edition.

Decal art is read from the player's own game install while the program runs
and is only held in memory. Nothing from the game is written to disk.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import queue
import re
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
import zlib
from tkinter import filedialog

if sys.platform == "win32":
    from ctypes import wintypes

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "v0.2"
APP_TITLE = "Stew Decal Enhancer"
APP_ID = "Grimfuldev.LID.StewDecalEnhancer"

GACHA_ID = "SKLGACH_NORMAL_OFFLINE"
GAME_EXE = "BrgGame-Steam.exe"
SAVE_NAME = "brggame.sav"
GAME_FOLDER = "LET IT DIE"
INF = -1
MAX_HOLD = 99                       # the game caps each premium decal at 99
SHA_UNLOCKER_URL = "https://github.com/Grimfuldev/let_it_die_borderless/releases/tag/v0.4"
# the game keeps the stew lineup in memory; it only re-reads masters.db after one of these
REFRESH_HINT = ("The next pull already uses it. Check Lineup in the game shows it after you "
                "leave and re-enter the Mushroom Lady.")
ALL_ZERO_MSG = "At least one decal must be inf or greater than 0"
ALL_MAXED_MSG = "All decals maxed, all maxed decals are set to obtainable"
NOT_PATCHED_MSG = "Patch the game first: Settings > Patch game."
SHA_LOCKED_MSG = "First you have to unlock SHA (this program doesn't has that feature)"

# catalog groups (premium_decals.json sections); PlayStation-only decals are not used
GROUPS = ("mushroom_lady", "bags", "collab")
GROUP_LABEL = {"mushroom_lady": "Mushroom Lady", "bags": "Lost Bag", "collab": "Collab"}

SORTS = ("Max val", "Min val", "Stars(+)", "Stars(-)", "Owned")

BG_COLOR = "#0b0b0d"
PANEL = "#141418"
TILE_PAD = "#28282e"
ENTRY_BG = "#030303"
ENTRY_BD = "#e0e0e0"
TEXT_FG = "#e6e8eb"
TEXT_DIM = "#969696"
BTN_BG = "#515151"
BTN_FG = "#ffffff"
BTN_ACTIVE = "#6d6d6d"
DARK_BTN = "#28282e"

TILE_IMG = 128
ROW1, ROW2, MID_TOP = 30, 74, 98      # header rows and top of the decal panel
DOUBLE_CLICK = 0.5                  # seconds between the two clicks that send a decal to Browse
TILE_W = 150
TILE_H = 182

ASSET_BG = ("UI background.webp",)
ASSET_CURSOR = ("let it die cursor.webp",)
ASSET_ICO = ("lidico.ico",)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def bundle_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", app_dir())
    return app_dir()


def find_file(*names: str, sub: str = "") -> str:
    """Look next to the program first, then inside the packed exe."""
    seen = set()
    for base in (app_dir(), bundle_dir(), os.getcwd()):
        root = os.path.normpath(os.path.join(base, sub) if sub else base)
        if root in seen:
            continue
        seen.add(root)
        for name in names:
            path = os.path.join(root, name)
            if os.path.isfile(path):
                return path
    return ""


def find_asset(*names: str) -> str:
    return find_file(*names, sub="UI_Assets") or find_file(*names)


def settings_path() -> str:
    return os.path.join(app_dir(), "settings.ini")


def limits_path() -> str:
    return os.path.join(app_dir(), "decal_max.json")


def lock_path() -> str:
    return os.path.join(app_dir(), "stew.lock")


# ---------------------------------------------------------------------------
# LZO1X decompression (UE3 packages use it for compressed chunks)
# ---------------------------------------------------------------------------

class LZOError(Exception):
    pass


def lzo1x_decompress(src, out_len=None) -> bytes:
    src = memoryview(src)
    n = len(src)
    dst = bytearray()

    def run_length(ip, t, base):
        start = ip
        while src[ip] == 0:
            ip += 1
        t += (ip - start) * 255 + base + src[ip]
        return ip + 1, t

    def copy_match(m_pos, t):
        if m_pos < 0:
            raise LZOError("bad back-reference")
        end = m_pos + t
        if end <= len(dst):
            dst.extend(dst[m_pos:end])
        else:
            for k in range(t):
                dst.append(dst[m_pos + k])

    ip = 0
    state = 0
    if src[0] > 17:
        t = src[0] - 17
        ip = 1
        dst.extend(src[ip:ip + t])
        ip += t
        state = t if t < 4 else 4

    while ip < n:
        t = src[ip]
        ip += 1
        if t < 16:
            if state == 0:
                if t == 0:
                    ip, t = run_length(ip, t, 15)
                t += 3
                dst.extend(src[ip:ip + t])
                ip += t
                state = 4
                continue
            nxt = t & 3
            if state != 4:
                m_pos = len(dst) - 1 - (t >> 2) - (src[ip] << 2)
                ip += 1
                copy_match(m_pos, 2)
            else:
                m_pos = len(dst) - 0x801 - (t >> 2) - (src[ip] << 2)
                ip += 1
                copy_match(m_pos, 3)
        elif t >= 64:
            nxt = t & 3
            m_pos = len(dst) - 1 - ((t >> 2) & 7) - (src[ip] << 3)
            ip += 1
            copy_match(m_pos, (t >> 5) + 1)
        elif t >= 32:
            t = (t & 31) + 2
            if t == 2:
                ip, t = run_length(ip, t, 31)
            v = src[ip] | (src[ip + 1] << 8)
            ip += 2
            nxt = v & 3
            copy_match(len(dst) - 1 - (v >> 2), t)
        else:
            m_pos = len(dst) - ((t & 8) << 11)
            t = (t & 7) + 2
            if t == 2:
                ip, t = run_length(ip, t, 7)
            v = src[ip] | (src[ip + 1] << 8)
            ip += 2
            m_pos -= v >> 2
            nxt = v & 3
            if m_pos == len(dst):
                break
            copy_match(m_pos - 0x4000, t)
        state = nxt
        if nxt:
            dst.extend(src[ip:ip + nxt])
            ip += nxt
    if out_len is not None and len(dst) != out_len:
        raise LZOError("size mismatch")
    return bytes(dst)


# ---------------------------------------------------------------------------
# UE3 package reading (decal textures only, in memory)
# ---------------------------------------------------------------------------

class Reader:
    def __init__(self, data, pos=0):
        self.d = data
        self.p = pos

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def u64(self):
        v = struct.unpack_from("<Q", self.d, self.p)[0]
        self.p += 8
        return v

    def raw(self, n):
        v = bytes(self.d[self.p:self.p + n])
        self.p += n
        return v

    def fstring(self):
        n = self.i32()
        if n == 0:
            return ""
        if n < 0:
            v = bytes(self.d[self.p:self.p - 2 * n]).decode("utf-16-le", "replace")
            self.p += -2 * n
        else:
            v = bytes(self.d[self.p:self.p + n]).decode("latin-1")
            self.p += n
        return v.rstrip("\0")


def read_compressed_chunk(data, pos) -> bytes:
    """UE3 compressed chunk: tag, block size, totals, block table, LZO blocks."""
    tag, _bs, _csize, usize = struct.unpack_from("<IiII", data, pos)
    if tag != 0x9E2A83C1:
        raise ValueError("bad chunk tag")
    p = pos + 16
    blocks = []
    got = 0
    while got < usize:
        c, u = struct.unpack_from("<ii", data, p)
        blocks.append((c, u))
        got += u
        p += 8
    out = bytearray()
    for c, u in blocks:
        out += lzo1x_decompress(data[p:p + c], u)
        p += c
    return bytes(out)


class Package:
    def __init__(self, path: str):
        with open(path, "rb") as fh:
            raw = fh.read()
        r = Reader(raw)
        if r.u32() != 0x9E2A83C1:
            raise ValueError("not a UE3 package")
        r.p += 4                                   # version, licensee
        r.i32()                                    # header size
        r.fstring()                                # folder
        r.u32()                                    # package flags
        self.name_count, self.name_off = r.i32(), r.i32()
        self.export_count, self.export_off = r.i32(), r.i32()
        self.import_count, self.import_off = r.i32(), r.i32()
        r.i32()                                    # depends
        r.p += 16                                  # guid tables / thumbnails
        r.p += 16                                  # package guid
        gens = r.i32()
        r.p += gens * 12
        r.p += 8                                   # engine / cooker version
        cflags = r.u32()
        nchunks = r.i32()
        chunks = [(r.i32(), r.i32(), r.i32(), r.i32()) for _ in range(nchunks)]
        if cflags and chunks:
            end = max(uo + us for uo, us, _, _ in chunks)
            full = bytearray(end)
            full[:chunks[0][0]] = raw[:chunks[0][0]]
            for uo, us, co, _cs in chunks:
                full[uo:uo + us] = read_compressed_chunk(raw, co)[:us]
            self.data = full
        else:
            self.data = raw
        self._read_tables()

    def _read_tables(self):
        r = Reader(self.data, self.name_off)
        self.names = []
        for _ in range(self.name_count):
            self.names.append(r.fstring())
            r.p += 8
        r.p = self.import_off
        self.imports = []
        for _ in range(self.import_count):
            r.p += 16                              # class package, class name
            cls_idx = struct.unpack_from("<i", self.data, r.p - 8)[0]
            r.i32()                                # outer
            name_idx = r.i32()
            r.i32()
            self.imports.append((self.names[cls_idx], self.names[name_idx]))
        r.p = self.export_off
        self.exports = []
        for _ in range(self.export_count):
            cls = r.i32()
            r.i32()                                # super
            r.i32()                                # outer
            name_idx = r.i32()
            r.i32()
            r.i32()                                # archetype
            r.u64()                                # object flags
            size, off = r.i32(), r.i32()
            r.u32()                                # export flags
            net = r.i32()
            r.p += 4 * net
            r.p += 16 + 4                          # guid, package flags
            cname = self.imports[-cls - 1][1] if cls < 0 else ""
            self.exports.append((self.names[name_idx], cname, size, off))

    def fname(self, r: Reader) -> str:
        idx, num = r.i32(), r.i32()
        name = self.names[idx]
        return name + ("_%d" % (num - 1) if num else "")

    def texture(self, name: str, cooked_dir: str):
        """Return a PIL image of the top mip of Texture2D `name`."""
        from PIL import Image

        exp = next((e for e in self.exports if e[0] == name and e[1] == "Texture2D"), None)
        if not exp:
            raise KeyError(name)
        r = Reader(self.data, exp[3])
        r.i32()                                    # net index
        props = {}
        while True:
            pname = self.fname(r)
            if pname == "None":
                break
            ptype = self.fname(r)
            size = r.i32()
            r.i32()                                # array index
            if ptype == "BoolProperty":
                props[pname] = self.data[r.p]
                r.p += 1
            elif ptype == "StructProperty":
                self.fname(r)
                r.p += size
            elif ptype == "ByteProperty":
                self.fname(r)                      # enum name
                if size == 8:
                    props[pname] = self.fname(r)
                else:
                    props[pname] = self.data[r.p]
                    r.p += size
            elif ptype == "NameProperty":
                props[pname] = self.fname(r)
            elif ptype == "IntProperty":
                props[pname] = r.i32()
            else:
                r.p += size
        fmt = props.get("Format", "PF_A8R8G8B8")
        # source art bulk data (empty in cooked packages)
        flags = r.u32()
        r.i32()
        size = r.u64()
        r.u64()
        if not flags & 1:
            r.p += size
        if r.i32() < 1:
            raise ValueError("no mips")
        flags = r.u32()
        r.i32()
        size = r.u64()
        offset = r.u64()
        if flags & 1:
            cache = props.get("TextureFileCacheName", "Textures")
            with open(os.path.join(cooked_dir, cache + ".tfc"), "rb") as fh:
                fh.seek(offset)
                data = fh.read(size)
        else:
            data = r.raw(size)
        if flags & 0x10:
            data = read_compressed_chunk(data, 0)
        sx, sy = r.i32(), r.i32()
        if fmt == "PF_A8R8G8B8":
            return Image.frombytes("RGBA", (sx, sy), data, "raw", "BGRA")
        if fmt == "PF_DXT5":
            return Image.frombytes("RGBA", (sx, sy), data, "bcn", 3)
        if fmt == "PF_DXT1":
            return Image.frombytes("RGBA", (sx, sy), data, "bcn", 1)
        raise ValueError("unsupported format " + fmt)


def load_decal_art(cooked_dir: str, icon: str):
    """Small (128px) decal art, falling back to the bigger versions."""
    for suffix in ("_S", "_M", ""):
        path = os.path.join(cooked_dir, "UI_%s%s_SF.upk" % (icon, suffix))
        if not os.path.isfile(path):
            continue
        try:
            img = Package(path).texture("TX_UI_Image_%s%s" % (icon, suffix), cooked_dir)
            if img.size != (TILE_IMG, TILE_IMG):
                img = img.resize((TILE_IMG, TILE_IMG))
            return img
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Save file (brggame.sav): "BRG\0", version, size, "ZLIB", zlib chunks
# ---------------------------------------------------------------------------

class SaveError(Exception):
    pass


def read_save(path: str):
    with open(path, "rb") as fh:
        blob = fh.read()
    if blob[:4] != b"BRG\0" or blob[12:16] != b"ZLIB":
        raise SaveError("not a LET IT DIE save")
    version, total = struct.unpack_from("<II", blob, 4)
    p = 16
    out = bytearray()
    sizes = []
    while len(out) < total:
        usize, csize = struct.unpack_from("<II", blob, p)
        out += zlib.decompress(blob[p + 8:p + 8 + csize])
        sizes.append(usize)
        p += 8 + csize
    if len(out) != total:
        raise SaveError("save size mismatch")
    meta = {"version": version, "chunks": len(sizes), "trailer": bytes(blob[p:])}
    return bytes(out), meta


def write_save(path: str, raw: bytes, meta: dict) -> None:
    n = max(1, int(meta.get("chunks", 4)))
    step = max(1, math.ceil(len(raw) / n))
    body = bytearray()
    for i in range(0, len(raw), step):
        part = raw[i:i + step]
        comp = zlib.compress(part, 6)
        body += struct.pack("<II", len(part), len(comp)) + comp
    blob = (b"BRG\0" + struct.pack("<II", meta.get("version", 2), len(raw)) + b"ZLIB"
            + bytes(body) + meta.get("trailer", b"\0\0\0\0"))
    tmp = path + ".sde_tmp"
    with open(tmp, "wb") as fh:
        fh.write(blob)
    check, _ = read_save(tmp)
    if check != raw:
        os.remove(tmp)
        raise SaveError("re-encoded save did not read back the same")
    os.replace(tmp, path)


def owned_counts(save_obj: dict) -> dict:
    """premium id -> (in inventory, equipped). Only eqskl["1"] is real."""
    skl = (save_obj.get("soul") or {}).get("skl") or {}
    inv = {}
    for item in skl.get("psskl") or []:
        sid = item.get("sklid")
        if sid:
            inv[sid] = inv.get(sid, 0) + max(0, int(item.get("cnt") or 0))
    eq = {}
    for item in (skl.get("eqskl") or {}).get("1") or []:
        sid = item.get("sklid")
        if sid:
            eq[sid] = eq.get(sid, 0) + 1
    return {sid: (inv.get(sid, 0), eq.get(sid, 0)) for sid in set(inv) | set(eq)}


GACHA_LIST_RE = re.compile(rb'("normal"\s*:\s*\{\s*"sklids"\s*:\s*)(\[[^\]]*\]|\{[^{}]*\})')


def empty_gacha_list(raw: bytes):
    """Empty soul.skl.gacha.normal.sklids, leaving every other byte as it was.

    The game writes the list as [..] when it has entries and as {} when it is empty,
    so an emptied list is written as {} too. Returns None if it is already empty.
    """
    found = list(GACHA_LIST_RE.finditer(raw))
    if len(found) != 1:
        raise SaveError("could not find the gacha list in the save")
    mt = found[0]
    before = json.loads(raw)
    cur = before["soul"]["skl"]["gacha"]["normal"]["sklids"]
    if not cur:
        return None
    new = raw[:mt.start(2)] + b"{}" + raw[mt.end(2):]
    after = json.loads(new)
    before["soul"]["skl"]["gacha"]["normal"]["sklids"] = {}
    if before != after:
        raise SaveError("emptying the gacha list changed something else")
    return new


def gacha_list_len(save_obj: dict) -> int:
    try:
        return len(save_obj["soul"]["skl"]["gacha"]["normal"]["sklids"])
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# masters.db (master_skillgacha_odds)
# ---------------------------------------------------------------------------

class DbBusy(Exception):
    pass


def db_open(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=4)
    con.execute("PRAGMA busy_timeout = 4000")
    return con


def db_read_odds(path: str) -> dict:
    con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True, timeout=4)
    try:
        rows = con.execute(
            "SELECT sklid, odds FROM master_skillgacha_odds WHERE id = ?", (GACHA_ID,)).fetchall()
    finally:
        con.close()
    return {sid: odds for sid, odds in rows}


# Rows this program inserted are listed in their own small table inside masters.db (the game
# never reads it), so Restore Decals removes exactly those and leaves rows added by anyone else.
ADDED_TABLE = "stew_decal_enhancer_added"


def db_read_added(path: str):
    """The decals this program added, or None if masters.db has no list (never patched, or v0.1)."""
    con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True, timeout=4)
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                           (ADDED_TABLE,)).fetchone():
            return None
        return {r[0] for r in con.execute("SELECT sklid FROM %s" % ADDED_TABLE)}
    finally:
        con.close()


def db_add_missing(path: str, decals: list) -> int:
    """Insert a stew row (odds 0, the bake sets them) for each decal not in the table yet."""
    con = db_open(path)
    try:
        have = {r[0] for r in con.execute(
            "SELECT sklid FROM master_skillgacha_odds WHERE id = ?", (GACHA_ID,))}
        add = [d["id"] for d in decals if d["id"] not in have]
        with con:
            con.execute("CREATE TABLE IF NOT EXISTS %s (sklid TEXT PRIMARY KEY)" % ADDED_TABLE)
            con.executemany(
                "INSERT INTO master_skillgacha_odds (id, sklid, odds, display_priority) "
                "VALUES (?, ?, 0, 0)", [(GACHA_ID, sid) for sid in add])
            con.executemany("INSERT OR IGNORE INTO %s (sklid) VALUES (?)" % ADDED_TABLE,
                            [(sid,) for sid in add])
        return len(add)
    except sqlite3.OperationalError as exc:
        raise DbBusy(str(exc))
    finally:
        con.close()


def db_adopt(path: str, sklids: set) -> None:
    """v0.1 added its decals without a list: write the list for them."""
    con = db_open(path)
    try:
        with con:
            con.execute("CREATE TABLE IF NOT EXISTS %s (sklid TEXT PRIMARY KEY)" % ADDED_TABLE)
            con.executemany("INSERT OR IGNORE INTO %s (sklid) VALUES (?)" % ADDED_TABLE,
                            [(sid,) for sid in sklids])
    except sqlite3.OperationalError as exc:
        raise DbBusy(str(exc))
    finally:
        con.close()


def db_restore(path: str, original_rows: list, drop_list: bool) -> int:
    """Remove the rows this program added and put the original odds back on the game's own rows.
    Rows added by anyone else are left as they are. Returns how many rows were removed.
    drop_list: also remove the (then empty) list table; Restore Decals keeps it, so masters.db
    still counts as converted and nothing gets adopted later."""
    con = db_open(path)
    try:
        added = []
        if con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                       (ADDED_TABLE,)).fetchone():
            added = [r[0] for r in con.execute("SELECT sklid FROM %s" % ADDED_TABLE)]
        with con:
            con.executemany("DELETE FROM master_skillgacha_odds WHERE id = ? AND sklid = ?",
                            [(GACHA_ID, sid) for sid in added])
            con.executemany("UPDATE master_skillgacha_odds SET odds = ? WHERE id = ? AND sklid = ?",
                            [(int(r["odds"]), GACHA_ID, r["sklid"]) for r in original_rows])
            if drop_list:
                con.execute("DROP TABLE IF EXISTS %s" % ADDED_TABLE)
            else:
                con.execute("DELETE FROM %s" % ADDED_TABLE)
        return len(added)
    except sqlite3.OperationalError as exc:
        raise DbBusy(str(exc))
    finally:
        con.close()


def db_write_odds(path: str, odds: dict) -> int:
    """Set odds for rows that exist. Returns how many rows changed."""
    con = db_open(path)
    try:
        current = dict(con.execute(
            "SELECT sklid, odds FROM master_skillgacha_odds WHERE id = ?", (GACHA_ID,)).fetchall())
        changes = [(int(v), GACHA_ID, sid) for sid, v in odds.items()
                   if sid in current and current[sid] != int(v)]
        if changes:
            with con:
                con.executemany(
                    "UPDATE master_skillgacha_odds SET odds = ? WHERE id = ? AND sklid = ?", changes)
        return len(changes)
    except sqlite3.OperationalError as exc:
        raise DbBusy(str(exc))
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Game exe patches (this build only; every byte is checked before writing)
#   1. the offline decal list is pre-rolled 1 at a time instead of 1000
#   2. the one-draw function mixes the CPU cycle counter into rand()
# ---------------------------------------------------------------------------

COUNT_SITES = ((0x13CCF41, b"\xba"), (0x13CCF4E, b"\xba"), (0x13CD07B, b"\x48\x81\xff"))
COUNT_ORIGINAL, COUNT_PATCHED = 1000, 1
RNG_CALL_RVA = 0x13D7018
RAND_IAT_RVA = 0x1B7CAA0
RNG_MARKER = b"LIDRNGFX"
RNG_STUP_LEN = 37
# 3. no longer applied: a helper that emptied the stew odds table's cache before each draw.
#    Turning immutable off (4.) was enough. Kept only so an exe that still has it gets it
#    taken out by Patch game or Revert patch.
FRESH_SITE_RVA = 0x13BD520          # lea rax, [odds table object]   (end of the getter)
FRESH_RET_RVA = 0x13BD527
ODDS_OBJ_RVA = 0xF8CAB3C
CLEAR_CACHE_RVA = 0x13B05F0
FRESH_MARKER = b"LIDSTWRF"
FRESH_STUB_LEN = 24
# 4. the game opens masters.db as "file:%s?immutable=1": SQLite then never checks whether the file
#    changed and keeps old pages in memory until other reads push them out (e.g. Naomi's
#    quest list). Turning immutable off makes SQLite check before each read.
LIVE_DB_RVA = 0x2206F68             # UTF-16 text used by the masters.db open (0x15AA0B0)
LIVE_DB_ORIGINAL = "file:%s?immutable=1".encode("utf-16-le")
LIVE_DB_PATCHED = "file:%s?immutable=0".encode("utf-16-le")


EXE_LABEL = {
    "original": "not patched by this program",
    "patched": "patched by this program",
    "partial": "partly patched by this program",
    "unknown": "unknown build (cannot patch)",
    "missing": "not found",
    "steam": "original Steam exe (SHA locked), no changes from this program",
}


def rng_stub(stub_rva: int) -> bytes:
    b = bytearray(bytes.fromhex("4883ec28"))
    b += b"\xff\x15" + struct.pack("<i", RAND_IAT_RVA - (stub_rva + len(b) + 6))
    b += bytes.fromhex("4189c0" "0f31" "69c0b179379e" "c1e811" "4431c0" "25ff7f0000" "4883c428" "c3")
    return bytes(b)


def fresh_stub(stub_rva: int) -> bytes:
    """lea rcx,[odds obj] / call clear cache / lea rax,[odds obj] / jmp back."""
    b = bytearray(b"\x48\x8d\x0d" + struct.pack("<i", ODDS_OBJ_RVA - (stub_rva + 7)))
    b += b"\xe8" + struct.pack("<i", CLEAR_CACHE_RVA - (stub_rva + 12))
    b += b"\x48\x8d\x05" + struct.pack("<i", ODDS_OBJ_RVA - (stub_rva + 19))
    b += b"\xe9" + struct.pack("<i", FRESH_RET_RVA - (stub_rva + 24))
    return bytes(b)


class ExeError(Exception):
    pass


class Exe:
    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as fh:
            self.data = bytearray(fh.read())
        d = self.data
        if d[:2] != b"MZ":
            raise ExeError("not an exe")
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        if d[pe:pe + 4] != b"PE\0\0":
            raise ExeError("not a PE file")
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        opt_size = struct.unpack_from("<H", d, pe + 20)[0]
        opt = pe + 24
        self.align = struct.unpack_from("<I", d, opt + 32)[0]
        self.sections = []
        for i in range(nsec):
            h = opt + opt_size + 40 * i
            name = bytes(d[h:h + 8]).rstrip(b"\0")
            vsize, va, rsize, rptr = struct.unpack_from("<IIII", d, h + 8)
            self.sections.append({"name": name, "hdr": h, "vsize": vsize, "va": va,
                                  "rsize": rsize, "rptr": rptr})
        self.text = next((s for s in self.sections if s["name"] == b".text"), None)
        if not self.text:
            raise ExeError("no .text section")

    def off(self, rva: int) -> int:
        for s in self.sections:
            if s["va"] <= rva < s["va"] + max(s["vsize"], s["rsize"]):
                return rva - s["va"] + s["rptr"]
        raise ExeError("address 0x%X not in the file" % rva)

    # --- state -------------------------------------------------------------
    def count_state(self):
        vals = []
        for off, op in COUNT_SITES:
            if bytes(self.data[off:off + len(op)]) != op:
                return None
            vals.append(struct.unpack_from("<i", self.data, off + len(op))[0])
        if len(set(vals)) != 1:
            return None
        return vals[0]

    def rng_state(self):
        """'original', ('patched', stub_rva) or None if the bytes are unknown."""
        o = self.off(RNG_CALL_RVA)
        b = bytes(self.data[o:o + 6])
        if b[:2] == b"\xff\x15" and RNG_CALL_RVA + 6 + struct.unpack_from("<i", b, 2)[0] == RAND_IAT_RVA:
            return "original"
        if b[0] == 0xE8 and b[5] == 0x90:
            stub = RNG_CALL_RVA + 5 + struct.unpack_from("<i", b, 1)[0]
            so = self.off(stub)
            if (bytes(self.data[so - len(RNG_MARKER):so]) == RNG_MARKER
                    and bytes(self.data[so:so + RNG_STUP_LEN]) == rng_stub(stub)):
                return ("patched", stub)
        return None

    def fresh_state(self):
        """'original', ('patched', stub_rva) or None if the bytes are unknown."""
        o = self.off(FRESH_SITE_RVA)
        b = bytes(self.data[o:o + 7])
        if b[:3] == b"\x48\x8d\x05" and FRESH_RET_RVA + struct.unpack_from("<i", b, 3)[0] == ODDS_OBJ_RVA:
            return "original"
        if b[0] == 0xE9 and b[5:7] == b"\x90\x90":
            stub = FRESH_SITE_RVA + 5 + struct.unpack_from("<i", b, 1)[0]
            so = self.off(stub)
            if (bytes(self.data[so - len(FRESH_MARKER):so]) == FRESH_MARKER
                    and bytes(self.data[so:so + FRESH_STUB_LEN]) == fresh_stub(stub)):
                return ("patched", stub)
        return None

    def live_state(self):
        """'original', 'patched' or None if the bytes are unknown."""
        o = self.off(LIVE_DB_RVA)
        b = bytes(self.data[o:o + len(LIVE_DB_ORIGINAL)])
        return {LIVE_DB_ORIGINAL: "original", LIVE_DB_PATCHED: "patched"}.get(b)

    def state(self) -> str:
        parts = [self.count_state(), self.rng_state(), self.fresh_state(), self.live_state()]
        if any(p is None for p in parts):
            return "unknown"
        old_helper = parts[2] != "original"
        done = [parts[0] == COUNT_PATCHED, parts[1] != "original", parts[3] == "patched"]
        if all(done) and not old_helper:
            return "patched"
        if parts[0] == COUNT_ORIGINAL and not any(done[1:]) and not old_helper:
            return "original"
        return "partial"

    # --- changes -----------------------------------------------------------
    def _cave(self, marker: bytes, length: int):
        """Free space after the code: [start: code size before, u32 + 4 zero][marker][helper]."""
        t = self.text
        start = (t["va"] + t["vsize"] + 15) & ~15
        stub = (start + len(marker) + 15) & ~15
        mark = stub - len(marker)
        end = stub + length
        page_end = (t["va"] + t["vsize"] + self.align - 1) & ~(self.align - 1)
        if end > t["va"] + t["rsize"] or end > page_end:
            raise ExeError("no free space for a helper at the end of the code")
        o1, o2 = self.off(start), self.off(end - 1) + 1
        if mark - start < 4 or any(self.data[o1:o2]):
            raise ExeError("the free space at the end of the code is not empty")
        return start, mark, stub, end

    def _place(self, marker: bytes, body_for) -> int:
        """Write [old code size][marker][helper] after the code and grow the code size. -> helper rva."""
        t = self.text
        start, mark, stub, end = self._cave(marker, len(body_for(0)))
        struct.pack_into("<I", self.data, self.off(start), t["vsize"])
        self.data[self.off(mark):self.off(mark) + len(marker)] = marker
        body = body_for(stub)
        self.data[self.off(stub):self.off(stub) + len(body)] = body
        if end - t["va"] > t["vsize"]:
            t["vsize"] = end - t["va"]
            struct.pack_into("<I", self.data, t["hdr"] + 8, t["vsize"])
        return stub

    def _remove(self, stub: int, marker: bytes, length: int) -> None:
        """Zero [marker][helper] and put back the code size saved in front of it."""
        so = self.off(stub)
        self.data[so - len(marker):so + length] = bytes(len(marker) + length)
        t = self.text
        saved_at = self.off(stub - len(marker) - 8)
        old = struct.unpack_from("<I", self.data, saved_at)[0]
        if 0 < old < t["vsize"] and (t["va"] + old + 15) & ~15 == stub - len(marker) - 8:
            t["vsize"] = old
            struct.pack_into("<I", self.data, t["hdr"] + 8, old)
            struct.pack_into("<I", self.data, saved_at, 0)

    def _unfresh(self, f) -> None:
        so = self.off(FRESH_SITE_RVA)
        self.data[so:so + 7] = b"\x48\x8d\x05" + struct.pack("<i", ODDS_OBJ_RVA - FRESH_RET_RVA)
        self._remove(f[1], FRESH_MARKER, FRESH_STUB_LEN)

    def patch(self) -> list:
        done = []
        c, r, f, v = self.count_state(), self.rng_state(), self.fresh_state(), self.live_state()
        if c is None or r is None or f is None or v is None:
            raise ExeError("the game exe is not the build this tool knows; nothing was changed")
        if f != "original":                     # newest helper: comes out before anything is added
            self._unfresh(f)
            done.append("old stew cache helper removed")
        if c != COUNT_PATCHED:
            for off, op in COUNT_SITES:
                struct.pack_into("<i", self.data, off + len(op), COUNT_PATCHED)
            done.append("decal list size 1000 -> 1")
        if r == "original":
            stub = self._place(RNG_MARKER, rng_stub)
            co = self.off(RNG_CALL_RVA)
            self.data[co:co + 6] = b"\xe8" + struct.pack("<i", stub - (RNG_CALL_RVA + 5)) + b"\x90"
            done.append("fresh random number per draw")
        if v == "original":
            o = self.off(LIVE_DB_RVA)
            self.data[o:o + len(LIVE_DB_PATCHED)] = LIVE_DB_PATCHED
            done.append("game sees masters.db changes right away")
        return done

    def revert(self) -> list:
        """Undo this program's changes, newest helper first (each puts back the code size before it)."""
        done = []
        c, r, f, v = self.count_state(), self.rng_state(), self.fresh_state(), self.live_state()
        if c is None or r is None or f is None or v is None:
            raise ExeError("the game exe bytes are not what this tool wrote; nothing was changed")
        if v != "original":
            o = self.off(LIVE_DB_RVA)
            self.data[o:o + len(LIVE_DB_ORIGINAL)] = LIVE_DB_ORIGINAL
            done.append("masters.db opened as before (immutable)")
        if f != "original":
            self._unfresh(f)
            done.append("old stew cache helper removed")
        if r != "original":
            co = self.off(RNG_CALL_RVA)
            self.data[co:co + 6] = b"\xff\x15" + struct.pack("<i", RAND_IAT_RVA - (RNG_CALL_RVA + 6))
            self._remove(r[1], RNG_MARKER, RNG_STUP_LEN)
            done.append("original random number call")
        if c != COUNT_ORIGINAL:
            for off, op in COUNT_SITES:
                struct.pack_into("<i", self.data, off + len(op), COUNT_ORIGINAL)
            done.append("decal list size back to 1000")
        return done

    def save(self) -> None:
        tmp = self.path + ".sde_tmp"
        with open(tmp, "wb") as fh:
            fh.write(self.data)
        os.replace(tmp, self.path)


# ---------------------------------------------------------------------------
# Game location
# ---------------------------------------------------------------------------

def steam_libraries(steam_dir: str) -> list:
    libs = [steam_dir]
    vdf = os.path.join(steam_dir, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                parts = line.strip().split('"')
                if len(parts) >= 4 and parts[1].lower() == "path":
                    libs.append(parts[3].replace("\\\\", "\\"))
    except OSError:
        pass
    return libs


def game_dir_from(path: str) -> str:
    """steam.exe (any library) or BrgGame-Steam.exe -> the LET IT DIE folder."""
    path = (path or "").strip().strip('"')
    if not path:
        return ""
    if os.path.basename(path).lower() == GAME_EXE.lower():
        d = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(path))))
        return d if os.path.isdir(d) else ""
    steam_dir = os.path.dirname(os.path.abspath(path)) if os.path.isfile(path) else path
    for lib in steam_libraries(steam_dir):
        d = os.path.join(lib, "steamapps", "common", GAME_FOLDER)
        if os.path.isfile(os.path.join(d, "Binaries", "Win64", GAME_EXE)):
            return d
    return ""


def find_save(game_dir: str) -> str:
    if not game_dir:
        return ""
    first = os.path.join(game_dir, "Binaries", "Win64", SAVE_NAME)
    if os.path.isfile(first):
        return first
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = [d for d in dirs if d.lower() not in ("cookedpcconsole", "movies", "splash")]
        for f in files:
            if f.lower() == SAVE_NAME:
                return os.path.join(root, f)
    return ""


class Paths:
    def __init__(self, steam_path: str, save_override: str = ""):
        self.game = game_dir_from(steam_path)
        g = self.game
        self.exe = os.path.join(g, "Binaries", "Win64", GAME_EXE) if g else ""
        self.db = os.path.join(g, "BrgGame", "Content", "masters.db") if g else ""
        self.cooked = os.path.join(g, "BrgGame", "CookedPCConsole") if g else ""
        so = (save_override or "").strip().strip('"')
        self.save = so if so and os.path.isfile(so) else find_save(g)

    def ok(self) -> bool:
        return bool(self.game) and os.path.isfile(self.exe) and os.path.isfile(self.db)


# ---------------------------------------------------------------------------
# SHA check (read-only). The game verifies its files against a list stored in
# the exe (resource type 10, id 1010: name, NUL, 20-byte SHA-1, ... "+++").
# A name ending in x/y has been switched off by an unlocker. This program never
# changes that list; it only checks that every entry is switched off.
# ---------------------------------------------------------------------------

def sha_state(exe_path: str) -> str:
    """'unlocked', 'locked' or 'unknown'."""
    try:
        with open(exe_path, "rb") as fh:
            raw = fh.read()
        u16 = lambda o: struct.unpack_from("<H", raw, o)[0]
        u32 = lambda o: struct.unpack_from("<I", raw, o)[0]
        pe = u32(0x3C)
        if raw[:2] != b"MZ" or raw[pe:pe + 4] != b"PE\0\0":
            return "unknown"
        opt = pe + 24
        if u16(opt) != 0x20B:
            return "unknown"
        secs = []
        table = opt + u16(pe + 20)
        for i in range(u16(pe + 6)):
            h = table + 40 * i
            vsize, va, rsize, rptr = struct.unpack_from("<IIII", raw, h + 8)
            secs.append((va, max(vsize, rsize), rptr))

        def off(rva):
            for va, span, rptr in secs:
                if va <= rva < va + span:
                    return rptr + rva - va
            raise ValueError("rva")

        res = u32(opt + 112 + 16)
        if not res:
            return "unknown"
        root = off(res)

        def child(at, key):
            for i in range(u16(at + 12) + u16(at + 14)):
                k, o = u32(at + 16 + 8 * i), u32(at + 20 + 8 * i)
                if k == key and o & 0x80000000:
                    return root + (o & 0x7FFFFFFF)
            raise ValueError("resource")

        lang = child(child(root, 10), 1010)
        leaf = u32(lang + 20)
        if leaf & 0x80000000:
            return "unknown"
        leaf += root
        start = off(u32(leaf))
        end = start + u32(leaf + 4)
        names = []
        cur = start
        while cur < end:
            stop = raw.find(b"\0", cur, end)
            if stop < 0:
                break
            name = raw[cur:stop]
            cur = stop + 1
            if not name:
                continue
            if name == b"+++" or cur + 20 > end:
                break
            names.append(name)
            cur += 20
        if not names:
            return "unknown"
        return "unlocked" if all(n[-1:].lower() in (b"x", b"y") for n in names) else "locked"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------

def process_pids(image: str) -> list:
    if sys.platform != "win32":
        return []
    want = (image or "").strip().lower()
    try:
        out = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], creationflags=NO_WINDOW,
                                      stderr=subprocess.DEVNULL, text=True, errors="ignore")
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        parts = [p.strip().strip('"') for p in line.strip().split('","')]
        if len(parts) >= 2 and parts[0].lower() == want and parts[1].isdigit():
            pids.append(int(parts[1]))
    return pids


def game_running() -> bool:
    return bool(process_pids(GAME_EXE))


# ---------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------

def load_catalog() -> list:
    path = find_file("premium_decals.json")
    if not path:
        raise FileNotFoundError("premium_decals.json not found next to the program")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for group in GROUPS:
        for d in data.get(group, []):
            item = dict(d)
            item["group"] = group
            out.append(item)
    return out


def load_original_odds() -> list:
    path = find_file("master_skillgacha_odds.json")
    if not path:
        raise FileNotFoundError("master_skillgacha_odds.json not found next to the program")
    with open(path, "r", encoding="utf-8") as fh:
        rows = json.load(fh)
    return [r for r in rows if r.get("id") == GACHA_ID]


def load_limits() -> dict:
    try:
        with open(limits_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {k: int(v) for k, v in data.items() if isinstance(v, (int, float))}
    except (OSError, ValueError):
        return {}


def save_limits(limits: dict) -> None:
    try:
        tmp = limits_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({k: v for k, v in sorted(limits.items()) if v != INF}, fh, indent=1)
        os.replace(tmp, limits_path())
    except OSError:
        pass


SETTING_DEFAULTS = {
    "steam_exe": "",
    "save_file": "",
    "hotkey": "",
    "show_stars": True,
    "sort": "Max val",
    "include_collab": True,
    "include_lost_bag": True,
    "bake_on_launch": False,
}


def load_settings() -> dict:
    data = dict(SETTING_DEFAULTS)
    try:
        with open(settings_path(), "r", encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key, value = key.strip().lower(), value.strip()
                if key not in data:
                    continue
                if isinstance(SETTING_DEFAULTS[key], bool):
                    data[key] = value.lower() in ("1", "true", "yes")
                elif key == "hotkey":
                    data[key] = value[:1]
                elif key == "sort":
                    data[key] = value if value in SORTS else "Max val"
                else:
                    data[key] = value.strip('"')
    except OSError:
        pass
    return data


def save_settings(s: dict) -> None:
    lines = [
        "# Stew Decal Enhancer settings",
        "# steam_exe = path to steam.exe (or to BrgGame-Steam.exe)",
        "# save_file = brggame.sav path; empty = find it in the game folder",
        "# hotkey = one character that hides/shows the window (empty = none)",
    ]
    for key, default in SETTING_DEFAULTS.items():
        v = s.get(key, default)
        if isinstance(default, bool):
            v = "true" if v else "false"
        lines.append("%s=%s" % (key, v))
    try:
        with open(settings_path(), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Stew maths
# ---------------------------------------------------------------------------

def wanted_odds(catalog: list, limits: dict, owned: dict, include: dict) -> dict:
    """Odds each decal should have in the stew right now."""
    out = {}
    for d in catalog:
        sid = d["id"]
        cap = limits.get(sid, INF)
        have = sum(owned.get(sid, (0, 0)))
        if not include.get(d["group"], True) or cap == 0 or (cap > 0 and have >= cap):
            out[sid] = 0
        else:
            out[sid] = int(d["stew_odds"])
    return out


# ---------------------------------------------------------------------------
# Window chrome (icon, cursor, dark title bar)
# ---------------------------------------------------------------------------

def _lanczos():
    from PIL import Image
    return getattr(getattr(Image, "Resampling", Image), "LANCZOS")


def image_to_cur(src_path: str, cur_path: str, size: int = 32) -> bool:
    try:
        from PIL import Image
        img = Image.open(src_path).convert("RGBA")
        box = img.getbbox()
        if box:
            img = img.crop(box)
        img.thumbnail((size, size), _lanczos())
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(img, (0, 0))
        px = canvas.load()
        hx = hy = 0
        for y in range(size):
            row = [x for x in range(size) if px[x, y][3] > 40]
            if row:
                hx, hy = row[0], y
                break
        xor = bytearray()
        for y in range(size - 1, -1, -1):
            for x in range(size):
                r, g, b, a = px[x, y]
                xor += bytes((b, g, r, a))
        row_and = ((size + 31) // 32) * 4
        and_mask = bytearray(row_and * size)
        for y in range(size):
            dy = size - 1 - y
            for x in range(size):
                if px[x, y][3] < 128:
                    and_mask[dy * row_and + (x >> 3)] |= 0x80 >> (x & 7)
        image = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(xor), 0, 0, 0, 0)
        image += bytes(xor) + bytes(and_mask)
        header = struct.pack("<HHH", 0, 2, 1)
        entry = struct.pack("<BBBBHHII", size, size, 0, 0, hx, hy, len(image), 22)
        with open(cur_path, "wb") as fh:
            fh.write(header + entry + image)
        return True
    except Exception:
        return False


def apply_cursor(widget, cur_path: str) -> None:
    if not cur_path or not os.path.isfile(cur_path):
        return
    path = os.path.abspath(cur_path)
    for spec in ("@" + path, "@" + path.replace("\\", "/")):
        try:
            widget.configure(cursor=spec)
            break
        except Exception:
            continue
    for child in widget.winfo_children():
        apply_cursor(child, cur_path)


_CURSOR_FILE = ""


def cursor_file() -> str:
    global _CURSOR_FILE
    if _CURSOR_FILE:
        return _CURSOR_FILE
    src = find_asset(*ASSET_CURSOR)
    if src and sys.platform == "win32":
        cur = os.path.join(tempfile.gettempdir(), "lid_stew_decal.cur")
        if image_to_cur(src, cur):
            _CURSOR_FILE = cur
    return _CURSOR_FILE


def color_titlebar(win) -> None:
    if sys.platform != "win32":
        return
    try:
        win.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
        black, dark = ctypes.c_int(0), ctypes.c_int(1)
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), 4)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(black), 4)
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(black), 4)
    except Exception:
        pass


def set_app_id() -> None:
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass


def apply_window_chrome(win) -> None:
    """Window + taskbar icon from lidico.ico."""
    ico = find_asset(*ASSET_ICO)
    photo = None
    if ico:
        try:
            from PIL import Image, ImageTk
            img = Image.open(ico)
            if img.format == "ICO" and img.info.get("sizes"):
                img.size = max(img.info["sizes"])          # use the biggest picture in the .ico
            photo = ImageTk.PhotoImage(img.convert("RGBA").resize((64, 64), _lanczos()))
        except Exception:
            photo = None
    if photo:
        try:
            win.iconphoto(True, photo)
            win._icon_photo = photo
        except Exception:
            pass
    if ico and sys.platform == "win32":
        try:
            win.iconbitmap(default=ico)
        except Exception:
            pass
        try:
            # hand Windows the .ico directly for the taskbar (big) and title bar (small)
            user32 = ctypes.windll.user32
            user32.LoadImageW.restype = ctypes.c_void_p
            user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                          ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
            win.update_idletasks()
            hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
            big = user32.LoadImageW(None, os.path.abspath(ico), 1, 32, 32, 0x0010)     # IMAGE_ICON, LR_LOADFROMFILE
            small = user32.LoadImageW(None, os.path.abspath(ico), 1, 16, 16, 0x0010)
            if big:
                user32.SendMessageW(hwnd, 0x0080, 1, big)      # WM_SETICON, ICON_BIG
            if small:
                user32.SendMessageW(hwnd, 0x0080, 0, small)    # WM_SETICON, ICON_SMALL
        except Exception:
            pass
    color_titlebar(win)
    cur = cursor_file()
    if cur:
        apply_cursor(win, cur)


# ---------------------------------------------------------------------------
# Hotkey (RegisterHotKey, so it works while the window is hidden)
# ---------------------------------------------------------------------------

_HOTKEY_ID = 0xE02
_HOTKEY_PRESSED = False
_WNDPROC = None
_OLD_WNDPROC = None
_HOTKEY_HWND = None


def _vk_from_char(ch: str) -> int:
    if not ch or sys.platform != "win32":
        return 0
    try:
        return ctypes.windll.user32.VkKeyScanW(ord(ch[0])) & 0xFF
    except Exception:
        return 0


def install_hotkey(ch: str, win) -> None:
    global _WNDPROC, _OLD_WNDPROC, _HOTKEY_HWND
    uninstall_hotkey()
    vk = _vk_from_char(ch)
    if not vk:
        return
    win.update_idletasks()
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
    _HOTKEY_HWND = hwnd
    if _OLD_WNDPROC is None:
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        def _wndproc(h, msg, wparam, lparam):
            global _HOTKEY_PRESSED
            if msg == 0x0312 and wparam == _HOTKEY_ID:
                _HOTKEY_PRESSED = True
                return 0
            return user32.CallWindowProcW(_OLD_WNDPROC, h, msg, wparam, lparam)

        _WNDPROC = WNDPROC(_wndproc)
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.CallWindowProcW.restype = LRESULT
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM]
        _OLD_WNDPROC = user32.SetWindowLongPtrW(hwnd, -4, _WNDPROC)
    if not user32.RegisterHotKey(hwnd, _HOTKEY_ID, 0, vk):
        user32.RegisterHotKey(hwnd, _HOTKEY_ID, 0x4000, vk)


def uninstall_hotkey() -> None:
    try:
        if _HOTKEY_HWND and sys.platform == "win32":
            ctypes.windll.user32.UnregisterHotKey(_HOTKEY_HWND, _HOTKEY_ID)
    except Exception:
        pass


def consume_hotkey() -> bool:
    global _HOTKEY_PRESSED
    if _HOTKEY_PRESSED:
        _HOTKEY_PRESSED = False
        return True
    return False


# ---------------------------------------------------------------------------
# Single instance
# ---------------------------------------------------------------------------

def process_start(pid: int):
    """When a running process started (Windows FILETIME), or None if it is not running."""
    if sys.platform != "win32" or pid <= 0:
        return None
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = ctypes.c_void_p
    h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        code = wintypes.DWORD()
        if not k.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code)) or code.value != 259:
            return None                            # 259 = STILL_ACTIVE
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(ctypes.c_void_p(h), *[ctypes.byref(t) for t in times]):
            return None
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        k.CloseHandle(ctypes.c_void_p(h))


def read_lock():
    """(pid, start time) from stew.lock; start is None for a lock without one."""
    try:
        parts = open(lock_path(), "r", encoding="utf-8").read().split()
        pid = int(parts[0])
        start = int(parts[1]) if len(parts) > 1 else None
        return pid, start
    except Exception:
        return 0, None


def remove_lock() -> None:
    try:
        os.remove(lock_path())
    except OSError:
        pass


def kill_pid(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], creationflags=NO_WINDOW,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def close_previous() -> None:
    """Close an older copy of this program that is still open.

    A lock left by a crash is just removed. The old process is only closed when both its
    process id and its start time match the lock, so a different program that later got
    the same process id is never touched.
    """
    pid, start = read_lock()
    if not os.path.isfile(lock_path()):
        return
    if pid <= 0 or pid == os.getpid():
        remove_lock()
        return
    running = process_start(pid)
    if start is None or running is None or running != start:
        remove_lock()                              # stale lock from a crash / another program
        return
    kill_pid(pid)
    for _ in range(20):
        if process_start(pid) != start:
            break
        time.sleep(0.1)
    remove_lock()


def write_lock() -> None:
    try:
        with open(lock_path(), "w", encoding="utf-8") as fh:
            fh.write("%d %d" % (os.getpid(), process_start(os.getpid()) or 0))
    except OSError:
        pass


def clear_lock() -> None:
    if read_lock()[0] == os.getpid():
        remove_lock()


# ---------------------------------------------------------------------------
# UI pieces
# ---------------------------------------------------------------------------

def flat_button(master, text, command, **kw):
    opts = dict(bg=DARK_BTN, fg=TEXT_FG, activebackground=BTN_ACTIVE, activeforeground=TEXT_FG,
                relief="solid", bd=1, highlightthickness=0, font=("Segoe UI", 11), padx=12, pady=3)
    opts.update(kw)
    return tk.Button(master, text=text, command=command, **opts)


def fmt_limit(v: int) -> str:
    return "Inf" if v == INF else str(v)


def step_limit(v: int, delta: int) -> int:
    """Inf counts as -1: - on 0 goes to Inf, - on Inf stays, + on Inf goes to 0."""
    if delta < 0:
        return v if v == INF else (INF if v == 0 else v - 1)
    return 0 if v == INF else min(MAX_HOLD, v + 1)


def parse_limit(text: str, fallback: int) -> int:
    text = text.strip().lower()
    if text in ("", "inf", "-1", "\u221e"):
        return INF
    try:
        return max(0, min(MAX_HOLD, int(float(text))))
    except ValueError:
        return fallback


class LimitInput(tk.Frame):
    """- [value] + box with the same rules as the decal tiles (used next to Browse)."""

    def __init__(self, master, value: int = INF):
        super().__init__(master, bg=BG_COLOR)
        self.value = value
        opts = dict(width=2, bg=BTN_BG, fg=BTN_FG, activebackground=BTN_ACTIVE, relief="flat", bd=0,
                    font=("Segoe UI", 12, "bold"))
        minus = tk.Button(self, text="-", command=lambda: self.set(step_limit(self.value, -1)), **opts)
        minus.pack(side="left")
        minus.bind("<Button-3>", lambda e: self.set(0))
        self.var = tk.StringVar(value=fmt_limit(value))
        self.entry = tk.Entry(self, textvariable=self.var, width=4, justify="center", bg=ENTRY_BG, fg=TEXT_FG,
                              insertbackground=TEXT_FG, relief="solid", bd=1, highlightthickness=1,
                              highlightbackground=ENTRY_BD, highlightcolor=ENTRY_BD, font=("Segoe UI", 12))
        self.entry.pack(side="left", padx=4, ipady=2)
        self.entry.bind("<Return>", self.commit)
        self.entry.bind("<FocusOut>", self.commit)
        plus = tk.Button(self, text="+", command=lambda: self.set(step_limit(self.value, 1)), **opts)
        plus.pack(side="left")
        plus.bind("<Button-3>", lambda e: self.set(INF))

    def set(self, v: int) -> None:
        self.value = v
        self.var.set(fmt_limit(v))

    def commit(self, _event=None) -> None:
        self.set(parse_limit(self.var.get(), self.value))


class Tile(tk.Frame):
    def __init__(self, app, decal: dict):
        super().__init__(app.inner, bg=TILE_PAD, width=TILE_W, height=TILE_H)
        self.app = app
        self.d = decal
        self.sid = decal["id"]
        self.grid_propagate(False)
        self.pack_propagate(False)

        self.cv = tk.Canvas(self, width=TILE_IMG + 4, height=TILE_IMG + 4, bg=TILE_PAD,
                            highlightthickness=0, bd=0)
        self.cv.pack(pady=(6, 4))
        self.img_id = self.cv.create_image(2 + TILE_IMG // 2, 2 + TILE_IMG // 2)
        self.name_id = self.cv.create_text(
            2 + TILE_IMG // 2, 2 + TILE_IMG // 2, text=decal["name"], fill=TEXT_DIM,
            width=TILE_IMG - 10, font=("Segoe UI", 9), justify="center")
        self.stars_shadow = self.cv.create_text(3 + TILE_IMG // 2, TILE_IMG - 6, text="",
                                                fill="#000000", font=("Segoe UI", 12, "bold"))
        self.stars_id = self.cv.create_text(2 + TILE_IMG // 2, TILE_IMG - 7, text="",
                                            fill="#ffd54a", font=("Segoe UI", 12, "bold"))
        self.badge_bg = self.cv.create_rectangle(0, 0, 0, 0, fill="#000000", outline="", state="hidden")
        self.badge_id = self.cv.create_text(8, 10, text="", anchor="w", fill=TEXT_FG,
                                            font=("Segoe UI", 9, "bold"))
        self.cv.bind("<Button-1>", self.on_click)
        self.cv.bind("<Button-3>", lambda e: app.show_details(self))

        row = tk.Frame(self, bg=TILE_PAD)
        row.pack()
        self.btn_minus = tk.Button(row, text="-", width=2, command=lambda: self.step(-1),
                                   bg=BTN_BG, fg=BTN_FG, activebackground=BTN_ACTIVE,
                                   relief="flat", bd=0, font=("Segoe UI", 12, "bold"))
        self.btn_minus.pack(side="left")
        self.btn_minus.bind("<Button-3>", lambda e: self.set_limit(0))
        self.var = tk.StringVar()
        self.entry = tk.Entry(row, textvariable=self.var, width=4, justify="center",
                              bg=ENTRY_BG, fg=TEXT_FG, insertbackground=TEXT_FG, relief="solid", bd=1,
                              highlightthickness=1, highlightbackground=ENTRY_BD,
                              highlightcolor=ENTRY_BD, font=("Segoe UI", 12))
        self.entry.pack(side="left", padx=4, ipady=2)
        self.entry.bind("<Return>", self.commit_entry)
        self.entry.bind("<FocusOut>", self.commit_entry)
        self.btn_plus = tk.Button(row, text="+", width=2, command=lambda: self.step(1),
                                  bg=BTN_BG, fg=BTN_FG, activebackground=BTN_ACTIVE,
                                  relief="flat", bd=0, font=("Segoe UI", 12, "bold"))
        self.btn_plus.pack(side="left")
        self.btn_plus.bind("<Button-3>", lambda e: self.set_limit(INF))
        self.refresh()

    def on_click(self, _event=None):
        app = self.app
        now = time.time()
        if app._last_click == self.sid and now - app._last_click_t <= DOUBLE_CLICK:
            app._last_click = None
            app.fill_search(self.d["name"])
        else:
            app._last_click, app._last_click_t = self.sid, now

    @property
    def limit(self) -> int:
        return self.app.limits.get(self.sid, INF)

    def step(self, delta: int) -> None:
        v = step_limit(self.limit, delta)
        if v != self.limit:
            self.set_limit(v)

    def set_limit(self, v: int) -> None:
        self.app.set_limit(self.sid, v)
        self.refresh()

    def commit_entry(self, _event=None) -> None:
        v = parse_limit(self.var.get(), self.limit)
        if v != self.limit:
            self.set_limit(v)
        else:
            self.refresh()

    def refresh(self) -> None:
        app = self.app
        self.var.set(fmt_limit(self.limit))
        enabled = app.include.get(self.d["group"], True)
        photo = app.photo(self.d.get("icon"), grey=not enabled)
        if photo:
            self.cv.itemconfigure(self.img_id, image=photo, state="normal")
            self.cv.itemconfigure(self.name_id, state="hidden")
        else:
            self.cv.itemconfigure(self.img_id, state="hidden")
            self.cv.itemconfigure(self.name_id, state="normal")
        stars = "★" * int(self.d["stars"]) if app.settings.get("show_stars") else ""
        self.cv.itemconfigure(self.stars_id, text=stars)
        self.cv.itemconfigure(self.stars_shadow, text=stars)
        have = sum(app.owned.get(self.sid, (0, 0)))
        cap = self.limit
        if have or cap != INF:
            capped = cap == 0 or (cap > 0 and have >= cap)
            txt = "%d/%s" % (have, "∞" if cap == INF else cap)
            self.cv.itemconfigure(self.badge_id, text=txt, fill="#ff6b5e" if capped else "#8be28b")
            x1, y1, x2, y2 = self.cv.bbox(self.badge_id)
            self.cv.coords(self.badge_bg, x1 - 4, y1 - 2, x2 + 4, y2 + 2)
            self.cv.itemconfigure(self.badge_bg, state="normal")
            self.cv.tag_raise(self.badge_id)
        else:
            self.cv.itemconfigure(self.badge_id, text="")
            self.cv.itemconfigure(self.badge_bg, state="hidden")


class Dropdown(tk.Button):
    """Sort list drawn with Tk widgets (a native menu would drop the custom cursor)."""

    def __init__(self, master, app, values, var, command):
        super().__init__(master, text="", command=self.toggle, bg=DARK_BTN, fg="#e2e2e2",
                         activebackground=BTN_ACTIVE, activeforeground=TEXT_FG, relief="solid", bd=1,
                         highlightthickness=0, font=("Segoe UI", 12), anchor="w", padx=10, width=9)
        self.app, self.values, self.var, self.command = app, values, var, command
        self.menu = None
        self._show()

    def _show(self):
        self.configure(text="%s   \u25be" % self.var.get())

    def toggle(self):
        if self.menu:
            self.close()
        else:
            self.open()

    def open(self):
        m = self.menu = tk.Toplevel(self)
        m.overrideredirect(True)
        m.configure(bg="#444444")
        for i, v in enumerate(self.values):
            on = v == self.var.get()
            lab = tk.Label(m, text=v, bg=BTN_ACTIVE if on else DARK_BTN, fg=TEXT_FG, anchor="w",
                           font=("Segoe UI", 12), padx=10, pady=4)
            lab.pack(fill="x", padx=1, pady=(1, 1 if i == len(self.values) - 1 else 0))
            lab.bind("<Enter>", lambda e, l=lab: l.configure(bg=BTN_ACTIVE))
            lab.bind("<Leave>", lambda e, l=lab, v=v: l.configure(
                bg=BTN_ACTIVE if v == self.var.get() else DARK_BTN))
            lab.bind("<Button-1>", lambda e, v=v: self.pick(v))
        m.bind("<Escape>", lambda e: self.close())
        cur = cursor_file()
        if cur:
            apply_cursor(m, cur)
        m.update_idletasks()
        width = max(self.winfo_width(), m.winfo_reqwidth())
        m.geometry("%dx%d+%d+%d" % (width, m.winfo_reqheight(), self.winfo_rootx(),
                                    self.winfo_rooty() + self.winfo_height()))
        m.lift()
        self.app.click_handlers.append(self._outside)

    def _outside(self, event):
        if event.widget is not self:
            self.close()

    def pick(self, v):
        self.var.set(v)
        self._show()
        self.close()
        self.command()

    def close(self):
        if self._outside in self.app.click_handlers:
            self.app.click_handlers.remove(self._outside)
        if self.menu:
            try:
                self.menu.destroy()
            except tk.TclError:
                pass
            self.menu = None


class Popup(tk.Toplevel):
    """Small dark popup that closes when you click outside it."""

    def __init__(self, app, title: str, width: int, height: int):
        super().__init__(app.root)
        self.app = app
        self.title(title)
        self.configure(bg=PANEL)
        self.resizable(False, False)
        self.transient(app.root)
        x = app.root.winfo_rootx() + max(0, (app.root.winfo_width() - width) // 2)
        y = app.root.winfo_rooty() + max(0, (app.root.winfo_height() - height) // 3)
        self.geometry("%dx%d+%d+%d" % (width, height, x, y))
        apply_window_chrome(self)
        self.bind("<Escape>", lambda e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(50, self._arm)

    def _arm(self):
        try:
            self.focus_force()
        except tk.TclError:
            pass
        self.app.click_handlers.append(self._outside)

    def _outside(self, event):
        try:
            if event.widget.winfo_toplevel() is not self:
                self.close()
        except Exception:
            self.close()

    def close(self):
        if self._outside in self.app.click_handlers:
            self.app.click_handlers.remove(self._outside)
        if self.app.popup is self:
            self.app.popup = None
        self.destroy()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class App:
    def __init__(self):
        self.settings = load_settings()
        self.limits = load_limits()
        self.owned = {}
        self.db_odds = {}
        self.save_mtime = None
        self.save_pending = None
        self.game_is_running = False
        self.sha = "unknown"
        self.dirty = False
        self.popup = None
        self.capturing = False
        self.click_handlers = []
        self.fallback_active = False       # all maxed: the maxed decals are kept in the stew
        self._zero_warned = False
        self._last_click, self._last_click_t = None, 0.0
        self.art = {}
        self.photos = {}
        self.art_queue = queue.Queue()
        self.include = {"mushroom_lady": True,
                        "collab": bool(self.settings["include_collab"]),
                        "bags": bool(self.settings["include_lost_bag"])}

        self.root = tk.Tk()
        self.root.title("%s %s" % (APP_TITLE, VERSION))
        self.root.geometry("1000x900")
        self.root.minsize(700, 560)
        self.root.configure(bg=BG_COLOR)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        try:
            self.catalog = load_catalog()
            self.original_rows = load_original_odds()
        except Exception as exc:
            self.catalog, self.original_rows = [], []
            self.startup_error = str(exc)
        else:
            self.startup_error = ""
        self.original_ids = {r["sklid"] for r in self.original_rows}
        self.added = set()          # stew rows this program inserted (see ADDED_TABLE)
        self.paths = Paths(self.settings["steam_exe"], self.settings["save_file"])

        self._build_ui()
        apply_window_chrome(self.root)
        if self.settings["hotkey"] and sys.platform == "win32":
            install_hotkey(self.settings["hotkey"], self.root)

        if self.startup_error:
            self.log(self.startup_error)
        self.reload_all(first=True)
        if self.settings["bake_on_launch"] and self.dirty:
            # decals capped (or settings changed) while the program was closed
            self.log("Bake on launch: the stew is not up to date with your save.")
            self.bake()
        self.root.after(200, self.poll_save)
        self.root.after(100, self.poll_art)
        self.root.after(100, self.poll_hotkey)
        self.root.after(500, self.poll_game)
        self.root.bind("<FocusIn>", self._on_focus, add="+")
        self.root.bind("<Button-1>", self._on_any_click, add="+")
        self.root.bind("<Unmap>", lambda e: self.sort_menu.close(), add="+")
        self.root.bind("<Configure>", lambda e: e.widget is self.root and self.sort_menu.close(), add="+")

    def _on_any_click(self, event):
        # clicking anywhere that is not a text box ends typing in the box that had focus
        w = event.widget
        if not isinstance(w, (tk.Entry, tk.Text)):
            focused = self.root.focus_get()
            if isinstance(focused, tk.Entry):
                self.root.focus_set()
        for handler in list(self.click_handlers):
            handler(event)

    def _on_focus(self, event):
        # coming back from the SHA unlocker: look again (at most every 3 s, only while locked)
        if event.widget is self.root and not self.sha_ok and time.time() - getattr(self, "_sha_checked", 0) > 3:
            self.check_sha()

    # --- layout ------------------------------------------------------------
    # Header and footer are drawn on one canvas over the background art, so the
    # art shows behind the text the way the mockup has it.
    def _build_ui(self):
        root = self.root
        self.bg_src = None
        bg_path = find_asset(*ASSET_BG)
        if bg_path:
            try:
                from PIL import Image
                self.bg_src = Image.open(bg_path).convert("RGB")
            except Exception:
                self.bg_src = None
        cv = self.chrome = tk.Canvas(root, bg=BG_COLOR, highlightthickness=0, bd=0)
        cv.pack(fill="both", expand=True)
        self.bg_id = cv.create_image(0, 0, anchor="nw")
        self._bg_size = None

        # group checkboxes (drawn: outlined square, white inside when ticked)
        self.checks = {}
        x = 16
        for group, text in (("collab", "Collab"), ("bags", "Lost Bag")):
            tag = "chk_" + group
            box = cv.create_rectangle(x, ROW1 - 13, x + 26, ROW1 + 13, outline="#7f7f7f", width=2,
                                      fill="#030303", tags=tag)
            tick = cv.create_rectangle(x + 5, ROW1 - 8, x + 21, ROW1 + 8, outline="", fill="#ffffff", tags=tag)
            label = cv.create_text(x + 36, ROW1, anchor="w", text=text, fill="#a0a0a0",
                                   font=("Segoe UI", 14), tags=tag)
            cv.tag_bind(tag, "<Button-1>", lambda e, g=group: self.toggle_group(g))
            self.checks[group] = (box, tick, label)
            x = cv.bbox(label)[2] + 36

        self.var_sort = tk.StringVar(value=self.settings["sort"])
        self.sort_menu = Dropdown(cv, self, SORTS, self.var_sort, self.on_sort)
        self.sort_text_id = cv.create_text(0, ROW1, anchor="e", text="Sort:", fill="#a0a0a0",
                                           font=("Segoe UI", 14))
        self.sort_win = cv.create_window(0, ROW1, anchor="e", window=self.sort_menu)
        self.bake_btn = flat_button(cv, "Bake Stew", self.bake, font=("Segoe UI", 13), fg="#e2e2e2",
                                    highlightbackground="#444444")
        self.bake_win = cv.create_window(0, ROW1, anchor="e", window=self.bake_btn)

        cv.create_text(16, ROW2, anchor="w", text="Browse:", fill="#a0a0a0", font=("Segoe UI", 14))
        self.var_search = tk.StringVar()
        self.var_search.trace_add("write", lambda *_: self.apply_filter())
        self.search = tk.Entry(cv, textvariable=self.var_search, bg=ENTRY_BG, fg=TEXT_FG,
                               insertbackground=TEXT_FG, relief="solid", bd=1, highlightthickness=1,
                               highlightbackground="#999999", highlightcolor="#cccccc", font=("Segoe UI", 13))
        self.search_win = cv.create_window(100, ROW2, anchor="w", window=self.search, width=420, height=34)
        self.clear_btn = flat_button(cv, "✕", lambda: self.var_search.set(""), padx=8, pady=1)
        self.clear_win = cv.create_window(528, ROW2, anchor="w", window=self.clear_btn)
        self.clear_btn.bind("<Button-3>", lambda e: self.show_keywords())
        self.bulk = LimitInput(cv, INF)
        self.bulk_win = cv.create_window(570, ROW2, anchor="w", window=self.bulk)
        self.bulk_btn = flat_button(cv, "Set Browsed", self.set_browsed, font=("Segoe UI", 11), fg="#e2e2e2")
        self.bulk_btn_win = cv.create_window(700, ROW2, anchor="w", window=self.bulk_btn)
        self.count_id = cv.create_text(0, ROW2, anchor="e", text="", fill="#b0b0b0", font=("Segoe UI", 10))

        mid = tk.Frame(cv, bg="#030303", highlightthickness=1, highlightbackground="#999999")
        self.mid_win = cv.create_window(14, MID_TOP, anchor="nw", window=mid)
        self.canvas = tk.Canvas(mid, bg="#030303", highlightthickness=0, bd=0)
        self.scroll = tk.Scrollbar(mid, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg="#030303")
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        self.sep_id = cv.create_line(14, 0, 100, 0, fill="#232323", width=2, capstyle="round")
        self.msg = tk.Text(cv, height=4, bg=ENTRY_BG, fg=TEXT_FG, relief="solid", bd=1,
                           highlightthickness=1, highlightbackground="#333333", font=("Segoe UI", 10),
                           wrap="word", state="disabled", padx=8, pady=4)
        self.msg_win = cv.create_window(14, 0, anchor="sw", window=self.msg)
        self.msg.bind("<Button-3>", lambda e: self.clear_log())
        self.hk_id = cv.create_text(0, 0, anchor="se", text="", fill="#a0a0a0", font=("Segoe UI", 12),
                                    tags="hk")
        cv.tag_bind("hk", "<Button-1>", lambda e: self.start_capture())
        cv.tag_bind("hk", "<Button-3>", lambda e: self.clear_hotkey())
        self.refresh_btn = flat_button(cv, "Refresh", lambda: self.reload_all(manual=True), fg="#e2e2e2")
        self.settings_btn = flat_button(cv, "Settings", self.open_settings, fg="#e2e2e2")
        self.refresh_win = cv.create_window(0, 0, anchor="se", window=self.refresh_btn)
        self.settings_win = cv.create_window(0, 0, anchor="se", window=self.settings_btn)
        self._update_hotkey_label()
        self._paint_checks()

        cv.bind("<Configure>", self._on_chrome_resize)
        root.bind_all("<MouseWheel>", self._on_wheel)
        root.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        root.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))

        self.tiles = [Tile(self, d) for d in self.catalog]
        self.visible = list(self.tiles)
        self.columns = 0
        self.apply_filter()

    def _on_chrome_resize(self, event):
        w, h = max(1, event.width), max(1, event.height)
        cv = self.chrome
        m = 14
        cv.coords(self.bake_win, w - m, ROW1)
        bx = cv.bbox(self.bake_win)
        cv.coords(self.sort_win, (bx[0] if bx else w - 150) - 14, ROW1)
        sx = cv.bbox(self.sort_win)
        cv.coords(self.sort_text_id, (sx[0] if sx else w - 300) - 8, ROW1)
        bulk_w = self.bulk.winfo_reqwidth() + 8 + self.bulk_btn.winfo_reqwidth()
        sw = max(140, min(420, w - 100 - 46 - 16 - bulk_w - 120 - m))
        cv.itemconfigure(self.search_win, width=sw)
        x = 100 + sw + 8
        cv.coords(self.clear_win, x, ROW2)
        x += self.clear_btn.winfo_reqwidth() + 16
        cv.coords(self.bulk_win, x, ROW2)
        cv.coords(self.bulk_btn_win, x + self.bulk.winfo_reqwidth() + 8, ROW2)
        cv.coords(self.count_id, w - m, ROW2)
        foot = 104
        cv.coords(self.mid_win, m, MID_TOP)
        cv.itemconfigure(self.mid_win, width=w - 2 * m, height=max(120, h - MID_TOP - foot - 10))
        cv.coords(self.sep_id, m + 6, h - foot, w - m - 6, h - foot)
        cv.coords(self.settings_win, w - m, h - 12)
        sb = cv.bbox(self.settings_win)
        cv.coords(self.refresh_win, (sb[0] if sb else w - 120) - 10, h - 12)
        cv.coords(self.hk_id, w - m, h - 58)
        right = 250
        cv.coords(self.msg_win, m, h - 10)
        cv.itemconfigure(self.msg_win, width=max(200, w - 2 * m - right), height=foot - 22)
        if self.bg_src and (w, h) != self._bg_size:
            self._bg_size = (w, h)
            if getattr(self, "_bg_after", None):
                self.root.after_cancel(self._bg_after)
            self._bg_after = self.root.after(100, self._paint_bg)

    def _paint_bg(self):
        from PIL import ImageTk
        w, h = self._bg_size
        src = self.bg_src
        scale = max(w / src.width, h / src.height)
        img = src.resize((max(1, int(src.width * scale)), max(1, int(src.height * scale))), _lanczos())
        left, top = (img.width - w) // 2, (img.height - h) // 2
        self._bg_photo = ImageTk.PhotoImage(img.crop((left, top, left + w, top + h)))
        self.chrome.itemconfigure(self.bg_id, image=self._bg_photo)

    def _paint_checks(self):
        for group, (box, tick, label) in self.checks.items():
            on = self.include.get(group, True)
            self.chrome.itemconfigure(tick, state="normal" if on else "hidden")
            self.chrome.itemconfigure(label, fill="#d0d0d0" if on else "#8a8a8a")

    def toggle_group(self, group):
        self.include[group] = not self.include.get(group, True)
        self._paint_checks()
        self.on_groups()

    def _on_canvas_resize(self, event):
        self.canvas.itemconfigure(self.inner_id, width=event.width)
        cols = max(1, (event.width - 8) // (TILE_W + 10))
        if cols != self.columns:
            self.columns = cols
            self.layout()

    def _on_wheel(self, event):
        self.sort_menu.close()
        if self.popup is not None:
            return
        self.canvas.yview_scroll(int(-event.delta / 120) * 3, "units")

    def layout(self):
        for t in self.tiles:
            t.grid_forget()
        cols = max(1, self.columns or 5)
        for c in range(cols):
            self.inner.grid_columnconfigure(c, weight=1, uniform="tiles")
        for c in range(cols, 40):
            self.inner.grid_columnconfigure(c, weight=0, uniform="")
        for i, t in enumerate(self.visible):
            t.grid(row=i // cols, column=i % cols, padx=5, pady=5)
        self.chrome.itemconfigure(self.count_id, text="%d of %d decals" % (len(self.visible), len(self.tiles)))
        self.root.after_idle(lambda: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

    # --- messages ----------------------------------------------------------
    def log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.msg.configure(state="normal")
        self.msg.insert("end", "%s  %s\n" % (stamp, text))
        lines = int(self.msg.index("end-1c").split(".")[0])
        if lines > 200:
            self.msg.delete("1.0", "%d.0" % (lines - 200))
        self.msg.see("end")
        self.msg.configure(state="disabled")

    def clear_log(self) -> None:
        self.msg.configure(state="normal")
        self.msg.delete("1.0", "end")
        self.msg.configure(state="disabled")

    # --- art ---------------------------------------------------------------
    def start_art_loader(self):
        cooked = self.paths.cooked
        if not cooked or not os.path.isdir(cooked):
            return
        icons = [d.get("icon") for d in self.catalog if d.get("icon") and d.get("icon") not in self.art]
        icons = list(dict.fromkeys(icons))

        def work():
            for icon in icons:
                img = load_decal_art(cooked, icon)
                self.art_queue.put((icon, img))
            self.art_queue.put((None, None))

        threading.Thread(target=work, daemon=True).start()

    def poll_art(self):
        changed = set()
        try:
            for _ in range(40):
                icon, img = self.art_queue.get_nowait()
                if icon is None:
                    missing = sum(1 for d in self.catalog if not self.art.get(d.get("icon")))
                    if missing:
                        self.log("%d decal images could not be read from the game files." % missing)
                    continue
                self.art[icon] = img
                changed.add(icon)
        except queue.Empty:
            pass
        if changed:
            for t in self.tiles:
                if t.d.get("icon") in changed:
                    t.refresh()
        self.root.after(60, self.poll_art)

    def photo(self, icon, grey=False):
        if not icon or not self.art.get(icon):
            return None
        key = (icon, grey)
        if key not in self.photos:
            from PIL import ImageEnhance, ImageTk
            img = self.art[icon]
            if grey:
                g = img.convert("LA").convert("RGBA")
                g = ImageEnhance.Brightness(g).enhance(0.45)
                g.putalpha(img.getchannel("A"))
                img = g
            self.photos[key] = ImageTk.PhotoImage(img)
        return self.photos[key]

    # --- filter / sort -----------------------------------------------------
    def fill_search(self, text: str) -> None:
        self.var_search.set(text)

    def apply_filter(self):
        q = self.var_search.get().strip().lower() if hasattr(self, "var_search") else ""

        # "4 star" / "4 stars" / "4star" searches stars only; anything else searches names and ids
        star = re.fullmatch(r"([1-5])\s*stars?", q)
        owned_only = q == "owned"          # only the premium decals you have now
        pull_only = q in ("pull", "stew")  # only what the stew can give right now (odds > 0 in masters.db)

        def match(t):
            d = t.d
            if not q:
                return True
            if owned_only:
                return sum(self.owned.get(t.sid, (0, 0))) > 0
            if pull_only:
                return self.db_odds.get(t.sid, 0) > 0
            if star:
                return int(star.group(1)) == int(d["stars"])
            return q in d["name"].lower() or q in d["id"].lower()

        order = self.var_sort.get() if hasattr(self, "var_sort") else "Max val"

        def cap(t):
            return self.limits.get(t.sid, INF)

        # decals you have set a max on come first; Inf (no limit) ones go last
        if order == "Max val":
            key = lambda t: (cap(t) == INF, -cap(t), -t.d["stars"], t.d["name"].lower())
        elif order == "Min val":
            key = lambda t: (cap(t) == INF, cap(t), -t.d["stars"], t.d["name"].lower())
        elif order == "Owned":             # most owned first (inventory + equipped), then stars
            key = lambda t: (-sum(self.owned.get(t.sid, (0, 0))), -t.d["stars"], t.d["name"].lower())
        elif order == "Stars(+)":
            key = lambda t: (-t.d["stars"], t.d["name"].lower())
        else:
            key = lambda t: (t.d["stars"], t.d["name"].lower())
        self.visible = sorted((t for t in self.tiles if match(t)), key=key)
        self.layout()
        self.canvas.yview_moveto(0)

    def on_sort(self):
        self.settings["sort"] = self.var_sort.get()
        save_settings(self.settings)
        self.apply_filter()

    # --- limits / groups ---------------------------------------------------
    def set_limit(self, sid: str, v: int) -> None:
        if v == INF:
            self.limits.pop(sid, None)
        else:
            self.limits[sid] = v
        save_limits(self.limits)
        self.mark_dirty()

    def refilter_live(self):
        """Re-run Browse / Sort when they depend on the save or masters.db."""
        if (self.var_search.get().strip().lower() in ("owned", "pull", "stew")
                or self.var_sort.get() == "Owned"):
            self.apply_filter()

    def set_browsed(self):
        self.bulk.commit()
        v = self.bulk.value
        tiles = list(self.visible)
        if not tiles:
            self.log("Nothing to set: no decals match Browse.")
            return
        for t in tiles:
            if v == INF:
                self.limits.pop(t.sid, None)
            else:
                self.limits[t.sid] = v
            t.refresh()
        save_limits(self.limits)
        self.mark_dirty()
        q = self.var_search.get().strip()
        self.log("Max set to %s on %d decal%s%s." % (fmt_limit(v), len(tiles), "" if len(tiles) == 1 else "s",
                                                    ' matching "%s"' % q if q else " (all)"))

    def on_groups(self):
        self.settings["include_collab"] = self.include["collab"]
        self.settings["include_lost_bag"] = self.include["bags"]
        save_settings(self.settings)
        for t in self.tiles:
            if t.d["group"] in ("collab", "bags"):
                t.refresh()
        self.mark_dirty()

    def plan_odds(self):
        """-> (odds, mode). mode: 'normal', 'fallback' (all maxed: all of them stay obtainable)
        or 'none' (all set to 0)."""
        want = wanted_odds(self.catalog, self.limits, self.owned, self.include)
        if any(want.values()):
            return want, "normal"
        # every decal is at 0; the ones you still allow (max > 0, group ticked) are all maxed out
        pool = [d for d in self.catalog
                if self.include.get(d["group"], True) and self.limits.get(d["id"], INF) != 0
                and d["id"] in self.db_odds and d["id"] in self.writable() and int(d["stew_odds"]) > 0]
        if not pool:
            return want, "none"
        # the stew can't be empty (the game would hang): every maxed decal stays in at its normal
        # odds and the game picks among them
        for d in pool:
            want[d["id"]] = int(d["stew_odds"])
        return want, "fallback"

    def update_bake_button(self):
        ok = self.game_patched()
        self.bake_btn.configure(state="normal" if ok else "disabled")

    def mark_dirty(self):
        plan, mode = self.plan_odds()
        w = self.writable()
        self.dirty = self.game_patched() and mode != "none" and (
            any(v != self.db_odds[k] for k, v in plan.items() if k in w and k in self.db_odds)
            or any(k not in self.db_odds for k in plan))     # e.g. after Restore Decals
        self.bake_btn.configure(text="Bake Stew *" if self.dirty else "Bake Stew")
        self.update_bake_button()

    # --- state -------------------------------------------------------------
    def stew_patched(self) -> bool:
        """This program's decals are in the stew table."""
        return bool(self.added)

    def game_patched(self) -> bool:
        """Patch game done (SHA unlocked, exe patched): Bake Stew may run."""
        return self.sha_ok and self.exe_state() == "patched"

    def writable(self) -> set:
        """Stew rows this program may set odds on: the game's own and the ones it added."""
        return self.original_ids | self.added

    def exe_state(self) -> str:
        if not self.paths.exe or not os.path.isfile(self.paths.exe):
            return "missing"
        if self.sha == "locked":
            # SHA locked again = the unlocker put the Steam exe back, so this program's changes are gone
            return "steam"
        try:
            st = os.stat(self.paths.exe)
            key = (self.paths.exe, st.st_mtime_ns, st.st_size)
            if getattr(self, "_exe_cache", (None,))[0] != key:     # read the exe only when it changed
                self._exe_cache = (key, Exe(self.paths.exe).state())
            return self._exe_cache[1]
        except Exception:
            return "unknown"

    def reload_all(self, first=False, manual=False):
        self.paths = Paths(self.settings["steam_exe"], self.settings["save_file"])
        if not self.paths.game:
            self.log("Game not found. Open Settings and browse to steam.exe.")
        else:
            self.read_db()
            self.read_save(log_change=False)
            if first or manual:
                self.start_art_loader()
            if manual:
                self.log("Refreshed: %s" % self.summary())
        self.check_sha(announce=first or manual)
        for t in self.tiles:
            t.refresh()
        self.mark_dirty()
        if manual:
            self.apply_filter()             # Refresh: Browse and Sort again with the new data
        else:
            self.refilter_live()

    def check_sha(self, announce=False):
        before = self.sha
        self.sha = sha_state(self.paths.exe) if self.paths.exe else "unknown"
        self._sha_checked = time.time()
        if self.sha != "unlocked" and (announce or self.sha != before):
            self.log(SHA_LOCKED_MSG if self.sha == "locked"
                     else "Could not check SHA: the game exe was not found or could not be read.")
        elif self.sha == "unlocked" and before == "locked":
            self.log("SHA is unlocked.")
        self.update_bake_button()
        if isinstance(self.popup, SettingsPopup):
            self.popup.refresh_state()

    @property
    def sha_ok(self) -> bool:
        return self.sha == "unlocked"

    def summary(self) -> str:
        n_owned = sum(1 for d in self.catalog if sum(self.owned.get(d["id"], (0, 0))))
        n_pull = sum(1 for v in self.db_odds.values() if v > 0)
        return "%d decal%s can be pulled from the stew now, %d premium decals owned, stew %s, exe %s, SHA %s" % (
            n_pull, "" if n_pull == 1 else "s", n_owned, "patched" if self.game_patched() else "not patched",
            EXE_LABEL.get(self.exe_state(), self.exe_state()), self.sha)

    def read_db(self):
        if not self.paths.db or not os.path.isfile(self.paths.db):
            self.db_odds, self.added = {}, set()
            return
        try:
            self.db_odds = db_read_odds(self.paths.db)
            added = db_read_added(self.paths.db)
            if added is None:
                added = self.convert_v01()
            self.added = added & set(self.db_odds)
        except Exception as exc:
            self.log("Could not read masters.db: %s" % exc)

    def convert_v01(self) -> set:
        """A stew table patched by v0.1 (exe patched, Lost Bag / Collab rows, no list): take those
        rows as this program's and write the list, so v0.2 bakes and restores them as usual."""
        ours = {d["id"] for d in self.catalog} - self.original_ids
        rows = {sid for sid in self.db_odds if sid in ours}
        if not rows or self.exe_state() not in ("patched", "partial"):
            return set()
        db_adopt(self.paths.db, rows)
        self.log("Stew table from v0.1 converted: %d added decals recognised." % len(rows))
        return rows

    def read_save(self, log_change=True) -> bool:
        path = self.paths.save
        if not path or not os.path.isfile(path):
            if self.paths.game:
                self.log("brggame.sav not found. Set it in Settings.")
            return False
        try:
            raw, _meta = read_save(path)
            obj = json.loads(raw)
        except Exception:
            return False
        try:
            st = os.stat(path)
            self.save_mtime = (st.st_mtime_ns, st.st_size)
        except OSError:
            pass
        new = owned_counts(obj)
        ids = {d["id"] for d in self.catalog}
        old_c = {k: sum(v) for k, v in self.owned.items() if k in ids}
        new_c = {k: sum(v) for k, v in new.items() if k in ids}
        self.owned = new
        if log_change and old_c != new_c:
            gained = [k for k in new_c if new_c[k] > old_c.get(k, 0)]
            names = {d["id"]: d["name"] for d in self.catalog}
            if gained:
                self.log("Owned: " + ", ".join("%s x%d" % (names[k], new_c[k]) for k in gained))
            for t in self.tiles:
                t.refresh()
            self.refilter_live()
            if self.game_patched():
                self.bake(auto=True)
        return True

    # --- polling -----------------------------------------------------------
    def poll_save(self):
        path = self.paths.save
        try:
            if path and os.path.isfile(path):
                st = os.stat(path)
                cur = (st.st_mtime_ns, st.st_size)
                if cur != self.save_mtime:
                    if self.save_pending == cur:
                        if self.read_save():
                            self.save_pending = None
                    else:
                        self.save_pending = cur
        except OSError:
            pass
        self.root.after(700, self.poll_save)

    def poll_game(self):
        def work():
            running = game_running()
            self.root.after(0, lambda: self._set_running(running))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(3000, self.poll_game)

    def _set_running(self, running):
        if running != self.game_is_running:
            self.game_is_running = running
            if isinstance(self.popup, SettingsPopup):
                self.popup.refresh_state()

    def poll_hotkey(self):
        if consume_hotkey():
            self.toggle_ui()
        self.root.after(80, self.poll_hotkey)

    # --- bake --------------------------------------------------------------
    def bake(self, auto=False):
        if not self.sha_ok:
            if not auto:
                self.log(SHA_LOCKED_MSG)
            return
        if not self.paths.db or not os.path.isfile(self.paths.db):
            self.log("masters.db not found. Check Settings.")
            return
        self.read_db()
        if not self.game_patched():
            if not auto:
                self.log(NOT_PATCHED_MSG)
            self.update_bake_button()
            return
        if any(d["id"] not in self.db_odds for d in self.catalog):
            # e.g. decals added to premium_decals.json after Patch game: give them a row (odds 0) first
            try:
                db_add_missing(self.paths.db, self.catalog)
            except Exception as exc:
                self.log("Bake failed: %s" % exc)
                return
            self.read_db()
        want, mode = self.plan_odds()
        if mode == "none":
            # every decal set to 0 by your settings: masters.db is left as it is
            if not auto or not self._zero_warned:
                self.log(ALL_ZERO_MSG)
            self._zero_warned = True
            return
        self._zero_warned = False
        w = self.writable()
        in_stew = {k: v for k, v in want.items() if k in self.db_odds and k in w}
        if not any(in_stew.values()):
            self.log(ALL_ZERO_MSG)
            return
        if mode == "fallback":
            if not self.fallback_active or not auto:
                self.log(ALL_MAXED_MSG + ".")
        elif self.fallback_active:
            self.log("A decal is below its max again: the stew follows your settings again.")
        self.fallback_active = mode == "fallback"
        try:
            changed = db_write_odds(self.paths.db, in_stew)
        except DbBusy:
            self.log("masters.db is busy; try Bake Stew again in a moment.")
            return
        except Exception as exc:
            self.log("Bake failed: %s" % exc)
            return
        self.read_db()
        self.refilter_live()
        live = sum(1 for v in in_stew.values() if v)
        if changed or not auto:
            self.log("Stew baked: %d decal%s changed, %d can come out of the stew." % (
                changed, "" if changed == 1 else "s", live))
        if changed:
            self.log(REFRESH_HINT)
        self.mark_dirty()
        return changed

    # --- details / settings ------------------------------------------------
    def show_details(self, tile: Tile):
        if self.popup:
            self.popup.close()
        d = tile.d
        p = Popup(self, d["name"], 460, 420)
        self.popup = p
        box = tk.Frame(p, bg=PANEL)
        box.pack(fill="both", expand=True, padx=14, pady=12)
        head = tk.Frame(box, bg=PANEL)
        head.pack(fill="x")
        ph = self.photo(d.get("icon"))
        if ph:
            tk.Label(head, image=ph, bg=PANEL).pack(side="left", padx=(0, 12))
        tk.Label(head, text="%s\n%s" % (d["name"], "★" * int(d["stars"])), bg=PANEL, fg=TEXT_FG,
                 font=("Segoe UI", 14, "bold"), justify="left").pack(side="left", anchor="n")
        inv, eq = self.owned.get(d["id"], (0, 0))
        cap = self.limits.get(d["id"], INF)
        rows = [
            ("ID", d["id"]),
            ("From", GROUP_LABEL.get(d["group"], d["group"])
             + (" (%s)" % "/".join(d["bag_tiers"]) if d.get("bag_tiers") else "")),
            ("Category", d.get("category", "")),
            ("Owned", "%d (%d in inventory, %d equipped)" % (inv + eq, inv, eq)),
            ("Max", fmt_limit(cap)),
            ("Stew odds", "%s (in masters.db now: %s)" % (
                d["stew_odds"], self.db_odds.get(d["id"], "not in stew"))),
        ]
        grid = tk.Frame(box, bg=PANEL)
        grid.pack(fill="x", pady=(10, 6))
        for i, (k, v) in enumerate(rows):
            tk.Label(grid, text=k, bg=PANEL, fg=TEXT_DIM, font=("Segoe UI", 10)).grid(row=i, column=0, sticky="nw")
            tk.Label(grid, text=v, bg=PANEL, fg=TEXT_FG, font=("Segoe UI", 10), wraplength=320,
                     justify="left").grid(row=i, column=1, sticky="w", padx=10)
        tk.Label(box, text=d.get("description", ""), bg=PANEL, fg=TEXT_FG, font=("Segoe UI", 10),
                 wraplength=420, justify="left").pack(fill="x", pady=(6, 8))
        flat_button(box, "Close", p.close).pack(side="bottom", anchor="e")
        apply_window_chrome(p)

    def show_keywords(self):
        if self.popup:
            self.popup.close()
        p = Popup(self, "Browse keywords", 480, 300)
        self.popup = p
        box = tk.Frame(p, bg=PANEL)
        box.pack(fill="both", expand=True, padx=16, pady=12)
        tk.Label(box, text="Browse keywords", bg=PANEL, fg=TEXT_FG,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(0, 8))
        rows = [
            ("4 star / 4 stars", "only decals with that many stars (1-5)"),
            ("owned", "only premium decals you have now"),
            ("pull / stew", "only decals the stew can give right now"),
            ("anything else", "decal name or id"),
        ]
        grid = tk.Frame(box, bg=PANEL)
        grid.pack(fill="x")
        for i, (k, v) in enumerate(rows):
            tk.Label(grid, text=k, bg=PANEL, fg="#ffd54a", font=("Segoe UI", 11, "bold")).grid(
                row=i, column=0, sticky="w", pady=3)
            tk.Label(grid, text=v, bg=PANEL, fg=TEXT_FG, font=("Segoe UI", 10)).grid(
                row=i, column=1, sticky="w", padx=(14, 0), pady=3)
        tk.Label(box, text="Keywords must be the whole entry; upper/lower case does not matter.\n"
                           "LMB on \u2715 clears Browse.", bg=PANEL, fg=TEXT_DIM, font=("Segoe UI", 9),
                 justify="left", wraplength=440).pack(anchor="w", pady=(10, 0))
        flat_button(box, "Close", p.close).pack(side="bottom", anchor="e")
        apply_window_chrome(p)

    def open_settings(self):
        if self.popup:
            self.popup.close()
        self.popup = SettingsPopup(self)

    # --- patch / revert ----------------------------------------------------
    def patch_game(self) -> None:
        self.check_sha()
        if not self.sha_ok:
            self.log(SHA_LOCKED_MSG)
            return
        if game_running():
            self.log("Close the game first.")
            return
        p = self.paths
        if not p.ok():
            self.log("Game files not found. Check the Steam path.")
            return
        if not p.save:
            self.log("brggame.sav not found. Set it in Settings before patching.")
            return
        try:
            exe = Exe(p.exe)
            if exe.state() == "unknown":
                raise ExeError("the game exe is not the build this tool knows")
            raw, meta = read_save(p.save)
            new_save = empty_gacha_list(raw)
        except Exception as exc:
            self.log("Patch cancelled, nothing changed: %s" % exc)
            return
        done = []
        try:
            done += exe.patch()
            exe.save()
            added = db_add_missing(p.db, self.catalog)
            done.append("%d decals added to the stew" % added)
            if new_save is None:
                done.append("saved decal list already empty")
            else:
                write_save(p.save, new_save, meta)
                done.append("saved decal list emptied (%d entries)" % gacha_list_len(json.loads(raw)))
        except Exception as exc:
            self.log("Patch stopped part way: %s. Done so far: %s" % (exc, ", ".join(done) or "nothing"))
            self.reload_all()
            return
        self.log("Game patched: " + ", ".join(done) + ".")
        self.reload_all()
        self.bake()

    def revert_patch(self) -> None:
        # SHA locked again = the Steam exe is back, so only masters.db is left to revert
        self.check_sha()
        exe_too = self.sha_ok
        if game_running():
            self.log("Close the game first.")
            return
        p = self.paths
        if not p.ok():
            self.log("Game files not found. Check the Steam path.")
            return
        done = []
        try:
            removed = db_restore(p.db, self.original_rows, drop_list=True)
            done.append("%d added decals removed from the stew, original odds back" % removed)
            if exe_too:
                exe = Exe(p.exe)
                changes = exe.revert()
                if changes:
                    exe.save()
                done += changes
            else:
                done.append("exe left alone (SHA locked: it is the Steam exe)")
        except Exception as exc:
            self.log("Revert stopped part way: %s. Done so far: %s" % (exc, ", ".join(done) or "nothing"))
            self.reload_all()
            return
        self.log("Patch reverted: " + ", ".join(done) + ".")
        self.reload_all()

    def restore_decals(self) -> None:
        """masters.db only: remove the decals this program added, original odds back."""
        p = self.paths
        if not p.db or not os.path.isfile(p.db):
            self.log("masters.db not found. Check Settings.")
            return
        self.read_db()
        if not self.stew_patched():
            self.log("Nothing to restore: this program has not added any decals to the stew.")
            return
        try:
            removed = db_restore(p.db, self.original_rows, drop_list=False)
        except Exception as exc:
            self.log("Restore failed, nothing changed: %s" % exc)
            return
        self.log("Decals restored: %d added decals removed, the game's stew decals have their "
                 "original odds again. Decals not added by this program were left as they are. "
                 "Bake Stew puts your decals back." % removed)
        self.reload_all()

    # --- hotkey / window ---------------------------------------------------
    def _update_hotkey_label(self):
        hk = self.settings.get("hotkey") or "..."
        self.chrome.itemconfigure(self.hk_id, text="Shortcut: %s" % hk)

    def start_capture(self):
        self.capturing = True
        self.chrome.itemconfigure(self.hk_id, text="Shortcut: press a key")
        self.root.bind("<Key>", self._capture_key)

    def _capture_key(self, event):
        if not self.capturing:
            return
        ch = event.char
        if ch and len(ch) == 1 and ch.isprintable() and not ch.isspace():
            self.settings["hotkey"] = ch
            save_settings(self.settings)
            if sys.platform == "win32":
                install_hotkey(ch, self.root)
            self.log("Shortcut set to %s." % ch)
        self.capturing = False
        self.root.unbind("<Key>")
        self._update_hotkey_label()

    def clear_hotkey(self):
        self.settings["hotkey"] = ""
        save_settings(self.settings)
        uninstall_hotkey()
        self._update_hotkey_label()
        self.log("Shortcut removed.")

    def toggle_ui(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        else:
            if self.popup:
                self.popup.close()
            self.root.withdraw()

    def on_close(self):
        uninstall_hotkey()
        clear_lock()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


class SettingsPopup(Popup):
    def __init__(self, app: App):
        super().__init__(app, "Settings", 620, 520)
        box = tk.Frame(self, bg=PANEL)
        box.pack(fill="both", expand=True, padx=16, pady=14)
        lab = dict(bg=PANEL, fg=TEXT_DIM, font=("Segoe UI", 10))

        tk.Label(box, text="steam.exe", **lab).pack(anchor="w")
        row = tk.Frame(box, bg=PANEL)
        row.pack(fill="x", pady=(2, 8))
        self.var_steam = tk.StringVar(value=app.settings["steam_exe"])
        tk.Entry(row, textvariable=self.var_steam, state="readonly", readonlybackground=ENTRY_BG,
                 fg=TEXT_FG, relief="solid", bd=1, font=("Segoe UI", 10)).pack(side="left", fill="x",
                                                                               expand=True, ipady=3)
        flat_button(row, "Browse", self.browse_steam, font=("Segoe UI", 10)).pack(side="left", padx=(6, 0))

        tk.Label(box, text="Save file (brggame.sav)", **lab).pack(anchor="w")
        row = tk.Frame(box, bg=PANEL)
        row.pack(fill="x", pady=(2, 8))
        self.var_save = tk.StringVar(value=app.paths.save)
        tk.Entry(row, textvariable=self.var_save, state="readonly", readonlybackground=ENTRY_BG,
                 fg=TEXT_FG, relief="solid", bd=1, font=("Segoe UI", 10)).pack(side="left", fill="x",
                                                                               expand=True, ipady=3)
        flat_button(row, "Browse", self.browse_save, font=("Segoe UI", 10)).pack(side="left", padx=(6, 0))
        flat_button(row, "Auto", self.auto_save, font=("Segoe UI", 10)).pack(side="left", padx=(6, 0))

        self.info = tk.Label(box, text="", justify="left", anchor="w", bg=PANEL, fg=TEXT_FG,
                             font=("Consolas", 9), wraplength=580)
        self.info.pack(fill="x", pady=(4, 8))

        self.var_stars = tk.BooleanVar(value=app.settings["show_stars"])
        tk.Checkbutton(box, text="Show stars", variable=self.var_stars, command=self.on_stars,
                       bg=PANEL, fg=TEXT_FG, activebackground=PANEL, activeforeground=TEXT_FG,
                       selectcolor=ENTRY_BG, font=("Segoe UI", 11)).pack(anchor="w")
        # bake at program start when the stew no longer matches the save / your settings
        self.var_launch = tk.BooleanVar(value=app.settings["bake_on_launch"])
        tk.Checkbutton(box, text="Bake on launch", variable=self.var_launch, command=self.on_launch,
                       bg=PANEL, fg=TEXT_FG, activebackground=PANEL, activeforeground=TEXT_FG,
                       selectcolor=ENTRY_BG, font=("Segoe UI", 11)).pack(anchor="w")

        sha_row = tk.Frame(box, bg=PANEL)
        sha_row.pack(fill="x", pady=(10, 0))
        flat_button(sha_row, "Get SHA unlocker in Github", lambda: webbrowser.open(SHA_UNLOCKER_URL),
                    font=("Segoe UI", 10)).pack(side="left")
        flat_button(sha_row, "Check again", self.recheck_sha, font=("Segoe UI", 10)).pack(side="left", padx=(6, 0))

        foot = tk.Frame(box, bg=PANEL)
        foot.pack(side="bottom", fill="x")
        self.patch_btn = flat_button(foot, "Patch game", self.on_patch, font=("Segoe UI", 12))
        self.patch_btn.pack(side="left")
        self.restore_btn = flat_button(foot, "Restore Decals", self.on_restore, font=("Segoe UI", 12))
        self.restore_btn.pack(side="left", padx=(8, 0))
        self.patch_note = tk.Label(foot, text="", bg=PANEL, fg=TEXT_DIM, font=("Segoe UI", 9))
        self.patch_note.pack(side="left", padx=10)
        flat_button(foot, "Close", self.close, font=("Segoe UI", 11)).pack(side="right")
        self.refresh_state()
        apply_window_chrome(self)
        self.after(60, self._show_path_ends)

    def _show_path_ends(self):
        for child in self.winfo_children():
            for w in child.winfo_children():
                for e in w.winfo_children() if isinstance(w, tk.Frame) else []:
                    if isinstance(e, tk.Entry):
                        e.xview_moveto(1.0)

    def refresh_state(self):
        app = self.app
        p = app.paths
        lines = [
            "Game folder : %s" % (p.game or "not found"),
            "masters.db  : %s" % ("found" if p.db and os.path.isfile(p.db) else "not found"),
            "Save file   : %s" % ("found" if p.save else "not found"),
            "Stew table  : %d decals, %d added by this program" % (len(app.db_odds), len(app.added)),
            "Game exe    : %s" % EXE_LABEL.get(app.exe_state(), app.exe_state()),
            "Game        : %s" % ("running" if app.game_is_running else "closed"),
            "SHA         : %s" % {"unlocked": "unlocked", "locked": "locked (unlock it first)"}.get(
                app.sha, "could not check"),
        ]
        self.info.configure(text="\n".join(lines))
        # Revert once everything is patched; a partly patched exe gets "Patch game" first
        reverting = (app.sha_ok and app.exe_state() == "patched") or (not app.sha_ok and app.stew_patched())
        self.patch_btn.configure(text="Revert patch" if reverting else "Patch game")
        # Patch needs SHA unlocked; Revert still works while locked (masters.db only)
        blocked = app.game_is_running or not p.ok() or (not app.sha_ok and not reverting)
        self.patch_btn.configure(state="disabled" if blocked else "normal")
        note = ("close the game first" if app.game_is_running else
                "unlock SHA first" if not app.sha_ok and not reverting else
                "SHA locked: reverts masters.db only" if not app.sha_ok else "")
        self.patch_note.configure(text=note)
        self.restore_btn.configure(state="normal" if app.stew_patched() else "disabled")

    def recheck_sha(self):
        before = self.app.sha
        self.app.check_sha(announce=True)
        if self.app.sha_ok and before != "locked":
            self.app.log("SHA is unlocked.")
        self.refresh_state()

    def browse_steam(self):
        path = filedialog.askopenfilename(
            parent=self, title="Select steam.exe",
            filetypes=[("steam.exe / BrgGame-Steam.exe", "*.exe"), ("All files", "*.*")])
        if not path:
            return
        if not game_dir_from(path):
            self.app.log("LET IT DIE was not found from %s." % path)
            return
        self.app.settings["steam_exe"] = os.path.normpath(path)
        save_settings(self.app.settings)
        self.var_steam.set(self.app.settings["steam_exe"])
        self.app.reload_all(manual=True)
        self.var_save.set(self.app.paths.save)
        self.refresh_state()
        self._show_path_ends()

    def browse_save(self):
        path = filedialog.askopenfilename(parent=self, title="Select brggame.sav",
                                          filetypes=[("Save", "*.sav"), ("All files", "*.*")])
        if not path:
            return
        try:
            read_save(path)
        except Exception:
            self.app.log("That file is not a LET IT DIE save.")
            return
        self.app.settings["save_file"] = os.path.normpath(path)
        save_settings(self.app.settings)
        self.app.reload_all(manual=True)
        self.var_save.set(self.app.paths.save)
        self.refresh_state()

    def auto_save(self):
        self.app.settings["save_file"] = ""
        save_settings(self.app.settings)
        self.app.reload_all(manual=True)
        self.var_save.set(self.app.paths.save)
        self.refresh_state()

    def on_stars(self):
        self.app.settings["show_stars"] = bool(self.var_stars.get())
        save_settings(self.app.settings)
        for t in self.app.tiles:
            t.refresh()

    def on_launch(self):
        self.app.settings["bake_on_launch"] = bool(self.var_launch.get())
        save_settings(self.app.settings)

    def on_restore(self):
        self.app.restore_decals()
        self.refresh_state()

    def on_patch(self):
        if self.patch_btn.cget("text") == "Revert patch":
            self.app.revert_patch()
        else:
            self.app.patch_game()
        self.refresh_state()


def main() -> int:
    set_app_id()
    close_previous()
    write_lock()
    save_settings(load_settings())      # creates settings.ini, or brings an older one up to date
    try:
        App().run()
    finally:
        uninstall_hotkey()
        clear_lock()
    return 0


if __name__ == "__main__":
    sys.exit(main())
