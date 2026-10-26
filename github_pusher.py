"""
GitHub Pusher - drop a project .zip, enter repo + token, push to GitHub.

Requirements:
    pip install customtkinter tkinterdnd2
    git must be installed (git --version)

Run:
    python github_pusher.py
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from tkinter import filedialog

import customtkinter as ctk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

# ------------------------------------------------------------------ theme
BG = "#0b0e1c"
CARD = "#141831"
CARD_2 = "#1b2040"
BORDER = "#2b3263"
ACCENT = "#7c5cff"
ACCENT_HOVER = "#6a4bf0"
GREEN = "#2ecc71"
RED = "#ff5c7a"
TEXT = "#e8eaff"
MUTED = "#8b93c9"

IGNORED_NAMES = {"__MACOSX", ".DS_Store", "Thumbs.db"}


# ---------------------------------------------------------------- helpers
def parse_repo_url(url: str):
    url = url.strip()
    m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url)
    if m:
        return m.group(1), m.group(2)
    m = re.fullmatch(r"([^/\s]+)/([^/\s]+?)(?:\.git)?", url)
    if m:
        return m.group(1), m.group(2)
    return None


def safe_extract(zip_path, dest):
    dest_abs = os.path.abspath(dest)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            parts = member.filename.replace("\\", "/").split("/")
            if any(p in IGNORED_NAMES for p in parts):
                continue
            target = os.path.abspath(os.path.join(dest_abs, member.filename))
            if not target.startswith(dest_abs + os.sep) and target != dest_abs:
                raise ValueError(f"Suspicious path in zip: {member.filename}")
            zf.extract(member, dest_abs)


def find_project_root(extracted):
    entries = [e for e in os.listdir(extracted) if e not in IGNORED_NAMES]
    if len(entries) == 1 and os.path.isdir(os.path.join(extracted, entries[0])):
        return os.path.join(extracted, entries[0])
    return extracted


def github_api(path, token):
    """Returns (status, json_or_None, headers)."""
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "github-pusher",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode()), r.headers
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = None
        return e.code, body, e.headers
    except Exception as e:  # network error
        return 0, {"message": str(e)}, {}


# -------------------------------------------------------------------- app
class App(ctk.CTk, *( [TkinterDnD.DnDWrapper] if HAS_DND else [] )):
    def __init__(self):
        super().__init__()
        if HAS_DND:
            self.TkdndVersion = TkinterDnD._require(self)

        ctk.set_appearance_mode("dark")
        self.title("GitHub Pusher")
        self.geometry("900x700")
        self.minsize(640, 520)
        self.configure(fg_color=BG)
        self.after(150, self._maximize)

        self.zip_path = None
        self.show_token = ctk.BooleanVar(value=False)
        self.force = ctk.BooleanVar(value=False)

        self._build()

        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
            self.dnd_bind("<<DropEnter>>", lambda e: self.drop.configure(border_color=ACCENT))
            self.dnd_bind("<<DropLeave>>", lambda e: self.drop.configure(border_color=BORDER))

    # ------------------------------------------------------------- layout
    def _maximize(self):
        try:
            self.state("zoomed")  # Windows / some Linux WMs
        except Exception:
            try:
                self.attributes("-zoomed", True)  # most Linux desktops
            except Exception:
                pass

    def _build(self):
        # scrollable, so nothing is ever cut off on small screens
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        wrap = ctk.CTkFrame(scroll, fg_color="transparent")
        wrap.pack(fill="x", padx=26, pady=18)

        # header
        head = ctk.CTkFrame(wrap, fg_color="transparent")
        head.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(head, text="GitHub Pusher",
                     font=ctk.CTkFont(size=30, weight="bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(head, text="Drop your project .zip and push it to GitHub in one click.",
                     font=ctk.CTkFont(size=13), text_color=MUTED).pack(anchor="w")

        # drop zone
        self.drop = ctk.CTkFrame(wrap, fg_color=CARD, corner_radius=26, border_width=2,
                                 border_color=BORDER, height=150, cursor="hand2")
        self.drop.pack(fill="x", pady=(0, 14))
        self.drop.pack_propagate(False)
        self.drop_icon = ctk.CTkLabel(self.drop, text="⬆", font=ctk.CTkFont(size=34),
                                      text_color=ACCENT)
        self.drop_icon.pack(pady=(26, 0))
        self.drop_title = ctk.CTkLabel(
            self.drop,
            text="Drag & drop your .zip here" if HAS_DND else "Click to choose your .zip",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT)
        self.drop_title.pack()
        self.drop_sub = ctk.CTkLabel(
            self.drop,
            text="or click to browse" if HAS_DND else "(install tkinterdnd2 for drag & drop)",
            font=ctk.CTkFont(size=12), text_color=MUTED)
        self.drop_sub.pack()
        for w in (self.drop, self.drop_icon, self.drop_title, self.drop_sub):
            w.bind("<Button-1>", lambda e: self._browse())

        # form card
        form = ctk.CTkFrame(wrap, fg_color=CARD, corner_radius=26)
        form.pack(fill="x", pady=(0, 14))
        inner = ctk.CTkFrame(form, fg_color="transparent")
        inner.pack(fill="x", padx=22, pady=20)

        self.repo = self._field(inner, "Repository URL", "https://github.com/user/repo")

        ctk.CTkLabel(inner, text="Access token", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=MUTED).pack(anchor="w", pady=(12, 4))
        trow = ctk.CTkFrame(inner, fg_color="transparent")
        trow.pack(fill="x")
        self.token = ctk.CTkEntry(trow, height=42, corner_radius=14, show="•",
                                  fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
                                  placeholder_text="ghp_xxxxxxxxxxxxxxxx")
        self.token.pack(side="left", fill="x", expand=True)
        ctk.CTkSwitch(trow, text="Show", variable=self.show_token, command=self._toggle_token,
                      progress_color=ACCENT, text_color=MUTED, width=70).pack(side="left", padx=(12, 0))

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x", pady=(12, 0))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=3)
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        right = ctk.CTkFrame(row, fg_color="transparent")
        right.grid(row=0, column=1, sticky="ew")
        self.branch = self._field(left, "Branch", "main", pad=0)
        self.branch.insert(0, "main")
        self.message = self._field(right, "Commit message", "Initial commit", pad=0)
        self.message.insert(0, "Initial commit")

        ctk.CTkSwitch(inner, text="Force push (replace existing content on that branch)",
                      variable=self.force, progress_color=RED, text_color=MUTED
                      ).pack(anchor="w", pady=(16, 0))

        # button + progress
        self.btn = ctk.CTkButton(wrap, text="Push to GitHub", height=52, corner_radius=26,
                                 font=ctk.CTkFont(size=16, weight="bold"),
                                 fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self._start)
        self.btn.pack(fill="x", pady=(0, 10))
        self.progress = ctk.CTkProgressBar(wrap, height=6, corner_radius=3,
                                           progress_color=ACCENT, fg_color=CARD_2,
                                           mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 12))
        self.progress.set(0)

        # status line: always visible right under the button
        self.status = ctk.CTkLabel(wrap, text="", justify="left", anchor="w", wraplength=760,
                                   font=ctk.CTkFont(size=14, weight="bold"), text_color=MUTED)
        self.status.pack(fill="x", pady=(0, 10))

        # log card
        self.log = ctk.CTkTextbox(wrap, height=260, corner_radius=22, fg_color=CARD,
                                  text_color="#c9d0ff",
                                  font=ctk.CTkFont(family="monospace", size=12),
                                  border_width=1, border_color=BORDER, wrap="word")
        self.log.pack(fill="x")
        self.log.configure(state="disabled")
        self.log.tag_config("ok", foreground=GREEN)
        self.log.tag_config("err", foreground=RED)

    def _field(self, parent, label, placeholder, pad=12):
        ctk.CTkLabel(parent, text=label, font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=MUTED).pack(anchor="w", pady=(pad, 4))
        e = ctk.CTkEntry(parent, height=42, corner_radius=14, fg_color=CARD_2,
                         border_color=BORDER, text_color=TEXT, placeholder_text=placeholder)
        e.pack(fill="x")
        return e

    def _toggle_token(self):
        self.token.configure(show="" if self.show_token.get() else "•")

    # ------------------------------------------------------------ helpers
    def _log(self, text, tag=None):
        def _do():
            self.log.configure(state="normal")
            self.log.insert("end", text + "\n", tag) if tag else self.log.insert("end", text + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
            if tag:
                self.status.configure(text=text.strip(),
                                      text_color=GREEN if tag == "ok" else RED)
        self.after(0, _do)

    def _busy(self, busy):
        def _do():
            self.btn.configure(state="disabled" if busy else "normal",
                               text="Pushing..." if busy else "Push to GitHub")
            if busy:
                self.progress.start()
            else:
                self.progress.stop()
                self.progress.set(0)
        self.after(0, _do)

    def _browse(self):
        p = filedialog.askopenfilename(title="Choose project zip",
                                       filetypes=[("Zip files", "*.zip"), ("All files", "*.*")])
        if p:
            self._set_zip(p)

    def _on_drop(self, event):
        self.drop.configure(border_color=BORDER)
        paths = self.tk.splitlist(event.data)
        if paths:
            self._set_zip(paths[0])

    def _set_zip(self, path):
        if not path.lower().endswith(".zip"):
            self._log("Please choose a .zip file.", "err")
            return
        self.zip_path = path
        self.drop.configure(border_color=GREEN)
        self.drop_icon.configure(text="✔", text_color=GREEN)
        self.drop_title.configure(text=os.path.basename(path))
        self.drop_sub.configure(text=path)

    def _run(self, args, cwd, secret=None):
        shown = " ".join(args)
        if secret:
            shown = shown.replace(secret, "***")
        self._log("$ " + shown)
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        p = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (p.stdout + p.stderr).strip()
        if secret:
            out = out.replace(secret, "***")
        # keep the log readable: skip the long "mode change" spam
        lines = [l for l in out.splitlines() if "mode change" not in l and "create mode" not in l]
        if lines:
            self._log("\n".join(lines))
        return p.returncode, out

    # --------------------------------------------------------------- push
    def _start(self):
        token = re.sub(r"[^\x21-\x7e]", "", self.token.get())  # strip spaces/hidden chars
        parsed = parse_repo_url(self.repo.get())
        branch = self.branch.get().strip() or "main"
        message = self.message.get().strip() or "Initial commit"

        if not self.zip_path or not os.path.isfile(self.zip_path):
            return self._log("Choose a project .zip first.", "err")
        if not parsed:
            return self._log("Invalid repository URL. Example: https://github.com/user/repo", "err")
        if not token:
            return self._log("Enter your GitHub token.", "err")
        if shutil.which("git") is None:
            return self._log("git is not installed. Install it with: sudo apt install git", "err")

        self.status.configure(text="Working...", text_color=MUTED)
        self._busy(True)
        threading.Thread(target=self._worker, daemon=True,
                         args=(self.zip_path, parsed[0], parsed[1], token, branch,
                               message, self.force.get())).start()

    def _check_access(self, owner, repo, token):
        """Validate the token + repo permissions before touching git."""
        self._log("Checking token...")
        status, data, headers = github_api("/user", token)
        if status == 0:
            raise RuntimeError(f"Network error: {data.get('message')}")
        if status == 401:
            raise RuntimeError(
                "GitHub rejected this token (401 Bad credentials).\n"
                "It is wrong, expired, or revoked. Create a new one at\n"
                "https://github.com/settings/tokens and paste it again.")
        if status != 200:
            raise RuntimeError(f"Token check failed ({status}): {(data or {}).get('message')}")
        self._log(f"Token OK - logged in as {data.get('login')}", "ok")
        scopes = headers.get("X-OAuth-Scopes") if headers else None
        if scopes is not None:
            self._log(f"Token scopes: {scopes or '(none)'}")

        status, data, _ = github_api(f"/repos/{owner}/{repo}", token)
        if status == 404:
            raise RuntimeError(
                f"Repository {owner}/{repo} not found, or this token cannot see it.\n"
                "Check the URL, make sure the repo exists, and that the token has access to it.")
        if status != 200:
            raise RuntimeError(f"Repo check failed ({status}): {(data or {}).get('message')}")
        perms = data.get("permissions") or {}
        if perms and not perms.get("push"):
            raise RuntimeError(
                "This token has no write access to the repo.\n"
                "Classic token: enable the 'repo' scope.\n"
                "Fine-grained token: Contents -> Read and write, and select this repository.")
        self._log(f"Repo OK - {data.get('full_name')} ({'private' if data.get('private') else 'public'})", "ok")

    def _worker(self, zip_path, owner, repo, token, branch, message, force):
        tmp = tempfile.mkdtemp(prefix="ghpush_")
        try:
            self._check_access(owner, repo, token)

            self._log("Extracting zip...")
            safe_extract(zip_path, tmp)
            project = find_project_root(tmp)
            if not [n for n in os.listdir(project) if n not in IGNORED_NAMES]:
                raise RuntimeError("The zip is empty.")

            if not os.path.isdir(os.path.join(project, ".git")):
                if self._run(["git", "init"], project)[0]:
                    raise RuntimeError("git init failed.")
            self._run(["git", "checkout", "-B", branch], project)

            if self._run(["git", "config", "user.name"], project)[0]:
                self._run(["git", "config", "user.name", owner], project)
            if self._run(["git", "config", "user.email"], project)[0]:
                self._run(["git", "config", "user.email",
                           f"{owner}@users.noreply.github.com"], project)

            self._run(["git", "add", "-A"], project)
            code, out = self._run(["git", "commit", "-m", message], project)
            if code and "nothing to commit" not in out:
                raise RuntimeError("Commit failed.")

            remote = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
            args = ["git", "push", remote, f"HEAD:refs/heads/{branch}"]
            if force:
                args.insert(2, "--force")
            self._log("Pushing...")
            code, out = self._run(args, project, secret=token)

            if code == 0:
                self._log(f"\nDone! https://github.com/{owner}/{repo}/tree/{branch}", "ok")
            else:
                hint = ""
                if any(k in out for k in ("non-fast-forward", "rejected", "fetch first")):
                    hint = ("\nThe repo already has commits on this branch. "
                            "Turn on 'Force push' to replace them.")
                elif "Authentication failed" in out or "403" in out:
                    hint = "\nAuthentication failed - check the token and its permissions."
                raise RuntimeError("Push failed." + hint)
        except Exception as e:
            self._log(f"\nError: {e}", "err")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self._busy(False)


if __name__ == "__main__":
    App().mainloop()