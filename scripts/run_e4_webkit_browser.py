#!/usr/bin/env python3
"""Rehearse public Mini App HTML in isolated non-root WebKit with no network.

Uses an explicit pinned browser runtime/systemd and locked playwright-core; no application
configuration, credentials, customer data or production API is used.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stop_and_verify(unit):
    """Never interpret failed/empty systemctl output as a stopped browser."""
    subprocess.run(["systemctl", "stop", unit], capture_output=True, timeout=30)
    state = subprocess.run(
        ["systemctl", "show", unit, "-p", "LoadState", "-p", "ActiveState", "-p", "MainPID"],
        capture_output=True, text=True, timeout=10)
    fields = dict(line.split("=", 1) for line in state.stdout.splitlines() if "=" in line)
    if (state.returncode != 0 or fields.get("LoadState") not in ("loaded", "not-found")
            or fields.get("ActiveState") not in ("inactive", "failed")
            or fields.get("MainPID") != "0"):
        raise RuntimeError("browser stop unverified; disposable files retained")
    cgroup = Path("/sys/fs/cgroup/system.slice") / (unit + ".service")
    # A transient collected unit normally has no cgroup. If it still exists,
    # require its hierarchy to contain no process, including detached children.
    if cgroup.exists():
        procs = list(cgroup.rglob("cgroup.procs"))
        if not procs or any(p.read_text().strip() for p in procs):
            raise RuntimeError("browser cgroup not empty; disposable files retained")
    return {**fields, "cgroupEmpty": True}


def tree_digest(path):
    """Bind runtime files and internal links without following links outside it."""
    entries = []
    for item in sorted(path.rglob('*')):
        relative = item.relative_to(path).as_posix()
        if item.is_symlink():
            if not item.resolve().is_relative_to(path.resolve()):
                raise RuntimeError('runtime symlink escapes root')
            entries.append([relative, 'link', os.readlink(item)])
        elif item.is_file():
            entries.append([relative, 'file', digest(item)])
        elif not item.is_dir():
            raise RuntimeError('unexpected runtime entry')
    if not entries:
        raise RuntimeError('empty browser runtime')
    return hashlib.sha256(json.dumps(entries, separators=(',', ':')).encode()).hexdigest()


def runtime_path(value):
    path = value.resolve(strict=True)
    if not path.is_dir() or not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(path)):
        raise RuntimeError('runtime path must be an existing plain absolute directory')
    return path


def run(source, output, root, runtime, runner_source=None, library_path=None):
    runtime = runtime_path(runtime)
    if library_path is not None:
        library_path = runtime_path(library_path)
    runtime_hash = tree_digest(runtime)
    library_hash = tree_digest(library_path) if library_path else None
    runner_source = runner_source or root / 'tests/e4_wallet_webkit_browser.cjs'
    unit = "e4-webkit-browser-" + uuid.uuid4().hex
    stage = Path(tempfile.mkdtemp(prefix="e4-webkit-browser-"))
    launch_attempted = False
    stopped = False
    try:
        stage.chmod(0o755)
        shutil.copyfile(source, stage / "webapp.html")
        shutil.copyfile(runner_source, stage / "runner.cjs")
        # The supervisor's private umask must not hide public/synthetic inputs.
        for name in ("webapp.html", "runner.cjs"):
            (stage / name).chmod(0o644)
        (stage / "node_modules").mkdir()
        (stage / "node_modules").chmod(0o755)
        shutil.copytree(root / "node_modules/playwright-core", stage / "node_modules/playwright-core")
        source_hash = digest(stage / "webapp.html")
        runner_hash = digest(stage / "runner.cjs")
        for name in ("xdg-config", "xdg-cache", "results"):
            directory = stage / name
            directory.mkdir(mode=0o700)
            os.chown(directory, 65534, 65534)
        package_hash = tree_digest(stage / 'node_modules/playwright-core')
        command = ["systemd-run", "--unit=" + unit, "--wait", "--pipe", "--collect",
                   "--property=User=nobody", "--property=PrivateNetwork=yes",
                   "--property=ProtectHome=yes", "--property=KillMode=control-group",
                   "--property=NoNewPrivileges=yes", "--property=LimitCORE=0",
                   "--property=BindReadOnlyPaths=" + str(runtime) + (" " + str(library_path) if library_path else ""),
                   "--property=RuntimeMaxSec=180",
                   "--working-directory=" + str(stage),
                   "--setenv=XDG_CONFIG_HOME=" + str(stage / "xdg-config"),
                   "--setenv=XDG_CACHE_HOME=" + str(stage / "xdg-cache"),
                   "--setenv=PLAYWRIGHT_BROWSERS_PATH=" + str(runtime),
                   *(["--setenv=LD_LIBRARY_PATH=" + str(library_path)] if library_path else []),
                   "/usr/bin/node", str(stage / "runner.cjs"), str(stage / "webapp.html"),
                   str(stage / "results")]
        launch_attempted = True
        try:
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=210)
            except subprocess.TimeoutExpired:
                result = subprocess.CompletedProcess(command, 124, '', 'browser supervisor timeout')
        finally:
            state = stop_and_verify(unit)
            stopped = True
        for artifact in (stage / "results").iterdir():
            if artifact.is_symlink() or not artifact.is_file():
                raise RuntimeError("unexpected browser artifact")
            shutil.copyfile(artifact, output / artifact.name)
        report_path = output / "report.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        if report and (report.get("sourceSha256") != source_hash
                       or report.get("runnerSha256") != runner_hash):
            raise RuntimeError("browser evidence does not match staged inputs")
        if tree_digest(runtime) != runtime_hash or (library_path and tree_digest(library_path) != library_hash):
            raise RuntimeError('browser runtime changed during acceptance')
        isolation = {"user": "nobody", "engine": "webkit", "engineSandbox": "NOT_ATTESTED", "privateNetwork": True,
                     "noNewPrivileges": True, "runtimeReadOnly": True,
                     "runtimePath": str(runtime), "runtimeTreeSha256": runtime_hash,
                     "libraryPath": str(library_path) if library_path else None, "libraryTreeSha256": library_hash,
                     "playwrightTreeSha256": package_hash, "launcherSha256": digest(Path(__file__)),
                     "protectHome": True, "unit": unit, "unitStopped": True,
                     "stopObservation": state, "sourceSha256": source_hash,
                     "runnerSha256": runner_hash, "processExitCode": result.returncode}
        (output / "isolation.json").write_text(json.dumps(isolation, indent=2) + "\n")
        print(json.dumps(isolation))
        if result.returncode:
            print(result.stderr[-5000:])
        if report:
            print(json.dumps(report, indent=2))
        return result.returncode if result.returncode else (0 if report.get("result") == "PASS" else 1)
    finally:
        if not launch_attempted or stopped:
            shutil.rmtree(stage)
        else:
            print("Unverified cleanup; retain disposable unit " + unit + " and " + str(stage))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("relay/webapp.html"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--runner", type=Path, default=Path('tests/e4_wallet_webkit_browser.cjs'))
    parser.add_argument("--library-path", type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("host root is needed to create the isolated non-root service")
    if args.output.exists():
        parser.error("output must be a new directory; do not overwrite evidence")
    args.output.mkdir(parents=True)
    return run(args.source.resolve(), args.output, Path(__file__).resolve().parents[1], args.runtime, args.runner.resolve(), args.library_path)


if __name__ == "__main__":
    raise SystemExit(main())
