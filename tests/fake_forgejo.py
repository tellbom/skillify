"""A minimal in-process fake Forgejo/Gitea API server, for testing publish (T1.3)
without a live Forgejo — mirrors just the endpoints ForgejoClient calls.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest


class FakeForgejoState:
    def __init__(self) -> None:
        self.repos: set[str] = set()
        self.releases: dict[str, dict] = {}  # f"{owner}/{repo}/{tag}" -> release json
        self.latest_tag: dict[str, str] = {}  # f"{owner}/{repo}" -> most-recently-created tag
        self.asset_bytes: dict[int, bytes] = {}  # asset id -> raw uploaded bytes
        self.archives: dict[str, bytes] = {}  # f"{owner}/{repo}/{ref}" -> raw tar.gz bytes
        self.raw_files: dict[str, str] = {}  # f"{owner}/{repo}/{ref}/{path}" -> file text
        self._next_release_id = 1
        self._next_asset_id = 1
        self.required_token: str | None = None

    def new_release_id(self) -> int:
        rid = self._next_release_id
        self._next_release_id += 1
        return rid

    def new_asset_id(self) -> int:
        aid = self._next_asset_id
        self._next_asset_id += 1
        return aid


def _extract_multipart_file(body: bytes, content_type: str) -> bytes:
    """Pull the raw file bytes out of a multipart/form-data body built by `requests`."""
    boundary = content_type.split("boundary=", 1)[1].strip().encode("utf-8")
    delimiter = b"--" + boundary
    parts = body.split(delimiter)
    for part in parts:
        if b'name="attachment"' not in part:
            continue
        header_end = part.find(b"\r\n\r\n")
        if header_end == -1:
            continue
        content = part[header_end + 4 :]
        if content.endswith(b"\r\n"):
            content = content[:-2]
        return content
    raise ValueError("no 'attachment' part found in multipart body")


class FakeForgejoHandler(BaseHTTPRequestHandler):
    server: "FakeForgejoServer"

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        state = self.server.state
        if state.required_token is None:
            return True
        return self.headers.get("Authorization") == f"token {state.required_token}"

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            return self._json(401, {"message": "unauthorized"})
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        state = self.server.state

        # GET /api/v1/repos/{owner}/{repo}
        if parts[:3] == ["api", "v1", "repos"] and len(parts) == 5:
            owner, repo = parts[3], parts[4]
            if f"{owner}/{repo}" in state.repos:
                return self._json(200, {"full_name": f"{owner}/{repo}"})
            return self._json(404, {"message": "not found"})

        # GET /api/v1/repos/{owner}/{repo}/releases (list)
        if parts[:3] == ["api", "v1", "repos"] and len(parts) == 6 and parts[5] == "releases":
            owner, repo = parts[3], parts[4]
            releases = [r for key, r in state.releases.items() if key.startswith(f"{owner}/{repo}/")]
            return self._json(200, releases)

        # GET /api/v1/repos/{owner}/{repo}/releases/latest
        if parts[:3] == ["api", "v1", "repos"] and len(parts) == 7 and parts[5:7] == ["releases", "latest"]:
            owner, repo = parts[3], parts[4]
            tag = state.latest_tag.get(f"{owner}/{repo}")
            if tag is None:
                return self._json(404, {"message": "no releases"})
            return self._json(200, state.releases[f"{owner}/{repo}/{tag}"])

        # GET /api/v1/repos/{owner}/{repo}/releases/tags/{tag}
        if parts[:3] == ["api", "v1", "repos"] and len(parts) == 8 and parts[5:7] == ["releases", "tags"]:
            owner, repo, tag = parts[3], parts[4], parts[7]
            key = f"{owner}/{repo}/{tag}"
            if key in state.releases:
                return self._json(200, state.releases[key])
            return self._json(404, {"message": "not found"})

        # GET /api/v1/repos/{owner}/{repo}/raw/{path}?ref={ref}
        if parts[:3] == ["api", "v1", "repos"] and len(parts) == 7 and parts[5] == "raw":
            owner, repo, path = parts[3], parts[4], parts[6]
            ref = parse_qs(parsed.query).get("ref", [""])[0]
            key = f"{owner}/{repo}/{ref}/{path}"
            if key not in state.raw_files:
                return self._json(404, {"message": "not found"})
            body = state.raw_files[key].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # GET /repos/{owner}/{repo}/releases/download/{release_id}/{asset_name}
        # (non-API asset download URL, mirroring browser_download_url shape)
        if (
            len(parts) == 7
            and parts[0] == "repos"
            and parts[3] == "releases"
            and parts[4] == "download"
        ):
            release_id, asset_name = int(parts[5]), parts[6]
            for release in state.releases.values():
                if release["id"] != release_id:
                    continue
                for asset in release["assets"]:
                    if asset["name"] == asset_name and asset["id"] in state.asset_bytes:
                        data = state.asset_bytes[asset["id"]]
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return
            self.send_response(404)
            self.end_headers()
            return

        # GET /api/v1/repos/{owner}/{repo}/archive/{ref}.tar.gz
        if parts[:3] == ["api", "v1", "repos"] and len(parts) == 7 and parts[5] == "archive":
            owner, repo, archive_name = parts[3], parts[4], parts[6]
            ref = archive_name.removesuffix(".tar.gz")
            data = state.archives.get(f"{owner}/{repo}/{ref}")
            if data is None:
                return self._json(404, {"message": f"no archive for {owner}/{repo}@{ref}"})
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self._json(404, {"message": f"unhandled GET {self.path}"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return self._json(401, {"message": "unauthorized"})
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        state = self.server.state
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b""

        # POST /api/v1/orgs/{org}/repos
        if parts[:3] == ["api", "v1", "orgs"] and len(parts) == 5 and parts[4] == "repos":
            org = parts[3]
            data = json.loads(raw_body) if raw_body else {}
            repo_name = data.get("name")
            state.repos.add(f"{org}/{repo_name}")
            return self._json(201, {"full_name": f"{org}/{repo_name}"})

        # POST /api/v1/repos/{owner}/{repo}/releases
        if parts[:3] == ["api", "v1", "repos"] and len(parts) == 6 and parts[5] == "releases":
            owner, repo = parts[3], parts[4]
            data = json.loads(raw_body) if raw_body else {}
            tag = data["tag_name"]
            release = {
                "id": state.new_release_id(),
                "tag_name": tag,
                "html_url": f"http://fake-forgejo/{owner}/{repo}/releases/tag/{tag}",
                "assets": [],
            }
            state.releases[f"{owner}/{repo}/{tag}"] = release
            state.latest_tag[f"{owner}/{repo}"] = tag
            return self._json(201, release)

        # POST /api/v1/repos/{owner}/{repo}/releases/{id}/assets?name=...
        if parts[:3] == ["api", "v1", "repos"] and len(parts) == 8 and parts[5] == "releases" and parts[7] == "assets":
            owner, repo, release_id = parts[3], parts[4], parts[6]
            qs = parse_qs(parsed.query)
            asset_name = qs.get("name", ["unnamed"])[0]
            asset_id = state.new_asset_id()
            host = self.headers.get("Host", "127.0.0.1")
            state.asset_bytes[asset_id] = _extract_multipart_file(
                raw_body, self.headers.get("Content-Type", "")
            )
            asset = {
                "id": asset_id,
                "name": asset_name,
                "browser_download_url": f"http://{host}/repos/{owner}/{repo}/releases/download/{release_id}/{asset_name}",
            }
            # Record it against whichever release has this id.
            for release in state.releases.values():
                if release["id"] == int(release_id):
                    release["assets"].append(asset)
                    break
            return self._json(201, asset)

        self._json(404, {"message": f"unhandled POST {self.path}"})


class FakeForgejoServer(HTTPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state = FakeForgejoState()


@pytest.fixture()
def fake_forgejo():
    server = FakeForgejoServer(("127.0.0.1", 0), FakeForgejoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)
