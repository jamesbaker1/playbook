# SPDX-License-Identifier: AGPL-3.0-only

"""Modal app that serves an open-weight model behind an OpenAI-compatible vLLM server.

NOTHING here runs automatically. One app definition serves any HuggingFace model on
any Modal GPU: the model, GPU, and API key are read from the *local* environment when
you run ``modal deploy``, baked into the deployed function, and the Modal app name and
the public web label are both derived from the model slug, so several models can be
live side by side without colliding.

Quick start (from the repo root)::

    # 7B on a single A10G -- the campaign default, ~$1.10/GPU-hour
    PLAYBOOK_VLLM_MODEL=Qwen/Qwen2.5-7B-Instruct \
    PLAYBOOK_VLLM_GPU=A10G \
    PLAYBOOK_VLLM_API_KEY=<shared-secret> \
        modal deploy training/modal_vllm.py

    # 14B needs more than 24GB in bf16 -- one L40S (48GB)
    PLAYBOOK_VLLM_MODEL=Qwen/Qwen2.5-14B-Instruct PLAYBOOK_VLLM_GPU=L40S \
        modal deploy training/modal_vllm.py

    # 32B is ~64GB of bf16 weights -- one H100 (80GB), or two L40S via "L40S:2"
    PLAYBOOK_VLLM_MODEL=Qwen/Qwen2.5-32B-Instruct PLAYBOOK_VLLM_GPU=H100 \
        modal deploy training/modal_vllm.py

``modal deploy`` prints a resolved-configuration banner (app name, endpoint URL, API
key) before it uploads, and the deploy summary repeats the URL. The URL can also be
re-derived at any time, without a container, straight from the deployment::

    python training/modal_vllm.py url          # -> https://<ws>--playbook-vllm-<slug>.modal.run
    python training/modal_vllm.py config       # the same banner, no deploy

Then poll for readiness and run the benchmark::

    export OPENAI_API_KEY=<the same shared secret>
    curl -sf -H "Authorization: Bearer $OPENAI_API_KEY" "$URL/v1/models"   # 200 == ready
    python -m playbook_legal.bench --runner baseline \
        --model Qwen/Qwen2.5-7B-Instruct --base-url "$URL/v1" ...

Tear down with ``modal app stop playbook-vllm-<slug>``. A deployed app with zero
running containers costs nothing, but a container that has just served a request
idle-burns its GPU until the scaledown window expires -- so stop apps when a sweep
finishes rather than trusting the window.

Environment variables (all read on the *client* machine, at deploy time):

==============================  ======================================================
PLAYBOOK_VLLM_MODEL             HuggingFace repo id. Default: Qwen/Qwen2.5-7B-Instruct
PLAYBOOK_VLLM_GPU               Modal GPU spec: "A10G", "L40S", "H100", "L40S:2", ...
                                A ":N" suffix also sets vLLM --tensor-parallel-size N.
PLAYBOOK_VLLM_API_KEY           Shared secret for vLLM --api-key. Override the default.
PLAYBOOK_VLLM_MAX_MODEL_LEN     Context length. Default: 32768
PLAYBOOK_VLLM_TOOL_PARSER       vLLM --tool-call-parser. Default: hermes (Qwen2.5)
PLAYBOOK_VLLM_SCALEDOWN         Idle seconds before the GPU is released. Default: 600
PLAYBOOK_VLLM_GPU_UTIL          vLLM --gpu-memory-utilization. Default: 0.90
PLAYBOOK_VLLM_EXTRA_ARGS        Extra flags appended verbatim to ``vllm serve``
PLAYBOOK_VLLM_VERSION           Pinned vLLM release. Default: 0.25.1
==============================  ======================================================

GPU sizing, from bf16 weight size plus room for a 32k KV cache:

======================  =========  ===========================================
Qwen2.5-7B-Instruct     ~15 GiB    A10G (24GB). Measured: 83k-token KV cache.
Qwen2.5-14B-Instruct    ~28 GiB    L40S (48GB). A10G is far too small.
Qwen2.5-32B-Instruct    ~62 GiB    H100 (80GB), or "L40S:2" for tensor parallel.
======================  =========  ===========================================

Measured on Qwen2.5-7B-Instruct / A10G, vLLM 0.25.1:

- Cold start, weights already on the volume: ~2 minutes to a 200 on /v1/models.
- Cold start, first ever pull of a 7B: ~4 minutes (~1 minute of that is download).
  Budget proportionally more for 14B/32B, whose weights are 2x/4x larger.
- One Playbook episode (matter ai_saas_001, 30-step budget): see training/README or
  the smoke scorecard under artifacts/scorecards/.

Windows notes: run ``modal`` from a shell with ``PYTHONIOENCODING=utf-8`` -- without
it the CLI dies on its own checkmark glyph with a 'charmap' codec error after the
deploy has already succeeded. ``modal app stop`` needs ``--yes`` when there is no
interactive terminal.
"""

from __future__ import annotations

import os
import re
import sys

import modal

# --------------------------------------------------------------------------------------
# Deploy-time configuration (resolved on the machine running `modal deploy`).
# --------------------------------------------------------------------------------------

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
DEFAULT_GPU = "A10G"

# A shared secret, not a credential: it exists so the public *.modal.run URL is not an
# open GPU proxy that anyone who guesses the workspace name can bill to this account.
# Override it with PLAYBOOK_VLLM_API_KEY for anything longer-lived than a bench sweep.
DEFAULT_API_KEY = "playbook-vllm-shared-key"

VLLM_VERSION = os.environ.get("PLAYBOOK_VLLM_VERSION", "0.25.1")
MODEL = os.environ.get("PLAYBOOK_VLLM_MODEL", DEFAULT_MODEL)
GPU = os.environ.get("PLAYBOOK_VLLM_GPU", DEFAULT_GPU)
API_KEY = os.environ.get("PLAYBOOK_VLLM_API_KEY", DEFAULT_API_KEY)
MAX_MODEL_LEN = os.environ.get("PLAYBOOK_VLLM_MAX_MODEL_LEN", "32768")
TOOL_PARSER = os.environ.get("PLAYBOOK_VLLM_TOOL_PARSER", "hermes")
GPU_UTIL = os.environ.get("PLAYBOOK_VLLM_GPU_UTIL", "0.90")
EXTRA_ARGS = os.environ.get("PLAYBOOK_VLLM_EXTRA_ARGS", "")
SCALEDOWN_WINDOW = int(os.environ.get("PLAYBOOK_VLLM_SCALEDOWN", str(10 * 60)))

VLLM_PORT = 8000
HF_CACHE_PATH = "/hf-cache"
# Weight download dominates a cold start, so wait generously for the port to open.
STARTUP_TIMEOUT = 30 * 60


def model_slug(model: str) -> str:
    """``Qwen/Qwen2.5-7B-Instruct`` -> ``qwen2-5-7b-instruct`` (a valid Modal label)."""
    tail = model.rstrip("/").split("/")[-1]
    slug = re.sub(r"[^a-z0-9]+", "-", tail.lower()).strip("-")
    return slug or "model"


def tensor_parallel_size(gpu: str) -> int:
    """``L40S:2`` -> 2. A bare GPU name means a single GPU."""
    _, _, count = gpu.partition(":")
    return int(count) if count.strip().isdigit() else 1


SLUG = model_slug(MODEL)
APP_NAME = f"playbook-vllm-{SLUG}"
TP_SIZE = tensor_parallel_size(GPU)

# --------------------------------------------------------------------------------------
# Modal objects.
# --------------------------------------------------------------------------------------

app = modal.App(APP_NAME)

# Shared by every model server, so re-deploying weights that are already cached is a
# warm start instead of another multi-gigabyte download.
hf_cache = modal.Volume.from_name("playbook-hf-cache", create_if_missing=True)

vllm_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        f"vllm=={VLLM_VERSION}",
        "huggingface_hub[hf_transfer]>=0.34",
    )
    .env(
        {
            "HF_HOME": HF_CACHE_PATH,
            # Fast weight transfer. Recent huggingface_hub deprecates HF_HUB_ENABLE_HF_TRANSFER
            # in favour of Xet; both are set so the image works either side of that change.
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "HF_XET_HIGH_PERFORMANCE": "1",
            # vLLM's compile cache also lives on the volume, so the torch.compile and
            # CUDA-graph warmup is paid once per (model, GPU) pair, not once per start.
            "VLLM_CACHE_ROOT": f"{HF_CACHE_PATH}/vllm",
            # vLLM defaults this to True and then JIT-compiles a CUDA sampling kernel
            # during engine warmup. debian_slim ships no CUDA toolkit, so the build dies
            # with "Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't
            # exist" and the engine never comes up. The Torch-native sampler is
            # equivalent here -- one short completion per turn, batch size one -- and it
            # is far cheaper than carrying a full -devel CUDA image just to satisfy JIT.
            "VLLM_USE_FLASHINFER_SAMPLER": "0",
            "VLLM_LOGGING_LEVEL": "INFO",
        }
    )
)


def _serve_command() -> list[str]:
    """Build the ``vllm serve`` argv from the environment baked into the container."""
    model = os.environ["PLAYBOOK_VLLM_MODEL"]
    command = [
        "vllm",
        "serve",
        model,
        # Report the full HF repo id as the model name so `--model Qwen/Qwen2.5-7B-Instruct`
        # works unchanged against this server and against any other OpenAI-compatible host.
        "--served-model-name",
        model,
        "--host",
        "0.0.0.0",
        "--port",
        str(VLLM_PORT),
        "--api-key",
        os.environ["PLAYBOOK_VLLM_API_KEY"],
        # Native OpenAI tool calling. The Playbook baseline runner drives the environment
        # entirely through `tools`, so without these two flags every episode scores zero.
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        os.environ["PLAYBOOK_VLLM_TOOL_PARSER"],
        "--max-model-len",
        os.environ["PLAYBOOK_VLLM_MAX_MODEL_LEN"],
        "--tensor-parallel-size",
        os.environ["PLAYBOOK_VLLM_TP_SIZE"],
        "--gpu-memory-utilization",
        os.environ["PLAYBOOK_VLLM_GPU_UTIL"],
    ]
    extra = os.environ.get("PLAYBOOK_VLLM_EXTRA_ARGS", "").split()
    return command + extra


def _commit_cache_when_ready() -> None:
    """Persist freshly downloaded weights back to the Volume once vLLM answers /health."""
    import time
    import urllib.request

    deadline = time.monotonic() + STARTUP_TIMEOUT
    url = f"http://127.0.0.1:{VLLM_PORT}/health"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    break
        except Exception as exc:  # noqa: BLE001 - the server is simply not listening yet
            last_error = exc
        time.sleep(5)
    else:
        # Never healthy: whatever is on the volume is a partial download, so leave it.
        print(f"[playbook] vLLM never became healthy ({last_error}); skipping commit", flush=True)
        return
    try:
        hf_cache.commit()
        print("[playbook] committed HuggingFace cache volume", flush=True)
    except Exception as exc:  # noqa: BLE001 - a failed commit only costs a slow cold start
        print(f"[playbook] cache commit failed: {exc}", flush=True)


@app.function(
    image=vllm_image,
    gpu=GPU,
    volumes={HF_CACHE_PATH: hf_cache},
    # One GPU-backed replica. Benchmark runs are serial, and capping containers bounds
    # the spend if the public endpoint is ever probed by someone else.
    max_containers=1,
    scaledown_window=SCALEDOWN_WINDOW,
    timeout=60 * 60,
    env={
        "PLAYBOOK_VLLM_MODEL": MODEL,
        "PLAYBOOK_VLLM_API_KEY": API_KEY,
        "PLAYBOOK_VLLM_MAX_MODEL_LEN": MAX_MODEL_LEN,
        "PLAYBOOK_VLLM_TOOL_PARSER": TOOL_PARSER,
        "PLAYBOOK_VLLM_TP_SIZE": str(TP_SIZE),
        "PLAYBOOK_VLLM_GPU_UTIL": GPU_UTIL,
        "PLAYBOOK_VLLM_EXTRA_ARGS": EXTRA_ARGS,
    },
)
@modal.concurrent(max_inputs=32)
@modal.web_server(port=VLLM_PORT, startup_timeout=STARTUP_TIMEOUT, label=APP_NAME)
def serve() -> None:
    """Launch vLLM's OpenAI-compatible server and hand its port to Modal."""
    import subprocess
    import threading

    command = _serve_command()
    printable = list(command)
    printable[printable.index("--api-key") + 1] = "<redacted>"
    print(f"[playbook] {' '.join(printable)}", flush=True)

    subprocess.Popen(command)
    threading.Thread(target=_commit_cache_when_ready, daemon=True).start()


# --------------------------------------------------------------------------------------
# Local helpers (never imported remotely; `python training/modal_vllm.py <cmd>`).
# --------------------------------------------------------------------------------------


def workspace_name() -> str:
    """Active Modal workspace, which is the first segment of every web URL."""
    from modal import config as modal_config

    return getattr(modal_config, "_profile", None) or "<workspace>"


def endpoint_url() -> str:
    """Base URL of the deployed server. Ask Modal first; fall back to the naming rule."""
    try:
        return modal.Function.from_name(APP_NAME, "serve").get_web_url().rstrip("/")
    except Exception:  # noqa: BLE001 - not deployed yet, or offline; the rule still holds
        return f"https://{workspace_name()}--{APP_NAME}.modal.run"


def _banner() -> str:
    url = endpoint_url()
    return "\n".join(
        [
            "",
            "  playbook vLLM server -- resolved configuration",
            f"    model            {MODEL}",
            f"    gpu              {GPU}  (tensor-parallel-size {TP_SIZE})",
            f"    vllm             {VLLM_VERSION}",
            f"    max-model-len    {MAX_MODEL_LEN}",
            f"    tool-call-parser {TOOL_PARSER}",
            f"    scaledown        {SCALEDOWN_WINDOW}s",
            f"    app name         {APP_NAME}   (teardown: modal app stop {APP_NAME})",
            f"    endpoint         {url}",
            f"    --base-url       {url}/v1",
            f"    OPENAI_API_KEY   {API_KEY}",
            "",
        ]
    )


if modal.is_local() and __name__ != "__main__":
    # Printed as a side effect of `modal deploy` / `modal serve`, on stderr so it never
    # pollutes anything that parses stdout.
    print(_banner(), file=sys.stderr)

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "config"
    if command == "url":
        print(endpoint_url())
    elif command == "base-url":
        print(f"{endpoint_url()}/v1")
    elif command == "app-name":
        print(APP_NAME)
    elif command == "api-key":
        print(API_KEY)
    elif command == "config":
        print(_banner())
    else:
        raise SystemExit(f"usage: {sys.argv[0]} [config|url|base-url|app-name|api-key]")
