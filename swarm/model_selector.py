"""Model selection per use-case/role (spec section 11).

Resolution order:
    1. Explicit model requested by parent agent (if allowed).
    2. MODEL line from the role's primary instruction file.
    3. MODEL line from the current phase prompt file (if phase switching on).
    4. Role fallback from settings (DEFAULT_<ROLE>_MODEL).
    5. DEFAULT_MODEL.
    6. Fail if no usable (non-placeholder) model exists.

Context size (num_ctx) is auto-detected from the model itself via the probe
when the setting is "auto"; an optional MAX_AUTO_NUM_CTX ceiling caps it so a
model's huge native context does not blow up laptop VRAM.
"""
from __future__ import annotations

from dataclasses import dataclass

from .instructions import parse_instruction_file
from .model_probe import ProbeCache
from .settings import PLACEHOLDER_MODEL, Settings, SettingsError

# role -> (primary instruction settings key, settings prefix used for ctx/predict/temp)
ROLE_PRIMARY_FILE = {
    "chat_agent": ("INSTRUCTION_PROGENITOR", "PROGENITOR"),
    "planner": ("INSTRUCTION_PLANNING", "PLANNER"),
    "spawner": ("INSTRUCTION_SPAWNING", "SPAWNER"),
    "coding_agent": ("INSTRUCTION_CODING", "CODE"),
    "terminal": ("INSTRUCTION_TERMINAL", "TERMINAL"),
    "python": ("INSTRUCTION_PYTHON", "PYTHON"),
    "shell": ("INSTRUCTION_SHELL", "SHELL"),
    "researcher": ("INSTRUCTION_CURL", "RESEARCH"),
    "file_reader": ("INSTRUCTION_FILE_READING", "FILE"),
    "file_writer": ("INSTRUCTION_FILE_WRITING", "FILE"),
    "file_deleter": ("INSTRUCTION_FILE_DELETING", "FILE"),
    "reviewer": ("INSTRUCTION_REVIEW", "REVIEW"),
    "integrator": ("INSTRUCTION_INTEGRATION", "INTEGRATION"),
    "tester": ("INSTRUCTION_TESTING", "TESTER"),
    "fixer": ("INSTRUCTION_FIXING", "FIX"),
    "profiler": ("INSTRUCTION_PROFILING", "PROFILING"),
    "optimizer": ("INSTRUCTION_OPTIMIZATION", "OPTIMIZATION"),
    "finisher": ("INSTRUCTION_FINISHING", "FINISH"),
    "summarizer": ("INSTRUCTION_SUMMARIZING", "SUMMARIZER"),
    "testing_agent": ("INSTRUCTION_CODE_CHECKING", "CODE_CHECKER"),
    "philosopher": ("INSTRUCTION_PHILOSOPHIZING", "PHILOSOPHER"),
}

# role -> DEFAULT_<X>_MODEL settings key
ROLE_DEFAULT_KEY = {
    "chat_agent": "DEFAULT_PROGENITOR_MODEL",
    "planner": "DEFAULT_PLANNER_MODEL",
    "spawner": "DEFAULT_SPAWNER_MODEL",
    "coding_agent": "DEFAULT_CODE_MODEL",
    "terminal": "DEFAULT_TERMINAL_MODEL",
    "python": "DEFAULT_PYTHON_MODEL",
    "shell": "DEFAULT_SHELL_MODEL",
    "researcher": "DEFAULT_RESEARCH_MODEL",
    "file_reader": "DEFAULT_FILE_MODEL",
    "file_writer": "DEFAULT_FILE_MODEL",
    "file_deleter": "DEFAULT_FILE_MODEL",
    "reviewer": "DEFAULT_REVIEW_MODEL",
    "integrator": "DEFAULT_INTEGRATION_MODEL",
    "tester": "DEFAULT_TESTER_MODEL",
    "fixer": "DEFAULT_FIX_MODEL",
    "profiler": "DEFAULT_PROFILING_MODEL",
    "optimizer": "DEFAULT_OPTIMIZATION_MODEL",
    "finisher": "DEFAULT_FINISH_MODEL",
    "summarizer": "DEFAULT_SUMMARIZER_MODEL",
    "testing_agent": "DEFAULT_CODE_CHECKER_MODEL",
    "philosopher": "DEFAULT_PHILOSOPHER_MODEL",
}

# Roles routed to GPU (setting ROUTE_<X>_TO_GPU=true). Default CPU otherwise.
GPU_ROUTE_KEY = {
    "chat_agent": "ROUTE_PROGENITOR_TO_GPU",
    "planner": "ROUTE_PLANNER_TO_GPU",
    "spawner": "ROUTE_SPAWNER_TO_GPU",
    "coding_agent": "ROUTE_CODE_TO_GPU",
    "integrator": "ROUTE_INTEGRATION_TO_GPU",
    "fixer": "ROUTE_FIX_TO_GPU",
    "optimizer": "ROUTE_OPTIMIZATION_TO_GPU",
    "testing_agent": "ROUTE_CODE_CHECKER_TO_GPU",
}


@dataclass
class ModelConfig:
    role: str
    selected_model: str
    model_source: str
    primary_instruction_file: str | None
    endpoint: str
    execution_class: str  # "gpu" | "cpu"
    num_ctx: int
    num_predict: int
    temperature: float
    native_num_ctx: int | None = None
    probe_source: str | None = None


class ModelSelector:
    def __init__(self, settings: Settings, probe: ProbeCache | None = None):
        self.s = settings
        self.probe = probe or ProbeCache(settings.path("RUNTIME_DIR") / "config_cache.json")

    def _instruction_model(self, role: str) -> tuple[str | None, str | None]:
        info = ROLE_PRIMARY_FILE.get(role)
        if not info:
            return None, None
        key, _ = info
        rel = self.s.get(key)
        # Instruction files no longer dictate the model; we only return the file
        # path (for logging / settings prefix). The model comes from settings.
        return None, (str(rel) if rel else None)

    def _role_default(self, role: str) -> str | None:
        key = ROLE_DEFAULT_KEY.get(role)
        v = self.s.get(key) if key else None
        if v and v != PLACEHOLDER_MODEL:
            return v
        return None

    def _global_default(self) -> str | None:
        v = self.s.get("DEFAULT_MODEL")
        return v if v and v != PLACEHOLDER_MODEL else None

    def _endpoint_for(self, role: str) -> tuple[str, str]:
        gpu_key = GPU_ROUTE_KEY.get(role)
        use_gpu = bool(gpu_key) and self.s.get_bool(gpu_key, False)
        if use_gpu:
            return self.s.require("OLLAMA_GPU_ENDPOINT"), "gpu"
        return self.s.require("OLLAMA_CPU_ENDPOINT"), "cpu"

    def _ctx_for(self, role: str, endpoint: str, model: str) -> tuple[int, int | None, str | None]:
        _, prefix = ROLE_PRIMARY_FILE.get(role, (None, "DEFAULT"))
        ctx_key = f"{prefix}_NUM_CTX"
        native = None
        probe_src = None
        if self.s.is_auto(ctx_key) or self.s.get(ctx_key) is None:
            info = self.probe.get(endpoint, model)
            native = info.native_num_ctx
            probe_src = info.source
            ctx = native or 8192  # conservative fallback when probe unavailable
        else:
            ctx = self.s.get_int(ctx_key, 8192) or 8192
        ceiling = self.s.get_int("MAX_AUTO_NUM_CTX", 0) or 0
        if ceiling and ctx > ceiling:
            ctx = ceiling
        return ctx, native, probe_src

    def _predict_for(self, role: str) -> int:
        _, prefix = ROLE_PRIMARY_FILE.get(role, (None, "DEFAULT"))
        v = self.s.get_int(f"{prefix}_NUM_PREDICT")
        if v is None:
            v = self.s.get_int("DEFAULT_NUM_PREDICT", 2048)
        return v or 2048

    def _temp_for(self, role: str) -> float:
        _, prefix = ROLE_PRIMARY_FILE.get(role, (None, "DEFAULT"))
        v = self.s.get_float(f"{prefix}_TEMPERATURE")
        return v if v is not None else 0.2

    def resolve(self, role: str, explicit_model: str | None = None,
                phase_prompt_model: str | None = None) -> ModelConfig:
        allow_override = self.s.get_bool("ALLOW_INSTRUCTION_FILE_MODEL_OVERRIDE", True)
        allow_phase = self.s.get_bool("ALLOW_PHASE_MODEL_SWITCHING", True)

        primary_file = None
        model = None
        source = None

        if explicit_model and explicit_model != PLACEHOLDER_MODEL:
            model, source = explicit_model, "explicit_spawn"
        if model is None and allow_override:
            instr_model, primary_file = self._instruction_model(role)
            if instr_model:
                model, source = instr_model, "instruction_file"
        else:
            _, primary_file = self._instruction_model(role)
        if model is None and allow_phase and phase_prompt_model and phase_prompt_model != PLACEHOLDER_MODEL:
            model, source = phase_prompt_model, "phase_prompt"
        if model is None:
            rd = self._role_default(role)
            if rd:
                model, source = rd, "role_fallback"
        if model is None:
            gd = self._global_default()
            if gd:
                model, source = gd, "default_fallback"
        if model is None:
            raise SettingsError(
                f"no usable model for role '{role}': set DEFAULT_{role.upper()}_MODEL "
                f"or DEFAULT_MODEL in settings/main.settings to a model you've pulled."
            )

        endpoint, exec_class = self._endpoint_for(role)
        num_ctx, native, probe_src = self._ctx_for(role, endpoint, model)
        return ModelConfig(
            role=role,
            selected_model=model,
            model_source=source,
            primary_instruction_file=primary_file,
            endpoint=endpoint,
            execution_class=exec_class,
            num_ctx=num_ctx,
            num_predict=self._predict_for(role),
            temperature=self._temp_for(role),
            native_num_ctx=native,
            probe_source=probe_src,
        )
