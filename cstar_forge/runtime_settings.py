"""
Bridge legacy ``roms.in`` and ``namelist.nml`` runtime settings layouts.

ModelSpec catalogs may ship ``run-time-defaults.yml`` keyed by ``namelist.nml``
(sections such as ``TIME_STEPPING``, ``GRID_SETTINGS``) while older workflows
used a nested ``roms.in`` dictionary.  ``RuntimeSettings`` centralizes updates so
``CstarSpecBuilder`` and ``RomsMarblInputData`` work with either format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Literal, Optional, Union

ROMS_IN_KEY = "roms.in"
NAMELIST_KEY = "namelist.nml"
RuntimeFormat = Literal["roms.in", "namelist.nml"]


def detect_runtime_format(settings_run_time: Dict[str, Any]) -> RuntimeFormat:
    """Return the top-level runtime settings key in use."""
    if NAMELIST_KEY in settings_run_time:
        return NAMELIST_KEY
    if ROMS_IN_KEY in settings_run_time:
        return ROMS_IN_KEY
    raise ValueError(
        f"Run-time settings must contain '{ROMS_IN_KEY}' or '{NAMELIST_KEY}'. "
        f"Found keys: {sorted(settings_run_time.keys())}"
    )


def detect_runtime_format_from_defaults(
    settings_run_time_dict: Optional[Dict[str, Any]],
) -> RuntimeFormat:
    """Infer format from model default settings (before builder initialization)."""
    if not settings_run_time_dict:
        return ROMS_IN_KEY
    return detect_runtime_format(settings_run_time_dict)


class RuntimeSettings:
    """Read/write helper for compile- and run-time settings dictionaries."""

    def __init__(
        self,
        settings_run_time: Dict[str, Any],
        settings_compile_time: Optional[Dict[str, Any]] = None,
        *,
        fmt: Optional[RuntimeFormat] = None,
    ) -> None:
        self.settings_run_time = settings_run_time
        self.settings_compile_time = settings_compile_time if settings_compile_time is not None else {}
        self.fmt: RuntimeFormat = fmt or detect_runtime_format(settings_run_time)
        self._root = settings_run_time[self.fmt]

    @classmethod
    def from_model_defaults(
        cls,
        compile_defaults: Dict[str, Any],
        run_defaults: Dict[str, Any],
    ) -> "RuntimeSettings":
        fmt = detect_runtime_format_from_defaults(run_defaults)
        return cls(run_defaults, compile_defaults, fmt=fmt)

    def _ensure_section(self, name: str) -> Dict[str, Any]:
        section = self._root.setdefault(name, {})
        if not isinstance(section, dict):
            raise TypeError(f"Expected mapping for section {name!r}, got {type(section).__name__}")
        return section

    def set_simulation_name(self, casename: str, output_root_name: str) -> None:
        if self.fmt == NAMELIST_KEY:
            sim = self._ensure_section("SIMULATION_NAME_SETTINGS")
            sim["title"] = casename
            sim["output_root_name"] = output_root_name
        else:
            self._root["title"] = {"casename": casename}
            self._root["output_root_name"] = {"output_root_name": output_root_name}

    def set_time_stepping(
        self,
        *,
        ntimes: int,
        dt: float,
        ndtfast: int = 60,
        ninfo: int = 1,
    ) -> None:
        if self.fmt == NAMELIST_KEY:
            self._ensure_section("TIME_STEPPING").update(
                {
                    "ntimes": int(round(ntimes)),
                    "dt": dt,
                    "ndtfast": ndtfast,
                    "ninfo": ninfo,
                }
            )
        else:
            self._root["time_stepping"] = {
                "ntimes": int(round(ntimes)),
                "dt": dt,
                "ndtfast": ndtfast,
                "ninfo": ninfo,
            }

    def get_time_stepping(self) -> Dict[str, Any]:
        if self.fmt == NAMELIST_KEY:
            return self._ensure_section("TIME_STEPPING")
        return self._root.setdefault("time_stepping", {})

    def get_dt(self) -> float:
        ts = self.get_time_stepping()
        return float(ts["dt"])

    def ensure_ntimes_int(self) -> None:
        ts = self.get_time_stepping()
        if "ntimes" in ts and isinstance(ts["ntimes"], float):
            ts["ntimes"] = int(round(ts["ntimes"]))

    def set_grid_file(self, path: Union[str, Path]) -> None:
        path_str = str(path)
        if self.fmt == NAMELIST_KEY:
            self._ensure_section("GRID_SETTINGS")["grdname"] = path_str
        else:
            self._root["grid"] = {"grid_file": path_str}

    def set_s_coord(self, *, theta_s: float, theta_b: float, hc: float) -> None:
        if self.fmt == NAMELIST_KEY:
            self._ensure_section("S_COORD").update(
                {"theta_s": theta_s, "theta_b": theta_b, "hc": hc}
            )
        else:
            self._root["s_coord"] = {
                "theta_s": theta_s,
                "theta_b": theta_b,
                "tcline": hc,
            }

    def set_initial_conditions(self, path: Union[str, Path], *, nrrec: int = 1) -> None:
        path_str = str(path)
        if self.fmt == NAMELIST_KEY:
            self._ensure_section("INITIAL_CONDITIONS").update(
                {"ininame": path_str, "nrrec": nrrec}
            )
        else:
            self._root["initial"] = {"initial_file": path_str, "nrrec": nrrec}

    def append_frcfile(self, path: Union[str, Path]) -> None:
        path_str = str(path)
        if self.fmt == NAMELIST_KEY:
            sec = self._ensure_section("FORCING_FILES")
            files = list(sec.get("frcfile") or [])
            if path_str not in files:
                files.append(path_str)
            sec["frcfile"] = files

    def set_legacy_forcing_path(self, key: str, path: Union[str, Path]) -> None:
        """Set a single forcing path in the legacy ``roms.in`` layout."""
        if self.fmt != ROMS_IN_KEY:
            self.append_frcfile(path)
            return
        forcing = self._root.setdefault("forcing", {})
        forcing[key] = str(path)

    def set_open_boundaries(
        self, *, west: bool, east: bool, north: bool, south: bool
    ) -> None:
        cpp = self.settings_compile_time.setdefault("cppdefs", {})
        cpp["obc_west"] = west
        cpp["obc_east"] = east
        cpp["obc_north"] = north
        cpp["obc_south"] = south

    def set_grid_partition_params(self, grid: Any, partitioning: Any) -> None:
        if self.fmt == NAMELIST_KEY:
            sec = self._ensure_section("PARAM_SETTINGS")
            sec["LLm"] = grid.nx
            sec["MMm"] = grid.ny
            sec["N"] = grid.N
            sec["NP_XI"] = partitioning.n_procs_x
            sec["NP_ETA"] = partitioning.n_procs_y
            sec["NSUB_X"] = 1
            sec["NSUB_E"] = 1
        else:
            param = self.settings_compile_time.setdefault("param", {})
            param["LLm"] = grid.nx
            param["MMm"] = grid.ny
            param["N"] = grid.N
            param["NP_XI"] = partitioning.n_procs_x
            param["NP_ETA"] = partitioning.n_procs_y
            param["NSUB_X"] = 1
            param["NSUB_E"] = 1

    def set_surface_interp_frc(self, *, forcing_type: str, interp_frc: int, has_bgc: bool) -> None:
        if self.fmt == NAMELIST_KEY:
            if "bgc" in forcing_type and has_bgc:
                self._ensure_section("BGC_SETTINGS")["interp_bgc_frc"] = bool(interp_frc)
            else:
                self._ensure_section("BULK_FRC_SETTINGS")["interp_bulk_frc"] = bool(interp_frc)
        else:
            if "bgc" in forcing_type and has_bgc:
                self.settings_compile_time.setdefault("bgc", {})["interp_frc"] = interp_frc
            else:
                self.settings_compile_time.setdefault("blk_frc", {})["interp_frc"] = interp_frc

    def set_extract_nesting(
        self,
        *,
        grid_child: Any,
        extract_file: str,
        period: Optional[float] = None,
    ) -> None:
        if self.fmt == NAMELIST_KEY:
            ex = self._ensure_section("EXTRACT_DATA_SETTINGS")
            ex["do_extract"] = True
            ex["extract_file"] = extract_file
            ex["N_chd"] = grid_child.N
            ex["theta_s_chd"] = grid_child.theta_s
            ex["theta_b_chd"] = grid_child.theta_b
            ex["hc_chd"] = grid_child.hc
            if period is not None:
                ex["extract_period"] = period
        else:
            ex = self.settings_compile_time.setdefault("extract_data", {})
            ex["do_extract"] = True
            ex["extract_file"] = extract_file
            ex["N_chd"] = grid_child.N
            ex["theta_s_chd"] = grid_child.theta_s
            ex["theta_b_chd"] = grid_child.theta_b
            ex["hc_chd"] = grid_child.hc
            if period is not None:
                ex["extract_period"] = period

    def set_extract_period(self, period: float) -> None:
        if self.fmt == NAMELIST_KEY:
            self._ensure_section("EXTRACT_DATA_SETTINGS")["extract_period"] = period
        else:
            self.settings_compile_time.setdefault("extract_data", {})["extract_period"] = period

    def rewrite_staged_input_paths(
        self,
        *,
        source_root: Path,
        staged_root: Path,
    ) -> None:
        """Rewrite absolute input-data paths to staged runtime dataset paths."""
        source_root = source_root.resolve()
        staged_root = staged_root.resolve()

        def _rewrite_path(value: str) -> str:
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                return value
            try:
                candidate.resolve().relative_to(source_root)
            except ValueError:
                return value
            return str(staged_root / candidate.name)

        if self.fmt == NAMELIST_KEY:
            nml = self._root
            grid = nml.get("GRID_SETTINGS")
            if isinstance(grid, dict) and "grdname" in grid:
                grid["grdname"] = _rewrite_path(str(grid["grdname"]))
            initial = nml.get("INITIAL_CONDITIONS")
            if isinstance(initial, dict) and "ininame" in initial:
                initial["ininame"] = _rewrite_path(str(initial["ininame"]))
            forcing = nml.get("FORCING_FILES")
            if isinstance(forcing, dict) and "frcfile" in forcing:
                forcing["frcfile"] = [
                    _rewrite_path(str(p)) for p in forcing["frcfile"]
                ]
            extract = nml.get("EXTRACT_DATA_SETTINGS")
            if isinstance(extract, dict) and "extract_file" in extract:
                rewritten = _rewrite_path(str(extract["extract_file"]))
                if rewritten != extract["extract_file"]:
                    extract["extract_file"] = rewritten
        else:
            for section_name in ("grid", "initial", "forcing"):
                section = self._root.get(section_name)
                if not isinstance(section, dict):
                    continue
                for key, value in list(section.items()):
                    if not isinstance(value, str) or not value.strip():
                        continue
                    if key not in {"grid_file", "initial_file"} and not key.endswith("_path"):
                        continue
                    section[key] = _rewrite_path(value)

    def set_tides_settings(
        self,
        *,
        ntides: int,
        bry_tides: bool = True,
        pot_tides: bool = True,
        ana_tides: bool = False,
    ) -> None:
        if self.fmt == NAMELIST_KEY:
            self._ensure_section("TIDES_SETTINGS").update(
                {
                    "ntides": ntides,
                    "bry_tides": bry_tides,
                    "pot_tides": pot_tides,
                    "ana_tides": ana_tides,
                }
            )
        else:
            self.settings_compile_time["tides"] = {
                "ntides": ntides,
                "bry_tides": bry_tides,
                "pot_tides": pot_tides,
                "ana_tides": ana_tides,
            }

    def set_river_frc_settings(self, *, nriv: int) -> None:
        if self.fmt == NAMELIST_KEY:
            self._ensure_section("RIVER_FRC_SETTINGS").update(
                {
                    "river_source": True,
                    "river_analytical": False,
                    "nriv": nriv,
                }
            )
        else:
            river = self.settings_compile_time.setdefault("river_frc", {})
            river.update(
                {
                    "river_source": True,
                    "analytical": False,
                    "nriv": nriv,
                    "rvol_vname": "river_volume",
                    "rvol_tname": "river_time",
                    "rtrc_vname": "river_tracer",
                    "rtrc_tname": "river_time",
                }
            )

    def runtime_config_basename(self) -> str:
        """Primary rendered runtime config filename (without directory)."""
        return "namelist.nml" if self.fmt == NAMELIST_KEY else "roms.in"
