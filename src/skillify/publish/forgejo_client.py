"""Minimal Forgejo REST client — repo/release/asset operations needed by `skillctl publish` (T1.3).

Forgejo's API v1 is a compatible fork of Gitea's; endpoints here follow the documented
Gitea/Forgejo swagger (`/api/v1/repos/...`, `/api/v1/orgs/...`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


class ForgejoError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass
class ReleaseAsset:
    id: int
    name: str
    browser_download_url: str


@dataclass
class Release:
    id: int
    tag_name: str
    html_url: str
    assets: list[ReleaseAsset]
    name: str = ""
    body: str = ""
    draft: bool = False
    published_at: str | None = None


@dataclass
class Repository:
    owner: str
    name: str


class ForgejoClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"token {token}"

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.base_url}/api/v1{path}"
        try:
            resp = self._session.request(method, url, timeout=self._timeout, **kwargs)
        except requests.RequestException as exc:
            raise ForgejoError(f"{method} {url} failed: {exc}") from exc
        return resp

    def current_username(self) -> str:
        resp = self._request("GET", "/user")
        if resp.status_code != 200:
            raise ForgejoError(
                f"failed to resolve Forgejo service-account username: HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        data = resp.json()
        username = data.get("login") or data.get("username")
        if not username:
            raise ForgejoError("Forgejo /user response did not contain a username")
        return str(username)

    def repo_exists(self, owner: str, repo: str) -> bool:
        resp = self._request("GET", f"/repos/{owner}/{repo}")
        if resp.status_code == 200:
            return True
        if resp.status_code == 404:
            return False
        raise ForgejoError(
            f"unexpected status checking repo {owner}/{repo}: {resp.status_code}",
            status_code=resp.status_code,
            body=resp.text,
        )

    def create_org_repo(self, org: str, repo: str, *, private: bool = False) -> None:
        resp = self._request(
            "POST", f"/orgs/{org}/repos", json={"name": repo, "private": private, "auto_init": True}
        )
        if resp.status_code not in (200, 201):
            raise ForgejoError(
                f"failed to create repo {org}/{repo}: HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )

    def ensure_org_repo(self, org: str, repo: str, *, private: bool = False) -> None:
        if not self.repo_exists(org, repo):
            self.create_org_repo(org, repo, private=private)

    def get_release_by_tag(self, owner: str, repo: str, tag_name: str) -> Release | None:
        resp = self._request("GET", f"/repos/{owner}/{repo}/releases/tags/{tag_name}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise ForgejoError(
                f"failed to look up release {tag_name}: HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return self._release_from_json(resp.json())

    def get_latest_release(self, owner: str, repo: str) -> Release | None:
        resp = self._request("GET", f"/repos/{owner}/{repo}/releases/latest")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise ForgejoError(
                f"failed to look up latest release for {owner}/{repo}: HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return self._release_from_json(resp.json())

    def list_releases(self, owner: str, repo: str) -> list[Release]:
        releases: list[Release] = []
        page = 1
        while True:
            resp = self._request(
                "GET", f"/repos/{owner}/{repo}/releases", params={"limit": 50, "page": page}
            )
            if resp.status_code != 200:
                raise ForgejoError(
                    f"failed to list releases for {owner}/{repo}: HTTP {resp.status_code}",
                    status_code=resp.status_code,
                    body=resp.text,
                )
            batch = [self._release_from_json(item) for item in resp.json()]
            releases.extend(batch)
            if len(batch) < 50:
                return releases
            page += 1

    def list_repositories(self) -> list[Repository]:
        """List repositories visible to the configured Forgejo service account."""
        repositories: list[Repository] = []
        page = 1
        while True:
            resp = self._request("GET", "/user/repos", params={"limit": 50, "page": page})
            if resp.status_code != 200:
                raise ForgejoError(
                    f"failed to list service-account repositories: HTTP {resp.status_code}",
                    status_code=resp.status_code,
                    body=resp.text,
                )
            payload = resp.json()
            for item in payload:
                owner = item.get("owner", {}).get("login") or item.get("owner", {}).get("username")
                if owner and item.get("name"):
                    repositories.append(Repository(owner=owner, name=item["name"]))
            if len(payload) < 50:
                return repositories
            page += 1

    def find_release_by_tag(self, owner: str, repo: str, tag_name: str) -> Release | None:
        """Find a published or draft release for ``tag_name``."""
        release = self.get_release_by_tag(owner, repo, tag_name)
        if release is not None:
            return release
        return next((item for item in self.list_releases(owner, repo) if item.tag_name == tag_name), None)

    def get_raw_file(self, owner: str, repo: str, path: str, ref: str) -> str | None:
        """Fetch a file's raw content at `ref` (branch/tag/sha) — T3.1: used to render a
        skill's README/SKILL.md on the web without needing a local checkout. Returns None
        if the file doesn't exist at that ref (not every skill ships a README)."""
        resp = self._request("GET", f"/repos/{owner}/{repo}/raw/{path}", params={"ref": ref})
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise ForgejoError(
                f"failed to fetch {owner}/{repo}/{path}@{ref}: HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.text

    def download_archive(self, owner: str, repo: str, ref: str, dest_path: Path) -> None:
        """Download a source snapshot at `ref` (branch/tag/sha) as a tarball —
        `GET /repos/{owner}/{repo}/archive/{ref}.tar.gz` (T2.1: webhook packaging service
        fetches the pushed tag's tree this way instead of needing a local git checkout)."""
        url = f"{self.base_url}/api/v1/repos/{owner}/{repo}/archive/{ref}.tar.gz"
        self.download(url, dest_path)

    def download(self, url: str, dest_path: Path) -> None:
        """Download an asset URL (e.g. a release asset's browser_download_url)
        using this client's authenticated session — needed for private repos."""
        try:
            resp = self._session.get(url, timeout=self._timeout, stream=True)
        except requests.RequestException as exc:
            raise ForgejoError(f"GET {url} failed: {exc}") from exc
        if resp.status_code != 200:
            raise ForgejoError(
                f"failed to download {url}: HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                fh.write(chunk)

    def fetch_text(self, url: str) -> str:
        """Fetch a small asset (e.g. `.sha256`/`.artifact.json`) as text, authenticated."""
        try:
            resp = self._session.get(url, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ForgejoError(f"GET {url} failed: {exc}") from exc
        if resp.status_code != 200:
            raise ForgejoError(
                f"failed to fetch {url}: HTTP {resp.status_code}", status_code=resp.status_code, body=resp.text
            )
        return resp.text

    def create_release(
        self, owner: str, repo: str, *, tag_name: str, name: str, body: str = "", draft: bool = False
    ) -> Release:
        resp = self._request(
            "POST",
            f"/repos/{owner}/{repo}/releases",
            json={"tag_name": tag_name, "name": name, "body": body, "draft": draft, "prerelease": False},
        )
        if resp.status_code not in (200, 201):
            raise ForgejoError(
                f"failed to create release {tag_name} for {owner}/{repo}: HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return self._release_from_json(resp.json())

    def update_release(
        self,
        owner: str,
        repo: str,
        release_id: int,
        *,
        tag_name: str,
        name: str,
        body: str,
        draft: bool,
    ) -> Release:
        resp = self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/releases/{release_id}",
            json={"tag_name": tag_name, "name": name, "body": body, "draft": draft, "prerelease": False},
        )
        if resp.status_code != 200:
            raise ForgejoError(
                f"failed to update release {release_id} for {owner}/{repo}: HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return self._release_from_json(resp.json())

    def upload_release_asset(self, owner: str, repo: str, release_id: int, file_path: Path) -> ReleaseAsset:
        with open(file_path, "rb") as fh:
            resp = self._request(
                "POST",
                f"/repos/{owner}/{repo}/releases/{release_id}/assets",
                params={"name": file_path.name},
                files={"attachment": (file_path.name, fh, "application/octet-stream")},
            )
        if resp.status_code not in (200, 201):
            raise ForgejoError(
                f"failed to upload asset {file_path.name}: HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        data = resp.json()
        return ReleaseAsset(
            id=data["id"], name=data["name"], browser_download_url=data["browser_download_url"]
        )

    @staticmethod
    def _release_from_json(data: dict[str, Any]) -> Release:
        assets = [
            ReleaseAsset(id=a["id"], name=a["name"], browser_download_url=a["browser_download_url"])
            for a in data.get("assets", [])
        ]
        return Release(
            id=data["id"],
            tag_name=data["tag_name"],
            html_url=data["html_url"],
            assets=assets,
            name=data.get("name", ""),
            body=data.get("body", ""),
            draft=bool(data.get("draft", False)),
            published_at=data.get("published_at") or data.get("created_at"),
        )
