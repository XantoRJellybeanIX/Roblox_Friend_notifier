"""
Roblox Friend Online Notifier (Windows)
- Add friends by Roblox username.
- Checks Roblox's documented presence endpoint every 60 seconds.
- Plays a sound and shows a Windows notification when a watched friend changes from offline to online.
- Does not ask for your Roblox password, cookie, or session token.

Use only for statuses Roblox makes available to you. Roblox APIs and policies can change;
if requests are blocked or Roblox says this use is not permitted, stop using the checker.
"""

import json
import threading
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
import winsound

import requests
from plyer import notification

APP_DIR = Path.home() / "RobloxFriendNotifier"
APP_DIR.mkdir(exist_ok=True)
WATCHLIST_FILE = APP_DIR / "watchlist.json"

USER_LOOKUP_URL = "https://users.roblox.com/v1/usernames/users"
PRESENCE_URL = "https://presence.roblox.com/v1/presence/users"
POLL_SECONDS = 60

session = requests.Session()
session.headers.update({
    "User-Agent": "RobloxFriendNotifier/1.0 (personal local notifier)",
    "Content-Type": "application/json",
})


def load_watchlist():
    try:
        return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_watchlist(data):
    WATCHLIST_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


class NotifierApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Roblox Friend Online Notifier")
        self.root.geometry("520x440")
        self.watchlist = load_watchlist()
        self.previous = {}
        self.running = False
        self.checking = False

        tk.Label(root, text="Roblox Friend Online Notifier",
                 font=("Segoe UI", 16, "bold")).pack(pady=(12, 4))
        tk.Label(root, text="Add usernames to watch. Checks every 60 seconds.",
                 font=("Segoe UI", 9)).pack()

        row = tk.Frame(root)
        row.pack(fill="x", padx=14, pady=12)
        self.username = tk.Entry(row, font=("Segoe UI", 11))
        self.username.pack(side="left", fill="x", expand=True)
        self.username.bind("<Return>", lambda _event: self.add_friend())
        tk.Button(row, text="Add friend", command=self.add_friend).pack(side="left", padx=(8, 0))

        self.listbox = tk.Listbox(root, height=12, font=("Segoe UI", 10))
        self.listbox.pack(fill="both", expand=True, padx=14)
        row2 = tk.Frame(root)
        row2.pack(fill="x", padx=14, pady=8)
        tk.Button(row2, text="Remove selected", command=self.remove_friend).pack(side="left")
        self.start_button = tk.Button(row2, text="Start monitoring", command=self.toggle_monitoring)
        self.start_button.pack(side="right")

        self.status = tk.StringVar(value=f"Watchlist saved in: {WATCHLIST_FILE}")
        tk.Label(root, textvariable=self.status, anchor="w",
                 wraplength=490, justify="left").pack(fill="x", padx=14, pady=(0, 10))
        self.refresh_list()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        for username, user_id in self.watchlist.items():
            self.listbox.insert(tk.END, f"{username}  (ID: {user_id})")

    def add_friend(self):
        username = self.username.get().strip().lstrip("@")
        if not username:
            return
        if username.casefold() in {name.casefold() for name in self.watchlist}:
            messagebox.showinfo("Already added", f"{username} is already on your watchlist.")
            return
        self.status.set(f"Looking up @{username}…")
        threading.Thread(target=self._resolve_and_add, args=(username,), daemon=True).start()

    def _resolve_and_add(self, username):
        try:
            response = session.post(USER_LOOKUP_URL,
                                    json={"usernames": [username], "excludeBannedUsers": False},
                                    timeout=15)
            response.raise_for_status()
            data = response.json().get("data", [])
            if not data:
                self.root.after(0, lambda: self.status.set(f"Could not find @{username}. Check the username."))
                return
            user = data[0]
            actual_name = user["name"]
            user_id = int(user["id"])

            def finish():
                self.watchlist[actual_name] = user_id
                save_watchlist(self.watchlist)
                self.refresh_list()
                self.username.delete(0, tk.END)
                self.status.set(f"Added @{actual_name}.")
            self.root.after(0, finish)
        except requests.RequestException as exc:
            error_text = str(exc)
            self.root.after(0, lambda error_text=error_text: self.status.set(f"Roblox lookup failed: {error_text}"))

    def remove_friend(self):
        selection = self.listbox.curselection()
        if not selection:
            return
        username = list(self.watchlist.keys())[selection[0]]
        user_id = self.watchlist[username]
        del self.watchlist[username]
        self.previous.pop(str(user_id), None)
        save_watchlist(self.watchlist)
        self.refresh_list()
        self.status.set(f"Removed @{username}.")

    def toggle_monitoring(self):
        self.running = not self.running
        self.start_button.config(text="Stop monitoring" if self.running else "Start monitoring")
        if self.running:
            self.status.set("Monitoring started. First check establishes the baseline; alerts occur on later offline → online changes.")
            self.schedule_check(0)
        else:
            self.status.set("Monitoring stopped.")

    def schedule_check(self, delay_ms=POLL_SECONDS * 1000):
        if self.running:
            self.root.after(delay_ms, self.check_presence)

    def check_presence(self):
        if not self.running or self.checking:
            return
        if not self.watchlist:
            self.status.set("Add at least one friend before monitoring.")
            self.schedule_check()
            return
        self.checking = True
        ids = list(self.watchlist.values())
        threading.Thread(target=self._fetch_presence, args=(ids,), daemon=True).start()

    def _fetch_presence(self, ids):
        try:
            response = session.post(PRESENCE_URL, json={"userIds": ids}, timeout=20)
            response.raise_for_status()
            presences = response.json().get("userPresences", [])
            by_id = {str(p.get("userId")): int(p.get("userPresenceType", 0)) for p in presences}
            self.root.after(0, lambda: self._process_presence(by_id))
        except requests.RequestException as exc:
            error_text = str(exc)
            self.root.after(0, lambda error_text=error_text: self._presence_error(error_text))

    def _process_presence(self, by_id):
        try:
            names_by_id = {str(uid): name for name, uid in self.watchlist.items()}
            alerts = []
            for uid, state in by_id.items():
                old = self.previous.get(uid)
                self.previous[uid] = state
                # Presence type 0 = offline; any non-zero type means Roblox reports a presence.
                if old == 0 and state != 0:
                    alerts.append(names_by_id.get(uid, f"User {uid}"))
            # Store a baseline for watched IDs even if the API omitted a response.
            if not self.previous:
                self.previous.update({str(uid): by_id.get(str(uid), 0) for uid in self.watchlist.values()})
            if alerts:
                for name in alerts:
                    try:
                        notification.notify(
                            title="Roblox friend is online!",
                            message=f"@{name} is now showing as online.",
                            app_name="Roblox Friend Notifier",
                            timeout=8,
                        )
                    except Exception:
                        pass
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                self.status.set("Online: " + ", ".join("@" + name for name in alerts))
            else:
                self.status.set("Last checked successfully. Next check in 60 seconds.")
        finally:
            self.checking = False
            self.schedule_check()

    def _presence_error(self, error):
        self.checking = False
        self.status.set("Presence check failed. Roblox may limit or change this endpoint. " + error[:180])
        self.schedule_check()

    def close(self):
        self.running = False
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = NotifierApp(root)
    root.mainloop()
