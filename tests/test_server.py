#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ds-vision-mcp 离线测试：配置解析、图片解析、缓存与路由跳过逻辑。"""
import base64
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server as srv


def make_png_bytes() -> bytes:
    import struct
    import zlib

    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        c += struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
        return c

    w, h = 8, 8
    rows = []
    for y in range(h):
        row = bytearray([0])
        for _ in range(w):
            row.extend((255, 0, 0, 255))
        rows.append(bytes(row))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(rows), 9))
            + chunk(b'IEND', b''))


class ImageParsingTest(unittest.TestCase):
    def test_local_path(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(make_png_bytes())
            path = f.name
        try:
            mime, b64 = srv.read_image_bytes(path)
            self.assertEqual(mime, "image/png")
            self.assertEqual(base64.b64decode(b64), make_png_bytes())
        finally:
            os.unlink(path)

    def test_data_uri(self):
        raw = make_png_bytes()
        uri = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        mime, b64 = srv.read_image_bytes(uri)
        self.assertEqual(mime, "image/png")
        self.assertEqual(base64.b64decode(b64), raw)

    def test_bare_base64(self):
        raw = make_png_bytes()
        mime, b64 = srv.read_image_bytes(base64.b64encode(raw).decode("ascii"))
        self.assertEqual(mime, "image/png")
        self.assertEqual(base64.b64decode(b64), raw)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            srv.read_image_bytes("/definitely/not/exists.png")


class ConfigTest(unittest.TestCase):
    def test_empty_config_has_no_builtin_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.json"
            cfg_path.write_text(json.dumps({}), encoding="utf-8")
            cfg = srv.Config(str(cfg_path))
            data = cfg.get()
            self.assertEqual(data["channels"], [])
            self.assertEqual(data["race"], [])
            self.assertEqual(data["fallback"], [])

    def test_new_style_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.json"
            cfg_path.write_text(json.dumps({
                "routing": {"race": ["a"], "fallback": ["b"]},
                "channels": [
                    {"id": "a", "base_url": "https://a.example/v1", "model": "m1", "api_key_env": "KEY_A"},
                    {"id": "b", "base_url": "https://b.example/v1", "model": "m2", "api_key_env": "KEY_B"},
                ],
            }), encoding="utf-8")
            old_env = os.environ.get("KEY_A")
            os.environ["KEY_A"] = "x"
            try:
                cfg = srv.Config(str(cfg_path))
                data = cfg.get()
                self.assertEqual(data["race"], ["a"])
                self.assertEqual(data["fallback"], ["b"])
                router = srv.VisionRouter(cfg.get)
                ready = [c["id"] for c in router._ready(data["race"])]
                self.assertEqual(ready, ["a"])
            finally:
                if old_env is None:
                    os.environ.pop("KEY_A", None)
                else:
                    os.environ["KEY_A"] = old_env


class CacheTest(unittest.TestCase):
    def test_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "cache": {"enabled": True, "directory": tmp, "ttl_seconds": 60},
            }
            key = "abc123"
            value = {"result": "hello"}
            srv.write_cache(config, key, value)
            hit = srv.read_cache(config, key)
            self.assertEqual(hit, value)


class RoutingTest(unittest.TestCase):
    def test_missing_key_channel_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.json"
            cfg_path.write_text(json.dumps({
                "routing": {"race": ["only"], "fallback": []},
                "channels": [{"id": "only", "base_url": "https://example.com/v1/chat/completions",
                              "model": "m", "api_key_env": "SURELY_MISSING_KEY_XYZ"}],
            }), encoding="utf-8")
            cfg = srv.Config(str(cfg_path))
            old = os.environ.get("SURELY_MISSING_KEY_XYZ")
            os.environ.pop("SURELY_MISSING_KEY_XYZ", None)
            try:
                router = srv.VisionRouter(cfg.get)
                ready = router._ready(cfg.get()["race"])
                self.assertEqual(ready, [])
                with self.assertRaises(RuntimeError):
                    router.route_image("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                                       "describe", "reason", False, False, False)
            finally:
                if old is not None:
                    os.environ["SURELY_MISSING_KEY_XYZ"] = old


class ServerCommandTest(unittest.TestCase):
    """server_command()：源码用 python3，frozen 用二进制自身（免 Python）。"""

    def test_source_mode_uses_python3(self):
        cmd, args = srv.server_command()
        self.assertEqual(cmd, "python3")
        self.assertEqual(len(args), 1)
        self.assertTrue(args[0].endswith("server.py"))

    def test_frozen_mode_uses_binary_itself(self):
        with unittest.mock.patch.object(srv, "IS_FROZEN", True), \
                unittest.mock.patch.object(srv.sys, "executable", "/usr/local/bin/vision-mcp"):
            cmd, args = srv.server_command()
        self.assertEqual(cmd, "/usr/local/bin/vision-mcp")
        self.assertEqual(args, [])

    def test_frozen_base_dir_is_binary_dir(self):
        with unittest.mock.patch.object(srv, "IS_FROZEN", True), \
                unittest.mock.patch.object(srv.sys, "executable", "/opt/vision-mcp/vision-mcp"):
            self.assertEqual(str(srv._base_dir()), "/opt/vision-mcp")


if __name__ == "__main__":
    unittest.main(verbosity=2)
