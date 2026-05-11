"""
Runs OpenBuilder build commands.
Uses openbuilder Python API directly (not CLI subprocess) to avoid TTY/stdout issues.
"""
import os
import sys
import threading
import hashlib
import tarfile
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from build_store import update_build

# ── OpenBuilder paths ──────────────────────────────────────────────────────────
OPENBUILDER_SRC = Path("/root/workspace/code/openbuilder/src")
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace/openbuilder-workspace"))

# Add openbuilder to path
sys.path.insert(0, str(OPENBUILDER_SRC))

# ── S3 config (from workspace manifest) ───────────────────────────────────────
_S3_ENDPOINT = "http://host.docker.internal:9000"
_S3_BUCKET = "openbuilder-builds"
_S3_ACCESS_KEY = "minioadmin"
_S3_SECRET_KEY = "minioadmin"


def _get_s3_client():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=_S3_ENDPOINT,
        aws_access_key_id=_S3_ACCESS_KEY,
        aws_secret_access_key=_S3_SECRET_KEY,
        region_name="us-east-1",
        config=Config(signature_version="s3v4"),
    ), _S3_BUCKET


def _s3_upload_file_obj(data, s3_key):
    client, bucket = _get_s3_client()
    client.upload_fileobj(data, bucket, s3_key)
    return f"s3://{bucket}/{s3_key}"


def _s3_allocate_build_id():
    """Atomically allocate a new build ID from S3."""
    client, bucket = _get_s3_client()

    # List existing builds to find max ID
    try:
        response = client.list_objects_v2(Bucket=bucket, Prefix="build/")
        builds = {}
        if "Contents" in response:
            for obj in response["Contents"]:
                key = obj["Key"]
                if key.endswith("/") or key.endswith("/.lock"):
                    continue
                parts = key.split("/")
                if len(parts) >= 2 and parts[0] == "build" and parts[1].isdigit():
                    bid = int(parts[1])
                    if bid not in builds:
                        builds[bid] = True
        next_id = max(builds.keys(), default=10000) + 1
    except Exception:
        next_id = 10001

    # Reserve with lock file
    lock_key = f"build/{next_id}/.lock"
    for _ in range(10):
        try:
            client.put_object(Bucket=bucket, Key=lock_key, Body=b"")
            return next_id
        except client.exceptions.ClientError:
            next_id += 1
            lock_key = f"build/{next_id}/.lock"
    raise RuntimeError("Failed to allocate build ID")


def _calc_hash(target_dir):
    h = hashlib.sha256()
    for p in sorted(target_dir.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(target_dir).as_posix().encode())
            h.update(p.read_bytes())
    return f"sha256:{h.hexdigest()}"


def _publish_to_s3(target_dir, build_id):
    """Package target dir and upload to S3. Returns s3:// URI."""
    manifest_file = WORKSPACE_DIR / ".openbuilder" / "manifest.yaml"
    if manifest_file.exists():
        import yaml
        with manifest_file.open() as f:
            manifest_data = list(yaml.safe_load_all(f))[0] or {}
    else:
        manifest_data = {}

    target_hash = _calc_hash(target_dir)

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
        tar.add(target_dir, arcname="target")
    tar_buffer.seek(0)

    info = {
        "id": build_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "manifest": manifest_data,
        "target_hash": target_hash,
    }

    tar_key = f"build/{build_id}/target-{build_id}.tar.gz"
    _s3_upload_file_obj(tar_buffer, tar_key)

    info_bytes = json.dumps(info, indent=2).encode()
    info_key = f"build/{build_id}/build-info-{build_id}.json"
    _s3_upload_file_obj(io.BytesIO(info_bytes), info_key)

    return f"s3://{_S3_BUCKET}/{tar_key}"


def run_build(build_id: str, project: str, mode: str, platform: str, manifest: str) -> None:
    """
    Execute openbuilder build + publish in a background thread.
    Writes the user-provided manifest to the workspace, then runs openbuilder build.
    """
    def _run():
        update_build(build_id, status="running",
                     log=f"Starting build (project={project}, mode={mode}, platform={platform})...\n")

        try:
            import subprocess
            OB_PY = "/usr/local/bin/python3"

            # Ensure workspace is initialized (only if no manifest provided yet)
            WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
            ob_dir = WORKSPACE_DIR / ".openbuilder"
            ob_dir.mkdir(parents=True, exist_ok=True)

            # GitHub token for private repos (inject into URLs before writing manifest)
            github_token = os.environ.get("GITHUB_TOKEN", "")
            for r in manifest_data.get("projects", []):
                if r.get("url", "").startswith("https://github.com/"):
                    r["url"] = r["url"].replace(
                        "https://github.com/",
                        f"https://{github_token}@github.com/",
                        1,
                    )

            # Step 1: Write manifest.yaml (convert repos -> projects for openbuilder)
            update_build(build_id, log="Writing manifest.yaml...\n")
            import yaml
            manifest_data = yaml.safe_load(manifest)
            if "repos" in manifest_data and "projects" not in manifest_data:
                manifest_data["projects"] = manifest_data.pop("repos")
            # Ensure workspace section exists
            if "workspace" not in manifest_data:
                manifest_data["workspace"] = {"name": project, "current_project": project}
            # Set platform for cross-compile
            if platform:
                manifest_data["workspace"]["current_platform"] = platform
            # Inject GitHub token into project URLs
            for r in manifest_data.get("projects", []):
                if r.get("url", "").startswith("https://github.com/"):
                    r["url"] = r["url"].replace(
                        "https://github.com/",
                        f"https://{github_token}@github.com/",
                        1,
                    )
            manifest_file = ob_dir / "manifest.yaml"
            with open(manifest_file, "w") as f:
                yaml.dump(manifest_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            update_build(build_id, log=f"manifest.yaml written ({len(manifest)} bytes)\n")

            # Prepare env for subprocess
            env = os.environ.copy()
            env["PYTHONPATH"] = "/root/workspace/code/openbuilder/src"

            # Step 2: Clone repos
            update_build(build_id, log="Cloning repos...\n")
            # manifest_data already loaded above (repos converted to projects)
            repo_names = [r["name"] for r in manifest_data.get("projects", [])]
            for rname in repo_names:
                result = subprocess.run(
                    [OB_PY, "-c", "from openbuilder.cli import main; main()", "clone", rname],
                    cwd=str(WORKSPACE_DIR),
                    capture_output=True,
                    text=True,
                    env=env,
                )
                if result.returncode != 0:
                    update_build(build_id, log=f"Warning: clone {rname} failed: {result.stderr}\n")
                else:
                    update_build(build_id, log=f"Cloned {rname}\n")

            # Step 3: Run openbuilder build
            update_build(build_id, log=f"Running openbuilder build...\n")
            result = subprocess.run(
                [OB_PY, "-c", "from openbuilder.cli import main; main()", "build", "--build-type", mode],
                cwd=str(WORKSPACE_DIR),
                capture_output=True,
                text=True,
                env=env,
            )
            log = (result.stdout or "") + "\n"
            if result.returncode != 0:
                raise RuntimeError(f"Build failed: {result.stderr or result.stdout}")
            # Check if build actually produced something
            if "Build complete." not in log:
                raise RuntimeError(f"Build did not complete successfully. Output:\n{log}")
            update_build(build_id, log=log)

            # Step 4: Capture commit hashes
            update_build(build_id, log="Capturing commit hashes...\n")
            repos_info = []
            for rname in repo_names:
                src_dir = WORKSPACE_DIR / "src" / rname
                commit = ""
                if src_dir.exists():
                    res = subprocess.run(
                        ["git", "-C", str(src_dir), "rev-parse", "HEAD"],
                        capture_output=True, text=True
                    )
                    if res.returncode == 0:
                        commit = res.stdout.strip()
                repos_info.append({"name": rname, "commit": commit})
                update_build(build_id, log=f"  {rname}: {commit[:8] or '(empty)'}\n")

            # Step 5: Publish to S3
            update_build(build_id, log=log + "Allocating build ID...\n")
            build_num = _s3_allocate_build_id()
            update_build(build_id, log=log + f"Build ID: {build_num}, packaging...\n")

            target_dir = WORKSPACE_DIR / "target"
            artifact_path = _publish_to_s3(target_dir, build_num)

            update_build(
                build_id,
                status="success",
                log=log + f"Published as build {build_num}.\n",
                artifact_path=artifact_path,
                repos=repos_info,
            )

        except Exception as e:
            update_build(
                build_id,
                status="failed",
                log=f"Build failed: {str(e)}\n",
                error=str(e),
            )

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
