"""Build agent: clone repo, checkout commit, build APK."""

import subprocess
from pathlib import Path

from .base import SetupAgent


class BuildAgent(SetupAgent):
    """Handles source code checkout and APK building.

    Outputs ``apk_path`` into the shared context so downstream agents
    (e.g. AppAgent) can install it.
    """

    name = "build"
    actions = {
        "checkout_and_build": "Checkout a git commit and build the APK (params: commit, repo_url, repo_path)",
        "checkout": "Checkout a git commit without building (params: commit, repo_path)",
        "build": "Build APK from current checkout (params: repo_path, build_variant)",
    }

    def __init__(
        self,
        default_repo_path: str | None = None,
        default_repo_url: str | None = None,
        default_build_variant: str = "alphaDebug",
    ):
        self.default_repo_path = default_repo_path
        self.default_repo_url = default_repo_url
        self.default_build_variant = default_build_variant

    def execute(self, action: str, device, params: dict) -> str:
        repo_path = params.get("repo_path", self.default_repo_path)
        repo_url = params.get("repo_url", self.default_repo_url)
        commit = params.get("commit", "")
        variant = params.get("build_variant", self.default_build_variant)

        if action == "checkout_and_build":
            self._ensure_repo(repo_path, repo_url)
            self._checkout(repo_path, commit)
            apk_path = self._build(repo_path, variant)
            params["apk_path"] = apk_path
            return f"built {apk_path} at {commit}"

        elif action == "checkout":
            self._ensure_repo(repo_path, repo_url)
            self._checkout(repo_path, commit)
            return f"checked out {commit}"

        elif action == "build":
            apk_path = self._build(repo_path, variant)
            params["apk_path"] = apk_path
            return f"built {apk_path}"

        return f"unknown action: {action}"

    def _ensure_repo(self, repo_path: str | None, repo_url: str | None) -> None:
        """Clone repo if it doesn't exist."""
        if repo_path and not Path(repo_path).exists() and repo_url:
            subprocess.run(
                ["git", "clone", "--depth", "500", repo_url, repo_path],
                check=True,
                timeout=300,
            )

    def _checkout(self, repo_path: str | None, commit: str) -> None:
        """Checkout a specific commit."""
        if not repo_path or not commit:
            return
        subprocess.run(
            ["git", "checkout", commit],
            cwd=repo_path,
            check=True,
            timeout=30,
        )

    def _build(self, repo_path: str | None, variant: str) -> str:
        """Run Gradle build and return APK path."""
        if not repo_path:
            raise ValueError("repo_path is required for build")

        task = f"assemble{variant[0].upper()}{variant[1:]}"
        subprocess.run(
            ["./gradlew", task],
            cwd=repo_path,
            check=True,
            timeout=600,
        )
        # Convention: app/build/outputs/apk/<flavor>/<type>/app-<flavor>-<type>.apk
        flavor = variant[:-5]
        build_type = variant[-5:].lower()
        apk_path = (
            Path(repo_path)
            / "app"
            / "build"
            / "outputs"
            / "apk"
            / flavor
            / build_type
            / f"app-{flavor}-{build_type}.apk"
        )
        if not apk_path.exists():
            raise FileNotFoundError(f"APK not found at {apk_path}")
        return str(apk_path)
