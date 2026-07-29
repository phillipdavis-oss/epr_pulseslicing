#!/usr/bin/env python3
"""SpecMan4EPR TCPIP device server.

Single self-contained script, meant to run standalone on the Raspberry Pi.
SpecMan4EPR (the Windows PC) is the TCP client; this process listens, holds
one session at a time, and answers property reads/writes. See
specman_tcpip_server_spec.md for the full protocol writeup this implements.

Sections in this file:
    Packet          - wire format: encode/decode, framing, recv_exact
    Properties      - property table: index<->name/unit/direction/handshake,
                      range enforcement
    Devices         - hardware backends, bound to the property table as
                      getter/setter callbacks (only a mock backend is
                      included here; real hardware hooks in via --config
                      plus editing bind_backend() below)
    Server          - accept loop, connection lifecycle, handshake dispatch,
                      EOP staging/commit
    Self-test       - a loopback client for `--self-test`, so the server can
                      be sanity-checked without a real SpecMan install
    main            - CLI entry point
"""

from __future__ import annotations

import argparse
import json
import logging
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

logger = logging.getLogger("specman")

# =====================================================================
# Packet: wire format, framing
# =====================================================================
#
# All multi-byte fields are little-endian. No padding, no alignment.
#
# Simple packet (16 bytes):   int32 prop | uint32 flags | float64 value
# Large packet (12B header):  int32 prop | uint32 flags | int32 size | bytes

DF_NO_FLAGS = 0x00000000
DF_ERROR = 0x00010000
DF_HANDSHAKE = 0x40000000
DF_LARGE_PACKET = 0x80000000

# Special (negative) property numbers.
CMD_INIT = -500
CMD_DEINIT = -501
CMD_EOP = -1102

_HEADER = struct.Struct("<iI")       # prop, flags
_SIMPLE_VALUE = struct.Struct("<d")  # float64 value
_LARGE_SIZE = struct.Struct("<i")    # buffer size


class ConnectionClosed(Exception):
    """Raised when the peer closes the socket (a zero-length recv)."""


@dataclass
class Packet:
    prop: int
    flags: int
    value: Optional[float] = None
    buffer: Optional[bytes] = None

    @property
    def is_large(self) -> bool:
        return bool(self.flags & DF_LARGE_PACKET)

    @property
    def is_handshake(self) -> bool:
        return bool(self.flags & DF_HANDSHAKE)

    @property
    def is_error(self) -> bool:
        return bool(self.flags & DF_ERROR)

    def flags_hex(self) -> str:
        return f"0x{self.flags:08x}"


def recv_exact(recv: Callable[[int], bytes], n: int) -> bytes:
    """Read exactly n bytes from a `.recv(bufsize)`-shaped callable.

    Loops until n bytes are collected, since a single recv() may return a
    short read on a real TCP socket. A zero-length recv means the peer
    closed the connection - that is a disconnect, not a malformed packet.
    """
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = recv(remaining)
        if not chunk:
            raise ConnectionClosed("peer closed connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_packet(recv: Callable[[int], bytes]) -> Packet:
    """Read one full packet. Packet length is not fixed, so this must not
    blindly read 16 bytes - it reads the 8-byte header first and only then
    knows whether a fixed value or a variable-length buffer follows."""
    header = recv_exact(recv, _HEADER.size)
    prop, flags = _HEADER.unpack(header)

    if flags & DF_LARGE_PACKET:
        size_bytes = recv_exact(recv, _LARGE_SIZE.size)
        (size,) = _LARGE_SIZE.unpack(size_bytes)
        buffer = recv_exact(recv, size) if size > 0 else b""
        return Packet(prop=prop, flags=flags, buffer=buffer)

    value_bytes = recv_exact(recv, _SIMPLE_VALUE.size)
    (value,) = _SIMPLE_VALUE.unpack(value_bytes)
    return Packet(prop=prop, flags=flags, value=value)


def pack_simple(prop: int, flags: int, value: float) -> bytes:
    flags &= ~DF_LARGE_PACKET
    return _HEADER.pack(prop, flags) + _SIMPLE_VALUE.pack(value)


def pack_large(prop: int, flags: int, buffer: bytes) -> bytes:
    flags |= DF_LARGE_PACKET
    return _HEADER.pack(prop, flags) + _LARGE_SIZE.pack(len(buffer)) + buffer


def pack_error(prop: int, error_code: int, handshake: bool = True) -> bytes:
    """Build an error reply: dfError set, error code in the flag word's LSB."""
    flags = DF_ERROR | (error_code & 0xFFFF)
    if handshake:
        flags |= DF_HANDSHAKE
    return pack_simple(prop, flags, 0.0)


# =====================================================================
# Properties: index <-> name/unit/direction/handshake, range enforcement
# =====================================================================
#
# This table must be kept in sync with the SpecMan CFG file's par0=, par1=,
# ... entries by hand (spec section 6). Numbering is positional starting at
# par0=property 0. [UNVERIFIED against a live SpecMan install.]

READ = "read"
WRITE = "write"
RWRITE = "rwrite"
_DIRECTIONS = {READ, WRITE, RWRITE}

# Error codes returned in the LSB of the flag word (spec 4, "Error
# reporting"). Vocabulary is [UNVERIFIED] against real SpecMan behaviour -
# these are this server's own codes until confirmed against a live install.
ERR_UNKNOWN_PROPERTY = 1
ERR_OUT_OF_RANGE = 2
ERR_WRONG_DIRECTION = 3
ERR_NOT_ARMED = 4
ERR_INTERNAL = 5


class PropertyError(Exception):
    def __init__(self, message: str, error_code: int = ERR_INTERNAL):
        super().__init__(message)
        self.error_code = error_code


@dataclass
class PropertyDef:
    index: int
    name: str
    unit: str = ""
    direction: str = WRITE
    handshake: bool = True

    # Optional safety range. `on_out_of_range` decides whether an
    # out-of-range write is clamped into range or rejected with
    # ERR_OUT_OF_RANGE - reject is the spec's recommended default
    # (section 9: "reject and log ... unless clamping is the safer
    # failure mode for that specific parameter").
    min: Optional[float] = None
    max: Optional[float] = None
    on_out_of_range: str = "reject"  # "reject" | "clamp"

    # If set, a write is refused with ERR_NOT_ARMED unless this returns
    # True at write time (spec 9: no laser fire without a separate,
    # explicitly-armed enable).
    requires_armed: Optional[Callable[[], bool]] = None

    # Hardware backend hooks. Left unset, the property just reads back
    # whatever was last written (in-memory, useful for --dry-run/testing).
    getter: Optional[Callable[[], float]] = None
    setter: Optional[Callable[[float], float]] = None  # returns applied value

    def __post_init__(self):
        if self.direction not in _DIRECTIONS:
            raise ValueError(f"property {self.index}: invalid direction {self.direction!r}")

    def clamp_or_reject(self, value: float) -> float:
        lo, hi = self.min, self.max
        if lo is not None and value < lo:
            if self.on_out_of_range == "clamp":
                logger.warning("property %d (%s): clamping %s up to min %s", self.index, self.name, value, lo)
                return lo
            raise PropertyError(f"property {self.index} ({self.name}): {value} below min {lo}", ERR_OUT_OF_RANGE)
        if hi is not None and value > hi:
            if self.on_out_of_range == "clamp":
                logger.warning("property %d (%s): clamping %s down to max %s", self.index, self.name, value, hi)
                return hi
            raise PropertyError(f"property {self.index} ({self.name}): {value} above max {hi}", ERR_OUT_OF_RANGE)
        return value


class PropertyTable:
    """Index -> PropertyDef, plus an in-memory fallback store for properties
    with no bound hardware getter/setter (dry-run, unbacked reads)."""

    def __init__(self, properties: Dict[int, PropertyDef]):
        self._properties = properties
        self._store: Dict[int, float] = {}

    @classmethod
    def from_config(cls, config: dict) -> "PropertyTable":
        properties: Dict[int, PropertyDef] = {}
        for entry in config.get("properties", []):
            prop = PropertyDef(
                index=entry["index"],
                name=entry["name"],
                unit=entry.get("unit", ""),
                direction=entry.get("direction", WRITE),
                handshake=entry.get("handshake", True),
                min=entry.get("min"),
                max=entry.get("max"),
                on_out_of_range=entry.get("on_out_of_range", "reject"),
            )
            if prop.index in properties:
                raise ValueError(f"duplicate property index {prop.index}")
            properties[prop.index] = prop
        return cls(properties)

    def all(self) -> Dict[int, PropertyDef]:
        return dict(self._properties)

    def get(self, index: int) -> PropertyDef:
        try:
            return self._properties[index]
        except KeyError:
            raise PropertyError(f"unknown property {index}", ERR_UNKNOWN_PROPERTY) from None

    def bind(self, index: int, getter: Optional[Callable[[], float]] = None,
             setter: Optional[Callable[[float], float]] = None) -> None:
        """Wire a hardware backend's callbacks into an existing property."""
        prop = self.get(index)
        if getter is not None:
            prop.getter = getter
        if setter is not None:
            prop.setter = setter

    def read(self, index: int) -> float:
        prop = self.get(index)
        if prop.direction == WRITE:
            raise PropertyError(f"property {index} ({prop.name}) is write-only", ERR_WRONG_DIRECTION)
        if prop.getter is not None:
            return float(prop.getter())
        return float(self._store.get(index, 0.0))

    def write(self, index: int, value: float, dry_run: bool = False) -> float:
        prop = self.get(index)
        if prop.direction == READ:
            raise PropertyError(f"property {index} ({prop.name}) is read-only", ERR_WRONG_DIRECTION)
        if prop.requires_armed is not None and not prop.requires_armed():
            raise PropertyError(f"property {index} ({prop.name}) requires arming first", ERR_NOT_ARMED)

        value = prop.clamp_or_reject(float(value))

        if dry_run:
            logger.info("[dry-run] would set property %d (%s) = %s %s", index, prop.name, value, prop.unit)
            self._store[index] = value
            return value

        if prop.setter is not None:
            applied = float(prop.setter(value))
        else:
            applied = value
        self._store[index] = applied
        return applied


# =====================================================================
# Devices: hardware backends, injected as getter/setter callbacks
# =====================================================================
#
# Nothing above this section is hardware-specific. To wire in real
# hardware, write a class with the same bind_all(property_table) shape as
# MockDevice below - typically calling into cniAPI.py / vironAPI.py /
# delay_generator.py already in this repo - and select it in
# bind_backend() near main().


class MockDevice:
    """Stores whatever value was last written per property index and hands
    it back on read. No actual hardware I/O - used for --mock-device and
    --self-test."""

    def __init__(self):
        self._values: Dict[int, float] = {}

    def getter(self, index: int) -> Callable[[], float]:
        def _get() -> float:
            return self._values.get(index, 0.0)
        return _get

    def setter(self, index: int) -> Callable[[float], float]:
        def _set(value: float) -> float:
            logger.info("mock device: property %d <- %s", index, value)
            self._values[index] = value
            return value
        return _set

    def bind_all(self, property_table: PropertyTable) -> None:
        for index, prop in property_table.all().items():
            if prop.direction in (READ, RWRITE):
                property_table.bind(index, getter=self.getter(index))
            if prop.direction in (WRITE, RWRITE):
                property_table.bind(index, setter=self.setter(index))


class DelayGeneratorBackend:
    """Drives a Greenfield Technology GFT1004 digital delay generator over
    raw ASCII TCP (NUT007 Ed.13 4.2), matching the command set used by the
    working GUI in 682026_fullcontrol.py.

    Every property write recomputes and re-pushes the entire ten-channel
    state (TRIG, WIDTH, DELAY) in fixed channel order. SpecMan only sends a
    property when that property's sweep axis advances, so most experiment
    points touch exactly one of the five bound properties - pushing only the
    changed channel would leave the rest of the chain holding stale values.
    Re-pushing everything makes the instrument state a pure function of the
    backend's held parameters rather than of which subset SpecMan happened
    to send.

    Units: held state (self._params, chain dict) is picoseconds throughout.
    DELAY on the wire is picoseconds; WIDTH on the wire is nanoseconds - do
    not share a conversion helper between the two.
    """

    HOST_DEFAULT = "192.168.103.22"
    PORT_DEFAULT = 4000

    TRIG_MODE = "EXT"
    # Fixed per-channel widths, ns. T2/T3/T8/T9 are the long Q-switch /
    # tail-end windows; everything else is a short reference/chain pulse.
    WIDTH_NS = {
        0: 500, 1: 500, 2: 100_000, 3: 100_000, 4: 500,
        5: 500, 6: 500, 7: 500, 8: 100_000, 9: 100_000,
    }

    # T1/T2/T3 are fixed offsets back from ADV, in picoseconds.
    PRETRIGGER_OFFSET_PS = 244 * 1_000_000  # 244 us laser pretrigger
    QSDELAY_OFFSET_PS = 179 * 1_000_000     # 179 us, matches $QSDELAY 179

    MAX_DELAY_PS = 9_999_999_999_999

    REQUIRED_NAMES = ("pulseLen1", "pulseLen2", "pulseLen3", "delay1", "delay2")
    NAME_TO_PARAM = {
        "pulseLen1": "P1", "pulseLen2": "P2", "pulseLen3": "P3",
        "delay1": "S1", "delay2": "S2",
    }

    MAX_PUSH_ATTEMPTS = 2

    def __init__(self, host: str = HOST_DEFAULT, port: int = PORT_DEFAULT, *,
                 adv_ps: float, timeout: float = 2.0, command_delay: float = 0.02,
                 dry_run: bool = False, verify_after_push: bool = False):
        self.host = host
        self.port = port
        self._adv_ps = adv_ps
        self.timeout = timeout
        self.command_delay = command_delay
        self.dry_run = dry_run
        self.verify_after_push = verify_after_push

        self.sock: Optional[socket.socket] = None
        self._reconnect_count = 0
        # Held state, picoseconds, intervals in the delay chain (not
        # absolute delays) - see _compute_chain.
        self._params: Dict[str, float] = {"P1": 0.0, "P2": 0.0, "P3": 0.0, "S1": 0.0, "S2": 0.0}

    # -- chain math ------------------------------------------------------

    def _compute_chain(self, params: Optional[Dict[str, float]] = None) -> Dict[int, float]:
        p = params if params is not None else self._params
        t4 = self._adv_ps
        t5 = t4 + p["P1"]
        t6 = t5 + p["S1"]
        t7 = t6 + p["P2"]
        t8 = t7 + p["S2"]
        t9 = t8 + p["P3"]
        return {
            1: self._adv_ps - self.PRETRIGGER_OFFSET_PS,
            2: self._adv_ps - self.QSDELAY_OFFSET_PS,
            3: self._adv_ps - self.QSDELAY_OFFSET_PS,
            4: t4, 5: t5, 6: t6, 7: t7, 8: t8, 9: t9,
        }

    def _validate_chain(self, chain: Dict[int, float]) -> None:
        for ch in range(1, 10):
            val = chain[ch]
            if val < 0:
                logger.warning("delay generator: T%d computed delay %.0f ps is negative", ch, val)
                raise PropertyError(
                    f"delay generator: T{ch} delay {val:.0f} ps is negative", ERR_OUT_OF_RANGE)
            if val > self.MAX_DELAY_PS:
                logger.warning(
                    "delay generator: T%d computed delay %.0f ps exceeds max %d ps",
                    ch, val, self.MAX_DELAY_PS)
                raise PropertyError(
                    f"delay generator: T{ch} delay {val:.0f} ps exceeds max {self.MAX_DELAY_PS} ps",
                    ERR_OUT_OF_RANGE)
        for a, b in zip(range(4, 9), range(5, 10)):
            if chain[a] > chain[b]:
                logger.warning(
                    "delay generator: chain non-monotonic T%d (%.0f ps) > T%d (%.0f ps)",
                    a, chain[a], b, chain[b])
                raise PropertyError(
                    f"delay generator: chain non-monotonic T{a} > T{b}", ERR_OUT_OF_RANGE)

    # -- socket lifecycle --------------------------------------------------
    #
    # self.sock is assigned only after connect() succeeds - the inherited
    # implementation in 682026_fullcontrol.py assigns the socket object
    # before connecting, so a failed connect leaves a dead-but-truthy socket
    # behind and every `if not self.sock` guard downstream passes anyway.

    def _connect(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((self.host, self.port))
        except OSError:
            sock.close()
            self.sock = None
            raise
        self.sock = sock
        logger.info("delay generator: connected to %s:%d", self.host, self.port)

    def _ensure_connected(self) -> None:
        if self.dry_run or self.sock is not None:
            return
        self._connect()

    def _close_socket(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def close(self) -> None:
        """Wired to SpecmanServer.on_disconnect - closes the delay generator
        socket cleanly when a SpecMan session ends."""
        self._close_socket()

    # -- wire I/O ----------------------------------------------------------

    def _send_line(self, line: str) -> None:
        if self.dry_run:
            logger.info("[dg dry-run] %s", line)
            return
        self.sock.sendall((line + "\n").encode("ascii"))
        logger.debug("dg -> %s", line)

    def _query(self, command: str) -> Optional[str]:
        """Accumulate-until-timeout read, tolerant of \\n or \\r\\n. The
        GFT1004's actual response terminator is not documented and has not
        been confirmed on this unit, so raw bytes are logged at DEBUG rather
        than asserting a terminator nobody has verified."""
        if self.dry_run:
            logger.info("[dg dry-run] query %s", command)
            return None
        self._send_line(command)
        buf = b""
        deadline = time.monotonic() + self.timeout
        self.sock.settimeout(0.05)
        try:
            while time.monotonic() < deadline:
                try:
                    chunk = self.sock.recv(1024)
                except socket.timeout:
                    if buf:
                        break
                    continue
                if not chunk:
                    break
                buf += chunk
                if buf.endswith(b"\n"):
                    break
        finally:
            self.sock.settimeout(self.timeout)
        logger.debug("dg <- raw bytes: %r", buf)
        return buf.decode("ascii", errors="replace").replace("\r\n", "\n").strip("\n")

    # -- push ----------------------------------------------------------

    def _push_all_once(self, chain: Dict[int, float]) -> None:
        for ch in range(10):
            self._send_line(f"TRIG T{ch},{self.TRIG_MODE}")
            time.sleep(self.command_delay)
        for ch in range(10):
            self._send_line(f"WIDTH T{ch},{self.WIDTH_NS[ch]}")
            time.sleep(self.command_delay)
        for ch in range(1, 10):  # DELAY does not accept channel 0
            self._send_line(f"DELAY T{ch},{int(round(chain[ch]))}")
            time.sleep(self.command_delay)
        if self.verify_after_push:
            self._verify(chain)

    def _verify(self, chain: Dict[int, float]) -> None:
        for ch in range(1, 10):
            expected = int(round(chain[ch]))
            reply = self._query(f"DELAY? T{ch}")
            if not reply:
                logger.warning("delay generator: no reply verifying T%d", ch)
                continue
            try:
                actual = int(reply.rsplit(",", 1)[-1])
            except ValueError:
                logger.warning("delay generator: could not parse verify reply for T%d: %r", ch, reply)
                continue
            if actual != expected:
                logger.warning(
                    "delay generator: verify mismatch T%d expected %d ps got %d ps", ch, expected, actual)

    def _push_all(self) -> None:
        # Trigger source is not retained across a power cycle (manual,
        # NUT007), and a dropped connection can't be distinguished from a
        # power cycle from the socket alone - so every push re-sends TRIG on
        # all ten channels, not just DELAY.
        chain = self._compute_chain()
        self._validate_chain(chain)
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.MAX_PUSH_ATTEMPTS + 1):
            try:
                self._ensure_connected()
                self._push_all_once(chain)
                return
            except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError) as exc:
                last_exc = exc
                self._reconnect_count += 1
                logger.warning(
                    "delay generator: connection error on attempt %d/%d (%s); reconnecting "
                    "(reconnect count=%d)",
                    attempt, self.MAX_PUSH_ATTEMPTS, exc, self._reconnect_count,
                )
                self._close_socket()
        raise PropertyError(
            f"delay generator: push failed after {self.MAX_PUSH_ATTEMPTS} attempts: {last_exc}",
            ERR_INTERNAL,
        )

    # -- unused in this task (external trigger only); provided for
    # completeness since the instrument supports them -----------------

    def set_amplitude(self, channel: int, millivolts: int) -> None:
        self._send_line(f"AMPL T{channel},{int(millivolts)}")

    def set_int_freq(self, fn: int, hz: int) -> None:
        self._send_line(f"FREQ F{fn},{int(hz)}")

    # -- SpecMan bindings ------------------------------------------------

    def setter(self, param_name: str) -> Callable[[float], float]:
        def _set(value_ns: float) -> float:
            value_ps = value_ns * 1000.0  # all five bound properties are ns
            trial = dict(self._params)
            trial[param_name] = value_ps
            chain = self._compute_chain(trial)
            self._validate_chain(chain)
            self._params = trial  # only commit once validation has passed
            self._push_all()
            return value_ns
        return _set

    def bind_all(self, property_table: PropertyTable) -> None:
        # Bind by name, not index: the CFG file's property indices and
        # DEFAULT_CONFIG's are known to disagree on occasion, and because
        # every index in question exists in both tables a mismatch produces
        # no error - it just lands writes on the wrong DG channel. Binding
        # by name plus a startup dump makes that drift visible immediately.
        by_name: Dict[str, int] = {}
        for index, prop in property_table.all().items():
            by_name[prop.name] = index

        logger.info("delay generator: resolved property table (index, name, unit, direction, handshake):")
        for index, prop in sorted(property_table.all().items()):
            logger.info(
                "  %2d  %-14s unit=%-4s direction=%-7s handshake=%s",
                index, prop.name, prop.unit, prop.direction, prop.handshake,
            )

        logger.warning(
            "delay generator: TRIG will be set to EXT on all ten channels, including T1/T2/T3 "
            "(laser pretrigger/Q-switch) - the T-channel-to-laser BNC cabling map is UNCONFIRMED. "
            "Verify cabling and laser state before the external trigger line goes live."
        )

        missing = [name for name in self.REQUIRED_NAMES if name not in by_name]
        if missing:
            raise ValueError(
                f"delay generator: required properties {missing} not found in property table; "
                f"available names: {sorted(by_name)}"
            )

        for name, param in self.NAME_TO_PARAM.items():
            property_table.bind(by_name[name], setter=self.setter(param))


# =====================================================================
# Server: accept loop, connection lifecycle, handshake dispatch
# =====================================================================


class SpecmanServer:
    def __init__(self, host: str, port: int, property_table: PropertyTable,
                 dry_run: bool = False, on_disconnect: Optional[Callable[[], None]] = None):
        self.host = host
        self.port = port
        self.property_table = property_table
        self.dry_run = dry_run
        # Optional callback invoked whenever a session ends (deinit, drop, or
        # error) - a hook for backends to put hardware into a safe state
        # (spec section 5.7's watchdog).
        self.on_disconnect = on_disconnect

    # -- lifecycle ---------------------------------------------------

    def serve_forever(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listen_sock:
            listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listen_sock.bind((self.host, self.port))
            listen_sock.listen(1)
            logger.info("listening on %s:%d", self.host, self.port)

            while True:
                conn, addr = listen_sock.accept()
                logger.info("connection from %s", addr)
                try:
                    self._handle_connection(conn)
                except Exception:
                    logger.exception("connection handler crashed")
                finally:
                    conn.close()
                    logger.info("connection from %s closed", addr)
                    if self.on_disconnect is not None:
                        try:
                            self.on_disconnect()
                        except Exception:
                            logger.exception("on_disconnect hook raised")

    # -- per-connection loop ------------------------------------------

    def _handle_connection(self, conn: socket.socket) -> None:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        staged: Dict[int, float] = {}

        while True:
            try:
                p = read_packet(conn.recv)
            except ConnectionClosed:
                logger.info("peer disconnected")
                return

            logger.debug("<- prop=%d flags=%s value=%r", p.prop, p.flags_hex(), p.value)

            if p.prop == CMD_DEINIT:
                logger.info("received de-init (-501); no reply, closing")
                return

            if p.prop == CMD_INIT:
                self._reply_echo(conn, p)
                continue

            if p.prop == CMD_EOP:
                self._commit_staged(conn, p, staged)
                staged.clear()
                continue

            if p.is_handshake:
                self._handle_handshake_property(conn, p)
            else:
                # dfNoFlags: buffer for the next EOP barrier, no reply.
                staged[p.prop] = p.value

    # -- reply helpers -------------------------------------------------

    def _send(self, conn: socket.socket, prop: int, flags: int, value: float) -> None:
        logger.debug("-> prop=%d flags=0x%08x value=%r", prop, flags, value)
        conn.sendall(pack_simple(prop, flags, value))

    def _reply_echo(self, conn: socket.socket, p: Packet) -> None:
        # -500 init and the -1102 EOP barrier both echo the packet back.
        self._send(conn, p.prop, p.flags, p.value if p.value is not None else 0.0)

    def _send_error(self, conn: socket.socket, prop: int, error_code: int) -> None:
        flags = DF_HANDSHAKE | DF_ERROR | (error_code & 0xFFFF)
        logger.warning("-> error prop=%d code=%d", prop, error_code)
        conn.sendall(pack_simple(prop, flags, 0.0))

    def _handle_handshake_property(self, conn: socket.socket, p: Packet) -> None:
        try:
            prop_def = self.property_table.get(p.prop)
            if prop_def.direction == READ:
                value = self.property_table.read(p.prop)
            else:  # WRITE or RWRITE - see spec 4's [UNVERIFIED] note on
                # how rwrite disambiguates a read from a write of 0.0.
                value = self.property_table.write(p.prop, p.value, dry_run=self.dry_run)
        except PropertyError as exc:
            logger.warning("property error on prop=%d: %s", p.prop, exc)
            self._send_error(conn, p.prop, exc.error_code)
            return
        self._send(conn, p.prop, DF_HANDSHAKE, value)

    def _commit_staged(self, conn: socket.socket, eop_packet: Packet, staged: Dict[int, float]) -> None:
        logger.info("EOP barrier: committing %d staged value(s)", len(staged))
        first_error: Optional[PropertyError] = None
        for index, value in staged.items():
            try:
                self.property_table.write(index, value, dry_run=self.dry_run)
            except PropertyError as exc:
                logger.warning("EOP commit: property %d rejected: %s", index, exc)
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            self._send_error(conn, eop_packet.prop, first_error.error_code)
            return
        self._reply_echo(conn, eop_packet)


# =====================================================================
# Self-test: a loopback client speaking the SpecMan side of the protocol,
# so the server can be sanity-checked on the Pi without a real SpecMan
# install. Not a substitute for a real unit test suite - just enough to
# catch "the server doesn't even come up" / "handshakes are broken" before
# plugging in the real driver.
# =====================================================================


class _LoopbackClient:
    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def close(self) -> None:
        self.sock.close()

    def _send(self, prop: int, flags: int, value: float) -> None:
        self.sock.sendall(pack_simple(prop, flags, value))

    def _recv(self) -> Packet:
        return read_packet(self.sock.recv)

    def init(self) -> Packet:
        self._send(CMD_INIT, DF_HANDSHAKE, 0.0)
        return self._recv()

    def deinit(self) -> None:
        self._send(CMD_DEINIT, DF_NO_FLAGS, 0.0)

    def write(self, prop: int, value: float) -> Packet:
        self._send(prop, DF_HANDSHAKE, value)
        return self._recv()

    def read(self, prop: int) -> Packet:
        self._send(prop, DF_HANDSHAKE, 0.0)
        return self._recv()

    def write_no_reply(self, prop: int, value: float) -> None:
        self._send(prop, DF_NO_FLAGS, value)

    def eop_barrier(self) -> Packet:
        self._send(CMD_EOP, DF_HANDSHAKE, 0.0)
        return self._recv()


def run_self_test(host: str, port: int, property_table: PropertyTable) -> bool:
    """Starts a server on a background thread, drives it through
    init/write/read/EOP/deinit using the given property table, and reports
    pass/fail. Returns True on success."""
    server = SpecmanServer(host, port, property_table, dry_run=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)  # let the listen socket come up

    writable = [p for p in property_table.all().values() if p.direction in (WRITE, RWRITE)]
    readable = [p for p in property_table.all().values() if p.direction in (READ, RWRITE)]

    ok = True
    client = _LoopbackClient(host, port)
    try:
        reply = client.init()
        if not (reply.prop == CMD_INIT and reply.is_handshake and not reply.is_error):
            logger.error("self-test: init handshake failed: %r", reply)
            ok = False
        else:
            logger.info("self-test: init OK")

        if writable:
            prop = writable[0]
            value = 0.0
            if prop.min is not None and prop.max is not None:
                value = (prop.min + prop.max) / 2
            reply = client.write(prop.index, value)
            if reply.is_error:
                logger.error("self-test: write to property %d failed: error code %d",
                             prop.index, reply.flags & 0xFFFF)
                ok = False
            else:
                logger.info("self-test: write property %d (%s) = %s -> applied %s",
                            prop.index, prop.name, value, reply.value)
        else:
            logger.info("self-test: no writable properties in config, skipping write check")

        if readable:
            prop = readable[0]
            reply = client.read(prop.index)
            if reply.is_error:
                logger.error("self-test: read of property %d failed: error code %d",
                             prop.index, reply.flags & 0xFFFF)
                ok = False
            else:
                logger.info("self-test: read property %d (%s) -> %s", prop.index, prop.name, reply.value)
        else:
            logger.info("self-test: no readable properties in config, skipping read check")

        if len(writable) >= 1:
            for prop in writable[:2]:
                client.write_no_reply(prop.index, 1.0)
            reply = client.eop_barrier()
            if reply.is_error:
                logger.error("self-test: EOP commit failed: error code %d", reply.flags & 0xFFFF)
                ok = False
            else:
                logger.info("self-test: EOP staged commit OK")

        client.deinit()
    finally:
        client.close()

    return ok


# =====================================================================
# main
# =====================================================================

DEFAULT_CONFIG = {
    "host": "0.0.0.0",
    "port": 50001,
    "properties": [
        {"index": 0, "name": "numPulses",   "unit": "",    "direction": "write", "handshake": True, "min": 1,   "max": 3},
        {"index": 1, "name": "delay1",      "unit": "ns",  "direction": "write", "handshake": True, "min": 0.0, "max": 1e9},
        {"index": 3, "name": "delay2",      "unit": "ns",  "direction": "write", "handshake": True, "min": 0.0, "max": 1e4},
        {"index": 5, "name": "delay3",      "unit": "ns",  "direction": "write", "handshake": True, "min": 0.0, "max": 1e4},
        {"index": 2, "name": "pulseLen1",   "unit": "ns",  "direction": "write", "handshake": True, "min": 0.0, "max": 1e3},
        {"index": 4, "name": "pulseLen2",   "unit": "ns",  "direction": "write", "handshake": True, "min": 0.0, "max": 1e3},
        {"index": 6, "name": "pulseLen3",   "unit": "ns",  "direction": "write", "handshake": True, "min": 0.0, "max": 1e3},
        {"index": 7, "name": "phaseShift1", "unit": "deg", "direction": "write", "handshake": True, "min": 0.0, "max": 360.0},
        {"index": 8, "name": "phaseShift2", "unit": "deg", "direction": "write", "handshake": True, "min": 0.0, "max": 360.0},
    ],
}


def bind_backend(property_table: PropertyTable, args: argparse.Namespace) -> Optional[DelayGeneratorBackend]:
    """Wire a hardware backend into the property table. Returns the backend
    instance if one needs a lifecycle hook (e.g. DelayGeneratorBackend.close
    on disconnect), else None."""
    if args.delay_generator and args.mock_device:
        raise ValueError(
            "--delay-generator and --mock-device are mutually exclusive; "
            "pick one backend rather than letting one silently overwrite the other's bindings"
        )

    if args.delay_generator:
        backend = DelayGeneratorBackend(
            host=args.dg_host,
            port=args.dg_port,
            adv_ps=args.dg_adv_ms * 1e9,  # 1 ms = 1e9 ps
            timeout=args.dg_timeout,
            command_delay=args.dg_command_delay,
            dry_run=args.dg_dry_run,
        )
        backend.bind_all(property_table)
        return backend
    elif args.mock_device:
        MockDevice().bind_all(property_table)
    elif not args.dry_run:
        logger.warning(
            "no hardware backend bound (pass --mock-device, --delay-generator, or --dry-run); "
            "properties will just echo the in-memory store"
        )
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="SpecMan4EPR TCPIP device server")
    parser.add_argument("--config", default=None,
                         help="path to a property-table JSON config (default: built-in example table)")
    parser.add_argument("--host", default=None, help="override host from config")
    parser.add_argument("--port", type=int, default=None, help="override port from config")
    parser.add_argument("--dry-run", action="store_true",
                         help="log property writes instead of touching hardware")
    parser.add_argument("--mock-device", action="store_true",
                         help="bind an in-memory MockDevice instead of real hardware")
    parser.add_argument("--delay-generator", action="store_true",
                         help="bind a real GFT1004 delay generator backend")
    parser.add_argument("--dg-host", default=None,
                         help=f"delay generator host (default: {DelayGeneratorBackend.HOST_DEFAULT} or config)")
    parser.add_argument("--dg-port", type=int, default=None,
                         help=f"delay generator port (default: {DelayGeneratorBackend.PORT_DEFAULT} or config)")
    parser.add_argument("--dg-adv-ms", type=float, default=None,
                         help="ADV, in milliseconds (default: 16.625 or config)")
    parser.add_argument("--dg-timeout", type=float, default=None,
                         help="delay generator socket timeout, seconds (default: 2.0 or config)")
    parser.add_argument("--dg-command-delay", type=float, default=None,
                         help="inter-command delay, seconds (default: 0.02 or config)")
    parser.add_argument("--dg-dry-run", action="store_true",
                         help="log the exact ASCII delay generator commands instead of opening a socket")
    parser.add_argument("--self-test", action="store_true",
                         help="run a loopback self-test against this config and exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.config:
        with open(args.config, "r") as f:
            config = json.load(f)
    else:
        logger.info("no --config given, using built-in example property table")
        config = DEFAULT_CONFIG

    host = args.host or config.get("host", "0.0.0.0")
    port = args.port or config.get("port", 50001)

    dg_config = config.get("delay_generator", {})
    args.dg_host = args.dg_host or dg_config.get("host", DelayGeneratorBackend.HOST_DEFAULT)
    args.dg_port = args.dg_port or dg_config.get("port", DelayGeneratorBackend.PORT_DEFAULT)
    args.dg_adv_ms = args.dg_adv_ms if args.dg_adv_ms is not None else dg_config.get("adv_ms", 16.625)
    args.dg_timeout = args.dg_timeout if args.dg_timeout is not None else dg_config.get("timeout", 2.0)
    args.dg_command_delay = (
        args.dg_command_delay if args.dg_command_delay is not None else dg_config.get("command_delay", 0.02)
    )
    args.dg_dry_run = args.dg_dry_run or dg_config.get("dry_run", False)

    property_table = PropertyTable.from_config(config)

    if args.self_test:
        ok = run_self_test(host, port, property_table)
        print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
        sys.exit(0 if ok else 1)

    backend = bind_backend(property_table, args)
    on_disconnect = backend.close if isinstance(backend, DelayGeneratorBackend) else None

    server = SpecmanServer(host, port, property_table, dry_run=args.dry_run, on_disconnect=on_disconnect)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
