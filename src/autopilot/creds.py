"""Login credentials: asked at run time, saved in the OS keychain, or read from a .env file.
Nothing is ever written into a settings file."""
import getpass
import os
from pathlib import Path
from urllib.parse import urlparse

SERVICE = "autopilot"
EMAIL_KEY = "__email__"


def _keyring():
    """The OS password store (Windows Credential Manager, macOS Keychain, Linux
    Secret Service), or None if there isn't a usable one."""
    try:
        import keyring
        kr = keyring.get_keyring()
        name = type(kr).__module__ + "." + type(kr).__name__
        if "fail" in name.lower() or "null" in name.lower():
            return None
        return keyring
    except Exception:
        return None


def host_of(url):
    return urlparse(url).hostname or url


def load_dotenv(*files):
    """Read KEY=VALUE lines from .env files without overriding real env vars."""
    for f in files:
        f = Path(f)
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


def saved_login(site):
    """The email saved for this site in the password store, or None."""
    kr = _keyring()
    if not kr:
        return None
    host = host_of(site)
    email = kr.get_password(SERVICE + ":" + host, EMAIL_KEY)
    if email and kr.get_password(SERVICE + ":" + host, email):
        return email
    return None


def save_login(site, email, pwd):
    """Save a login in the OS password store. Returns False if there's none."""
    kr = _keyring()
    if not kr:
        return False
    host = host_of(site)
    old = kr.get_password(SERVICE + ":" + host, EMAIL_KEY)
    if old and old != email:
        try:
            kr.delete_password(SERVICE + ":" + host, old)
        except Exception:
            pass
    kr.set_password(SERVICE + ":" + host, EMAIL_KEY, email)
    kr.set_password(SERVICE + ":" + host, email, pwd)
    return True


def store_available():
    return _keyring() is not None


class Credentials:
    def __init__(self, login_cfg, site, config_path, log):
        self.cfg = login_cfg
        self.host = host_of(site)
        self.config_path = Path(config_path)
        self.config_dir = self.config_path.parent
        self.log = log
        self._cached = None

    @property
    def mode(self):
        return self.cfg["credentials"]

    def get(self):
        if self._cached:
            return self._cached
        if self.mode == "env":
            load_dotenv(self.config_path.with_suffix(".env"), self.config_dir / ".env", Path.cwd() / ".env")
            email = os.environ.get(self.cfg["email_env"])
            pwd = os.environ.get(self.cfg["password_env"])
            if not email or not pwd:
                raise RuntimeError(
                    f"credentials: env is set, but {self.cfg['email_env']} / {self.cfg['password_env']} "
                    f"weren't found. Put them in {self.config_path.with_suffix('.env').name} or .env next to your settings file:\n"
                    f"    {self.cfg['email_env']}=you@example.com\n    {self.cfg['password_env']}=your-password")
            self._cached = (email, pwd)
        elif self.mode == "saved":
            kr = _keyring()
            saved = None
            if kr:
                email = kr.get_password(SERVICE + ":" + self.host, EMAIL_KEY)
                pwd = kr.get_password(SERVICE + ":" + self.host, email) if email else None
                if email and pwd:
                    saved = (email, pwd)
            if saved:
                self.log(f"Using your saved login for {self.host} ({saved[0]}).")
                self._cached = saved
            else:
                if not kr:
                    self.log("No password store available on this computer, so the login can't be saved; "
                             "asking instead.")
                self._cached = self._ask(offer_save=bool(kr), default_save=True)
        else:
            self._cached = self._ask(offer_save=_keyring() is not None, default_save=False)
        return self._cached

    def _ask(self, offer_save, default_save):
        print(f"\nLogin for {self.host}  (typed here, not stored in any file)")
        email = ""
        while not email:
            email = input("  Email / username: ").strip()
        pwd = ""
        while not pwd:
            pwd = getpass.getpass("  Password (hidden): ")
        if offer_save:
            hint = "Y/n" if default_save else "y/N"
            ans = input(f"  Remember it in this computer's password store for next time? [{hint}] ").strip().lower()
            if (ans == "" and default_save) or ans in ("y", "yes"):
                kr = _keyring()
                kr.set_password(SERVICE + ":" + self.host, EMAIL_KEY, email)
                kr.set_password(SERVICE + ":" + self.host, email, pwd)
                print("  Saved. Use 'credentials: saved' in your settings to use it automatically,")
                print(f"  and 'autopilot forget {self.host}' to remove it.")
        print()
        return email, pwd


def forget(site_or_host):
    host = host_of(site_or_host) if "://" in site_or_host else site_or_host
    kr = _keyring()
    if not kr:
        return False, "No password store available on this computer."
    email = kr.get_password(SERVICE + ":" + host, EMAIL_KEY)
    if not email:
        return False, f"No saved login for {host}."
    for user in (email, EMAIL_KEY):
        try:
            kr.delete_password(SERVICE + ":" + host, user)
        except Exception:
            pass
    return True, f"Removed the saved login for {host} ({email})."
