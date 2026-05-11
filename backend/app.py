"""
OpenBuilder Web UI - Flask Backend
Minimal API server that wraps OpenBuilder CLI for web access.
"""
import os
import tempfile
import threading
from flask import Flask, jsonify, request, send_file, send_from_directory
from pathlib import Path

import yaml

from build_store import create_build, get_build, get_all_builds, update_build
from build_runner import run_build

import boto3
from botocore.config import Config

app = Flask(__name__, static_folder=None)

# Paths
BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace/openbuilder-workspace"))


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route("/api/projects", methods=["GET"])
def list_projects():
    """Return all projects found in the config repo."""
    projects_dir = WORKSPACE_DIR / ".openbuilder" / "projects"
    if not projects_dir.is_dir():
        return jsonify({"projects": []})

    projects = []
    for entry in sorted(projects_dir.iterdir()):
        manifest_path = entry / "manifest.yaml"
        if entry.is_dir() and manifest_path.exists():
            try:
                data = yaml.safe_load(manifest_path.read_text())
                projects.append({
                    "name": data.get("name", entry.name),
                    "description": data.get("description", ""),
                    "manifest_path": f"projects/{entry.name}/manifest.yaml",
                })
            except Exception:
                projects.append({
                    "name": entry.name,
                    "description": "",
                    "manifest_path": f"projects/{entry.name}/manifest.yaml",
                })

    return jsonify({"projects": projects})


@app.route("/api/builds/compare", methods=["GET"])
def compare_builds():
    """Compare two builds side by side."""
    left_id = request.args.get("left")
    right_id = request.args.get("right")

    if not left_id or not right_id:
        return jsonify({"error": "Both 'left' and 'right' query parameters are required"}), 400

    left = get_build(left_id)
    right = get_build(right_id)

    if not left:
        return jsonify({"error": f"Build '{left_id}' not found"}), 404
    if not right:
        return jsonify({"error": f"Build '{right_id}' not found"}), 404

    def get_project_repos(project_name):
        """Read repos from the project's manifest.yaml."""
        manifest_path = WORKSPACE_DIR / ".openbuilder" / "projects" / project_name / "manifest.yaml"
        if not manifest_path.exists():
            return []
        try:
            import yaml
            with open(manifest_path) as f:
                data = yaml.safe_load(f)
            repos = data.get("repos", [])
            return [{ "name": r["name"], "url": r.get("url", ""), "revision": r.get("revision", "") } for r in repos]
        except Exception:
            return []

    # Prefer repos stored in build record (has commit hashes), fallback to manifest
    left_repos_raw = left.get("repos", []) or get_project_repos(left.get("project", ""))
    right_repos_raw = right.get("repos", []) or get_project_repos(right.get("project", ""))

    left_repos = {r["name"]: r for r in left_repos_raw}
    right_repos = {r["name"]: r for r in right_repos_raw}

    all_repo_names = sorted(set(left_repos.keys()) | set(right_repos.keys()))

    repo_comparisons = []
    for name in all_repo_names:
        in_left = name in left_repos
        in_right = name in right_repos
        if in_left and in_right:
            lc = left_repos[name].get("commit", "")
            rc = right_repos[name].get("commit", "")
            if lc and rc and lc != rc:
                repo_comparisons.append({"name": name, "status": "modified", "left_commit": lc, "right_commit": rc})
            else:
                repo_comparisons.append({"name": name, "status": "unchanged"})
        elif in_left:
            repo_comparisons.append({"name": name, "status": "left_only"})
        else:
            repo_comparisons.append({"name": name, "status": "right_only"})

    return jsonify({
        "left": {
            "id": left["id"],
            "project": left.get("project", "-"),
            "mode": left.get("mode", left.get("build_type", "-")),
            "platform": left.get("platform", "-"),
            "status": left.get("status", "-"),
        },
        "right": {
            "id": right["id"],
            "project": right.get("project", "-"),
            "mode": right.get("mode", right.get("build_type", "-")),
            "platform": right.get("platform", "-"),
            "status": right.get("status", "-"),
        },
        "summary": {
            "same_project": left.get("project") == right.get("project"),
            "same_platform": left.get("platform") == right.get("platform"),
            "same_mode": left.get("mode") == right.get("mode"),
            "total_repos_left": len(left_repos),
            "total_repos_right": len(right_repos),
        },
        "repo_comparisons": repo_comparisons,
    })


@app.route("/api/manifest", methods=["GET"])
def get_workspace_manifest():
    """Return current manifest.yaml content from the workspace."""
    manifest_file = WORKSPACE_DIR / ".openbuilder" / "manifest.yaml"
    if not manifest_file.exists():
        return jsonify({"content": ""})
    try:
        content = manifest_file.read_text()
        return jsonify({"content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/projects/<project_name>/manifest", methods=["GET"])
def get_project_manifest(project_name: str):
    """Return the manifest template for a given project from the config repo.

    The config repo is cloned into .openbuilder/ with projects under .openbuilder/projects/<name>/manifest.yaml.
    """
    # Config repo content (including projects/) lives directly in .openbuilder/
    projects_dir = WORKSPACE_DIR / ".openbuilder" / "projects"
    project_manifest_path = projects_dir / project_name / "manifest.yaml"

    if not project_manifest_path.exists():
        return jsonify({
            "content": "",
            "error": f"Project '{project_name}' not found (looked in {project_manifest_path})"
        }), 404

    try:
        content = project_manifest_path.read_text()
        return jsonify({"content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/builds", methods=["GET"])
def list_builds():
    """Return all builds, newest first."""
    builds = get_all_builds()
    return jsonify({"builds": builds})


@app.route("/api/builds", methods=["POST"])
def create_new_build():
    """Create and start a new build."""
    data = request.get_json() or {}

    project  = data.get("project", "demo")
    mode     = data.get("mode", "release")
    platform = data.get("platform", "linux-x86_64")
    manifest = data.get("manifest", "")

    # Validate platform
    valid_platforms = ["linux-arm64", "linux-armv7", "linux-x86_64"]
    if platform not in valid_platforms:
        return jsonify({"error": f"Invalid platform. Must be one of: {valid_platforms}"}), 400

    # Create build record
    build = create_build(project=project, mode=mode, platform=platform)

    # Start build in background (uses fixed workspace at ~/workspace/openbuilder-workspace)
    run_build(build["id"], project, mode, platform, manifest)

    return jsonify({"id": build["id"], "status": build["status"]}), 201


@app.route("/api/builds/<build_id>", methods=["GET"])
def get_build_info(build_id: str):
    """Get details of a specific build."""
    build = get_build(build_id)
    if not build:
        return jsonify({"error": "Build not found"}), 404
    return jsonify(build)


@app.route("/api/builds/<build_id>/download", methods=["GET"])
def download_artifact(build_id: str):
    """Download the artifact for a completed build from S3."""
    build = get_build(build_id)
    if not build:
        return jsonify({"error": "Build not found"}), 404

    if build["status"] != "success":
        return jsonify({"error": "Build not ready for download"}), 400

    artifact_path = build.get("artifact_path", "")
    if not artifact_path:
        return jsonify({"error": "No artifact path recorded"}), 404

    # S3 path format: "s3://bucket/key"
    if artifact_path.startswith("s3://"):
        parts = artifact_path[5:].split("/", 1)
        bucket = parts[0]
        s3_key = parts[1] if len(parts) > 1 else ""

        s3_client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("OPENBUILDER_S3_ENDPOINT", "http://localhost:9000"),
            aws_access_key_id=os.environ.get("OPENBUILDER_S3_ACCESS_KEY_ID", "minioadmin"),
            aws_secret_access_key=os.environ.get("OPENBUILDER_S3_SECRET_ACCESS_KEY", "minioadmin"),
            region_name=os.environ.get("OPENBUILDER_S3_REGION", "us-east-1"),
            config=Config(signature_version="s3v4"),
        )

        filename = os.path.basename(s3_key)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp:
            tmp_path = tmp.name

        s3_client.download_file(bucket, s3_key, tmp_path)

        # Clean up temp file after sending
        return send_file(tmp_path, as_attachment=True, download_name=filename)

    # Local file fallback
    local_path = Path(artifact_path)
    if not local_path.exists():
        return jsonify({"error": "Artifact file not found"}), 404
    return send_file(local_path, as_attachment=True, download_name=local_path.name)


@app.route("/api/builds/<build_id>", methods=["DELETE"])
def cancel_build(build_id: str):
    """Cancel or delete a build."""
    build = get_build(build_id)
    if not build:
        return jsonify({"error": "Build not found"}), 404

    # For pending/running builds, mark as cancelled
    if build["status"] in ("pending", "running"):
        update_build(build_id, status="cancelled")
        return jsonify({"status": "cancelled"})

    # Remove from store
    # (simplified - just mark as deleted)
    update_build(build_id, status="deleted")
    return jsonify({"status": "deleted"})


# ---------------------------------------------------------------------------
# Serve frontend static files
# ---------------------------------------------------------------------------

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

@app.route("/")
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.route("/<path:filename>")
def serve_static(filename):
    return send_from_directory(FRONTEND_DIR, filename)


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("OpenBuilder Web UI starting on http://localhost:8080")
    app.run(host="0.0.0.0", port=8080, debug=True)
