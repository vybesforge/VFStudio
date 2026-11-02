#!/usr/bin/env python3
"""Probe/recommend checks. No network, no downloads.

  python3 tools/forge/test_recommend.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import recommend as rec  # noqa: E402

INSTALLER_ESSENTIALS = {
    "z-image-turbo", "z-image-te", "z-image-vae",
    "realesrgan-x4plus", "4x-ultrasharp",
    "stable-audio-open-1.0", "t5-base",
    "trellis2-int8", "trellis2-shape-vae", "trellis2-texture-vae", "dinov3-L", "birefnet",
}
STABLE_IDS = [
    "flux1-dev-fp8", "z-image-turbo", "z-image-te", "z-image-vae", "z-image-controlnet-union",
    "qwen-image-edit-2509", "sa3-small-sfx", "hyvideo15-720p-i2v", "hyvideo15-480p-t2v",
    "hyvideo15-vae", "hyvideo15-byt5", "hyvideo15-sigclip", "qwen-image-edit-2509-gguf",
    "qwen-2.5-vl-7b", "qwen-image-vae", "wan2.2-ti2v-5b", "wan2.2-vae", "umt5-xxl-fp8",
    "stable-audio-open-1.0", "t5-base", "stable-audio-3-medium", "t5gemma-b-b-ul2",
    "flux2-klein-4b", "flux2-vae", "seedvr2-3b-int8", "seedvr2-vae", "ace-step-1.5-turbo-aio",
    "4x-ultrasharp", "realesrgan-x4plus", "trellis2-int8", "trellis2-shape-vae",
    "trellis2-texture-vae", "dinov3-L", "birefnet",
]


def load():
    return rec.load_manifest(ROOT / "models" / "manifest.json")


def run(name: str):
    return rec.recommend(load(), rec.fixture_machine(name))


def bucket(result, model_id):
    for row in result["models"]:
        if row["id"] == model_id:
            return row["bucket"], row["reason"]
    raise AssertionError(model_id)


def kept_gb(result) -> float:
    total = sum(m["gb"] for m in result["models"] if m["bucket"] != "skip")
    for tier in ("essentials", "quality", "optional"):
        total += sum(m["gb"] for m in result["hf"][tier])
    return total


class ManifestTests(unittest.TestCase):
    def test_ids_and_flux_url_stay_put(self):
        models = load()["models"]
        self.assertEqual([m["id"] for m in models], STABLE_IDS)
        flux = models[0]
        self.assertEqual(flux["id"], "flux1-dev-fp8")
        self.assertEqual(flux["gb"], 17.2)
        self.assertEqual(
            flux["url"],
            "https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev-fp8.safetensors",
        )
        self.assertTrue(flux["path"].startswith("checkpoints/"))

    def test_fit_graph(self):
        models = load()["models"]
        by = {m["id"]: m for m in models}
        included = set()
        for m in models:
            self.assertIn("fit", m)
            fit = m["fit"]
            for inc in fit.get("includes") or []:
                self.assertIn(inc, by)
                self.assertTrue(by[inc]["fit"].get("companion"), inc)
                included.add(inc)
            if not fit.get("companion"):
                self.assertIn(fit.get("tier"), {"essentials", "quality", "optional"})
                self.assertTrue(fit.get("backends"))
        for m in models:
            if m["fit"].get("companion"):
                self.assertIn(m["id"], included)
                self.assertNotIn("includes", m["fit"])


class RuleTests(unittest.TestCase):
    def test_every_id_lands_once_and_disk_holds(self):
        for name in rec.FIXTURES:
            result = run(name)
            ids = [m["id"] for m in result["models"]]
            self.assertEqual(ids, STABLE_IDS, name)
            self.assertEqual(len(ids), len(set(ids)))
            for row in result["models"]:
                self.assertTrue(row["reason"], row["id"])
            free = result["machine"]["disk_free_gb"]
            headroom = result["disk"]["headroom_gb"]
            self.assertLessEqual(kept_gb(result) + headroom, free + 0.05, name)

    def test_recommend_does_not_probe_or_download(self):
        src = Path(rec.__file__).read_text()
        self.assertNotIn("urlopen", src)
        self.assertNotIn("curl", src)
        import subprocess as sp
        orig = sp.run

        def boom(*_a, **_k):
            raise AssertionError("recommend() probed the machine")

        sp.run = boom
        try:
            run("billie")
        finally:
            sp.run = orig

    def test_billie_full_quality_on_the_v100(self):
        result = run("billie")
        self.assertEqual({m["id"] for m in result["models"] if m["bucket"] == "essentials"}, INSTALLER_ESSENTIALS)
        for model_id in ("flux1-dev-fp8", "qwen-image-edit-2509", "wan2.2-ti2v-5b",
                         "hyvideo15-720p-i2v", "hyvideo15-480p-t2v", "flux2-klein-4b"):
            self.assertEqual(bucket(result, model_id)[0], "quality", model_id)
        self.assertEqual(bucket(result, "stable-audio-3-medium")[0], "optional")
        b, reason = bucket(result, "qwen-image-edit-2509-gguf")
        self.assertEqual(b, "skip")
        self.assertIn("covered by qwen-image-edit-2509", reason)
        self.assertNotIn("qwen-image-edit-2509-gguf", rec.ids_for(result, "recommended"))
        self.assertIn("flux1-dev-fp8", rec.ids_for(result, "recommended"))
        text = " ".join(result["notes"])
        self.assertIn("RTX 2060", text)
        self.assertIn("not split", text)
        self.assertEqual(result["hf"]["essentials"], [])
        self.assertTrue(result["hf"]["skip"])
        self.assertIn("MLX", result["hf"]["skip"][0]["reason"])

    def test_4080_uses_gguf_and_skips_hyvideo(self):
        result = run("4080")
        self.assertEqual(result["machine"]["os"], "windows")
        self.assertEqual(bucket(result, "qwen-image-edit-2509-gguf")[0], "quality")
        self.assertEqual(bucket(result, "flux1-dev-fp8")[0], "quality")
        self.assertEqual(bucket(result, "wan2.2-ti2v-5b")[0], "quality")
        self.assertEqual(bucket(result, "z-image-turbo")[0], "essentials")
        b, reason = bucket(result, "qwen-image-edit-2509")
        self.assertEqual(b, "skip")
        self.assertIn("24", reason)
        b, reason = bucket(result, "hyvideo15-720p-i2v")
        self.assertEqual(b, "skip")
        self.assertIn("20", reason)
        self.assertIn("MLX", result["hf"]["skip"][0]["reason"])
        ids = rec.ids_for(result, "recommended")
        self.assertNotIn("qwen-image-edit-2509", ids)
        self.assertNotIn("hyvideo15-720p-i2v", ids)
        self.assertIn("qwen-image-edit-2509-gguf", ids)

    def test_nvidia_smi_mib_still_counts_as_16gb(self):
        gpus = rec.parse_nvidia_smi("0, NVIDIA GeForce RTX 4080, 16376, 560.35.03\n")
        self.assertEqual(gpus[0]["driver"], "560.35.03")
        self.assertAlmostEqual(gpus[0]["vram_gb"], 15.992, places=3)
        machine = rec.normalize({
            "os": "windows", "arch": "x86_64", "cpu": "x", "cpu_cores": 8,
            "ram_gb": 64, "disk_free_gb": 800, "disk_path": "C:/media-stack",
            "gpus": gpus, "gpu_class": "nvidia", "apple_silicon": False, "os_pretty": "Windows",
        })
        result = rec.recommend(load(), machine)
        self.assertEqual(bucket(result, "flux1-dev-fp8")[0], "quality")
        self.assertEqual(bucket(result, "hyvideo15-720p-i2v")[0], "skip")
        self.assertEqual(bucket(result, "qwen-image-edit-2509")[0], "skip")

    def test_mac64_is_mlx_first_and_matches_installer_essentials(self):
        result = run("mac64")
        self.assertEqual({m["id"] for m in result["models"] if m["bucket"] == "essentials"}, INSTALLER_ESSENTIALS)
        self.assertEqual(bucket(result, "qwen-image-edit-2509-gguf")[0], "quality")
        b, reason = bucket(result, "qwen-image-edit-2509")
        self.assertEqual(b, "skip")
        self.assertIn("gguf", reason)
        self.assertIn("upcast", bucket(result, "flux1-dev-fp8")[1])
        self.assertEqual(bucket(result, "hyvideo15-720p-i2v")[0], "quality")
        hf_ess = {m["id"] for m in result["hf"]["essentials"]}
        hf_qual = {m["id"] for m in result["hf"]["quality"]}
        self.assertIn("kokoro-82m", hf_ess)
        self.assertIn("parakeet-tdt", hf_ess)
        self.assertIn("qwen3-vl-8b", hf_qual)
        self.assertIn("qwen3.8-27b-writer", hf_qual)
        ids = rec.ids_for(result, "recommended")
        self.assertNotIn("kokoro-82m", ids)
        self.assertNotIn("qwen-image-edit-2509", ids)

    def test_mac32_skips_flux_hyvideo_and_27b(self):
        result = run("mac32")
        self.assertEqual(bucket(result, "z-image-turbo")[0], "essentials")
        self.assertEqual(bucket(result, "qwen-image-edit-2509-gguf")[0], "quality")
        for model_id in ("flux1-dev-fp8", "hyvideo15-720p-i2v", "qwen-image-edit-2509"):
            b, reason = bucket(result, model_id)
            self.assertEqual(b, "skip", model_id)
            self.assertTrue("unified" in reason or "Apple" in reason or "GGUF" in reason, reason)
        skipped = {m["id"] for m in result["hf"]["skip"]}
        self.assertIn("qwen3.8-27b-writer", skipped)
        self.assertNotIn("qwen3.8-27b-writer", {m["id"] for m in result["hf"]["quality"]})

    def test_mid_promotes_klein_and_names_vram_skips(self):
        result = run("mid")
        b, reason = bucket(result, "flux2-klein-4b")
        self.assertEqual(b, "essentials")
        self.assertIn("promoted", reason)
        b, reason = bucket(result, "z-image-turbo")
        self.assertEqual(b, "skip")
        self.assertIn("VRAM", reason)
        self.assertEqual(bucket(result, "trellis2-int8")[0], "skip")
        self.assertEqual(bucket(result, "wan2.2-ti2v-5b")[0], "skip")
        self.assertIn("z-image-te", rec.ids_for(result, "essentials"))

    def test_weak_and_cpu_keep_upscalers_only(self):
        for name in ("weak", "cpu"):
            result = run(name)
            kept = {m["id"] for m in result["models"] if m["bucket"] != "skip"}
            self.assertEqual(kept, {"4x-ultrasharp", "realesrgan-x4plus"}, name)
            self.assertIn("VRAM" if name == "weak" else "GPU", bucket(result, "z-image-turbo")[1])

    def test_tight_disk_drops_zimage_and_keeps_sao(self):
        result = run("tight")
        self.assertEqual(bucket(result, "stable-audio-open-1.0")[0], "essentials")
        self.assertEqual(bucket(result, "realesrgan-x4plus")[0], "essentials")
        self.assertEqual(bucket(result, "seedvr2-3b-int8")[0], "quality")
        for model_id in ("z-image-turbo", "trellis2-int8", "flux1-dev-fp8", "sa3-small-sfx"):
            b, reason = bucket(result, model_id)
            self.assertEqual(b, "skip", model_id)
            self.assertIn("disk", reason)
        self.assertIn("kokoro-82m", {m["id"] for m in result["hf"]["essentials"]})
        self.assertIn("disk", next(m["reason"] for m in result["hf"]["skip"] if m["id"] == "whisper-large-v3-turbo"))


class ProbeTests(unittest.TestCase):
    def test_classify(self):
        v100 = [{"vendor": "nvidia", "vram_gb": 32}, {"vendor": "nvidia", "vram_gb": 6}]
        self.assertEqual(rec.classify("linux", "x86_64", "Xeon", v100), "nvidia")
        self.assertEqual(rec.classify("darwin", "arm64", "Apple M3 Max", [{"vendor": "apple"}]), "apple")
        self.assertEqual(
            rec.classify("darwin", "arm64", "Apple M3 Max", [{"vendor": "nvidia", "vram_gb": 16}, {"vendor": "apple"}]),
            "nvidia",
        )
        self.assertEqual(rec.classify("linux", "x86_64", "Ryzen", [{"vendor": "amd", "vram_gb": 16}]), "amd")
        self.assertEqual(rec.classify("linux", "x86_64", "cpu", [{"vendor": "intel"}]), "cpu")
        self.assertTrue(rec.is_apple_silicon("darwin", "arm64", "Apple M3 Max"))
        self.assertFalse(rec.is_apple_silicon("linux", "x86_64", "Xeon"))

    def test_live_probe_shape(self):
        machine = rec.probe(ROOT)
        for key in ("os", "arch", "cpu", "ram_gb", "disk_free_gb", "disk_path", "gpus", "gpu_class", "apple_silicon"):
            self.assertIn(key, machine)
        self.assertIn(machine["os"], ("linux", "darwin", "windows"))
        self.assertIn(machine["gpu_class"], ("nvidia", "amd", "apple", "cpu"))
        self.assertGreater(machine["disk_free_gb"], 0)
        self.assertGreater(machine["ram_gb"], 0)
        result = rec.recommend(load(), machine)
        self.assertEqual([m["id"] for m in result["models"]], STABLE_IDS)
        text = rec.render_text(result)
        self.assertIn("fetch-models --profile auto", text)
        self.assertIn(machine["gpu_class"], text)


class CliTests(unittest.TestCase):
    def test_cli_ids_and_json(self):
        script = ROOT / "tools" / "forge" / "recommend.py"
        ids = subprocess.check_output(
            [sys.executable, str(script), "--fixture", "billie", "--ids"],
            text=True,
        ).split()
        self.assertIn("flux1-dev-fp8", ids)
        self.assertNotIn("qwen-image-edit-2509-gguf", ids)
        self.assertNotIn("stable-audio-3-medium", ids)
        raw = subprocess.check_output(
            [sys.executable, str(script), "--fixture", "mac64", "--json"],
            text=True,
        )
        data = json.loads(raw)
        self.assertEqual(data["machine"]["fixture"], "mac64")
        self.assertEqual(data["summary"]["fetch_command"], "fetch-models --profile auto")
        ess = subprocess.check_output(
            [sys.executable, str(script), "--fixture", "mac64", "--ids", "--tier", "essentials"],
            text=True,
        ).split()
        self.assertEqual(set(ess), INSTALLER_ESSENTIALS)

    def test_fetch_models_dry_run_and_fixture_refusal(self):
        script = ROOT / "bin" / "fetch-models"
        out = subprocess.check_output(
            ["bash", str(script), "--dry-run", "--profile", "auto", "--fixture", "4080"],
            text=True,
        )
        self.assertIn("would fetch qwen-image-edit-2509-gguf", out)
        self.assertNotIn("would fetch qwen-image-edit-2509 ", out)
        self.assertNotIn("would fetch hyvideo15-720p-i2v", out)
        self.assertIn("nothing downloaded", out)
        refused = subprocess.run(
            ["bash", str(script), "--profile", "auto", "--fixture", "billie"],
            text=True, capture_output=True,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("refusing", refused.stderr)


if __name__ == "__main__":
    unittest.main()
